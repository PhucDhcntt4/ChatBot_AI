import json
import unittest
from unittest.mock import Mock, patch

import httpx

import app.main as main
from app.knowledge.remote import RemoteKnowledgeSearch
from app.conversation.context import ConversationContextStore
from app.conversation.executor import ConversationExecutor
from app.conversation.models import ConversationIntent, ConversationPlan, CTAType
from app.conversation.service import ConversationService


FOUND = {"success": True, "status": "knowledge_found", "content": "Dữ liệu kiểm thử",
         "sources": [{"source_key": "test.txt"}]}
MISSING = {"success": False, "status": "knowledge_not_found", "content": "", "sources": []}
UNAVAILABLE = {**MISSING, "status": "knowledge_service_unavailable"}


class RemoteKnowledgeTests(unittest.TestCase):
    def client(self, handler):
        client = httpx.Client(base_url="https://rag.example.test/", transport=httpx.MockTransport(handler),
                              headers={"Authorization": "Bearer test-search-key"})
        self.addCleanup(client.close)
        with patch("app.knowledge.remote.httpx.Client", return_value=client):
            return RemoteKnowledgeSearch("https://rag.example.test", "test-search-key")

    def test_search_sends_query_category_and_key(self):
        def handler(request):
            self.assertEqual(request.url.path, "/api/v1/knowledge/search")
            self.assertEqual(request.headers["Authorization"], "Bearer test-search-key")
            self.assertEqual(json.loads(request.content), {"query": "Cửa hàng", "categories": ["store"]})
            return httpx.Response(200, json=FOUND)
        self.assertEqual(self.client(handler).search("Cửa hàng", categories=["store"]), FOUND)

    def test_not_found_is_not_connection_failure(self):
        self.assertEqual(self.client(lambda req: httpx.Response(200, json=MISSING)).search("abc"), MISSING)

    def test_http_failures_propagate_to_factory(self):
        for status in (401, 429, 503):
            with self.subTest(status=status), self.assertRaises(httpx.HTTPStatusError):
                self.client(lambda req: httpx.Response(status)).search("abc")

    def test_malformed_responses_are_rejected(self):
        for data in ([], {}, {**FOUND, "success": "false"}, {**FOUND, "sources": "wrong"},
                     {**FOUND, "content": ""}, {**FOUND, "status": []},
                     {**MISSING, "content": "invented"}, UNAVAILABLE):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.client(lambda req: httpx.Response(200, json=data)).search("abc")

    def test_invalid_json_is_rejected(self):
        with self.assertRaises(ValueError):
            self.client(lambda req: httpx.Response(200, text="not-json")).search("abc")

    def test_factory_has_only_remote_backend_and_closes_after_call(self):
        with patch.multiple(main, RAG_ENABLED=True, RAG_SERVICE_URL="https://rag.example.test",
                            RAG_SERVICE_API_KEY="test-search-key", RAG_SERVICE_TIMEOUT_SECONDS=40), \
                patch.object(main, "RemoteKnowledgeSearch") as remote:
            remote.return_value.search.return_value = FOUND
            search = main.create_knowledge_search()
            self.assertEqual(search("abc", categories=["store"]), FOUND)
            remote.return_value.search.assert_called_once_with("abc", categories=["store"])
            remote.return_value.close.assert_called_once()

    def test_factory_never_falls_back_when_remote_fails(self):
        with patch.multiple(main, RAG_ENABLED=True, RAG_SERVICE_URL="https://rag.example.test",
                            RAG_SERVICE_API_KEY="test-search-key", RAG_SERVICE_TIMEOUT_SECONDS=40), \
                patch.object(main, "RemoteKnowledgeSearch") as remote:
            for error in (httpx.ReadTimeout("timeout"), ValueError("bad response")):
                remote.reset_mock()
                remote.return_value.search.side_effect = error
                self.assertEqual(main.create_knowledge_search()("abc"), UNAVAILABLE)
                remote.return_value.close.assert_called_once()

    def test_disabled_rag_does_not_construct_client(self):
        with patch.object(main, "RAG_ENABLED", False), patch.object(main, "RemoteKnowledgeSearch") as remote:
            self.assertIsNone(main.create_knowledge_search())
            remote.assert_not_called()

    def test_missing_remote_config_does_not_use_local_rag(self):
        with patch.multiple(main, RAG_ENABLED=True, RAG_SERVICE_URL="", RAG_SERVICE_API_KEY=""):
            with self.assertRaises(RuntimeError):
                main.create_knowledge_search()

    def test_service_failure_does_not_change_order_or_add_cta(self):
        for intent in (ConversationIntent.POLICY_QUESTION, ConversationIntent.PRODUCT_INFORMATION):
            with self.subTest(intent=intent):
                ai = Mock(provider_name="fake", model="fake")
                store = ConversationContextStore()
                context = store.get("remote-test", "web")
                context.draft_product_code = "TEST1"
                context.draft_quantity = 1
                store.save(context)
                repo = Mock()
                repo.public_info.return_value = {"product_code": "TEST1"}
                service = ConversationService(ai, ConversationExecutor(
                    products=repo, knowledge_search=lambda q, **kwargs: UNAVAILABLE), store)
                plan = ConversationPlan(intent=intent, use_knowledge=True, knowledge_query="Hỏi size",
                                        reference_product_code="TEST1", buying_intent=True)
                service.planner.plan = Mock(return_value=plan)
                service.fast_responses.reply = Mock(return_value=None)
                service.order_flow.apply = Mock()
                service._export_confirmed_order = Mock()
                service.cta.apply = Mock()
                response = service.chat(message="Tôi cần tư vấn size trước khi đặt",
                                        session_id="remote-test", channel="web")
                self.assertEqual(response.status, "knowledge_service_unavailable")
                self.assertEqual(response.cta_type, CTAType.NONE)
                self.assertIsNone(response.cta_text)
                self.assertEqual(response.media, [])
                self.assertIn("tạm gián đoạn", response.message)
                service.order_flow.apply.assert_not_called()
                service._export_confirmed_order.assert_not_called()
                service.cta.apply.assert_not_called()
                ai.present.assert_not_called()
                self.assertEqual(store.get("remote-test", "web").draft_quantity, 1)
