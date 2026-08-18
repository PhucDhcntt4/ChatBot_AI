import unittest

from app.conversation.models import (
    ConversationContext,
    ConversationIntent,
    ExecutionResult,
)
from app.conversation.service import ConversationService
from app.services.sheets_service import SheetsService


class _Executable:
    def __init__(self, calls):
        self.calls = calls

    def execute(self):
        self.calls.append("execute")
        return {"updates": {"updatedRows": 2}}


class _Values:
    def __init__(self, calls):
        self.calls = calls

    def append(self, **kwargs):
        self.calls.append(kwargs)
        return _Executable(self.calls)


class _Spreadsheets:
    def __init__(self, calls):
        self.calls = calls

    def values(self):
        return _Values(self.calls)


class _FakeAPI:
    def __init__(self):
        self.calls = []

    def spreadsheets(self):
        return _Spreadsheets(self.calls)


class _FakeAI:
    provider_name = "fake"
    model = "fake"


class _FailingSheets:
    enabled = True

    @staticmethod
    def create_order_id():
        return "DH-FAIL"

    @staticmethod
    def append_confirmed_order(**kwargs):
        raise RuntimeError("temporary Google error")


class SheetsServiceTests(unittest.TestCase):
    def setUp(self):
        self.summary = {
            "items": [
                {
                    "product_code": "ABC01",
                    "product_name": "Sản phẩm A",
                    "color": "Đen",
                    "size": "37",
                    "quantity": 2,
                    "unit_price": 500_000,
                    "subtotal": 1_000_000,
                },
                {
                    "product_code": "XYZ02",
                    "product_name": "Sản phẩm B",
                    "color": "Kem",
                    "size": "38",
                    "quantity": 1,
                    "unit_price": 700_000,
                    "subtotal": 700_000,
                },
            ],
            "subtotal": 1_700_000,
            "shipping_fee": 30_000,
            "total": 1_730_000,
            "customer_name": "Phúc",
            "customer_phone": "0764776093",
            "shipping_address": "12 Phan Huy Ích",
            "payment_method": "cod",
            "promotion_note": "Khach muon ap dung ma SALE08.",
        }

    def test_append_one_row_per_item_with_22_columns(self):
        api = _FakeAPI()
        service = SheetsService(
            enabled=True,
            spreadsheet_id="sheet-id",
            orders_range="Orders!A:V",
            api=api,
        )

        count = service.append_confirmed_order(
            order_id="DH-001",
            order_summary=self.summary,
            channel="web",
            session_id="session-1",
        )

        self.assertEqual(count, 2)
        request = api.calls[0]
        self.assertEqual(request["spreadsheetId"], "sheet-id")
        self.assertEqual(request["range"], "Orders!A:V")
        self.assertEqual(request["valueInputOption"], "RAW")
        rows = request["body"]["values"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(len(row) == 22 for row in rows))
        self.assertEqual(rows[0][0], "DH-001")
        self.assertEqual(rows[0][5], "0764776093")
        self.assertEqual(rows[1][9], "XYZ02")
        self.assertEqual(rows[0][19], "Khach muon ap dung ma SALE08.")

    def test_google_failure_does_not_break_order_confirmation(self):
        service = ConversationService(
            _FakeAI(),
            sheets_service=_FailingSheets(),
        )
        context = ConversationContext(session_id="session-2", channel="web")
        result = ExecutionResult(
            success=True,
            status="order_confirmed",
            intent=ConversationIntent.PRODUCT_INFORMATION,
            facts={"order_summary": self.summary},
        )

        service._export_confirmed_order(result, context)

        self.assertEqual(result.status, "order_confirmed")
        self.assertEqual(context.sheet_export_status, "failed")
        self.assertEqual(result.facts["sheet_export"]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
