import hashlib
import hmac
import itertools
import logging
import time
from collections import deque
from threading import Lock
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.config import (
    CHANNEL_PROVIDERS,
    FACEBOOK_APP_SECRET,
    FACEBOOK_CHAT_CHANNEL,
    FACEBOOK_VERIFY_TOKEN,
)


router = APIRouter(tags=["Facebook"])
logger = logging.getLogger("uvicorn.error")
_message_lock = Lock()
_processed_messages: deque[str] = deque(maxlen=5000)
_processed_message_ids: set[str] = set()
_queue_lock = Lock()
_event_queues: dict[str, deque[tuple[int, int, dict[str, Any]]]] = {}
_active_recipients: set[str] = set()
_event_sequence = itertools.count()
AI_MESSAGE_METADATA = "donghai_ai"


def _remember_message(message_id: str | None) -> bool:
    if not message_id:
        return True
    with _message_lock:
        if message_id in _processed_message_ids:
            return False
        if len(_processed_messages) == _processed_messages.maxlen:
            _processed_message_ids.discard(_processed_messages[0])
        _processed_messages.append(message_id)
        _processed_message_ids.add(message_id)
    return True


def _valid_signature(body: bytes, signature: str) -> bool:
    if not FACEBOOK_APP_SECRET:
        return False
    expected = "sha256=" + hmac.new(
        FACEBOOK_APP_SECRET.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _handle_message_echo(
    app,
    event_payload: dict[str, Any],
    page_id: str | None = None,
) -> bool:
    """Pause AI when a Page agent replies from Meta Business Suite."""
    message = event_payload.get("message") or {}
    if not isinstance(message, dict):
        return False
    sender_id = str(
        (event_payload.get("sender") or {}).get("id") or ""
    ).strip()
    customer_id = str(
        (event_payload.get("recipient") or {}).get("id") or ""
    ).strip()
    is_page_outbound = bool(
        page_id
        and sender_id == str(page_id).strip()
        and customer_id
        and customer_id != sender_id
    )
    if not message.get("is_echo") and not is_page_outbound:
        return False
    logger.info(
        "FACEBOOK OUTBOUND EVENT sender=%s recipient=%s is_echo=%s "
        "metadata=%s app_id=%s mid=%s",
        sender_id,
        customer_id,
        bool(message.get("is_echo")),
        message.get("metadata"),
        message.get("app_id"),
        message.get("mid"),
    )
    if str(message.get("metadata") or "").strip() == AI_MESSAGE_METADATA:
        logger.info("FACEBOOK BOT ECHO IGNORED mid=%s", message.get("mid"))
        return True
    if not customer_id:
        logger.warning("FACEBOOK STAFF ECHO missing recipient mid=%s", message.get("mid"))
        return True
    human_mode = getattr(app.state, "human_mode_service", None)
    if human_mode is None:
        logger.warning("FACEBOOK STAFF ECHO human mode unavailable customer=%s", customer_id)
        return True
    human_mode.enable(
        FACEBOOK_CHAT_CHANNEL,
        customer_id,
        reason="staff_replied_in_meta",
        activated_by="meta_business_suite",
    )
    logger.info(
        "FACEBOOK STAFF TAKEOVER customer=%s mid=%s",
        customer_id,
        message.get("mid"),
    )
    return True


def _process_event(app, event_payload: dict[str, Any]) -> None:
    provider = getattr(app.state, "channel_providers", {}).get(
        FACEBOOK_CHAT_CHANNEL
    )
    dispatcher = getattr(app.state, "channel_dispatcher", None)
    recipient_id, _, _, _ = (
        provider.extract(event_payload) if provider else (None, "", None, None)
    )
    if provider is None or dispatcher is None or recipient_id is None:
        return
    try:
        try:
            provider.send_typing(recipient_id)
        except Exception:
            logger.warning(
                "Không thể gửi typing Facebook recipient=%s", recipient_id
            )
        event, _ = provider.to_event(event_payload)
        if event is None or (not event.text and not event.has_image):
            return
        if (
            event.text.casefold() in {"/reset", "/new", "hội thoại mới"}
            and not event.has_image
        ):
            dispatcher.reset(FACEBOOK_CHAT_CHANNEL, recipient_id)
            provider.send_text(
                recipient_id,
                "Dạ, em đã bắt đầu một hội thoại mới. Anh/chị cần em hỗ trợ gì ạ?",
            )
            return
        response, history_message_id = dispatcher.dispatch_with_history(
            event,
            respect_human_mode=True,
        )
        if response is None:
            return
        history_service = getattr(
            app.state, "conversation_history_service", None
        )
        try:
            provider.send_response(recipient_id, response)
        except Exception as error:
            if history_service is not None:
                history_service.mark_send_failed(
                    history_message_id,
                    error,
                    error_code="FACEBOOK_SEND_FAILED",
                )
            raise
        else:
            if history_service is not None:
                history_service.mark_sent(history_message_id)
        logger.info(
            "CHANNEL RESPONSE provider=facebook session=%s status=%s media=%s",
            recipient_id,
            response.status,
            len(response.media),
        )
    except Exception:
        logger.exception(
            "CHANNEL ERROR provider=facebook recipient=%s", recipient_id
        )
        try:
            provider.send_text(
                recipient_id,
                "Dạ, hiện em chưa thể xử lý yêu cầu này. Anh/chị thử lại giúp em sau ạ.",
            )
        except Exception:
            logger.exception(
                "Không thể gửi thông báo lỗi Facebook recipient=%s",
                recipient_id,
            )


def _drain_recipient_queue(app, recipient_id: str) -> None:
    """Process one customer's Facebook events sequentially and in timestamp order."""
    # Facebook may deliver an image and its following text through separate,
    # nearly simultaneous webhook requests. A short collection window lets us
    # order those events by Facebook's timestamp before starting AI work.
    time.sleep(0.25)
    while True:
        with _queue_lock:
            queue = _event_queues.get(recipient_id)
            if not queue:
                _event_queues.pop(recipient_id, None)
                _active_recipients.discard(recipient_id)
                return
            ordered = sorted(queue, key=lambda item: (item[0], item[1]))
            queue.clear()

        for _, _, event_payload in ordered:
            logger.info(
                "FACEBOOK EVENT PROCESS recipient=%s mid=%s timestamp=%s",
                recipient_id,
                (event_payload.get("message") or {}).get("mid"),
                event_payload.get("timestamp"),
            )
            _process_event(app, event_payload)


def _enqueue_event(app, event_payload: dict[str, Any]) -> str | None:
    provider = getattr(app.state, "channel_providers", {}).get(
        FACEBOOK_CHAT_CHANNEL
    )
    if provider is None:
        return None
    recipient_id, _, _, message_id = provider.extract(event_payload)
    if recipient_id is None or not _remember_message(message_id):
        return None

    timestamp = event_payload.get("timestamp")
    try:
        timestamp_value = int(timestamp)
    except (TypeError, ValueError):
        timestamp_value = int(time.time() * 1000)

    should_start = False
    with _queue_lock:
        queue = _event_queues.setdefault(recipient_id, deque())
        queue.append((timestamp_value, next(_event_sequence), event_payload))
        pending_count = len(queue)
        if recipient_id not in _active_recipients:
            _active_recipients.add(recipient_id)
            should_start = True
    logger.info(
        "FACEBOOK EVENT QUEUED recipient=%s mid=%s timestamp=%s pending=%s",
        recipient_id,
        message_id,
        timestamp_value,
        pending_count,
    )
    return recipient_id if should_start else None


@router.get("/webhook/facebook", response_class=PlainTextResponse)
def verify_facebook_webhook(
    mode: str | None = Query(None, alias="hub.mode"),
    verify_token: str | None = Query(None, alias="hub.verify_token"),
    challenge: str | None = Query(None, alias="hub.challenge"),
):
    if FACEBOOK_CHAT_CHANNEL not in CHANNEL_PROVIDERS:
        raise HTTPException(status_code=503, detail="Kênh Facebook chưa được bật.")
    if mode != "subscribe" or not hmac.compare_digest(
        verify_token or "", FACEBOOK_VERIFY_TOKEN
    ):
        raise HTTPException(status_code=403, detail="Facebook verify token không hợp lệ.")
    return challenge or ""


@router.post("/webhook/facebook")
async def facebook_webhook(request: Request, background_tasks: BackgroundTasks):
    if FACEBOOK_CHAT_CHANNEL not in CHANNEL_PROVIDERS:
        raise HTTPException(status_code=503, detail="Kênh Facebook chưa được bật.")
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _valid_signature(body, signature):
        raise HTTPException(status_code=403, detail="Chữ ký Facebook không hợp lệ.")
    try:
        payload = await request.json()
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Payload Facebook không hợp lệ.") from error
    if payload.get("object") != "page":
        raise HTTPException(status_code=400, detail="Facebook object không được hỗ trợ.")
    accepted = 0
    recipients_to_start: set[str] = set()
    for entry in payload.get("entry") or []:
        page_id = str(entry.get("id") or "").strip() or None
        events = list(entry.get("messaging") or [])
        events.extend(entry.get("standby") or [])
        for event in events:
            if isinstance(event, dict):
                message = event.get("message")
                logger.info(
                    "FACEBOOK WEBHOOK EVENT page=%s container=%s keys=%s "
                    "sender=%s recipient=%s message_keys=%s",
                    page_id,
                    "standby" if event in (entry.get("standby") or []) else "messaging",
                    sorted(event.keys()),
                    (event.get("sender") or {}).get("id"),
                    (event.get("recipient") or {}).get("id"),
                    sorted(message.keys()) if isinstance(message, dict) else [],
                )
            if isinstance(event, dict) and isinstance(event.get("message"), dict):
                if _handle_message_echo(request.app, event, page_id):
                    accepted += 1
                    continue
                recipient_to_start = _enqueue_event(request.app, event)
                if recipient_to_start:
                    recipients_to_start.add(recipient_to_start)
                accepted += 1
    for recipient_id in recipients_to_start:
        background_tasks.add_task(
            _drain_recipient_queue,
            request.app,
            recipient_id,
        )
    return {"status": "received", "channel": FACEBOOK_CHAT_CHANNEL, "events": accepted}
