import logging
from contextvars import ContextVar
from typing import Callable, TypeVar

from pydantic import BaseModel

from app.ai.base import AIProvider
from app.conversation.models import (
    ConversationContext,
    ConversationPlan,
    ExecutionResult,
)


logger = logging.getLogger("uvicorn.error")
ResultT = TypeVar("ResultT")
VisionResultT = TypeVar("VisionResultT", bound=BaseModel)
TRANSIENT_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}
TRANSIENT_ERROR_NAMES = {
    "APIConnectionError",
    "APITimeoutError",
    "InternalServerError",
    "RateLimitError",
    "ServerError",
    "ServiceUnavailableError",
    "TimeoutError",
}


def _error_chain(error: BaseException):
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def transient_ai_error(error: BaseException) -> bool:
    """Return True only for failures that are safe to retry on another AI."""

    for current in _error_chain(error):
        status = getattr(current, "status_code", None)
        if status is None:
            status = getattr(current, "code", None)
        try:
            if int(status) in TRANSIENT_STATUS_CODES:
                return True
        except (TypeError, ValueError):
            pass
        if type(current).__name__ in TRANSIENT_ERROR_NAMES:
            return True
    return False


def _status_code(error: BaseException) -> str:
    for current in _error_chain(error):
        value = getattr(current, "status_code", None)
        if value is None:
            value = getattr(current, "code", None)
        if value is not None:
            return str(value)
    return "unknown"


class FallbackAIProvider(AIProvider):
    """Use a second provider when the primary AI has a temporary outage."""

    def __init__(self, primary: AIProvider, fallback: AIProvider) -> None:
        self.primary = primary
        self.fallback = fallback
        self._active_provider: ContextVar[AIProvider] = ContextVar(
            f"active_ai_provider_{id(self)}",
            default=primary,
        )

    @property
    def provider_name(self) -> str:
        return self._active_provider.get().provider_name

    @property
    def model(self) -> str:
        return self._active_provider.get().model

    def _call(
        self,
        operation: str,
        primary_call: Callable[[], ResultT],
        fallback_call: Callable[[], ResultT],
    ) -> ResultT:
        self._active_provider.set(self.primary)
        try:
            return primary_call()
        except Exception as error:
            if not transient_ai_error(error):
                raise
            self._active_provider.set(self.fallback)
            logger.warning(
                "AI FALLBACK operation=%s primary=%s model=%s status=%s "
                "error=%s fallback=%s fallback_model=%s",
                operation,
                self.primary.provider_name,
                self.primary.model,
                _status_code(error),
                type(error).__name__,
                self.fallback.provider_name,
                self.fallback.model,
            )
            return fallback_call()

    def create_plan(
        self,
        message: str,
        context: ConversationContext,
    ) -> ConversationPlan:
        return self._call(
            "create_plan",
            lambda: self.primary.create_plan(message, context),
            lambda: self.fallback.create_plan(message, context),
        )

    def present(
        self,
        message: str,
        plan: ConversationPlan,
        result: ExecutionResult,
        context: ConversationContext,
    ) -> str:
        return self._call(
            "present",
            lambda: self.primary.present(message, plan, result, context),
            lambda: self.fallback.present(message, plan, result, context),
        )

    def analyze_images(
        self,
        *,
        instruction: str,
        images: list[tuple[str, bytes, str]],
        response_model: type[VisionResultT],
    ) -> VisionResultT:
        return self._call(
            "analyze_images",
            lambda: self.primary.analyze_images(
                instruction=instruction,
                images=images,
                response_model=response_model,
            ),
            lambda: self.fallback.analyze_images(
                instruction=instruction,
                images=images,
                response_model=response_model,
            ),
        )
