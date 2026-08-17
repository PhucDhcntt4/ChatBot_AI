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
    PROVIDE_MORE_INFO = "provide_more_info"


class ConversationPlan(BaseModel):
    intent: ConversationIntent = ConversationIntent.UNKNOWN
    search_query: str | None = None
    reference_product_code: str | None = None
    requested_color: str | None = None
    requested_attributes: list[str] = Field(default_factory=list)
    requested_count: int = Field(default=3, ge=1, le=5)
    send_images: bool = False
    buying_intent: bool = False
    relation: Literal["same_product_type"] | None = None

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
    last_cta_type: CTAType | None = None
    cta_history: list[str] = Field(default_factory=list)
    history: list[HistoryItem] = Field(default_factory=list)


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
