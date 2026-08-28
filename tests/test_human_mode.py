import json
import unittest
from unittest.mock import patch

from app.channels.dispatcher import ChannelDispatcher
from app.channels.models import IncomingChannelMessage
from app.conversation.models import (
    ConversationIntent,
    ConversationResponse,
)
from app.services.human_mode_service import HumanModeService


class FakeConversation:
    def __init__(self, status="general_chat"):
        self.status = status
        self.calls = 0
        self.context_store = type("Store", (), {"reset": lambda *_: None})()

    def chat(self, *, message, session_id, channel):
        self.calls += 1
        return ConversationResponse(
            status=self.status,
            message="Đã xử lý",
            intent=(
                ConversationIntent.HUMAN_HANDOFF
                if self.status == "human_handoff_requested"
                else ConversationIntent.GENERAL_CHAT
            ),
            provider="fake",
            model="fake",
        )


class FakeHistory:
    def __init__(self):
        self.user_messages = 0
        self.assistant_messages = 0

    def save_user_message(self, **kwargs):
        self.user_messages += 1

    def save_assistant_message(self, **kwargs):
        self.assistant_messages += 1
        return 1


class FakeHumanMode:
    def __init__(self, enabled=False):
        self.enabled = enabled
        self.enable_calls = []
        self.disable_calls = []

    def is_enabled(self, channel, user_id):
        return self.enabled

    def enable(self, channel, user_id, **kwargs):
        self.enabled = True
        self.enable_calls.append((channel, user_id, kwargs))

    def disable(self, channel, user_id):
        self.enabled = False
        self.disable_calls.append((channel, user_id))


class HumanModeTests(unittest.TestCase):
    def test_service_serializes_valid_json(self):
        service = HumanModeService()
        with (
            patch("app.services.human_mode_service.HUMAN_MODE_ENABLED", True),
            patch("app.services.human_mode_service.redis_client") as redis,
        ):
            service.enable("facebook", "customer-1")

        redis.setex.assert_called_once()
        key, ttl, payload = redis.setex.call_args.args
        self.assertEqual(key, "donghai:human_mode:facebook:customer-1")
        self.assertGreater(ttl, 0)
        self.assertEqual(json.loads(payload)["enabled"], True)

    def test_service_uses_custom_ttl_and_exposes_remaining_time(self):
        service = HumanModeService()
        with (
            patch("app.services.human_mode_service.HUMAN_MODE_ENABLED", True),
            patch("app.services.human_mode_service.redis_client") as redis,
        ):
            service.enable("telegram", "customer-2", ttl_seconds=1800)
            _, ttl, payload = redis.setex.call_args.args
            redis.get.return_value = payload
            redis.ttl.return_value = 1797
            details = service.details("telegram", "customer-2")

        self.assertEqual(ttl, 1800)
        self.assertEqual(details["ttl_seconds"], 1800)
        self.assertEqual(details["remaining_seconds"], 1797)
        self.assertIn("expires_at", details)

    def test_service_rejects_invalid_custom_ttl(self):
        service = HumanModeService()
        with self.assertRaises(ValueError):
            service.enable("web", "customer-3", ttl_seconds=30)

    def test_default_ttl_is_saved_and_loaded_from_redis(self):
        service = HumanModeService()
        with patch(
            "app.services.human_mode_service.redis_client"
        ) as redis:
            stored = service.set_default_ttl(1500)
            redis.get.return_value = "1500"
            loaded = service.get_default_ttl()

        redis.set.assert_called_once_with(service.DEFAULT_TTL_KEY, 1500)
        self.assertEqual(stored, 1500)
        self.assertEqual(loaded, 1500)

    def test_human_mode_keeps_user_history_and_skips_ai(self):
        conversation = FakeConversation()
        history = FakeHistory()
        human = FakeHumanMode(enabled=True)
        dispatcher = ChannelDispatcher(
            conversation,
            image_conversation_service=object(),
            history_service=history,
            human_mode_service=human,
        )

        response, message_id = dispatcher.dispatch_with_history(
            IncomingChannelMessage(
                channel="facebook",
                user_id="customer-1",
                text="Tôi cần hỗ trợ",
            ),
            respect_human_mode=True,
        )

        self.assertIsNone(response)
        self.assertIsNone(message_id)
        self.assertEqual(history.user_messages, 1)
        self.assertEqual(history.assistant_messages, 0)
        self.assertEqual(conversation.calls, 0)

    def test_handoff_response_enables_next_turn_human_mode(self):
        conversation = FakeConversation(status="human_handoff_requested")
        human = FakeHumanMode()
        dispatcher = ChannelDispatcher(
            conversation,
            image_conversation_service=object(),
            human_mode_service=human,
        )

        response, _ = dispatcher.dispatch_with_history(
            IncomingChannelMessage(
                channel="facebook",
                user_id="customer-1",
                text="Cho tôi gặp nhân viên",
            ),
            respect_human_mode=True,
        )

        self.assertEqual(response.status, "human_handoff_requested")
        self.assertEqual(len(human.enable_calls), 1)
        self.assertEqual(human.enable_calls[0][:2], ("facebook", "customer-1"))


if __name__ == "__main__":
    unittest.main()
