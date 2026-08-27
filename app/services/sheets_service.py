import logging
from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from google.oauth2.service_account import Credentials  # type: ignore
from googleapiclient.discovery import build  # type: ignore
from googleapiclient.errors import HttpError  # type: ignore

from app.config import (
    GOOGLE_SERVICE_ACCOUNT_FILE,
    GOOGLE_SHEETS_ENABLED,
    GOOGLE_SHEETS_ORDERS_RANGE,
    GOOGLE_SHEETS_SPREADSHEET_ID,
    PROJECT_ROOT,
)


logger = logging.getLogger("uvicorn.error")
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


class SheetsConfigurationError(RuntimeError):
    """Raised when Sheets export is enabled but its configuration is invalid."""


class SheetsService:
    """Append confirmed order items to a Google Sheets worksheet.

    One item is stored per row. Order-level and customer fields are repeated so
    staff can filter the sheet without parsing JSON or merging cells.
    """

    def __init__(
        self,
        *,
        enabled: bool = GOOGLE_SHEETS_ENABLED,
        spreadsheet_id: str = GOOGLE_SHEETS_SPREADSHEET_ID,
        orders_range: str = GOOGLE_SHEETS_ORDERS_RANGE,
        credentials_file: str = GOOGLE_SERVICE_ACCOUNT_FILE,
        api: Any | None = None,
        max_append_attempts: int = 3,
        retry_base_delay: float = 1.0,
        sleep_function: Any = sleep,
    ) -> None:
        self.enabled = enabled
        self.spreadsheet_id = spreadsheet_id.strip()
        self.orders_range = orders_range.strip() or "Orders!A:V"
        credentials_path = Path(credentials_file)
        self.credentials_path = (
            credentials_path
            if credentials_path.is_absolute()
            else PROJECT_ROOT / credentials_path
        )
        self._api = api
        self.max_append_attempts = max(1, int(max_append_attempts))
        self.retry_base_delay = max(0.0, float(retry_base_delay))
        self._sleep = sleep_function
        self.last_append_response: dict[str, Any] | None = None

    @staticmethod
    def _retryable_http_error(error: HttpError) -> bool:
        return int(getattr(error.resp, "status", 0) or 0) in {
            429,
            500,
            502,
            503,
            504,
        }

    def validate(self) -> None:
        if not self.enabled:
            return
        if not self.spreadsheet_id:
            raise SheetsConfigurationError(
                "Thiếu GOOGLE_SHEETS_SPREADSHEET_ID."
            )
        if self._api is None and not self.credentials_path.is_file():
            raise SheetsConfigurationError(
                "Không tìm thấy Google service-account key tại "
                f"{self.credentials_path}."
            )

    def _client(self):
        self.validate()
        if self._api is None:
            credentials = Credentials.from_service_account_file(
                str(self.credentials_path),
                scopes=[SHEETS_SCOPE],
            )
            self._api = build(
                "sheets",
                "v4",
                credentials=credentials,
                cache_discovery=False,
            )
        return self._api

    @staticmethod
    def create_order_id() -> str:
        timestamp = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).strftime(
            "%Y%m%d-%H%M%S"
        )
        return f"DH-{timestamp}-{uuid4().hex[:8].upper()}"

    @staticmethod
    def _cell(value: Any) -> Any:
        """Return scalar data only; RAW mode keeps text from becoming formulas."""
        if value is None:
            return ""
        if isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    def build_rows(
        self,
        *,
        order_id: str,
        order_summary: dict[str, Any],
        channel: str,
        session_id: str,
    ) -> list[list[Any]]:
        confirmed_at = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).isoformat(
            timespec="seconds"
        )
        items = order_summary.get("items") or []
        rows: list[list[Any]] = []
        for index, item in enumerate(items, start=1):
            rows.append([
                order_id,
                confirmed_at,
                channel,
                session_id,
                order_summary.get("customer_name"),
                order_summary.get("customer_phone"),
                order_summary.get("shipping_address"),
                order_summary.get("payment_method"),
                index,
                item.get("product_code"),
                item.get("product_name"),
                item.get("color"),
                item.get("size"),
                item.get("quantity"),
                item.get("unit_price"),
                item.get("subtotal"),
                order_summary.get("subtotal"),
                order_summary.get("shipping_fee"),
                order_summary.get("total"),
                order_summary.get("promotion_note")
                or "Không ghi nhận chương trình khuyến mãi.",
                "pending_review",
                "exported",
            ])
        return [[self._cell(value) for value in row] for row in rows]

    def append_confirmed_order(
        self,
        *,
        order_id: str,
        order_summary: dict[str, Any],
        channel: str,
        session_id: str,
    ) -> int:
        if not self.enabled:
            return 0
        rows = self.build_rows(
            order_id=order_id,
            order_summary=order_summary,
            channel=channel,
            session_id=session_id,
        )
        if not rows:
            raise ValueError("Đơn đã xác nhận không có sản phẩm để xuất Sheets.")
        response = None
        for attempt in range(1, self.max_append_attempts + 1):
            try:
                response = (
                    self._client()
                    .spreadsheets()
                    .values()
                    .append(
                        spreadsheetId=self.spreadsheet_id,
                        range=self.orders_range,
                        valueInputOption="RAW",
                        insertDataOption="INSERT_ROWS",
                        body={"values": rows},
                    )
                    .execute()
                )
                break
            except HttpError as error:
                if (
                    not self._retryable_http_error(error)
                    or attempt >= self.max_append_attempts
                ):
                    raise

                # An append can reach Google even when its response is lost.
                # Check the stable order ID before retrying to avoid duplicates.
                try:
                    existing_rows = self.find_order_rows(order_id)
                except Exception:
                    existing_rows = []
                if existing_rows:
                    logger.warning(
                        "GOOGLE SHEETS ORDER ALREADY PRESENT AFTER ERROR "
                        "order_id=%s rows=%s attempt=%s",
                        order_id,
                        len(existing_rows),
                        attempt,
                    )
                    return len(existing_rows)

                delay = self.retry_base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "GOOGLE SHEETS ORDER RETRY order_id=%s status=%s "
                    "attempt=%s/%s delay=%.1fs",
                    order_id,
                    getattr(error.resp, "status", None),
                    attempt + 1,
                    self.max_append_attempts,
                    delay,
                )
                self._sleep(delay)

        if response is None:
            raise RuntimeError("Google Sheets không trả kết quả ghi đơn hàng.")
        self.last_append_response = response
        updated_range = (
            response.get("updates", {}).get("updatedRange")
            if isinstance(response, dict)
            else None
        )
        logger.info(
            "GOOGLE SHEETS ORDER EXPORTED order_id=%s rows=%s session=%s "
            "updated_range=%s",
            order_id,
            len(rows),
            session_id,
            updated_range,
        )
        return len(rows)

    def find_order_rows(
        self,
        order_id: str,
        lookup_range: str | None = None,
    ) -> list[list[Any]]:
        """Read the configured worksheet and return rows for one order ID."""
        if not self.enabled:
            return []
        response = (
            self._client()
            .spreadsheets()
            .values()
            .get(
                spreadsheetId=self.spreadsheet_id,
                range=lookup_range or self.orders_range,
            )
            .execute()
        )
        return [
            row
            for row in response.get("values", [])
            if row and str(row[0]).strip() == order_id
        ]
