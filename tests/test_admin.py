import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.admin_auth_service import admin_auth_service
from app.routes.admin_conversation_router import (
    _combined_sessions,
    clear_session_cache,
    session_detail,
)
from app.routes.admin_product_router import recognition_image_content


class AdminTests(unittest.TestCase):
    def setUp(self):
        self._admin_auth_enabled = admin_auth_service.enabled
        admin_auth_service.enabled = False
        self.client = TestClient(app)

    def tearDown(self):
        admin_auth_service.enabled = self._admin_auth_enabled

    def test_admin_page_is_utf8(self):
        response = self.client.get("/admin/products")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Kho sản phẩm", response.text)
        self.assertIn("/static/js/product_catalog_admin.js", response.text)

    def test_admin_ui_uses_v2_chat_backend(self):
        response = self.client.get("/static/js/admin_base.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn('fetch("/api/chat"', response.text)
        self.assertIn('fetch("/api/chat/image"', response.text)
        self.assertNotIn('fetch("/admin/products/api/chat"', response.text)

    def test_admin_chat_can_start_a_new_conversation(self):
        page = self.client.get("/admin/products")
        script = self.client.get("/static/js/admin_base.js")
        self.assertIn('id="chatReset"', page.text)
        self.assertIn('fetch("/api/chat/reset"', script.text)
        self.assertIn("crypto.randomUUID()", script.text)
        self.assertIn('id="chatBody"', page.text)

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
        script = self.client.get("/static/js/product_catalog_admin.js")
        self.assertIn('id="productDetailModal"', page.text)
        self.assertIn('id="productDetailBody"', page.text)
        self.assertIn("openProductDetail", script.text)
        self.assertIn("/admin/products/api/catalog/", script.text)
        self.assertNotIn('id="syncAllButton"', page.text)
        self.assertNotIn("/admin/products/api/sync-all", script.text)
        self.assertIn('id="catalogType"', page.text)
        self.assertIn("product_type: productType", script.text)
        self.assertIn("Ảnh marketing nhận diện", script.text)
        self.assertIn('id="recognitionImageForm"', script.text)
        self.assertIn("/recognition-images", script.text)

    def test_conversation_admin_page_is_available(self):
        response = self.client.get("/admin/conversations")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Quản lý hội thoại", response.text)
        self.assertIn("/static/js/conversation_admin.js", response.text)

    def test_conversation_detail_shows_time_and_scrolls_to_latest_message(self):
        script = self.client.get("/static/js/conversation_admin.js")

        self.assertEqual(script.status_code, 200)
        self.assertIn('function messageTimeLabel(value)', script.text)
        self.assertIn('timeZone: "Asia/Ho_Chi_Minh"', script.text)
        self.assertIn('historyElement.closest(".modal-body")', script.text)
        self.assertIn(
            "historyScroller.scrollTop = historyScroller.scrollHeight",
            script.text,
        )

    def test_knowledge_page_is_read_only(self):
        response = self.client.get("/admin/knowledge", follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("location", response.headers)
        for element in ('id="documentRows"', 'id="docModal"', 'id="refreshDocuments"'):
            self.assertIn(element, response.text)
        self.assertNotIn('id="uploadForm"', response.text)
        self.assertNotIn('id="docModalDelete"', response.text)
        self.assertIn("20260918-readonly1", response.text)

    def test_knowledge_script_only_uses_read_apis(self):
        script = self.client.get("/static/js/knowledge_admin.js")
        self.assertEqual(script.status_code, 200)
        self.assertIn('fetch("/admin/knowledge/api/documents")', script.text)
        self.assertNotIn("/api/upload", script.text)
        self.assertNotIn('method: "DELETE"', script.text)
        self.assertNotIn("window.confirm(", script.text)
        self.assertNotIn("Authorization", script.text)
        self.assertNotIn("API_KEY", script.text)

    def test_knowledge_page_requires_bot_login(self):
        admin_auth_service.enabled = True
        with patch.object(admin_auth_service, "read_session", return_value=None):
            self.assertEqual(self.client.get("/admin/knowledge", follow_redirects=False).status_code, 401)

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

    def test_conversation_detail_keeps_total_and_uses_latest_message_window(self):
        history_service = Mock()
        history_service.get_session.return_value = {
            "channel": "facebook",
            "session_id": "customer-1",
            "message_count": 785,
            "last_message": "Tin moi nhat",
        }
        history_service.list_messages.return_value = [
            {"role": "user", "content": "Tin 286", "created_at": "2026-09-01"},
            {"role": "assistant", "content": "Tin moi nhat", "created_at": "2026-09-03"},
        ]
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            conversation_history_service=history_service,
        )))

        with patch(
            "app.routes.admin_conversation_router.conversation_context_store"
        ) as context_store:
            context_store.inspect.return_value = None
            result = session_detail("facebook", "customer-1", request)

        history_service.list_messages.assert_called_once_with(
            channel="facebook",
            session_id="customer-1",
            limit=500,
        )
        self.assertEqual(result["message_count"], 785)
        self.assertEqual(result["last_message"], "Tin moi nhat")
        self.assertEqual(result["context"]["history"][-1]["text"], "Tin moi nhat")

    def test_recognition_image_content_reads_from_product_image_directory(self):
        repository = Mock()
        repository.payload_by_id.return_value = {
            "source_kind": "recognition",
            "is_active": True,
            "local_path": "recognition/test.jpg",
            "mime_type": "image/jpeg",
        }
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "recognition" / "test.jpg"
            image_path.parent.mkdir()
            image_path.write_bytes(b"test-image")
            with patch(
                "app.routes.admin_product_router.QdrantImageRepository",
                return_value=repository,
            ), patch(
                "app.routes.admin_product_router.PRODUCT_IMAGE_DIR", Path(directory)
            ):
                response = recognition_image_content("image-id")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body, b"test-image")
        self.assertEqual(response.media_type, "image/jpeg")


if __name__ == "__main__":
    unittest.main()
