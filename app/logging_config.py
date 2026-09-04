import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
from typing import Any


DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent / "log"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 10
NOISY_LIBRARY_LOGGERS = (
    "watchfiles",
    "watchfiles.main",
    "httpx",
    "httpx2",
    "httpcore",
    "urllib3",
    "PIL",
    "google_genai",
    "google_genai.models",
    "open_clip",
    "open_clip.factory",
    "filelock",
)


def _integer_env(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _boolean_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def setup_logging(
    *,
    service_name: str = "app",
    log_dir: str | Path | None = None,
    enable_file: bool | None = None,
) -> list[logging.Handler]:
    """Configure terminal logs and optionally add UTF-8 rotating files."""
    level_name = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)

    # Keep business-flow INFO logs, but hide repetitive dependency messages
    # such as reload scans and outbound HTTP request summaries.
    for logger_name in NOISY_LIBRARY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    # Uvicorn access records every static asset, polling request and webhook.
    # Keep them available behind an explicit switch, but hide them by default.
    access_level = (
        logging.INFO if _boolean_env("LOG_ACCESS_ENABLED") else logging.WARNING
    )
    logging.getLogger("uvicorn.access").setLevel(access_level)
    logging.getLogger("uvicorn.error").setLevel(level)

    # Terminal-only is the safe default. File logging must be explicitly
    # enabled with LOG_TO_FILE=true (or enable_file=True in a caller/test).
    file_logging_enabled = (
        _boolean_env("LOG_TO_FILE")
        if enable_file is None
        else enable_file
    )
    if not file_logging_enabled:
        logging.basicConfig(level=level)
        # Some dependencies log directly to root (not their package logger).
        # App messages use uvicorn.error, so WARNING here removes dependency
        # startup noise without hiding application INFO records.
        logging.getLogger().setLevel(logging.WARNING)
        logging.getLogger(service_name).setLevel(level)
        return []

    directory = Path(log_dir or os.getenv("LOG_DIR") or DEFAULT_LOG_DIR)
    directory.mkdir(parents=True, exist_ok=True)

    max_bytes = _integer_env("LOG_MAX_BYTES", DEFAULT_MAX_BYTES, 1024)
    backup_count = _integer_env(
        "LOG_BACKUP_COUNT",
        DEFAULT_BACKUP_COUNT,
        1,
    )
    normalized_service = "".join(
        character
        for character in service_name.strip().casefold()
        if character.isalnum() or character in {"-", "_"}
    ) or "app"
    marker = f"donghai:{normalized_service}:{directory.resolve()}"

    root = logging.getLogger()
    existing = [
        handler
        for handler in root.handlers
        if getattr(handler, "_donghai_log_marker", None) == marker
    ]
    if existing:
        return existing

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | "
        "pid=%(process)d thread=%(threadName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    app_handler = RotatingFileHandler(
        directory / f"{normalized_service}.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
        delay=True,
    )
    app_handler.setLevel(level)
    app_handler.setFormatter(formatter)

    error_handler = RotatingFileHandler(
        directory / f"{normalized_service}_error.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
        delay=True,
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    handlers = [app_handler, error_handler]
    for handler in handlers:
        handler._donghai_log_marker = marker  # type: ignore[attr-defined]
        root.addHandler(handler)

    root.setLevel(logging.WARNING)
    logging.getLogger(service_name).setLevel(level)

    # Uvicorn owns these loggers and normally disables propagation. Attach the
    # same files directly while retaining its existing console handlers.
    # uvicorn.error propagates to the parent "uvicorn" logger. Attaching to
    # both would write each application message twice.
    for logger_name in ("uvicorn", "uvicorn.access"):
        target = logging.getLogger(logger_name)
        # These handlers are also registered on the root logger. Prevent the
        # Uvicorn records from propagating back to root and being written twice.
        target.propagate = False
        for handler in handlers:
            if handler not in target.handlers:
                target.addHandler(handler)

    logging.getLogger("uvicorn.error").info(
        "FILE LOGGING READY service=%s directory=%s level=%s "
        "max_bytes=%s backups=%s",
        normalized_service,
        directory.resolve(),
        logging.getLevelName(level),
        max_bytes,
        backup_count,
    )
    return handlers


def log_bot_response(
    logger: logging.Logger,
    *,
    channel: str,
    session_id: str,
    response: Any,
    total_seconds: float,
    send_seconds: float | None = None,
) -> None:
    """Write one compact, timing-aware line for a completed bot reply."""
    timing = dict(getattr(response, "timing", None) or {})
    phase_names = (
        "planner",
        "executor",
        "classification",
        "recognition",
        "presenter",
    )
    phase_text = " ".join(
        f"{name}={float(timing[name]):.3f}s"
        for name in phase_names
        if timing.get(name) is not None
    )
    intent = getattr(response, "intent", None)
    intent_value = getattr(intent, "value", intent) or "unknown"
    kind = "image" if "recognition" in timing else "text"
    send_text = (
        f" send={send_seconds:.3f}s"
        if send_seconds is not None
        else ""
    )
    logger.info(
        "BOT RESPONSE channel=%s session=%s kind=%s status=%s intent=%s "
        "provider=%s model=%s products=%s media=%s%s%s total=%.3fs",
        channel,
        session_id,
        kind,
        getattr(response, "status", "unknown"),
        intent_value,
        getattr(response, "provider", "unknown"),
        getattr(response, "model", "unknown"),
        len(getattr(response, "products", None) or []),
        len(getattr(response, "media", None) or []),
        f" {phase_text}" if phase_text else "",
        send_text,
        total_seconds,
    )
