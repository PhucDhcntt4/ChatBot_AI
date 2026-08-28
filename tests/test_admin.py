import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from app.routes.admin_conversation_router import (
    _combined_sessions,
    clear_session_cache,
)
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

    def test_admin_chat_can_start_a_new_conversation(self):
        page = self.client.get("/admin/products")
        script = self.client.get("/static/js/product_admin.js")
        self.assertIn('id="chatReset"', page.text)
        self.assertIn('fetch("/api/chat/reset"', script.text)
        self.assertIn("crypto.randomUUID()", script.text)
        self.assertIn(
            '<div class="ck-msg bot">👋 Xin chào anh/chị!',
            page.text,
        )

    def test_old_admin_chat_routes_do_not_exist(self):
        self.assertEqual(
            self.client.post("/admin/products/api/chat", json={}).status_code,
            404,
        )
        self.assertEqual(
            self.client.post("/admin/products/api/chat/image").status_code,
            404,
        )

    def test_catalog_rows_can_open_product_details(self):
        page = self.client.get("/admin/products")
        script = self.client.get("/static/js/product_admin.js")
        self.assertIn('id="productDetailModal"', page.text)
        self.assertIn('id="productDetailBody"', page.text)
        self.assertIn("openProductDetail", script.text)
        self.assertIn("/admin/products/api/catalog/", script.text)
        self.assertIn("catalog-ai-select", script.text)
        self.assertIn("/cancel", script.text)
        self.assertIn('id="syncAllButton"', page.text)
        self.assertIn("/admin/products/api/sync-all", script.text)
        self.assertIn('id="syncAllConfirmModal"', page.text)
        self.assertIn("/admin/products/api/sync-all/preview", script.text)
        self.assertIn('id="catalogType"', page.text)
        self.assertIn("product_type=", script.text)

    def test_conversation_admin_page_is_available(self):
        response = self.client.get("/admin/conversations")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Quản lý hội thoại", response.text)
        self.assertIn("/static/js/conversation_admin.js", response.text)

    def test_human_mode_duration_is_persisted_through_api(self):
        service = Mock()
        service.set_default_ttl.return_value = 1500
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            human_mode_service=service,
        )))
        from app.routes.admin_conversation_router import (
            HumanModeRequest,
            update_human_mode_duration,
        )

        with patch(
            "app.routes.admin_conversation_router._all_session_keys",
            return_value=[],
        ):
            result = update_human_mode_duration(
                HumanModeRequest(ttl_seconds=1500),
                request,
            )

        service.set_default_ttl.assert_called_once_with(1500)
        self.assertEqual(result["default_ttl_seconds"], 1500)
        self.assertEqual(result["renewed"], 0)

    def test_conversation_admin_list_api_is_available(self):
        response = self.client.get(
            "/admin/conversations/api/sessions?limit=20&offset=0"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("sessions", response.json())

    def test_conversation_cache_can_be_cleared_without_deleting_history(self):
        page = self.client.get("/admin/conversations")
        script = self.client.get("/static/js/conversation_admin.js")

        self.assertIn('id="clearCacheConfirmModal"', page.text)
        self.assertIn('id="clearCurrentCache"', page.text)
        self.assertIn("confirmClearCache", script.text)
        response = self.client.delete(
            "/admin/conversations/api/sessions/web/session-delete"
        )
        self.assertEqual(response.status_code, 405)

        history_service = Mock()
        history_service.get_session.return_value = {
            "channel": "web",
            "session_id": "session-delete",
        }
        history_service.update_session_snapshot.return_value = True
        human_mode_service = Mock()
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            conversation_history_service=history_service,
            human_mode_service=human_mode_service,
        )))
        live = {
            "channel": "web",
            "session_id": "session-delete",
            "customer_name": "Minh",
            "customer_phone": "0764776093",
            "sales_stage": "browsing",
            "latest_product_code": "G81V6",
        }
        with patch(
            "app.routes.admin_conversation_router.conversation_context_store"
        ) as context_store:
            context_store.inspect.return_value = live
            context_store.reset.return_value = True
            result = clear_session_cache(
                "web",
                "session-delete",
                request,
            )

        context_store.reset.assert_called_once_with("session-delete", "web")
        history_service.update_session_snapshot.assert_called_once()
        self.assertTrue(result["cache_deleted"])
        self.assertTrue(result["history_preserved"])

    def test_conversation_list_keeps_postgres_rows_without_redis_cache(self):
        history_service = Mock()
        history_service.list_sessions.return_value = [{
            "channel": "facebook",
            "session_id": "customer-1",
            "message_count": 12,
            "last_message": "Cảm ơn em",
            "sales_stage": "archived",
            "cache_active": False,
        }]
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            conversation_history_service=history_service,
        )))
        with patch(
            "app.routes.admin_conversation_router.conversation_context_store"
        ) as context_store:
            context_store.list_sessions.return_value = []
            sessions = _combined_sessions(request)

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["session_id"], "customer-1")
        self.assertFalse(sessions[0]["cache_active"])

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
