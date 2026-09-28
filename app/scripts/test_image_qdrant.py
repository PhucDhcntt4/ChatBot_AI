"""Read-only image retrieval smoke test: no LLM call, no messages or orders."""
import argparse
from pathlib import Path
from time import perf_counter

from app.config import (
    IMAGE_EMBEDDING_MODEL, IMAGE_EMBEDDING_PRETRAINED, PRODUCT_IMAGE_DIR,
)
from app.database.qdrant_catalog_repository import QdrantCatalogRepository
from app.database.qdrant_image_repository import QdrantImageRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--image", type=Path, help="Test a JPEG/PNG/WebP file")
    choice.add_argument("--catalog-image", action="store_true", help="Embed a catalog image again using CLIP")
    parser.add_argument("--offline", action="store_true", help="Use cached CLIP weights only")
    args = parser.parse_args()
    repository = QdrantImageRepository()
    info = repository.ready()
    print(f"Qdrant collection ready; points={info.get('points_count')}", flush=True)

    sample = None
    if args.image is None:
        indexed = {
            (payload.get("product_code"), payload.get("source_url"))
            for payload in repository.point_metadata().values()
            if payload.get("source_kind") == "catalog"
            and payload.get("model_name") == IMAGE_EMBEDDING_MODEL
            and payload.get("pretrained_name") == IMAGE_EMBEDDING_PRETRAINED
        }
        sample = next(
            (
                record for record in QdrantCatalogRepository().image_records()
                if (record.get("product_code"), record.get("source_url")) in indexed
                and (PRODUCT_IMAGE_DIR / record["local_path"]).is_file()
            ),
            None,
        )
        if sample is None:
            raise RuntimeError("No indexed catalog image available")

    if args.offline:
        import os
        os.environ["HF_HUB_OFFLINE"] = "1"
    from app.product_recognition.image_embedding_service import ImageEmbeddingService

    image_path = args.image
    if image_path is None:
        image_path = (PRODUCT_IMAGE_DIR / sample["local_path"]).resolve()
        if not image_path.is_relative_to(PRODUCT_IMAGE_DIR.resolve()):
            raise ValueError("Invalid catalog image path")
    if image_path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("Test image exceeds 20 MB")
    print(f"Embedding local image: {image_path.name}", flush=True)
    embedder = ImageEmbeddingService()
    vector = embedder.embed_bytes(image_path.read_bytes())
    model, weights = embedder.model_name, embedder.pretrained_name

    started = perf_counter()
    results = repository.search(vector, model, weights, limit=10)
    print(f"Search completed in {perf_counter() - started:.3f}s")
    for index, row in enumerate(results, start=1):
        print(f"{index}. code={row['product_code']} similarity={row['similarity']:.6f}")
    if not results:
        raise RuntimeError("No active candidate returned")
    if sample is not None and not any(row["product_code"] == sample["product_code"] for row in results):
        raise RuntimeError(f"Expected catalog code {sample['product_code']} missing from top 10")
    print("PASS: Qdrant retrieval + Qdrant catalog metadata. LLM verification not tested.")


if __name__ == "__main__":
    main()
