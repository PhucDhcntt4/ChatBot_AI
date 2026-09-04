import logging
from time import perf_counter

from app.ai.vision_bridge import ProviderVisionClient
from app.channels.models import IncomingImage
from app.config import PRODUCT_ALBUM_IMAGE_LIMIT
from app.conversation.content_blocks import build_content_blocks
from app.conversation.context import ConversationContextStoreProtocol
from app.conversation.cta import CTAService
from app.conversation.models import (
    ConversationIntent,
    ConversationPlan,
    ConversationResponse,
    ExecutionResult,
    ProductMedia,
)
from app.conversation.presenter import ConversationPresenter
from app.database.product_repository import ProductRepository
from app.product_recognition.catalog_service import ProductCatalogService
from app.product_recognition.handler import ProductImageHandler
from app.product_recognition.image_crop import crop_product_region
from app.product_recognition.image_intent_service import ImageIntentService


logger = logging.getLogger("uvicorn.error")
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_INCOMING_IMAGES = 5


class ProductImageConversationService:
    def __init__(
        self,
        *,
        ai,
        context_store: ConversationContextStoreProtocol,
        repository: ProductRepository | None = None,
        client=None,
    ) -> None:
        self.ai = ai
        self.client = client or ProviderVisionClient(ai)
        self.model = ai.model
        self.context_store = context_store
        self.repository = repository or ProductRepository()
        self.catalog = ProductCatalogService(source="database")
        self.intent_service = ImageIntentService(ai=self.ai, catalog=self.catalog)
        self.handler = ProductImageHandler(
            client=self.client,
            model=self.model,
            catalog=self.catalog,
        )
        self.presenter = ConversationPresenter(ai)
        self.cta = CTAService()

    def recognize(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        caption: str,
        session_id: str,
        channel: str,
    ) -> ConversationResponse:
        """Backward-compatible entry point for Web and Telegram."""
        return self.recognize_many(
            images=[IncomingImage(image_bytes=image_bytes, mime_type=mime_type)],
            caption=caption,
            session_id=session_id,
            channel=channel,
        )

    def recognize_many(
        self,
        *,
        images: list[IncomingImage],
        caption: str,
        session_id: str,
        channel: str,
    ) -> ConversationResponse:
        """Recognize images separately and return one merged conversation reply."""
        started = perf_counter()
        images = list(images[:MAX_INCOMING_IMAGES])
        if not images:
            raise ValueError("Ảnh không có dữ liệu")
        for image in images:
            if not image.image_bytes:
                raise ValueError("Ảnh không có dữ liệu")
            if image.mime_type not in ALLOWED_IMAGE_TYPES:
                raise ValueError("Chỉ hỗ trợ ảnh JPEG, PNG hoặc WebP")

        context = self.context_store.get(session_id, channel)
        classify_seconds = 0.0
        recognition_seconds = 0.0
        product_types: list[str] = []
        codes: list[str] = []
        crop_count = 0

        for image_index, image in enumerate(images, start=1):
            try:
                classify_started = perf_counter()
                classification = self.intent_service.classify(
                    image_bytes=image.image_bytes,
                    mime_type=image.mime_type,
                    caption=caption,
                )
                classify_seconds += perf_counter() - classify_started
                product_type = str(
                    classification.get("product_type") or "unknown"
                )
                product_types.append(product_type)

                cropped_bytes, cropped_mime, crop_applied = crop_product_region(
                    image.image_bytes,
                    classification.get("bounding_box"),
                )
                crop_count += int(crop_applied)
                recognition_bytes = (
                    cropped_bytes if crop_applied else image.image_bytes
                )
                recognition_mime = cropped_mime if crop_applied else image.mime_type

                recognition_started = perf_counter()
                handled = self.handler.handle(
                    image_bytes=recognition_bytes,
                    mime_type=recognition_mime,
                    product_type=product_type,
                    original_image_bytes=(image.image_bytes if crop_applied else None),
                    original_mime_type=(image.mime_type if crop_applied else None),
                )
                recognition_seconds += perf_counter() - recognition_started
                for code in handled.get("product_codes", []):
                    normalized_code = str(code).strip().upper()
                    if normalized_code and normalized_code not in codes:
                        codes.append(normalized_code)
            except Exception:
                logger.exception(
                    "V2 IMAGE ITEM ERROR channel=%s session=%s index=%s",
                    channel,
                    session_id,
                    image_index,
                )

        products = [self.repository.public_info(code) for code in codes]
        products = [product for product in products if product]
        media = [
            ProductMedia(
                product_code=product["product_code"],
                image_urls=(product.get("image_urls") or [])[
                    :PRODUCT_ALBUM_IMAGE_LIMIT
                ],
            )
            for product in products
            if product.get("image_urls")
        ]

        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
            reference_product_code=products[0]["product_code"] if products else None,
            send_images=bool(media),
        )
        result = ExecutionResult(
            success=bool(products),
            status="product_found" if products else "product_not_recognized",
            intent=ConversationIntent.PRODUCT_INFORMATION,
            products=products,
            media=media,
            facts={
                "classified_product_type": (
                    product_types[0] if len(product_types) == 1 else product_types
                ),
                "crop_applied": bool(crop_count),
                "received_image_count": len(images),
                "recognized_product_count": len(products),
                "origin": "image_recognition",
            },
        )
        self.cta.apply(plan, result, context)

        presentation_started = perf_counter()
        if products:
            reply = self.presenter.present(
                caption or "Nhận diện sản phẩm",
                plan,
                result,
                context,
            )
        else:
            reply = (
                "Dạ, em chưa tìm thấy sản phẩm khớp với các hình ảnh "
                "này trong hệ thống. Anh/chị gửi thêm mã sản phẩm hoặc "
                "ảnh rõ hơn, chụp trọn sản phẩm giúp em nhé. 😊"
            )
        reply = self.presenter.with_cta(reply, result)
        presentation_seconds = perf_counter() - presentation_started

        if products:
            context.latest_product_code = products[0]["product_code"]
        self.cta.record(context, result)
        history_message = caption.strip() or (
            f"[Khách gửi {len(images)} ảnh sản phẩm]"
        )
        self.context_store.append(context, "user", history_message)
        self.context_store.append(context, "assistant", reply)
        self.context_store.save(context)

        total_seconds = perf_counter() - started
        logger.debug(
            "V2 IMAGE status=%s channel=%s images=%s types=%s codes=%s "
            "crops=%s cta=%s provider=%s model=%s classification=%.3fs "
            "recognition=%.3fs presenter=%.3fs total=%.3fs",
            result.status,
            channel,
            len(images),
            product_types,
            codes,
            crop_count,
            result.cta_type.value,
            self.ai.provider_name,
            self.ai.model,
            classify_seconds,
            recognition_seconds,
            presentation_seconds,
            total_seconds,
        )
        return ConversationResponse(
            status=result.status,
            message=reply,
            intent=result.intent,
            products=products,
            media=media,
            content_blocks=build_content_blocks(
                reply,
                products,
                media,
                result.cta_text,
            ),
            cta_type=result.cta_type,
            cta_text=result.cta_text,
            provider=self.ai.provider_name,
            model=self.ai.model,
            timing={
                "classification": round(classify_seconds, 3),
                "recognition": round(recognition_seconds, 3),
                "presenter": round(presentation_seconds, 3),
                "total": round(total_seconds, 3),
            },
        )
