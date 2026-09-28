import os
import re
from datetime import datetime, timezone
from pathlib import Path

from app.config import PROJECT_ROOT


LOG_FILE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.log(?:\.\d+)?$")
LOG_HEADER_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:,\d{3})?)"
    r"\s+\|\s+(?P<level>[A-Z]+)\s+\|\s+(?P<logger>[^|]+?)"
    r"\s+\|\s+(?P<context>.*?)\s+\|\s+(?P<message>.*)$"
)
SENSITIVE_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)([^\s,;]+)"),
    re.compile(
        r"(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password)"
        r"\s*[:=]\s*)([^\s,;&]+)"
    ),
)


class SystemLogError(ValueError):
    pass


class SystemLogService:
    ALL_FILES = "__all__"
    MAX_SINGLE_FILE_BYTES = 12 * 1024 * 1024
    MAX_ALL_FILE_BYTES = 2 * 1024 * 1024
    MAX_ALL_ENTRIES_PER_FILE = 2500

    def __init__(self, log_dir: str | Path | None = None) -> None:
        configured = Path(log_dir or os.getenv("LOG_DIR") or "log")
        if not configured.is_absolute():
            configured = PROJECT_ROOT / configured
        self.log_dir = configured.resolve()

    def list_files(self) -> list[dict]:
        if not self.log_dir.exists():
            return []
        files = []
        for path in self.log_dir.iterdir():
            if not path.is_file() or not LOG_FILE_PATTERN.fullmatch(path.name):
                continue
            stat = path.stat()
            files.append({
                "name": path.name,
                "size": stat.st_size,
                "updated_at": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
            })
        return sorted(
            files,
            key=lambda item: (item["updated_at"], item["name"]),
            reverse=True,
        )

    def read_entries(
        self, *, file_name: str = ALL_FILES, level: str = "",
        search: str = "", offset: int = 0, limit: int = 200,
    ) -> dict:
        available = {item["name"]: item for item in self.list_files()}
        normalized_level = level.strip().upper()
        normalized_search = search.strip().casefold()

        if file_name == self.ALL_FILES:
            entries = []
            truncated = False
            for name in available:
                parsed, file_truncated = self._read_file(
                    self.log_dir / name, self.MAX_ALL_FILE_BYTES
                )
                truncated = truncated or file_truncated
                for entry in parsed[-self.MAX_ALL_ENTRIES_PER_FILE:]:
                    entry["file"] = name
                    entries.append(entry)
            entries.sort(
                key=lambda item: (item.get("timestamp") or "", item["file"]),
                reverse=True,
            )
        else:
            if file_name not in available:
                raise SystemLogError("File log không tồn tại hoặc không được phép đọc.")
            entries, truncated = self._read_file(
                self.log_dir / file_name, self.MAX_SINGLE_FILE_BYTES
            )
            for entry in entries:
                entry["file"] = file_name
            entries.reverse()

        if normalized_level:
            entries = [
                entry for entry in entries
                if entry.get("level", "").upper() == normalized_level
            ]
        if normalized_search:
            entries = [
                entry for entry in entries
                if normalized_search in entry["raw"].casefold()
                or normalized_search in entry["file"].casefold()
            ]

        total = len(entries)
        page = entries[offset:offset + limit]
        return {
            "file": file_name, "entries": page, "total": total,
            "offset": offset, "limit": limit,
            "has_more": offset + len(page) < total,
            "truncated": truncated,
        }

    def clear(self, file_name: str) -> dict:
        available = {item["name"]: item for item in self.list_files()}
        if file_name == self.ALL_FILES:
            selected = list(available)
        elif file_name in available:
            selected = [file_name]
        else:
            raise SystemLogError("File log không tồn tại hoặc không được phép xóa nội dung.")

        cleared_bytes = 0
        for name in selected:
            path = (self.log_dir / name).resolve()
            if path.parent != self.log_dir or not path.is_file():
                raise SystemLogError("File log không tồn tại hoặc không được phép xóa nội dung.")
            cleared_bytes += path.stat().st_size
            with path.open("r+b") as stream:
                stream.truncate(0)
        return {
            "cleared": True,
            "files": selected,
            "file_count": len(selected),
            "cleared_bytes": cleared_bytes,
        }

    def _read_file(self, path: Path, max_bytes: int) -> tuple[list[dict], bool]:
        resolved = path.resolve()
        if resolved.parent != self.log_dir or not resolved.is_file():
            raise SystemLogError("File log không tồn tại hoặc không được phép đọc.")
        size = resolved.stat().st_size
        truncated = size > max_bytes
        with resolved.open("rb") as stream:
            if truncated:
                stream.seek(-max_bytes, os.SEEK_END)
                stream.readline()
            data = stream.read()
        return self._parse_entries(data.decode("utf-8", errors="replace")), truncated

    def _parse_entries(self, text: str) -> list[dict]:
        entries: list[dict] = []
        current: dict | None = None
        for physical_line in text.splitlines():
            match = LOG_HEADER_PATTERN.match(physical_line)
            if match:
                if current is not None:
                    entries.append(self._finish_entry(current))
                current = {
                    "timestamp": match.group("timestamp"),
                    "level": match.group("level"),
                    "logger": match.group("logger").strip(),
                    "context": match.group("context").strip(),
                    "message": match.group("message"),
                    "raw": physical_line,
                }
            elif current is not None:
                current["message"] += "\n" + physical_line
                current["raw"] += "\n" + physical_line
            elif physical_line.strip():
                entries.append(self._finish_entry({
                    "timestamp": "", "level": "", "logger": "",
                    "context": "", "message": physical_line, "raw": physical_line,
                }))
        if current is not None:
            entries.append(self._finish_entry(current))
        return entries

    @staticmethod
    def _finish_entry(entry: dict) -> dict:
        for field in ("message", "raw"):
            value = entry[field]
            for pattern in SENSITIVE_PATTERNS:
                value = pattern.sub(r"\1[REDACTED]", value)
            entry[field] = value
        return entry
