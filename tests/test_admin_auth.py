import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware import AdminAuthMiddleware
from app.routes.admin_auth_router import router as admin_auth_router
from app.routes.admin_user_router import router as admin_user_router
from app.routes.admin_environment_router import router as admin_environment_router
from app.services.admin_auth_service import (
    AdminAuthConfigurationError,
    AdminAuthService,
    hash_password,
    verify_password,
)


class _UserRepository:
    def __init__(self):
        self.schema_ready = True
        self.user = {
            "id": 7,
            "username": "admin",
            "password_hash": hash_password("strong-password"),
            "display_name": "Quản trị viên",
            "role": "admin",
            "is_active": True,
            "session_version": 1,
        }
        self.login_count = 0
        self.users = [self.user]

    def validate_schema(self):
        if not self.schema_ready:
            raise RuntimeError("missing table")

    def find_for_login(self, username):
        for user in self.users:
            if str(username).casefold() == user["username"].casefold():
                return dict(user)
        return None

    def find_active_by_id(self, user_id):
        for user in self.users:
            if int(user_id) == user["id"] and user["is_active"]:
                return dict(user)
        return None

    def find_by_id(self, user_id):
        for user in self.users:
            if int(user_id) == user["id"]:
                return dict(user)
        return None

    def list_users(self):
        return [dict(user) for user in self.users]

    def active_admin_count(self):
        return sum(
            1 for user in self.users
            if user["is_active"] and user["role"] == "admin"
        )

    def create_user(self, **values):
        if any(
            user["username"].casefold() == values["username"].casefold()
            for user in self.users
        ):
            raise ValueError("Tài khoản đã tồn tại.")
        user = {
            "id": max(item["id"] for item in self.users) + 1,
            "username": values["username"],
            "password_hash": values["password_hash"],
            "display_name": values.get("display_name"),
            "role": values.get("role", "staff"),
            "is_active": True,
            "session_version": 1,
            "last_login_at": None,
        }
        self.users.append(user)
        return dict(user)

    def update_user(self, *, user_id, **values):
        for user in self.users:
            if user["id"] == int(user_id):
                changed_access = (
                    user["role"] != values["role"]
                    or user["is_active"] != values["is_active"]
                )
                user.update(values)
                if changed_access:
                    user["session_version"] += 1
                return dict(user)
        return None

    def update_password_by_id(self, *, user_id, password_hash):
        for user in self.users:
            if user["id"] == int(user_id):
                user["password_hash"] = password_hash
                user["session_version"] += 1
                return True
        return False

    def record_login(self, user_id):
        if int(user_id) == self.user["id"]:
            self.login_count += 1


def _protected_test_app(service: AdminAuthService) -> FastAPI:
    app = FastAPI()
    app.state.admin_auth_service = service
    app.state.admin_user_repository = service.repository
    app.add_middleware(AdminAuthMiddleware, auth_service=service)
    app.include_router(admin_auth_router)
    app.include_router(admin_user_router)
    app.include_router(admin_environment_router)

    @app.get("/admin/secret")
    def secret():
        return {"secret": True}

    @app.get("/admin/example/api/items")
    def items():
        return {"items": []}

    return app


class AdminAuthTests(unittest.TestCase):
    def setUp(self):
        self.repository = _UserRepository()
        self.service = AdminAuthService(
            enabled=True,
            session_secret="s" * 48,
            session_ttl=3600,
            remember_ttl=86400,
            cookie_secure=False,
            repository=self.repository,
        )
        self.client = TestClient(_protected_test_app(self.service))

    def test_password_is_hashed_and_verified(self):
        with self.assertRaises(ValueError):
            hash_password("ab")
        short_encoded = hash_password("abc")
        self.assertTrue(verify_password("abc", short_encoded))

        encoded = hash_password("another-strong-password")
        self.assertNotIn("another-strong-password", encoded)
        self.assertTrue(verify_password("another-strong-password", encoded))
        self.assertFalse(verify_password("wrong-password", encoded))

    def test_admin_page_redirects_to_login_and_api_returns_401(self):
        page = self.client.get(
            "/admin/secret?tab=one",
            headers={"Accept": "text/html"},
            follow_redirects=False,
        )
        api = self.client.get("/admin/example/api/items")

        self.assertEqual(page.status_code, 303)
        self.assertIn("/admin/login?next=", page.headers["location"])
        self.assertEqual(api.status_code, 401)

    def test_login_cookie_allows_admin_and_logout_revokes_browser_cookie(self):
        wrong = self.client.post(
            "/admin/login",
            json={"username": "admin", "password": "wrong"},
        )
        self.assertEqual(wrong.status_code, 401)

        login = self.client.post(
            "/admin/login",
            json={
                "username": "ADMIN",
                "password": "strong-password",
                "remember": True,
                "redirect_to": "/admin/conversations?channel=facebook",
            },
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(
            login.json()["redirect"],
            "/admin/conversations?channel=facebook",
        )
        self.assertEqual(login.json()["display_name"], "Quản trị viên")
        self.assertEqual(self.repository.login_count, 1)
        self.assertIn("HttpOnly", login.headers["set-cookie"])
        self.assertEqual(self.client.get("/admin/secret").status_code, 200)
        session = self.client.get("/admin/session").json()
        self.assertEqual(session["username"], "admin")
        self.assertEqual(session["role"], "admin")

        logout = self.client.post("/admin/logout")
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(
            self.client.get("/admin/example/api/items").status_code,
            401,
        )

    def test_disabling_user_or_changing_password_revokes_existing_session(self):
        user = self.service.authenticate("admin", "strong-password")
        token, _ = self.service.create_session(user)
        self.assertIsNotNone(self.service.read_session(token))

        self.repository.user["session_version"] += 1
        self.assertIsNone(self.service.read_session(token))

        refreshed_user = self.service.authenticate("admin", "strong-password")
        refreshed_token, _ = self.service.create_session(refreshed_user)
        self.repository.user["is_active"] = False
        self.assertIsNone(self.service.read_session(refreshed_token))

    def test_tampered_cookie_is_rejected(self):
        user = self.service.authenticate("admin", "strong-password")
        token, _ = self.service.create_session(user)
        self.assertIsNotNone(self.service.read_session(token))
        self.assertIsNone(self.service.read_session(token + "changed"))
        self.assertIsNone(self.service.read_session("không-phải-cookie"))

    def test_enabled_auth_requires_secret_and_database_table(self):
        missing_secret = AdminAuthService(
            enabled=True,
            session_secret="too-short",
            repository=self.repository,
        )
        with self.assertRaises(AdminAuthConfigurationError):
            missing_secret.validate()

        self.repository.schema_ready = False
        with self.assertRaises(AdminAuthConfigurationError):
            self.service.validate()

    def test_admin_can_create_update_lock_and_reset_user(self):
        self.client.post(
            "/admin/login",
            json={"username": "admin", "password": "strong-password"},
        )
        self.assertEqual(self.client.get("/admin/users").status_code, 200)

        created = self.client.post(
            "/admin/users/api",
            json={
                "username": "staff.01",
                "password": "staff-password",
                "display_name": "Nhân viên 01",
                "role": "staff",
            },
        )
        self.assertEqual(created.status_code, 201)
        user_id = created.json()["user"]["id"]

        updated = self.client.put(
            f"/admin/users/api/{user_id}",
            json={
                "display_name": "Nhân viên bán hàng",
                "role": "manager",
                "is_active": False,
            },
        )
        self.assertEqual(updated.status_code, 200)
        self.assertFalse(updated.json()["user"]["is_active"])

        password = self.client.post(
            f"/admin/users/api/{user_id}/password",
            json={"password": "new-staff-password"},
        )
        self.assertEqual(password.status_code, 200)
        self.assertFalse(password.json()["session_revoked"])

    def test_only_admin_can_manage_environment(self):
        self.client.post(
            "/admin/login",
            json={"username": "admin", "password": "strong-password"},
        )
        page = self.client.get("/admin/environment")
        payload = self.client.get("/admin/environment/api")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(payload.status_code, 200)
        self.assertGreater(payload.json()["variable_count"], 0)
        for section in payload.json()["sections"]:
            for variable in section["variables"]:
                if variable["sensitive"]:
                    self.assertIsInstance(variable["value"], str)
                    self.assertTrue(variable["configured"] or variable["value"] == "")

        self.client.post("/admin/logout")
        self.repository.user["role"] = "manager"
        self.repository.user["session_version"] += 1
        self.client.post(
            "/admin/login",
            json={"username": "admin", "password": "strong-password"},
        )
        self.assertEqual(self.client.get("/admin/environment").status_code, 403)
        self.assertEqual(self.client.get("/admin/environment/api").status_code, 403)

    def test_admin_cannot_lock_self_and_non_admin_cannot_manage_users(self):
        self.client.post(
            "/admin/login",
            json={"username": "admin", "password": "strong-password"},
        )
        blocked = self.client.put(
            "/admin/users/api/7",
            json={
                "display_name": "Quản trị viên",
                "role": "staff",
                "is_active": False,
            },
        )
        self.assertEqual(blocked.status_code, 422)

        self.client.post("/admin/logout")
        self.repository.user["role"] = "manager"
        self.repository.user["session_version"] += 1
        self.client.post(
            "/admin/login",
            json={"username": "admin", "password": "strong-password"},
        )
        self.assertEqual(self.client.get("/admin/users/api").status_code, 403)


if __name__ == "__main__":
    unittest.main()
