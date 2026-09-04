from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.services.admin_auth_service import AdminAuthService


router = APIRouter(tags=["Admin Authentication"])
PAGE_PATH = Path(__file__).resolve().parent.parent / "static" / "login_admin.html"


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=500)
    remember: bool = False
    redirect_to: str | None = Field(default=None, max_length=1000)


def _service(request: Request) -> AdminAuthService:
    service = getattr(request.app.state, "admin_auth_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Dịch vụ đăng nhập quản trị chưa sẵn sàng.",
        )
    return service


def _safe_admin_redirect(value: str | None) -> str:
    target = str(value or "").strip()
    if (
        target.startswith("/admin/")
        and not target.startswith("//")
        and not target.startswith("/admin/login")
    ):
        return target
    return "/admin/products"


@router.get("/admin/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    next_path: str | None = Query(default=None, alias="next", max_length=1000),
):
    service = _service(request)
    if not service.enabled:
        return RedirectResponse(url="/admin/products", status_code=303)
    if service.is_authenticated(
        request.cookies.get(service.COOKIE_NAME)
    ):
        return RedirectResponse(
            url=_safe_admin_redirect(next_path),
            status_code=303,
        )
    return HTMLResponse(
        PAGE_PATH.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )


@router.post("/admin/login")
def login(payload: AdminLoginRequest, request: Request):
    service = _service(request)
    if not service.enabled:
        raise HTTPException(
            status_code=503,
            detail=(
                "Đăng nhập quản trị chưa được bật. "
                "Hãy cấu hình ADMIN_AUTH_ENABLED trong .env."
            ),
        )
    user = service.authenticate(payload.username, payload.password)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Sai tài khoản hoặc mật khẩu.",
        )

    token, ttl = service.create_session(user, remember=payload.remember)
    response = JSONResponse({
        "success": True,
        "username": user["username"],
        "display_name": user.get("display_name"),
        "role": user["role"],
        "redirect": _safe_admin_redirect(payload.redirect_to),
    })
    response.set_cookie(
        key=service.COOKIE_NAME,
        value=token,
        max_age=ttl,
        httponly=True,
        secure=service.cookie_secure,
        samesite="lax",
        path="/admin",
    )
    return response


@router.get("/admin/session")
def session(request: Request):
    service = _service(request)
    payload = service.read_session(
        request.cookies.get(service.COOKIE_NAME)
    )
    return {
        "enabled": service.enabled,
        "authenticated": payload is not None,
        "username": payload.get("username") if payload else None,
        "display_name": payload.get("display_name") if payload else None,
        "role": payload.get("role") if payload else None,
    }


@router.post("/admin/logout")
def logout(request: Request):
    service = _service(request)
    response = JSONResponse({"success": True, "redirect": "/admin/login"})
    response.delete_cookie(
        key=service.COOKIE_NAME,
        path="/admin",
        secure=service.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response
