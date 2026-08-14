import io
import unittest

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from app.routes.admin_product_router import _read_excel_skus


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_admin_page_is_utf8(self):
        response = self.client.get("/admin/products")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Đồng bộ danh mục sản phẩm", response.text)
        self.assertIn("/static/js/product_admin.js", response.text)

    def test_original_admin_ui_uses_v2_chat_backend(self):
        response = self.client.get("/static/js/product_admin.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn('fetch("/api/chat"', response.text)
        self.assertIn('fetch("/api/chat/image"', response.text)
        self.assertNotIn('fetch("/admin/products/api/chat"', response.text)

    def test_old_admin_chat_routes_do_not_exist(self):
        self.assertEqual(
            self.client.post("/admin/products/api/chat", json={}).status_code,
            404,
        )
        self.assertEqual(
            self.client.post("/admin/products/api/chat/image").status_code,
            404,
        )

    def test_excel_accepts_vietnamese_product_code_header(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Mã sản phẩm"])
        sheet.append(["FE04"])
        sheet.append(["G81V6"])
        content = io.BytesIO()
        workbook.save(content)
        self.assertEqual(_read_excel_skus(content.getvalue()), ["FE04", "G81V6"])


if __name__ == "__main__":
    unittest.main()
