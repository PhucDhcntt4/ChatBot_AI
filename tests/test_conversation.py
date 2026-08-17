import unittest

from app.ai.base import AIProvider
from app.conversation.context import ConversationContextStore
from app.conversation.cta import CTAService
from app.conversation.executor import ConversationExecutor
from app.conversation.models import (
    CTAType,
    ConversationContext,
    ConversationIntent,
    ConversationPlan,
    ExecutionResult,
)
from app.conversation.service import ConversationService


PRODUCT = {
    "product_code": "G81V6",
    "product_name": "Giày cao gót Đông Hải",
    "product_type": "GIAY CAO GOT",
    "description": "",
    "material": "Da tổng hợp",
    "sole": "Cao su",
    "height": "5cm",
    "status": "ACTIVE",
    "prices": [850000],
    "colors": ["Đen", "Kem"],
    "available_sizes": ["35", "36"],
    "availability_by_color": {},
    "image_urls": ["https://example.test/black.jpg"],
    "image_urls_by_color": {
        "Kem": ["https://example.test/cream-1.jpg", "https://example.test/cream-2.jpg"]
    },
}


class FakeRepository:
    def public_info(self, code):
        return PRODUCT.copy() if code == "G81V6" else None

    def search(self, query, limit=5):
        return [PRODUCT.copy()] if "giày" in query.casefold() else []

    def recommend_same_type(self, product_type, exclude_codes, limit):
        recommended = PRODUCT.copy()
        recommended["product_code"] = "G81V7"
        return [recommended]

    def recommend_by_query(self, query, limit):
        return [PRODUCT.copy()]


class FakeAI(AIProvider):
    provider_name = "fake"
    model = "fake-model"

    def create_plan(self, message, context):
        if "đổi size" in message.casefold():
            return ConversationPlan(intent=ConversationIntent.POLICY_QUESTION)
        if "màu kem" in message.casefold():
            return ConversationPlan(
                intent=ConversationIntent.PRODUCT_IMAGES,
                requested_color="Kem",
                send_images=True,
            )
        if "chất liệu" in message.casefold():
            return ConversationPlan(
                intent=ConversationIntent.PRODUCT_INFORMATION,
                requested_attributes=["material"],
            )
        return ConversationPlan(
            intent=ConversationIntent.PRODUCT_SEARCH,
            search_query="giày",
        )

    def present(self, message, plan, result, context):
        return f"reply:{result.status}"


class ConversationTests(unittest.TestCase):
    def setUp(self):
        executor = ConversationExecutor(products=FakeRepository())
        self.service = ConversationService(
            FakeAI(), executor, ConversationContextStore()
        )

    def test_follow_up_uses_latest_product(self):
        first = self.service.chat(
            message="Tìm giày", session_id="one", channel="web"
        )
        second = self.service.chat(
            message="Chất liệu gì?", session_id="one", channel="web"
        )
        self.assertEqual(first.products[0]["product_code"], "G81V6")
        self.assertEqual(second.status, "product_found")
        self.assertEqual(second.media, [])
        self.assertEqual(second.products[0]["material"], "Da tổng hợp")

    def test_requested_color_returns_only_matching_images(self):
        self.service.chat(message="Tìm giày", session_id="two", channel="web")
        response = self.service.chat(
            message="Cho xem màu kem", session_id="two", channel="web"
        )
        self.assertEqual(response.status, "images_found")
        self.assertEqual(response.media[0].color, "Kem")
        self.assertEqual(len(response.media[0].image_urls), 2)

    def test_product_info_sends_album_only_for_new_product(self):
        executor = ConversationExecutor(products=FakeRepository())
        context = ConversationContext(
            session_id="album",
            channel="web",
        )
        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
            reference_product_code="G81V6",
        )
        first = executor.execute("Thông tin G81V6", plan, context)
        self.assertEqual(first.media[0].product_code, "G81V6")
        context.latest_product_code = "G81V6"
        follow_up = executor.execute("Chất liệu gì?", plan, context)
        self.assertEqual(follow_up.media, [])

    def test_policy_question_uses_knowledge_adapter(self):
        def fake_knowledge_search(question):
            return {
                "success": True,
                "status": "knowledge_found",
                "content": "Được đổi size theo điều kiện trong chính sách.",
                "sources": [{"source_key": "policy/test.txt"}],
            }

        service = ConversationService(
            FakeAI(),
            ConversationExecutor(
                products=FakeRepository(),
                knowledge_search=fake_knowledge_search,
            ),
            ConversationContextStore(),
        )
        response = service.chat(
            message="Chính sách đổi size thế nào?",
            session_id="policy",
            channel="web",
        )
        self.assertEqual(response.status, "knowledge_found")
        self.assertEqual(response.sources[0]["source_key"], "policy/test.txt")
        self.assertEqual(response.cta_type, CTAType.NONE)
        self.assertIsNone(response.cta_text)

    def test_contextual_cta_does_not_repeat_recent_wording(self):
        first = self.service.chat(
            message="Tìm giày",
            session_id="cta",
            channel="web",
        )
        second = self.service.chat(
            message="Tìm giày",
            session_id="cta",
            channel="web",
        )
        self.assertEqual(first.cta_type, CTAType.ASK_SIZE)
        self.assertEqual(second.cta_type, CTAType.ASK_SIZE)
        self.assertNotEqual(first.cta_text, second.cta_text)
        self.assertTrue(first.message.endswith(first.cta_text))
        self.assertTrue(second.message.endswith(second.cta_text))

    def test_buying_intent_uses_start_order_cta(self):
        policy = CTAService()
        context = ConversationContext(session_id="buy", channel="web")
        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
            reference_product_code="G81V6",
            buying_intent=True,
        )
        result = ExecutionResult(
            success=True,
            status="product_found",
            intent=plan.intent,
            products=[PRODUCT.copy()],
        )
        policy.apply(plan, result, context)
        self.assertEqual(result.cta_type, CTAType.START_ORDER)
        self.assertIsNotNone(result.cta_text)


if __name__ == "__main__":
    unittest.main()
