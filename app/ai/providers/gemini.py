import json
import os

from google import genai
from google.genai import types

from app.ai.base import AIProvider
from app.config import (
    GEMINI_MODEL,
    PLANNER_PROMPT_PATH,
    PRESENTER_PROMPT_PATH,
    PROMOTION_RULES_PATH,
)
from app.conversation.models import (
    ConversationContext,
    ConversationPlan,
    ExecutionResult,
)
from app.conversation.cta import CTA_TEMPLATES


class GeminiProvider(AIProvider):
    provider_name = "gemini"

    def __init__(self) -> None:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("Thiếu GEMINI_API_KEY trong file .env")
        self.client = genai.Client(api_key=api_key)
        self.model = GEMINI_MODEL
        self.planner_prompt = PLANNER_PROMPT_PATH.read_text(encoding="utf-8")
        self.presenter_prompt = PRESENTER_PROMPT_PATH.read_text(encoding="utf-8")
        self.promotion_rules = PROMOTION_RULES_PATH.read_text(encoding="utf-8")

    def create_plan(
        self, message: str, context: ConversationContext
    ) -> ConversationPlan:
        response = self.client.models.generate_content(
            model=self.model,
            contents=json.dumps(
                {
                    "message": message,
                    "context": {
                        "latest_product_code": context.latest_product_code,
                        "recently_recommended_codes": context.recently_recommended_codes,
                        "sales_stage": context.sales_stage.value,
                        "order_draft": {
                            "product_code": context.draft_product_code,
                            "color": context.draft_color,
                            "size": context.draft_size,
                            "quantity": context.draft_quantity,
                            "customer_name": context.draft_customer_name,
                            "customer_phone": context.draft_customer_phone,
                            "shipping_address": context.draft_shipping_address,
                            "payment_method": context.draft_payment_method,
                            "promotion_name": context.draft_promotion_name,
                            "promotion_code": context.draft_promotion_code,
                            "promotion_discount_amount": context.draft_promotion_discount_amount,
                            "promotion_benefit": context.draft_promotion_benefit,
                            "promotion_eligible": context.draft_promotion_eligible,
                        },
                        "cart_items": context.cart_items,
                        "history": [item.model_dump() for item in context.history[-6:]],
                    },
                    "cta_candidates": {
                        cta_type.value: list(sentences)
                        for cta_type, sentences in CTA_TEMPLATES.items()
                    },
                },
                ensure_ascii=False,
            ),
            config=types.GenerateContentConfig(
                system_instruction=(
                    self.planner_prompt
                    + "\n\n"
                    + self.promotion_rules
                ),
                response_mime_type="application/json",
                response_schema=ConversationPlan,
                temperature=0,
            ),
        )
        return ConversationPlan.model_validate_json(response.text or "{}")

    def present(
        self,
        message: str,
        plan: ConversationPlan,
        result: ExecutionResult,
        context: ConversationContext,
    ) -> str:
        verified_result = result.model_dump(mode="json")
        response = self.client.models.generate_content(
            model=self.model,
            contents=json.dumps(
                {
                    "customer_message": message,
                    "plan": plan.model_dump(mode="json"),
                    "verified_result": verified_result,
                    "promotion_history": [
                        item.model_dump(mode="json")
                        for item in context.history[-8:]
                    ],
                },
                ensure_ascii=False,
            ),
            config=types.GenerateContentConfig(
                system_instruction=(
                    self.presenter_prompt
                    + "\n\n"
                    + self.promotion_rules
                ),
                temperature=0.2,
            ),
        )
        return (response.text or "").strip()
