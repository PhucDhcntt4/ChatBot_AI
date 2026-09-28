import unittest
from unittest.mock import patch

from app.scripts.sync_catalog_to_qdrant import sync_one


class ShopifyQdrantCatalogImportTests(unittest.TestCase):
    def test_one_sku_imports_to_qdrant(self):
        products = [{"product": {"id": "gid://shopify/Product/1"}}]
        with (
            patch(
                "app.services.product_import_service.find_products_by_sku",
                return_value=products,
            ),
            patch(
                "app.scripts.sync_product_images.sync_product_images",
                return_value={"local_images": {}, "failed": 0},
            ),
            patch(
                "app.services.qdrant_catalog_sync.sync_shopify_products_to_qdrant",
                return_value={"total": 1, "synced": 1, "product_codes": ["ABC01"]},
            ) as catalog,
            patch(
                "app.scripts.build_product_image_embeddings.main",
                return_value={"created": 1, "skipped": 0, "failed": 0},
            ),
        ):
            result = sync_one("ABC01")

        self.assertEqual(result["status"], "completed")
        catalog.assert_called_once_with(products, local_images={})


if __name__ == "__main__":
    unittest.main()
