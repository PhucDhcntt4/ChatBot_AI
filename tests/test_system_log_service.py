from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.services.system_log_service import SystemLogError, SystemLogService


class SystemLogServiceTests(unittest.TestCase):
    def test_lists_parses_filters_and_redacts_logs(self):
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            (directory / "app.log").write_text(
                "2026-09-17 10:00:00 | INFO | uvicorn.error | "
                "pid=1 thread=MainThread | BOT RESPONSE total=1.2s\n"
                "2026-09-17 10:01:00 | ERROR | uvicorn.error | "
                "pid=1 thread=MainThread | token=private-value failed\n"
                "Traceback line\n",
                encoding="utf-8",
            )
            (directory / "ignored.txt").write_text("not a log", encoding="utf-8")
            service = SystemLogService(directory)

            self.assertEqual(
                [item["name"] for item in service.list_files()],
                ["app.log"],
            )
            result = service.read_entries(
                file_name="app.log", level="ERROR", search="failed", limit=25
            )
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["entries"][0]["level"], "ERROR")
            self.assertIn("Traceback line", result["entries"][0]["message"])
            self.assertIn("token=[REDACTED]", result["entries"][0]["message"])
            self.assertNotIn("private-value", result["entries"][0]["raw"])

    def test_rejects_path_traversal_and_paginates_newest_first(self):
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            (directory / "worker.log").write_text(
                "2026-09-17 10:00:00 | INFO | worker | pid=1 | first\n"
                "2026-09-17 10:01:00 | INFO | worker | pid=1 | second\n",
                encoding="utf-8",
            )
            service = SystemLogService(directory)
            page = service.read_entries(file_name="worker.log", limit=25)
            self.assertEqual(page["entries"][0]["message"], "second")
            with self.assertRaises(SystemLogError):
                service.read_entries(file_name="../worker.log", limit=25)

    def test_clears_one_or_all_log_files_without_deleting_them(self):
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            first = directory / "app.log"
            second = directory / "worker.log"
            first.write_text("first history", encoding="utf-8")
            second.write_text("second history", encoding="utf-8")
            service = SystemLogService(directory)

            one = service.clear("app.log")
            self.assertEqual(one["files"], ["app.log"])
            self.assertEqual(first.read_text(encoding="utf-8"), "")
            self.assertTrue(first.exists())
            self.assertGreater(second.stat().st_size, 0)

            all_logs = service.clear(SystemLogService.ALL_FILES)
            self.assertEqual(all_logs["file_count"], 2)
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())
            self.assertEqual(second.read_text(encoding="utf-8"), "")
            with self.assertRaises(SystemLogError):
                service.clear("../app.log")


if __name__ == "__main__":
    unittest.main()
