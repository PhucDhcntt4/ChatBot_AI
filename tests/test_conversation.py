import unittest

from app.ai.base import AIProvider
from app.conversation.context import ConversationContextStore
from app.conversation.cta import CTAService, CTA_TEMPLATES
from app.conversation.executor import ConversationExecutor
from app.conversation.models import (
    CTAType,
    ConversationContext,
    ConversationIntent,
    ConversationPlan,
    ExecutionResult,
    RequestedOrderItem,
    SalesStage,
)
from app.conversation.service import ConversationService
from app.conversation.presenter import ConversationPresenter
from app.conversation.planner import ConversationPlanner
from app.conversation.order_flow import OrderFlowService
from app.database.product_repository import ProductRepository


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

ACCESSORY_PRODUCT = {
    "product_code": "PK01",
    "product_name": "Ví da Đông Hải",
    "product_type": "PHU KIEN",
    "description": "",
    "material": "Da",
    "sole": None,
    "height": None,
    "status": "ACTIVE",
    "prices": [500000],
    "variant_prices": [{
        "color": "Đen",
        "size": "",
        "price": 500000,
        "available": True,
    }],
    "colors": ["Đen"],
    "available_sizes": [],
    "availability_by_color": {
        "Đen": {"available": True, "available_sizes": []},
    },
    "image_urls": [],
    "image_urls_by_color": {},
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

    def test_exact_code_uses_direct_lookup_when_classified_as_search(self):
        executor = ConversationExecutor(products=FakeRepository())
        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_SEARCH,
            reference_product_code="G81V6",
            send_images=True,
        )
        context = ConversationContext(session_id="exact-code", channel="web")

        result = executor.execute("Cho xem mẫu G81V6", plan, context)

        self.assertEqual(result.status, "products_found")
        self.assertEqual(result.products[0]["product_code"], "G81V6")
        self.assertEqual(len(result.media), 1)

    def test_exact_code_query_also_uses_direct_lookup(self):
        executor = ConversationExecutor(products=FakeRepository())
        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_SEARCH,
            reference_product_code="G81V6",
            search_query="G81V6",
            buying_intent=True,
        )
        context = ConversationContext(session_id="code-query", channel="web")

        result = executor.execute("Mua G81V6", plan, context)

        self.assertEqual(result.status, "products_found")
        self.assertEqual(result.products[0]["product_code"], "G81V6")

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

    def test_short_greeting_uses_local_fast_path_without_ai(self):
        class CountingAI(FakeAI):
            calls = 0

            def create_plan(self, message, context):
                self.calls += 1
                return super().create_plan(message, context)

            def present(self, message, plan, result, context):
                self.calls += 1
                return super().present(message, plan, result, context)

        ai = CountingAI()
        service = ConversationService(
            ai,
            ConversationExecutor(products=FakeRepository()),
            ConversationContextStore(),
        )

        response = service.chat(
            message="hi",
            session_id="fast-greeting",
            channel="web",
        )

        self.assertEqual(ai.calls, 0)
        self.assertEqual(response.intent, ConversationIntent.GENERAL_CHAT)
        self.assertEqual(response.provider, "local")
        self.assertEqual(response.model, "fast-responses")
        self.assertEqual(response.timing["planner"], 0.0)
        self.assertEqual(response.timing["presenter"], 0.0)

    def test_fast_path_is_disabled_during_order_flow(self):
        class CountingAI(FakeAI):
            calls = 0

            def create_plan(self, message, context):
                self.calls += 1
                return super().create_plan(message, context)

        ai = CountingAI()
        store = ConversationContextStore()
        context = store.get("active-order", "web")
        context.sales_stage = SalesStage.COLLECTING_PRODUCT
        store.save(context)
        service = ConversationService(
            ai,
            ConversationExecutor(products=FakeRepository()),
            store,
        )

        service.chat(message="ok", session_id="active-order", channel="web")

        self.assertEqual(ai.calls, 1)

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
            send_images=True,
        )
        first = executor.execute("Thông tin G81V6", plan, context)
        self.assertEqual(first.media[0].product_code, "G81V6")
        context.latest_product_code = "G81V6"
        follow_up = executor.execute("Chất liệu gì?", plan, context)
        self.assertEqual(follow_up.media, [])

    def test_new_product_info_stays_text_only_without_plan_image_flag(self):
        executor = ConversationExecutor(products=FakeRepository())
        context = ConversationContext(session_id="code-only", channel="web")
        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
            reference_product_code="G81V6",
            send_images=False,
        )

        result = executor.execute("G81V6", plan, context)

        self.assertEqual(result.status, "product_found")
        self.assertEqual(result.media, [])

    def test_exact_code_search_returns_album_without_ai_image_flag(self):
        class ExactCodeRepository(FakeRepository):
            def search(self, query, limit=5):
                return [PRODUCT.copy()] if query.upper() == "G81V6" else []

        executor = ConversationExecutor(products=ExactCodeRepository())
        context = ConversationContext(session_id="code-search", channel="web")
        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_SEARCH,
            reference_product_code="G81V6",
            search_query="G81V6",
            send_images=False,
        )

        result = executor.execute("G81V6", plan, context)

        self.assertEqual(result.status, "products_found")
        self.assertEqual(len(result.media), 1)
        self.assertEqual(result.media[0].product_code, "G81V6")

    def test_presenter_does_not_duplicate_cta_with_different_case(self):
        cta = (
            "Anh/chị gửi em mã sản phẩm hoặc mô tả rõ hơn để em "
            "kiểm tra chính xác nhé."
        )
        reply = (
            "Dạ, anh/chị gửi em mã sản phẩm hoặc mô tả rõ hơn để em "
            "kiểm tra chính xác nhé."
        )
        result = ExecutionResult(
            success=False,
            status="products_not_found",
            intent=ConversationIntent.PRODUCT_SEARCH,
            cta_type=CTAType.PROVIDE_MORE_INFO,
            cta_text=cta,
        )

        rendered = ConversationPresenter.with_cta(reply, result)

        self.assertEqual(rendered, reply)
        self.assertEqual(rendered.casefold().count("mã sản phẩm"), 1)

    def test_presenter_normalizes_customer_address(self):
        reply = "Chào bạn. Quý khách đang quan tâm sản phẩm nào ạ?"

        normalized = ConversationPresenter.normalize_customer_address(reply)

        self.assertEqual(
            normalized,
            "Chào anh/chị. Anh/chị đang quan tâm sản phẩm nào ạ?",
        )
        self.assertNotIn("bạn", normalized.casefold())
        self.assertNotIn("quý khách", normalized.casefold())

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

    def test_size_measurement_product_question_uses_knowledge(self):
        def fake_size_knowledge(question):
            return {
                "success": True,
                "status": "knowledge_found",
                "content": "Ban chan 25cm tham khao size 40.",
                "sources": [{"source_key": "size_guide/test.txt"}],
            }

        executor = ConversationExecutor(
            products=FakeRepository(),
            knowledge_search=fake_size_knowledge,
        )
        context = ConversationContext(
            session_id="size-rag",
            channel="web",
            latest_product_code="G81V6",
        )
        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
            reference_product_code="G81V6",
            requested_attributes=["sizes"],
        )

        result = executor.execute("Chan dai 25cm mang size nao?", plan, context)

        self.assertEqual(result.status, "product_found")
        self.assertIn("25cm", result.knowledge_context)
        self.assertEqual(result.sources[0]["source_key"], "size_guide/test.txt")

    def test_promotion_order_question_uses_knowledge_and_keeps_order_draft(self):
        def fake_promotion_knowledge(question):
            return {
                "success": True,
                "status": "knowledge_found",
                "content": "Đơn từ 1.000.000 đ được giảm 200.000 đ.",
                "sources": [{"source_key": "promotion/test.txt"}],
            }

        executor = ConversationExecutor(
            products=FakeRepository(),
            knowledge_search=fake_promotion_knowledge,
        )
        context = ConversationContext(
            session_id="promotion-rag",
            channel="web",
            latest_product_code="G81V6",
            sales_stage=SalesStage.AWAITING_FINAL_CONFIRMATION,
            draft_product_code="G81V6",
            draft_color="Đen",
            draft_size="36",
            draft_quantity=1,
            cart_items=[{
                "product_name": "Giày cao gót Đông Hải",
                "product_code": "G81V6",
                "color": "Đen",
                "size": "36",
                "quantity": 1,
                "unit_price": 850_000,
                "subtotal": 850_000,
            }],
        )
        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
            reference_product_code="G81V6",
            requested_attributes=["promotion"],
        )

        result = executor.execute(
            "Áp dụng khuyến mãi cho đơn này",
            plan,
            context,
        )
        OrderFlowService().apply(plan, result, context)

        self.assertIn("giảm 200.000", result.knowledge_context)
        self.assertEqual(
            result.facts["order_draft"]["subtotal"],
            850_000,
        )
        self.assertIn(
            "200.000",
            result.facts["order_draft"]["promotion_note"],
        )

    def test_structured_promotion_is_saved_and_reduces_draft_total(self):
        context = ConversationContext(
            session_id="structured-promotion",
            channel="web",
            latest_product_code="G81V6",
            sales_stage=SalesStage.AWAITING_FINAL_CONFIRMATION,
            draft_product_code="G81V6",
            draft_color="Đen",
            draft_size="36",
            draft_quantity=1,
            draft_payment_method="cod",
            cart_items=[{
                "product_name": "Giày cao gót Đông Hải",
                "product_code": "G81V6",
                "color": "Đen",
                "size": "36",
                "quantity": 1,
                "unit_price": 850_000,
                "subtotal": 850_000,
            }],
        )
        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
            reference_product_code="G81V6",
            requested_attributes=["promotion"],
            promotion_name="Ưu đãi Sinh nhật tháng 08",
            promotion_discount_amount=200_000,
            promotion_eligible=True,
        )
        result = ExecutionResult(
            success=True,
            status="product_found",
            intent=ConversationIntent.PRODUCT_INFORMATION,
            products=[FakeRepository().public_info("G81V6")],
        )

        OrderFlowService().apply(plan, result, context)

        draft = result.facts["order_draft"]
        self.assertEqual(draft["promotion_discount_amount"], 200_000)
        self.assertEqual(draft["discounted_subtotal"], 650_000)
        self.assertEqual(draft["total"], 680_000)
        self.assertIn("Ưu đãi Sinh nhật tháng 08", draft["promotion_note"])
        self.assertIn("200.000 đ", draft["promotion_note"])

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

    def test_buying_intent_with_color_and_size_still_asks_quantity(self):
        policy = CTAService()
        context = ConversationContext(session_id="confirm-buy", channel="web")
        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
            reference_product_code="G81V6",
            requested_color="Đen",
            requested_size="36",
            requested_quantity=1,
            buying_intent=True,
        )
        result = ExecutionResult(
            success=True,
            status="product_found",
            intent=plan.intent,
            products=[PRODUCT.copy()],
        )

        policy.apply(plan, result, context)

        self.assertEqual(result.cta_type, CTAType.ASK_QUANTITY)
        self.assertIsNotNone(result.cta_text)

    def test_buying_intent_with_color_only_asks_only_for_size(self):
        policy = CTAService()
        context = ConversationContext(session_id="missing-size", channel="web")
        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
            requested_color="Đen",
            buying_intent=True,
        )
        result = ExecutionResult(
            success=True,
            status="product_found",
            intent=plan.intent,
            products=[PRODUCT.copy()],
        )

        policy.apply(plan, result, context)

        self.assertEqual(result.cta_type, CTAType.ASK_SIZE)

    def test_accessory_without_sizes_never_asks_for_size(self):
        context = ConversationContext(session_id="accessory-order", channel="web")
        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
            reference_product_code="PK01",
            requested_quantity=1,
            buying_intent=True,
        )
        result = ExecutionResult(
            success=True,
            status="product_found",
            intent=plan.intent,
            products=[ACCESSORY_PRODUCT.copy()],
        )

        OrderFlowService().apply(plan, result, context)
        CTAService().apply(plan, result, context)

        self.assertEqual(result.facts["missing_product_fields"], [])
        self.assertEqual(context.draft_color, "Đen")
        self.assertIsNone(context.draft_size)
        self.assertEqual(context.sales_stage, SalesStage.COLLECTING_CONTACT)
        self.assertEqual(result.cta_type, CTAType.PROVIDE_CONTACT)

    def test_accessory_information_cta_does_not_ask_for_size(self):
        context = ConversationContext(session_id="accessory-info", channel="web")
        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
            reference_product_code="PK01",
        )
        result = ExecutionResult(
            success=True,
            status="product_found",
            intent=plan.intent,
            products=[ACCESSORY_PRODUCT.copy()],
        )

        CTAService().apply(plan, result, context)

        self.assertNotIn(result.cta_type, {CTAType.ASK_SIZE, CTAType.SIZE_SUPPORT})

    def test_quantity_is_not_inferred_when_customer_did_not_say_it(self):
        class HallucinatedQuantityAI(FakeAI):
            def create_plan(self, message, context):
                return ConversationPlan(
                    intent=ConversationIntent.PRODUCT_INFORMATION,
                    requested_color="Den",
                    requested_size="37",
                    requested_quantity=1,
                    buying_intent=True,
                )

        plan = ConversationPlanner(HallucinatedQuantityAI()).plan(
            "Cho anh size 37 mau den",
            ConversationContext(session_id="no-quantity", channel="web"),
        )

        self.assertIsNone(plan.requested_quantity)

    def test_quantity_accepts_piece_unit_for_accessories(self):
        plan = ConversationPlanner(FakeAI()).plan(
            "Cho anh 1 chiếc",
            ConversationContext(session_id="piece-quantity", channel="web"),
        )

        self.assertEqual(plan.requested_quantity, 1)

    def test_explicit_quantity_is_kept(self):
        class MissingQuantityAI(FakeAI):
            def create_plan(self, message, context):
                return ConversationPlan(
                    intent=ConversationIntent.PRODUCT_INFORMATION,
                    requested_color="Den",
                    requested_size="37",
                    buying_intent=True,
                )

        plan = ConversationPlanner(MissingQuantityAI()).plan(
            "Cho anh size 37 mau den 2 doi",
            ConversationContext(session_id="with-quantity", channel="web"),
        )

        self.assertEqual(plan.requested_quantity, 2)

    def test_contact_cta_only_asks_for_fields_still_missing(self):
        policy = CTAService()
        context = ConversationContext(
            session_id="contact-fields",
            channel="web",
            sales_stage=SalesStage.COLLECTING_CONTACT,
        )
        plan = ConversationPlan(intent=ConversationIntent.PRODUCT_INFORMATION)
        result = ExecutionResult(
            success=True,
            status="order_flow_updated",
            intent=plan.intent,
            facts={
                "missing_contact_fields": [
                    "shipping_address",
                    "payment_method",
                ]
            },
        )

        policy.apply(plan, result, context)

        self.assertEqual(result.cta_type, CTAType.PROVIDE_CONTACT)
        self.assertIn("địa chỉ nhận hàng", result.cta_text)
        self.assertIn("phương thức thanh toán", result.cta_text)
        self.assertNotIn("họ tên", result.cta_text)
        self.assertNotIn("số điện thoại", result.cta_text)

    def test_ai_can_choose_contextual_cta_sentence_by_index(self):
        policy = CTAService()
        context = ConversationContext(session_id="ai-cta", channel="web")
        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
            suggested_cta_type=CTAType.CHOOSE_COLOR,
            suggested_cta_index=1,
        )
        result = ExecutionResult(
            success=True,
            status="product_found",
            intent=plan.intent,
            products=[PRODUCT.copy()],
        )

        policy.apply(plan, result, context)

        self.assertEqual(result.cta_type, CTAType.CHOOSE_COLOR)
        self.assertEqual(result.cta_text, CTA_TEMPLATES[CTAType.CHOOSE_COLOR][1])

    def test_ai_can_explicitly_choose_no_cta(self):
        policy = CTAService()
        context = ConversationContext(session_id="no-cta", channel="web")
        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
            suggested_cta_type=CTAType.NONE,
        )
        result = ExecutionResult(
            success=True,
            status="product_found",
            intent=plan.intent,
            products=[PRODUCT.copy()],
        )

        policy.apply(plan, result, context)

        self.assertEqual(result.cta_type, CTAType.NONE)
        self.assertIsNone(result.cta_text)

    def test_sales_flow_collects_selection_then_confirms(self):
        class FlowAI(FakeAI):
            def create_plan(self, message, context):
                if "xác nhận" in message.casefold():
                    return ConversationPlan(
                        intent=ConversationIntent.PRODUCT_INFORMATION,
                        reference_product_code="G81V6",
                        order_action="confirm",
                        suggested_cta_type=CTAType.NONE,
                    )
                if "0901234567" in message:
                    return ConversationPlan(
                        intent=ConversationIntent.PRODUCT_INFORMATION,
                        reference_product_code="G81V6",
                        customer_name="Nguyễn Văn An",
                        customer_phone="0901234567",
                        shipping_address="12 Nguyễn Trãi, Quận 1, TP.HCM",
                        payment_method="cod",
                    )
                return ConversationPlan(
                    intent=ConversationIntent.PRODUCT_INFORMATION,
                    reference_product_code="G81V6",
                    requested_color="Đen",
                    requested_size="36",
                    requested_quantity=1,
                    buying_intent=True,
                    suggested_cta_type=CTAType.CONFIRM_ORDER,
                    suggested_cta_index=0,
                )

        store = ConversationContextStore()
        service = ConversationService(
            FlowAI(),
            ConversationExecutor(products=FakeRepository()),
            store,
        )

        selection = service.chat(
            message="Chốt màu đen size 36 một đôi",
            session_id="sales-flow",
            channel="web",
        )
        collecting_contact = store.get("sales-flow", "web")
        contact = service.chat(
            message="Nguyễn Văn An, 0901234567, 12 Nguyễn Trãi, Quận 1, TP.HCM, COD",
            session_id="sales-flow",
            channel="web",
        )
        pending = store.get("sales-flow", "web")
        confirmation = service.chat(
            message="Xác nhận",
            session_id="sales-flow",
            channel="web",
        )
        confirmed = store.get("sales-flow", "web")

        self.assertEqual(selection.cta_type, CTAType.PROVIDE_CONTACT)
        self.assertEqual(
            collecting_contact.sales_stage,
            SalesStage.COLLECTING_CONTACT,
        )
        self.assertEqual(contact.cta_type, CTAType.CONFIRM_ORDER)
        self.assertEqual(pending.sales_stage, SalesStage.AWAITING_CONFIRMATION)
        self.assertEqual(pending.draft_color, "Đen")
        self.assertEqual(pending.draft_size, "36")
        self.assertEqual(confirmation.cta_type, CTAType.NONE)
        self.assertEqual(confirmed.sales_stage, SalesStage.CONFIRMED)

    def test_multi_item_order_recalculates_total_after_removal(self):
        def product(code, price):
            return {
                **PRODUCT,
                "product_code": code,
                "product_name": f"Sản phẩm {code}",
                "prices": [price],
                "variant_prices": [],
            }

        def result(item):
            return ExecutionResult(
                success=True,
                status="product_found",
                intent=ConversationIntent.PRODUCT_INFORMATION,
                products=[item],
            )

        flow = OrderFlowService()
        context = ConversationContext(session_id="multi-cart", channel="web")
        first = product("P1", 100_000)
        second = product("P2", 200_000)

        first_result = result(first)
        flow.apply(
            ConversationPlan(
                intent=ConversationIntent.PRODUCT_INFORMATION,
                reference_product_code="P1",
                requested_color="Đen",
                requested_size="37",
                requested_quantity=1,
                buying_intent=True,
            ),
            first_result,
            context,
        )
        second_result = result(second)
        flow.apply(
            ConversationPlan(
                intent=ConversationIntent.PRODUCT_INFORMATION,
                reference_product_code="P2",
                requested_color="Kem",
                requested_size="38",
                requested_quantity=2,
                buying_intent=True,
                order_action="add_item",
            ),
            second_result,
            context,
        )
        contact_result = result(second)
        flow.apply(
            ConversationPlan(
                intent=ConversationIntent.PRODUCT_INFORMATION,
                reference_product_code="P2",
                customer_name="Phúc",
                customer_phone="0764776093",
                shipping_address="12 Phan Huy Ích, Gò Vấp, Hồ Chí Minh",
                payment_method="cod",
            ),
            contact_result,
            context,
        )

        full_order = contact_result.facts["order_draft"]
        self.assertEqual(len(full_order["items"]), 2)
        self.assertEqual(full_order["subtotal"], 500_000)
        self.assertEqual(full_order["shipping_fee"], 30_000)
        self.assertEqual(full_order["total"], 530_000)

        removed_result = result(second)
        flow.apply(
            ConversationPlan(
                intent=ConversationIntent.PRODUCT_INFORMATION,
                reference_product_code="P2",
                order_action="remove_item",
            ),
            removed_result,
            context,
        )

        remaining = removed_result.facts["order_draft"]
        self.assertEqual(removed_result.status, "order_item_removed")
        self.assertEqual(
            [item["product_code"] for item in remaining["items"]],
            ["P1"],
        )
        self.assertEqual(remaining["subtotal"], 100_000)
        self.assertEqual(remaining["shipping_fee"], 30_000)
        self.assertEqual(remaining["total"], 130_000)

    def test_each_color_one_pair_creates_two_verified_cart_items(self):
        product = {
            **PRODUCT,
            "product_code": "DCF97",
            "product_name": "Dép nữ DCF97",
            "prices": [850_000],
            "variant_prices": [],
            "colors": ["Kem", "Đen"],
        }
        context = ConversationContext(
            session_id="multi-color",
            channel="web",
            sales_stage=SalesStage.COLLECTING_PRODUCT,
            draft_product_code="DCF97",
            draft_size="38",
        )
        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
            reference_product_code="DCF97",
            buying_intent=True,
            requested_items=[
                RequestedOrderItem(
                    product_code="DCF97",
                    color="Kem",
                    size="38",
                    quantity=1,
                ),
                RequestedOrderItem(
                    product_code="DCF97",
                    color="Đen",
                    size="38",
                    quantity=1,
                ),
            ],
        )
        result = ExecutionResult(
            success=True,
            status="product_found",
            intent=ConversationIntent.PRODUCT_INFORMATION,
            products=[product],
        )

        OrderFlowService().apply(plan, result, context)

        order = result.facts["order_draft"]
        self.assertEqual(len(order["items"]), 2)
        self.assertEqual(
            [(item["color"], item["quantity"]) for item in order["items"]],
            [("Kem", 1), ("Đen", 1)],
        )
        self.assertEqual(order["subtotal"], 1_700_000)
        self.assertEqual(result.facts["missing_product_fields"], [])

    def test_change_variant_replaces_existing_item_instead_of_adding(self):
        product = {
            **PRODUCT,
            "product_code": "SCM47",
            "product_name": "Sandal SCM47",
            "colors": ["Đen", "Nâu"],
            "available_sizes": ["36", "37"],
            "prices": [2_350_000],
            "variant_prices": [],
        }
        original_item = {
            "product_code": "SCM47",
            "product_name": "Sandal SCM47",
            "color": "Đen",
            "size": "37",
            "quantity": 1,
            "unit_price": 2_350_000,
            "subtotal": 2_350_000,
        }
        context = ConversationContext(
            session_id="change-variant",
            channel="web",
            sales_stage=SalesStage.AWAITING_FINAL_CONFIRMATION,
            draft_product_code="SCM47",
            draft_color="Đen",
            draft_size="37",
            draft_quantity=1,
            draft_customer_name="Minh",
            draft_customer_phone="0764898234",
            draft_shipping_address="333 Quang Trung, Gò Vấp, Hồ Chí Minh",
            draft_payment_method="cod",
            cart_items=[original_item],
        )
        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
            reference_product_code="SCM47",
            requested_color="Nâu",
            requested_size="36",
            order_action="change",
        )
        result = ExecutionResult(
            success=True,
            status="product_found",
            intent=ConversationIntent.PRODUCT_INFORMATION,
            products=[product],
        )

        OrderFlowService().apply(plan, result, context)

        order = result.facts["order_draft"]
        self.assertEqual(len(order["items"]), 1)
        self.assertEqual(order["items"][0]["color"], "Nâu")
        self.assertEqual(order["items"][0]["size"], "36")
        self.assertEqual(order["subtotal"], 2_350_000)

    def test_explicit_product_category_resolves_from_database_taxonomy(self):
        product_type = ProductRepository.match_product_type(
            "giày tây đi tiệc",
            ["GIAY CAO GOT (WGC)", "GIAY TAY (MGT)", "GIÀY SNEAKER (MSN)"],
        )
        self.assertEqual(product_type, "GIAY TAY (MGT)")

    def test_broad_one_word_product_type_does_not_force_catalog_filter(self):
        self.assertFalse(
            ProductRepository.should_enforce_product_type("SANDAL (MSD)")
        )
        self.assertTrue(
            ProductRepository.should_enforce_product_type(
                "SANDAL DE BANG (WSD)"
            )
        )

    def test_vietnamese_product_words_do_not_collapse_into_other_words(self):
        self.assertNotEqual("dép".casefold(), "đẹp".casefold())
        self.assertEqual(
            ProductRepository._normalize("dép"),
            ProductRepository._normalize("đẹp"),
        )


if __name__ == "__main__":
    unittest.main()
