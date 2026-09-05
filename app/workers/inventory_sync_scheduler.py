import logging
import math
import time
from datetime import datetime, timedelta, timezone

from dotenv import dotenv_values # type: ignore

from app.config import PROJECT_ROOT
from app.logging_config import setup_logging
from app.services.scheduled_inventory_sync import sync_low_inventory


logger = logging.getLogger("inventory_sync_scheduler")

ENV_PATH = PROJECT_ROOT / ".env"
VIETNAM_TZ = timezone(timedelta(hours=7))
CHECK_SECONDS = 5


def read_config() -> tuple[bool, float]:
    if not ENV_PATH.is_file():
        raise ValueError("Không tìm thấy file .env")

    values = dotenv_values(ENV_PATH, encoding="utf-8-sig")

    enabled = (
        values.get("INVENTORY_SYNC_ENABLED") or "false"
    ).strip().lower()

    if enabled not in {"true", "false"}:
        raise ValueError(
            "INVENTORY_SYNC_ENABLED chỉ nhận true hoặc false"
        )

    if enabled == "false":
        return False, 0.0

    hours = float(
        values.get("INVENTORY_SYNC_INTERVAL_HOURS") or "3"
    )

    if not math.isfinite(hours) or hours <= 0:
        raise ValueError(
            "INVENTORY_SYNC_INTERVAL_HOURS phải là số dương hữu hạn"
        )

    return True, hours * 3600


def log_next_run(seconds: float) -> None:
    next_time = datetime.now(VIETNAM_TZ) + timedelta(
        seconds=seconds
    )
    logger.info(
        "INVENTORY SYNC lần tiếp theo=%s",
        next_time.isoformat(),
    )


def main() -> None:
    logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)

    setup_logging(service_name="inventory_sync_scheduler")
    setup_logging(service_name="inventory_sync_scheduler")
    logger.info("INVENTORY SYNC scheduler sẵn sàng")

    previous_config = None
    next_run = None
    last_error = None

    try:
        while True:
            try:
                config = read_config()

            except (OSError, ValueError, OverflowError) as error:
                message = str(error)

                if message != last_error:
                    logger.error(
                        "INVENTORY SYNC cấu hình lỗi: %s",
                        message,
                    )

                last_error = message
                previous_config = None
                next_run = None

                time.sleep(CHECK_SECONDS)
                continue

            last_error = None
            enabled, interval = config

            if config != previous_config:
                previous_config = config

                if enabled:
                    next_run = time.monotonic() + interval
                    log_next_run(interval)
                else:
                    next_run = None
                    logger.info("INVENTORY SYNC đã tắt")

            if (
                enabled
                and next_run is not None
                and time.monotonic() >= next_run
            ):
                try:
                    sync_low_inventory()

                except Exception:
                    logger.exception(
                        "INVENTORY SYNC tác vụ thất bại"
                    )

                finally:
                    # Chờ đủ khoảng thời gian sau khi lượt này kết thúc.
                    next_run = time.monotonic() + interval
                    log_next_run(interval)

            time.sleep(CHECK_SECONDS)

    except KeyboardInterrupt:
        logger.info("INVENTORY SYNC scheduler đã dừng")


if __name__ == "__main__":
    main()