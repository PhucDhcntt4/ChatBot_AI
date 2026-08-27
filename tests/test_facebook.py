import hashlib
import hmac
import json
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.channels.providers.facebook import FacebookChannelProvider
from app.routes import facebook_router
from app.routes.facebook_router import router


class FakeProvider:
    channel_name = "facebook"

    @staticmethod
    def extract(payload):
        message = payload.get("message") or {}
        return payload["sender"]["id"], message.get("text", ""), None, message.get("mid")

    def send_typing(self, recipient_id):
        pass

    def to_event(self, payload):
        return None, None


class FakeHumanMode:
    def __init__(self):
        self.calls = []

    def enable(self, channel, user_id, **kwargs):
        self.calls.append((channel, user_id, kwargs))


class FacebookWebhookTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        app.state.channel_providers = {"facebook": FakeProvider()}
        app.state.channel_dispatcher = object()
        app.state.human_mode_service = FakeHumanMode()
        self.client = TestClient(app)

    def test_verification_returns_challenge(self):
        with (
            patch("app.routes.facebook_router.CHANNEL_PROVIDERS", {"facebook"}),
            patch("app.routes.facebook_router.FACEBOOK_VERIFY_TOKEN", "verify-me"),
        ):
            response = self.client.get(
                "/webhook/facebook",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "verify-me",
                    "hub.challenge": "12345",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "12345")

    def test_post_rejects_invalid_signature(self):
        with patch("app.routes.facebook_router.CHANNEL_PROVIDERS", {"facebook"}):
            response = self.client.post(
                "/webhook/facebook",
                json={"object": "page", "entry": []},
                headers={"X-Hub-Signature-256": "sha256=invalid"},
            )
        self.assertEqual(response.status_code, 403)

    def test_post_accepts_valid_signature(self):
        payload = {"object": "page", "entry": []}
        body = json.dumps(payload).encode()
        signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
        with (
            patch("app.routes.facebook_router.CHANNEL_PROVIDERS", {"facebook"}),
            patch("app.routes.facebook_router.FACEBOOK_APP_SECRET", "secret"),
        ):
            response = self.client.post(
                "/webhook/facebook",
                content=body,
                headers={
                    "content-type": "application/json",
                    "X-Hub-Signature-256": signature,
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["channel"], "facebook")

    def test_recipient_queue_orders_events_and_does_not_drop_messages(self):
        recipient = "queue-customer"
        newer = {
            "sender": {"id": recipient},
            "timestamp": 200,
            "message": {"mid": "queue-newer", "text": "tin sau"},
        }
        older = {
            "sender": {"id": recipient},
            "timestamp": 100,
            "message": {"mid": "queue-older", "text": "tin trước"},
        }
        app = self.client.app
        try:
            self.assertEqual(
                facebook_router._enqueue_event(app, newer), recipient
            )
            self.assertIsNone(facebook_router._enqueue_event(app, older))
            processed = []
            with (
                patch("app.routes.facebook_router.time.sleep"),
                patch(
                    "app.routes.facebook_router._process_event",
                    side_effect=lambda _app, payload: processed.append(
                        payload["message"]["mid"]
                    ),
                ),
            ):
                facebook_router._drain_recipient_queue(app, recipient)
            self.assertEqual(processed, ["queue-older", "queue-newer"])
        finally:
            with facebook_router._queue_lock:
                facebook_router._event_queues.pop(recipient, None)
                facebook_router._active_recipients.discard(recipient)

    def test_staff_echo_enables_human_mode_for_customer(self):
        event = {
            "sender": {"id": "page-1"},
            "recipient": {"id": "customer-1"},
            "message": {
                "mid": "staff-message",
                "is_echo": True,
                "text": "Nhân viên đang hỗ trợ",
            },
        }

        handled = facebook_router._handle_message_echo(
            self.client.app,
            event,
            "page-1",
        )

        self.assertTrue(handled)
        human = self.client.app.state.human_mode_service
        self.assertEqual(human.calls[0][0:2], ("facebook", "customer-1"))
        self.assertEqual(
            human.calls[0][2]["reason"],
            "staff_replied_in_meta",
        )

    def test_bot_echo_does_not_enable_human_mode(self):
        event = {
            "sender": {"id": "page-1"},
            "recipient": {"id": "customer-1"},
            "message": {
                "mid": "bot-message",
                "is_echo": True,
                "metadata": "donghai_ai",
            },
        }

        handled = facebook_router._handle_message_echo(
            self.client.app,
            event,
            "page-1",
        )

        self.assertTrue(handled)
        self.assertEqual(self.client.app.state.human_mode_service.calls, [])

    def test_page_outbound_without_is_echo_is_treated_as_staff_reply(self):
        event = {
            "sender": {"id": "page-1"},
            "recipient": {"id": "customer-2"},
            "message": {"mid": "business-suite-message", "text": "Em hỗ trợ nhé"},
        }

        handled = facebook_router._handle_message_echo(
            self.client.app,
            event,
            "page-1",
        )

        self.assertTrue(handled)
        self.assertEqual(
            self.client.app.state.human_mode_service.calls[0][0:2],
            ("facebook", "customer-2"),
        )


class FacebookProviderTests(unittest.TestCase):
    def setUp(self):
        self.provider = FacebookChannelProvider("page-token", "v23.0")

    def test_multiple_images_are_sent_as_one_attachment_group(self):
        urls = ["https://cdn.example/1.jpg", "https://cdn.example/2.jpg"]
        with patch.object(self.provider, "_post") as post:
            self.provider.send_image_group("recipient-1", urls)

        post.assert_called_once()
        payload = post.call_args.args[0]
        attachments = payload["message"]["attachments"]
        self.assertEqual(len(attachments), 2)
        self.assertEqual(attachments[0]["type"], "image")
        self.assertEqual(attachments[0]["payload"]["url"], urls[0])
        self.assertNotIn("is_reusable", attachments[0]["payload"])
        self.assertEqual(
            payload["message"]["metadata"],
            self.provider.AI_MESSAGE_METADATA,
        )

    def test_text_message_contains_bot_echo_marker(self):
        with patch.object(self.provider, "_post") as post:
            self.provider.send_text("recipient-1", "Xin chào")

        payload = post.call_args.args[0]
        self.assertEqual(
            payload["message"]["metadata"],
            self.provider.AI_MESSAGE_METADATA,
        )

    def test_single_image_is_sent_as_plain_image(self):
        with patch.object(self.provider, "_post") as post:
            self.provider.send_image_group(
                "recipient-1", ["https://cdn.example/1.jpg"]
            )

        post.assert_called_once()
        payload = post.call_args.args[0]
        attachment = payload["message"]["attachment"]
        self.assertEqual(attachment["type"], "image")

    def test_group_failure_falls_back_to_single_images(self):
        urls = ["https://cdn.example/1.jpg", "https://cdn.example/2.jpg"]
        with patch.object(
            self.provider,
            "_post",
            side_effect=[RuntimeError("Upload attachment failure"), {}, {}],
        ) as post:
            self.provider.send_image_group("recipient-1", urls)

        self.assertEqual(post.call_count, 3)
        self.assertIn("attachments", post.call_args_list[0].args[0]["message"])
        self.assertEqual(
            post.call_args_list[1].args[0]["message"]["attachment"]["type"],
            "image",
        )

    def test_incoming_message_keeps_all_image_attachments(self):
        payload = {
            "sender": {"id": "customer-1"},
            "message": {
                "mid": "message-1",
                "attachments": [
                    {
                        "type": "image",
                        "payload": {"url": "https://cdn.example/1.jpg"},
                    },
                    {
                        "type": "image",
                        "payload": {"url": "https://cdn.example/2.jpg"},
                    },
                ],
            },
        }
        with patch.object(
            self.provider,
            "download_image",
            side_effect=[(b"image-1", "image/jpeg"), (b"image-2", "image/jpeg")],
        ) as download:
            event, message_id = self.provider.to_event(payload)

        self.assertEqual(message_id, "message-1")
        self.assertIsNotNone(event)
        self.assertEqual(download.call_count, 2)
        self.assertEqual(len(event.images), 2)
        self.assertEqual(event.images[0].image_bytes, b"image-1")
        self.assertEqual(event.images[1].image_bytes, b"image-2")
        self.assertEqual(len(event.media_metadata or []), 2)


if __name__ == "__main__":
    unittest.main()
