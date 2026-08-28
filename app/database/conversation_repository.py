import json
from typing import Any

from app.database.connection import database_connection


class ConversationRepository:
    """PostgreSQL persistence for channel-independent chat history."""

    @staticmethod
    def _json(value: Any, default: Any) -> str:
        return json.dumps(
            default if value is None else value,
            ensure_ascii=False,
        )

    def ensure_session(
        self,
        *,
        channel: str,
        session_key: str,
        external_user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        normalized_channel = str(channel or "").strip().lower()
        normalized_session = str(session_key or "").strip()
        if not normalized_channel:
            raise ValueError("Channel không được để trống")
        if not normalized_session:
            raise ValueError("Session key không được để trống")

        with database_connection() as connection:
            row = connection.execute(
                """
                INSERT INTO conversation_sessions(
                    channel,
                    session_key,
                    external_user_id,
                    metadata
                )
                VALUES (%s, %s, %s, %s::jsonb)
                ON CONFLICT (channel, session_key)
                DO UPDATE SET
                    external_user_id = COALESCE(
                        EXCLUDED.external_user_id,
                        conversation_sessions.external_user_id
                    ),
                    metadata = conversation_sessions.metadata
                        || EXCLUDED.metadata,
                    last_message_at = NOW()
                RETURNING id
                """,
                (
                    normalized_channel,
                    normalized_session,
                    str(external_user_id) if external_user_id is not None else None,
                    self._json(metadata, {}),
                ),
            ).fetchone()

        if not row:
            raise RuntimeError("Không thể tạo hoặc lấy phiên hội thoại")
        return int(row["id"])

    def save_message(
        self,
        *,
        conversation_id: int,
        channel: str,
        role: str,
        content: str | None,
        message_type: str = "text",
        external_message_id: str | None = None,
        media: list[dict[str, Any]] | None = None,
        intent: str | None = None,
        product_codes: list[str] | None = None,
        rag_sources: list[dict[str, Any]] | None = None,
        ai_provider: str | None = None,
        ai_model: str | None = None,
        planner_ms: int | None = None,
        executor_ms: int | None = None,
        presenter_ms: int | None = None,
        total_ms: int | None = None,
        processing_status: str = "completed",
        delivery_status: str = "received",
        metadata: dict[str, Any] | None = None,
    ) -> int | None:
        normalized_role = str(role or "").strip().lower()
        if normalized_role not in {"user", "assistant", "system"}:
            raise ValueError("Role hội thoại không hợp lệ")

        external_id = (
            str(external_message_id).strip()
            if external_message_id is not None
            else None
        ) or None
        with database_connection() as connection:
            row = connection.execute(
                """
                INSERT INTO conversation_messages(
                    conversation_id,
                    channel,
                    external_message_id,
                    role,
                    message_type,
                    content,
                    media,
                    intent,
                    product_codes,
                    rag_sources,
                    ai_provider,
                    ai_model,
                    planner_ms,
                    executor_ms,
                    presenter_ms,
                    total_ms,
                    processing_status,
                    delivery_status,
                    metadata
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s::jsonb, %s, %s::jsonb, %s::jsonb,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s::jsonb
                )
                ON CONFLICT (channel, external_message_id)
                WHERE external_message_id IS NOT NULL
                DO NOTHING
                RETURNING id
                """,
                (
                    int(conversation_id),
                    str(channel).strip().lower(),
                    external_id,
                    normalized_role,
                    str(message_type or "text").strip().lower(),
                    content,
                    self._json(media, []),
                    intent,
                    self._json(product_codes, []),
                    self._json(rag_sources, []),
                    ai_provider,
                    ai_model,
                    planner_ms,
                    executor_ms,
                    presenter_ms,
                    total_ms,
                    processing_status,
                    delivery_status,
                    self._json(metadata, {}),
                ),
            ).fetchone()

        # None means the channel delivered a duplicate external message.
        return int(row["id"]) if row else None

    def update_delivery_status(
        self,
        *,
        message_id: int,
        delivery_status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        with database_connection() as connection:
            cursor = connection.execute(
                """
                UPDATE conversation_messages
                SET delivery_status = %s,
                    error_code = %s,
                    error_message = %s
                WHERE id = %s
                """,
                (
                    delivery_status,
                    error_code,
                    error_message,
                    int(message_id),
                ),
            )
        return bool(cursor.rowcount)

    def list_messages(
        self,
        *,
        channel: str,
        session_key: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 500)
        with database_connection() as connection:
            rows = connection.execute(
                """
                SELECT cm.*
                FROM conversation_messages cm
                JOIN conversation_sessions cs
                  ON cs.id = cm.conversation_id
                WHERE cs.channel = %s
                  AND cs.session_key = %s
                ORDER BY cm.created_at ASC, cm.id ASC
                LIMIT %s
                """,
                (
                    str(channel).strip().lower(),
                    str(session_key).strip(),
                    safe_limit,
                ),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_sessions(self, *, limit: int = 5000) -> list[dict[str, Any]]:
        """Danh sách hội thoại bền vững để trang quản trị theo dõi."""
        safe_limit = min(max(int(limit), 1), 10000)
        with database_connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    cs.channel,
                    cs.session_key AS session_id,
                    cs.external_user_id,
                    cs.customer_name,
                    cs.customer_phone,
                    cs.status,
                    cs.started_at,
                    cs.last_message_at,
                    cs.metadata,
                    COALESCE(message_stats.message_count, 0) AS message_count,
                    COALESCE(last_message.content, '') AS last_message,
                    latest_product.product_codes AS latest_product_codes
                FROM conversation_sessions cs
                LEFT JOIN LATERAL (
                    SELECT COUNT(*)::integer AS message_count
                    FROM conversation_messages cm
                    WHERE cm.conversation_id = cs.id
                ) message_stats ON TRUE
                LEFT JOIN LATERAL (
                    SELECT cm.content
                    FROM conversation_messages cm
                    WHERE cm.conversation_id = cs.id
                    ORDER BY cm.created_at DESC, cm.id DESC
                    LIMIT 1
                ) last_message ON TRUE
                LEFT JOIN LATERAL (
                    SELECT cm.product_codes
                    FROM conversation_messages cm
                    WHERE cm.conversation_id = cs.id
                      AND jsonb_array_length(cm.product_codes) > 0
                    ORDER BY cm.created_at DESC, cm.id DESC
                    LIMIT 1
                ) latest_product ON TRUE
                ORDER BY cs.last_message_at DESC, cs.id DESC
                LIMIT %s
                """,
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_session(
        self,
        *,
        channel: str,
        session_key: str,
    ) -> dict[str, Any] | None:
        with database_connection() as connection:
            row = connection.execute(
                """
                SELECT
                    cs.channel,
                    cs.session_key AS session_id,
                    cs.external_user_id,
                    cs.customer_name,
                    cs.customer_phone,
                    cs.status,
                    cs.started_at,
                    cs.last_message_at,
                    cs.metadata,
                    COALESCE(message_stats.message_count, 0) AS message_count,
                    COALESCE(last_message.content, '') AS last_message,
                    latest_product.product_codes AS latest_product_codes
                FROM conversation_sessions cs
                LEFT JOIN LATERAL (
                    SELECT COUNT(*)::integer AS message_count
                    FROM conversation_messages cm
                    WHERE cm.conversation_id = cs.id
                ) message_stats ON TRUE
                LEFT JOIN LATERAL (
                    SELECT cm.content
                    FROM conversation_messages cm
                    WHERE cm.conversation_id = cs.id
                    ORDER BY cm.created_at DESC, cm.id DESC
                    LIMIT 1
                ) last_message ON TRUE
                LEFT JOIN LATERAL (
                    SELECT cm.product_codes
                    FROM conversation_messages cm
                    WHERE cm.conversation_id = cs.id
                      AND jsonb_array_length(cm.product_codes) > 0
                    ORDER BY cm.created_at DESC, cm.id DESC
                    LIMIT 1
                ) latest_product ON TRUE
                WHERE cs.channel = %s AND cs.session_key = %s
                """,
                (
                    str(channel).strip().lower(),
                    str(session_key).strip(),
                ),
            ).fetchone()
        return dict(row) if row else None

    def update_session_snapshot(
        self,
        *,
        channel: str,
        session_key: str,
        customer_name: str | None = None,
        customer_phone: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Giữ thông tin tóm tắt trước khi cache Redis được giải phóng."""
        with database_connection() as connection:
            cursor = connection.execute(
                """
                UPDATE conversation_sessions
                SET customer_name = COALESCE(%s, customer_name),
                    customer_phone = COALESCE(%s, customer_phone),
                    metadata = metadata || %s::jsonb
                WHERE channel = %s AND session_key = %s
                """,
                (
                    customer_name,
                    customer_phone,
                    self._json(metadata, {}),
                    str(channel).strip().lower(),
                    str(session_key).strip(),
                ),
            )
        return bool(cursor.rowcount)
