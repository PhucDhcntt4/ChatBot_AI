import argparse
import logging
import time

from app.logging_config import setup_logging
from app.services.product_sync_service import product_sync_manager


logger = logging.getLogger("product_sync_worker")


def run_worker(*, once: bool = False, poll_interval: float = 2.0) -> None:
    logger.info("Product sync worker đã sẵn sàng")
    recovered = product_sync_manager.recover_stale_jobs()
    if recovered:
        logger.warning("Đã phục hồi %s job bị treo", recovered)

    recovery_interval = max(
        5.0,
        min(60.0, product_sync_manager.stale_seconds / 3),
    )
    next_recovery = time.monotonic() + recovery_interval

    while True:   
        if time.monotonic() >= next_recovery:
            recovered = product_sync_manager.recover_stale_jobs()
            if recovered:
                logger.warning("Đã phục hồi %s job bị treo", recovered)
            next_recovery = time.monotonic() + recovery_interval

        job_id = product_sync_manager.claim_next()
        if not job_id:
            if once:
                return
            continue
        logger.info("Worker bắt đầu job=%s", job_id)
        try:
            product_sync_manager.run(job_id)
        except Exception:
            logger.exception("Worker xử lý thất bại job=%s", job_id)
        else:
            logger.info("Worker hoàn tất job=%s", job_id)
        if once:
            return


def main() -> None:
    parser = argparse.ArgumentParser(description="Worker đồng bộ sản phẩm và embedding")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    args = parser.parse_args()
    setup_logging(service_name="product_sync_worker")
    run_worker(once=args.once, poll_interval=max(0.2, args.poll_interval))


if __name__ == "__main__":
    main()
