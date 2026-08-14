import json
import os

from google import genai
from google.genai import types

from app.ai.base import AIProvider
from app.config import GEMINI_MODEL, PLANNER_PROMPT_PATH, PRESENTER_PROMPT_PATH
from app.conversation.models import (
    ConversationContext,
    ConversationPlan,
    ExecutionResult,
)


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
                        "history": [item.model_dump() for item in context.history[-6:]],
                    },
                },
                ensure_ascii=False,
            ),
            config=types.GenerateContentConfig(
                system_instruction=self.planner_prompt,
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
        response = self.client.models.generate_content(
            model=self.model,
            contents=json.dumps(
                {
                    "customer_message": message,
                    "plan": plan.model_dump(mode="json"),
                    "verified_result": result.model_dump(mode="json"),
                    "recent_history": [item.model_dump() for item in context.history[-4:]],
                },
                ensure_ascii=False,
            ),
            config=types.GenerateContentConfig(
                system_instruction=self.presenter_prompt,
                temperature=0.2,
            ),
        )
        return (response.text or "").strip()
