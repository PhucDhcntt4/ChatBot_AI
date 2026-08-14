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
        return self.handlers[plan.intent](message, plan, context)

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

    def _product_search(self, message, plan, context) -> ExecutionResult:
        query = plan.search_query or plan.reference_product_code or message
        found = self.products.search(query, limit=plan.requested_count)
        media = [item for product in found if (item := self._media(product))]
        return ExecutionResult(
            success=bool(found), status="products_found" if found else "products_not_found",
            intent=plan.intent, products=found, media=media if plan.send_images else [],
        )

    def _product_info(self, message, plan, context) -> ExecutionResult:
        product = self.products.public_info(plan.reference_product_code or "")
        # Only attach an album when introducing a new product. Follow-up
        # questions about the current product must not resend the same images.
        is_new_product = bool(
            product
            and product["product_code"] != context.latest_product_code
        )
        media = self._media(product) if is_new_product else None
        return ExecutionResult(
            success=product is not None,
            status="product_found" if product else "product_context_missing",
            intent=plan.intent,
            products=[product] if product else [],
            media=[media] if media else [],
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
