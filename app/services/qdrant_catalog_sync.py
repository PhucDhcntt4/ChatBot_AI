from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.config import IMAGE_EMBEDDING_MODEL, IMAGE_EMBEDDING_PRETRAINED
from app.database.product_repository import ProductRepository
from app.database.qdrant_catalog_repository import QdrantCatalogRepository
from app.services.catalog_normalization import normalize_catalog


def _json_value(value: Any):
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _shopify_snapshot(product: dict[str, Any]) -> dict[str, Any]:
    code = str(product["product_code"]).strip().upper()
    variants = [dict(item) for item in product["variants"].values()]
    for variant in variants:
        for field in ("price", "compare_at_price"):
            value = variant.get(field)
            if isinstance(value, str) and value.strip():
                try:
                    variant[field] = Decimal(value.strip())
                except ValueError:
                    pass
    images = [
        {**image, "is_active": True, "embedded": bool(image.get("local_path"))}
        for image in product["images"].values()
    ]
    public_info = ProductRepository()._public_info_from_rows(
        code,
        product,
        variants,
        images,
    )
    colors = sorted({
        str(item.get("color") or "").strip()
        for item in variants
        if str(item.get("color") or "").strip()
    })
    active_images = [item for item in images if item.get("is_active")]
    local_images = [item for item in active_images if item.get("local_path")]
    embedded_images = [item for item in local_images if item.get("embedded")]
    updated_at = product.get("source_updated_at") or datetime.now().isoformat()
    product_detail = {
        key: value
        for key, value in product.items()
        if key not in {"variants", "images", "colors", "aliases"}
    }
    summary = {
        "product_code": code,
        "title": product.get("title"),
        "vendor": product.get("vendor"),
        "product_type": product.get("product_type"),
        "status": product.get("status"),
        "updated_at": updated_at,
        "variant_count": len(variants),
        "image_count": len(active_images),
        "local_image_count": len(local_images),
        "embedding_count": len(embedded_images),
        "colors": ", ".join(colors),
        "image_url": next(
            (
                item.get("source_url")
                for item in active_images
                if item.get("source_url")
            ),
            None,
        ),
        "ai_ready": (
            product.get("status") == "ACTIVE"
            and bool(local_images)
            and len(embedded_images) >= len(local_images)
        ),
    }
    return _json_value({
        "product_code": code,
        "title": product.get("title"),
        "product_type": product.get("product_type"),
        "description": product.get("description"),
        "vendor": product.get("vendor"),
        "material": product.get("material"),
        "sole": product.get("sole"),
        "height": product.get("height"),
        "status": product.get("status"),
        "updated_at": updated_at,
        "variant_skus": sorted({
            str(item.get("sku") or "").strip().upper()
            for item in variants if str(item.get("sku") or "").strip()
        }),
        "public_info": public_info,
        "summary": summary,
        "variants": variants,
        "images": images,
        "detail": {
            "product": product_detail,
            "variants": variants,
            "images": images,
            "attributes": [
                {"attribute_key": key, "attribute_value": value}
                for key, value in (
                    ("material", product.get("material")),
                    ("sole", product.get("sole")),
                    ("height", product.get("height")),
                ) if value
            ],
            "aliases": [
                {"alias": alias, "alias_type": "shopify"}
                for alias in sorted(product.get("aliases") or [])
            ],
            "embedding_model": IMAGE_EMBEDDING_MODEL,
            "embedding_pretrained": IMAGE_EMBEDDING_PRETRAINED,
        },
    })


def sync_shopify_products_to_qdrant(
    product_items: list[dict[str, Any]],
    *,
    local_images: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    catalog = normalize_catalog(product_items, local_images=local_images)
    snapshots = [
        _shopify_snapshot(product)
        for product in catalog["products"].values()
    ]
    repository = QdrantCatalogRepository()
    repository.ensure_collection()
    synced = repository.upsert_snapshots(snapshots)
    return {
        "status": "completed",
        "total": len(snapshots),
        "synced": synced,
        "deleted": 0,
        "product_codes": [item["product_code"] for item in snapshots],
    }
