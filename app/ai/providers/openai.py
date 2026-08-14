import json
import os

from openai import OpenAI

from app.ai.base import AIProvider
from app.config import OPENAI_MODEL, PLANNER_PROMPT_PATH, PRESENTER_PROMPT_PATH
from app.conversation.models import (
    ConversationContext,
    ConversationPlan,
    ExecutionResult,
)


class OpenAIProvider(AIProvider):
    provider_name = "openai"

    def __init__(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("Thiếu OPENAI_API_KEY trong file .env")
        self.client = OpenAI(api_key=api_key)
        self.model = OPENAI_MODEL
        self.planner_prompt = PLANNER_PROMPT_PATH.read_text(encoding="utf-8")
        self.presenter_prompt = PRESENTER_PROMPT_PATH.read_text(encoding="utf-8")

    def create_plan(
        self, message: str, context: ConversationContext
    ) -> ConversationPlan:
        response = self.client.responses.parse(
            model=self.model,
            instructions=self.planner_prompt,
            input=json.dumps(
                {
                    "message": message,
                    "context": context.model_dump(mode="json"),
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
        response = self.client.responses.create(
            model=self.model,
            instructions=self.presenter_prompt,
            input=json.dumps(
                {
                    "customer_message": message,
                    "plan": plan.model_dump(mode="json"),
                    "verified_result": result.model_dump(mode="json"),
                    "recent_history": [item.model_dump() for item in context.history[-4:]],
                },
                ensure_ascii=False,
            ),
        )
        return response.output_text.strip()
