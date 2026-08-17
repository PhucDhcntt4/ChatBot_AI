import unittest

from fastapi.testclient import TestClient

from app.conversation.models import ConversationIntent, ConversationResponse
from app.main import app


class FakeConversationService:
    class AI:
        provider_name = "fake"
        model = "fake-model"

    ai = AI()

    def chat(self, *, message, session_id, channel):
        return ConversationResponse(
            status="product_found",
            message="Dạ, em gửi anh/chị thông tin sản phẩm.",
            intent=ConversationIntent.PRODUCT_INFORMATION,
            products=[{"product_code": "G81V6"}],
            media=[{
                "product_code": "G81V6",
                "color": "Kem",
                "image_urls": ["https://example.test/image.jpg"],
            }],
            provider="fake",
            model="fake-model",
            timing={"total": 0.01},
        )


class FakeImageConversationService:
    def recognize(self, **kwargs):
        return ConversationResponse(
            status="product_found",
            message="Dạ, em nhận diện được mã G81V6.",
            intent=ConversationIntent.PRODUCT_INFORMATION,
            products=[{"product_code": "G81V6"}],
            media=[{
                "product_code": "G81V6",
                "image_urls": ["https://example.test/g81v6.jpg"],
            }],
            provider="fake",
            model="fake-model",
            timing={"total": 0.02},
        )


class WebTests(unittest.TestCase):
    def setUp(self):
        app.state.conversation_service = FakeConversationService()
        app.state.image_conversation_service = FakeImageConversationService()
        self.client = TestClient(app)

    def test_home_page_redirects_to_combined_admin_chat_page(self):
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/admin/products")

    def test_chat_contract_contains_media(self):
        response = self.client.post(
            "/api/chat",
            json={
                "message": "Cho xem màu kem",
                "session_id": "web-test",
                "channel": "web",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["media"][0]["product_code"], "G81V6")
        self.assertEqual(payload["timing"]["total"], 0.01)

    def test_image_chat_accepts_multipart_and_returns_media(self):
        response = self.client.post(
            "/api/chat/image",
            data={"session_id": "web-image", "channel": "web", "caption": "Xin thông tin"},
            files={"image": ("product.jpg", b"fake-image", "image/jpeg")},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "product_found")
        self.assertEqual(payload["media"][0]["product_code"], "G81V6")


if __name__ == "__main__":
    unittest.main()
