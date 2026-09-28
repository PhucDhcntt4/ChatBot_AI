import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.catalog_normalization import normalize_catalog
from app.scripts.sync_product_images import sync_product_images
from app.services.product_image_store import ProductImageStore


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

    def test_product_image_store_reads_local_path_from_qdrant(self):
        source_url = "https://cdn.example.test/product.jpg"
        with tempfile.TemporaryDirectory() as directory:
            image_root = Path(directory)
            image_path = image_root / "ABC01" / "image-1.jpg"
            image_path.parent.mkdir()
            image_path.write_bytes(b"image-data")
            with patch(
                "app.services.product_image_store.QdrantCatalogRepository",
            ) as catalog_class:
                catalog_class.return_value.image_records.return_value = [{
                    "source_url": source_url,
                    "local_path": "ABC01/image-1.jpg",
                    "mime_type": "image/jpeg",
                }]
                store = ProductImageStore(image_dir=image_root)
                result = store.get(source_url)

            self.assertEqual(result, (b"image-data", "image/jpeg"))

    def test_sync_reuses_local_image_only_for_matching_qdrant_url(self):
        source_url = "https://cdn.example.test/product.jpg"
        with tempfile.TemporaryDirectory() as directory:
            image_root = Path(directory)
            image_path = image_root / "ABC01" / "1_01.jpg"
            image_path.parent.mkdir()
            image_path.write_bytes(b"existing-image")
            with (
                patch(
                    "app.scripts.sync_product_images.QdrantCatalogRepository",
                ) as catalog_class,
                patch(
                    "app.scripts.sync_product_images.PRODUCT_IMAGE_DIR",
                    image_root,
                ),
                patch(
                    "app.scripts.sync_product_images.download_image",
                    side_effect=AssertionError("Không được tải lại ảnh"),
                ),
            ):
                catalog_class.return_value.image_records.return_value = [{
                    "source_url": source_url,
                    "local_path": "ABC01/1_01.jpg",
                    "mime_type": "image/jpeg",
                    "checksum": hashlib.sha256(b"existing-image").hexdigest(),
                }]
                result = sync_product_images(
                    self._shopify_product(source_url)
                )

            self.assertEqual(result["downloaded"], 0)
            self.assertEqual(result["skipped"], 1)
            self.assertEqual(result["local_images"][source_url]["local_path"], "ABC01/1_01.jpg")
            self.assertEqual(result["local_images"][source_url]["mime_type"], "image/jpeg")

    def test_sync_downloads_when_url_changes_at_same_position(self):
        old_url = "https://cdn.example.test/old.jpg"
        new_url = "https://cdn.example.test/new.jpg"
        with tempfile.TemporaryDirectory() as directory:
            image_root = Path(directory)
            image_path = image_root / "ABC01" / "1_01.jpg"
            image_path.parent.mkdir()
            image_path.write_bytes(b"old-image")
            with (
                patch(
                    "app.scripts.sync_product_images.QdrantCatalogRepository",
                ) as catalog_class,
                patch("app.scripts.sync_product_images.PRODUCT_IMAGE_DIR", image_root),
                patch(
                    "app.scripts.sync_product_images.download_image",
                    return_value=(b"new-image", "image/jpeg"),
                ) as download,
            ):
                catalog_class.return_value.image_records.return_value = [{
                    "source_url": old_url,
                    "local_path": "ABC01/1_01.jpg",
                    "checksum": hashlib.sha256(b"old-image").hexdigest(),
                }]
                result = sync_product_images(self._shopify_product(new_url))

            download.assert_called_once_with(new_url)
            self.assertEqual(result["downloaded"], 1)
            self.assertEqual(image_path.read_bytes(), b"new-image")


if __name__ == "__main__":
    unittest.main()
