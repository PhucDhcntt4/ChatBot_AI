import re
import unicodedata

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

    @staticmethod
    def _explicit_quantity(
        message: str,
        context: ConversationContext,
    ) -> int | None:
        normalized = unicodedata.normalize("NFD", message.casefold())
        normalized = "".join(
            character
            for character in normalized
            if unicodedata.category(character) != "Mn"
        ).replace("đ", "d")
        unit_match = re.search(
            r"(?<!\d)(\d{1,2})\s*"
            r"(?:doi|chiec|cai|cap|san\s*pham)\b",
            normalized,
        )
        if unit_match:
            quantity = int(unit_match.group(1))
            return quantity if 1 <= quantity <= 99 else None

        # A bare answer is a quantity only while the active order is waiting
        # for it. This does not turn an isolated number during browsing into
        # an order selection.
        if (
            context.sales_stage == SalesStage.COLLECTING_PRODUCT
            and context.draft_quantity is None
            and context.draft_size is not None
        ):
            bare_match = re.fullmatch(
                r"\s*(\d{1,2})(?:\s*(?:a|ạ|e|em|nhe|nhé))?\s*",
                message.casefold(),
            )
            if bare_match:
                quantity = int(bare_match.group(1))
                return quantity if 1 <= quantity <= 99 else None
        return None

    def plan(self, message: str, context: ConversationContext) -> ConversationPlan:
        plan = self.ai.create_plan(message, context)
        # A message containing only an alphanumeric SKU is authoritative.
        # Models sometimes put it in search_query but omit reference_product_code,
        # which would incorrectly route an exact lookup through fuzzy search.
        compact_message = re.sub(r"[\s._-]+", "", message.strip().upper())
        if (
            not plan.reference_product_code
            and re.fullmatch(r"(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*\d)[A-Z0-9]{3,20}", compact_message)
        ):
            plan.reference_product_code = compact_message
            plan.search_query = compact_message
            plan.send_images = True
        # Deterministic fallback for common typo/wording so CTA logic does not
        # ask for a size that the customer has already supplied.
        if not plan.requested_size and not plan.use_knowledge:
            size_match = re.search(
                r"\b(?:size|sizr|sz)\s*[:#-]?\s*(\d{2})\b",
                message,
                flags=re.IGNORECASE,
            )
            if size_match:
                plan.requested_size = size_match.group(1)
        # The explicit flag separates a real customer choice from a model-
        # inferred default. If the model forgets that flag, verify the value
        # against the customer's actual wording before accepting it.
        explicit_quantity = self._explicit_quantity(message, context)
        if explicit_quantity is not None:
            plan.requested_quantity = explicit_quantity
            plan.quantity_explicitly_provided = True
        elif not plan.quantity_explicitly_provided:
            plan.requested_quantity = None
        if not plan.customer_phone:
            phone_match = re.search(r"(?<!\d)(?:\+?84|0)[\d .-]{8,13}(?!\d)", message)
            if phone_match:
                plan.customer_phone = phone_match.group(0).strip()
        # Contact replies such as "Trang 0764897432" can be mistaken by an
        # LLM for one long alphanumeric SKU.  At the contact stage the phone
        # number is authoritative, and a short text prefix is the customer's
        # name. Never let that accidental code create a pending cart item.
        if (
            context.sales_stage == SalesStage.COLLECTING_CONTACT
            and plan.customer_phone
        ):
            phone_digits = re.sub(r"\D", "", plan.customer_phone)
            phone_match = re.search(
                r"(?<!\d)(?:\+?84|0)[\d .-]{8,13}(?!\d)",
                message,
            )
            if phone_match and not plan.customer_name:
                name_candidate = message[:phone_match.start()].strip(" ,;:-")
                if (
                    1 <= len(name_candidate) <= 80
                    and not any(character.isdigit() for character in name_candidate)
                ):
                    plan.customer_name = name_candidate

            normalized_reference = re.sub(
                r"[^A-Z0-9]", "", str(plan.reference_product_code or "").upper()
            )
            looks_like_contact_as_code = bool(
                phone_digits
                and normalized_reference
                and phone_digits in normalized_reference
            )
            if looks_like_contact_as_code:
                plan.reference_product_code = None
                plan.search_query = None
                plan.requested_items = []
                plan.send_images = False
                plan.explicit_image_request = False
        if not plan.payment_method:
            lowered = message.casefold()
            if "cod" in lowered or "nhận hàng" in lowered:
                plan.payment_method = "cod"
            elif "chuyển khoản" in lowered or "bank" in lowered:
                plan.payment_method = "bank_transfer"
        explicit_product_code = bool(plan.reference_product_code)
        explicit_code_in_message = False
        if explicit_product_code:
            normalized_code = re.sub(
                r"[^A-Z0-9]",
                "",
                str(plan.reference_product_code).upper(),
            )
            explicit_code_in_message = bool(
                normalized_code
                and re.search(
                    rf"(?<![A-Z0-9]){re.escape(normalized_code)}(?![A-Z0-9])",
                    message.upper(),
                )
            )
        if not plan.reference_product_code:
            plan.reference_product_code = (
                context.draft_product_code or context.latest_product_code
            )
        for item in plan.requested_items:
            if not item.product_code:
                item.product_code = plan.reference_product_code
            if not item.size:
                item.size = plan.requested_size or context.draft_size
        has_product_selection = bool(
            plan.requested_items
            or plan.requested_color
            or plan.requested_size
            or plan.requested_quantity
        )
        # A short selection such as "lấy 1 cái màu đen" refers to the current
        # product. Models occasionally label it as recommendation because it
        # contains product attributes. Recommendation is only valid when an
        # actual recommendation query/relation exists.
        if (
            plan.intent == ConversationIntent.PRODUCT_RECOMMENDATION
            and plan.buying_intent
            and plan.reference_product_code
            and has_product_selection
            and not plan.search_query
            and plan.relation is None
        ):
            plan.intent = ConversationIntent.PRODUCT_INFORMATION
            plan.send_images = plan.explicit_image_request
        # After a list of recommendations, selecting one explicit product code
        # means "show this product", not "search the category again".  The AI
        # may preserve the previous broad query (for example "giay tay"), which
        # would otherwise make the executor return all three albums again.
        if (
            plan.intent == ConversationIntent.PRODUCT_SEARCH
            and explicit_product_code
            and explicit_code_in_message
        ):
            plan.intent = ConversationIntent.PRODUCT_INFORMATION
            plan.search_query = None
            plan.send_images = True
        order_flow_active = context.sales_stage in {
            SalesStage.COLLECTING_PRODUCT,
            SalesStage.COLLECTING_CONTACT,
            SalesStage.AWAITING_FINAL_CONFIRMATION,
        }
        # Asking for alternatives while an unavailable variant is pending is
        # a catalog recommendation turn, not another mutation of the draft.
        if (
            plan.intent == ConversationIntent.PRODUCT_RECOMMENDATION
            and plan.relation == "same_product_type"
        ):
            plan.buying_intent = False
            plan.order_action = None
            plan.requested_items = []
            plan.send_images = True
        if (
            order_flow_active
            and plan.intent != ConversationIntent.PRODUCT_RECOMMENDATION
            and (
            plan.order_action
            or plan.customer_name
            or plan.customer_phone
            or plan.shipping_address
            or plan.payment_method
            or plan.requested_color
            or plan.requested_size
            or plan.requested_quantity
            or plan.requested_items
            or plan.promotion_action
            or "promotion" in {
                str(item).strip().casefold()
                for item in plan.requested_attributes
            }
            )
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
