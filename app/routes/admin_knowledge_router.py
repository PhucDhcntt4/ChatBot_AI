"""Keep the bot's Knowledge UI; document data is owned exclusively by RAG Service."""
from pathlib import Path
import re
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path as PathParam, Request, UploadFile
from fastapi.responses import HTMLResponse

from app.knowledge.admin_client import admin_client


router = APIRouter(prefix="/admin/knowledge", tags=["Knowledge Admin"])
PAGE_PATH = Path(__file__).resolve().parent.parent / "static" / "knowledge_admin.html"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def get_client():
    with admin_client() as client:
        yield client


def same_origin(request: Request):
    # Cookie-authenticated writes must not originate from another website.
    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin:
        supplied = urlsplit(origin)
        target = urlsplit(str(request.base_url))
        if supplied.scheme != target.scheme or supplied.netloc != target.netloc:
            raise HTTPException(403, "Nguồn yêu cầu không hợp lệ")
    elif request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Nguồn yêu cầu không hợp lệ")


@router.get("", response_class=HTMLResponse)
def page():
    return HTMLResponse(PAGE_PATH.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.get("/api/documents")
def documents(client=Depends(get_client)):
    return client.documents()


@router.get("/api/documents/{document_id}")
def document_detail(document_id: int = PathParam(gt=0), client=Depends(get_client)):
    return client.detail(document_id)


@router.delete("/api/documents/{document_id}", dependencies=[Depends(same_origin)])
def delete_document(document_id: int = PathParam(gt=0), client=Depends(get_client)):
    return client.delete(document_id)


@router.post("/api/upload", dependencies=[Depends(same_origin)])
def upload(file: UploadFile = File(...), category: str = Form("customer_care"), client=Depends(get_client)):
    try:
        filename = re.split(r"[/\\]", file.filename or "")[-1].strip()
        if (not filename or len(filename) > 500 or "\x00" in filename
                or Path(filename).suffix.lower() not in {".txt", ".md", ".pdf"}):
            raise HTTPException(422, "Chỉ hỗ trợ tài liệu TXT, Markdown, PDF có tên hợp lệ.")
        category = re.sub(r"\s+", "_", category.strip().casefold())
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,99}", category):
            raise HTTPException(422, "Tên nhóm chỉ dùng chữ không dấu, số, dấu gạch ngang hoặc gạch dưới.")
        content = file.file.read(MAX_UPLOAD_BYTES + 1)
        if not content:
            raise HTTPException(422, "Tài liệu không có dữ liệu")
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Tài liệu vượt quá 10 MB")
        # Add means add: a same-named upload cannot silently replace another service document.
        return client.upload(filename, content, category, f"bot_upload/{uuid4().hex}")
    finally:
        file.file.close()


@router.get("/api/jobs/{job_id}")
def retired_job(job_id: str):
    raise HTTPException(410, "Upload hiện chờ kết quả trực tiếp từ RAG Service. Hãy tải lại trang.")
