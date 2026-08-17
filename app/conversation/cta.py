from pathlib import Path

from app.config import CTA_TEMPLATE_PATH
from app.conversation.models import (
    CTAType,
    ConversationContext,
    ConversationIntent,
    ConversationPlan,
    ExecutionResult,
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

    def apply(
        self,
        plan: ConversationPlan,
        result: ExecutionResult,
        context: ConversationContext,
    ) -> ExecutionResult:
        cta_type = self._resolve_type(plan, result)
        result.cta_type = cta_type
        result.cta_text = self._select_text(cta_type, context)
        return result

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
    ) -> CTAType:
        if plan.intent in {
            ConversationIntent.POLICY_QUESTION,
            ConversationIntent.GENERAL_CHAT,
        }:
            return CTAType.NONE
        if plan.buying_intent and result.success:
            return CTAType.START_ORDER
        if not result.success:
            return CTAType.PROVIDE_MORE_INFO
        if result.facts.get("origin") == "image_recognition":
            return CTAType.IMAGE_FEEDBACK
        if plan.intent == ConversationIntent.PRODUCT_IMAGES:
            return CTAType.IMAGE_FEEDBACK
        if plan.intent == ConversationIntent.PRODUCT_RECOMMENDATION:
            return CTAType.CHOOSE_PRODUCT
        if plan.intent == ConversationIntent.PRODUCT_SEARCH:
            return (
                CTAType.CHOOSE_PRODUCT
                if len(result.products) > 1
                else CTAType.ASK_SIZE
            )
        requested = {
            str(item).strip().casefold()
            for item in plan.requested_attributes
        }
        if "colors" in requested:
            return CTAType.CHOOSE_COLOR
        if "sizes" in requested:
            return CTAType.SIZE_SUPPORT
        if plan.requested_color:
            return CTAType.CHOOSE_COLOR
        if plan.intent == ConversationIntent.PRODUCT_INFORMATION:
            return CTAType.ASK_SIZE
        return CTAType.NONE

    def _select_text(
        self,
        cta_type: CTAType,
        context: ConversationContext,
    ) -> str | None:
        candidates = CTA_TEMPLATES.get(cta_type, ())
        if not candidates:
            return None
        recent = set(context.cta_history[-self.DEDUP_WINDOW :])
        for candidate in candidates:
            if candidate not in recent:
                return candidate
        return candidates[len(context.cta_history) % len(candidates)]
