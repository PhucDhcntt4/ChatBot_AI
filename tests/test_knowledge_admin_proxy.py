import unittest
from unittest.mock import Mock, patch

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.knowledge.admin_client import KnowledgeAdminClient, admin_client
from app.routes.admin_knowledge_router import get_client
from app.services.admin_auth_service import admin_auth_service


DOCUMENT = {"id": 1, "title": "Cửa hàng.txt", "category": "store", "source_key": "sample",
            "is_active": True, "chunk_count": 1, "embedding_model": "test",
            "source_text": "Nội dung đầy đủ", "file_storage_key": "private/path"}


class ProxyTests(unittest.TestCase):
    def setUp(self):
        original = admin_auth_service.enabled
        admin_auth_service.enabled = False
        self.addCleanup(setattr, admin_auth_service, "enabled", original)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.addCleanup(app.dependency_overrides.pop, get_client, None)

    def remote(self, handler):
        client = httpx.Client(base_url="https://rag.test/", headers={"Authorization": "Bearer server-admin-key"},
                              transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        service = KnowledgeAdminClient(client)
        app.dependency_overrides[get_client] = lambda: service
        return service

    def test_list_and_detail_keep_old_ui_contract(self):
        def handler(request):
            self.assertEqual(request.headers["Authorization"], "Bearer server-admin-key")
            return httpx.Response(200, json={"documents": [DOCUMENT]} if request.url.path.endswith("documents") else DOCUMENT)
        self.remote(handler)
        result = self.client.get("/admin/knowledge/api/documents").json()
        self.assertEqual(result["total"], 1)
        self.assertNotIn("file_storage_key", result["documents"][0])
        detail = self.client.get("/admin/knowledge/api/documents/1").json()
        self.assertEqual(detail["content"], DOCUMENT["source_text"])
        self.assertNotIn("file_storage_key", detail)

    def test_all_service_pages_are_loaded(self):
        offsets = []
        def handler(request):
            offset = int(request.url.params["offset"])
            offsets.append(offset)
            batch = [{**DOCUMENT, "id": i + 1} for i in range(200)] if offset == 0 else [{**DOCUMENT, "id": 201}]
            return httpx.Response(200, json={"documents": batch})
        service = self.remote(handler)
        self.assertEqual(service.documents()["total"], 201)
        self.assertEqual(offsets, [0, 200])

    def test_upload_is_remote_and_waits_for_completion(self):
        def handler(request):
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.url.path, "/api/v1/documents/upload")
            self.assertIn(b'name="source_key"', request.content)
            self.assertIn(b"bot_upload/", request.content)
            self.assertIn(b"store", request.content)
            self.assertIn(b"file-content", request.content)
            return httpx.Response(200, json=DOCUMENT)
        self.remote(handler)
        response = self.client.post("/admin/knowledge/api/upload", data={"category": "Store"},
                                    files={"file": ("sample.txt", b"file-content", "text/plain")})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertNotIn("job", response.json())

    def test_delete_only_calls_service_and_filters_private_fields(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"deleted": True, "id": 1, "file_storage_key": "private"})
        self.remote(handler)
        response = self.client.delete("/admin/knowledge/api/documents/1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].method, "DELETE")
        self.assertNotIn("private", response.text)

    def test_upstream_errors_are_sanitized(self):
        for upstream, expected in ((401, 503), (403, 503), (404, 404), (429, 429), (503, 503)):
            with self.subTest(status=upstream):
                self.remote(lambda req: httpx.Response(upstream, json={"detail": "sensitive-upstream-data"}))
                response = self.client.get("/admin/knowledge/api/documents")
                self.assertEqual(response.status_code, expected)
                self.assertNotIn("sensitive-upstream-data", response.text)

    def test_timeout_does_not_retry_mutation(self):
        handler = Mock(side_effect=httpx.ReadTimeout("secret URL"))
        self.remote(handler)
        response = self.client.delete("/admin/knowledge/api/documents/1")
        self.assertEqual(response.status_code, 504)
        handler.assert_called_once()
        self.assertNotIn("secret URL", response.text)

    def test_empty_unsupported_and_large_uploads_are_rejected(self):
        handler = Mock()
        self.remote(handler)
        for filename, content, status in (("a.exe", b"abc", 422), ("a.txt", b"", 422), ("a.txt", b"a" * 11, 413)):
            with self.subTest(filename=filename, length=len(content)), patch("app.routes.admin_knowledge_router.MAX_UPLOAD_BYTES", 10):
                response = self.client.post("/admin/knowledge/api/upload", files={"file": (filename, content)})
                self.assertEqual(response.status_code, status)
        handler.assert_not_called()

    def test_cross_site_write_is_rejected(self):
        handler = Mock()
        self.remote(handler)
        response = self.client.delete("/admin/knowledge/api/documents/1", headers={"Origin": "https://evil.test"})
        self.assertEqual(response.status_code, 403)
        handler.assert_not_called()

    def test_management_routes_require_login(self):
        admin_auth_service.enabled = True
        handler = Mock()
        self.remote(handler)
        with patch.object(admin_auth_service, "read_session", return_value=None):
            for method, path in (("GET", "/admin/knowledge/api/documents"), ("DELETE", "/admin/knowledge/api/documents/1"),
                                 ("POST", "/admin/knowledge/api/upload")):
                self.assertEqual(self.client.request(method, path).status_code, 401)
        handler.assert_not_called()

    def test_missing_admin_key_fails_clearly_without_affecting_page(self):
        with patch("app.knowledge.admin_client.RAG_SERVICE_ADMIN_API_KEY", ""):
            self.assertEqual(self.client.get("/admin/knowledge").status_code, 200)
            response = self.client.get("/admin/knowledge/api/documents")
            self.assertEqual(response.status_code, 503)
            self.assertIn("RAG_SERVICE_ADMIN_API_KEY", response.text)

    def test_malformed_list_is_not_treated_as_empty(self):
        self.remote(lambda req: httpx.Response(200, json={"documents": "bad"}))
        self.assertEqual(self.client.get("/admin/knowledge/api/documents").status_code, 502)

    def test_client_uses_only_server_admin_key(self):
        configured_client = Mock()
        configured_client.__enter__ = Mock(return_value=configured_client)
        configured_client.__exit__ = Mock(return_value=False)
        with patch("app.knowledge.admin_client.RAG_SERVICE_URL", "https://rag.test"), \
                patch("app.knowledge.admin_client.RAG_SERVICE_ADMIN_API_KEY", "admin-test"), \
                patch("app.knowledge.admin_client.httpx.Client", return_value=configured_client) as factory:
            with admin_client():
                pass
            self.assertEqual(factory.call_args.kwargs["headers"]["Authorization"], "Bearer admin-test")
            self.assertFalse(factory.call_args.kwargs["follow_redirects"])
