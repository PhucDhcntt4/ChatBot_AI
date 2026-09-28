import logging
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from app.config import (
    IMAGE_EMBEDDING_MODEL,
    IMAGE_EMBEDDING_PRETRAINED,
    PRODUCT_IMAGE_DIR,
)
from app.database.product_repository_factory import create_product_repository
from app.database.qdrant_image_repository import QdrantImageRepository
from app.services.product_recognition_reference_service import (
    add_recognition_reference,
)


router = APIRouter(prefix="/admin/products", tags=["Product Admin"])
PAGE_PATH = Path(__file__).resolve().parent.parent / "static" / "product_admin.html"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
logger = logging.getLogger("uvicorn.error")


def _recognition_images(product_code: str) -> list[dict]:
    rows = QdrantImageRepository().images_for_product(
        product_code, source_kind="recognition"
    )
    rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    return [{
        **row,
        "embedded": True,
        "content_url": f"/admin/products/api/recognition-images/{row['id']}/content",
    } for row in rows]


@router.get("", response_class=HTMLResponse)
def page():
    return HTMLResponse(PAGE_PATH.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.get("/api/catalog")
def catalog(
    response: Response,
    search: str = Query("", max_length=100),
    product_type: str = Query("", max_length=200),
    status: str = Query("", max_length=50),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    response.headers["Cache-Control"] = "no-store"
    repository = create_product_repository()
    result = repository.catalog_page(
        search=search.strip(),
        product_type=product_type.strip(),
        status=status.strip(),
        limit=limit,
        offset=offset,
    )
    return {
        **result,
        "embedding_model": IMAGE_EMBEDDING_MODEL,
        "provider": repository.provider,
    }


@router.get("/api/catalog/{product_code}")
def catalog_detail(product_code: str, response: Response):
    response.headers["Cache-Control"] = "no-store"
    code = product_code.strip().upper()
    if not code:
        raise HTTPException(status_code=422, detail="Mã sản phẩm không hợp lệ.")

    repository = create_product_repository()
    detail = repository.catalog_detail(code)
    if not detail:
        raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm.")
    return {
        **detail,
        "recognition_images": _recognition_images(code),
        "embedding_model": IMAGE_EMBEDDING_MODEL,
        "embedding_pretrained": IMAGE_EMBEDDING_PRETRAINED,
        "provider": repository.provider,
    }


@router.post("/api/catalog/{product_code}/recognition-images")
async def upload_recognition_image(
    product_code: str,
    file: UploadFile = File(...),
    color: str = Form(""),
):
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Ảnh vượt quá 5 MB.")
    try:
        result = await run_in_threadpool(
            add_recognition_reference,
            product_code=product_code,
            image_bytes=content,
            color=color,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    logger.info(
        "PRODUCT RECOGNITION IMAGE ADDED code=%s image_id=%s backend=%s",
        result["product_code"],
        result["product_image_id"],
        result["backend"],
    )
    return result


@router.get("/api/recognition-images/{image_id}/content")
def recognition_image_content(image_id: str):
    row = QdrantImageRepository().payload_by_id(image_id)
    if (
        not row or row.get("source_kind") != "recognition"
        or row.get("is_active") is False or not row.get("local_path")
    ):
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh.")
    image_path = (PRODUCT_IMAGE_DIR / str(row["local_path"])).resolve()
    try:
        image_path.relative_to(PRODUCT_IMAGE_DIR.resolve())
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Đường dẫn ảnh không hợp lệ.") from error
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="File ảnh không tồn tại.")
    return Response(
        content=image_path.read_bytes(),
        media_type=str(row.get("mime_type") or "image/jpeg"),
        headers={"Cache-Control": "private, max-age=300"},
    )
