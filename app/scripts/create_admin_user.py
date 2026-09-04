import argparse
from getpass import getpass
import sys

from app.database.admin_user_repository import AdminUserRepository
from app.services.admin_auth_service import hash_password


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _password_from_terminal() -> str:
    password = getpass("Mật khẩu: ")
    confirmation = getpass("Nhập lại mật khẩu: ")
    if password != confirmation:
        raise ValueError("Hai lần nhập mật khẩu không giống nhau.")
    return password


def main() -> None:
    _configure_console()
    parser = argparse.ArgumentParser(
        description="Tạo tài khoản đăng nhập trang quản trị Đông Hải."
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name")
    parser.add_argument("--role", default="admin")
    parser.add_argument(
        "--update-password",
        action="store_true",
        help="Đổi mật khẩu tài khoản đã tồn tại và thu hồi các phiên cũ.",
    )
    args = parser.parse_args()

    password_hash = hash_password(_password_from_terminal())
    repository = AdminUserRepository()
    if args.update_password:
        updated = repository.update_password(
            username=args.username,
            password_hash=password_hash,
        )
        if not updated:
            raise SystemExit("Không tìm thấy tài khoản cần đổi mật khẩu.")
        print(f"Đã đổi mật khẩu cho tài khoản {args.username}.")
        return

    user = repository.create_user(
        username=args.username,
        password_hash=password_hash,
        display_name=args.display_name,
        role=args.role,
    )
    print(f"Đã tạo tài khoản {user['username']} với role {user['role']}.")


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        print(f"Không thể tạo tài khoản: {error}", file=sys.stderr)
        raise SystemExit(1) from None
