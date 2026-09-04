import json
import os
import base64

from openai import OpenAI
from pydantic import BaseModel

from app.ai.base import AIProvider
from app.config import (
    CONVERSATION_INSTRUCTION_PATH,
    OPENAI_MODEL,
    PLANNER_CONTRACT_PATH,
    PRESENTER_CONTRACT_PATH,
    PROMOTION_RULES_PATH,
)
from app.conversation.models import (
    ConversationContext,
    ConversationPlan,
    ExecutionResult,
)
from app.conversation.cta import CTA_TEMPLATES


class OpenAIProvider(AIProvider):
    provider_name = "openai"

    def __init__(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("Thiếu OPENAI_API_KEY trong file .env")
        self.client = OpenAI(api_key=api_key)
        self.model = OPENAI_MODEL
        self.instruction_prompt = CONVERSATION_INSTRUCTION_PATH.read_text(
            encoding="utf-8"
        )
        self.promotion_rules = PROMOTION_RULES_PATH.read_text(encoding="utf-8")
        self.planner_contract = PLANNER_CONTRACT_PATH.read_text(encoding="utf-8")
        self.presenter_contract = PRESENTER_CONTRACT_PATH.read_text(encoding="utf-8")

    def create_plan(
        self, message: str, context: ConversationContext
    ) -> ConversationPlan:
        response = self.client.responses.parse(
            model=self.model,
            instructions=(
                self.instruction_prompt
                + "\n\n"
                + self.promotion_rules
                + "\n\n"
                + self.planner_contract
            ),
            input=json.dumps(
                {
                    "message": message,
                    "context": context.model_dump(mode="json"),
                    "cta_candidates": {
                        cta_type.value: list(sentences)
                        for cta_type, sentences in CTA_TEMPLATES.items()
                    },
                },
                ensure_ascii=False,
            ),
            text_format=ConversationPlan,
        )
        if response.output_parsed is None:
            raise RuntimeError("OpenAI không trả về ConversationPlan")
        return response.output_parsed

    def present(
        self,
        message: str,
        plan: ConversationPlan,
        result: ExecutionResult,
        context: ConversationContext,
    ) -> str:
        verified_result = result.model_dump(mode="json")
        response = self.client.responses.create(
            model=self.model,
            instructions=(
                self.instruction_prompt
                + "\n\n"
                + self.promotion_rules
                + "\n\n"
                + self.presenter_contract
            ),
            input=json.dumps(
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
        )
        return response.output_text.strip()

    def analyze_images(
        self,
        *,
        instruction: str,
        images: list[tuple[str, bytes, str]],
        response_model: type[BaseModel],
    ) -> BaseModel:
        content: list[dict] = [{"type": "input_text", "text": instruction}]
        for label, image_bytes, mime_type in images:
            encoded = base64.b64encode(image_bytes).decode("ascii")
            content.extend([
                {"type": "input_text", "text": label},
                {
                    "type": "input_image",
                    "image_url": f"data:{mime_type};base64,{encoded}",
                    "detail": "high",
                },
            ])
        response = self.client.responses.parse(
            model=self.model,
            input=[{"role": "user", "content": content}],
            text_format=response_model,
        )
        if response.output_parsed is None:
            raise RuntimeError("OpenAI không trả về kết quả nhận diện ảnh")
        return response.output_parsed
