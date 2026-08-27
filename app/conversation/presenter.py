import re

from app.ai.base import AIProvider
from app.config import HUMAN_HANDOFF_REPLY_PATH
from app.conversation.models import (
    CTAType,
    ConversationContext,
    ConversationIntent,
    ConversationPlan,
    ExecutionResult,
)


class ConversationPresenter:
    INSUFFICIENT_KNOWLEDGE_REPLY = (
        "Dạ, hiện tại em chưa có đủ thông tin để có thể hỗ trợ "
        "anh/chị về nội dung này ạ."
    )

    def __init__(self, ai: AIProvider) -> None:
        self.ai = ai
        self.human_handoff_reply = HUMAN_HANDOFF_REPLY_PATH.read_text(
            encoding="utf-8"
        ).strip()

    def present(
        self,
        message: str,
        plan: ConversationPlan,
        result: ExecutionResult,
        context: ConversationContext,
    ) -> str:
        if result.status == "human_handoff_requested":
            return self.human_handoff_reply
        if self._has_insufficient_knowledge(plan, result):
            return self.INSUFFICIENT_KNOWLEDGE_REPLY
        reply = self.naturalize_acknowledgement(
            self.normalize_customer_address(
                self.ai.present(message, plan, result, context).strip()
            )
        )
        if reply:
            return self.with_cta(reply, result)
        # A partial contact reply does not need an acknowledgement bubble.
        # When the mechanical acknowledgement was removed, return the one
        # backend-selected question directly instead of generating a fallback.
        if result.cta_text:
            return result.cta_text.strip()
        fallback = (
            "Dạ, hiện tại em chưa có đủ thông tin để hỗ trợ chính xác. "
            "Anh/chị cho em thêm mã sản phẩm hoặc nhu cầu cụ thể nhé."
        )
        return self.with_cta(fallback, result)

    @staticmethod
    def _has_insufficient_knowledge(
        plan: ConversationPlan,
        result: ExecutionResult,
    ) -> bool:
        if plan.intent == ConversationIntent.UNKNOWN:
            return True
        if plan.intent == ConversationIntent.POLICY_QUESTION:
            return not result.knowledge_context
        return result.status in {
            "knowledge_not_found",
            "knowledge_service_disabled",
            "intent_unknown",
        }

    @staticmethod
    def normalize_customer_address(text: str) -> str:
        def replacement(match: re.Match[str]) -> str:
            return "Anh/chị" if match.group(0)[0].isupper() else "anh/chị"

        return re.sub(
            r"\b(?:bạn|quý\s+khách)\b",
            replacement,
            text,
            flags=re.IGNORECASE,
        )

    @staticmethod
    def naturalize_acknowledgement(text: str) -> str:
        """Remove mechanical order acknowledgements occasionally emitted by AI."""

        text = re.sub(
            r"\bDạ,?\s*em\s+(?:đã\s+)?ghi nhận\s+mẫu\s+(.+?)"
            r"\s+vào\s+đơn\s+cho\s+(?:anh/chị|anh|chị)\s+ạ\.?",
            r"Dạ, anh/chị đang chọn mẫu \1 ạ.",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\bDạ,?\s*em\s+(?:đã\s+)?ghi nhận\s+thông tin\s+của\s+"
            r"(?:anh/chị|anh|chị)?[^.!?\n]*[.!?]?",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"^\s*Dạ,?\s*em\s+cảm\s+ơn\s+anh/chị\s+ạ[.!]?\s*$",
            "",
            text,
            flags=re.IGNORECASE,
        )
        return text.strip()

    @staticmethod
    def with_cta(reply: str, result: ExecutionResult) -> str:
        cta = (result.cta_text or "").strip()
        normalized_reply = reply.strip()
        if cta:
            # The presenter model is instructed not to invent a CTA, but an
            # occasional response still appends a request such as "Anh/chị
            # cho em xin...".  Remove that trailing generated request and let
            # the deterministic CTA selected from the order state be the only
            # call to action shown to the customer.
            normalized_reply = re.sub(
                r"(?:\n+|\s{2,}|(?<=[.!?])\s+)"
                r"(?:anh/chị\s+cho\s+em|em\s+xin|mẫu\s+này\s+anh/chị)"
                r"[^\n]*$",
                "",
                normalized_reply,
                flags=re.IGNORECASE,
            ).rstrip()
        comparable_reply = re.sub(r"\s+", " ", normalized_reply).casefold()
        comparable_cta = re.sub(r"\s+", " ", cta).casefold()
        if (
            result.cta_type == CTAType.PROVIDE_MORE_INFO
            and re.search(
                r"(?:gửi|cho|cung cấp)[^.\n]{0,100}"
                r"(?:mã sản phẩm|ảnh rõ hơn|mô tả rõ hơn|thông tin)",
                normalized_reply,
                flags=re.IGNORECASE,
            )
        ):
            return normalized_reply
        if not cta or comparable_cta in comparable_reply:
            return normalized_reply
        return f"{normalized_reply}\n\n{cta}"
