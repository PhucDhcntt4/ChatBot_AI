import os
from threading import RLock
from typing import Any, Protocol

from app.config import HISTORY_LIMIT
from app.conversation.models import ConversationContext, HistoryItem


class ConversationContextStoreProtocol(Protocol):
    def get(self, session_id: str, channel: str) -> ConversationContext:
        ...

    def save(self, context: ConversationContext) -> None:
        ...

    def append(
        self,
        context: ConversationContext,
        role: str,
        text: str,
    ) -> None:
        ...

    def reset(self, session_id: str, channel: str) -> None:
        ...

    def list_sessions(self) -> list[dict[str, Any]]:
        ...

    def inspect(self, session_id: str, channel: str) -> dict[str, Any] | None:
        ...


class ConversationContextStore:
    """Kho hội thoại trong RAM, chủ yếu dùng cho unit test."""

    def __init__(self) -> None:
        self._items: dict[str, ConversationContext] = {}
        self._lock = RLock()

    @staticmethod
    def _key(channel: str, session_id: str) -> str:
        return f"{channel.strip().casefold()}:{session_id.strip()}"

    def get(self, session_id: str, channel: str) -> ConversationContext:
        key = self._key(channel, session_id)
        with self._lock:
            context = self._items.get(key)
            if context is None:
                context = ConversationContext(
                    session_id=session_id,
                    channel=channel,
                )
                self._items[key] = context
            return context.model_copy(deep=True)

    def save(self, context: ConversationContext) -> None:
        context.history = context.history[-HISTORY_LIMIT:]
        context.cta_history = context.cta_history[-5:]
        with self._lock:
            self._items[self._key(context.channel, context.session_id)] = (
                context.model_copy(deep=True)
            )

    def append(self, context: ConversationContext, role: str, text: str) -> None:
        context.history.append(HistoryItem(role=role, text=text))
        context.history = context.history[-HISTORY_LIMIT:]

    def reset(self, session_id: str, channel: str) -> None:
        with self._lock:
            self._items.pop(self._key(channel, session_id), None)

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            contexts = [item.model_copy(deep=True) for item in self._items.values()]
        return [_context_summary(context, ttl_seconds=None) for context in contexts]

    def inspect(self, session_id: str, channel: str) -> dict[str, Any] | None:
        with self._lock:
            context = self._items.get(self._key(channel, session_id))
            if context is None:
                return None
            copied = context.model_copy(deep=True)
        return {
            **_context_summary(copied, ttl_seconds=None),
            "context": copied.model_dump(mode="json"),
        }


def _context_summary(
    context: ConversationContext,
    ttl_seconds: int | None,
) -> dict[str, Any]:
    last_message = context.history[-1].text if context.history else ""
    return {
        "channel": context.channel,
        "session_id": context.session_id,
        "message_count": len(context.history),
        "sales_stage": context.sales_stage.value,
        "latest_product_code": context.latest_product_code,
        "customer_name": context.draft_customer_name,
        "customer_phone": context.draft_customer_phone,
        "last_message": last_message,
        "ttl_seconds": ttl_seconds,
    }


def create_conversation_context_store() -> ConversationContextStoreProtocol:
    enabled = os.getenv(
        "REDIS_CONVERSATION_ENABLED",
        "false",
    ).strip().casefold() in {"1", "true", "yes", "on"}

    if not enabled:
        return ConversationContextStore()

    # Import trễ để RAM store và unit test không phụ thuộc Redis.
    from app.conversation.redis_context import RedisConversationContextStore

    return RedisConversationContextStore()


conversation_context_store = create_conversation_context_store()
