import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.conversation.models import ConversationIntent, ConversationResponse
from app.channels import ChannelDispatcher, IncomingChannelMessage
from app.main import app


class FakeTelegramService:
    def __init__(self) -> None:
        self.messages = []
        self.albums = []
        self.typing = []
        self.downloads = []

    def send_typing(self, chat_id):
        self.typing.append(chat_id)

    def send_text(self, chat_id, text):
        self.messages.append((chat_id, text))

    def send_media(self, chat_id, urls):
        self.albums.append((chat_id, list(urls)))

    def download_image(self, file_id):
        self.downloads.append(file_id)
        return b"image", "image/jpeg"

    def extract(self, payload):
        message = payload.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        text = str(message.get("text") or message.get("caption") or "").strip()
        photos = message.get("photo") or []
        file_id = photos[-1].get("file_id") if photos else None
        return chat_id, text, file_id

    def to_event(self, payload):
        chat_id, text, file_id = self.extract(payload)
        image_bytes = mime_type = None
        if file_id:
            image_bytes, mime_type = self.download_image(file_id)
        return IncomingChannelMessage(
            channel="telegram",
            user_id=str(chat_id),
            text=text,
            image_bytes=image_bytes,
            mime_type=mime_type,
            external_message_id=str(
                (payload.get("message") or {}).get("message_id")
            ) if (payload.get("message") or {}).get("message_id") is not None else None,
            external_user_id=str(chat_id),
            media_metadata=[{"telegram_file_id": file_id}] if file_id else None,
        ), file_id

    def send_response(self, recipient_id, response):
        self.send_text(recipient_id, response.message)
        for media in response.media:
            self.send_media(recipient_id, media.image_urls)


class FakeConversationService:
    def __init__(self) -> None:
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return ConversationResponse(
            status="product_found",
            message="Thông tin sản phẩm S81V3",
            intent=ConversationIntent.PRODUCT_INFORMATION,
            media=[{
                "product_code": "S81V3",
                "image_urls": ["https://cdn.test/1.jpg", "https://cdn.test/2.jpg"],
            }],
            provider="fake",
            model="fake-model",
        )


class FakeImageConversationService:
    def __init__(self) -> None:
        self.calls = []

    def recognize(self, **kwargs):
        self.calls.append(kwargs)
        return ConversationResponse(
            status="product_found",
            message="Đã nhận diện S81V3",
            intent=ConversationIntent.PRODUCT_INFORMATION,
            provider="fake",
            model="fake-model",
        )


class FakeHistoryService:
    def __init__(self):
        self.users = []
        self.assistants = []
        self.sent = []
        self.failed = []

    def save_user_message(self, **kwargs):
        self.users.append(kwargs)
        return 40

    def save_assistant_message(self, **kwargs):
        self.assistants.append(kwargs)
        return 41

    def mark_sent(self, message_id):
        self.sent.append(message_id)
        return True

    def mark_send_failed(self, message_id, error, **kwargs):
        self.failed.append((message_id, str(error), kwargs))
        return True


class TelegramTests(unittest.TestCase):
    def setUp(self):
        self.telegram = FakeTelegramService()
        self.conversation = FakeConversationService()
        self.image_conversation = FakeImageConversationService()
        self.history = FakeHistoryService()
        app.state.conversation_service = self.conversation
        app.state.image_conversation_service = self.image_conversation
        app.state.conversation_history_service = self.history
        app.state.channel_providers = {"telegram": self.telegram}
        app.state.channel_dispatcher = ChannelDispatcher(
            self.conversation,
            self.image_conversation,
            self.history,
        )
        self.client = TestClient(app)

    def _post(self, payload, secret="test-secret"):
        with (
            patch("app.routes.telegram_router.CHANNEL_PROVIDERS", {"web", "telegram"}),
            patch("app.routes.telegram_router.TELEGRAM_WEBHOOK_SECRET", "test-secret"),
        ):
            return self.client.post(
                "/api/telegram/webhook",
                json=payload,
                headers={"X-Telegram-Bot-Api-Secret-Token": secret},
            )

    def test_text_uses_telegram_channel_and_sends_album(self):
        response = self._post({
            "update_id": 910001,
            "message": {"chat": {"id": 1481483387}, "text": "S81V3"},
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["channel"], "telegram")
        self.assertEqual(self.conversation.calls[0]["channel"], "telegram")
        self.assertEqual(self.conversation.calls[0]["session_id"], "1481483387")
        self.assertEqual(self.telegram.messages[0][1], "Thông tin sản phẩm S81V3")
        self.assertEqual(len(self.telegram.albums[0][1]), 2)

    def test_photo_uses_same_image_business_flow(self):
        response = self._post({
            "update_id": 910002,
            "message": {
                "chat": {"id": 12345},
                "caption": "Xin thông tin",
                "photo": [{"file_id": "small"}, {"file_id": "largest"}],
            },
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.telegram.downloads, ["largest"])
        call = self.image_conversation.calls[0]
        self.assertEqual(call["channel"], "telegram")
        self.assertEqual(call["session_id"], "12345")
        self.assertEqual(call["caption"], "Xin thông tin")

    def test_invalid_webhook_secret_is_rejected(self):
        response = self._post(
            {"update_id": 910003, "message": {"chat": {"id": 1}, "text": "hi"}},
            secret="wrong",
        )
        self.assertEqual(response.status_code, 403)

    def test_telegram_message_is_saved_and_marked_sent(self):
        response = self._post({
            "update_id": 910004,
            "message": {
                "message_id": 701,
                "chat": {"id": 1481483387},
                "text": "S81V3",
            },
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.history.users[0]["external_message_id"],
            "701",
        )
        self.assertEqual(self.history.users[0]["channel"], "telegram")
        self.assertEqual(len(self.history.assistants), 1)
        self.assertEqual(self.history.sent, [41])


if __name__ == "__main__":
    unittest.main()
