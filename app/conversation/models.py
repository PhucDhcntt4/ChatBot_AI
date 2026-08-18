from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator # type: ignore


class ConversationIntent(str, Enum):
    PRODUCT_SEARCH = "product_search"
    PRODUCT_RECOMMENDATION = "product_recommendation"
    PRODUCT_INFORMATION = "product_information"
    PRODUCT_IMAGES = "product_images"
    POLICY_QUESTION = "policy_question"
    GENERAL_CHAT = "general_chat"
    UNKNOWN = "unknown"


class CTAType(str, Enum):
    NONE = "none"
    ASK_SIZE = "ask_size"
    CHOOSE_COLOR = "choose_color"
    SIZE_SUPPORT = "size_support"
    IMAGE_FEEDBACK = "image_feedback"
    CHOOSE_PRODUCT = "choose_product"
    START_ORDER = "start_order"
    ASK_QUANTITY = "ask_quantity"
    PROVIDE_CONTACT = "provide_contact"
    CHOOSE_PAYMENT = "choose_payment"
    CONFIRM_ORDER = "confirm_order"
    PROVIDE_MORE_INFO = "provide_more_info"


class SalesStage(str, Enum):
    BROWSING = "browsing"
    COLLECTING_PRODUCT = "collecting_product"
    COLLECTING_CONTACT = "collecting_contact"
    AWAITING_FINAL_CONFIRMATION = "awaiting_final_confirmation"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"

    COLLECTING_ORDER = "collecting_product"
    AWAITING_CONFIRMATION = "awaiting_final_confirmation"


class RequestedOrderItem(BaseModel):
    product_code: str | None = None
    color: str | None = None
    size: str | None = None
    quantity: int = Field(ge=1, le=99)

    @field_validator("product_code")
    @classmethod
    def normalize_product_code(cls, value: str | None) -> str | None:
        normalized = (value or "").strip().upper()
        return normalized or None


class ConversationPlan(BaseModel):
    intent: ConversationIntent = ConversationIntent.UNKNOWN
    search_query: str | None = None
    reference_product_code: str | None = None
    requested_color: str | None = None
    requested_size: str | None = None
    requested_quantity: int | None = Field(default=None, ge=1, le=99)
    requested_items: list[RequestedOrderItem] = Field(default_factory=list)
    customer_name: str | None = None
    customer_phone: str | None = None
    shipping_address: str | None = None
    payment_method: Literal["cod", "bank_transfer", "other"] | None = None
    requested_attributes: list[str] = Field(default_factory=list)
    requested_count: int = Field(default=3, ge=1, le=5)
    send_images: bool = False
    buying_intent: bool = False
    suggested_cta_type: CTAType | None = None
    suggested_cta_index: int | None = Field(default=None, ge=0)
    order_action: Literal[
        "confirm", "change", "cancel", "add_item", "remove_item"
    ] | None = None
    relation: Literal["same_product_type"] | None = None
    promotion_name: str | None = None
    promotion_code: str | None = None
    promotion_discount_amount: int | None = Field(default=None, ge=0)
    promotion_benefit: str | None = None
    promotion_eligible: bool | None = None

    @field_validator("reference_product_code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        normalized = (value or "").strip().upper()
        return normalized or None


class HistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1)


class ConversationContext(BaseModel):
    session_id: str
    channel: str
    latest_product_code: str | None = None
    recently_recommended_codes: list[str] = Field(default_factory=list)
    sales_stage: SalesStage = SalesStage.BROWSING
    draft_product_code: str | None = None
    draft_color: str | None = None
    draft_size: str | None = None
    draft_quantity: int | None = None
    draft_customer_name: str | None = None
    draft_customer_phone: str | None = None
    draft_shipping_address: str | None = None
    draft_payment_method: str | None = None
    draft_promotion_note: str | None = None
    draft_promotion_name: str | None = None
    draft_promotion_code: str | None = None
    draft_promotion_discount_amount: int | None = None
    draft_promotion_benefit: str | None = None
    draft_promotion_eligible: bool | None = None
    cart_items: list[dict[str, Any]] = Field(default_factory=list)
    last_cta_type: CTAType | None = None
    cta_history: list[str] = Field(default_factory=list)
    history: list[HistoryItem] = Field(default_factory=list)
    confirmed_order_id: str | None = None
    sheet_export_status: Literal["pending", "exported", "failed"] | None = None


class ProductMedia(BaseModel):
    product_code: str
    color: str | None = None
    image_urls: list[str] = Field(default_factory=list)


class ExecutionResult(BaseModel):
    success: bool
    status: str
    intent: ConversationIntent
    products: list[dict[str, Any]] = Field(default_factory=list)
    media: list[ProductMedia] = Field(default_factory=list)
    knowledge_context: str = ""
    sources: list[dict[str, Any]] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)
    cta_type: CTAType = CTAType.NONE
    cta_text: str | None = None


class ConversationResponse(BaseModel):
    status: str
    message: str
    intent: ConversationIntent
    products: list[dict[str, Any]] = Field(default_factory=list)
    media: list[ProductMedia] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    cta_type: CTAType = CTAType.NONE
    cta_text: str | None = None
    provider: str
    model: str
    timing: dict[str, float] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    channel: str = Field(default="web", min_length=1)


class ResetRequest(BaseModel):
    session_id: str = Field(min_length=1)
    channel: str = Field(default="web", min_length=1)
