from app.ai.base import AIProvider
from app.config import IMAGE_INTENT_PROMPT_PATH
from app.product_recognition.catalog_service import ProductCatalogService
from app.product_recognition.models import ImageIntent


class ImageIntentService:
    def __init__(self, ai: AIProvider, catalog: ProductCatalogService) -> None:
        self.ai = ai
        self.catalog = catalog
        self.prompt = IMAGE_INTENT_PROMPT_PATH.read_text(encoding="utf-8")

    def classify(
        self,
        image_bytes: bytes,
        mime_type: str,
        caption: str | None = None,
    ) -> dict[str, object]:
        product_types = self.catalog.product_types()
        product_type_context = (
            "Các productType hợp lệ trong catalog:\n"
            + "\n".join(f"- {product_type}" for product_type in product_types)
            + "\n\nChỉ chọn đúng nguyên văn một giá trị trong danh sách. "
            "Nếu không chắc, trả product_type=null."
        )
        try:
            result = self.ai.analyze_images(
                instruction=(
                    self.prompt
                    + "\n\n"
                    + f"Caption khách gửi: {caption or '(không có)'}"
                    + "\n\n"
                    + product_type_context
                ),
                images=[("CUSTOMER IMAGE", image_bytes, mime_type)],
                response_model=ImageIntent,
            )
        except (ValueError, RuntimeError):
            return {
                "intent": "unknown",
                "product_type": "unknown",
                "bounding_box": None,
            }
        resolved_type = (
            self.catalog.resolve_product_type(result.product_type)
            if result.intent == "product_lookup"
            else None
        )
        return {
            "intent": result.intent,
            "product_type": resolved_type or "unknown",
            "bounding_box": (
                result.bounding_box if result.intent == "product_lookup" else None
            ),
        }
