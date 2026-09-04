from pathlib import Path
import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.database.admin_user_repository import AdminUserRepository
from app.services.admin_auth_service import hash_password


router = APIRouter(prefix="/admin/users", tags=["Admin Users"])
PAGE_PATH = Path(__file__).resolve().parent.parent / "static" / "user_admin.html"
AdminRole = Literal["admin", "manager", "staff"]


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=3, max_length=500)
    display_name: str | None = Field(default=None, max_length=150)
    role: AdminRole = "staff"


class AdminUserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=150)
    role: AdminRole
    is_active: bool


class AdminPasswordUpdate(BaseModel):
    password: str = Field(min_length=3, max_length=500)


def _repository(request: Request) -> AdminUserRepository:
    repository = getattr(request.app.state, "admin_user_repository", None)
    if repository is None:
        raise HTTPException(
            status_code=503,
            detail="Kho tài khoản quản trị chưa sẵn sàng.",
        )
    return repository


def _require_admin(request: Request) -> dict:
    service = getattr(request.app.state, "admin_auth_service", None)
    if service is None or not service.enabled:
        raise HTTPException(
            status_code=503,
            detail="Hãy bật đăng nhập quản trị trước khi quản lý tài khoản.",
        )
    user = getattr(request.state, "admin_user", None)
    if not user or user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Chỉ quản trị viên được quản lý tài khoản.",
        )
    return user


def _clean_optional(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _validate_username(value: str) -> str:
    username = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,100}", username):
        raise HTTPException(
            status_code=422,
            detail=(
                "Tài khoản chỉ gồm chữ không dấu, số, dấu chấm, "
                "gạch dưới hoặc gạch ngang."
            ),
        )
    return username


@router.get("", response_class=HTMLResponse)
def page(request: Request):
    _require_admin(request)
    return HTMLResponse(
        PAGE_PATH.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api")
def list_users(request: Request):
    current = _require_admin(request)
    return {
        "users": _repository(request).list_users(),
        "current_user_id": int(current["id"]),
        "roles": ["admin", "manager", "staff"],
    }


@router.post("/api", status_code=201)
def create_user(payload: AdminUserCreate, request: Request):
    _require_admin(request)
    repository = _repository(request)
    try:
        user = repository.create_user(
            username=_validate_username(payload.username),
            password_hash=hash_password(payload.password),
            display_name=_clean_optional(payload.display_name),
            role=payload.role,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"status": "created", "user": user}


@router.put("/api/{user_id}")
def update_user(user_id: int, payload: AdminUserUpdate, request: Request):
    current = _require_admin(request)
    repository = _repository(request)
    target = repository.find_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản.")

    is_self = int(target["id"]) == int(current["id"])
    removes_admin = payload.role != "admin" or not payload.is_active
    if is_self and removes_admin:
        raise HTTPException(
            status_code=422,
            detail="Bạn không thể tự khóa hoặc tự bỏ quyền admin của mình.",
        )
    if (
        bool(target.get("is_active"))
        and target.get("role") == "admin"
        and removes_admin
        and repository.active_admin_count() <= 1
    ):
        raise HTTPException(
            status_code=422,
            detail="Hệ thống phải còn ít nhất một tài khoản admin hoạt động.",
        )

    try:
        updated = repository.update_user(
            user_id=user_id,
            display_name=_clean_optional(payload.display_name),
            role=payload.role,
            is_active=payload.is_active,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if not updated:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản.")
    return {"status": "updated", "user": updated}


@router.post("/api/{user_id}/password")
def update_password(
    user_id: int,
    payload: AdminPasswordUpdate,
    request: Request,
):
    current = _require_admin(request)
    repository = _repository(request)
    target = repository.find_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản.")
    updated = repository.update_password_by_id(
        user_id=user_id,
        password_hash=hash_password(payload.password),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản.")
    return {
        "status": "password_updated",
        "session_revoked": int(user_id) == int(current["id"]),
    }
