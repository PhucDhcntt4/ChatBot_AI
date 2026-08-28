import unittest

from app.ai.base import AIProvider
from app.conversation.context import ConversationContextStore
from app.conversation.content_blocks import build_content_blocks
from app.conversation.cta import CTAService, CTA_TEMPLATES
from app.conversation.executor import ConversationExecutor
from app.conversation.models import (
    CTAType,
    ConversationContext,
    ConversationIntent,
    ConversationPlan,
    ExecutionResult,
    ProductMedia,
    RequestedOrderItem,
    SalesStage,
)
from app.conversation.service import ConversationService
from app.conversation.presenter import ConversationPresenter
from app.database.product_repository import ProductRepository
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

SECOND_ACCESSORY_PRODUCT = {
    **ACCESSORY_PRODUCT,
    "product_code": "PK02",
    "product_name": "Túi da Đông Hải",
    "prices": [700000],
    "variant_prices": [{
        "color": "Nâu",
        "size": "",
        "price": 700000,
        "available": True,
    }],
    "colors": ["Nâu"],
    "availability_by_color": {
        "Nâu": {"available": True, "available_sizes": []},
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
    def test_presenter_naturalizes_product_acknowledgement(self):
        text = (
            "Dạ, em ghi nhận mẫu Giày Thể Thao Zuciani The Trend Walkers "
            "N27 màu Trắng size 37 (920.000 đ) vào đơn cho anh ạ."
        )
        self.assertEqual(
            ConversationPresenter.naturalize_acknowledgement(text),
            "Dạ, anh/chị đang chọn mẫu Giày Thể Thao Zuciani The Trend "
            "Walkers N27 màu Trắng size 37 (920.000 đ) ạ.",
        )

    def test_presenter_naturalizes_contact_acknowledgement(self):
        self.assertEqual(
            ConversationPresenter.naturalize_acknowledgement(
                "Dạ, em ghi nhận thông tin của anh Tuấn (0764891234) ạ."
            ),
            "",
        )

    def test_presenter_removes_media_urls_but_keeps_other_links(self):
        image_url = "https://cdn.shopify.com/files/product_image.jpg?v=1"
        result = ExecutionResult(
            success=True,
            status="product_found",
            intent=ConversationIntent.PRODUCT_INFORMATION,
            media=[
                ProductMedia(
                    product_code="GHLO8",
                    image_urls=[image_url],
                )
            ],
        )
        text = (
            "Dạ, đây là mẫu GHLO8 ạ.\n\n"
            f"[{image_url}]({image_url})\n\n"
            "Xem thêm tại https://shopdonghai.com/collections/giay-luoi"
        )

        cleaned = ConversationPresenter.remove_embedded_media_urls(text, result)

        self.assertNotIn(image_url, cleaned.splitlines()[1] if len(cleaned.splitlines()) > 1 else "")
        self.assertIn("https://shopdonghai.com/collections/giay-luoi", cleaned)

    def test_presenter_adds_media_lead_when_ai_omits_it(self):
        result = ExecutionResult(
            success=True,
            status="product_found",
            intent=ConversationIntent.PRODUCT_INFORMATION,
            media=[
                ProductMedia(
                    product_code="GHLO8",
                    image_urls=["https://cdn.shopify.com/product.jpg"],
                )
            ],
        )

        reply = ConversationPresenter.ensure_media_lead(
            "Dạ, mẫu GHLO8 hiện còn hàng ạ.",
            result,
        )

        self.assertTrue(
            reply.endswith("Em gửi anh/chị xem hình thực tế mẫu này nhé 👇")
        )

    def test_presenter_does_not_duplicate_existing_media_lead(self):
        result = ExecutionResult(
            success=True,
            status="product_found",
            intent=ConversationIntent.PRODUCT_INFORMATION,
            media=[
                ProductMedia(
                    product_code="GHLO8",
                    image_urls=["https://cdn.shopify.com/product.jpg"],
                )
            ],
        )
        original = "Em gửi anh/chị xem hình thực tế mẫu này nhé 👇"

        self.assertEqual(
            ConversationPresenter.ensure_media_lead(original, result),
            original,
        )

    def test_presenter_removes_generated_cta_before_album(self):
        result = ExecutionResult(
            success=True,
            status="product_found",
            intent=ConversationIntent.PRODUCT_INFORMATION,
            media=[
                ProductMedia(
                    product_code="GHLO8",
                    image_urls=["https://cdn.shopify.com/product.jpg"],
                )
            ],
            cta_type=CTAType.CHOOSE_PRODUCT,
            cta_text="Anh/chị thích màu nào để em hỗ trợ tiếp ạ?",
        )
        reply = (
            "Dạ, đây là thông tin mẫu GHLO8 ạ.\n\n"
            "Anh/chị ưng mẫu em hỗ trợ tư vấn thêm cho mình ạ"
        )

        cleaned = ConversationPresenter.ensure_media_lead(reply, result)

        self.assertNotIn("Anh/chị ưng mẫu", cleaned)
        self.assertTrue(
            cleaned.endswith("Em gửi anh/chị xem hình thực tế mẫu này nhé 👇")
        )

    def test_presenter_moves_if_cta_after_album_lead(self):
        cta = (
            "Nếu anh/chị ưng sản phẩm này, em hỗ trợ kiểm tra tình trạng "
            "hàng và tư vấn thêm cho mình ạ❤️"
        )
        result = ExecutionResult(
            success=True,
            status="product_found",
            intent=ConversationIntent.PRODUCT_INFORMATION,
            products=[{
                "product_code": "TM29",
                "product_name": "Túi Xách Dáng Vỏ Sò",
            }],
            media=[
                ProductMedia(
                    product_code="TM29",
                    image_urls=["https://cdn.shopify.com/TM29.jpg"],
                )
            ],
            cta_type=CTAType.IMAGE_FEEDBACK,
            cta_text=cta,
        )
        reply = (
            "Dạ, em nhận diện được sản phẩm anh/chị vừa gửi rồi ạ:\n\n"
            "Túi Xách Dáng Vỏ Sò\n\n"
            "- Mã: TM29\n"
            "- Giá: 3.450.000đ\n\n"
            f"{cta}\n\n"
            "Em gửi anh/chị xem hình thực tế mẫu này nhé 👇"
        )

        cleaned = ConversationPresenter.ensure_media_lead(reply, result)
        presented = ConversationPresenter.with_cta(cleaned, result)
        blocks = build_content_blocks(
            presented,
            result.products,
            result.media,
            result.cta_text,
        )

        self.assertNotIn(cta, cleaned)
        self.assertEqual(
            [block.type for block in blocks],
            ["text", "media", "text"],
        )
        self.assertTrue(
            (blocks[0].text or "").endswith(
                "Em gửi anh/chị xem hình thực tế mẫu này nhé 👇"
            )
        )
        self.assertEqual(blocks[-1].text, cta)

    def test_presenter_removes_description_from_product_reply(self):
        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
        )
        text = (
            "Giày Tây Nam Zuciani Khóa Kim Loại\n\n"
            "- Mã: GSD11\n"
            "- Giá: 3.150.000 đ\n"
            "- Mô tả: Nội dung marketing rất dài.\n"
            "- Màu: Đen"
        )

        cleaned = ConversationPresenter.enforce_product_reply_format(text, plan)

        self.assertNotIn("Mô tả", cleaned)
        self.assertIn("- Màu: Đen", cleaned)

    def test_presenter_hides_discounted_subtotal_without_promotion(self):
        result = ExecutionResult(
            success=True,
            status="order_flow_updated",
            intent=ConversationIntent.PRODUCT_INFORMATION,
            facts={
                "order_draft": {
                    "subtotal": 1_550_000,
                    "promotion_note": None,
                    "discounted_subtotal": None,
                    "shipping_fee": 30_000,
                    "total": 1_580_000,
                }
            },
        )
        reply = (
            "TỔNG KẾT THANH TOÁN\n\n"
            "- Tiền sản phẩm: 1.550.000đ\n"
            "- Tiền sản phẩm sau ưu đãi: 1.550.000đ\n"
            "- Phí vận chuyển: 30.000đ\n"
            "- Tổng thanh toán: 1.580.000đ"
        )

        cleaned = ConversationPresenter.enforce_order_summary_format(
            reply,
            result,
        )

        self.assertNotIn("sau ưu đãi", cleaned)
        self.assertIn("Tổng thanh toán: 1.580.000đ", cleaned)

    def test_presenter_keeps_discounted_subtotal_with_promotion(self):
        result = ExecutionResult(
            success=True,
            status="order_flow_updated",
            intent=ConversationIntent.PRODUCT_INFORMATION,
            facts={
                "order_draft": {
                    "subtotal": 1_550_000,
                    "promotion_note": (
                        "Chương trình: Ưu đãi Sinh nhật | "
                        "Giảm: 100.000 đ | Trạng thái: Đã ghi nhận ưu đãi"
                    ),
                    "promotion_discount_amount": 100_000,
                    "discounted_subtotal": 1_450_000,
                    "shipping_fee": 30_000,
                    "total": 1_480_000,
                }
            },
        )
        reply = (
            "- Khuyến mãi: Giảm trực tiếp 100.000 đ\n"
            "- Tiền sản phẩm sau ưu đãi: 1.450.000đ"
        )

        cleaned = ConversationPresenter.enforce_order_summary_format(
            reply,
            result,
        )

        self.assertIn("Khuyến mãi", cleaned)
        self.assertIn("- Khuyến mãi: 100.000đ", cleaned)
        self.assertNotIn("Chương trình:", cleaned)
        self.assertNotIn("Trạng thái:", cleaned)
        self.assertIn("sau ưu đãi", cleaned)

    def test_recommendation_reply_keeps_only_compact_product_fields(self):
        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_RECOMMENDATION,
        )
        text = (
            "- Mã: GSD11\n"
            "- Giá: 3.150.000 đ\n"
            "- Màu: Đen\n"
            "- Size: 39, 40, 41, 42\n"
            "- Chất liệu: Da cao cấp\n"
            "- Đế: Cao su\n"
            "- Chiều cao: 3cm\n"
            "- Mô tả: Nội dung dài"
        )

        cleaned = ConversationPresenter.enforce_product_reply_format(text, plan)

        self.assertIn("- Size: 39, 40, 41, 42", cleaned)
        self.assertNotIn("Chất liệu", cleaned)
        self.assertNotIn("Chiều cao", cleaned)
        self.assertNotIn("Mô tả", cleaned)

    def test_product_search_extracts_vietnamese_height_constraints(self):
        self.assertEqual(
            ProductRepository._requested_heights(
                "Tư vấn mình mẫu sandal 5 phân, guốc 7 phân nha"
            ),
            {5.0, 7.0},
        )

    def test_product_height_parser_reads_catalog_height(self):
        self.assertEqual(
            ProductRepository._height_values("Gót cao 7cm"),
            {7.0},
        )

    def test_generic_feature_constraints_support_exclusions(self):
        self.assertFalse(
            ProductRepository._matches_feature_constraints(
                "Giày tây nam buộc dây da cao cấp",
                include_features=[],
                exclude_features=["dây"],
            )
        )
        self.assertTrue(
            ProductRepository._matches_feature_constraints(
                "Giày lười nam da cao cấp",
                include_features=[],
                exclude_features=["dây"],
            )
        )

    def test_negated_catalog_description_is_not_treated_as_positive_feature(self):
        self.assertTrue(
            ProductRepository._matches_feature_constraints(
                "Thiết kế không dây, tiện lợi khi mang",
                include_features=[],
                exclude_features=["dây"],
            )
        )

    def test_product_description_does_not_expose_stale_variant_facts(self):
        description = (
            "Giày sandal có quai nhúng nữ tính. "
            "Mẫu giày có 3 màu: đen, hồng, xanh lá. "
            "- Mã sản phẩm: S81Q8 - Màu: Đen, Hồng, Xanh Lá "
            "- Size: 35 - 39"
        )

        cleaned = ProductRepository._presentation_description(description)

        self.assertEqual(cleaned, "Giày sandal có quai nhúng nữ tính.")
        self.assertNotIn("Đen", cleaned)
        self.assertNotIn("35 - 39", cleaned)

    def setUp(self):
        executor = ConversationExecutor(products=FakeRepository())
        self.service = ConversationService(
            FakeAI(), executor, ConversationContextStore()
        )

    def test_general_chat_is_not_replaced_by_missing_knowledge_reply(self):
        presenter = ConversationPresenter(FakeAI())
        plan = ConversationPlan(intent=ConversationIntent.GENERAL_CHAT)
        result = ExecutionResult(
            success=True,
            status="general_chat",
            intent=ConversationIntent.GENERAL_CHAT,
        )

        reply = presenter.present(
            "Chào em nhé",
            plan,
            result,
            ConversationContext(session_id="greeting", channel="web"),
        )

        self.assertEqual(reply, "reply:general_chat")

    def test_unknown_intent_uses_missing_knowledge_reply(self):
        presenter = ConversationPresenter(FakeAI())
        plan = ConversationPlan(intent=ConversationIntent.UNKNOWN)
        result = ExecutionResult(
            success=False,
            status="intent_unknown",
            intent=ConversationIntent.UNKNOWN,
        )

        reply = presenter.present(
            "Nội dung không xác định",
            plan,
            result,
            ConversationContext(session_id="unknown", channel="web"),
        )

        self.assertEqual(reply, presenter.INSUFFICIENT_KNOWLEDGE_REPLY)

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

    def test_presenter_does_not_append_semantically_duplicate_more_info_cta(self):
        reply = (
            "Dạ, em chưa tìm thấy sản phẩm khớp với các hình ảnh này trong "
            "hệ thống. Anh/chị gửi thêm mã sản phẩm hoặc ảnh rõ hơn, chụp "
            "trọn sản phẩm giúp em nhé. 😊"
        )
        result = ExecutionResult(
            success=False,
            status="products_not_found",
            intent=ConversationIntent.PRODUCT_SEARCH,
            cta_type=CTAType.PROVIDE_MORE_INFO,
            cta_text=(
                "Anh/chị gửi em mã sản phẩm hoặc mô tả rõ hơn để em kiểm "
                "tra chính xác nhé."
            ),
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

        plan.use_knowledge = True
        plan.knowledge_query = "Chọn size theo bàn chân dài 25cm"
        plan.knowledge_categories = ["size_guide"]
        result = executor.execute("Chan dai 25cm mang size nao?", plan, context)

        self.assertEqual(result.status, "product_found")
        self.assertIn("25cm", result.knowledge_context)
        self.assertEqual(result.sources[0]["source_key"], "size_guide/test.txt")

    def test_size_advice_targets_size_guide_category(self):
        received = {}

        def fake_size_knowledge(question, *, categories=None):
            received["question"] = question
            received["categories"] = categories
            return {
                "success": True,
                "status": "knowledge_found",
                "content": "Bảng quy đổi size theo chiều dài bàn chân.",
                "sources": [{"source_key": "size_guide/test.txt"}],
            }

        executor = ConversationExecutor(
            products=FakeRepository(),
            knowledge_search=fake_size_knowledge,
        )
        context = ConversationContext(
            session_id="size-category",
            channel="web",
            latest_product_code="G81V6",
        )
        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
            reference_product_code="G81V6",
            requested_attributes=["sizes"],
        )

        plan.use_knowledge = True
        plan.knowledge_query = "Chọn size theo bàn chân dài 25cm"
        plan.knowledge_categories = ["size_guide"]
        result = executor.execute("Chân 25cm mang size nào?", plan, context)

        self.assertEqual(received["categories"], ["size_guide"])
        self.assertTrue(result.knowledge_context)

    def test_planner_uses_semantic_ai_knowledge_decision(self):
        class SizeAdviceAI:
            def create_plan(self, message, context):
                return ConversationPlan(
                    intent=ConversationIntent.PRODUCT_INFORMATION,
                    reference_product_code="GRD70",
                    requested_size=None,
                    buying_intent=False,
                    requested_attributes=["sizes"],
                    use_knowledge=True,
                    knowledge_query=(
                        "Quy đổi size 43 sang chiều dài bàn chân cho giày nam"
                    ),
                    knowledge_categories=["size_guide"],
                )

        planner = ConversationPlanner(SizeAdviceAI())
        context = ConversationContext(
            session_id="size-not-order",
            channel="web",
            latest_product_code="GRD70",
        )

        plan = planner.plan("Size 43 thì chân dài bao nhiêu cm?", context)

        self.assertIsNone(plan.requested_size)
        self.assertFalse(plan.buying_intent)
        self.assertTrue(plan.use_knowledge)
        self.assertEqual(plan.knowledge_categories, ["size_guide"])

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
            promotion_action="recommend",
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
        self.assertIsNone(result.facts["order_draft"]["promotion_note"])
        self.assertEqual(
            result.facts["order_draft"]["promotion_discount_amount"],
            0,
        )
        self.assertIn("promotion_recommendation", result.facts)

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
            promotion_action="apply",
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
        self.assertNotIn("AI tạm tính", draft["promotion_note"])

    def test_promotion_recommendation_does_not_change_order_total(self):
        context = ConversationContext(
            session_id="promotion-recommendation",
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
            promotion_action="recommend",
            promotion_name="Ưu đãi Sinh nhật tháng 08",
            promotion_discount_amount=100_000,
            promotion_benefit="Voucher 100.000 đ dùng lần sau",
            promotion_eligible=True,
        )
        result = ExecutionResult(
            success=True,
            status="product_found",
            intent=ConversationIntent.PRODUCT_INFORMATION,
            products=[FakeRepository().public_info("G81V6")],
        )

        OrderFlowService().apply(plan, result, context)
        CTAService().apply(plan, result, context)

        draft = result.facts["order_draft"]
        self.assertEqual(draft["promotion_discount_amount"], 0)
        self.assertEqual(draft["total"], 880_000)
        self.assertIsNone(draft["promotion_note"])
        self.assertEqual(result.cta_type, CTAType.APPLY_PROMOTION)

    def test_remove_promotion_restores_original_total(self):
        context = ConversationContext(
            session_id="promotion-remove",
            channel="web",
            latest_product_code="G81V6",
            sales_stage=SalesStage.AWAITING_FINAL_CONFIRMATION,
            draft_product_code="G81V6",
            draft_color="Đen",
            draft_size="36",
            draft_quantity=1,
            draft_payment_method="cod",
            draft_promotion_name="Ưu đãi Sinh nhật tháng 08",
            draft_promotion_discount_amount=100_000,
            draft_promotion_eligible=True,
            draft_promotion_note="Chương trình: Ưu đãi Sinh nhật tháng 08",
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
            promotion_action="remove",
        )
        result = ExecutionResult(
            success=True,
            status="product_found",
            intent=ConversationIntent.PRODUCT_INFORMATION,
            products=[FakeRepository().public_info("G81V6")],
        )

        OrderFlowService().apply(plan, result, context)

        draft = result.facts["order_draft"]
        self.assertTrue(result.facts["promotion_removed"])
        self.assertEqual(draft["promotion_discount_amount"], 0)
        self.assertEqual(draft["total"], 880_000)
        self.assertIsNone(draft["promotion_note"])

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

    def test_unavailable_variant_does_not_ask_quantity(self):
        product = {
            **PRODUCT,
            "available_sizes": ["35", "36", "37", "38", "39"],
            "availability_by_color": {
                "Đen": {
                    "available": True,
                    "available_sizes": ["35", "36", "37", "38"],
                },
                "Hồng": {
                    "available": True,
                    "available_sizes": ["39"],
                },
            },
        }
        context = ConversationContext(
            session_id="unavailable-before-quantity",
            channel="facebook",
        )
        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
            reference_product_code="S32D9",
            requested_color="Đen",
            requested_size="39",
            requested_quantity=None,
            buying_intent=True,
        )
        result = ExecutionResult(
            success=True,
            status="product_found",
            intent=plan.intent,
            products=[{**product, "product_code": "S32D9"}],
        )

        OrderFlowService().apply(plan, result, context)
        CTAService().apply(plan, result, context)

        self.assertIn(
            "size_unavailable_for_color",
            result.facts["product_validation_errors"],
        )
        self.assertEqual(result.cta_type, CTAType.OUT_OF_STOCK_OPTIONS)
        self.assertNotEqual(result.cta_type, CTAType.ASK_QUANTITY)

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

    def test_incomplete_product_is_kept_when_customer_adds_another_product(self):
        flow = OrderFlowService()
        context = ConversationContext(session_id="pending-cart", channel="web")

        first_plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
            reference_product_code="PK01",
            requested_color="Đen",
            buying_intent=True,
        )
        first_result = ExecutionResult(
            success=True,
            status="product_found",
            intent=first_plan.intent,
            products=[ACCESSORY_PRODUCT.copy()],
        )
        flow.apply(first_plan, first_result, context)

        self.assertEqual(context.pending_items[0]["product_code"], "PK01")
        self.assertIn("quantity", context.pending_items[0]["missing_fields"])

        second_plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
            reference_product_code="PK02",
            requested_color="Nâu",
            requested_quantity=1,
            buying_intent=True,
            order_action="add_item",
        )
        second_result = ExecutionResult(
            success=True,
            status="product_found",
            intent=second_plan.intent,
            products=[SECOND_ACCESSORY_PRODUCT.copy()],
        )
        flow.apply(second_plan, second_result, context)

        self.assertEqual([item["product_code"] for item in context.cart_items], ["PK02"])
        self.assertEqual(context.draft_product_code, "PK01")
        self.assertEqual(context.sales_stage, SalesStage.COLLECTING_PRODUCT)
        self.assertIn("quantity", second_result.facts["missing_product_fields"])

        finish_first_plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
            reference_product_code="PK01",
            requested_quantity=1,
            buying_intent=True,
        )
        finish_first_result = ExecutionResult(
            success=True,
            status="product_found",
            intent=finish_first_plan.intent,
            products=[ACCESSORY_PRODUCT.copy()],
        )
        flow.apply(finish_first_plan, finish_first_result, context)

        self.assertEqual(context.pending_items, [])
        self.assertEqual(
            {item["product_code"] for item in context.cart_items},
            {"PK01", "PK02"},
        )
        self.assertEqual(context.sales_stage, SalesStage.COLLECTING_CONTACT)

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
        class SemanticQuantityAI(FakeAI):
            def create_plan(self, message, context):
                return ConversationPlan(
                    intent=ConversationIntent.PRODUCT_INFORMATION,
                    requested_quantity=1,
                    quantity_explicitly_provided=True,
                    buying_intent=True,
                )

        plan = ConversationPlanner(SemanticQuantityAI()).plan(
            "Cho anh 1 chiếc",
            ConversationContext(session_id="piece-quantity", channel="web"),
        )

        self.assertEqual(plan.requested_quantity, 1)

    def test_quantity_unit_in_customer_message_recovers_missing_ai_flag(self):
        class MissingQuantityFlagAI(FakeAI):
            def create_plan(self, message, context):
                return ConversationPlan(
                    intent=ConversationIntent.PRODUCT_INFORMATION,
                    requested_color="Đen",
                    requested_size="39",
                    requested_quantity=1,
                    quantity_explicitly_provided=False,
                    buying_intent=True,
                )

        plan = ConversationPlanner(MissingQuantityFlagAI()).plan(
            "Cho màu đen 1 đôi nhé",
            ConversationContext(
                session_id="quantity-unit-fallback",
                channel="web",
                sales_stage=SalesStage.COLLECTING_PRODUCT,
                draft_product_code="GSD03",
                draft_size="39",
            ),
        )

        self.assertEqual(plan.requested_quantity, 1)
        self.assertTrue(plan.quantity_explicitly_provided)

    def test_bare_number_is_quantity_when_order_is_waiting_for_quantity(self):
        class ContextualQuantityAI(FakeAI):
            def create_plan(self, message, context):
                return ConversationPlan(
                    intent=ConversationIntent.PRODUCT_INFORMATION,
                    requested_quantity=(
                        2 if message.strip().startswith("2") else 1
                    ),
                    quantity_explicitly_provided=True,
                    buying_intent=True,
                )

        context = ConversationContext(
            session_id="bare-quantity",
            channel="web",
            sales_stage=SalesStage.COLLECTING_PRODUCT,
            draft_product_code="G2295",
            draft_color="Đen",
            draft_size="43",
        )

        for message in ("1", "1 e", "2 ạ"):
            with self.subTest(message=message):
                plan = ConversationPlanner(ContextualQuantityAI()).plan(message, context)
                self.assertEqual(
                    plan.requested_quantity,
                    2 if message.startswith("2") else 1,
                )

    def test_bare_number_is_not_quantity_while_browsing(self):
        plan = ConversationPlanner(FakeAI()).plan(
            "1",
            ConversationContext(session_id="bare-browsing", channel="web"),
        )

        self.assertIsNone(plan.requested_quantity)

    def test_bare_size_is_not_reused_as_quantity_when_size_is_missing(self):
        class SizeAndQuantityConfusedAI(FakeAI):
            def create_plan(self, message, context):
                return ConversationPlan(
                    intent=ConversationIntent.PRODUCT_INFORMATION,
                    requested_size="39",
                    requested_quantity=39,
                    quantity_explicitly_provided=False,
                    buying_intent=True,
                )

        plan = ConversationPlanner(SizeAndQuantityConfusedAI()).plan(
            "39",
            ConversationContext(
                session_id="bare-size-not-quantity",
                channel="facebook",
                sales_stage=SalesStage.COLLECTING_PRODUCT,
                draft_product_code="GCF94",
                draft_color="Đen",
                draft_size=None,
                draft_quantity=None,
            ),
        )

        self.assertEqual(plan.requested_size, "39")
        self.assertIsNone(plan.requested_quantity)
        self.assertFalse(plan.quantity_explicitly_provided)

    def test_recommended_product_replaces_unavailable_pending_variant(self):
        flow = OrderFlowService()
        new_product = {
            **PRODUCT,
            "product_code": "GCF94",
            "product_name": "Giày cao gót thay thế",
            "available_sizes": ["39"],
            "availability_by_color": {
                "Đen": {"available": True, "available_sizes": ["39"]},
            },
            "variant_prices": [{
                "color": "Đen",
                "size": "39",
                "price": 2350000,
                "available": True,
            }],
            "prices": [2350000],
        }
        context = ConversationContext(
            session_id="replace-unavailable",
            channel="facebook",
            sales_stage=SalesStage.COLLECTING_PRODUCT,
            draft_product_code="GSD03",
            draft_color="Nâu",
            draft_size="39",
            draft_quantity=1,
            pending_items=[{
                "product_code": "GSD03",
                "color": "Nâu",
                "size": "39",
                "quantity": 1,
                "missing_fields": ["size_unavailable_for_color"],
            }],
            recently_recommended_codes=["GCF94"],
        )
        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
            reference_product_code="GCF94",
            requested_color="Đen",
            requested_size="39",
            requested_quantity=1,
            quantity_explicitly_provided=True,
            buying_intent=True,
        )
        result = ExecutionResult(
            success=True,
            status="product_found",
            intent=plan.intent,
            products=[new_product],
        )

        flow.apply(plan, result, context)

        self.assertEqual(context.pending_items, [])
        self.assertEqual(context.draft_product_code, "GCF94")
        self.assertEqual(context.draft_quantity, 1)
        self.assertEqual(
            [item["product_code"] for item in context.cart_items],
            ["GCF94"],
        )

    def test_current_product_purchase_is_not_treated_as_recommendation(self):
        class MisclassifiedPurchaseAI(FakeAI):
            def create_plan(self, message, context):
                return ConversationPlan(
                    intent=ConversationIntent.PRODUCT_RECOMMENDATION,
                    reference_product_code="JC59",
                    requested_color="Đen",
                    requested_items=[RequestedOrderItem(
                        product_code="JC59",
                        color="Đen",
                        quantity=1,
                    )],
                    buying_intent=True,
                    send_images=True,
                )

        plan = ConversationPlanner(MisclassifiedPurchaseAI()).plan(
            "Lấy anh 1 cái màu đen",
            ConversationContext(
                session_id="current-product-purchase",
                channel="web",
                latest_product_code="JC59",
            ),
        )

        self.assertEqual(plan.intent, ConversationIntent.PRODUCT_INFORMATION)
        self.assertFalse(plan.send_images)
        self.assertEqual(plan.reference_product_code, "JC59")
        self.assertEqual(plan.requested_items[0].quantity, 1)

    def test_purchase_with_explicit_image_request_keeps_media_signal(self):
        class PurchaseWithImageAI(FakeAI):
            def create_plan(self, message, context):
                return ConversationPlan(
                    intent=ConversationIntent.PRODUCT_RECOMMENDATION,
                    reference_product_code="JC59",
                    requested_color="Đen",
                    requested_items=[RequestedOrderItem(
                        product_code="JC59",
                        color="Đen",
                        quantity=1,
                    )],
                    buying_intent=True,
                    send_images=True,
                    explicit_image_request=True,
                )

        plan = ConversationPlanner(PurchaseWithImageAI()).plan(
            "Lấy một cái màu đen và cho anh xem ảnh",
            ConversationContext(
                session_id="purchase-with-image",
                channel="web",
                latest_product_code="JC59",
            ),
        )

        self.assertEqual(plan.intent, ConversationIntent.PRODUCT_INFORMATION)
        self.assertTrue(plan.explicit_image_request)
        self.assertTrue(plan.send_images)

    def test_selecting_exact_code_does_not_repeat_category_recommendations(self):
        class MisclassifiedSelectionAI(FakeAI):
            def create_plan(self, message, context):
                return ConversationPlan(
                    intent=ConversationIntent.PRODUCT_SEARCH,
                    reference_product_code="G01D1",
                    search_query="giay tay",
                    send_images=True,
                )

        plan = ConversationPlanner(MisclassifiedSelectionAI()).plan(
            "Cho anh xem G01D1",
            ConversationContext(
                session_id="select-recommended-product",
                channel="web",
                latest_product_code="GRD70",
                recently_recommended_codes=["GRD70", "G2295", "G01D1"],
            ),
        )

        self.assertEqual(plan.intent, ConversationIntent.PRODUCT_INFORMATION)
        self.assertEqual(plan.reference_product_code, "G01D1")
        self.assertIsNone(plan.search_query)
        self.assertTrue(plan.send_images)

    def test_bare_sku_is_promoted_to_exact_product_reference(self):
        class BareSkuAsQueryAI(FakeAI):
            def create_plan(self, message, context):
                return ConversationPlan(
                    intent=ConversationIntent.PRODUCT_SEARCH,
                    search_query="S81V3",
                    suggested_cta_type=CTAType.PROVIDE_MORE_INFO,
                )

        plan = ConversationPlanner(BareSkuAsQueryAI()).plan(
            "S81V3",
            ConversationContext(session_id="bare-sku", channel="web"),
        )

        self.assertEqual(plan.intent, ConversationIntent.PRODUCT_INFORMATION)
        self.assertEqual(plan.reference_product_code, "S81V3")
        self.assertIsNone(plan.search_query)
        self.assertTrue(plan.send_images)

    def test_name_and_phone_at_contact_stage_are_not_product_code(self):
        class ContactMisclassifiedAsProductAI(FakeAI):
            def create_plan(self, message, context):
                return ConversationPlan(
                    intent=ConversationIntent.PRODUCT_INFORMATION,
                    reference_product_code="TRANG0764897432",
                    search_query="TRANG0764897432",
                    customer_phone="0764897432",
                    buying_intent=True,
                    send_images=True,
                )

        context = ConversationContext(
            session_id="contact-not-product",
            channel="telegram",
            sales_stage=SalesStage.COLLECTING_CONTACT,
            latest_product_code="S81Q8",
            draft_product_code="S81Q8",
            draft_color="Xanh Lá",
            draft_size="38",
            draft_quantity=2,
            cart_items=[{
                "product_code": "S81Q8",
                "color": "Xanh Lá",
                "size": "38",
                "quantity": 2,
            }],
        )

        plan = ConversationPlanner(ContactMisclassifiedAsProductAI()).plan(
            "Trang 0764897432",
            context,
        )

        self.assertEqual(plan.customer_name, "Trang")
        self.assertEqual(plan.customer_phone, "0764897432")
        self.assertEqual(plan.reference_product_code, "S81Q8")
        self.assertIsNone(plan.search_query)
        self.assertEqual(plan.requested_items, [])
        self.assertFalse(plan.send_images)

    def test_explicit_quantity_is_kept(self):
        class ExplicitQuantityAI(FakeAI):
            def create_plan(self, message, context):
                return ConversationPlan(
                    intent=ConversationIntent.PRODUCT_INFORMATION,
                    requested_color="Den",
                    requested_size="37",
                    requested_quantity=2,
                    quantity_explicitly_provided=True,
                    buying_intent=True,
                )

        plan = ConversationPlanner(ExplicitQuantityAI()).plan(
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
                    quantity_explicitly_provided=True,
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

    def test_change_to_each_color_keeps_old_variant_when_requested(self):
        product = {
            **PRODUCT,
            "product_code": "S81V3",
            "product_name": "Sandal S81V3",
            "colors": ["Đen", "Bò"],
            "available_sizes": ["37"],
            "prices": [890_000],
            "variant_prices": [],
        }
        black_item = {
            "product_code": "S81V3",
            "product_name": "Sandal S81V3",
            "color": "Đen",
            "size": "37",
            "quantity": 1,
            "unit_price": 890_000,
            "subtotal": 890_000,
        }
        context = ConversationContext(
            session_id="change-to-each-color",
            channel="web",
            sales_stage=SalesStage.COLLECTING_PRODUCT,
            draft_product_code="S81V3",
            draft_color="Đen",
            draft_size="37",
            draft_quantity=1,
            cart_items=[black_item],
        )
        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
            reference_product_code="S81V3",
            buying_intent=True,
            order_action="change",
            requested_items=[
                RequestedOrderItem(
                    product_code="S81V3", color="Đen", size="37", quantity=1,
                ),
                RequestedOrderItem(
                    product_code="S81V3", color="Bò", size="37", quantity=1,
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
            {(item["color"], item["quantity"]) for item in order["items"]},
            {("Đen", 1), ("Bò", 1)},
        )
        self.assertEqual(order["subtotal"], 1_780_000)
        CTAService().apply(plan, result, context)
        self.assertEqual(result.cta_type, CTAType.PROVIDE_CONTACT)

    def test_presenter_removes_ai_generated_cta_before_backend_cta(self):
        result = ExecutionResult(
            success=True,
            status="order_flow_updated",
            intent=ConversationIntent.PRODUCT_INFORMATION,
            cta_type=CTAType.PROVIDE_CONTACT,
            cta_text="Anh/chị cho em xin họ tên và số điện thoại ạ.",
        )
        reply = (
            "Dạ, em đã ghi nhận mỗi màu một đôi ạ ❤️  "
            "Anh/chị cho em xin thông tin nhận hàng để em ghi nhận tiếp ạ."
        )

        presented = ConversationPresenter.with_cta(reply, result)

        self.assertEqual(
            presented,
            "Dạ, em đã ghi nhận mỗi màu một đôi ạ ❤️\n\n"
            "Anh/chị cho em xin họ tên và số điện thoại ạ.",
        )

    def test_presenter_removes_duplicate_cta_after_normal_sentence(self):
        result = ExecutionResult(
            success=False,
            status="products_not_found",
            intent=ConversationIntent.PRODUCT_SEARCH,
            cta_type=CTAType.PROVIDE_MORE_INFO,
            cta_text=(
                "Anh/chị cho em thêm mã hoặc loại sản phẩm đang tìm "
                "để em hỗ trợ tiếp ạ."
            ),
        )
        reply = (
            "Dạ, em chưa tìm thấy sản phẩm với mã anh/chị vừa cung cấp ạ. "
            "Anh/chị cho em xin thêm mã hoặc loại sản phẩm đang tìm nhé."
        )

        presented = ConversationPresenter.with_cta(reply, result)

        self.assertEqual(
            presented,
            "Dạ, em chưa tìm thấy sản phẩm với mã anh/chị vừa cung cấp ạ.\n\n"
            "Anh/chị cho em thêm mã hoặc loại sản phẩm đang tìm "
            "để em hỗ trợ tiếp ạ.",
        )

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
