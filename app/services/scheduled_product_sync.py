import logging
import time

from app.database.connection import database_connection


logger = logging.getLogger("product_sync_scheduler")


def sync_all_products() -> dict:
    # Chỉ nạp các thư viện nặng khi bắt đầu đồng bộ.
    from app.services.product_import_service import (
        find_products_by_sku,
        import_products_to_database,
    )
    from app.scripts.sync_product_images import sync_product_images
    from app.scripts.build_product_image_embeddings import (
        main as build_embeddings,
    )

    started = time.monotonic()

    with database_connection() as connection:
        rows = connection.execute(
            """
            SELECT product_code
            FROM products
            WHERE status = 'ACTIVE'
              AND COALESCE(product_code, '') <> ''
            ORDER BY product_code
            """
        ).fetchall()

    codes = list(dict.fromkeys(
        str(row["product_code"]).strip()
        for row in rows
        if str(row["product_code"]).strip()
    ))

    if not codes:
        logger.info("AUTO SYNC: không có sản phẩm ACTIVE để đồng bộ")
        return {"status": "skipped", "total": 0}

    succeeded = 0
    failed = 0
    failed_images = 0
    embedding_result = None
    embedding_error = False

    logger.info("AUTO SYNC bắt đầu total=%s", len(codes))

    for index, code in enumerate(codes, start=1):
        try:
            products = find_products_by_sku(code)

            if not products:
                raise ValueError(
                    "Không tìm thấy sản phẩm ACTIVE trên Shopify"
                )

            image_result = sync_product_images(products)
            failed_images += image_result["failed"]

            import_products_to_database(
                products,
                local_images=image_result["local_images"],
            )

            succeeded += 1

        except Exception:
            failed += 1
            logger.exception("AUTO SYNC lỗi product=%s", code)

        finally:
            logger.info(
                "AUTO SYNC [%s/%s | %.1f%%] "
                "Thành công: %s | Lỗi: %s | Còn lại: %s | Mã: %s",
                index,
                len(codes),
                index / len(codes) * 100,
                succeeded,
                failed,
                len(codes) - index,
                code,
            )

    if succeeded:
        try:
            logger.info("AUTO SYNC đang tạo/cập nhật embedding")
            embedding_result = build_embeddings()
        except Exception:
            embedding_error = True
            logger.exception("AUTO SYNC lỗi embedding")

    has_errors = (
        failed > 0
        or failed_images > 0
        or embedding_error
        or bool((embedding_result or {}).get("failed", 0))
    )

    result = {
        "status": (
            "completed_with_errors" if has_errors else "completed"
        ),
        "total": len(codes),
        "succeeded": succeeded,
        "failed": failed,
        "failed_images": failed_images,
        "embedding": embedding_result,
        "embedding_error": embedding_error,
        "seconds": round(time.monotonic() - started, 2),
    }

    logger.info("AUTO SYNC hoàn tất result=%s", result)
    return result