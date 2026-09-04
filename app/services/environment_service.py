import json
import os
import re
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any


ASSIGNMENT_PATTERN = re.compile(
    r"^(?P<prefix>\s*(?:export\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*)(?P<raw>.*)$"
)
SENSITIVE_MARKERS = (
    "API_KEY",
    "PASSWORD",
    "SECRET",
    "TOKEN",
    "PRIVATE_KEY",
    "ACCESS_KEY",
)
SENSITIVE_EXACT_NAMES = {
    "DATABASE_URL",
    "REDIS_URL",
}


class EnvironmentFileError(ValueError):
    pass


class EnvironmentFileService:
    """Read and atomically update existing variables in a dotenv file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = Lock()

    @staticmethod
    def _is_sensitive(name: str) -> bool:
        upper_name = name.upper()
        return (
            upper_name in SENSITIVE_EXACT_NAMES
            or any(marker in upper_name for marker in SENSITIVE_MARKERS)
        )

    @staticmethod
    def _split_inline_comment(raw: str) -> tuple[str, str]:
        quote: str | None = None
        escaped = False
        for index, character in enumerate(raw):
            if escaped:
                escaped = False
                continue
            if character == "\\" and quote == '"':
                escaped = True
                continue
            if character in {'"', "'"}:
                if quote == character:
                    quote = None
                elif quote is None:
                    quote = character
                continue
            if (
                character == "#"
                and quote is None
                and (index == 0 or raw[index - 1].isspace())
            ):
                return raw[:index].rstrip(), raw[index + 1 :].strip()
        return raw.rstrip(), ""

    @staticmethod
    def _display_value(raw: str) -> str:
        value = raw.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            try:
                decoded = json.loads(value)
                return decoded if isinstance(decoded, str) else value
            except json.JSONDecodeError:
                return value[1:-1]
        if len(value) >= 2 and value[0] == value[-1] == "'":
            return value[1:-1]
        return value

    @staticmethod
    def _encoded_value(value: str) -> str:
        if not value:
            return ""
        if value != value.strip() or any(
            character in value for character in ("#", "\n", "\r", '"')
        ):
            return json.dumps(value, ensure_ascii=False)
        return value

    @staticmethod
    def _value_kind(value: str, sensitive: bool) -> str:
        if sensitive:
            return "secret"
        if value.casefold() in {"true", "false"}:
            return "boolean"
        if re.fullmatch(r"-?(?:\d+|\d+\.\d+)", value):
            return "number"
        return "text"

    @staticmethod
    def _enabled(value: str) -> bool:
        return value.strip().casefold() in {"1", "true", "yes", "on"}

    @classmethod
    def _validate_effective_values(cls, values: dict[str, str]) -> None:
        log_level = values.get("LOG_LEVEL", "INFO").strip().upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise EnvironmentFileError("LOG_LEVEL không hợp lệ.")

        ai_provider = values.get("AI_PROVIDER", "gemini").strip().casefold()
        fallback = values.get("AI_FALLBACK_PROVIDER", "").strip().casefold()
        if ai_provider not in {"gemini", "openai"}:
            raise EnvironmentFileError("AI_PROVIDER chỉ nhận gemini hoặc openai.")
        if fallback and fallback not in {"gemini", "openai"}:
            raise EnvironmentFileError(
                "AI_FALLBACK_PROVIDER chỉ nhận gemini, openai hoặc để trống."
            )
        if fallback == ai_provider:
            raise EnvironmentFileError(
                "AI_FALLBACK_PROVIDER phải khác AI_PROVIDER."
            )

        channels = {
            item.strip().casefold()
            for item in values.get("CHANNEL_PROVIDER", "web").split(",")
            if item.strip()
        }
        unknown_channels = channels - {"web", "telegram", "facebook"}
        if not channels or unknown_channels:
            raise EnvironmentFileError(
                "CHANNEL_PROVIDER chỉ hỗ trợ web, telegram và facebook."
            )

        if cls._enabled(values.get("ADMIN_AUTH_ENABLED", "false")):
            if len(values.get("ADMIN_SESSION_SECRET", "")) < 32:
                raise EnvironmentFileError(
                    "ADMIN_SESSION_SECRET phải có ít nhất 32 ký tự khi bật đăng nhập."
                )

        try:
            human_ttl = int(values.get("HUMAN_MODE_TTL_SECONDS", "86400"))
        except ValueError as error:
            raise EnvironmentFileError(
                "HUMAN_MODE_TTL_SECONDS phải là số nguyên."
            ) from error
        if not 60 <= human_ttl <= 604800:
            raise EnvironmentFileError(
                "HUMAN_MODE_TTL_SECONDS phải từ 60 đến 604800 giây."
            )

    def _read(self) -> tuple[str, list[str]]:
        if not self.path.is_file():
            raise EnvironmentFileError(f"Không tìm thấy file cấu hình: {self.path}")
        content = self.path.read_text(encoding="utf-8-sig")
        newline = "\r\n" if "\r\n" in content else "\n"
        return newline, content.splitlines()

    def read_public(self) -> dict[str, Any]:
        _, lines = self._read()
        sections: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        pending_comments: list[str] = []
        after_blank = True
        seen_names: set[str] = set()

        def ensure_section(title: str = "Cấu hình chung") -> dict[str, Any]:
            nonlocal current
            if current is None:
                current = {"title": title, "notes": [], "variables": []}
                sections.append(current)
            return current

        def finish_block() -> None:
            nonlocal current, pending_comments, after_blank
            if pending_comments and current is not None:
                current["notes"].extend(pending_comments)
            pending_comments = []
            current = None
            after_blank = True

        for line_number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                finish_block()
                continue
            if stripped.startswith("#"):
                comment = stripped[1:].strip()
                if after_blank and current is None and comment:
                    current = {
                        "title": comment,
                        "notes": [],
                        "variables": [],
                    }
                    sections.append(current)
                    after_blank = False
                elif comment:
                    pending_comments.append(comment)
                continue

            match = ASSIGNMENT_PATTERN.match(line)
            if not match:
                # Do not echo malformed content because it may contain a secret.
                ensure_section()["notes"].append(
                    f"Dòng {line_number} chưa đúng định dạng KEY=VALUE."
                )
                after_blank = False
                continue

            name = match.group("name")
            raw_value, inline_comment = self._split_inline_comment(
                match.group("raw")
            )
            value = self._display_value(raw_value)
            sensitive = self._is_sensitive(name)
            section = ensure_section()
            description_parts = pending_comments
            pending_comments = []
            if inline_comment:
                description_parts.append(inline_comment)
            duplicate = name in seen_names
            seen_names.add(name)
            section["variables"].append({
                "name": name,
                # This payload is only served by an admin-only, no-store API.
                # The browser renders sensitive values as password fields.
                "value": value,
                "kind": self._value_kind(value, sensitive),
                "sensitive": sensitive,
                "configured": bool(value),
                "description": " ".join(description_parts),
                "duplicate": duplicate,
            })
            after_blank = False

        finish_block()
        sections = [section for section in sections if section["variables"] or section["notes"]]
        stat = self.path.stat()
        return {
            "sections": sections,
            "variable_count": len(seen_names),
            "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "restart_required": True,
        }

    def update(self, changes: dict[str, str]) -> dict[str, Any]:
        if not changes:
            raise EnvironmentFileError("Không có biến môi trường nào được thay đổi.")
        if len(changes) > 500:
            raise EnvironmentFileError("Có quá nhiều biến môi trường trong một lần lưu.")
        for name, value in changes.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise EnvironmentFileError(f"Tên biến không hợp lệ: {name}")
            if "\x00" in value or "\n" in value or "\r" in value:
                raise EnvironmentFileError(
                    f"Giá trị của {name} không được chứa ký tự xuống dòng."
                )
            if len(value) > 20_000:
                raise EnvironmentFileError(f"Giá trị của {name} quá dài.")

        with self._lock:
            newline, lines = self._read()
            last_positions: dict[str, int] = {}
            current_values: dict[str, str] = {}
            for index, line in enumerate(lines):
                match = ASSIGNMENT_PATTERN.match(line)
                if match:
                    name = match.group("name")
                    raw_value, _ = self._split_inline_comment(match.group("raw"))
                    last_positions[name] = index
                    current_values[name] = self._display_value(raw_value)

            unknown = sorted(set(changes) - set(last_positions))
            if unknown:
                raise EnvironmentFileError(
                    "Chỉ được cập nhật biến đã có trong .env: "
                    + ", ".join(unknown)
                )

            effective_values = {**current_values, **changes}
            self._validate_effective_values(effective_values)

            for name, value in changes.items():
                index = last_positions[name]
                match = ASSIGNMENT_PATTERN.match(lines[index])
                if match is None:
                    raise EnvironmentFileError(f"Không thể cập nhật biến {name}.")
                _, inline_comment = self._split_inline_comment(match.group("raw"))
                suffix = f"  # {inline_comment}" if inline_comment else ""
                lines[index] = (
                    match.group("prefix")
                    + self._encoded_value(value)
                    + suffix
                )

            content = newline.join(lines)
            if lines:
                content += newline
            temporary = self.path.with_name(f"{self.path.name}.tmp")
            try:
                temporary.write_text(content, encoding="utf-8", newline="")
                os.replace(temporary, self.path)
            finally:
                if temporary.exists():
                    temporary.unlink()

        return {
            "updated": sorted(changes),
            "updated_count": len(changes),
            "restart_required": True,
            "updated_at": datetime.now().isoformat(),
        }
