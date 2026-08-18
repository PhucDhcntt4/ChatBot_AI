import json
import os
import re
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv  # type: ignore

from app.database.connection import database_connection
from app.scripts.import_products_to_db import (
    import_catalog,
    initialize_schema,
    normalize_catalog,
)
from app.scripts.sync_product_images import sync_product_images

from app.scripts.build_product_image_embeddings import(
    main as build_product_image_embeddings
)



load_dotenv()


SHOP = os.getenv("SHOP")
TOKEN = os.getenv("SHOPIFY_TOKEN")
API_VERSION = os.getenv("SHOPIFY_API_VERSION")

# ThÆ° má»¥c lÆ°u file JSON.
PROJECT_ROOT = Path(__file__).resolve().parent


PRODUCT_BY_SKU_QUERY = """
query ProductBySku(
  $query: String!
  $variantLimit: Int!
  $imageLimit: Int!
  $after: String
) {
  productVariants(
    first: $variantLimit
    after: $after
    query: $query
  ) {
    nodes {
      id
      legacyResourceId
      title
      sku
      barcode
      price
      compareAtPrice
      inventoryQuantity

      selectedOptions {
        name
        value
      }

      inventoryItem {
        id
        tracked

        measurement {
          weight {
            value
            unit
          }
        }
      }

      image {
        id
        url
        altText
        width
        height
      }

      product {
        id
        legacyResourceId

        title
        handle
        vendor
        productType

        description
        status

        createdAt
        updatedAt

        onlineStoreUrl

        featuredImage {
          id
          url
          altText
          width
          height
        }

        images(first: $imageLimit) {
          nodes {
            id
            url
            altText
            width
            height
          }
        }

        options {
          id
          name
          values
        }

        variants(first: 100) {
          nodes {
            id
            legacyResourceId

            title
            sku
            barcode

            price
            compareAtPrice
            inventoryQuantity

            selectedOptions {
              name
              value
            }

            image {
              id
              url
              altText
              width
              height
            }

            inventoryItem {
              id
              tracked

              measurement {
                weight {
                  value
                  unit
                }
              }
            }
          }
        }

        seo {
          title
          description
        }
      }
    }

    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""


PRODUCT_VARIANTS_QUERY = """
query ProductVariants(
  $productId: ID!
  $first: Int!
  $after: String
) {
  product(id: $productId) {
    id

    variants(
      first: $first
      after: $after
    ) {
      nodes {
        id
        legacyResourceId
        title
        sku
        barcode
        price
        compareAtPrice
        inventoryQuantity

        selectedOptions {
          name
          value
        }

        inventoryItem {
          id
          tracked

          measurement {
            weight {
              value
              unit
            }
          }
        }

        image {
          id
          url
          altText
          width
          height
        }
      }

      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""


def validate_config() -> None:
    """
    Kiá»ƒm tra cĂ¡c biáº¿n cáº¥u hĂ¬nh Shopify.
    """

    missing: list[str] = []

    if not SHOP:
        missing.append("SHOP")

    if not TOKEN:
        missing.append("SHOPIFY_TOKEN")

    if not API_VERSION:
        missing.append("SHOPIFY_API_VERSION")

    if missing:
        raise ValueError(
            "Thiáº¿u biáº¿n mĂ´i trÆ°á»ng trong file .env: "
            + ", ".join(missing)
        )


def shopify_graphql(
    query: str,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Gá»i Shopify GraphQL Admin API.
    """

    validate_config()

    url = (
        f"https://{SHOP}/admin/api/"
        f"{API_VERSION}/graphql.json"
    )

    try:
        response = requests.post(
            url,
            headers={
                "X-Shopify-Access-Token": str(TOKEN),
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "variables": variables or {},
            },
            timeout=30,
        )

        response.raise_for_status()

    except requests.Timeout as error:
        raise RuntimeError(
            "Shopify API pháº£n há»“i quĂ¡ thá»i gian."
        ) from error

    except requests.RequestException as error:
        raise RuntimeError(
            f"KhĂ´ng thá»ƒ káº¿t ná»‘i Shopify API: {error}"
        ) from error

    try:
        result = response.json()

    except ValueError as error:
        raise RuntimeError(
            "Shopify tráº£ vá» dá»¯ liá»‡u khĂ´ng pháº£i JSON."
        ) from error

    if result.get("errors"):
        raise RuntimeError(
            "Shopify GraphQL lá»—i:\n"
            + json.dumps(
                result["errors"],
                ensure_ascii=False,
                indent=2,
            )
        )

    if "data" not in result:
        raise RuntimeError(
            "Shopify khĂ´ng tráº£ vá» trÆ°á»ng data."
        )

    return result["data"]


def normalize_sku(sku: str) -> str:
    """
    Chuáº©n hĂ³a SKU ngÆ°á»i dĂ¹ng nháº­p.
    """

    return sku.strip().upper()


def escape_search_value(value: str) -> str:
    """
    Escape giĂ¡ trá»‹ dĂ¹ng trong Shopify search query.
    """

    return (
        value
        .replace("\\", "\\\\")
        .replace('"', '\\"')
    )


def product_contains_code(
    variant: dict[str, Any],
    product_code: str,
) -> bool:
    """
    Kiá»ƒm tra mĂ£ máº«u trĂªn SKU, handle vĂ  mĂ´ táº£ sáº£n pháº©m.

    Má»™t sá»‘ mĂ u Ä‘Æ°á»£c quáº£n lĂ½ thĂ nh Shopify Product riĂªng vĂ  cĂ³ thá»ƒ dĂ¹ng
    SKU variant khĂ¡c, trong khi mĂ£ máº«u váº«n náº±m trong handle/mĂ´ táº£.
    """

    normalized_code = normalize_sku(product_code)
    variant_sku = normalize_sku(
        str(variant.get("sku") or "")
    )

    if variant_sku == normalized_code:
        return True

    product = variant.get("product") or {}
    handle = str(product.get("handle") or "").upper()

    handle_tokens = [
        token
        for token in re.split(r"[^A-Z0-9]+", handle)
        if token
    ]

    if normalized_code in handle_tokens:
        return True

    description = str(product.get("description") or "")
    code_pattern = re.compile(
        r"(?:MĂƒ|MA)\s*Sáº¢N\s*PHáº¨M\s*:\s*"
        + re.escape(normalized_code)
        + r"\b",
        re.IGNORECASE,
    )

    return bool(code_pattern.search(description))


def get_all_product_variants(
    product_id: str,
) -> list[dict[str, Any]]:
    """
    Láº¥y toĂ n bá»™ variants cá»§a má»™t sáº£n pháº©m báº±ng phĂ¢n trang Shopify.
    """

    all_variants: list[dict[str, Any]] = []
    cursor: str | None = None

    while True:
        data = shopify_graphql(
            PRODUCT_VARIANTS_QUERY,
            {
                "productId": product_id,
                "first": 100,
                "after": cursor,
            },
        )

        product = data.get("product")

        if not product:
            raise ValueError(
                f"KhĂ´ng tĂ¬m tháº¥y sáº£n pháº©m Shopify: {product_id}"
            )

        variants_connection = product.get("variants", {})
        nodes = variants_connection.get("nodes", [])

        if not isinstance(nodes, list):
            raise RuntimeError(
                "Shopify tráº£ vá» danh sĂ¡ch variants khĂ´ng há»£p lá»‡."
            )

        all_variants.extend(nodes)

        page_info = variants_connection.get("pageInfo", {})

        if not page_info.get("hasNextPage"):
            break

        cursor = page_info.get("endCursor")

        if not cursor:
            raise RuntimeError(
                "Shopify bĂ¡o cĂ²n trang variants nhÆ°ng khĂ´ng tráº£ endCursor."
            )

    return all_variants


def find_products_by_sku(
    sku: str,
) -> list[dict[str, Any]]:
    """
    TĂ¬m táº¥t cáº£ sáº£n pháº©m ACTIVE chá»©a variant cĂ³ SKU chĂ­nh xĂ¡c.

    Shopify cĂ³ thá»ƒ quáº£n lĂ½ má»—i mĂ u thĂ nh má»™t Product riĂªng nhÆ°ng
    cĂ¡c Product Ä‘Ă³ váº«n dĂ¹ng chung má»™t mĂ£ SKU.
    """

    normalized_sku = normalize_sku(sku)

    if not normalized_sku:
        raise ValueError("MĂ£ SKU khĂ´ng Ä‘Æ°á»£c Ä‘á»ƒ trá»‘ng.")

    escaped_sku = escape_search_value(normalized_sku)

    variants: list[dict[str, Any]] = []
    cursor: str | None = None

    while True:
        data = shopify_graphql(
            PRODUCT_BY_SKU_QUERY,
            {
                # TĂ¬m máº·c Ä‘á»‹nh trĂªn nhiá»u trÆ°á»ng thay vĂ¬ chá»‰ SKU.
                # Cáº§n thiáº¿t khi má»—i mĂ u lĂ  má»™t Product riĂªng.
                "query": f'"{escaped_sku}"',
                "variantLimit": 50,
                "imageLimit": 100,
                "after": cursor,
            },
        )

        variants_connection = data.get("productVariants", {})
        page_nodes = variants_connection.get("nodes", [])

        if not isinstance(page_nodes, list):
            raise RuntimeError(
                "Shopify tráº£ vá» káº¿t quáº£ tĂ¬m SKU khĂ´ng há»£p lá»‡."
            )

        variants.extend(page_nodes)

        page_info = variants_connection.get("pageInfo", {})

        if not page_info.get("hasNextPage"):
            break

        cursor = page_info.get("endCursor")

        if not cursor:
            raise RuntimeError(
                "Shopify bĂ¡o cĂ²n káº¿t quáº£ SKU nhÆ°ng khĂ´ng tráº£ endCursor."
            )

    if not variants:
        return []

    # Shopify search cĂ³ thá»ƒ tráº£ vá» nhiá»u káº¿t quáº£ gáº§n giá»‘ng.
    # Kiá»ƒm tra mĂ£ trĂªn SKU, handle hoáº·c mĂ´ táº£ báº±ng Python.
    code_matches = [
        variant
        for variant in variants
        if product_contains_code(variant, normalized_sku)
    ]

    if not code_matches:
        return []

    # Chá»‰ láº¥y sáº£n pháº©m Ä‘ang ACTIVE.
    active_matches = [
        variant
        for variant in code_matches
        if (
            variant.get("product")
            and variant["product"].get("status") == "ACTIVE"
        )
    ]

    if not active_matches:
        raise ValueError(
            f"ÄĂ£ tĂ¬m tháº¥y SKU '{normalized_sku}', "
            "nhÆ°ng sáº£n pháº©m khĂ´ng á»Ÿ tráº¡ng thĂ¡i ACTIVE."
        )

    products_by_id: dict[str, dict[str, Any]] = {}

    for matched_variant in active_matches:
        product = matched_variant["product"]
        product_id = product.get("id")

        if not product_id:
            continue

        # Má»™t Product cĂ³ nhiá»u size cĂ¹ng SKU nĂªn cáº§n khá»­ trĂ¹ng theo
        # Shopify Product ID trÆ°á»›c khi táº£i toĂ n bá»™ variants.
        if product_id in products_by_id:
            continue

        all_variants = get_all_product_variants(product_id)
        product["variants"] = {
            "nodes": all_variants,
        }

        products_by_id[product_id] = {
            "searched_sku": normalized_sku,
            "matched_variant": {
                "id": matched_variant.get("id"),
                "legacyResourceId": matched_variant.get(
                    "legacyResourceId"
                ),
                "title": matched_variant.get("title"),
                "sku": matched_variant.get("sku"),
                "barcode": matched_variant.get("barcode"),
                "price": matched_variant.get("price"),
                "compareAtPrice": matched_variant.get(
                    "compareAtPrice"
                ),
                "inventoryQuantity": matched_variant.get(
                    "inventoryQuantity"
                ),
                "selectedOptions": matched_variant.get(
                    "selectedOptions",
                    [],
                ),
                "image": matched_variant.get("image"),
                "inventoryItem": matched_variant.get(
                    "inventoryItem"
                ),
            },
            "product": product,
        }

    return list(products_by_id.values())


def find_product_by_sku(
    sku: str,
) -> dict[str, Any] | None:
    """
    HĂ m tÆ°Æ¡ng thĂ­ch cho nÆ¡i chá»‰ cáº§n káº¿t quáº£ Ä‘áº§u tiĂªn.
    """

    products = find_products_by_sku(sku)
    return products[0] if products else None

def print_product_summary(
    product_data: dict[str, Any],
) -> None:
    """
    In thĂ´ng tin tĂ³m táº¯t ra terminal.
    """

    product = product_data["product"]
    matched_variant = product_data["matched_variant"]

    print("\n========== Sáº¢N PHáº¨M ==========")
    print(f"TĂªn: {product.get('title')}")
    print(f"Handle: {product.get('handle')}")
    print(f"Tráº¡ng thĂ¡i: {product.get('status')}")
    print(f"Loáº¡i: {product.get('productType')}")
    print(f"NhĂ  cung cáº¥p: {product.get('vendor')}")
    print(f"SKU tĂ¬m tháº¥y: {matched_variant.get('sku')}")
    print(f"GiĂ¡: {matched_variant.get('price')}")
    print(
        "Tá»“n kho: "
        f"{matched_variant.get('inventoryQuantity')}"
    )
    print(
        "Sá»‘ lÆ°á»£ng áº£nh: "
        f"{len(product.get('images', {}).get('nodes', []))}"
    )
    print(
        "Sá»‘ lÆ°á»£ng variants: "
        f"{len(product.get('variants', {}).get('nodes', []))}"
    )


PROJECT_ROOT = Path(__file__).resolve().parent
PRODUCTS_FILE = PROJECT_ROOT / "products.json"


def validate_product_structure(
    product_data: dict[str, Any],
) -> None:
    """
    Báº£o Ä‘áº£m dá»¯ liá»‡u lÆ°u ra Ä‘Ăºng schema mĂ  á»©ng dá»¥ng Ä‘ang Ä‘á»c:
    searched_sku + matched_variant + product.
    """

    searched_sku = product_data.get("searched_sku")
    matched_variant = product_data.get("matched_variant")
    product = product_data.get("product")

    if not isinstance(searched_sku, str) or not searched_sku:
        raise ValueError("Dá»¯ liá»‡u thiáº¿u searched_sku há»£p lá»‡.")

    if not isinstance(matched_variant, dict):
        raise ValueError("Dá»¯ liá»‡u thiáº¿u matched_variant.")

    if not isinstance(product, dict):
        raise ValueError("Dá»¯ liá»‡u thiáº¿u product.")

    if not isinstance(product.get("featuredImage"), dict):
        raise ValueError("Product thiáº¿u featuredImage.")

    images = product.get("images")
    if not isinstance(images, dict) or not isinstance(
        images.get("nodes"),
        list,
    ):
        raise ValueError("Product.images.nodes khĂ´ng há»£p lá»‡.")

    variants = product.get("variants")
    if not isinstance(variants, dict) or not isinstance(
        variants.get("nodes"),
        list,
    ):
        raise ValueError("Product.variants.nodes khĂ´ng há»£p lá»‡.")


def save_product(product_data: dict) -> None:
    """
    ThĂªm hoáº·c cáº­p nháº­t sáº£n pháº©m vĂ o products.json
    """

    validate_product_structure(product_data)

    PRODUCTS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    # Náº¿u chÆ°a cĂ³ file
    if not PRODUCTS_FILE.exists():
        products = []
    else:
        with open(
            PRODUCTS_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            try:
                products = json.load(f)
            except Exception:
                products = []

    sku = product_data["searched_sku"]
    product_id = product_data["product"].get("id")

    if not product_id:
        raise ValueError("Sáº£n pháº©m khĂ´ng cĂ³ Shopify ID.")

    updated = False

    for index, item in enumerate(products):

        existing_product = (
            item.get("product", {})
            if isinstance(item, dict)
            else {}
        )

        if existing_product.get("id") == product_id:

            products[index] = product_data
            updated = True
            break

    if not updated:
        products.append(product_data)

    with open(
        PRODUCTS_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            products,
            f,
            ensure_ascii=False,
            indent=4
        )

    if updated:
        print(f"âœ“ Updated: {sku}")
    else:
        print(f"âœ“ Added: {sku}")


def import_products_to_database(
    product_items: list[dict[str, Any]],
) -> int:
    """Chuáº©n hĂ³a vĂ  upsert cĂ¡c sáº£n pháº©m vá»«a láº¥y vĂ o PostgreSQL."""

    if not product_items:
        raise ValueError("KhĂ´ng cĂ³ sáº£n pháº©m Ä‘á»ƒ import vĂ o database.")

    catalog = normalize_catalog(product_items)
    if not catalog["products"]:
        raise ValueError("Dá»¯ liá»‡u sáº£n pháº©m khĂ´ng thá»ƒ chuáº©n hĂ³a.")

    variant_count = sum(
        len(product["variants"])
        for product in catalog["products"].values()
    )
    image_count = sum(
        len(product["images"])
        for product in catalog["products"].values()
    )

    print(
        "\nÄang import database: "
        f"products={len(catalog['products'])}, "
        f"variants={variant_count}, images={image_count}"
    )

    with database_connection() as connection:
        initialize_schema(connection)
        return import_catalog(connection, catalog)

def main() -> None:
    print("====================================")
    print("  Láº¤Y Sáº¢N PHáº¨M SHOPIFY THEO SKU")
    print("====================================")
    print("Nháº­p 'exit' hoáº·c 'q' Ä‘á»ƒ thoĂ¡t chÆ°Æ¡ng trĂ¬nh.")

    while True:
        print("\n------------------------------------")

        sku = input(
            "Nháº­p mĂ£ SKU sáº£n pháº©m: "
        ).strip()

        # ThoĂ¡t chÆ°Æ¡ng trĂ¬nh
        if sku.lower() in {"exit", "quit", "q"}:
            print("\nÄĂ£ káº¿t thĂºc chÆ°Æ¡ng trĂ¬nh.")
            break

        if not sku:
            print("Lá»—i: Báº¡n chÆ°a nháº­p mĂ£ SKU.")
            continue

        try:
            matching_products = find_products_by_sku(sku)

            if not matching_products:
                print(
                    f"KhĂ´ng tĂ¬m tháº¥y sáº£n pháº©m cĂ³ SKU: "
                    f"{normalize_sku(sku)}"
                )
                continue

            print(
                "\nTĂ¬m tháº¥y "
                f"{len(matching_products)} Shopify Product "
                f"cĂ¹ng mĂ£ {normalize_sku(sku)}."
            )

            for product_data in matching_products:
                # Má»—i mĂ u cĂ³ thá»ƒ lĂ  má»™t Shopify Product riĂªng.
                save_product(product_data)
                print_product_summary(product_data)

            image_result = sync_product_images(
                matching_products,
                remove_stale=False,
            )

            sync_run_id = import_products_to_database(
                matching_products
            )

            print("\n========== Táº O IMAGE EMBEDDING ==========")

            try:
                build_product_image_embeddings()
            except Exception as error:
                print(
                    "Cáº£nh bĂ¡o: sáº£n pháº©m Ä‘Ă£ Ä‘Æ°á»£c import nhÆ°ng "
                    f"khĂ´ng thá»ƒ táº¡o embedding: {error}"
                )

            print("\n========== HOĂ€N THĂ€NH ==========")
            print(f"ÄĂ£ lÆ°u vĂ o: {PRODUCTS_FILE}")
            print(
                "ÄĂ£ import/cáº­p nháº­t PostgreSQL: "
                f"sync_run_id={sync_run_id}"
            )
            print(
                "áº¢nh local: "
                f"táº£i má»›i={image_result['downloaded']}, "
                f"Ä‘Ă£ cĂ³={image_result['skipped']}, "
                f"lá»—i={image_result['failed']}"
            )

        except KeyboardInterrupt:
            print("\n\nÄĂ£ dá»«ng chÆ°Æ¡ng trĂ¬nh.")
            break

        except Exception as error:
            print(f"\nLá»—i: {error}")

if __name__ == "__main__":
    main()

