import logging
from time import perf_counter

from app.ai.base import AIProvider
from app.conversation.context import (
    ConversationContextStore,
    conversation_context_store,
)
from app.conversation.cta import CTAService
from app.conversation.executor import ConversationExecutor
from app.conversation.fast_response import FastResponseService
from app.conversation.models import (
    CTAType,
    ConversationIntent,
    ConversationResponse,
)
from app.conversation.order_flow import OrderFlowService
from app.conversation.planner import ConversationPlanner
from app.conversation.presenter import ConversationPresenter
from app.services.sheets_service import SheetsService


logger = logging.getLogger("uvicorn.error")


class ConversationService:
    def __init__(
        self,
        ai: AIProvider,
        executor: ConversationExecutor | None = None,
        context_store: ConversationContextStore | None = None,
        sheets_service: SheetsService | None = None,
    ) -> None:
        self.ai = ai
        self.planner = ConversationPlanner(ai)
        self.executor = executor or ConversationExecutor()
        self.presenter = ConversationPresenter(ai)
        self.cta = CTAService()
        self.order_flow = OrderFlowService()
        self.fast_responses = FastResponseService()
        self.context_store = context_store or conversation_context_store
        # The configured instance is injected by app.main. Keeping the local
        # fallback disabled prevents unit tests and ad-hoc service instances
        # from contacting an external system unexpectedly.
        self.sheets_service = sheets_service or SheetsService(enabled=False)

    def _export_confirmed_order(self, result, context) -> None:
        if result.status != "order_confirmed":
            return
        order_summary = result.facts.get("order_summary")
        if not order_summary or not self.sheets_service.enabled:
            return
        if (
            context.confirmed_order_id
            and context.sheet_export_status == "exported"
        ):
            result.facts["sheet_export"] = {
                "status": "already_exported",
                "order_id": context.confirmed_order_id,
            }
            return

        order_id = (
            context.confirmed_order_id
            or self.sheets_service.create_order_id()
        )
        context.confirmed_order_id = order_id
        context.sheet_export_status = "pending"
        try:
            row_count = self.sheets_service.append_confirmed_order(
                order_id=order_id,
                order_summary=order_summary,
                channel=context.channel,
                session_id=context.session_id,
            )
        except Exception as error:
            context.sheet_export_status = "failed"
            result.facts["sheet_export"] = {
                "status": "failed",
                "order_id": order_id,
            }
            logger.exception(
                "GOOGLE SHEETS ORDER EXPORT FAILED order_id=%s session=%s",
                order_id,
                context.session_id,
            )
            return

        context.sheet_export_status = "exported"
        result.facts["sheet_export"] = {
            "status": "exported",
            "order_id": order_id,
            "rows": row_count,
        }

    def _fast_response(
        self,
        *,
        message: str,
        context,
        started: float,
    ) -> ConversationResponse | None:
        fast_started = perf_counter()
        reply = self.fast_responses.reply(message, context)
        if not reply:
            return None
        elapsed = perf_counter() - fast_started
        total = perf_counter() - started
        self.context_store.append(context, "user", message)
        self.context_store.append(context, "assistant", reply)
        self.context_store.save(context)
        logger.info(
            "V2 FAST RESPONSE channel=%s session=%s intent=general_chat "
            "lookup=%.3fs total=%.3fs",
            context.channel,
            context.session_id,
            elapsed,
            total,
        )
        return ConversationResponse(
            status="general_chat",
            message=reply,
            intent=ConversationIntent.GENERAL_CHAT,
            cta_type=CTAType.NONE,
            provider="local",
            model="fast-responses",
            timing={
                "planner": 0.0,
                "executor": 0.0,
                "presenter": 0.0,
                "total": round(total, 3),
            },
        )

    @staticmethod
    def _safe_order_log(order: dict | None) -> dict | None:
        if not order:
            return None
        return {
            "product_code": order.get("product_code"),
            "color": order.get("color"),
            "size": order.get("size"),
            "quantity": order.get("quantity"),
            "items": [
                {
                    "product_code": item.get("product_code"),
                    "color": item.get("color"),
                    "size": item.get("size"),
                    "quantity": item.get("quantity"),
                }
                for item in order.get("items", [])
            ],
            "contact_fields": [
                field
                for field in (
                    "customer_name",
                    "customer_phone",
                    "shipping_address",
                    "payment_method",
                )
                if order.get(field)
            ],
        }

    def chat(
        self, *, message: str, session_id: str, channel: str
    ) -> ConversationResponse:
        started = perf_counter()
        context = self.context_store.get(session_id, channel)
        fast_response = self._fast_response(
            message=message,
            context=context,
            started=started,
        )
        if fast_response is not None:
            return fast_response

        plan_started = perf_counter()
        plan = self.planner.plan(message, context)
        plan_seconds = perf_counter() - plan_started
        logger.info(
            "V2 PLAN channel=%s session=%s intent=%s code=%s query=%s "
            "color=%s size=%s quantity=%s requested_items=%s buying=%s suggested_cta=%s "
            "cta_index=%s send_images=%s time=%.3fs",
            channel, session_id, plan.intent.value, plan.reference_product_code,
            plan.search_query, plan.requested_color, plan.requested_size,
            plan.requested_quantity,
            [item.model_dump(mode="json") for item in plan.requested_items],
            plan.buying_intent,
            plan.suggested_cta_type.value if plan.suggested_cta_type else None,
            plan.suggested_cta_index, plan.send_images, plan_seconds,
        )

        execution_started = perf_counter()
        result = self.executor.execute(message, plan, context)
        self.order_flow.apply(plan, result, context)
        self._export_confirmed_order(result, context)
        self.cta.apply(plan, result, context)
        execution_seconds = perf_counter() - execution_started
        logger.info(
            "V2 EXECUTE session=%s status=%s products=%s media=%s "
            "sources=%s sales_stage=%s order=%s cta=%s time=%.3fs",
            session_id, result.status,
            [item.get("product_code") for item in result.products],
            [{"code": item.product_code, "color": item.color, "images": len(item.image_urls)} for item in result.media],
            len(result.sources), context.sales_stage.value,
            self._safe_order_log(result.facts.get("order_draft")),
            result.cta_type.value,
            execution_seconds,
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
        self.cta.record(context, result)
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
            cta_type=result.cta_type,
            cta_text=result.cta_text,
            provider=self.ai.provider_name,
            model=self.ai.model,
            timing={
                "planner": round(plan_seconds, 3),
                "executor": round(execution_seconds, 3),
                "presenter": round(presentation_seconds, 3),
                "total": round(total_seconds, 3),
            },
        )
