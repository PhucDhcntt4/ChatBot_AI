import logging
import math
from time import perf_counter
from urllib.parse import quote

import httpx # type: ignore

from app.config import (
    IMAGE_QDRANT_URL,
    IMAGE_QDRANT_API_KEY,
    IMAGE_QDRANT_COLLECTION,
)


logger = logging.getLogger("uvicorn.error")


class QdrantImageRepository:
    DIMENSION = 512
    KIND = "bot_product_image"
    MAX_SEARCH_CANDIDATES = 4096

    def __init__(self, collection: str | None = None):
        collection_name = (collection or IMAGE_QDRANT_COLLECTION).strip()
        if not IMAGE_QDRANT_URL or not collection_name:
            raise ValueError("Thiếu cấu hình Qdrant ảnh")
        url = httpx.URL(IMAGE_QDRANT_URL)
        if (
            url.scheme not in {"http", "https"} or not url.host
            or url.username or url.password or url.query or url.fragment
        ):
            raise ValueError("URL Qdrant ảnh không hợp lệ")

        self.path = "/collections/" + quote(
            collection_name, safe=""
        )

    def request(self, method, path, **kwargs):
        headers = {}
        if IMAGE_QDRANT_API_KEY:
            headers["api-key"] = IMAGE_QDRANT_API_KEY

        with httpx.Client(
            timeout=httpx.Timeout(30, connect=5),
            headers=headers,
            follow_redirects=False,
        ) as client:
            response = client.request(
                method,
                IMAGE_QDRANT_URL + path,
                **kwargs,
            )
            response.raise_for_status()
            body = response.json()

        if not isinstance(body, dict) or body.get("status") != "ok":
            raise RuntimeError("Qdrant trả dữ liệu không hợp lệ")

        return body["result"]

    def ready(self):
        info = self.request("GET", self.path)
        self._validate_collection(info)
        if info.get("status") not in {"green", "yellow"}:
            raise RuntimeError("Collection ảnh Qdrant chưa sẵn sàng")
        return info

    @classmethod
    def _validate_collection(cls, info):
        vectors = info["config"]["params"]["vectors"]
        if (
            vectors.get("size") != cls.DIMENSION
            or vectors.get("distance") != "Cosine"
        ):
            raise ValueError(
                "Collection ảnh phải có vector 512 chiều, distance=Cosine"
            )

    def ensure_collection(self):
        try:
            info = self.request("GET", self.path)
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 404:
                raise

            self.request(
                "PUT",
                self.path,
                json={
                    "vectors": {
                        "size": self.DIMENSION,
                        "distance": "Cosine",
                    }
                },
            )
            info = self.request("GET", self.path)

        self._validate_collection(info)

        for field in (
            "kind",
            "model_name",
            "pretrained_name",
            "product_code",
            "product_type",
        ):
            self.request(
                "PUT",
                self.path + "/index",
                params={"wait": "true"},
                json={
                    "field_name": field,
                    "field_schema": "keyword",
                },
            )

    def upsert(self, points):
        if not points:
            return

        self.request(
            "PUT",
            self.path + "/points",
            params={"wait": "true"},
            json={"points": points},
        )

    def point_metadata(self):
        """Return all image points owned by this application."""
        conditions = [
            {"key": "kind", "match": {"value": self.KIND}},
        ]
        offset = None
        seen_offsets = set()
        points = {}

        while True:
            query = {
                "filter": {"must": conditions},
                "limit": 256,
                "with_payload": True,
                "with_vector": False,
            }
            if offset is not None:
                query["offset"] = offset

            result = self.request(
                "POST",
                self.path + "/points/scroll",
                json=query,
            )
            page = result.get("points")
            if not isinstance(page, list):
                raise RuntimeError("Qdrant trả danh sách point không hợp lệ")

            for point in page:
                raw_id = point["id"]
                point_id = int(raw_id) if str(raw_id).isdigit() else str(raw_id)
                if point_id in points:
                    raise RuntimeError("Qdrant trả trùng point khi đồng bộ")
                payload = point.get("payload") or {}
                if payload.get("kind") != self.KIND:
                    raise RuntimeError("Qdrant trả point không đúng phạm vi đồng bộ")
                points[point_id] = payload

            next_offset = result.get("next_page_offset")
            if next_offset is None:
                return points
            offset_key = str(next_offset)
            if not page or offset_key in seen_offsets:
                raise RuntimeError("Qdrant trả cursor lặp khi đồng bộ")
            seen_offsets.add(offset_key)
            offset = next_offset

    def delete_points(self, point_ids):
        ids = sorted(set(point_ids), key=str)
        for start in range(0, len(ids), 256):
            self.request(
                "POST",
                self.path + "/points/delete",
                params={"wait": "true"},
                json={"points": ids[start:start + 256]},
            )

    def payload_by_id(self, point_id):
        result = self.request(
            "POST",
            self.path + "/points",
            json={
                "ids": [point_id],
                "with_payload": True,
                "with_vector": False,
            },
        )
        if not isinstance(result, list) or len(result) > 1:
            raise RuntimeError("Qdrant trả metadata ảnh không hợp lệ")
        return (result[0].get("payload") or {}) if result else None

    def images_for_product(self, product_code, source_kind=None):
        code = str(product_code or "").strip().upper()
        values = []
        for point_id, payload in self.point_metadata().items():
            if str(payload.get("product_code") or "").upper() != code:
                continue
            if source_kind and payload.get("source_kind") != source_kind:
                continue
            values.append({"id": point_id, **payload})
        return values

    def search(
        self,
        embedding,
        model_name,
        pretrained_name,
        product_type=None,
        limit=10,
    ):
        started = perf_counter()
        if (
            len(embedding) != self.DIMENSION
            or not all(math.isfinite(value) for value in embedding)
            or not any(value != 0 for value in embedding)
        ):
            raise ValueError("Vector ảnh phải có 512 giá trị hữu hạn và khác vector 0")

        if limit <= 0:
            return []

        product_types = (
            [product_type]
            if isinstance(product_type, str)
            else list(product_type or [])
        )

        conditions = [
            {"key": "kind", "match": {"value": self.KIND}},
            {"key": "model_name", "match": {"value": model_name}},
            {
                "key": "pretrained_name",
                "match": {"value": pretrained_name},
            },
        ]

        if product_types:
            conditions.append({
                "key": "product_type",
                "match": {"any": product_types},
            })

        # Đọc thêm ứng viên nếu một số ảnh đã bị tắt/xóa trong PostgreSQL.
        batch_size = max(64, limit * 2)
        offset = 0
        results = []
        seen = set()

        while len(results) < limit:
            if offset >= self.MAX_SEARCH_CANDIDATES:
                raise RuntimeError(
                    "Quá nhiều vector ảnh không hợp lệ; cần đồng bộ lại Qdrant"
                )
            response = self.request(
                "POST",
                self.path + "/points/query",
                json={
                    "query": embedding,
                    "filter": {"must": conditions},
                    "limit": batch_size,
                    "offset": offset,
                    "with_payload": True,
                    "with_vector": False,
                },
            )
            hits = response["points"]

            if not hits:
                break

            ids = [str(hit["id"]) for hit in hits]
            if any(point_id in seen for point_id in ids) or len(set(ids)) != len(ids):
                raise RuntimeError("Qdrant trả lặp ứng viên; hãy thử lại")
            seen.update(ids)

            for hit in hits:
                payload = hit.get("payload") or {}
                if payload.get("kind") != self.KIND:
                    continue
                if payload.get("is_active") is False:
                    continue
                if not payload.get("product_code") or not payload.get("image_checksum"):
                    continue
                if product_types and payload.get("product_type") not in product_types:
                    continue
                score = float(hit["score"])
                if not math.isfinite(score):
                    raise RuntimeError("Qdrant trả điểm tương đồng không hợp lệ")
                row = dict(payload)
                row["vector_id"] = hit["id"]
                row["product_image_id"] = (
                    payload.get("product_image_id") or hit["id"]
                )
                row["similarity"] = score
                results.append(row)

                if len(results) >= limit:
                    break

            if len(hits) < batch_size:
                break

            offset += len(hits)

        logger.info(
            "IMAGE VECTOR backend=qdrant candidates=%s scanned=%s time=%.3fs",
            len(results), len(seen), perf_counter() - started,
        )
        return results
