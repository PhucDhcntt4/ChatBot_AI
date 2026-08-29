import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from app.scripts.import_products_to_db import normalize_catalog
from app.scripts.sync_product_images import sync_product_images
from app.services.product_image_store import ProductImageStore


class _Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def execute(self, query, parameters):
        self.calls.append((query, parameters))
        return _Result(self.row)


class ProductImageDatabaseTests(unittest.TestCase):
    @staticmethod
    def _shopify_product(source_url: str):
        return [{
            "searched_sku": "ABC01",
            "product": {
                "id": "gid://shopify/Product/1",
                "legacyResourceId": "1",
                "title": "Sản phẩm ABC",
                "featuredImage": {"id": "image-1", "url": source_url},
                "images": {"nodes": []},
                "variants": {"nodes": []},
            },
        }]

    def test_normalized_catalog_keeps_downloaded_image_metadata(self):
        source_url = "https://cdn.example.test/product.jpg"
        catalog = normalize_catalog(
            [{
                "searched_sku": "ABC01",
                "product": {
                    "id": "gid://shopify/Product/1",
                    "title": "Sản phẩm ABC",
                    "status": "ACTIVE",
                    "featuredImage": {"id": "image-1", "url": source_url},
                    "images": {"nodes": []},
                    "variants": {"nodes": [{
                        "sku": "ABC01",
                        "inventoryQuantity": 1,
                        "selectedOptions": [],
                    }]},
                },
            }],
            local_images={
                source_url: {
                    "local_path": "ABC01/image-1.jpg",
                    "mime_type": "image/jpeg",
                    "checksum": "abc123",
                },
            },
        )

        image = next(iter(catalog["products"]["ABC01"]["images"].values()))
        self.assertEqual(image["local_path"], "ABC01/image-1.jpg")
        self.assertEqual(image["mime_type"], "image/jpeg")
        self.assertEqual(image["checksum"], "abc123")

    def test_product_image_store_reads_local_path_from_database(self):
        source_url = "https://cdn.example.test/product.jpg"
        with tempfile.TemporaryDirectory() as directory:
            image_root = Path(directory)
            image_path = image_root / "ABC01" / "image-1.jpg"
            image_path.parent.mkdir()
            image_path.write_bytes(b"image-data")
            connection = _Connection({
                "local_path": "ABC01/image-1.jpg",
                "mime_type": "image/jpeg",
            })

            @contextmanager
            def fake_database_connection():
                yield connection

            with patch(
                "app.services.product_image_store.database_connection",
                fake_database_connection,
            ):
                store = ProductImageStore(image_dir=image_root)
                result = store.get(source_url)

            self.assertEqual(result, (b"image-data", "image/jpeg"))
            self.assertEqual(connection.calls[0][1], (source_url,))

    def test_sync_uses_database_metadata_instead_of_manifest(self):
        source_url = "https://cdn.example.test/product.jpg"
        with tempfile.TemporaryDirectory() as directory:
            image_root = Path(directory)
            image_path = image_root / "ABC01" / "1_01.jpg"
            image_path.parent.mkdir()
            image_path.write_bytes(b"existing-image")
            metadata = {
                source_url: {
                    "local_path": "ABC01/1_01.jpg",
                    "mime_type": "image/jpeg",
                    "checksum": "checksum",
                },
            }

            with (
                patch(
                    "app.scripts.sync_product_images.PRODUCT_IMAGE_DIR",
                    image_root,
                ),
                patch(
                    "app.scripts.sync_product_images.load_database_image_metadata",
                    return_value=metadata,
                ),
                patch(
                    "app.scripts.sync_product_images.download_image",
                    side_effect=AssertionError("Không được tải lại ảnh"),
                ),
            ):
                result = sync_product_images(
                    self._shopify_product(source_url)
                )

            self.assertEqual(result["downloaded"], 0)
            self.assertEqual(result["skipped"], 1)
            self.assertEqual(result["local_images"], metadata)


if __name__ == "__main__":
    unittest.main()
