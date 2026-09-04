import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from app.config import (
    ADMIN_AUTH_ENABLED,
    ADMIN_COOKIE_SECURE,
    ADMIN_REMEMBER_TTL_SECONDS,
    ADMIN_SESSION_SECRET,
    ADMIN_SESSION_TTL_SECONDS,
)
from app.database.admin_user_repository import AdminUserRepository


class AdminAuthConfigurationError(RuntimeError):
    pass


PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 600_000
_DUMMY_SALT = b"donghai-admin-dummy"


def _base64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(
    password: str,
    *,
    iterations: int = PASSWORD_ITERATIONS,
    salt: bytes | None = None,
) -> str:
    raw_password = str(password or "")
    if len(raw_password) < 3:
        raise ValueError("Mật khẩu phải có ít nhất 3 ký tự.")
    rounds = int(iterations)
    if rounds < 100_000:
        raise ValueError("Số vòng băm mật khẩu không an toàn.")
    password_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        raw_password.encode("utf-8"),
        password_salt,
        rounds,
    )
    return "$".join((
        PASSWORD_ALGORITHM,
        str(rounds),
        _base64_encode(password_salt),
        _base64_encode(digest),
    ))


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, raw_rounds, raw_salt, raw_digest = str(encoded).split("$", 3)
        rounds = int(raw_rounds)
        if algorithm != PASSWORD_ALGORITHM or not 100_000 <= rounds <= 2_000_000:
            return False
        salt = _base64_decode(raw_salt)
        expected = _base64_decode(raw_digest)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            str(password or "").encode("utf-8"),
            salt,
            rounds,
        )
        return hmac.compare_digest(actual, expected)
    except (binascii.Error, UnicodeError, ValueError, TypeError):
        return False


_DUMMY_PASSWORD_HASH = hash_password(
    "invalid-password-placeholder",
    salt=_DUMMY_SALT,
)


class AdminAuthService:
    """Database-backed admin login with stateless signed browser sessions."""

    COOKIE_NAME = "donghai_admin_session"

    def __init__(
        self,
        *,
        enabled: bool = ADMIN_AUTH_ENABLED,
        session_secret: str = ADMIN_SESSION_SECRET,
        session_ttl: int = ADMIN_SESSION_TTL_SECONDS,
        remember_ttl: int = ADMIN_REMEMBER_TTL_SECONDS,
        cookie_secure: bool = ADMIN_COOKIE_SECURE,
        repository: AdminUserRepository | Any | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.session_secret = str(session_secret or "")
        self.session_ttl = max(300, int(session_ttl))
        self.remember_ttl = max(self.session_ttl, int(remember_ttl))
        self.cookie_secure = bool(cookie_secure)
        self.repository = repository or AdminUserRepository()

    def validate(self) -> None:
        if not self.enabled:
            return
        if len(self.session_secret) < 32:
            raise AdminAuthConfigurationError(
                "ADMIN_SESSION_SECRET phải có ít nhất 32 ký tự."
            )
        try:
            self.repository.validate_schema()
        except Exception as error:
            raise AdminAuthConfigurationError(
                "Không thể đọc bảng admin_users. "
                "Hãy chạy db_postgre/005_admin_users.sql."
            ) from error

    @staticmethod
    def _public_user(user: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(user["id"]),
            "username": str(user["username"]),
            "display_name": user.get("display_name"),
            "role": str(user.get("role") or "admin"),
            "session_version": int(user.get("session_version") or 1),
        }

    def authenticate(self, username: str, password: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        user = self.repository.find_for_login(username)
        password_hash = user.get("password_hash") if user else _DUMMY_PASSWORD_HASH
        password_matches = verify_password(password, password_hash)
        if not user or not password_matches or not bool(user.get("is_active")):
            return None
        self.repository.record_login(int(user["id"]))
        return self._public_user(user)

    def create_session(
        self,
        user: dict[str, Any],
        *,
        remember: bool = False,
    ) -> tuple[str, int]:
        if not self.enabled or len(self.session_secret) < 32:
            raise AdminAuthConfigurationError("Đăng nhập quản trị chưa sẵn sàng.")
        now = int(time.time())
        ttl = self.remember_ttl if remember else self.session_ttl
        payload = {
            "sub": int(user["id"]),
            "usr": str(user["username"]),
            "role": str(user.get("role") or "admin"),
            "sv": int(user.get("session_version") or 1),
            "iat": now,
            "exp": now + ttl,
            "v": 1,
        }
        encoded = _base64_encode(
            json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        signature = hmac.new(
            self.session_secret.encode("utf-8"),
            encoded.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return f"{encoded}.{_base64_encode(signature)}", ttl

    def _decode_session(self, token: str | None) -> dict[str, Any] | None:
        if not self.enabled or not token or not self.session_secret:
            return None
        try:
            encoded, supplied_signature = token.split(".", 1)
            expected_signature = hmac.new(
                self.session_secret.encode("utf-8"),
                encoded.encode("ascii"),
                hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(
                _base64_decode(supplied_signature),
                expected_signature,
            ):
                return None
            payload = json.loads(_base64_decode(encoded).decode("utf-8"))
            if int(payload.get("exp") or 0) <= int(time.time()):
                return None
            if int(payload.get("v") or 0) != 1:
                return None
            if int(payload.get("sub") or 0) <= 0:
                return None
            return payload
        except (
            binascii.Error,
            UnicodeError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
        ):
            return None

    def read_session(self, token: str | None) -> dict[str, Any] | None:
        payload = self._decode_session(token)
        if payload is None:
            return None
        try:
            user = self.repository.find_active_by_id(int(payload["sub"]))
        except Exception:
            return None
        if not user:
            return None
        current = self._public_user(user)
        if (
            current["username"] != payload.get("usr")
            or current["role"] != payload.get("role")
            or current["session_version"] != int(payload.get("sv") or 0)
        ):
            return None
        return current

    def is_authenticated(self, token: str | None) -> bool:
        return self.read_session(token) is not None


admin_auth_service = AdminAuthService()
