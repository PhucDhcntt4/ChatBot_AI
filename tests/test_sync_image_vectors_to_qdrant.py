import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.scripts import sync_image_vectors_to_qdrant as sync


class ImageVectorSyncTests(unittest.TestCase):
    def run_sync(self, vector, existing=None, product_codes=None):
        record = {
            "local_path": "TEST01/test.jpg",
            "checksum": "test-checksum",
            "product_code": "TEST01",
            "title": "Test product",
            "product_type": "SHOE",
            "color": "Black",
            "source_url": "https://cdn.test/test.jpg",
            "mime_type": "image/jpeg",
            "is_active": True,
        }
        point_id = sync._point_id(record)
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / record["local_path"]
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"image")
            embedder = MagicMock()
            embedder.model_name = "ViT-B-32"
            embedder.pretrained_name = "laion2b_s34b_b79k"
            embedder.checksum.return_value = "test-checksum"
            embedder.embed_bytes.return_value = vector
            catalog = MagicMock()
            catalog.image_records.return_value = [record]
            with patch.object(sync, "PRODUCT_IMAGE_DIR", Path(directory)), \
                 patch.object(sync, "ImageEmbeddingService", return_value=embedder), \
                 patch.object(sync, "QdrantCatalogRepository", return_value=catalog), \
                 patch.object(sync, "QdrantImageRepository") as repository_class, \
                 redirect_stdout(io.StringIO()):
                repository = repository_class.return_value
                repository.DIMENSION = 512
                repository.KIND = "bot_product_image"
                repository.point_metadata.return_value = existing or {}
                result = sync.main(product_codes=product_codes)
                points = (
                    list(repository.upsert.call_args.args[0])
                    if repository.upsert.called else []
                )
        return result, points, repository, embedder, point_id

    def test_image_is_embedded_and_uploaded_directly(self):
        values = [1.0] + [0.0] * 511
        result, points, repository, embedder, point_id = self.run_sync(values)
        self.assertEqual(result, {
            "synced": 1, "unchanged": 0, "failed": 0,
            "deleted": 0, "total": 1,
        })
        self.assertEqual(points[0]["id"], point_id)
        self.assertEqual(points[0]["vector"], values)
        self.assertEqual(points[0]["payload"]["product_code"], "TEST01")
        self.assertEqual(points[0]["payload"]["source_kind"], "catalog")
        embedder.embed_bytes.assert_called_once_with(b"image")
        repository.delete_points.assert_called_once_with([])

    def test_unchanged_point_is_not_encoded_again(self):
        values = [1.0] + [0.0] * 511
        _, _, _, embedder, point_id = self.run_sync(values)
        expected = {
            "kind": "bot_product_image", "source_kind": "catalog",
            "product_image_id": point_id, "product_code": "TEST01",
            "title": "Test product", "product_type": "SHOE",
            "color": "Black", "image_order": None,
            "is_featured": False, "is_active": True,
            "local_path": "TEST01/test.jpg",
            "source_url": "https://cdn.test/test.jpg",
            "mime_type": "image/jpeg", "model_name": "ViT-B-32",
            "pretrained_name": "laion2b_s34b_b79k",
            "image_checksum": "test-checksum",
        }
        result, points, repository, embedder, _ = self.run_sync(
            values, {point_id: expected}
        )
        self.assertEqual(result["unchanged"], 1)
        self.assertEqual(points, [])
        embedder.embed_bytes.assert_not_called()

    def test_invalid_vector_marks_failure_without_upload(self):
        for vector in ([1.0, 0.0], [0.0] * 512):
            with self.subTest(length=len(vector)):
                result, points, repository, _, _ = self.run_sync(vector)
                self.assertEqual(result["failed"], 1)
                self.assertEqual(points, [])
                repository.upsert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
