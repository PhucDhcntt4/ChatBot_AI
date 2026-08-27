from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.conversation.context import conversation_context_store


router = APIRouter(prefix="/admin/conversations", tags=["Conversation Admin"])
PAGE_PATH = Path(__file__).resolve().parent.parent / "static" / "conversation_admin.html"


class HumanModeRequest(BaseModel):
    ttl_seconds: int = Field(default=600, ge=60, le=604800)


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
    items = conversation_context_store.list_sessions()
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
            item.get("ttl_seconds") is not None,
            item.get("ttl_seconds") or -1,
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
def session_detail(channel: str, session_id: str):
    item = conversation_context_store.inspect(session_id, channel)
    if item is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy hội thoại")
    return item


@router.delete("/api/sessions/{channel}/{session_id}")
def delete_session(channel: str, session_id: str, request: Request):
    item = conversation_context_store.inspect(session_id, channel)
    if item is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy hội thoại")
    conversation_context_store.reset(session_id, channel)
    service = getattr(request.app.state, "human_mode_service", None)
    if service is not None:
        service.disable(channel, session_id)
    return {"success": True, "channel": channel, "session_id": session_id}


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
    }


@router.post("/api/human-mode")
def enable_global_human_mode(payload: HumanModeRequest, request: Request):
    service = _human_mode_service(request)
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
