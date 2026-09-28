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
            if request.url.path.endswith("documents"):
                self.assertEqual(request.url.params["doc_type_id"], "1")
            return httpx.Response(200, json={"documents": [DOCUMENT]} if request.url.path.endswith("documents") else DOCUMENT)
        self.remote(handler)
        result = self.client.get("/admin/knowledge/api/documents").json()
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["documents"][0]["id"], "1")
        self.assertNotIn("file_storage_key", result["documents"][0])
        detail = self.client.get("/admin/knowledge/api/documents/1").json()
        self.assertEqual(detail["content"], DOCUMENT["source_text"])
        self.assertNotIn("file_storage_key", detail)

    def test_qdrant_64_bit_document_id_stays_an_exact_string(self):
        identifier = "4221233152686565400"

        def handler(request):
            document = {**DOCUMENT, "id": identifier}
            return httpx.Response(
                200,
                json={"documents": [document]}
                if request.url.path.endswith("documents") else document,
            )

        self.remote(handler)
        listed = self.client.get("/admin/knowledge/api/documents").json()
        self.assertEqual(listed["documents"][0]["id"], identifier)
        detail = self.client.get(
            f"/admin/knowledge/api/documents/{identifier}"
        ).json()
        self.assertEqual(detail["id"], identifier)

    def test_exact_source_key_lookup_is_forwarded(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={
                **DOCUMENT,
                "id": "2651988400946607363",
                "source_key": "shipping/order-policy",
            })

        service = self.remote(handler)
        document = service.detail_by_source_key("shipping/order-policy")
        self.assertEqual(document["source_key"], "shipping/order-policy")
        self.assertEqual(
            requests[0].url.path,
            "/api/v1/documents/by-source-key",
        )
        self.assertEqual(
            requests[0].url.params["source_key"],
            "shipping/order-policy",
        )

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

    def test_document_scope_is_forwarded_on_every_page(self):
        requests = []

        def handler(request):
            requests.append(request)
            offset = int(request.url.params["offset"])
            batch = [
                {**DOCUMENT, "id": index + 1}
                for index in range(200)
            ] if offset == 0 else []
            return httpx.Response(200, json={"documents": batch})

        service = self.remote(handler)
        service.documents(doc_type_id=1)

        self.assertEqual(len(requests), 2)
        self.assertTrue(all(
            request.url.params["doc_type_id"] == "1"
            for request in requests
        ))

    def test_category_lookup_returns_full_active_documents(self):
        requests = []
        shipping = {
            **DOCUMENT,
            "id": 7,
            "category": "shipping",
            "title": "Shipping",
        }
        inactive = {**shipping, "id": 8, "is_active": False}

        def handler(request):
            requests.append(request)
            if request.url.path == "/api/v1/documents":
                return httpx.Response(200, json={
                    "documents": [shipping, inactive, DOCUMENT],
                })
            self.assertEqual(request.url.path, "/api/v1/documents/7")
            return httpx.Response(200, json={
                **shipping,
                "source_text": "Full shipping policy",
            })

        service = self.remote(handler)
        documents = service.details_by_category("shipping")

        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0]["id"], "7")
        self.assertEqual(documents[0]["content"], "Full shipping policy")
        self.assertEqual(len(requests), 2)

    def test_mutation_routes_are_not_exposed(self):
        handler = Mock()
        self.remote(handler)
        self.assertEqual(
            self.client.post("/admin/knowledge/api/upload").status_code,
            404,
        )
        self.assertEqual(
            self.client.delete("/admin/knowledge/api/documents/1").status_code,
            405,
        )
        handler.assert_not_called()

    def test_upstream_errors_are_sanitized(self):
        for upstream, expected in ((401, 503), (403, 503), (404, 404), (429, 429), (503, 503)):
            with self.subTest(status=upstream):
                self.remote(lambda req: httpx.Response(upstream, json={"detail": "sensitive-upstream-data"}))
                response = self.client.get("/admin/knowledge/api/documents")
                self.assertEqual(response.status_code, expected)
                self.assertNotIn("sensitive-upstream-data", response.text)

    def test_management_routes_require_login(self):
        admin_auth_service.enabled = True
        handler = Mock()
        self.remote(handler)
        with patch.object(admin_auth_service, "read_session", return_value=None):
            for method, path in (("GET", "/admin/knowledge/api/documents"),
                                 ("GET", "/admin/knowledge/api/documents/1")):
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
