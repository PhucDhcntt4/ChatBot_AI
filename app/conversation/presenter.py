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
        reply = self.ai.present(message, plan, result, context).strip()
        if reply:
            return reply
        return (
            "Dạ, hiện tại em chưa có đủ thông tin để hỗ trợ chính xác. "
            "Anh/chị cho em thêm mã sản phẩm hoặc nhu cầu cụ thể nhé."
        )
