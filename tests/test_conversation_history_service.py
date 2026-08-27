import unittest

from app.conversation.models import (
    CTAType,
    ConversationIntent,
    ConversationResponse,
    ProductMedia,
)
from app.services.conversation_history_service import (
    ConversationHistoryService,
)


class _Repository:
    def __init__(self):
        self.calls = []

    def ensure_session(self, **kwargs):
        self.calls.append(("ensure_session", kwargs))
        return 9

    def save_message(self, **kwargs):
        self.calls.append(("save_message", kwargs))
        return 21

    def update_delivery_status(self, **kwargs):
        self.calls.append(("update_delivery_status", kwargs))
        return True

    def list_messages(self, **kwargs):
        self.calls.append(("list_messages", kwargs))
        return [{"id": 21, "role": "assistant"}]

    def delete_session(self, **kwargs):
        self.calls.append(("delete_session", kwargs))
        return True


class _FailingRepository(_Repository):
    def ensure_session(self, **kwargs):
        raise RuntimeError("database unavailable")


class ConversationHistoryServiceTests(unittest.TestCase):
    def test_save_user_message_includes_channel_identity(self):
        repository = _Repository()
        service = ConversationHistoryService(repository)

        message_id = service.save_user_message(
            session_id="1481483387",
            channel="telegram",
            external_user_id="1481483387",
            external_message_id="501",
            content="Xin chào",
        )

        self.assertEqual(message_id, 21)
        saved = repository.calls[1][1]
        self.assertEqual(saved["role"], "user")
        self.assertEqual(saved["external_message_id"], "501")
        self.assertEqual(saved["delivery_status"], "received")

    def test_save_assistant_extracts_response_metadata(self):
        repository = _Repository()
        service = ConversationHistoryService(repository)
        response = ConversationResponse(
            status="product_found",
            message="Dạ, mẫu S81Q8 hiện có màu Xanh Lá ạ.",
            intent=ConversationIntent.PRODUCT_INFORMATION,
            products=[{"product_code": "S81Q8"}],
            media=[ProductMedia(
                product_code="S81Q8",
                color="Xanh Lá",
                image_urls=["https://cdn.example/image.jpg"],
            )],
            provider="gemini",
            model="gemini-3.5-flash-lite",
            cta_type=CTAType.CHOOSE_COLOR,
            timing={
                "planner": 1.9,
                "executor": 0.062,
                "presenter": 1.078,
                "total": 3.054,
            },
        )

        message_id = service.save_assistant_message(
            session_id="1481483387",
            channel="telegram",
            response=response,
        )

        self.assertEqual(message_id, 21)
        saved = repository.calls[1][1]
        self.assertEqual(saved["intent"], "product_information")
        self.assertEqual(saved["product_codes"], ["S81Q8"])
        self.assertEqual(saved["message_type"], "multimedia")
        self.assertEqual(saved["planner_ms"], 1900)
        self.assertEqual(saved["total_ms"], 3054)
        self.assertEqual(saved["delivery_status"], "generated")
        self.assertEqual(saved["metadata"]["cta_type"], "choose_color")

    def test_history_failure_does_not_break_chat(self):
        service = ConversationHistoryService(_FailingRepository())

        result = service.save_user_message(
            session_id="session-1",
            channel="web",
            content="Xin chào",
        )

        self.assertIsNone(result)

    def test_delivery_status_helpers(self):
        repository = _Repository()
        service = ConversationHistoryService(repository)

        self.assertTrue(service.mark_sent(21))
        self.assertTrue(
            service.mark_send_failed(
                22,
                RuntimeError("Telegram 400"),
                error_code="TELEGRAM_400",
            )
        )
        self.assertFalse(service.mark_sent(None))

        sent = repository.calls[0][1]
        failed = repository.calls[1][1]
        self.assertEqual(sent["delivery_status"], "sent")
        self.assertEqual(failed["delivery_status"], "send_failed")
        self.assertEqual(failed["error_code"], "TELEGRAM_400")

    def test_list_and_delete_use_session_id_as_key(self):
        repository = _Repository()
        service = ConversationHistoryService(repository)

        messages = service.list_messages(
            channel="web",
            session_id="session-1",
        )
        deleted = service.delete_session(
            channel="web",
            session_id="session-1",
        )

        self.assertEqual(messages[0]["id"], 21)
        self.assertTrue(deleted)
        self.assertEqual(
            repository.calls[0][1]["session_key"],
            "session-1",
        )


if __name__ == "__main__":
    unittest.main()
