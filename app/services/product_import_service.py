import json
import logging
import os
import re
from typing import Any

import requests
from dotenv import load_dotenv  # type: ignore

load_dotenv()
logger = logging.getLogger("product_import")


SHOP = os.getenv("SHOP")
TOKEN = os.getenv("SHOPIFY_TOKEN")
API_VERSION = os.getenv("SHOPIFY_API_VERSION")

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
          pageInfo {
            hasNextPage
            endCursor
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
    Kiểm tra các biến cấu hình Shopify.
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
            "Thiếu biến môi trường trong file .env: "
            + ", ".join(missing)
        )


def shopify_graphql(
    query: str,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Gọi Shopify GraphQL Admin API.
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
            "Shopify API phản hồi quá thời gian."
        ) from error

    except requests.RequestException as error:
        raise RuntimeError(
            f"Không thể kết nối Shopify API: {error}"
        ) from error

    try:
        result = response.json()

    except ValueError as error:
        raise RuntimeError(
            "Shopify trả về dữ liệu không phải JSON."
        ) from error

    if result.get("errors"):
        raise RuntimeError(
            "Shopify GraphQL lỗi:\n"
            + json.dumps(
                result["errors"],
                ensure_ascii=False,
                indent=2,
            )
        )

    if "data" not in result:
        raise RuntimeError(
            "Shopify không trả về trường data."
        )

    return result["data"]


def normalize_sku(sku: str) -> str:
    """
    Chuẩn hóa SKU người dùng nhập.
    """

    return sku.strip().upper()


def escape_search_value(value: str) -> str:
    """
    Escape giá trị dùng trong Shopify search query.
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
    Kiểm tra mã mẫu trên SKU, handle và mô tả sản phẩm.

    Một số màu được quản lý thành Shopify Product riêng và có thể dùng
    SKU variant khác, trong khi mã mẫu vẫn nằm trong handle/mô tả.
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
        r"(?:MÃ|MA)\s*SẢN\s*PHẨM\s*:\s*"
        + re.escape(normalized_code)
        + r"\b",
        re.IGNORECASE,
    )

    return bool(code_pattern.search(description))


def get_all_product_variants(
    product_id: str,
) -> list[dict[str, Any]]:
    """
    Lấy toàn bộ variants của một sản phẩm bằng phân trang Shopify.
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
                f"Không tìm thấy sản phẩm Shopify: {product_id}"
            )

        variants_connection = product.get("variants", {})
        nodes = variants_connection.get("nodes", [])

        if not isinstance(nodes, list):
            raise RuntimeError(
                "Shopify trả về danh sách variants không hợp lệ."
            )

        all_variants.extend(nodes)

        page_info = variants_connection.get("pageInfo", {})

        if not page_info.get("hasNextPage"):
            break

        cursor = page_info.get("endCursor")

        if not cursor:
            raise RuntimeError(
                "Shopify báo còn trang variants nhưng không trả endCursor."
            )

    return all_variants


def find_products_by_sku(
    sku: str,
) -> list[dict[str, Any]]:
    """
    Tìm tất cả sản phẩm ACTIVE chứa variant có SKU chính xác.

    Shopify có thể quản lý mỗi màu thành một Product riêng nhưng
    các Product đó vẫn dùng chung một mã SKU.
    """

    normalized_sku = normalize_sku(sku)

    if not normalized_sku:
        raise ValueError("Mã SKU không được để trống.")

    escaped_sku = escape_search_value(normalized_sku)

    variants: list[dict[str, Any]] = []
    cursor: str | None = None

    while True:
        data = shopify_graphql(
            PRODUCT_BY_SKU_QUERY,
            {
                # Tìm mặc định trên nhiều trường thay vì chỉ SKU.
                # Cần thiết khi mỗi màu là một Product riêng.
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
                "Shopify trả về kết quả tìm SKU không hợp lệ."
            )

        variants.extend(page_nodes)

        page_info = variants_connection.get("pageInfo", {})

        if not page_info.get("hasNextPage"):
            break

        cursor = page_info.get("endCursor")

        if not cursor:
            raise RuntimeError(
                "Shopify báo còn kết quả SKU nhưng không trả endCursor."
            )

    if not variants:
        return []

    # Shopify search có thể trả về nhiều kết quả gần giống.
    # Kiểm tra mã trên SKU, handle hoặc mô tả bằng Python.
    code_matches = [
        variant
        for variant in variants
        if product_contains_code(variant, normalized_sku)
    ]

    if not code_matches:
        return []

    # Chỉ lấy sản phẩm đang ACTIVE.
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
            f"Đã tìm thấy SKU '{normalized_sku}', "
            "nhưng sản phẩm không ở trạng thái ACTIVE."
        )

    products_by_id: dict[str, dict[str, Any]] = {}

    for matched_variant in active_matches:
        product = matched_variant["product"]
        product_id = product.get("id")

        if not product_id:
            continue

        # Một Product có nhiều size cùng SKU nên cần khử trùng theo
        # Shopify Product ID trước khi tải toàn bộ variants.
        if product_id in products_by_id:
            continue

        included = product.get("variants") or {}
        all_variants = (
            get_all_product_variants(product_id)
            if (included.get("pageInfo") or {}).get("hasNextPage")
            else list(included.get("nodes") or [])
        )
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
