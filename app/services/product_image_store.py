from pathlib import Path

from app.config import PRODUCT_IMAGE_DIR
from app.database.connection import database_connection


class ProductImageStore:
    def __init__(
        self,
        image_dir: str | Path = PRODUCT_IMAGE_DIR,
    ) -> None:
        self.image_dir = Path(image_dir)
        self._metadata_cache: dict[str, dict[str, str]] = {}

    def reload(self) -> None:
        self._metadata_cache.clear()

    def _metadata(self, source_url: str) -> dict[str, str] | None:
        cached = self._metadata_cache.get(source_url)
        if cached:
            return cached

        try:
            with database_connection() as connection:
                row = connection.execute(
                    """
                    SELECT local_path, mime_type
                    FROM product_images
                    WHERE source_url = %s
                      AND is_active = TRUE
                      AND local_path IS NOT NULL
                      AND local_path <> ''
                    ORDER BY updated_at DESC, id DESC
                    LIMIT 1
                    """,
                    (source_url,),
                ).fetchone()
        except Exception:
            return None

        if not row:
            return None

        metadata = {
            "local_path": str(row["local_path"]),
            "mime_type": str(row["mime_type"] or "image/jpeg"),
        }
        self._metadata_cache[source_url] = metadata
        return metadata

    def get(
        self,
        source_url: str,
    ) -> tuple[bytes, str] | None:
        item = self._metadata(source_url)

        if not item:
            return None

        relative_path = item.get("local_path")
        mime_type = str(
            item.get("mime_type") or "image/jpeg"
        ).strip().lower()

        if mime_type not in {
            "image/jpeg",
            "image/png",
            "image/webp",
        }:
            return None
        if not relative_path:
            return None

        image_path = (
            self.image_dir / str(relative_path)
        ).resolve()

        image_root = self.image_dir.resolve()

        try:
            image_path.relative_to(image_root)
        except ValueError:
            return None

        if not image_path.is_file():
            return None

        try:
            image_bytes = image_path.read_bytes()
        except OSError:
            return None

        if not image_bytes:
            return None

        return image_bytes, str(mime_type)
