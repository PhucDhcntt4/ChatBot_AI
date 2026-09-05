import logging
import time
from collections.abc import Iterator
from typing import Any

from app.database.connection import database_connection
from app.scripts.import_products_to_db import normalize_text, selected_option


logger = logging.getLogger("inventory_sync_scheduler")

# Shopify filters aggregate variant inventory across locations.
LOW_INVENTORY_SEARCH = "inventory_quantity:<=2 AND product_status:ACTIVE"
LOW_INVENTORY_QUERY = """
query LowInventoryVariants($first: Int!, $after: String, $query: String!) {
  productVariants(first: $first, after: $after, query: $query, sortKey: ID) {
    nodes {
      id
      sku
      inventoryQuantity
      selectedOptions { name value }
      product { status }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def _fetch_inventory_page(variables: dict[str, Any]) -> dict[str, Any]:
    # Reuse the existing authenticated client, without invoking product/image sync.
    from app.services.product_import_service import shopify_graphql

    return shopify_graphql(LOW_INVENTORY_QUERY, variables)


def iter_low_inventory_variants() -> Iterator[dict[str, Any]]:
    cursor = None
    cursors: set[str] = set()
    seen: set[str] = set()
    page_number = 0

    while True:
        data = _fetch_inventory_page({
            "first": 100,
            "after": cursor,
            "query": LOW_INVENTORY_SEARCH,
        })
        connection = data.get("productVariants")
        if not isinstance(connection, dict):
            raise RuntimeError("Shopify không trả về productVariants hợp lệ.")
        nodes = connection.get("nodes")
        info = connection.get("pageInfo")
        if (
            not isinstance(nodes, list)
            or not all(isinstance(node, dict) for node in nodes)
            or not isinstance(info, dict)
            or type(info.get("hasNextPage")) is not bool
        ):
            raise RuntimeError("Shopify trả dữ liệu phân trang tồn kho không hợp lệ.")

        next_cursor = info.get("endCursor")
        if info["hasNextPage"] and (
            not isinstance(next_cursor, str)
            or not next_cursor
            or next_cursor in cursors
        ):
            raise RuntimeError("Shopify trả cursor thiếu hoặc lặp; dừng để tránh bỏ sót.")

        page_number += 1
        logger.info(
            "INVENTORY SYNC Shopify page=%s received=%s filter=%s",
            page_number, len(nodes), LOW_INVENTORY_SEARCH,
        )
        for node in nodes:
            variant_id = node.get("id")
            if isinstance(variant_id, str) and variant_id:
                if variant_id in seen:
                    continue
                seen.add(variant_id)
            yield node

        if not info["hasNextPage"]:
            return
        cursors.add(next_cursor)
        cursor = next_cursor


def sync_low_inventory() -> dict[str, Any]:
    started = time.monotonic()
    stats = dict(checked=0, updated=0, unchanged=0, unmatched=0, skipped=0, failed=0)
    completed = False
    logger.info("INVENTORY SYNC bắt đầu source=shopify filter=%s", LOW_INVENTORY_SEARCH)

    try:
        for variant in iter_low_inventory_variants():
            stats["checked"] += 1
            quantity = variant.get("inventoryQuantity")
            sku = str(variant.get("sku") or "").strip().upper()
            variant_id = variant.get("id")
            product = variant.get("product")

            # Defensive validation of Shopify results; never infer missing stock as zero.
            if (
                type(quantity) is not int
                or quantity > 2
                or not isinstance(product, dict)
                or product.get("status") != "ACTIVE"
                or not sku
                or not isinstance(variant_id, str)
                or not variant_id
            ):
                stats["skipped"] += 1
                continue

            try:
                color = normalize_text(selected_option(variant, "Color"))
                size = selected_option(variant, "Size") or ""
                with database_connection() as connection:
                    matches = connection.execute(
                        """
                        SELECT pv.id
                        FROM product_variants pv
                        JOIN products p ON p.id = pv.product_id
                        WHERE p.status = 'ACTIVE'
                          AND pv.external_id = %s
                          AND pv.sku = %s
                          AND pv.color_normalized = %s
                          AND pv.size = %s
                        LIMIT 2
                        FOR UPDATE OF pv
                        """,
                        (variant_id, sku, color, size),
                    ).fetchall()

                    if len(matches) != 1:
                        outcome = "unmatched"
                        logger.warning(
                            "INVENTORY SYNC không khớp duy nhất sku=%s variant=%s matches=%s",
                            sku, variant_id, len(matches),
                        )
                    else:
                        result = connection.execute(
                            """
                            UPDATE product_variants
                            SET inventory_quantity = %s,
                                available = %s,
                                updated_at = NOW()
                            WHERE id = %s
                              AND (
                                  inventory_quantity IS DISTINCT FROM %s
                                  OR available IS DISTINCT FROM %s
                              )
                            """,
                            (quantity, quantity > 0, matches[0]["id"], quantity, quantity > 0),
                        )
                        outcome = "updated" if result.rowcount else "unchanged"
                # Count only after a successful commit.
                stats[outcome] += 1
            except Exception:
                stats["failed"] += 1
                logger.exception("INVENTORY SYNC lỗi sku=%s variant=%s", sku, variant_id)

            logger.info(
                "INVENTORY SYNC checked=%s updated=%s unchanged=%s unmatched=%s skipped=%s failed=%s",
                *stats.values(),
            )
        completed = True
    finally:
        status = (
            "completed_with_errors" if stats["failed"] else "completed"
        ) if completed else "interrupted"
        logger.info(
            "INVENTORY SYNC kết thúc status=%s stats=%s time=%.1fs",
            status, stats, time.monotonic() - started,
        )

    return {"status": status, **stats}
