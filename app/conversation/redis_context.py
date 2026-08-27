import os
from typing import Any

from redis import Redis  # type: ignore

from app.config import HISTORY_LIMIT
from app.conversation.context import _context_summary
from app.conversation.models import ConversationContext, HistoryItem
from app.database.redis_connection import redis_client


class RedisConversationContextStore:
    """Lưu toàn bộ lịch sử và đơn nháp của một session trong Redis."""

    def __init__(self, client: Redis = redis_client) -> None:
        self.redis = client
        self.prefix = os.getenv(
            "REDIS_CONVERSATION_PREFIX",
            "donghai:conversation",
        ).strip().rstrip(":")
        self.ttl = int(
            os.getenv("REDIS_CONVERSATION_TTL_SECONDS", "604800")
        )
        if self.ttl <= 0:
            raise ValueError("REDIS_CONVERSATION_TTL_SECONDS phải lớn hơn 0.")

    def _key(self, channel: str, session_id: str) -> str:
        normalized_channel = channel.strip().casefold()
        normalized_session = session_id.strip()
        if not normalized_channel or not normalized_session:
            raise ValueError("Channel và session ID không được để trống.")
        if len(normalized_channel) > 50 or len(normalized_session) > 200:
            raise ValueError("Channel hoặc session ID vượt quá độ dài cho phép.")
        return f"{self.prefix}:{normalized_channel}:{normalized_session}"

    def get(self, session_id: str, channel: str) -> ConversationContext:
        key = self._key(channel, session_id)
        payload = self.redis.get(key)
        if payload:
            context = ConversationContext.model_validate_json(payload)
            # Mỗi lần khách tiếp tục trò chuyện, session được giữ thêm một TTL.
            self.redis.expire(key, self.ttl)
            return context

        return ConversationContext(
            session_id=session_id.strip(),
            channel=channel.strip().casefold(),
        )

    def save(self, context: ConversationContext) -> None:
        context.history = context.history[-HISTORY_LIMIT:]
        context.cta_history = context.cta_history[-5:]
        self.redis.set(
            self._key(context.channel, context.session_id),
            context.model_dump_json(),
            ex=self.ttl,
        )

    def append(
        self,
        context: ConversationContext,
        role: str,
        text: str,
    ) -> None:
        context.history.append(HistoryItem(role=role, text=text))
        context.history = context.history[-HISTORY_LIMIT:]

    def reset(self, session_id: str, channel: str) -> None:
        self.redis.delete(self._key(channel, session_id))

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        for key in self.redis.scan_iter(match=f"{self.prefix}:*", count=200):
            payload = self.redis.get(key)
            if not payload:
                continue
            try:
                context = ConversationContext.model_validate_json(payload)
            except ValueError:
                continue
            ttl = int(self.redis.ttl(key))
            sessions.append(
                _context_summary(context, ttl_seconds=ttl if ttl >= 0 else None)
            )
        return sessions

    def inspect(self, session_id: str, channel: str) -> dict[str, Any] | None:
        key = self._key(channel, session_id)
        payload = self.redis.get(key)
        if not payload:
            return None
        context = ConversationContext.model_validate_json(payload)
        ttl = int(self.redis.ttl(key))
        return {
            **_context_summary(context, ttl_seconds=ttl if ttl >= 0 else None),
            "context": context.model_dump(mode="json"),
        }
