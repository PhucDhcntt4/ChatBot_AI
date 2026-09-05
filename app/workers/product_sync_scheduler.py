import logging
import re
import time
from datetime import datetime, timedelta, timezone

from dotenv import dotenv_values # type: ignore

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

    # Đọc trực tiếp từ file để nhận giờ mới mà không cần restart.
    values = dotenv_values(ENV_PATH, encoding="utf-8-sig")

    enabled_text = (
        values.get("PRODUCT_AUTO_SYNC_ENABLED") or "false"
    ).strip().lower()

    if enabled_text not in {"true", "false"}:
        raise ValueError(
            "PRODUCT_AUTO_SYNC_ENABLED chỉ nhận true hoặc false"
        )

    if enabled_text == "false":
        return False, 0, 0

    clock = (
        values.get("PRODUCT_AUTO_SYNC_TIME") or ""
    ).strip()

    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", clock):
        raise ValueError(
            "PRODUCT_AUTO_SYNC_TIME phải có dạng HH:MM, "
            "từ 00:00 đến 23:59"
        )

    hour, minute = map(int, clock.split(":"))
    return True, hour, minute


def next_occurrence(
    now: datetime,
    hour: int,
    minute: int,
) -> datetime:
    target = now.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )

    # Nếu giờ hôm nay đã qua thì chờ ngày hôm sau.
    if target <= now:
        target += timedelta(days=1)

    return target


def main() -> None:
    setup_logging(service_name="product_sync_scheduler")

    logger.info("AUTO SYNC scheduler sẵn sàng timezone=UTC+7")

    previous_config = None
    next_run = None
    last_config_error = None

    try:
        while True:
            try:
                config = read_schedule()

            except (OSError, ValueError) as error:
                error_text = str(error)

                # Không in lại cùng một lỗi sau mỗi 5 giây.
                if error_text != last_config_error:
                    logger.error(
                        "AUTO SYNC cấu hình không hợp lệ: %s",
                        error_text,
                    )

                last_config_error = error_text
                previous_config = None
                next_run = None

                time.sleep(CHECK_SECONDS)
                continue

            if last_config_error is not None:
                logger.info("AUTO SYNC cấu hình đã hợp lệ")

            last_config_error = None
            now = datetime.now(VIETNAM_TZ)
            enabled, hour, minute = config

            # Tính lại lịch khi bật/tắt hoặc thay đổi giờ.
            if config != previous_config:
                previous_config = config

                next_run = (
                    next_occurrence(now, hour, minute)
                    if enabled
                    else None
                )

                if enabled:
                    logger.info(
                        "AUTO SYNC lần tiếp theo=%s",
                        next_run.isoformat(),
                    )
                else:
                    logger.info("AUTO SYNC đã tắt lịch")

            if enabled and next_run is not None and now >= next_run:
                # Máy ngủ qua ngày: bỏ lịch cũ, không chạy bù nhiều lượt.
                if now.date() > next_run.date():
                    next_run = next_occurrence(now, hour, minute)

                    logger.info(
                        "AUTO SYNC bỏ lịch đã lỡ, lần tiếp theo=%s",
                        next_run.isoformat(),
                    )

                else:
                    logger.info(
                        "AUTO SYNC đến giờ chạy scheduled_for=%s",
                        next_run.isoformat(),
                    )

                    try:
                        # Chạy tuần tự, chờ hoàn tất mới tiếp tục vòng lặp.
                        sync_all_products()

                    except Exception:
                        logger.exception("AUTO SYNC tác vụ thất bại")

                    finally:
                        next_run = next_occurrence(
                            datetime.now(VIETNAM_TZ),
                            hour,
                            minute,
                        )

                        logger.info(
                            "AUTO SYNC lần tiếp theo=%s",
                            next_run.isoformat(),
                        )

            time.sleep(CHECK_SECONDS)

    except KeyboardInterrupt:
        logger.info("AUTO SYNC scheduler đã dừng")


if __name__ == "__main__":
    main()