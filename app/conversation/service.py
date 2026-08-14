import logging
from time import perf_counter

from app.ai.base import AIProvider
from app.conversation.context import (
    ConversationContextStore,
    conversation_context_store,
)
from app.conversation.executor import ConversationExecutor
from app.conversation.models import ConversationResponse
from app.conversation.planner import ConversationPlanner
from app.conversation.presenter import ConversationPresenter


logger = logging.getLogger("uvicorn.error")


class ConversationService:
    def __init__(
        self,
        ai: AIProvider,
        executor: ConversationExecutor | None = None,
        context_store: ConversationContextStore | None = None,
    ) -> None:
        self.ai = ai
        self.planner = ConversationPlanner(ai)
        self.executor = executor or ConversationExecutor()
        self.presenter = ConversationPresenter(ai)
        self.context_store = context_store or conversation_context_store

    def chat(
        self, *, message: str, session_id: str, channel: str
    ) -> ConversationResponse:
        started = perf_counter()
        context = self.context_store.get(session_id, channel)

        plan_started = perf_counter()
        plan = self.planner.plan(message, context)
        plan_seconds = perf_counter() - plan_started
        logger.info(
            "V2 PLAN channel=%s session=%s intent=%s code=%s query=%s color=%s send_images=%s time=%.3fs",
            channel, session_id, plan.intent.value, plan.reference_product_code,
            plan.search_query, plan.requested_color, plan.send_images, plan_seconds,
        )

        execution_started = perf_counter()
        result = self.executor.execute(message, plan, context)
        execution_seconds = perf_counter() - execution_started
        logger.info(
            "V2 EXECUTE session=%s status=%s products=%s media=%s sources=%s time=%.3fs",
            session_id, result.status,
            [item.get("product_code") for item in result.products],
            [{"code": item.product_code, "color": item.color, "images": len(item.image_urls)} for item in result.media],
            len(result.sources), execution_seconds,
        )

        presentation_started = perf_counter()
        reply = self.presenter.present(message, plan, result, context)
        presentation_seconds = perf_counter() - presentation_started
        total_seconds = perf_counter() - started
        logger.info(
            "V2 RESPONSE session=%s status=%s provider=%s model=%s planner=%.3fs executor=%.3fs presenter=%.3fs total=%.3fs",
            session_id, result.status, self.ai.provider_name, self.ai.model,
            plan_seconds, execution_seconds, presentation_seconds, total_seconds,
        )

        if result.products:
            context.latest_product_code = result.products[0]["product_code"]
        if plan.intent.value == "product_recommendation":
            context.recently_recommended_codes = [
                product["product_code"] for product in result.products
            ]
        self.context_store.append(context, "user", message)
        self.context_store.append(context, "assistant", reply)
        self.context_store.save(context)

        return ConversationResponse(
            status=result.status,
            message=reply,
            intent=plan.intent,
            products=result.products,
            media=result.media,
            sources=result.sources,
            provider=self.ai.provider_name,
            model=self.ai.model,
            timing={
                "planner": round(plan_seconds, 3),
                "executor": round(execution_seconds, 3),
                "presenter": round(presentation_seconds, 3),
                "total": round(total_seconds, 3),
            },
        )
