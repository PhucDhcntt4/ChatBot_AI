import re
import unicodedata

from fastapi import HTTPException # type: ignore

from app.config import SHIPPING_POLICY_DOCUMENT_ID
from app.knowledge.admin_client import admin_client


class ShippingPolicyService:
    """Đọc tài liệu qua API, giữ nguyên cách phân tích phí."""

    def _read_content(self) -> str:
        if SHIPPING_POLICY_DOCUMENT_ID <= 0:
            raise HTTPException(
                status_code=503,
                detail="Chưa cấu hình ID tài liệu vận chuyển.",
            )

        with admin_client() as client:
            document = client.detail(SHIPPING_POLICY_DOCUMENT_ID)

        if document.get("is_active") is not True:
            raise HTTPException(
                status_code=503,
                detail="Tài liệu vận chuyển đang bị tắt.",
            )

        # Client hiện có đã đổi source_text của API thành content.
        content = document.get("content")

        if not isinstance(content, str) or not content.strip():
            raise HTTPException(
                status_code=503,
                detail="Tài liệu vận chuyển không có nội dung.",
            )

        return content

    @staticmethod
    def _normalize(value: str) -> str:
        value = unicodedata.normalize("NFD", value.casefold())
        return "".join(
            character
            for character in value
            if unicodedata.category(character) != "Mn"
        ).replace("đ", "d")

    @staticmethod
    def _amount(line: str) -> int | None:
        compact = re.sub(r"[^0-9]", "", line)
        return int(compact) if compact else None

    def standard_fee(self, payment_method: str | None) -> int | None:
        if payment_method not in {"cod", "bank_transfer"}:
            return None

        content = self._read_content()

        in_standard_section = False
        for raw_line in content.splitlines():
            line = self._normalize(raw_line).strip()

            if "goi tieu chuan" in line:
                in_standard_section = True
                continue

            if in_standard_section and "goi chuyen phat nhanh" in line:
                break

            if not in_standard_section:
                continue

            if (
                payment_method == "bank_transfer"
                and "chuyen khoan truoc" in line
            ):
                fee = 0 if "mien ship" in line else self._amount(line)
                if fee is not None:
                    return fee

            if (
                payment_method == "cod"
                and "nhan hang thanh toan" in line
            ):
                fee = self._amount(line)
                if fee is not None:
                    return fee

        raise HTTPException(
            status_code=503,
            detail="Không đọc được phí tiêu chuẩn trong tài liệu vận chuyển.",
        )