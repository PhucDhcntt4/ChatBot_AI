import json
import logging
from datetime import datetime, timedelta, timezone

from redis.exceptions import RedisError  # type: ignore

from app.config import (
    HUMAN_MODE_ENABLED,
    HUMAN_MODE_TTL_SECONDS,
)
from app.database.redis_connection import redis_client


logger = logging.getLogger("uvicorn.error")


class HumanModeService:
    KEY_PREFIX = "donghai:human_mode"

    @classmethod
    def _key(cls, channel: str, user_id: str) -> str:
        safe_channel = channel.strip().casefold()
        safe_user_id = user_id.strip()

        if not safe_channel or not safe_user_id:
            raise ValueError("channel và user_id không được để trống")

        return f"{cls.KEY_PREFIX}:{safe_channel}:{safe_user_id}"

    def is_enabled(
        self,
        channel: str,
        user_id: str,
    ) -> bool:
        if not HUMAN_MODE_ENABLED:
            return False

        try:
            return redis_client.exists(
                self._key(channel, user_id)
            ) == 1
        except RedisError:
            return False

    def enable(
        self,
        channel: str,
        user_id: str,
        reason: str ="customer_requested",
        activated_by: str = "bot",
        ttl_seconds: int | None = None,
    ) -> None:
        effective_ttl = (
            HUMAN_MODE_TTL_SECONDS
            if ttl_seconds is None
            else int(ttl_seconds)
        )
        if effective_ttl < 60 or effective_ttl > 604800:
            raise ValueError("Thời gian tạm dừng bot phải từ 1 phút đến 7 ngày")
        activated_at = datetime.now(timezone.utc)
        payload = {
            "enabled": True,
            "channel": channel,
            "user_id": user_id,
            "reason": reason,
            "activated_by": activated_by,
            "activated_at": activated_at.isoformat(),
            "expires_at": (
                activated_at + timedelta(seconds=effective_ttl)
            ).isoformat(),
            "ttl_seconds": effective_ttl,
        }

        if not HUMAN_MODE_ENABLED:
            return
        try:
            redis_client.setex(
                self._key(channel, user_id),
                effective_ttl,
                json.dumps(payload, ensure_ascii=False),
            )
        except RedisError as error:
            raise RuntimeError("Không thể bật human mode trong Redis") from error
        logger.info(
            "HUMAN MODE ENABLED channel=%s session=%s reason=%s by=%s ttl=%s",
            channel,
            user_id,
            reason,
            activated_by,
            effective_ttl,
        )

    def disable(
        self,
        channel: str,
        user_id: str
    ) -> None:
        try:
            redis_client.delete(self._key(channel, user_id))
        except RedisError as error:
            raise RuntimeError("Không thể tắt human mode trong Redis") from error
        logger.info(
            "HUMAN MODE DISABLED channel=%s session=%s",
            channel,
            user_id,
        )

    def details(
        self,
        channel: str,
        user_id: str,
    ) -> dict | None:
        try:
            key = self._key(channel, user_id)
            value = redis_client.get(key)
            remaining_seconds = redis_client.ttl(key)
        except RedisError:
            return None

        if not value:
            return None

        try:
            details = json.loads(value)
            details["remaining_seconds"] = max(0, remaining_seconds)
            return details
        except (TypeError, json.JSONDecodeError):
            return None
