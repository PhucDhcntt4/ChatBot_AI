import re

from app.ai.base import AIProvider
from app.conversation.models import (
    ConversationContext,
    ConversationPlan,
    ExecutionResult,
)


class ConversationPresenter:
    def __init__(self, ai: AIProvider) -> None:
        self.ai = ai

    def present(
        self,
        message: str,
        plan: ConversationPlan,
        result: ExecutionResult,
        context: ConversationContext,
    ) -> str:
        reply = self.normalize_customer_address(
            self.ai.present(message, plan, result, context).strip()
        )
        if reply:
            return self.with_cta(reply, result)
        fallback = (
            "Dạ, hiện tại em chưa có đủ thông tin để hỗ trợ chính xác. "
            "Anh/chị cho em thêm mã sản phẩm hoặc nhu cầu cụ thể nhé."
        )
        return self.with_cta(fallback, result)

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
    def with_cta(reply: str, result: ExecutionResult) -> str:
        cta = (result.cta_text or "").strip()
        normalized_reply = reply.strip()
        comparable_reply = re.sub(r"\s+", " ", normalized_reply).casefold()
        comparable_cta = re.sub(r"\s+", " ", cta).casefold()
        if not cta or comparable_cta in comparable_reply:
            return normalized_reply
        return f"{normalized_reply}\n\n{cta}"
