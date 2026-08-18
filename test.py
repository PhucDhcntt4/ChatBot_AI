"""Google Sheets smoke test: `python test.py` or `python test.py --write`."""

import argparse
import json
import sys

from app.services.sheets_service import SheetsService


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


TEST_ORDER = {
    "customer_name": "Nguyễn Văn An",
    "customer_phone": "0764776093",
    "shipping_address": "12 Phan Huy Ích, Gò Vấp, Hồ Chí Minh",
    "payment_method": "cod",
    "subtotal": 1_570_000,
    "shipping_fee": 30_000,
    "total": 1_600_000,
    "items": [
        {
            "product_code": "G81V6",
            "product_name": "Giày Cao Gót Đông Hải Mũi Nhọn Khóa Logo",
            "color": "Đen",
            "size": "36",
            "quantity": 1,
            "unit_price": 750_000,
            "subtotal": 750_000,
        },
        {
            "product_code": "S32I4",
            "product_name": "Sandal Xuồng Đông Hải Êm Chân Quai Đan Chéo",
            "color": "Kem",
            "size": "37",
            "quantity": 1,
            "unit_price": 820_000,
            "subtotal": 820_000,
        },
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    service = SheetsService()

    print("========== GOOGLE SHEETS ORDER TEST ==========")
    print(f"Enabled: {service.enabled}")
    print(f"Spreadsheet ID: {service.spreadsheet_id or '(chưa cấu hình)'}")
    print(f"Range: {service.orders_range}")
    print(f"Credentials: {service.credentials_path}")
    try:
        service.validate()
    except Exception as error:
        print(f"CẤU HÌNH KHÔNG HỢP LỆ: {error}")
        return 1
    if not service.enabled:
        print("Google Sheets đang tắt trong .env.")
        return 1

    order_id = f"TEST-{service.create_order_id()}"
    rows = service.build_rows(
        order_id=order_id,
        order_summary=TEST_ORDER,
        channel="test",
        session_id="test-sheets-service",
    )
    print(f"Order ID: {order_id}")
    print(f"Số dòng: {len(rows)}; số cột: {[len(row) for row in rows]}")
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    if not args.write:
        print("DRY RUN THÀNH CÔNG - chưa ghi Google Sheets.")
        print("Dùng `python test.py --write` để ghi thật.")
        return 0
    try:
        count = service.append_confirmed_order(
            order_id=order_id,
            order_summary=TEST_ORDER,
            channel="test",
            session_id="test-sheets-service",
        )
    except Exception as error:
        print(f"GHI GOOGLE SHEETS THẤT BẠI: {error}")
        return 1
    print(f"GHI THÀNH CÔNG: {count} dòng, order_id={order_id}")
    response = service.last_append_response or {}
    updated_range = response.get("updates", {}).get("updatedRange")
    print(f"Google updatedRange: {updated_range or '(không có)'}")
    try:
        saved_rows = service.find_order_rows(
            order_id,
            lookup_range=updated_range,
        )
    except Exception as error:
        print(f"KHÔNG THỂ ĐỌC KIỂM TRA: {error}")
        return 1
    print(f"ĐỌC LẠI TỪ SHEETS: tìm thấy {len(saved_rows)} dòng.")
    if len(saved_rows) != count:
        print("CẢNH BÁO: số dòng đọc lại không khớp số dòng đã ghi.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
