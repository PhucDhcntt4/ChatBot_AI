import logging
from typing import Any

from app.database.conversation_repository import ConversationRepository


logger = logging.getLogger("uvicorn.error")


class ConversationHistoryService:
    """Best-effort persistent history shared by every chat channel.

    History failures are logged and intentionally do not interrupt customer
    conversations. Redis remains the live conversation state; PostgreSQL is
    the durable audit and review store.
    """

    def __init__(
        self,
        repository: ConversationRepository | None = None,
    ) -> None:
        self.repository = repository or ConversationRepository()

    @staticmethod
    def _milliseconds(value: Any) -> int | None:
        try:
            return max(0, round(float(value) * 1000))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _value(value: Any) -> Any:
        return getattr(value, "value", value)

    @classmethod
    def _media_payload(cls, media: Any) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in media or []:
            if hasattr(item, "model_dump"):
                normalized.append(item.model_dump(mode="json"))
            elif isinstance(item, dict):
                normalized.append(dict(item))
        return normalized

    def save_user_message(
        self,
        *,
        session_id: str,
        channel: str,
        content: str,
        external_message_id: str | None = None,
        external_user_id: str | None = None,
        message_type: str = "text",
        media: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int | None:
        try:
            conversation_id = self.repository.ensure_session(
                channel=channel,
                session_key=str(session_id),
                external_user_id=external_user_id,
            )
            message_id = self.repository.save_message(
                conversation_id=conversation_id,
                channel=channel,
                external_message_id=external_message_id,
                role="user",
                content=content,
                message_type=message_type,
                media=media,
                processing_status="completed",
                delivery_status="received",
                metadata=metadata,
            )
            logger.info(
                "CONVERSATION HISTORY SAVED role=user channel=%s "
                "session=%s stored=%s",
                channel,
                session_id,
                message_id is not None,
            )
            return message_id
        except Exception:
            logger.exception(
                "CONVERSATION HISTORY SAVE FAILED role=user channel=%s "
                "session=%s",
                channel,
                session_id,
            )
            return None

    def save_assistant_message(
        self,
        *,
        session_id: str,
        channel: str,
        response: Any,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int | None:
        try:
            conversation_id = self.repository.ensure_session(
                channel=channel,
                session_key=str(session_id),
            )
            products = list(getattr(response, "products", None) or [])
            product_codes = list(dict.fromkeys(
                str(product.get("product_code") or "").strip().upper()
                for product in products
                if isinstance(product, dict) and product.get("product_code")
            ))
            timing = dict(getattr(response, "timing", None) or {})
            message_id = self.repository.save_message(
                conversation_id=conversation_id,
                channel=channel,
                role="assistant",
                content=(
                    content
                    if content is not None
                    else str(getattr(response, "message", "") or "")
                ),
                message_type=(
                    "multimedia"
                    if getattr(response, "media", None)
                    else "text"
                ),
                media=self._media_payload(getattr(response, "media", None)),
                intent=self._value(getattr(response, "intent", None)),
                product_codes=product_codes,
                rag_sources=list(getattr(response, "sources", None) or []),
                ai_provider=getattr(response, "provider", None),
                ai_model=getattr(response, "model", None),
                planner_ms=self._milliseconds(timing.get("planner")),
                executor_ms=self._milliseconds(timing.get("executor")),
                presenter_ms=self._milliseconds(timing.get("presenter")),
                total_ms=self._milliseconds(timing.get("total")),
                processing_status="completed",
                delivery_status="generated",
                metadata={
                    "response_status": getattr(response, "status", None),
                    "cta_type": self._value(
                        getattr(response, "cta_type", None)
                    ),
                    **(metadata or {}),
                },
            )
            logger.info(
                "CONVERSATION HISTORY SAVED role=assistant channel=%s "
                "session=%s stored=%s",
                channel,
                session_id,
                message_id is not None,
            )
            return message_id
        except Exception:
            logger.exception(
                "CONVERSATION HISTORY SAVE FAILED role=assistant "
                "channel=%s session=%s",
                channel,
                session_id,
            )
            return None

    def mark_sent(self, message_id: int | None) -> bool:
        if message_id is None:
            return False
        try:
            return self.repository.update_delivery_status(
                message_id=message_id,
                delivery_status="sent",
            )
        except Exception:
            logger.exception(
                "CONVERSATION DELIVERY UPDATE FAILED message_id=%s "
                "status=sent",
                message_id,
            )
            return False

    def mark_send_failed(
        self,
        message_id: int | None,
        error: Exception | str,
        *,
        error_code: str | None = None,
    ) -> bool:
        if message_id is None:
            return False
        try:
            return self.repository.update_delivery_status(
                message_id=message_id,
                delivery_status="send_failed",
                error_code=error_code,
                error_message=str(error)[:2000],
            )
        except Exception:
            logger.exception(
                "CONVERSATION DELIVERY UPDATE FAILED message_id=%s "
                "status=send_failed",
                message_id,
            )
            return False

    def list_messages(
        self,
        *,
        channel: str,
        session_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        try:
            return self.repository.list_messages(
                channel=channel,
                session_key=str(session_id),
                limit=limit,
            )
        except Exception:
            logger.exception(
                "CONVERSATION HISTORY READ FAILED channel=%s session=%s",
                channel,
                session_id,
            )
            return []

    @staticmethod
    def _session_summary(row: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(row.get("metadata") or {})
        product_codes = list(row.get("latest_product_codes") or [])
        status = str(row.get("status") or "active")
        return {
            **row,
            "session_id": str(row.get("session_id") or ""),
            "sales_stage": metadata.get("sales_stage") or (
                status if status != "active" else "archived"
            ),
            "latest_product_code": (
                metadata.get("latest_product_code")
                or (str(product_codes[0]) if product_codes else None)
            ),
            "customer_name": (
                row.get("customer_name") or metadata.get("customer_name")
            ),
            "customer_phone": (
                row.get("customer_phone") or metadata.get("customer_phone")
            ),
            "ttl_seconds": None,
            "cache_active": False,
        }

    def list_sessions(self, *, limit: int = 5000) -> list[dict[str, Any]]:
        try:
            return [
                self._session_summary(row)
                for row in self.repository.list_sessions(limit=limit)
            ]
        except Exception:
            logger.exception("CONVERSATION SESSION LIST FAILED")
            return []

    def get_session(
        self,
        *,
        channel: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        try:
            row = self.repository.get_session(
                channel=channel,
                session_key=str(session_id),
            )
            return self._session_summary(row) if row else None
        except Exception:
            logger.exception(
                "CONVERSATION SESSION READ FAILED channel=%s session=%s",
                channel,
                session_id,
            )
            return None

    def update_session_snapshot(
        self,
        *,
        channel: str,
        session_id: str,
        snapshot: dict[str, Any],
    ) -> bool:
        try:
            return self.repository.update_session_snapshot(
                channel=channel,
                session_key=str(session_id),
                customer_name=snapshot.get("customer_name"),
                customer_phone=snapshot.get("customer_phone"),
                metadata={
                    "sales_stage": snapshot.get("sales_stage"),
                    "latest_product_code": snapshot.get(
                        "latest_product_code"
                    ),
                    "customer_name": snapshot.get("customer_name"),
                    "customer_phone": snapshot.get("customer_phone"),
                },
            )
        except Exception:
            logger.exception(
                "CONVERSATION SNAPSHOT UPDATE FAILED channel=%s session=%s",
                channel,
                session_id,
            )
            return False
