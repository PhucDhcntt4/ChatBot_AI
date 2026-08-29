import json
import hashlib
import mimetypes
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from psycopg.errors import UndefinedTable

from app.config import (
    PRODUCTS_PATH,
    PRODUCT_IMAGE_DIR,
)
from app.database.connection import database_connection


ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}

EXTENSIONS_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def safe_name(value: Any) -> str:
    text = str(value or "").strip().upper()

    cleaned = re.sub(
        r"[^A-Z0-9_-]+",
        "_",
        text,
    ).strip("_")

    return cleaned or "UNKNOWN"


def product_code(
    wrapper: dict[str, Any],
    product: dict[str, Any],
) -> str:
    searched_sku = str(
        wrapper.get("searched_sku") or ""
    ).strip()

    if searched_sku:
        return safe_name(searched_sku)

    variants = (
        product
        .get("variants", {})
        .get("nodes", [])
    )

    for variant in variants:
        sku = str(
            variant.get("sku") or ""
        ).strip()

        if sku:
            return safe_name(sku)

    return "UNKNOWN"


def image_extension(
    image_url: str,
    mime_type: str,
) -> str:
    known_extension = EXTENSIONS_BY_MIME.get(
        mime_type
    )

    if known_extension:
        return known_extension

    suffix = Path(
        urlparse(image_url).path
    ).suffix.lower()

    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return ".jpg" if suffix == ".jpeg" else suffix

    guessed = mimetypes.guess_extension(mime_type)

    return guessed or ".jpg"


def load_products() -> list[dict[str, Any]]:
    data = json.loads(
        PRODUCTS_PATH.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(data, list):
        raise ValueError(
            "products.json phải là một danh sách"
        )

    return [
        item
        for item in data
        if isinstance(item, dict)
    ]


def load_database_image_metadata(
    source_urls: set[str],
) -> dict[str, dict[str, str]]:
    """Lấy ánh xạ URL → ảnh local từ PostgreSQL."""

    if not source_urls:
        return {}

    try:
        with database_connection() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT ON (source_url)
                       source_url, local_path, mime_type, checksum
                FROM product_images
                WHERE source_url = ANY(%s)
                  AND local_path IS NOT NULL
                  AND local_path <> ''
                ORDER BY source_url, is_active DESC, updated_at DESC, id DESC
                """,
                (list(source_urls),),
            ).fetchall()
    except UndefinedTable:
        # Lần đồng bộ đầu tiên có thể chạy trước khi schema catalog được tạo.
        rows = []

    return {
        str(row["source_url"]): {
            "local_path": str(row["local_path"]),
            "mime_type": str(row["mime_type"] or "image/jpeg"),
            "checksum": str(row["checksum"] or ""),
        }
        for row in rows
        if row.get("source_url") and row.get("local_path")
    }


def existing_local_path(
    metadata: dict[str, str] | None,
) -> Path | None:
    if not metadata or not metadata.get("local_path"):
        return None

    image_root = PRODUCT_IMAGE_DIR.resolve()
    image_path = (
        PRODUCT_IMAGE_DIR / metadata["local_path"]
    ).resolve()
    try:
        image_path.relative_to(image_root)
    except ValueError:
        return None
    return image_path if image_path.is_file() else None


def collect_images(
    product: dict[str, Any],
) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []

    featured_image = product.get(
        "featuredImage"
    )

    if isinstance(featured_image, dict):
        images.append(featured_image)

    product_images = (
        product
        .get("images", {})
        .get("nodes", [])
    )

    for image in product_images:
        if not isinstance(image, dict):
            continue

        image_url = image.get("url")

        if not image_url:
            continue

        if any(
            existing.get("url") == image_url
            for existing in images
        ):
            continue

        images.append(image)

    return images


def download_image(
    image_url: str,
) -> tuple[bytes, str]:
    response = requests.get(
        image_url,
        timeout=30,
    )

    response.raise_for_status()

    mime_type = response.headers.get(
        "Content-Type",
        "image/jpeg",
    ).split(";")[0].strip().lower()

    if mime_type not in ALLOWED_MIME_TYPES:
        raise ValueError(
            f"Định dạng ảnh không hỗ trợ: {mime_type}"
        )

    if not response.content:
        raise ValueError("Ảnh không có dữ liệu")

    if len(response.content) > 20 * 1024 * 1024:
        raise ValueError("Ảnh vượt quá 20 MB")

    return response.content, mime_type


def sync_product_images(
    products: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Tải ảnh catalog và trả metadata để importer ghi PostgreSQL."""

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(
            encoding="utf-8",
            errors="replace",
        )

    if products is None:
        products = load_products()

    PRODUCT_IMAGE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    downloaded = 0
    skipped = 0
    failed = 0
    active_urls: set[str] = set()
    tasks: list[tuple[str, str, Path, int, dict[str, Any]]] = []

    for wrapper in products:
        nested_product = wrapper.get("product")

        product = (
            nested_product
            if isinstance(nested_product, dict)
            else wrapper
        )

        code = product_code(
            wrapper=wrapper,
            product=product,
        )

        shopify_product_id = safe_name(
            product.get("legacyResourceId")
            or product.get("id")
        )

        image_items = collect_images(product)

        product_dir = PRODUCT_IMAGE_DIR / code

        product_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        for position, image in enumerate(
            image_items,
            start=1,
        ):
            image_url = str(
                image.get("url") or ""
            ).strip()

            if not image_url:
                continue

            active_urls.add(image_url)
            tasks.append((
                code,
                shopify_product_id,
                product_dir,
                position,
                image,
            ))

    database_metadata = load_database_image_metadata(active_urls)
    local_images: dict[str, dict[str, str]] = {}

    for code, shopify_product_id, product_dir, position, image in tasks:
        image_url = str(image.get("url") or "").strip()
        existing = database_metadata.get(image_url)
        existing_path = existing_local_path(existing)
        if existing and existing_path:
            local_images[image_url] = existing
            skipped += 1
            continue

        try:
            image_bytes, mime_type = download_image(image_url)

            extension = image_extension(
                image_url=image_url,
                mime_type=mime_type,
            )

            filename = (
                f"{shopify_product_id}_"
                f"{position:02d}{extension}"
            )

            image_path = product_dir / filename
            image_path.write_bytes(image_bytes)

            relative_path = image_path.relative_to(
                PRODUCT_IMAGE_DIR
            )

            local_images[image_url] = {
                "local_path": relative_path.as_posix(),
                "mime_type": mime_type,
                "checksum": hashlib.sha256(image_bytes).hexdigest(),
            }

            downloaded += 1

            print(
                f"Downloaded: {code} -> "
                f"{relative_path}"
            )

        except Exception as error:
            failed += 1

            print(
                f"Failed: {code} | "
                f"{image_url} | {error}"
            )

    print("\n========== HOÀN THÀNH ==========")
    print(f"Đã tải: {downloaded}")
    print(f"Đã tồn tại: {skipped}")
    print(f"Lỗi: {failed}")
    print("Metadata ảnh sẽ được lưu trực tiếp vào PostgreSQL.")

    return {
        "downloaded": downloaded,
        "skipped": skipped,
        "failed": failed,
        "local_images": local_images,
    }


def main() -> None:
    products = load_products()
    result = sync_product_images(products)

    # Không còn manifest trung gian: CLI cũng phải ghi metadata ảnh vào DB.
    from app.services.product_import_service import (
        import_products_to_database,
    )
    sync_run_id = import_products_to_database(
        products,
        local_images=result["local_images"],
    )
    print(f"Đã lưu metadata ảnh vào PostgreSQL: sync_run_id={sync_run_id}")


if __name__ == "__main__":
    main()
