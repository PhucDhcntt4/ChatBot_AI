import re
import unicodedata
from time import monotonic

from fastapi import HTTPException  # type: ignore

from app.config import (
    SHIPPING_POLICY_CACHE_SECONDS,
    SHIPPING_POLICY_CATEGORY,
)
from app.knowledge.admin_client import admin_client


class ShippingPolicyService:
    """Read complete active shipping documents through the RAG administration API."""

    def __init__(self) -> None:
        self._cached_content: str | None = None
        self._cache_expires_at = 0.0

    def _read_content(self) -> str:
        now = monotonic()
        if (
            self._cached_content is not None
            and now < self._cache_expires_at
        ):
            return self._cached_content

        if not SHIPPING_POLICY_CATEGORY:
            raise HTTPException(
                status_code=503,
                detail="Chua cau hinh nhom tai lieu van chuyen.",
            )

        with admin_client() as client:
            documents = client.details_by_category(
                SHIPPING_POLICY_CATEGORY
            )

        contents = [
            document["content"].strip()
            for document in documents
            if isinstance(document.get("content"), str)
            and document["content"].strip()
        ]
        if not contents:
            raise HTTPException(
                status_code=503,
                detail="Nhom tai lieu van chuyen khong co noi dung.",
            )

        content = "\n\n".join(contents)
        self._cached_content = content
        self._cache_expires_at = now + SHIPPING_POLICY_CACHE_SECONDS
        return content

    @staticmethod
    def _normalize(value: str) -> str:
        value = unicodedata.normalize("NFD", value.casefold())
        return "".join(
            character
            for character in value
            if unicodedata.category(character) != "Mn"
        ).replace("\u0111", "d")

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
            detail="Khong doc duoc phi tieu chuan trong tai lieu van chuyen.",
        )
