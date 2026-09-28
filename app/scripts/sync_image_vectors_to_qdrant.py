"""Build image vectors from Qdrant catalog metadata and local image files."""

import math
from uuid import NAMESPACE_URL, uuid5

from app.config import PRODUCT_IMAGE_DIR
from app.database.qdrant_catalog_repository import QdrantCatalogRepository
from app.database.qdrant_image_repository import QdrantImageRepository
from app.product_recognition.image_embedding_service import ImageEmbeddingService


BATCH_SIZE = 64


def _point_id(record: dict) -> str:
    identity = "|".join((
        str(record.get("product_code") or "").strip().upper(),
        str(record.get("source_url") or "").strip(),
        str(record.get("color") or "").strip().casefold(),
    ))
    return str(uuid5(NAMESPACE_URL, "donghai-image:" + identity))


def _payload(record, repository, service, checksum, point_id):
    return {
        "kind": repository.KIND,
        "source_kind": "catalog",
        "product_image_id": point_id,
        "product_code": record.get("product_code"),
        "title": record.get("title"),
        "product_type": record.get("product_type"),
        "color": record.get("color") or "",
        "image_order": record.get("image_order"),
        "is_featured": bool(record.get("is_featured")),
        "is_active": True,
        "local_path": record.get("local_path"),
        "source_url": record.get("source_url"),
        "mime_type": record.get("mime_type"),
        "model_name": service.model_name,
        "pretrained_name": service.pretrained_name,
        "image_checksum": checksum,
    }


def _payload_matches(current, expected):
    return all(current.get(key) == value for key, value in expected.items())


def main(product_codes: list[str] | tuple[str, ...] | None = None) -> dict[str, int]:
    codes = tuple(dict.fromkeys(
        str(code).strip().upper()
        for code in (product_codes or []) if str(code).strip()
    ))
    full_sync = not codes
    catalog = QdrantCatalogRepository()
    catalog.ready()
    repository = QdrantImageRepository()
    repository.ensure_collection()
    service = ImageEmbeddingService()
    records = catalog.image_records(codes)
    existing = repository.point_metadata()
    active_ids = {_point_id(record) for record in records}
    if full_sync:
        stale_ids = [
            point_id for point_id, payload in existing.items()
            if payload.get("source_kind") != "recognition"
            and str(point_id) not in active_ids
        ]
    else:
        code_set = set(codes)
        stale_ids = [
            point_id for point_id, payload in existing.items()
            if payload.get("source_kind") == "catalog"
            and str(payload.get("product_code") or "").upper() in code_set
            and str(point_id) not in active_ids
        ]
    repository.delete_points(stale_ids)

    synced = unchanged = failed = 0
    points = []

    def flush():
        nonlocal synced
        if not points:
            return
        repository.upsert(list(points))
        synced += len(points)
        print(f"QDRANT IMAGE UPSERT [{synced}]", flush=True)
        points.clear()

    print(
        "QDRANT IMAGE PLAN "
        f"scope={'all' if full_sync else str(len(codes)) + ' products'} "
        f"active={len(records)} existing={len(existing)} delete={len(stale_ids)}",
        flush=True,
    )
    for record in records:
        point_id = _point_id(record)
        image_path = (PRODUCT_IMAGE_DIR / str(record["local_path"])).resolve()
        try:
            image_path.relative_to(PRODUCT_IMAGE_DIR.resolve())
            image_bytes = image_path.read_bytes()
            checksum = service.checksum(image_bytes)
            expected = _payload(record, repository, service, checksum, point_id)
            current = existing.get(point_id, {})
            if _payload_matches(current, expected):
                unchanged += 1
                continue
            vector = [float(value) for value in service.embed_bytes(image_bytes)]
            if (
                len(vector) != repository.DIMENSION
                or not all(math.isfinite(value) for value in vector)
                or not any(value != 0 for value in vector)
            ):
                raise ValueError("Vector ảnh không hợp lệ")
            points.append({"id": point_id, "vector": vector, "payload": expected})
            if len(points) >= BATCH_SIZE:
                flush()
        except Exception as error:
            failed += 1
            print(f"QDRANT IMAGE FAILED id={point_id} error={error}", flush=True)
    flush()
    print(
        "QDRANT IMAGE COMPLETE "
        f"synced={synced} unchanged={unchanged} failed={failed} "
        f"deleted={len(stale_ids)} total={len(records)}",
        flush=True,
    )
    return {
        "synced": synced,
        "unchanged": unchanged,
        "failed": failed,
        "deleted": len(stale_ids),
        "total": len(records),
    }


if __name__ == "__main__":
    print(main())
