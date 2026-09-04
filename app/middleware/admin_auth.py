from urllib.parse import urlencode

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from app.services.admin_auth_service import AdminAuthService


class AdminAuthMiddleware(BaseHTTPMiddleware):
    """Require a valid signed cookie for every admin page and admin API."""

    PUBLIC_PATHS = frozenset({"/admin/login"})

    def __init__(self, app, *, auth_service: AdminAuthService) -> None:
        super().__init__(app)
        self.auth_service = auth_service

    async def dispatch(self, request: Request, call_next):
        path = request.url.path.rstrip("/") or "/"
        if (
            not self.auth_service.enabled
            or not path.startswith("/admin")
            or path in self.PUBLIC_PATHS
        ):
            return await call_next(request)

        token = request.cookies.get(self.auth_service.COOKIE_NAME)
        session = self.auth_service.read_session(token)
        if session is not None:
            request.state.admin_user = session
            request.state.admin_username = session["username"]
            return await call_next(request)

        is_admin_api = "/api/" in f"{path}/"
        accepts_html = "text/html" in request.headers.get("accept", "")
        if request.method == "GET" and not is_admin_api and accepts_html:
            target = request.url.path
            if request.url.query:
                target += f"?{request.url.query}"
            query = urlencode({"next": target})
            return RedirectResponse(
                url=f"/admin/login?{query}",
                status_code=303,
            )
        return JSONResponse(
            status_code=401,
            content={"detail": "Phiên đăng nhập đã hết hạn hoặc không hợp lệ."},
        )
