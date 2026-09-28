import unittest
from unittest.mock import Mock, patch

from app.database.qdrant_catalog_repository import QdrantCatalogRepository


def payload(code="G81V6", product_type="GIAY CAO GOT", status="ACTIVE"):
    return {
        "kind": QdrantCatalogRepository.KIND,
        "product_code": code,
        "title": f"Sản phẩm {code}",
        "product_type": product_type,
        "status": status,
        "updated_at": "2026-09-18T10:00:00",
        "public_info": {"product_code": code, "image_urls": []},
        "summary": {
            "product_code": code,
            "title": f"Sản phẩm {code}",
            "product_type": product_type,
            "status": status,
        },
        "detail": {"product": {"product_code": code}},
        "variants": [{"sku": code}],
        "images": [],
    }


class QdrantCatalogRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.repository = QdrantCatalogRepository("catalog-test")

    def test_point_id_is_stable_and_code_is_case_insensitive(self):
        self.assertEqual(
            self.repository.point_id("g81v6"),
            self.repository.point_id(" G81V6 "),
        )

    def test_upsert_uses_catalog_payload_and_dummy_vector(self):
        self.repository.request = Mock(return_value={})
        self.assertEqual(self.repository.upsert_snapshots([payload()]), 1)
        request = self.repository.request.call_args
        point = request.kwargs["json"]["points"][0]
        self.assertEqual(point["vector"], [1.0])
        self.assertEqual(point["payload"]["kind"], self.repository.KIND)
        self.assertEqual(point["payload"]["product_code"], "G81V6")

    def test_public_info_and_detail_are_read_from_payload(self):
        value = payload()
        self.repository.request = Mock(return_value={
            "points": [{"payload": value}],
            "next_page_offset": None,
        })
        self.assertEqual(
            self.repository.public_info("g81v6")["product_code"],
            "G81V6",
        )
        self.assertEqual(
            self.repository.catalog_detail("G81V6")["product"]["product_code"],
            "G81V6",
        )

    def test_catalog_page_filters_search_and_type(self):
        values = [
            payload("G81V6", "GIAY CAO GOT"),
            payload("S32F8", "SANDAL CAO GOT"),
        ]
        self.repository.request = Mock(return_value={
            "points": [{"payload": value} for value in values],
            "next_page_offset": None,
        })
        result = self.repository.catalog_page(
            search="g81",
            product_type="GIAY CAO GOT",
        )
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["products"][0]["product_code"], "G81V6")
        self.assertEqual(
            result["product_types"],
            ["GIAY CAO GOT", "SANDAL CAO GOT"],
        )

    def test_factory_selects_qdrant(self):
        from app.database import product_repository_factory as factory

        fake = Mock(provider="qdrant")
        with patch.object(factory, "QdrantCatalogRepository", return_value=fake):
            self.assertIs(factory.create_product_repository(), fake)
        fake.ready.assert_called_once()


if __name__ == "__main__":
    unittest.main()
