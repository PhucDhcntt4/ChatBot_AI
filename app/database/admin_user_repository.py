from typing import Any

from app.database.connection import database_connection


class AdminUserRepository:
    """PostgreSQL persistence for users allowed to access /admin."""

    _PUBLIC_COLUMNS = """
        id, username, display_name, role, is_active,
        session_version, last_login_at, created_at, updated_at
    """

    def validate_schema(self) -> None:
        with database_connection() as connection:
            connection.execute("SELECT id FROM admin_users LIMIT 0")

    def find_for_login(self, username: str) -> dict[str, Any] | None:
        normalized = str(username or "").strip()
        if not normalized:
            return None
        with database_connection() as connection:
            row = connection.execute(
                f"""
                SELECT {self._PUBLIC_COLUMNS}, password_hash
                FROM admin_users
                WHERE LOWER(username) = LOWER(%s)
                LIMIT 1
                """,
                (normalized,),
            ).fetchone()
        return dict(row) if row else None

    def find_active_by_id(self, user_id: int) -> dict[str, Any] | None:
        with database_connection() as connection:
            row = connection.execute(
                f"""
                SELECT {self._PUBLIC_COLUMNS}
                FROM admin_users
                WHERE id = %s AND is_active = TRUE
                LIMIT 1
                """,
                (int(user_id),),
            ).fetchone()
        return dict(row) if row else None

    def find_by_id(self, user_id: int) -> dict[str, Any] | None:
        with database_connection() as connection:
            row = connection.execute(
                f"""
                SELECT {self._PUBLIC_COLUMNS}
                FROM admin_users
                WHERE id = %s
                LIMIT 1
                """,
                (int(user_id),),
            ).fetchone()
        return dict(row) if row else None

    def list_users(self) -> list[dict[str, Any]]:
        with database_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT {self._PUBLIC_COLUMNS}
                FROM admin_users
                ORDER BY is_active DESC, LOWER(username), id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def active_admin_count(self) -> int:
        with database_connection() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM admin_users
                WHERE is_active = TRUE AND role = 'admin'
                """
            ).fetchone()
        return int(row["total"] if row else 0)

    def record_login(self, user_id: int) -> None:
        with database_connection() as connection:
            connection.execute(
                """
                UPDATE admin_users
                SET last_login_at = NOW(), updated_at = NOW()
                WHERE id = %s
                """,
                (int(user_id),),
            )

    def create_user(
        self,
        *,
        username: str,
        password_hash: str,
        display_name: str | None = None,
        role: str = "admin",
    ) -> dict[str, Any]:
        with database_connection() as connection:
            row = connection.execute(
                f"""
                INSERT INTO admin_users(
                    username, password_hash, display_name, role
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING {self._PUBLIC_COLUMNS}
                """,
                (
                    str(username).strip(),
                    password_hash,
                    str(display_name).strip() if display_name else None,
                    str(role or "admin").strip(),
                ),
            ).fetchone()
        if not row:
            raise ValueError("Tài khoản đã tồn tại.")
        return dict(row)

    def update_password(self, *, username: str, password_hash: str) -> bool:
        with database_connection() as connection:
            row = connection.execute(
                """
                UPDATE admin_users
                SET password_hash = %s,
                    session_version = session_version + 1,
                    updated_at = NOW()
                WHERE LOWER(username) = LOWER(%s)
                RETURNING id
                """,
                (password_hash, str(username).strip()),
            ).fetchone()
        return row is not None

    def update_password_by_id(self, *, user_id: int, password_hash: str) -> bool:
        with database_connection() as connection:
            row = connection.execute(
                """
                UPDATE admin_users
                SET password_hash = %s,
                    session_version = session_version + 1,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id
                """,
                (password_hash, int(user_id)),
            ).fetchone()
        return row is not None

    def update_user(
        self,
        *,
        user_id: int,
        display_name: str | None,
        role: str,
        is_active: bool,
    ) -> dict[str, Any] | None:
        with database_connection() as connection:
            row = connection.execute(
                f"""
                UPDATE admin_users
                SET display_name = %s,
                    role = %s,
                    is_active = %s,
                    session_version = CASE
                        WHEN role IS DISTINCT FROM %s
                          OR is_active IS DISTINCT FROM %s
                        THEN session_version + 1
                        ELSE session_version
                    END,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING {self._PUBLIC_COLUMNS}
                """,
                (
                    display_name,
                    role,
                    bool(is_active),
                    role,
                    bool(is_active),
                    int(user_id),
                ),
            ).fetchone()
        return dict(row) if row else None
