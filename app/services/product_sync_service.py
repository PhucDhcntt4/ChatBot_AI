import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from redis import Redis  # type: ignore

from app.database.redis_connection import redis_client


@dataclass
class SyncJob:
    id: str
    skus: list[str]
    status: str = "queued"
    current_sku: str | None = None
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    phase: str = "queued"
    phase_label: str = "Đang chờ worker xử lý"
    completed_units: int = 0
    messages: list[str] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    claimed_at: str | None = None
    heartbeat_at: str | None = None
    attempts: int = 0

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id, "status": self.status, "skus": self.skus,
            "total": len(self.skus), "current_sku": self.current_sku,
            "processed": self.processed, "succeeded": self.succeeded,
            "failed": self.failed, "phase": self.phase,
            "phase_label": self.phase_label,
            "completed_units": self.completed_units,
            "total_units": len(self.skus) * 4 + 1,
            "messages": self.messages[-100:], "results": self.results,
            "created_at": self.created_at, "completed_at": self.completed_at,
            "claimed_at": self.claimed_at,
            "heartbeat_at": self.heartbeat_at,
            "attempts": self.attempts,
        }


class ProductSyncManager:
    """Kho job Redis dùng chung giữa API và worker độc lập."""

    def __init__(
        self,
        client: Redis = redis_client,
    ) -> None:
        self.redis = client
        self.queue_key = os.getenv(
            "REDIS_SYNC_QUEUE",
            "donghai:sync:queue",
        )
        self.processing_key = os.getenv(
            "REDIS_SYNC_PROCESSING",
            "donghai:sync:processing",
        )
        self.job_prefix = os.getenv(
            "REDIS_SYNC_JOB_PREFIX",
            "donghai:sync:job",
        )
        self.cancel_prefix = os.getenv(
            "REDIS_SYNC_CANCEL_PREFIX",
            "donghai:sync:cancel",
        )
        self.job_ttl = int(
            os.getenv("REDIS_SYNC_JOB_TTL_SECONDS", "86400")
        )
        self.block_seconds = int(
            os.getenv("REDIS_SYNC_BLOCK_SECONDS", "5")
        )
        self.stale_seconds = int(
            os.getenv("REDIS_SYNC_STALE_SECONDS", "1800")
        )
        self.max_attempts = int(
            os.getenv("REDIS_SYNC_MAX_ATTEMPTS", "3")
        )

    def _job_key(self, job_id: str) -> str:
        if (
            not job_id
            or any(
                character not in "0123456789abcdef"
                for character in job_id
            )
        ):
            raise ValueError("Mã tác vụ không hợp lệ.")
        return f"{self.job_prefix}:{job_id}"

    def _cancel_key(self, job_id: str) -> str:
        # Dùng cùng quy tắc kiểm tra ID với khóa job để không cho phép
        # người dùng tạo Redis key tùy ý qua endpoint quản trị.
        self._job_key(job_id)
        return f"{self.cancel_prefix}:{job_id}"

    @staticmethod
    def normalize_skus(values: list[str]) -> list[str]:
        # Giữ phép chuẩn hóa nhỏ tại đây để API không phải import toàn bộ
        # product_import_service (module đó nạp cả pipeline ảnh/embedding).
        values = [value.strip().upper() for value in values]
        return list(dict.fromkeys(value for value in values if value))

    def _save(self, job: SyncJob) -> None:
        self.redis.set(
            self._job_key(job.id),
            json.dumps(asdict(job), ensure_ascii=False),
            ex=self.job_ttl,
        )

    def _load(self, job_id: str) -> SyncJob | None:
        try:
            value = self.redis.get(self._job_key(job_id))
        except ValueError:
            return None
        if not value:
            return None
        try:
            return SyncJob(**json.loads(value))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def create(
        self,
        skus: list[str],
        *,
        max_skus: int | None = 1000,
    ) -> SyncJob:
        normalized = self.normalize_skus(skus)
        if not normalized:
            raise ValueError("Danh sách không có mã sản phẩm hợp lệ.")
        if max_skus is not None and len(normalized) > max_skus:
            raise ValueError(
                f"Mỗi lần chỉ được import tối đa {max_skus:,} mã."
                .replace(",", ".")
            )
        job = SyncJob(id=uuid.uuid4().hex, skus=normalized)
        with self.redis.pipeline() as pipeline:
            pipeline.set(
                self._job_key(job.id),
                json.dumps(asdict(job), ensure_ascii=False),
                ex=self.job_ttl,
            )
            # LPUSH + BRPOPLPUSH giữ thứ tự FIFO và đồng thời chuyển
            # job sang processing khi worker nhận.
            pipeline.lpush(self.queue_key, job.id)
            pipeline.execute()
        return job

    def get(self, job_id: str) -> dict[str, Any] | None:
        job = self._load(job_id)
        return job.public() if job else None

    def cancel(self, job_id: str) -> dict[str, Any] | None:
        job = self._load(job_id)
        if not job:
            return None
        if job.status in {
            "completed", "completed_with_errors", "failed", "cancelled"
        }:
            return job.public()

        self.redis.set(self._cancel_key(job.id), "1", ex=self.job_ttl)
        now = datetime.now(timezone.utc).isoformat()
        if job.status == "queued":
            self.redis.lrem(self.queue_key, 0, job.id)
            job.status = "cancelled"
            job.phase = "cancelled"
            job.phase_label = "Đã dừng đồng bộ"
            job.current_sku = None
            job.completed_at = now
            job.messages.append("Tác vụ đã được dừng trước khi worker xử lý.")
        else:
            job.status = "cancel_requested"
            job.phase = "cancel_requested"
            job.phase_label = "Đang dừng tại bước an toàn gần nhất"
            job.messages.append("Đã tiếp nhận yêu cầu dừng đồng bộ.")
        self._save(job)
        return job.public()

    def _is_cancel_requested(self, job_id: str) -> bool:
        try:
            return bool(self.redis.get(self._cancel_key(job_id)))
        except ValueError:
            return False

    def _finish_cancelled(self, job_id: str) -> bool:
        if not self._is_cancel_requested(job_id):
            return False
        job = self._load(job_id)
        if not job:
            return True
        if job.status != "cancelled":
            job.status = "cancelled"
            job.phase = "cancelled"
            job.phase_label = "Đã dừng đồng bộ"
            job.current_sku = None
            job.completed_at = datetime.now(timezone.utc).isoformat()
            job.messages.append("Worker đã dừng tác vụ tại điểm an toàn.")
            self._save(job)
        return True

    def claim_next(self) -> str | None:
        while True:
            job_id = self.redis.brpoplpush(
                self.queue_key,
                self.processing_key,
                timeout=self.block_seconds,
            )
            if not job_id:
                return None

            job = self._load(job_id)
            if not job or job.status != "queued":
                self.acknowledge(job_id)
                continue

            now = datetime.now(timezone.utc).isoformat()
            job.status = "claimed"
            job.phase = "claimed"
            job.phase_label = "Worker đã nhận tác vụ"
            job.claimed_at = now
            job.heartbeat_at = now
            job.attempts += 1
            self._save(job)
            return job.id

    def acknowledge(self, job_id: str) -> None:
        """Xóa job đã kết thúc khỏi danh sách đang xử lý."""
        self.redis.lrem(self.processing_key, 0, job_id)

    def heartbeat(self, job: SyncJob) -> None:
        """Ghi nhận worker vẫn đang xử lý job."""
        job.heartbeat_at = datetime.now(timezone.utc).isoformat()
        self._save(job)

    def recover_stale_jobs(self) -> int:
        """Đưa job bị treo về queue hoặc đánh dấu lỗi khi quá số lần thử."""
        recovered = 0
        now = datetime.now(timezone.utc)
        job_ids = self.redis.lrange(self.processing_key, 0, -1)

        for job_id in job_ids:
            job = self._load(job_id)
            if not job:
                self.acknowledge(job_id)
                continue

            if self._is_cancel_requested(job_id):
                self._finish_cancelled(job_id)
                self.acknowledge(job_id)
                continue

            timestamp = job.heartbeat_at or job.claimed_at or job.created_at
            try:
                last_update = datetime.fromisoformat(timestamp)
                if last_update.tzinfo is None:
                    last_update = last_update.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                last_update = datetime.fromtimestamp(0, tz=timezone.utc)

            if (now - last_update).total_seconds() < self.stale_seconds:
                continue

            self.acknowledge(job_id)
            if job.attempts >= self.max_attempts:
                job.status = "failed"
                job.phase = "failed"
                job.phase_label = "Tác vụ thất bại sau nhiều lần thử"
                job.current_sku = None
                job.completed_at = now.isoformat()
                job.messages.append(
                    "Tác vụ bị dừng quá lâu và đã vượt số lần thử lại."
                )
                self._save(job)
                continue

            # Chạy lại toàn bộ job; các bước ghi catalog/database là upsert,
            # còn ảnh và embedding đã tồn tại sẽ được bỏ qua.
            job.status = "queued"
            job.phase = "queued"
            job.phase_label = "Tác vụ được đưa lại vào hàng chờ"
            job.current_sku = None
            job.processed = 0
            job.succeeded = 0
            job.failed = 0
            job.completed_units = 0
            job.results = []
            job.claimed_at = None
            job.heartbeat_at = None
            job.completed_at = None
            job.messages.append("Worker cũ ngừng phản hồi; tác vụ được thử lại.")
            self._save(job)
            self.redis.lpush(self.queue_key, job.id)
            recovered += 1

        return recovered

    def _message(self, job: SyncJob, message: str) -> None:
        job.messages.append(message)
        job.heartbeat_at = datetime.now(timezone.utc).isoformat()
        self._save(job)

    def _phase(self, job: SyncJob, phase: str, label: str) -> None:
        job.phase, job.phase_label = phase, label
        job.heartbeat_at = datetime.now(timezone.utc).isoformat()
        self._save(job)

    def run(self, job_id: str) -> None:
        # Các import nặng chỉ được nạp trong process worker.
        from app.scripts.build_product_image_embeddings import main as build_embeddings
        from app.scripts.sync_product_images import sync_product_images
        from app.services.product_import_service import (
            find_products_by_sku, import_products_to_database, save_product,
        )

        job = self._load(job_id)
        if not job:
            self.acknowledge(job_id)
            raise ValueError(f"Không tìm thấy tác vụ {job_id}.")
        if self._finish_cancelled(job_id):
            self.acknowledge(job_id)
            return
        if job.status not in {"queued", "claimed"}:
            self.acknowledge(job_id)
            return
        job.status = "running"
        self.heartbeat(job)
        imported: list[dict[str, Any]] = []
        try:
            for index, sku in enumerate(job.skus):
                if self._finish_cancelled(job_id):
                    return
                job.current_sku = sku
                self._message(job, f"Đang lấy {sku} từ Shopify…")
                try:
                    self._phase(job, "shopify", f"Đang lấy {sku} từ Shopify")
                    products = find_products_by_sku(sku)
                    if self._finish_cancelled(job_id):
                        return
                    self.heartbeat(job)
                    if not products:
                        raise ValueError("Không tìm thấy sản phẩm ACTIVE.")
                    job.completed_units = index * 4 + 1
                    self._save(job)

                    self._phase(job, "catalog", f"Đang lưu catalog {sku}")
                    for product in products:
                        save_product(product)
                    if self._finish_cancelled(job_id):
                        return
                    self.heartbeat(job)
                    job.completed_units = index * 4 + 2
                    self._save(job)

                    self._phase(job, "images", f"Đang tải ảnh {sku}")
                    image_result = sync_product_images(products, remove_stale=False)
                    if self._finish_cancelled(job_id):
                        return
                    self.heartbeat(job)
                    job.completed_units = index * 4 + 3
                    self._save(job)

                    self._phase(job, "database", f"Đang import database {sku}")
                    sync_run_id = import_products_to_database(products)
                    if self._finish_cancelled(job_id):
                        return
                    self.heartbeat(job)
                    job.completed_units = index * 4 + 4
                    imported.extend(products)
                    job.results.append({
                        "sku": sku, "success": True,
                        "shopify_products": len(products),
                        "downloaded": image_result["downloaded"],
                        "skipped_images": image_result["skipped"],
                        "failed_images": image_result["failed"],
                        "sync_run_id": sync_run_id,
                    })
                    job.succeeded += 1
                    self._message(job, f"Đã import {sku} thành công.")
                except Exception as error:
                    job.failed += 1
                    job.results.append({"sku": sku, "success": False, "error": str(error)})
                    self._message(job, f"Lỗi {sku}: {error}")
                finally:
                    job.processed += 1
                    job.completed_units = max(job.completed_units, (index + 1) * 4)
                    self._save(job)

            if imported:
                if self._finish_cancelled(job_id):
                    return
                self._phase(job, "embedding", "Đang tạo embedding cho ảnh mới")
                self._message(job, "Đang tạo embedding cho ảnh mới…")
                try:
                    result = build_embeddings()
                    if self._finish_cancelled(job_id):
                        return
                    self.heartbeat(job)
                    self._message(
                        job,
                        "Embedding hoàn tất: "
                        f"created={result.get('created', 0)}, "
                        f"skipped={result.get('skipped', 0)}, "
                        f"failed={result.get('failed', 0)}.",
                    )
                except Exception as error:
                    self._message(job, f"Cảnh báo embedding: {error}")

            job.completed_units = len(job.skus) * 4 + 1
            job.current_sku = None
            job.status = "completed" if job.failed == 0 else "completed_with_errors"
            job.phase = job.status
            job.phase_label = "Đã đồng bộ hoàn tất" if job.failed == 0 else "Hoàn tất nhưng có mã bị lỗi"
            job.completed_at = datetime.now(timezone.utc).isoformat()
            self._save(job)
        except Exception as error:
            job.status, job.phase = "failed", "failed"
            job.phase_label = "Worker gặp lỗi"
            job.current_sku = None
            job.completed_at = datetime.now(timezone.utc).isoformat()
            job.messages.append(f"Worker gặp lỗi: {error}")
            self._save(job)
            raise
        finally:
            self.acknowledge(job_id)


product_sync_manager = ProductSyncManager()
