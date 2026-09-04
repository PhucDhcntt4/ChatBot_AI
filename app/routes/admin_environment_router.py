import os
import time
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from app.config import PROJECT_ROOT
from app.services.environment_service import (
    EnvironmentFileError,
    EnvironmentFileService,
)


router = APIRouter(prefix="/admin/environment", tags=["Admin Environment"])
PAGE_PATH = Path(__file__).resolve().parent.parent / "static" / "environment_admin.html"
ENVIRONMENT_SERVICE = EnvironmentFileService(PROJECT_ROOT / ".env")
RELOAD_MARKER_PATH = PROJECT_ROOT / "app" / "runtime_reload.py"


class EnvironmentChange(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    value: str = Field(default="", max_length=20_000)


class EnvironmentUpdate(BaseModel):
    changes: list[EnvironmentChange] = Field(min_length=1, max_length=500)


def _require_admin(request: Request) -> dict:
    service = getattr(request.app.state, "admin_auth_service", None)
    if service is None or not service.enabled:
        raise HTTPException(
            status_code=503,
            detail="Hãy bật đăng nhập quản trị trước khi quản lý biến môi trường.",
        )
    user = getattr(request.state, "admin_user", None)
    if not user or user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Chỉ quản trị viên được quản lý biến môi trường.",
        )
    return user


@router.get("", response_class=HTMLResponse)
def page(request: Request):
    _require_admin(request)
    return HTMLResponse(
        PAGE_PATH.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api")
def read_environment(request: Request):
    _require_admin(request)
    try:
        payload = ENVIRONMENT_SERVICE.read_public()
    except EnvironmentFileError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


def _reload_application() -> None:
    # Background tasks run after the response has been sent. Uvicorn reload
    # mode watches Python files and restarts the app with the new .env values.
    time.sleep(0.6)
    os.utime(RELOAD_MARKER_PATH, None)


@router.put("/api")
def update_environment(
    payload: EnvironmentUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
):
    user = _require_admin(request)
    changes: dict[str, str] = {}
    for change in payload.changes:
        if change.name in changes:
            raise HTTPException(
                status_code=422,
                detail=f"Biến {change.name} xuất hiện nhiều lần trong yêu cầu.",
            )
        changes[change.name] = change.value
    try:
        result = ENVIRONMENT_SERVICE.update(changes)
    except EnvironmentFileError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    # Never log values because this page also manages API keys and secrets.
    import logging

    logging.getLogger("uvicorn.error").info(
        "ENV UPDATED admin=%s variables=%s reload_scheduled=true",
        user.get("username"),
        ",".join(result["updated"]),
    )
    result["previous_runtime_id"] = getattr(
        request.app.state,
        "runtime_id",
        None,
    )
    background_tasks.add_task(_reload_application)
    result["restart_required"] = True
    result["reload_scheduled"] = True
    return result
