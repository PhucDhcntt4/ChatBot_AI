import tempfile
import unittest
from pathlib import Path

from app.services.environment_service import (
    EnvironmentFileError,
    EnvironmentFileService,
)


class EnvironmentFileServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / ".env"
        self.path.write_text(
            "# Log\n"
            "# Mức log của ứng dụng\n"
            "LOG_LEVEL=INFO\n"
            "PORT=8000  # Cổng web\n"
            "\n"
            "# Secrets\n"
            "API_KEY=super-secret\n",
            encoding="utf-8",
        )
        self.service = EnvironmentFileService(self.path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_comments_and_admin_editable_secret_values_are_returned(self):
        payload = self.service.read_public()

        self.assertEqual(payload["variable_count"], 3)
        self.assertEqual(payload["sections"][0]["title"], "Log")
        log_level = payload["sections"][0]["variables"][0]
        api_key = payload["sections"][1]["variables"][0]
        self.assertEqual(log_level["description"], "Mức log của ứng dụng")
        self.assertEqual(api_key["value"], "super-secret")
        self.assertTrue(api_key["configured"])
        self.assertTrue(api_key["sensitive"])

    def test_updates_only_existing_keys_and_preserves_inline_comment(self):
        result = self.service.update({
            "LOG_LEVEL": "DEBUG",
            "PORT": "9000",
            "API_KEY": "new#secret",
        })

        content = self.path.read_text(encoding="utf-8")
        self.assertEqual(result["updated_count"], 3)
        self.assertIn("LOG_LEVEL=DEBUG", content)
        self.assertIn("PORT=9000  # Cổng web", content)
        self.assertIn('API_KEY="new#secret"', content)
        self.assertNotIn("super-secret", content)

    def test_rejects_unknown_keys_and_multiline_values(self):
        with self.assertRaises(EnvironmentFileError):
            self.service.update({"UNKNOWN_KEY": "value"})
        with self.assertRaises(EnvironmentFileError):
            self.service.update({"LOG_LEVEL": "INFO\nBROKEN=true"})

    def test_rejects_values_that_would_break_startup(self):
        with self.assertRaises(EnvironmentFileError):
            self.service.update({"LOG_LEVEL": "EVERYTHING"})
        with self.assertRaises(EnvironmentFileError):
            self.service.update({"CHANNEL_PROVIDER": "web,unknown"})


if __name__ == "__main__":
    unittest.main()
