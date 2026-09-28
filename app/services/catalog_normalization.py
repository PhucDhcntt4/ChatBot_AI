"""Normalize Shopify catalog payloads for the Qdrant product catalog."""

import re
import unicodedata
from collections import defaultdict
from typing import Any


def normalize_text(value: Any) -> str:
    normalized = unicodedata.normalize(
        "NFD", str(value or "").casefold()
    )
    return "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Mn"
    ).replace("đ", "d").strip()


def product_code(item: dict[str, Any], product: dict[str, Any]) -> str:
    searched_sku = str(item.get("searched_sku") or "").strip().upper()
    if searched_sku:
        return searched_sku

    matched_sku = str(
        (item.get("matched_variant") or {}).get("sku") or ""
    ).strip().upper()
    if matched_sku:
        return matched_sku

    title_match = re.search(
        r"\b[A-Z]\d{3,}[A-Z0-9]*\b",
        str(product.get("title") or "").upper(),
    )
    if title_match:
        return title_match.group(0)

    for variant in (product.get("variants") or {}).get("nodes", []):
        sku = str(variant.get("sku") or "").strip().upper()
        if sku:
            return sku
    return ""


def selected_option(
    variant: dict[str, Any],
    option_name: str,
) -> str | None:
    expected = normalize_text(option_name)
    for option in variant.get("selectedOptions") or []:
        if normalize_text(option.get("name")) == expected:
            value = str(option.get("value") or "").strip()
            return value or None
    return None


def product_colors(product: dict[str, Any]) -> list[str]:
    colors: list[str] = []
    for option in product.get("options") or []:
        if normalize_text(option.get("name")) == "color":
            colors.extend(
                str(value).strip()
                for value in option.get("values") or []
                if str(value).strip()
            )
    return list(dict.fromkeys(colors))


def description_spec(description: str, labels: tuple[str, ...]) -> str | None:
    for label in labels:
        match = re.search(
            rf"-\s*{label}\s*:\s*([^-\r\n]+)",
            description,
            flags=re.IGNORECASE,
        )
        if match:
            value = match.group(1).strip()
            if value:
                return value
    return None


def description_colors(description: str) -> list[str]:
    match = re.search(
        r"-\s*(?:Màu sắc|Màu)\s*:\s*([^-]+)",
        description,
        flags=re.IGNORECASE,
    )
    if not match:
        return []
    return [
        color.strip()
        for color in match.group(1).split(",")
        if color.strip()
    ]


def normalize_catalog(
    data: list[dict[str, Any]],
    local_images: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    local_images = local_images or {}
    products: dict[str, dict[str, Any]] = {}

    for item in data:
        if not isinstance(item, dict):
            continue
        product = item.get("product", item)
        if not isinstance(product, dict):
            continue

        code = product_code(item, product)
        if not code:
            continue

        description = str(product.get("description") or "")
        canonical = products.setdefault(code, {
            "product_code": code,
            "title": str(product.get("title") or code),
            "handle": product.get("handle"),
            "vendor": product.get("vendor"),
            "product_type": product.get("productType"),
            "description": description,
            "material": description_spec(description, ("Chất liệu",)),
            "sole": description_spec(description, ("Đế",)),
            "height": description_spec(
                description, ("Cao", "Chiều cao")
            ),
            "status": product.get("status") or "ACTIVE",
            "online_store_url": product.get("onlineStoreUrl"),
            "source_updated_at": product.get("updatedAt"),
            "variants": {},
            "images": {},
            "colors": {},
            "aliases": set(),
        })

        canonical["aliases"].update(filter(None, (
            canonical["title"],
            canonical["product_type"],
            code,
        )))

        colors = product_colors(product)
        # Màu đang bán phải lấy từ Shopify options/variants.
        # Description chỉ là nội dung giới thiệu và có thể chưa được
        # cập nhật, nên không dùng nó để xác định màu hiện có.
        for color in colors:
            canonical["colors"].setdefault(
                normalize_text(color),
                color,
            )
        for variant in (product.get("variants") or {}).get("nodes", []):
            sku = str(variant.get("sku") or code).strip().upper()
            color = selected_option(variant, "Color")
            size = selected_option(variant, "Size")
            key = (sku, normalize_text(color), size or "")
            quantity = int(variant.get("inventoryQuantity") or 0)
            canonical["variants"][key] = {
                "external_id": variant.get("id"),
                "legacy_id": variant.get("legacyResourceId"),
                "sku": sku,
                "barcode": variant.get("barcode"),
                "variant_title": variant.get("title"),
                "color": color,
                "color_normalized": normalize_text(color),
                "size": size or "",
                "price": variant.get("price"),
                "compare_at_price": variant.get("compareAtPrice"),
                "inventory_quantity": quantity,
                "available": quantity > 0,
            }

        image_items: list[tuple[dict[str, Any], bool]] = []
        featured = product.get("featuredImage") or {}
        if featured.get("url"):
            image_items.append((featured, True))
        image_items.extend(
            (image, False)
            for image in (product.get("images") or {}).get("nodes", [])
            if image.get("url")
        )

        assigned_colors = colors or [None]
        for color in assigned_colors:
            for position, (image, is_featured) in enumerate(image_items):
                key = (str(image.get("url")), normalize_text(color))
                image_url = str(image.get("url") or "").strip()
                local_metadata = local_images.get(image_url) or {}
                canonical["images"][key] = {
                    "external_id": image.get("id"),
                    "color": color,
                    "color_normalized": normalize_text(color),
                    "source_url": image_url,
                    "local_path": local_metadata.get("local_path"),
                    "alt_text": image.get("altText"),
                    "mime_type": local_metadata.get("mime_type"),
                    "width": image.get("width"),
                    "height": image.get("height"),
                    "image_order": position,
                    "is_featured": is_featured,
                    "checksum": local_metadata.get("checksum"),
                }

    return {"products": products}
