import re
import unicodedata
from pathlib import Path

from app.config import KNOWLEDGE_DIR


class ShippingPolicyService:
    """Read standard delivery fees from the editable shipping document."""

    DEFAULT_PATH = KNOWLEDGE_DIR / "shipping" / "Dat_Hang_Van_Chuyen.txt"

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else self.DEFAULT_PATH

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
        if not self.path.is_file():
            return None

        in_standard_section = False
        for raw_line in self.path.read_text(encoding="utf-8").splitlines():
            line = self._normalize(raw_line).strip()
            if "goi tieu chuan" in line:
                in_standard_section = True
                continue
            if in_standard_section and "goi chuyen phat nhanh" in line:
                break
            if not in_standard_section:
                continue
            if payment_method == "bank_transfer" and "chuyen khoan truoc" in line:
                return 0 if "mien ship" in line else self._amount(line)
            if payment_method == "cod" and "nhan hang thanh toan" in line:
                return self._amount(line)
        return None
