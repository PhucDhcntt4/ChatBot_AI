import unittest

from pydantic import BaseModel

from app.ai.base import AIProvider
from app.ai.fallback import FallbackAIProvider, transient_ai_error
from app.conversation.models import (
    ConversationContext,
    ConversationIntent,
    ConversationPlan,
    ExecutionResult,
)


class TemporaryAIError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"temporary status {status_code}")
        self.status_code = status_code


class ImageResult(BaseModel):
    value: str


class StubProvider(AIProvider):
    def __init__(self, name: str, error: Exception | None = None):
        self.provider_name = name
        self.model = f"{name}-model"
        self.error = error
        self.calls: list[str] = []

    def _result(self, operation: str, value):
        self.calls.append(operation)
        if self.error is not None:
            raise self.error
        return value

    def create_plan(self, message, context):
        return self._result(
            "create_plan",
            ConversationPlan(intent=ConversationIntent.GENERAL_CHAT),
        )

    def present(self, message, plan, result, context):
        return self._result("present", f"reply from {self.provider_name}")

    def analyze_images(self, *, instruction, images, response_model):
        return self._result(
            "analyze_images",
            response_model(value=self.provider_name),
        )


class FallbackAIProviderTests(unittest.TestCase):
    def setUp(self):
        self.context = ConversationContext(session_id="test", channel="web")
        self.plan = ConversationPlan(intent=ConversationIntent.GENERAL_CHAT)
        self.result = ExecutionResult(
            success=True,
            status="ok",
            intent=ConversationIntent.GENERAL_CHAT,
        )

    def test_503_uses_fallback_for_presenter(self):
        primary = StubProvider("primary", TemporaryAIError(503))
        fallback = StubProvider("fallback")
        provider = FallbackAIProvider(primary, fallback)

        reply = provider.present("hello", self.plan, self.result, self.context)

        self.assertEqual(reply, "reply from fallback")
        self.assertEqual(primary.calls, ["present"])
        self.assertEqual(fallback.calls, ["present"])
        self.assertEqual(provider.provider_name, "fallback")
        self.assertEqual(provider.model, "fallback-model")

    def test_non_transient_error_is_not_hidden(self):
        primary = StubProvider("primary", ValueError("bad response"))
        fallback = StubProvider("fallback")
        provider = FallbackAIProvider(primary, fallback)

        with self.assertRaises(ValueError):
            provider.create_plan("hello", self.context)

        self.assertEqual(fallback.calls, [])

    def test_recognizes_transient_statuses(self):
        self.assertTrue(transient_ai_error(TemporaryAIError(429)))
        self.assertTrue(transient_ai_error(TemporaryAIError(503)))
        self.assertFalse(transient_ai_error(TemporaryAIError(400)))


if __name__ == "__main__":
    unittest.main()
