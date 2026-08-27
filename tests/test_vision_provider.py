import unittest

from google.genai import types

from app.ai.base import AIProvider
from app.ai.vision_bridge import ProviderVisionClient
from app.conversation.models import ConversationContext, ConversationPlan, ExecutionResult
from app.product_recognition.models import ImageIntent


class FakeVisionProvider(AIProvider):
    provider_name = "fake"
    model = "fake-vision"

    def __init__(self) -> None:
        self.received_images = []

    def create_plan(self, message, context):
        return ConversationPlan()

    def present(self, message, plan, result, context):
        return ""

    def analyze_images(self, *, instruction, images, response_model):
        self.received_images = images
        return response_model(
            intent="product_lookup",
            product_type="TEST",
            bounding_box=[0, 0, 100, 100],
        )


class VisionProviderTest(unittest.TestCase):
    def test_bridge_uses_selected_provider_for_gemini_style_recognition_calls(self):
        provider = FakeVisionProvider()
        client = ProviderVisionClient(provider)
        response = client.models.generate_content(
            model="ignored",
            contents=[
                "CUSTOMER IMAGE",
                types.Part.from_bytes(data=b"image", mime_type="image/jpeg"),
            ],
            config=types.GenerateContentConfig(response_schema=ImageIntent),
        )

        parsed = ImageIntent.model_validate_json(response.text)
        self.assertEqual(parsed.product_type, "TEST")
        self.assertEqual(provider.received_images[0][1], b"image")


if __name__ == "__main__":
    unittest.main()
