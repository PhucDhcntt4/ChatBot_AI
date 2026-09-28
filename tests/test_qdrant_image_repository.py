import unittest
from unittest.mock import MagicMock, patch

import httpx

from app.database import qdrant_image_repository as module
from app.product_recognition import handler
from app.scripts import build_product_image_embeddings as builder


class QdrantImageTests(unittest.TestCase):
    def setUp(self):
        self.repository = module.QdrantImageRepository()
        self.vector = [1.0] + [0.0] * 511

    @staticmethod
    def hit(point_id, checksum="v1", score=0.99):
        return {"id": point_id, "score": score,
                "payload": {"kind": "bot_product_image",
                            "image_checksum": checksum,
                            "product_image_id": point_id,
                            "product_code": "TEST01",
                            "product_type": "SHOE",
                            "is_active": True}}

    @staticmethod
    def row(point_id, kind="SHOE"):
        return {"vector_id": point_id, "image_checksum": "v1",
                "product_image_id": point_id,
                "product_code": "TEST01", "product_type": kind}

    def test_wrong_collection_dimension_rejected_without_writes(self):
        info = {"config": {"params": {"vectors": {"size": 768, "distance": "Cosine"}}}}
        with patch.object(self.repository, "request", return_value=info) as request:
            with self.assertRaises(ValueError):
                self.repository.ensure_collection()
            self.assertEqual(request.call_count, 1)

    def test_ready_only_reads_collection(self):
        info = {"status": "green", "config": {"params": {
            "vectors": {"size": 512, "distance": "Cosine"}}}}
        with patch.object(self.repository, "request", return_value=info) as request:
            self.assertEqual(self.repository.ready(), info)
            request.assert_called_once_with("GET", self.repository.path)

    def test_inactive_vectors_are_not_returned(self):
        hits = [self.hit(1), self.hit(2), self.hit(3)]
        hits[1]["payload"]["is_active"] = False
        with patch.object(self.repository, "request", return_value={"points": hits}):
            results = self.repository.search(self.vector, "model", "weights")
        self.assertEqual([str(row["vector_id"]) for row in results], ["1", "3"])
        self.assertEqual(results[0]["similarity"], 0.99)

    def test_type_filter_uses_qdrant_payload_index(self):
        with patch.object(self.repository, "request", return_value={"points": [self.hit(3)]}) as request:
            results = self.repository.search(self.vector, "model", "weights", ["SHOE"])
        self.assertEqual(len(results), 1)
        self.assertIn(
            {"key": "product_type", "match": {"any": ["SHOE"]}},
            request.call_args.kwargs["json"]["filter"]["must"],
        )

    def test_empty_type_result_returns_empty(self):
        with patch.object(self.repository, "request", return_value={"points": []}) as request:
            self.assertEqual(self.repository.search(self.vector, "model", "weights", "NONE"), [])
        request.assert_called_once()

    def test_point_metadata_scrolls_and_delete_is_explicit(self):
        first = {
            "points": [{"id": 1, "payload": {
                "kind": self.repository.KIND,
                "model_name": "model",
                "pretrained_name": "weights",
                "image_checksum": "a",
            }}],
            "next_page_offset": 1,
        }
        second = {
            "points": [{"id": 2, "payload": {
                "kind": self.repository.KIND,
                "model_name": "model",
                "pretrained_name": "weights",
                "image_checksum": "b",
            }}],
            "next_page_offset": None,
        }
        with patch.object(self.repository, "request", side_effect=[first, second, {}]) as request:
            metadata = self.repository.point_metadata()
            self.repository.delete_points([2, 1, 2])
        self.assertEqual(set(metadata), {1, 2})
        self.assertEqual(request.call_args.kwargs["json"], {"points": [1, 2]})

    def test_query_failure_is_not_disguised_as_no_match(self):
        with patch.object(self.repository, "request", side_effect=httpx.ReadTimeout("test")):
            with self.assertRaises(httpx.ReadTimeout):
                self.repository.search(self.vector, "model", "weights")

    def test_invalid_vector_does_not_query_qdrant(self):
        for values in ([0.0] * 512, [float("nan")] * 512, [1.0]):
            with self.subTest(length=len(values)), patch.object(self.repository, "request") as request:
                with self.assertRaises(ValueError):
                    self.repository.search(values, "model", "weights")
                request.assert_not_called()

    def test_handler_always_uses_qdrant(self):
        with patch.object(handler, "PRODUCT_VECTOR_SEARCH_ENABLED", True), \
             patch.object(handler, "ProductRecognitionService"), \
             patch(
                 "app.product_recognition.image_embedding_service.ImageEmbeddingService"
             ), \
             patch.object(handler, "QdrantImageRepository") as qdrant:
            instance = handler.ProductImageHandler(MagicMock(), "test", catalog=MagicMock())
            self.assertIsNone(instance.embedding_repository)
            self.assertTrue(instance._ensure_vector_backend())
            self.assertIs(instance.embedding_repository, qdrant.return_value)
            self.assertTrue(instance.vector_enabled)
            qdrant.return_value.ready.assert_called_once()

    def test_builder_delegates_directly_to_qdrant_sync(self):
        with patch.object(builder, "sync_qdrant", return_value={
            "synced": 3, "unchanged": 2, "failed": 0,
            "deleted": 1, "total": 5,
        }) as sync:
            result = builder.main()
        sync.assert_called_once_with(product_codes=None)
        self.assertEqual(result["created"], 3)
        self.assertEqual(result["skipped"], 2)
        self.assertEqual(result["qdrant_synced"], 3)

    def test_builder_reports_qdrant_vector_failures(self):
        with patch.object(builder, "sync_qdrant", return_value={
            "synced": 0, "unchanged": 0, "failed": 1,
            "deleted": 0, "total": 1,
        }):
            with self.assertRaises(RuntimeError):
                builder.main()


if __name__ == "__main__":
    unittest.main()
