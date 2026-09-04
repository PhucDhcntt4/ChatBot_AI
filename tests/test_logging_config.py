import logging
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from app.logging_config import log_bot_response, setup_logging


class LoggingConfigTests(unittest.TestCase):
    def test_bot_response_log_contains_phase_send_and_total_times(self):
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        logger = logging.Logger("bot_response_test", level=logging.INFO)
        logger.addHandler(handler)
        response = SimpleNamespace(
            status="product_found",
            intent=SimpleNamespace(value="product_information"),
            provider="gemini",
            model="gemini-test",
            products=[{"product_code": "ABC01"}],
            media=[object()],
            timing={"planner": 1.25, "executor": 0.05, "presenter": 0.7},
        )

        log_bot_response(
            logger,
            channel="facebook",
            session_id="customer-1",
            response=response,
            send_seconds=0.4,
            total_seconds=2.4,
        )

        output = stream.getvalue()
        self.assertIn("BOT RESPONSE channel=facebook", output)
        self.assertIn("planner=1.250s", output)
        self.assertIn("send=0.400s", output)
        self.assertIn("total=2.400s", output)

    def test_rotating_log_files_receive_info_and_error(self):
        with TemporaryDirectory() as temporary_directory:
            handlers = setup_logging(
                service_name="unit_test_logging",
                log_dir=temporary_directory,
                enable_file=True,
            )
            logger = logging.getLogger("unit_test_logging.case")
            logger.info("history info test")
            logger.error("history error test")
            for handler in handlers:
                handler.flush()

            info_text = (
                Path(temporary_directory) / "unit_test_logging.log"
            ).read_text(encoding="utf-8")
            error_text = (
                Path(temporary_directory) / "unit_test_logging_error.log"
            ).read_text(encoding="utf-8")

            self.assertIn("history info test", info_text)
            self.assertIn("history error test", info_text)
            self.assertIn("history error test", error_text)
            self.assertNotIn("history info test", error_text)

            # Windows cannot remove open rotating files. Detach and close the
            # test-only handlers before TemporaryDirectory cleanup.
            for handler in handlers:
                logging.getLogger().removeHandler(handler)
                for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
                    logging.getLogger(name).removeHandler(handler)
                handler.close()


if __name__ == "__main__":
    unittest.main()
