from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

from app.conversation.models import (
    ConversationContext,
    ConversationPlan,
    ExecutionResult,
)


VisionResult = TypeVar("VisionResult", bound=BaseModel)


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

    def analyze_images(
        self,
        *,
        instruction: str,
        images: list[tuple[str, bytes, str]],
        response_model: type[VisionResult],
    ) -> VisionResult:
        """Analyze labeled images and return a provider-neutral model."""
        raise NotImplementedError(
            f"Provider {self.provider_name} chưa hỗ trợ nhận diện hình ảnh"
        )
