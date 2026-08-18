import re

from app.ai.base import AIProvider
from app.config import RECOMMENDATION_DEFAULT_COUNT, RECOMMENDATION_MAX_COUNT
from app.conversation.models import (
    ConversationContext,
    ConversationIntent,
    ConversationPlan,
    SalesStage,
)


class ConversationPlanner:
    def __init__(self, ai: AIProvider) -> None:
        self.ai = ai

    def plan(self, message: str, context: ConversationContext) -> ConversationPlan:
        plan = self.ai.create_plan(message, context)
        # Deterministic fallback for common typo/wording so CTA logic does not
        # ask for a size that the customer has already supplied.
        if not plan.requested_size:
            size_match = re.search(
                r"\b(?:size|sizr|sz)\s*[:#-]?\s*(\d{2})\b",
                message,
                flags=re.IGNORECASE,
            )
            if size_match:
                plan.requested_size = size_match.group(1)
        quantity_match = re.search(
            r"\b(\d{1,2}|một|mot|hai|ba|bốn|bon|tư|tu|năm|nam)\s*"
            r"(?:đôi|doi|cặp|cap|chiếc|chiec|cái|cai|bộ|bo|hộp|hop|"
            r"sản phẩm|san pham|sp)\b",
            message,
            flags=re.IGNORECASE,
        )
        if quantity_match and not plan.requested_items:
            quantity_words = {
                "một": 1, "mot": 1, "hai": 2, "ba": 3,
                "bốn": 4, "bon": 4, "tư": 4, "tu": 4,
                "năm": 5, "nam": 5,
            }
            raw_quantity = quantity_match.group(1).casefold()
            plan.requested_quantity = (
                int(raw_quantity)
                if raw_quantity.isdigit()
                else quantity_words[raw_quantity]
            )
        else:
            # Never trust an AI-inferred default quantity. Quantity is a
            # required order field and must be explicitly stated by customer.
            plan.requested_quantity = None
        if not plan.customer_phone:
            phone_match = re.search(r"(?<!\d)(?:\+?84|0)[\d .-]{8,13}(?!\d)", message)
            if phone_match:
                plan.customer_phone = phone_match.group(0).strip()
        if not plan.payment_method:
            lowered = message.casefold()
            if "cod" in lowered or "nhận hàng" in lowered:
                plan.payment_method = "cod"
            elif "chuyển khoản" in lowered or "bank" in lowered:
                plan.payment_method = "bank_transfer"
        explicit_product_code = bool(plan.reference_product_code)
        if not plan.reference_product_code:
            plan.reference_product_code = (
                context.draft_product_code or context.latest_product_code
            )
        for item in plan.requested_items:
            if not item.product_code:
                item.product_code = plan.reference_product_code
            if not item.size:
                item.size = plan.requested_size or context.draft_size
        order_flow_active = context.sales_stage in {
            SalesStage.COLLECTING_PRODUCT,
            SalesStage.COLLECTING_CONTACT,
            SalesStage.AWAITING_FINAL_CONFIRMATION,
        }
        if order_flow_active and (
            plan.order_action
            or plan.customer_name
            or plan.customer_phone
            or plan.shipping_address
            or plan.payment_method
            or plan.requested_color
            or plan.requested_size
            or plan.requested_quantity
            or plan.requested_items
            or "promotion" in {
                str(item).strip().casefold()
                for item in plan.requested_attributes
            }
        ):
            plan.intent = ConversationIntent.PRODUCT_INFORMATION
        if (
            plan.intent == ConversationIntent.PRODUCT_INFORMATION
            and explicit_product_code
            and plan.reference_product_code != context.latest_product_code
        ):
            # A newly requested product is introduced together with its album.
            # Follow-up questions inherit the code from context and stay text-only.
            plan.send_images = True
        if plan.requested_count < 1:
            plan.requested_count = RECOMMENDATION_DEFAULT_COUNT
        plan.requested_count = min(plan.requested_count, RECOMMENDATION_MAX_COUNT)
        return plan
