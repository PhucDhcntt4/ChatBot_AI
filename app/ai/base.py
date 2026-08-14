from abc import ABC, abstractmethod

from app.conversation.models import (
    ConversationContext,
    ConversationPlan,
    ExecutionResult,
)


class AIProvider(ABC):
    provider_name: str
    model: str

    @abstractmethod
    def create_plan(
        self, message: str, context: ConversationContext
    ) -> ConversationPlan:
        raise NotImplementedError

    @abstractmethod
    def present(
        self,
        message: str,
        plan: ConversationPlan,
        result: ExecutionResult,
        context: ConversationContext,
    ) -> str:
        raise NotImplementedError
