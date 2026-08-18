import re
import unicodedata
from typing import Any, Callable

from app.config import PRODUCT_ALBUM_IMAGE_LIMIT
from app.conversation.models import (
    ConversationContext,
    ConversationIntent,
    ConversationPlan,
    ExecutionResult,
    ProductMedia,
)
from app.database.product_repository import ProductRepository


class ConversationExecutor:
    def __init__(
        self,
        products: ProductRepository | None = None,
        knowledge_search: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self.products = products or ProductRepository()
        self.knowledge_search = knowledge_search
        self.handlers = {
            ConversationIntent.PRODUCT_SEARCH: self._product_search,
            ConversationIntent.PRODUCT_RECOMMENDATION: self._recommend,
            ConversationIntent.PRODUCT_INFORMATION: self._product_info,
            ConversationIntent.PRODUCT_IMAGES: self._product_images,
            ConversationIntent.POLICY_QUESTION: self._policy,
            ConversationIntent.GENERAL_CHAT: self._general,
            ConversationIntent.UNKNOWN: self._unknown,
        }

    def execute(
        self,
        message: str,
        plan: ConversationPlan,
        context: ConversationContext,
    ) -> ExecutionResult:
        # A model can classify "xem mẫu ABC01" as product_search while still
        # extracting the exact product code. An exact code is authoritative:
        # query it directly instead of sending it through fuzzy text search.
        normalized_reference = re.sub(
            r"[^A-Z0-9]",
            "",
            str(plan.reference_product_code or "").upper(),
        )
        normalized_query = re.sub(
            r"[^A-Z0-9]",
            "",
            str(plan.search_query or "").upper(),
        )
        if (
            plan.intent == ConversationIntent.PRODUCT_SEARCH
            and normalized_reference
            and (
                not normalized_query
                or normalized_query == normalized_reference
            )
        ):
            return self._exact_product_search(plan, context)
        return self.handlers[plan.intent](message, plan, context)

    def _exact_product_search(
        self,
        plan: ConversationPlan,
        context: ConversationContext,
    ) -> ExecutionResult:
        product = self.products.public_info(plan.reference_product_code or "")
        media = None
        if product and (
            plan.send_images
            or product["product_code"] != context.latest_product_code
        ):
            media = self._media(product, plan.requested_color)
        return ExecutionResult(
            success=product is not None,
            status="products_found" if product else "products_not_found",
            intent=plan.intent,
            products=[product] if product else [],
            media=[media] if media else [],
        )

    def _media(
        self, product: dict[str, Any], color: str | None = None
    ) -> ProductMedia | None:
        urls = product.get("image_urls", [])
        if color:
            color_map = product.get("image_urls_by_color", {})
            for existing_color, color_urls in color_map.items():
                if existing_color.casefold() == color.casefold():
                    urls = color_urls
                    color = existing_color
                    break
            else:
                urls = []
        urls = list(dict.fromkeys(urls))[:PRODUCT_ALBUM_IMAGE_LIMIT]
        if not urls:
            return None
        return ProductMedia(
            product_code=product["product_code"],
            color=color,
            image_urls=urls,
        )

    @staticmethod
    def _needs_size_knowledge(message: str, plan: ConversationPlan) -> bool:
        normalized = unicodedata.normalize("NFD", message.casefold())
        normalized = "".join(
            character
            for character in normalized
            if unicodedata.category(character) != "Mn"
        ).replace("đ", "d")
        requested = {
            str(item).strip().casefold()
            for item in plan.requested_attributes
        }
        asks_size_advice = any(
            phrase in normalized
            for phrase in (
                "tu van size",
                "chon size",
                "mang size nao",
                "chan dai",
                "chieu dai chan",
                "do dai ban chan",
            )
        ) or bool(re.search(r"\b\d+(?:[.,]\d+)?\s*cm\b", normalized))
        return asks_size_advice or bool(
            requested.intersection({"size_advice", "size_guide"})
        )

    @staticmethod
    def _payment_knowledge_query(plan: ConversationPlan) -> str | None:
        if plan.payment_method == "cod":
            return "Phương thức thanh toán COD khi nhận hàng và phí giao hàng"
        if plan.payment_method == "bank_transfer":
            return "Phương thức thanh toán chuyển khoản và thông tin thanh toán"
        return None

    def _product_search(self, message, plan, context) -> ExecutionResult:
        query = plan.search_query or plan.reference_product_code or message
        found = self.products.search(query, limit=plan.requested_count)
        media = [item for product in found if (item := self._media(product))]
        # A bare/explicit product code may be classified by the AI as search
        # instead of product_information. Treat the exact single-code result as
        # a product introduction and include its album without trusting the
        # probabilistic send_images flag.
        normalized_query = re.sub(r"[^A-Z0-9]", "", str(query).upper())
        exact_code_result = bool(
            len(found) == 1
            and normalized_query == str(found[0].get("product_code", "")).upper()
        )
        should_send_media = plan.send_images or (
            exact_code_result
            and found[0]["product_code"] != context.latest_product_code
        )
        return ExecutionResult(
            success=bool(found), status="products_found" if found else "products_not_found",
            intent=plan.intent,
            products=found,
            media=media if should_send_media else [],
        )

    def _product_info(self, message, plan, context) -> ExecutionResult:
        product = self.products.public_info(plan.reference_product_code or "")
        # Only attach an album when introducing a new product. Follow-up
        # questions about the current product must not resend the same images.
        is_new_product = bool(
            product
            and product["product_code"] != context.latest_product_code
        )
        # Product information follow-ups (size, color, material, order data)
        # must remain text-only. An album is attached only when the planner
        # explicitly marks this turn as an image/introduction request.
        media = (
            self._media(product)
            if is_new_product and plan.send_images
            else None
        )
        knowledge_context = ""
        sources: list[dict[str, Any]] = []
        promotion_requested = "promotion" in {
            str(item).strip().casefold()
            for item in plan.requested_attributes
        }
        knowledge_query = self._payment_knowledge_query(plan)
        if promotion_requested:
            knowledge_query = message
        if self.knowledge_search and (
            knowledge_query or self._needs_size_knowledge(message, plan)
        ):
            knowledge_result = self.knowledge_search(knowledge_query or message)
            if knowledge_result.get("success"):
                knowledge_context = str(knowledge_result.get("content") or "")
                sources = list(knowledge_result.get("sources") or [])
        return ExecutionResult(
            success=product is not None,
            status="product_found" if product else "product_context_missing",
            intent=plan.intent,
            products=[product] if product else [],
            media=[media] if media else [],
            knowledge_context=knowledge_context,
            sources=sources,
            facts={"requested_attributes": plan.requested_attributes},
        )

    def _product_images(self, message, plan, context) -> ExecutionResult:
        product = self.products.public_info(plan.reference_product_code or "")
        media = self._media(product, plan.requested_color) if product else None
        return ExecutionResult(
            success=media is not None,
            status="images_found" if media else "images_not_found",
            intent=plan.intent,
            products=[product] if product else [],
            media=[media] if media else [],
        )

    def _recommend(self, message, plan, context) -> ExecutionResult:
        reference = self.products.public_info(plan.reference_product_code or "")
        excluded = list(dict.fromkeys(
            context.recently_recommended_codes
            + ([reference["product_code"]] if reference else [])
        ))
        if plan.relation == "same_product_type" and reference:
            found = self.products.recommend_same_type(
                reference["product_type"], excluded, plan.requested_count
            )
        else:
            found = self.products.recommend_by_query(
                plan.search_query or message, plan.requested_count
            )
        media = [item for product in found if (item := self._media(product))]
        return ExecutionResult(
            success=bool(found), status="recommendations_found" if found else "products_not_found",
            intent=plan.intent, products=found, media=media if plan.send_images else [],
        )

    def _policy(self, message, plan, context) -> ExecutionResult:
        if not self.knowledge_search:
            return ExecutionResult(
                success=False, status="knowledge_service_disabled", intent=plan.intent
            )
        result = self.knowledge_search(message)
        return ExecutionResult(
            success=bool(result.get("success")), status=result.get("status", "unknown"),
            intent=plan.intent, knowledge_context=result.get("content", ""),
            sources=result.get("sources", []),
        )

    def _general(self, message, plan, context) -> ExecutionResult:
        return ExecutionResult(success=True, status="general_chat", intent=plan.intent)

    def _unknown(self, message, plan, context) -> ExecutionResult:
        return ExecutionResult(success=False, status="intent_unknown", intent=plan.intent)
