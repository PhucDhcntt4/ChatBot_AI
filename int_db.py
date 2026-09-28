"""Khởi tạo PostgreSQL cho Bot Conversation và tạo tài khoản quản trị.

Chạy:
    python int_db.py
    python int_db.py --username admin --display-name "Quản trị viên"

Script này chỉ kết nối PostgreSQL qua DATABASE_URL. Không kết nối Qdrant,
Redis, RAG Service hoặc Shopify.
"""

import argparse
from getpass import getpass
import sys

from app.database.admin_user_repository import AdminUserRepository
from app.database.connection import database_connection
from app.services.admin_auth_service import hash_password


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS conversation_sessions (
        id BIGSERIAL PRIMARY KEY,
        channel VARCHAR(30) NOT NULL,
        session_key VARCHAR(255) NOT NULL,
        external_user_id VARCHAR(255),
        customer_name VARCHAR(255),
        customer_phone VARCHAR(30),
        status VARCHAR(30) NOT NULL DEFAULT 'active',
        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_message_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        ended_at TIMESTAMPTZ,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        CONSTRAINT uq_conversation_session UNIQUE (channel, session_key),
        CONSTRAINT chk_conversation_session_status
            CHECK (status IN ('active', 'completed', 'cancelled'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_conversation_sessions_updated
    ON conversation_sessions(last_message_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_conversation_sessions_external_user
    ON conversation_sessions(channel, external_user_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS conversation_messages (
        id BIGSERIAL PRIMARY KEY,
        conversation_id BIGINT NOT NULL
            REFERENCES conversation_sessions(id) ON DELETE CASCADE,
        channel VARCHAR(30) NOT NULL,
        external_message_id VARCHAR(255),
        role VARCHAR(20) NOT NULL,
        message_type VARCHAR(30) NOT NULL DEFAULT 'text',
        content TEXT,
        media JSONB NOT NULL DEFAULT '[]'::jsonb,
        intent VARCHAR(100),
        product_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
        rag_sources JSONB NOT NULL DEFAULT '[]'::jsonb,
        ai_provider VARCHAR(30),
        ai_model VARCHAR(100),
        planner_ms INTEGER,
        executor_ms INTEGER,
        presenter_ms INTEGER,
        total_ms INTEGER,
        processing_status VARCHAR(30) NOT NULL DEFAULT 'completed',
        delivery_status VARCHAR(30) NOT NULL DEFAULT 'received',
        error_code VARCHAR(100),
        error_message TEXT,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT chk_conversation_message_role
            CHECK (role IN ('user', 'assistant', 'system')),
        CONSTRAINT chk_conversation_processing_status
            CHECK (processing_status IN ('pending', 'completed', 'failed')),
        CONSTRAINT chk_conversation_delivery_status
            CHECK (
                delivery_status IN (
                    'received', 'generated', 'sent', 'send_failed'
                )
            )
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_conversation_messages_session_time
    ON conversation_messages(conversation_id, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_conversation_messages_created
    ON conversation_messages(created_at DESC)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_conversation_external_message
    ON conversation_messages(channel, external_message_id)
    WHERE external_message_id IS NOT NULL
    """,
    """
    CREATE TABLE IF NOT EXISTS admin_users (
        id BIGSERIAL PRIMARY KEY,
        username VARCHAR(100) NOT NULL,
        password_hash TEXT NOT NULL,
        display_name VARCHAR(150),
        role VARCHAR(50) NOT NULL DEFAULT 'admin',
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        session_version INTEGER NOT NULL DEFAULT 1,
        last_login_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT chk_admin_users_username_not_blank
            CHECK (BTRIM(username) <> ''),
        CONSTRAINT chk_admin_users_password_hash_not_blank
            CHECK (BTRIM(password_hash) <> ''),
        CONSTRAINT chk_admin_users_role_not_blank
            CHECK (BTRIM(role) <> ''),
        CONSTRAINT chk_admin_users_session_version
            CHECK (session_version > 0)
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_admin_users_username_lower
    ON admin_users(LOWER(username))
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_admin_users_active
    ON admin_users(is_active, role)
    """,
)


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _create_schema() -> None:
    with database_connection() as connection:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)


def _read_password() -> str:
    password = getpass("Mật khẩu: ")
    confirmation = getpass("Nhập lại mật khẩu: ")
    if password != confirmation:
        raise ValueError("Hai lần nhập mật khẩu không giống nhau.")
    return password


def _create_or_update_user(args: argparse.Namespace) -> str:
    repository = AdminUserRepository()
    existing = repository.find_for_login(args.username)
    if existing and not args.update_password:
        return (
            f"Tài khoản {existing['username']} đã tồn tại; "
            "không thay đổi mật khẩu."
        )

    password_hash = hash_password(_read_password())
    if existing:
        repository.update_password(
            username=args.username,
            password_hash=password_hash,
        )
        return f"Đã cập nhật mật khẩu tài khoản {existing['username']}."

    user = repository.create_user(
        username=args.username,
        password_hash=password_hash,
        display_name=args.display_name,
        role=args.role,
    )
    return f"Đã tạo tài khoản {user['username']} với vai trò {user['role']}."


def main() -> None:
    _configure_console()
    parser = argparse.ArgumentParser(
        description=(
            "Tạo 3 bảng PostgreSQL của Bot Conversation và tạo tài khoản quản trị."
        )
    )
    parser.add_argument("--username", default="admin")
    parser.add_argument("--display-name", default="Quản trị viên")
    parser.add_argument(
        "--role",
        choices=("admin", "manager", "staff"),
        default="admin",
    )
    parser.add_argument(
        "--update-password",
        action="store_true",
        help="Đặt lại mật khẩu nếu tài khoản đã tồn tại.",
    )
    args = parser.parse_args()

    _create_schema()
    print("Đã kiểm tra/tạo 3 bảng PostgreSQL:")
    print("- conversation_sessions")
    print("- conversation_messages")
    print("- admin_users")
    print(_create_or_update_user(args))
    print("Hoàn tất. Script không kết nối Qdrant.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print(f"Khởi tạo database thất bại: {error}", file=sys.stderr)
        raise SystemExit(1) from None
