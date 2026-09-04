from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.conversation.context import conversation_context_store


router = APIRouter(prefix="/admin/conversations", tags=["Conversation Admin"])
PAGE_PATH = Path(__file__).resolve().parent.parent / "static" / "conversation_admin.html"


class HumanModeRequest(BaseModel):
    ttl_seconds: int = Field(default=600, ge=60, le=604800)


def _history_service(request: Request):
    return getattr(
        request.app.state,
        "conversation_history_service",
        None,
    )


def _combined_sessions(request: Request) -> list[dict]:
    """Ghép cache đang chạy với lịch sử bền vững trong PostgreSQL."""
    live_items = conversation_context_store.list_sessions()
    history_service = _history_service(request)
    stored_items = (
        history_service.list_sessions(limit=10000)
        if history_service is not None
        else []
    )
    combined = {
        (str(item["channel"]), str(item["session_id"])): {
            **item,
            "cache_active": False,
            "ttl_seconds": None,
        }
        for item in stored_items
    }
    for live in live_items:
        key = (str(live["channel"]), str(live["session_id"]))
        stored = combined.get(key, {})
        combined[key] = {
            **stored,
            **live,
            "message_count": max(
                int(stored.get("message_count") or 0),
                int(live.get("message_count") or 0),
            ),
            "cache_active": True,
        }
    return list(combined.values())


@router.get("", response_class=HTMLResponse)
def page():
    return HTMLResponse(
        PAGE_PATH.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/sessions")
def sessions(
    request: Request,
    channel: str | None = Query(default=None, max_length=50),
    search: str = Query(default="", max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    items = _combined_sessions(request)
    normalized_channel = (channel or "").strip().casefold()
    normalized_search = search.strip().casefold()
    if normalized_channel:
        items = [item for item in items if item["channel"] == normalized_channel]
    if normalized_search:
        fields = ("session_id", "customer_name", "customer_phone", "last_message")
        items = [
            item for item in items
            if any(normalized_search in str(item.get(field) or "").casefold() for field in fields)
        ]
    items.sort(
        key=lambda item: (
            str(item.get("last_message_at") or ""),
            bool(item.get("cache_active")),
        ),
        reverse=True,
    )
    page_items = [dict(item) for item in items[offset:offset + limit]]
    human_mode_service = getattr(request.app.state, "human_mode_service", None)
    for item in page_items:
        details = (
            human_mode_service.details(item["channel"], item["session_id"])
            if human_mode_service
            else None
        )
        item["human_mode"] = bool(details)
        item["human_mode_remaining_seconds"] = (
            details.get("remaining_seconds") if details else None
        )
    return {
        "total": len(items),
        "limit": limit,
        "offset": offset,
        "sessions": page_items,
    }


@router.get("/api/sessions/{channel}/{session_id}")
def session_detail(channel: str, session_id: str, request: Request):
    live_item = conversation_context_store.inspect(session_id, channel)
    history_service = _history_service(request)
    stored_item = (
        history_service.get_session(channel=channel, session_id=session_id)
        if history_service is not None
        else None
    )
    if live_item is None and stored_item is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy hội thoại")
    item = {
        **(stored_item or {}),
        **(live_item or {}),
        "cache_active": live_item is not None,
        "ttl_seconds": (
            live_item.get("ttl_seconds") if live_item is not None else None
        ),
    }
    total_message_count = max(
        int((stored_item or {}).get("message_count") or 0),
        int((live_item or {}).get("message_count") or 0),
    )
    stored_messages = (
        history_service.list_messages(
            channel=channel,
            session_id=session_id,
            limit=500,
        )
        if history_service is not None
        else []
    )
    context = dict(item.get("context") or {})
    if stored_messages:
        context["history"] = [
            {
                "role": message.get("role"),
                "text": message.get("content") or "",
                "created_at": message.get("created_at"),
            }
            for message in stored_messages
        ]
        item["message_count"] = max(total_message_count, len(stored_messages))
        item["last_message"] = stored_messages[-1].get("content") or ""
    context.setdefault("history", [])
    item["context"] = context
    return item


@router.delete("/api/sessions/{channel}/{session_id}/cache")
def clear_session_cache(channel: str, session_id: str, request: Request):
    live_item = conversation_context_store.inspect(session_id, channel)
    history_service = _history_service(request)
    stored_item = (
        history_service.get_session(channel=channel, session_id=session_id)
        if history_service is not None
        else None
    )
    if live_item is None and stored_item is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy hội thoại")

    snapshot_saved = False
    if live_item is not None and history_service is not None:
        snapshot_saved = history_service.update_session_snapshot(
            channel=channel,
            session_id=session_id,
            snapshot=live_item,
        )
    if live_item is not None and stored_item is None and not snapshot_saved:
        raise HTTPException(
            status_code=503,
            detail=(
                "Hội thoại chưa được lưu an toàn vào PostgreSQL; "
                "cache Redis chưa bị xóa"
            ),
        )
    cache_deleted = conversation_context_store.reset(session_id, channel)

    human_mode_service = getattr(
        request.app.state,
        "human_mode_service",
        None,
    )
    if human_mode_service is not None:
        human_mode_service.disable(channel, session_id)

    return {
        "success": True,
        "channel": channel,
        "session_id": session_id,
        "cache_deleted": bool(cache_deleted),
        "snapshot_saved": bool(snapshot_saved),
        "history_preserved": stored_item is not None or snapshot_saved,
    }


def _human_mode_service(request: Request):
    service = getattr(request.app.state, "human_mode_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Human mode service chưa sẵn sàng",
        )
    return service


def _all_session_keys() -> list[tuple[str, str]]:
    return list({
        (str(item["channel"]), str(item["session_id"]))
        for item in conversation_context_store.list_sessions()
    })


@router.get("/api/human-mode")
def global_human_mode_status(request: Request):
    service = _human_mode_service(request)
    session_keys = _all_session_keys()
    paused = []
    for channel, session_id in session_keys:
        details = service.details(channel, session_id)
        if details:
            paused.append(details)
    remaining = [
        int(item.get("remaining_seconds") or 0)
        for item in paused
        if item.get("remaining_seconds") is not None
    ]
    return {
        "total": len(session_keys),
        "paused": len(paused),
        "all_paused": bool(session_keys) and len(paused) == len(session_keys),
        "remaining_seconds": min(remaining) if remaining else None,
        "default_ttl_seconds": service.get_default_ttl(),
    }


@router.put("/api/human-mode/duration")
def update_human_mode_duration(payload: HumanModeRequest, request: Request):
    """Lưu thời gian mặc định và gia hạn các hội thoại đang tạm dừng."""
    service = _human_mode_service(request)
    ttl_seconds = service.set_default_ttl(payload.ttl_seconds)
    renewed = 0
    for channel, session_id in _all_session_keys():
        details = service.details(channel, session_id)
        if not details:
            continue
        service.enable(
            channel,
            session_id,
            reason=str(details.get("reason") or "staff_takeover"),
            activated_by=str(details.get("activated_by") or "admin"),
            ttl_seconds=ttl_seconds,
        )
        renewed += 1
    return {
        "success": True,
        "default_ttl_seconds": ttl_seconds,
        "renewed": renewed,
        "remaining_seconds": ttl_seconds if renewed else None,
    }


@router.post("/api/human-mode")
def enable_global_human_mode(payload: HumanModeRequest, request: Request):
    service = _human_mode_service(request)
    service.set_default_ttl(payload.ttl_seconds)
    session_keys = _all_session_keys()
    for channel, session_id in session_keys:
        service.enable(
            channel,
            session_id,
            reason="global_staff_takeover",
            activated_by="admin",
            ttl_seconds=payload.ttl_seconds,
        )
    return {
        "success": True,
        "paused": len(session_keys),
        "remaining_seconds": payload.ttl_seconds,
    }


@router.delete("/api/human-mode")
def disable_global_human_mode(request: Request):
    service = _human_mode_service(request)
    session_keys = _all_session_keys()
    for channel, session_id in session_keys:
        service.disable(channel, session_id)
    return {"success": True, "resumed": len(session_keys)}


@router.get("/api/sessions/{channel}/{session_id}/human-mode")
def human_mode_status(channel: str, session_id: str, request: Request):
    service = _human_mode_service(request)
    return {
        "enabled": service.is_enabled(channel, session_id),
        "details": service.details(channel, session_id),
    }


@router.post("/api/sessions/{channel}/{session_id}/human-mode")
def enable_human_mode(
    channel: str,
    session_id: str,
    request: Request,
    payload: HumanModeRequest,
):
    service = _human_mode_service(request)
    service.enable(
        channel,
        session_id,
        reason="staff_takeover",
        activated_by="admin",
        ttl_seconds=payload.ttl_seconds,
    )
    details = service.details(channel, session_id)
    return {
        "success": True,
        "channel": channel,
        "session_id": session_id,
        "human_mode": True,
        "details": details,
    }


@router.delete("/api/sessions/{channel}/{session_id}/human-mode")
def disable_human_mode(channel: str, session_id: str, request: Request):
    service = _human_mode_service(request)
    service.disable(channel, session_id)
    return {
        "success": True,
        "channel": channel,
        "session_id": session_id,
        "human_mode": False,
    }
