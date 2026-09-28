"""Import one active Shopify SKU into the Qdrant catalog."""

import argparse
import logging

def sync_one(sku: str) -> dict:
    from app.scripts.build_product_image_embeddings import main as build_embeddings
    from app.scripts.sync_product_images import sync_product_images
    from app.services.product_import_service import find_products_by_sku
    from app.services.qdrant_catalog_sync import sync_shopify_products_to_qdrant

    products = find_products_by_sku(sku)
    if not products:
        raise ValueError(f"No active Shopify product found for SKU {sku}.")
    image_result = sync_product_images(products)
    catalog_result = sync_shopify_products_to_qdrant(
        products, local_images=image_result["local_images"]
    )
    embedding_result = build_embeddings(product_codes=catalog_result["product_codes"])
    has_errors = bool(image_result["failed"] or embedding_result["failed"])
    return {
        "status": "completed_with_errors" if has_errors else "completed",
        "total": catalog_result["total"],
        "succeeded": catalog_result["synced"],
        "failed_images": image_result["failed"],
        "embedding": embedding_result,
    }


def main(argv: list[str] | None = None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sku", required=True, help="Shopify SKU to import")
    args = parser.parse_args(argv)
    result = sync_one(args.sku)
    print("\n========== SHOPIFY TO QDRANT CATALOG ==========")
    print(f"Status: {result['status']}")
    print(f"Products: {result['total']}")
    print(f"Synced: {result.get('succeeded', 0)}")
    print(f"Failed images: {result.get('failed_images', 0)}")
    print(f"Seconds: {result.get('seconds', 0)}")
    return result


if __name__ == "__main__":
    main()
