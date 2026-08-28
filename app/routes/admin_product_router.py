import io
import re
import unicodedata
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse
from openpyxl import load_workbook
from pydantic import BaseModel

from app.config import IMAGE_EMBEDDING_MODEL, IMAGE_EMBEDDING_PRETRAINED
from app.database.connection import database_connection
from app.services.product_sync_service import product_sync_manager


router = APIRouter(prefix="/admin/products", tags=["Product Admin"])
PAGE_PATH = Path(__file__).resolve().parent.parent / "static" / "product_admin.html"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
SKU_HEADERS = {"sku", "ma san pham", "product code", "product sku", "variant sku"}


class SkuImportRequest(BaseModel):
    skus: list[str]


def _normalize_header(value: object) -> str:
    normalized = unicodedata.normalize("NFD", str(value or "").strip().casefold())
    normalized = "".join(
        character for character in normalized
        if unicodedata.category(character) != "Mn"
    ).replace("đ", "d")
    return re.sub(r"[\s_-]+", " ", normalized).strip()


def _read_excel_skus(content: bytes) -> list[str]:
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as error:
        raise ValueError("File Excel không hợp lệ hoặc bị hỏng.") from error
    rows = workbook.active.iter_rows(values_only=True)
    header = next((row for row in rows if any(str(v or "").strip() for v in row)), None)
    if not header:
        raise ValueError("File Excel không có dữ liệu.")
    headers = [_normalize_header(value) for value in header]
    sku_index = next((i for i, name in enumerate(headers) if name in SKU_HEADERS), None)
    if sku_index is None:
        raise ValueError("Excel phải có cột SKU, Mã sản phẩm hoặc Product Code.")
    skus = [
        str(row[sku_index]).strip()
        for row in rows
        if sku_index < len(row) and row[sku_index] is not None and str(row[sku_index]).strip()
    ]
    if not skus:
        raise ValueError("Cột SKU không có mã sản phẩm.")
    return skus


def _start_job(skus: list[str]) -> dict:
    try:
        job = product_sync_manager.create(skus)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return job.public()


@router.get("", response_class=HTMLResponse)
def page():
    return HTMLResponse(PAGE_PATH.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.post("/api/import-skus")
def import_skus(data: SkuImportRequest):
    return _start_job(data.skus)


@router.post("/api/import-excel")
async def import_excel(file: UploadFile = File(...)):
    if Path(file.filename or "").suffix.casefold() != ".xlsx":
        raise HTTPException(status_code=415, detail="Chỉ hỗ trợ file .xlsx.")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File vượt quá 5 MB.")
    try:
        return _start_job(_read_excel_skus(content))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/api/sync-all")
def sync_all_products():
    with database_connection() as connection:
        rows = connection.execute(
            """
            SELECT product_code
            FROM products
            WHERE status = 'ACTIVE'
              AND COALESCE(product_code, '') <> ''
            ORDER BY product_code
            """
        ).fetchall()
    codes = [str(row["product_code"]).strip() for row in rows]
    if not codes:
        raise HTTPException(
            status_code=422,
            detail="Chưa có sản phẩm ACTIVE để đồng bộ.",
        )
    try:
        # Nút quản trị này cố ý không áp giới hạn 1.000 mã của file Excel.
        # Worker vẫn xử lý tuần tự và ghi tiến độ vào Redis như job bình thường.
        job = product_sync_manager.create(codes, max_skus=None)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return job.public()


@router.get("/api/sync-all/preview")
def sync_all_preview():
    with database_connection() as connection:
        active_count = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM products
            WHERE status = 'ACTIVE'
              AND COALESCE(product_code, '') <> ''
            """
        ).fetchone()["count"]
    return {"active_count": int(active_count or 0)}


@router.get("/api/jobs/{job_id}")
def job(job_id: str):
    result = product_sync_manager.get(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ.")
    return result


@router.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    result = product_sync_manager.cancel(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ.")
    return result


@router.get("/api/catalog")
def catalog(
    search: str = Query("", max_length=100),
    product_type: str = Query("", max_length=200),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    keyword = search.strip()
    selected_type = product_type.strip()
    conditions: list[str] = []
    filter_params: list[object] = []
    if keyword:
        conditions.append(
            "(p.product_code ILIKE %s OR p.title ILIKE %s "
            "OR p.product_type ILIKE %s)"
        )
        pattern = f"%{keyword}%"
        filter_params.extend([pattern, pattern, pattern])
    if selected_type:
        conditions.append("p.product_type = %s")
        filter_params.append(selected_type)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    with database_connection() as connection:
        product_types = connection.execute(
            """
            SELECT DISTINCT product_type
            FROM products
            WHERE COALESCE(product_type, '') <> ''
            ORDER BY product_type
            """
        ).fetchall()
        total = connection.execute(
            f"SELECT COUNT(*) count FROM products p {where}", filter_params
        ).fetchone()["count"]
        rows = connection.execute(
            f"""
            SELECT p.product_code, p.title, p.product_type, p.status, p.updated_at,
                   COUNT(DISTINCT pv.id) variant_count,
                   COUNT(DISTINCT pi.id) FILTER (WHERE pi.is_active) image_count,
                   COUNT(DISTINCT pi.id) FILTER (
                       WHERE pi.is_active AND COALESCE(pi.local_path, '') <> ''
                   ) local_image_count,
                   COUNT(DISTINCT pie.product_image_id) embedding_count,
                   STRING_AGG(DISTINCT pv.color, ', ' ORDER BY pv.color) colors
            FROM products p
            LEFT JOIN product_variants pv ON pv.product_id = p.id
            LEFT JOIN product_images pi ON pi.product_id = p.id
            LEFT JOIN product_image_embeddings pie
              ON pie.product_image_id = pi.id
             AND pie.model_name = %s AND pie.pretrained_name = %s
            {where}
            GROUP BY p.id ORDER BY p.updated_at DESC, p.product_code
            LIMIT %s OFFSET %s
            """,
            [
                IMAGE_EMBEDDING_MODEL,
                IMAGE_EMBEDDING_PRETRAINED,
                *filter_params,
                limit,
                offset,
            ],
        ).fetchall()
    products = []
    for row in rows:
        item = dict(row)
        item["updated_at"] = item["updated_at"].isoformat() if item["updated_at"] else None
        item["ai_ready"] = (
            item["status"] == "ACTIVE"
            and int(item["local_image_count"] or 0) > 0
            and int(item["embedding_count"] or 0) >= int(item["local_image_count"] or 0)
        )
        products.append(item)
    return {
        "total": int(total), "limit": limit, "offset": offset,
        "embedding_model": IMAGE_EMBEDDING_MODEL,
        "product_types": [row["product_type"] for row in product_types],
        "products": products,
    }


@router.get("/api/catalog/{product_code}")
def catalog_detail(product_code: str):
    code = product_code.strip().upper()
    if not code:
        raise HTTPException(status_code=422, detail="Mã sản phẩm không hợp lệ.")

    with database_connection() as connection:
        product = connection.execute(
            """
            SELECT product_code, title, handle, vendor, product_type,
                   description, material, sole, height, status,
                   online_store_url, source_updated_at, created_at, updated_at
            FROM products
            WHERE product_code = %s
            """,
            (code,),
        ).fetchone()
        if not product:
            raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm.")

        product_id = connection.execute(
            "SELECT id FROM products WHERE product_code = %s",
            (code,),
        ).fetchone()["id"]
        variants = connection.execute(
            """
            SELECT external_id, legacy_id, sku, barcode, variant_title,
                   color, size, price, compare_at_price, inventory_quantity,
                   available, source_updated_at, updated_at
            FROM product_variants
            WHERE product_id = %s
            ORDER BY color NULLS LAST, size NULLS LAST, sku
            """,
            (product_id,),
        ).fetchall()
        images = connection.execute(
            """
            SELECT pi.color, pi.source_url, pi.local_path, pi.alt_text,
                   pi.mime_type, pi.width, pi.height, pi.image_order,
                   pi.is_featured, pi.is_active,
                   EXISTS (
                       SELECT 1
                       FROM product_image_embeddings pie
                       WHERE pie.product_image_id = pi.id
                         AND pie.model_name = %s
                         AND pie.pretrained_name = %s
                   ) AS embedded
            FROM product_images pi
            WHERE pi.product_id = %s
            ORDER BY pi.is_active DESC, pi.image_order NULLS LAST, pi.id
            """,
            (IMAGE_EMBEDDING_MODEL, IMAGE_EMBEDDING_PRETRAINED, product_id),
        ).fetchall()
        attributes = connection.execute(
            """
            SELECT attribute_key, attribute_value
            FROM product_attributes
            WHERE product_id = %s
            ORDER BY attribute_key
            """,
            (product_id,),
        ).fetchall()
        aliases = connection.execute(
            """
            SELECT alias, alias_type
            FROM product_aliases
            WHERE product_id = %s
            ORDER BY alias_type, alias
            """,
            (product_id,),
        ).fetchall()

    return {
        "product": dict(product),
        "variants": [dict(row) for row in variants],
        "images": [dict(row) for row in images],
        "attributes": [dict(row) for row in attributes],
        "aliases": [dict(row) for row in aliases],
        "embedding_model": IMAGE_EMBEDDING_MODEL,
        "embedding_pretrained": IMAGE_EMBEDDING_PRETRAINED,
    }
