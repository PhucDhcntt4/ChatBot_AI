import logging
import os
from time import perf_counter

from google import genai

from app.config import GEMINI_MODEL, PRODUCT_ALBUM_IMAGE_LIMIT
from app.conversation.context import ConversationContextStore
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


class ProductImageConversationService:
    def __init__(
        self,
        *,
        ai,
        context_store: ConversationContextStore,
        repository: ProductRepository | None = None,
        client=None,
    ) -> None:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if client is None and not api_key:
            raise RuntimeError("Thiếu GEMINI_API_KEY để nhận diện ảnh sản phẩm")
        self.client = client or genai.Client(api_key=api_key)
        self.model = GEMINI_MODEL
        self.ai = ai
        self.context_store = context_store
        self.repository = repository or ProductRepository()
        self.catalog = ProductCatalogService(source="database")
        self.intent_service = ImageIntentService(
            client=self.client, model=self.model, catalog=self.catalog
        )
        self.handler = ProductImageHandler(
            client=self.client, model=self.model, catalog=self.catalog
        )
        self.presenter = ConversationPresenter(ai)

    def recognize(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        caption: str,
        session_id: str,
        channel: str,
    ) -> ConversationResponse:
        started = perf_counter()
        if not image_bytes:
            raise ValueError("Ảnh không có dữ liệu")
        if mime_type not in ALLOWED_IMAGE_TYPES:
            raise ValueError("Chỉ hỗ trợ ảnh JPEG, PNG hoặc WebP")

        context = self.context_store.get(session_id, channel)
        classify_started = perf_counter()
        classification = self.intent_service.classify(
            image_bytes=image_bytes,
            mime_type=mime_type,
            caption=caption,
        )
        classify_seconds = perf_counter() - classify_started
        bounding_box = classification.get("bounding_box")
        cropped_bytes, cropped_mime, crop_applied = crop_product_region(
            image_bytes, bounding_box
        )
        recognition_bytes = cropped_bytes if crop_applied else image_bytes
        recognition_mime = cropped_mime if crop_applied else mime_type

        recognition_started = perf_counter()
        handled = self.handler.handle(
            image_bytes=recognition_bytes,
            mime_type=recognition_mime,
            product_type=str(classification.get("product_type") or "unknown"),
            original_image_bytes=image_bytes,
            original_mime_type=mime_type,
        )
        recognition_seconds = perf_counter() - recognition_started
        codes = list(dict.fromkeys(
            str(code).strip().upper()
            for code in handled.get("product_codes", [])
            if str(code).strip()
        ))
        products = [self.repository.public_info(code) for code in codes]
        products = [product for product in products if product]
        media = [
            ProductMedia(
                product_code=product["product_code"],
                image_urls=product.get("image_urls", [])[:PRODUCT_ALBUM_IMAGE_LIMIT],
            )
            for product in products
            if product.get("image_urls")
        ]

        plan = ConversationPlan(
            intent=ConversationIntent.PRODUCT_INFORMATION,
            reference_product_code=(products[0]["product_code"] if products else None),
            send_images=bool(media),
        )
        result = ExecutionResult(
            success=bool(products),
            status="product_found" if products else "product_not_recognized",
            intent=ConversationIntent.PRODUCT_INFORMATION,
            products=products,
            media=media,
            facts={
                "classified_product_type": classification.get("product_type"),
                "crop_applied": crop_applied,
            },
        )
        presentation_started = perf_counter()
        if products:
            reply = self.presenter.present(caption or "Nhận diện sản phẩm", plan, result, context)
        else:
            reply = (
                "Dạ, em chưa tìm thấy sản phẩm khớp với hình ảnh này trong hệ thống. "
                "Anh/chị gửi thêm mã sản phẩm hoặc một ảnh rõ hơn, chụp trọn sản phẩm giúp em nhé. 😊"
            )
        presentation_seconds = perf_counter() - presentation_started

        if products:
            context.latest_product_code = products[0]["product_code"]
        history_message = caption.strip() or "[Khách gửi ảnh sản phẩm]"
        self.context_store.append(context, "user", history_message)
        self.context_store.append(context, "assistant", reply)
        self.context_store.save(context)

        logger.info(
            "WEB V2 IMAGE status=%s type=%s codes=%s crop=%s total=%.3fs",
            result.status,
            classification.get("product_type"),
            codes,
            crop_applied,
            perf_counter() - started,
        )
        return ConversationResponse(
            status=result.status,
            message=reply,
            intent=result.intent,
            products=products,
            media=media,
            provider=self.ai.provider_name,
            model=self.ai.model,
            timing={
                "classification": round(classify_seconds, 3),
                "recognition": round(recognition_seconds, 3),
                "presenter": round(presentation_seconds, 3),
                "total": round(perf_counter() - started, 3),
            },
        )
