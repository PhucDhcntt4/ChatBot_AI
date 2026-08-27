import logging
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.logging_config import setup_logging


class LoggingConfigTests(unittest.TestCase):
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
