# Đồng bộ sản phẩm hằng ngày theo giờ trong .env

Tài liệu này chứa code để bạn thêm vào dự án. Các file Python bên dưới CHƯA được tạo trong source.

Luồng: scheduler đọc `.env` → đến giờ Việt Nam → lấy mã sản phẩm ACTIVE trong PostgreSQL → gọi Shopify → tải ảnh → cập nhật database → tạo embedding.

Không tạo bảng lịch, không dùng Redis cho tác vụ này. PostgreSQL vẫn lưu dữ liệu sản phẩm và các bản ghi import mà pipeline hiện có vốn đã sử dụng. Không cần cài thêm thư viện.

## 1. Thêm cấu hình vào .env

Thêm đúng một lần, không ghi đè các cấu hình khác:

```dotenv
# Đồng bộ sản phẩm tự động hằng ngày theo giờ Việt Nam (UTC+7)
PRODUCT_AUTO_SYNC_ENABLED=true
PRODUCT_AUTO_SYNC_TIME=02:00
```

`02:00` nghĩa là 2 giờ sáng hằng ngày. Giờ phải có dạng HH:MM, từ 00:00 đến 23:59. Tắt bằng `PRODUCT_AUTO_SYNC_ENABLED=false`.

Trang `/admin/environment` hiện đọc các biến có trong `.env`, nên sau khi thêm hai dòng này, tải lại trang để chỉnh chúng trên giao diện.

## 2. Tạo app/services/scheduled_product_sync.py

Service chạy trực tiếp bằng các hàm đã có. Không import `product_sync_manager`, không gọi endpoint đồng bộ thủ công.

```python
import logging
import time

from app.database.connection import database_connection


logger = logging.getLogger("product_sync_scheduler")


def sync_all_products() -> dict:
    # Chỉ nạp thư viện ảnh/AI khi thực sự đến giờ chạy.
    from app.services.product_import_service import (
        find_products_by_sku,
        import_products_to_database,
    )
    from app.scripts.sync_product_images import sync_product_images
    from app.scripts.build_product_image_embeddings import main as build_embeddings

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
        str(row["product_code"]).strip() for row in rows
        if str(row["product_code"]).strip()
    ))
    succeeded = 0
    failed = 0
    failed_images = 0
    embedding_result = None
    embedding_error = False

    if not codes:
        logger.info("AUTO SYNC skipped: không có sản phẩm ACTIVE")
        return {"status": "skipped", "total": 0}

    logger.info("AUTO SYNC started total=%s", len(codes))
    for index, code in enumerate(codes, start=1):
        try:
            products = find_products_by_sku(code)
            if not products:
                raise ValueError("Không tìm thấy sản phẩm ACTIVE trên Shopify")

            images = sync_product_images(products)
            failed_images += images["failed"]
            import_products_to_database(
                products,
                local_images=images["local_images"],
            )
            succeeded += 1
            logger.info("AUTO SYNC product=%s progress=%s/%s", code, index, len(codes))
        except Exception:
            failed += 1
            logger.exception("AUTO SYNC product failed code=%s", code)

    # Tạo/cập nhật các vector còn thiếu hoặc có checksum thay đổi.
    # Hàm hiện có sẽ quét ảnh ACTIVE của toàn catalog.
    if succeeded:
        try:
            embedding_result = build_embeddings()
        except Exception:
            embedding_error = True
            logger.exception("AUTO SYNC embedding failed")

    has_errors = (
        failed > 0
        or failed_images > 0
        or embedding_error
        or bool((embedding_result or {}).get("failed", 0))
    )
    result = {
        "status": "completed_with_errors" if has_errors else "completed",
        "total": len(codes),
        "succeeded": succeeded,
        "failed": failed,
        "failed_images": failed_images,
        "embedding": embedding_result,
        "embedding_error": embedding_error,
        "seconds": round(time.monotonic() - started, 2),
    }
    logger.info("AUTO SYNC finished result=%s", result)
    return result
```

Service này đưa dữ liệu nhận được trực tiếp vào hàm import database, không cần bước ghi snapshot `products.json` của luồng thủ công.

Phạm vi vẫn giống nút “Đồng bộ tất cả”: sản phẩm ACTIVE đã có trong database. Nó chưa khám phá SKU mới trên Shopify và chưa tự đánh dấu sản phẩm đã bị xóa/ẩn trên Shopify; các mã không tìm thấy được báo lỗi trong log.

## 3. Tạo app/workers/product_sync_scheduler.py

```python
import logging
import re
import time
from datetime import datetime, timedelta, timezone

from dotenv import dotenv_values

from app.config import PROJECT_ROOT
from app.logging_config import setup_logging
from app.services.scheduled_product_sync import sync_all_products


logger = logging.getLogger("product_sync_scheduler")
ENV_PATH = PROJECT_ROOT / ".env"
VIETNAM_TZ = timezone(timedelta(hours=7), name="UTC+7")
CHECK_SECONDS = 5


def read_schedule() -> tuple[bool, int, int]:
    if not ENV_PATH.is_file():
        raise ValueError("Không tìm thấy file .env")

    # Đọc file trực tiếp để nhận thay đổi, không dùng os.getenv đã nạp lúc startup.
    values = dotenv_values(ENV_PATH, encoding="utf-8-sig")
    enabled_text = (values.get("PRODUCT_AUTO_SYNC_ENABLED") or "false").strip().lower()
    if enabled_text not in {"true", "false"}:
        raise ValueError("PRODUCT_AUTO_SYNC_ENABLED chỉ nhận true hoặc false")
    if enabled_text == "false":
        return False, 0, 0

    clock = (values.get("PRODUCT_AUTO_SYNC_TIME") or "").strip()
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", clock):
        raise ValueError("PRODUCT_AUTO_SYNC_TIME phải có dạng HH:MM, từ 00:00 đến 23:59")

    hour, minute = map(int, clock.split(":"))
    return True, hour, minute


def next_occurrence(now: datetime, hour: int, minute: int) -> datetime:
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def main() -> None:
    setup_logging(service_name="product_sync_scheduler")
    logger.info("AUTO SYNC scheduler ready timezone=UTC+7")
    previous_config = None
    next_run = None
    last_config_error = None

    try:
        while True:
            try:
                config = read_schedule()
            except (OSError, ValueError) as error:
                # Cấu hình không hợp lệ: tạm dừng lịch, chỉ log khi lỗi thay đổi.
                error_text = str(error)
                if error_text != last_config_error:
                    logger.error("AUTO SYNC invalid config: %s", error_text)
                last_config_error = error_text
                previous_config = None
                next_run = None
                time.sleep(CHECK_SECONDS)
                continue

            if last_config_error is not None:
                logger.info("AUTO SYNC config valid again")
            last_config_error = None
            now = datetime.now(VIETNAM_TZ)
            enabled, hour, minute = config

            if config != previous_config:
                previous_config = config
                next_run = next_occurrence(now, hour, minute) if enabled else None
                if enabled:
                    logger.info("AUTO SYNC next_run=%s", next_run.isoformat())
                else:
                    logger.info("AUTO SYNC disabled")

            if enabled and next_run is not None and now >= next_run:
                # Nếu máy ngủ qua một ngày/lâu hơn, bỏ lần cũ, không chạy bù hàng loạt.
                if now.date() > next_run.date():
                    next_run = next_occurrence(now, hour, minute)
                    logger.info("AUTO SYNC missed schedule skipped next_run=%s", next_run.isoformat())
                else:
                    logger.info("AUTO SYNC triggered scheduled_for=%s", next_run.isoformat())
                    try:
                        # Chạy tuần tự: process này không tự khởi động lượt thứ hai khi đang bận.
                        sync_all_products()
                    except Exception:
                        logger.exception("AUTO SYNC run failed")
                    finally:
                        next_run = next_occurrence(datetime.now(VIETNAM_TZ), hour, minute)
                        logger.info("AUTO SYNC next_run=%s", next_run.isoformat())

            time.sleep(CHECK_SECONDS)
    except KeyboardInterrupt:
        logger.info("AUTO SYNC scheduler stopped")


if __name__ == "__main__":
    main()
```

Giờ Việt Nam ở đây cố định UTC+7, không phụ thuộc múi giờ Windows và không cần thêm thư viện timezone.

Các quy tắc của đoạn code:

- Khi khởi động hoặc đổi giờ: luôn chọn lần chạy trong tương lai. Khởi động lúc 02:05 với lịch 02:00 sẽ chờ ngày mai.
- Trong lúc chờ: đọc lại `.env` mỗi 5 giây. Chỉ hai biến lịch được cập nhật động; token Shopify, database và model vẫn nạp theo cơ chế hiện có của dự án.
- Đến giờ: bắt đầu ở lần kiểm tra kế tiếp, thông thường trễ tối đa khoảng 5 giây khi hệ thống hoạt động bình thường.
- Trong lúc đồng bộ: thao tác tắt/đổi lịch được nhận sau khi lượt hiện tại kết thúc; không hủy lượt đang chạy.
- Lượt lỗi được ghi log, không tự chạy lại cả catalog liên tục.
- Chỉ chạy MỘT process scheduler. Code không có khóa giữa nhiều process. Nếu mở hai scheduler, cả hai đều có thể chạy.
- Nút đồng bộ thủ công vẫn sử dụng worker Redis và chưa dùng chung khóa với scheduler. Tránh bấm đồng bộ thủ công trong giờ scheduler đang chạy; muốn bảo đảm tự động chống chồng giữa hai luồng cần bổ sung khóa dùng chung sau này.

## 4. Chạy và kiểm tra

Trong PowerShell, chạy từng lệnh:

```powershell
cd "D:\ĐÔNG HẢI\DATA\BOT_Conversation_V2"
.\.venv\Scripts\Activate.ps1
python -m compileall -q app/services/scheduled_product_sync.py app/workers/product_sync_scheduler.py
python -m app.workers.product_sync_scheduler
```

Terminal sẽ báo lịch tiếp theo. Giữ process này hoạt động; đóng trình duyệt không ảnh hưởng. `start.ps1` hiện chưa tự khởi động scheduler mới này.

Kiểm thử thủ công trên môi trường thử nghiệm:

1. Đặt giờ chạy khoảng 2 phút sau giờ Việt Nam hiện tại.
2. Bật lịch, khởi động scheduler; kiểm tra log `next_run` đúng.
3. Đổi giờ khi scheduler đang chờ; sau khoảng 5 giây phải thấy `next_run` mới.
4. Đổi enabled=false; phải thấy log disabled và không chạy khi tới giờ.
5. Bật lại, đặt một giờ tương lai và chờ; log phải có triggered, started, từng SKU và finished.
6. Xem trạng thái finished: cần kiểm tra cả failed_images và embedding_error/embedding.failed.
7. Khởi động lại sau giờ hẹn; lịch tiếp theo phải là ngày hôm sau.

Bước 5 thực sự gọi Shopify và cập nhật dữ liệu sản phẩm/embedding. Chọn môi trường thử hoặc thời điểm phù hợp để kiểm tra.

Lượt tự động không xuất hiện trong thanh tiến độ Redis của trang sản phẩm. Xem log scheduler và tải lại danh sách sản phẩm để xem dữ liệu đã cập nhật.

Trên production, cấu hình scheduler thành service thường trực, một instance, dùng cùng thư mục dự án/.env và có quyền ghi thư mục ảnh. Không chạy scheduler trong request FastAPI hoặc trong JavaScript trình duyệt.
