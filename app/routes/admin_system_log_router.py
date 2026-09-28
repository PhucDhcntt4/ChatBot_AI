from pathlib import Path
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.services.system_log_service import SystemLogError, SystemLogService


router = APIRouter(prefix="/admin/system-logs", tags=["Admin System Logs"])
PAGE_PATH = Path(__file__).resolve().parent.parent / "static" / "system_log_admin.html"
LOG_SERVICE = SystemLogService()
logger = logging.getLogger("uvicorn.error")


def _require_admin(request: Request) -> dict:
    service = getattr(request.app.state, "admin_auth_service", None)
    if service is None or not service.enabled:
        raise HTTPException(
            status_code=503,
            detail="Hãy bật đăng nhập quản trị trước khi xem lịch sử hệ thống.",
        )
    user = getattr(request.state, "admin_user", None)
    if not user or user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Chỉ quản trị viên được xem lịch sử hệ thống.",
        )
    return user


@router.get("", response_class=HTMLResponse)
def page(request: Request):
    _require_admin(request)
    return HTMLResponse(
        PAGE_PATH.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/files")
def list_log_files(request: Request):
    _require_admin(request)
    return JSONResponse(
        {"files": LOG_SERVICE.list_files()},
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/entries")
def list_log_entries(
    request: Request,
    file: str = Query(default=SystemLogService.ALL_FILES, max_length=255),
    level: str = Query(default="", max_length=20),
    search: str = Query(default="", max_length=200),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=25, le=500),
):
    _require_admin(request)
    try:
        result = LOG_SERVICE.read_entries(
            file_name=file,
            level=level,
            search=search,
            offset=offset,
            limit=limit,
        )
    except SystemLogError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.delete("/api/entries")
def clear_log_entries(
    request: Request,
    file: str = Query(default=SystemLogService.ALL_FILES, max_length=255),
):
    user = _require_admin(request)
    try:
        result = LOG_SERVICE.clear(file)
    except SystemLogError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(
            status_code=503,
            detail="Không thể giải phóng file log đang được sử dụng.",
        ) from error
    logger.warning(
        "SYSTEM LOG CLEARED admin=%s files=%s cleared_bytes=%s",
        user.get("username"),
        ",".join(result["files"]),
        result["cleared_bytes"],
    )
    return JSONResponse(result, headers={"Cache-Control": "no-store"})
