import logging
from collections import deque
from threading import Lock
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.config import (
    CHANNEL_PROVIDERS,
    TELEGRAM_CHAT_CHANNEL,
    TELEGRAM_WEBHOOK_SECRET,
)


router = APIRouter(prefix="/api/telegram", tags=["Telegram"])
logger = logging.getLogger("uvicorn.error")
_update_lock = Lock()
_processed_updates: deque[int] = deque(maxlen=2000)
_processed_update_ids: set[int] = set()


def _remember_update(update_id: Any) -> bool:
    if not isinstance(update_id, int):
        return True
    with _update_lock:
        if update_id in _processed_update_ids:
            return False
        if len(_processed_updates) == _processed_updates.maxlen:
            _processed_update_ids.discard(_processed_updates[0])
        _processed_updates.append(update_id)
        _processed_update_ids.add(update_id)
    return True


def _process_payload(app, payload: dict[str, Any]) -> None:
    providers = getattr(app.state, "channel_providers", {})
    provider = providers.get(TELEGRAM_CHAT_CHANNEL)
    dispatcher = getattr(app.state, "channel_dispatcher", None)
    chat_id, text, file_id = provider.extract(payload) if provider else (None, "", None)
    try:
        if provider is None or dispatcher is None:
            raise RuntimeError("Telegram channel provider chưa sẵn sàng.")
        if chat_id is None:
            return
        recipient_id = str(chat_id)
        try:
            provider.send_typing(recipient_id)
        except Exception:
            logger.warning("Không thể gửi typing Telegram chat_id=%s", chat_id)

        if text.casefold() in {"/reset", "/new", "hội thoại mới"} and not file_id:
            dispatcher.reset(TELEGRAM_CHAT_CHANNEL, recipient_id)
            provider.send_text(
                recipient_id,
                "Dạ, em đã bắt đầu một hội thoại mới. Anh/chị cần em hỗ trợ gì ạ?",
            )
            return

        event, _ = provider.to_event(payload)
        if event is None or (not event.text and not event.has_image):
            return
        response, history_message_id = dispatcher.dispatch_with_history(
            event,
            respect_human_mode=True,
        )
        if response is None:
            return
        history_service = getattr(app.state, "conversation_history_service", None)
        try:
            provider.send_response(recipient_id, response)
        except Exception as error:
            if history_service is not None:
                history_service.mark_send_failed(
                    history_message_id,
                    error,
                    error_code="TELEGRAM_SEND_FAILED",
                )
            raise
        else:
            if history_service is not None:
                history_service.mark_sent(history_message_id)
        logger.info(
            "CHANNEL RESPONSE provider=%s session=%s status=%s media=%s",
            event.channel,
            event.user_id,
            response.status,
            len(response.media),
        )
    except Exception:
        logger.exception("CHANNEL ERROR provider=telegram chat_id=%s", chat_id)
        if provider is not None and chat_id is not None:
            try:
                provider.send_text(
                    str(chat_id),
                    "Dạ, hiện em chưa thể xử lý yêu cầu này. Anh/chị thử lại giúp em sau ạ.",
                )
            except Exception:
                logger.exception("Không thể gửi thông báo lỗi Telegram chat_id=%s", chat_id)


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: dict[str, Any],
):
    if TELEGRAM_CHAT_CHANNEL not in CHANNEL_PROVIDERS:
        raise HTTPException(status_code=503, detail="Kênh Telegram chưa được bật.")
    received_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if TELEGRAM_WEBHOOK_SECRET and received_secret != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Telegram webhook secret không hợp lệ.")
    providers = getattr(request.app.state, "channel_providers", {})
    if TELEGRAM_CHAT_CHANNEL not in providers:
        raise HTTPException(status_code=503, detail="Telegram provider chưa sẵn sàng.")
    if not _remember_update(payload.get("update_id")):
        return {"status": "duplicate", "channel": TELEGRAM_CHAT_CHANNEL}
    background_tasks.add_task(_process_payload, request.app, payload)
    return {"status": "received", "channel": TELEGRAM_CHAT_CHANNEL}
