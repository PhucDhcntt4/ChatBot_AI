"""Manage recognition-only images without PostgreSQL catalog tables."""

import hashlib
import math
import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from PIL import Image, UnidentifiedImageError

from app.config import PRODUCT_IMAGE_DIR
from app.database.qdrant_catalog_repository import QdrantCatalogRepository
from app.database.qdrant_image_repository import QdrantImageRepository


MAX_IMAGE_BYTES = 20 * 1024 * 1024
CODE_PATTERN = re.compile(r"^[A-Z0-9_-]{1,100}$")
FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
}


def add_recognition_reference(
    *, product_code: str, image_bytes: bytes, color: str = "",
) -> dict:
    # Torch/OpenCLIP is intentionally imported only for an actual image
    # operation so merely starting the web application stays lightweight.
    from app.product_recognition.image_embedding_service import ImageEmbeddingService

    code = product_code.strip().upper()
    if not CODE_PATTERN.fullmatch(code):
        raise ValueError("Mã sản phẩm không hợp lệ")
    if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("Ảnh phải có dữ liệu và không vượt quá 20 MB")
    product = QdrantCatalogRepository().public_info(code)
    if not product:
        raise ValueError(f"Không tìm thấy sản phẩm {code} trong Qdrant")
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image_format = str(image.format or "").upper()
            width, height = image.size
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ValueError("File ảnh không hợp lệ") from error
    if image_format not in FORMATS:
        raise ValueError("Chỉ hỗ trợ ảnh JPEG, PNG hoặc WebP")

    extension, mime_type = FORMATS[image_format]
    checksum = hashlib.sha256(image_bytes).hexdigest()
    relative_path = Path(code) / "recognition" / f"{checksum}.{extension}"
    destination = (PRODUCT_IMAGE_DIR / relative_path).resolve()
    destination.relative_to(PRODUCT_IMAGE_DIR.resolve())
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        destination.write_bytes(image_bytes)

    embedder = ImageEmbeddingService()
    embedding = [float(value) for value in embedder.embed_bytes(image_bytes)]
    if (
        len(embedding) != QdrantImageRepository.DIMENSION
        or not all(math.isfinite(value) for value in embedding)
        or not any(value != 0 for value in embedding)
    ):
        raise ValueError("Vector ảnh không hợp lệ")
    color = color.strip()
    point_id = str(uuid5(
        NAMESPACE_URL,
        f"donghai-recognition:{code}:{checksum}:{color.casefold()}",
    ))
    now = datetime.now(timezone.utc).isoformat()
    repository = QdrantImageRepository()
    repository.ensure_collection()
    repository.upsert([{
        "id": point_id,
        "vector": embedding,
        "payload": {
            "kind": repository.KIND,
            "source_kind": "recognition",
            "product_image_id": point_id,
            "product_code": code,
            "title": product.get("product_name"),
            "product_type": product.get("product_type"),
            "color": color,
            "is_active": True,
            "local_path": relative_path.as_posix(),
            "source_url": f"recognition://{code}/{checksum}",
            "mime_type": mime_type,
            "width": width,
            "height": height,
            "created_at": now,
            "updated_at": now,
            "model_name": embedder.model_name,
            "pretrained_name": embedder.pretrained_name,
            "image_checksum": checksum,
        },
    }])
    return {
        "product_code": code,
        "product_image_id": point_id,
        "vector_id": point_id,
        "backend": "qdrant",
    }
