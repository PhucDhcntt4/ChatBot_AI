from threading import RLock

from app.config import HISTORY_LIMIT
from app.conversation.models import ConversationContext, HistoryItem


class ConversationContextStore:
    """RAM store dùng khi phát triển; có thể thay bằng Redis ở production."""

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


conversation_context_store = ConversationContextStore()
