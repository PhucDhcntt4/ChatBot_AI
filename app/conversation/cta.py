from pathlib import Path

from app.config import CTA_TEMPLATE_PATH
from app.conversation.models import (
    CTAType,
    ConversationContext,
    ConversationIntent,
    ConversationPlan,
    ExecutionResult,
    SalesStage,
)


def parse_cta_templates(
    content: str,
    source_name: str = "cta_templates.txt",
) -> dict[CTAType, tuple[str, ...]]:
    templates: dict[CTAType, list[str]] = {}
    current_type: CTAType | None = None
    for line_number, raw_line in enumerate(
        content.splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            try:
                current_type = CTAType(section)
            except ValueError as error:
                raise ValueError(
                    f"CTA section không hợp lệ tại dòng {line_number}: "
                    f"[{section}] ({source_name})"
                ) from error
            if current_type == CTAType.NONE:
                raise ValueError("Không khai báo câu cho section [none]")
            templates.setdefault(current_type, [])
            continue

        if current_type is None:
            raise ValueError(
                f"Câu CTA tại dòng {line_number} chưa nằm trong section"
            )
        templates[current_type].append(line)

    required_types = set(CTAType) - {CTAType.NONE}
    missing = sorted(
        item.value
        for item in required_types
        if not templates.get(item)
    )
    if missing:
        raise ValueError(
            "File CTA thiếu câu cho section: " + ", ".join(missing)
        )

    return {
        cta_type: tuple(sentences)
        for cta_type, sentences in templates.items()
    }


def load_cta_templates(
    path: str | Path,
) -> dict[CTAType, tuple[str, ...]]:
    """Read editable CTA groups from an UTF-8 section-based text file."""

    template_path = Path(path)
    if not template_path.is_file():
        raise RuntimeError(f"Không tìm thấy file CTA: {template_path}")
    return parse_cta_templates(
        template_path.read_text(encoding="utf-8"),
        template_path.name,
    )


CTA_TEMPLATES = load_cta_templates(CTA_TEMPLATE_PATH)


class CTAService:
    """Select one contextual CTA and avoid recently used wording."""

    HISTORY_LIMIT = 5
    DEDUP_WINDOW = 3
    CONTACT_FIELD_LABELS = {
        "customer_name": "họ tên",
        "customer_phone": "số điện thoại",
        "shipping_address": "địa chỉ nhận hàng",
        "payment_method": "phương thức thanh toán (COD hoặc chuyển khoản)",
    }

    def apply(
        self,
        plan: ConversationPlan,
        result: ExecutionResult,
        context: ConversationContext,
    ) -> ExecutionResult:
        cta_type = self._resolve_type(plan, result, context)
        result.cta_type = cta_type
        selected_text = self._select_text(
            cta_type,
            context,
            plan.suggested_cta_index,
        )
        result.cta_text = self._format_text(selected_text, result)
        return result

    @classmethod
    def _format_text(
        cls,
        text: str | None,
        result: ExecutionResult,
    ) -> str | None:
        if not text or "{fields}" not in text:
            return text
        missing = result.facts.get("missing_contact_fields") or []
        labels = [
            cls.CONTACT_FIELD_LABELS[field]
            for field in missing
            if field in cls.CONTACT_FIELD_LABELS
        ]
        if not labels:
            return None
        if len(labels) == 1:
            fields_text = labels[0]
        else:
            fields_text = ", ".join(labels[:-1]) + " và " + labels[-1]
        return text.replace("{fields}", fields_text)

    def record(
        self,
        context: ConversationContext,
        result: ExecutionResult,
    ) -> None:
        context.last_cta_type = result.cta_type
        if result.cta_text:
            context.cta_history.append(result.cta_text)
            context.cta_history = context.cta_history[-self.HISTORY_LIMIT :]

    @staticmethod
    def _resolve_type(
        plan: ConversationPlan,
        result: ExecutionResult,
        context: ConversationContext,
    ) -> CTAType:
        product = result.products[0] if len(result.products) == 1 else None
        has_color_options = bool((product or {}).get("colors"))
        has_size_options = bool((product or {}).get("available_sizes"))
        if result.facts.get("order_confirmed") or result.facts.get("order_cancelled"):
            return CTAType.NONE
        if context.sales_stage == SalesStage.COLLECTING_PRODUCT:
            missing = set(result.facts.get("missing_product_fields") or [])
            if "product_code" in missing:
                return CTAType.START_ORDER
            if "color" in missing:
                return CTAType.CHOOSE_COLOR
            if "size" in missing:
                return CTAType.ASK_SIZE
            if "quantity" in missing:
                return CTAType.ASK_QUANTITY
            return CTAType.START_ORDER
        if context.sales_stage == SalesStage.COLLECTING_CONTACT:
            missing = set(result.facts.get("missing_contact_fields") or [])
            if missing == {"payment_method"}:
                return CTAType.CHOOSE_PAYMENT
            return CTAType.PROVIDE_CONTACT
        if context.sales_stage == SalesStage.AWAITING_FINAL_CONFIRMATION:
            return CTAType.CONFIRM_ORDER
        if context.sales_stage in {SalesStage.CONFIRMED, SalesStage.CANCELLED}:
            return CTAType.NONE
        if plan.intent in {
            ConversationIntent.POLICY_QUESTION,
            ConversationIntent.GENERAL_CHAT,
        }:
            return CTAType.NONE
        if not result.success:
            return CTAType.PROVIDE_MORE_INFO
        if plan.buying_intent:
            has_color = bool(
                (context.draft_color or plan.requested_color or "").strip()
            )
            has_size = bool(
                (context.draft_size or plan.requested_size or "").strip()
            )
            if (has_color or not has_color_options) and (
                has_size or not has_size_options
            ):
                return CTAType.ASK_QUANTITY
            if has_color and has_size_options:
                return CTAType.ASK_SIZE
            if has_size and has_color_options:
                return CTAType.CHOOSE_COLOR
            # Before OrderFlow starts, use the neutral start-order CTA. Once
            # the draft is active, missing_product_fields above selects the
            # exact dimension required by this product.
            return CTAType.START_ORDER
        suggested = plan.suggested_cta_type
        if suggested is not None:
            # Ordering CTAs are only valid when the planner also detected a
            # buying intent. This prevents an AI suggestion from advancing an
            # ordinary information request into an order flow.
            if suggested in {
                CTAType.START_ORDER,
                CTAType.CONFIRM_ORDER,
            }:
                return CTAType.NONE
            if suggested in {CTAType.ASK_SIZE, CTAType.SIZE_SUPPORT} and not has_size_options:
                return CTAType.CHOOSE_COLOR if has_color_options else CTAType.NONE
            return suggested
        if result.facts.get("origin") == "image_recognition":
            return CTAType.IMAGE_FEEDBACK
        if plan.intent == ConversationIntent.PRODUCT_IMAGES:
            return CTAType.IMAGE_FEEDBACK
        if plan.intent == ConversationIntent.PRODUCT_RECOMMENDATION:
            return CTAType.CHOOSE_PRODUCT
        if plan.intent == ConversationIntent.PRODUCT_SEARCH:
            if len(result.products) > 1:
                return CTAType.CHOOSE_PRODUCT
            if has_size_options:
                return CTAType.ASK_SIZE
            if has_color_options:
                return CTAType.CHOOSE_COLOR
            return CTAType.NONE
        requested = {
            str(item).strip().casefold()
            for item in plan.requested_attributes
        }
        if "colors" in requested:
            return CTAType.CHOOSE_COLOR
        if "sizes" in requested:
            return CTAType.SIZE_SUPPORT if has_size_options else CTAType.NONE
        if plan.requested_color:
            return CTAType.CHOOSE_COLOR
        if plan.intent == ConversationIntent.PRODUCT_INFORMATION:
            if has_size_options:
                return CTAType.ASK_SIZE
            if has_color_options:
                return CTAType.CHOOSE_COLOR
            return CTAType.NONE
        return CTAType.NONE

    def _select_text(
        self,
        cta_type: CTAType,
        context: ConversationContext,
        preferred_index: int | None = None,
    ) -> str | None:
        candidates = CTA_TEMPLATES.get(cta_type, ())
        if not candidates:
            return None
        recent = set(context.cta_history[-self.DEDUP_WINDOW :])
        if preferred_index is not None and preferred_index < len(candidates):
            preferred = candidates[preferred_index]
            if preferred not in recent:
                return preferred
        for candidate in candidates:
            if candidate not in recent:
                return candidate
        return candidates[len(context.cta_history) % len(candidates)]
