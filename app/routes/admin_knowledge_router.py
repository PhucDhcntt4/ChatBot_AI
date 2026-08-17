from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from app.database.knowledge_repository import KnowledgeRepository
from app.services.knowledge_admin_service import (
    delete_source_file,
    knowledge_import_manager,
    safe_filename,
)


router = APIRouter(prefix="/admin/knowledge", tags=["Knowledge Admin"])
PAGE_PATH = Path(__file__).resolve().parent.parent / "static" / "knowledge_admin.html"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@router.get("", response_class=HTMLResponse)
def page():
    return HTMLResponse(
        PAGE_PATH.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/documents")
def documents():
    items = KnowledgeRepository().list_documents()
    for item in items:
        for key in ("created_at", "updated_at"):
            if item.get(key):
                item[key] = item[key].isoformat()
    return {"total": len(items), "documents": items}


@router.get("/api/documents/{document_id}")
def document_detail(document_id: int):
    item = KnowledgeRepository().get_document(document_id)
    if not item:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài liệu")
    for key in ("created_at", "updated_at"):
        if item.get(key):
            item[key] = item[key].isoformat()
    return item


@router.delete("/api/documents/{document_id}")
def delete_document(document_id: int):
    deleted = KnowledgeRepository().delete_document(document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài liệu")
    try:
        file_deleted = delete_source_file(deleted["source_key"])
    except (OSError, ValueError) as error:
        # The RAG record is already removed. Return the filesystem warning so
        # the administrator knows an orphan source file may remain.
        return {
            "success": True,
            "document": deleted,
            "file_deleted": False,
            "warning": str(error),
        }
    return {
        "success": True,
        "document": deleted,
        "file_deleted": file_deleted,
    }


@router.post("/api/upload")
async def upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    category: str = Form("customer_care"),
):
    try:
        filename = safe_filename(file.filename or "")
        job = knowledge_import_manager.create(filename, category)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(status_code=422, detail="Tài liệu không có dữ liệu")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Tài liệu vượt quá 10 MB")
    background_tasks.add_task(knowledge_import_manager.run, job.id, content)
    return job.public()


@router.get("/api/jobs/{job_id}")
def job(job_id: str):
    result = knowledge_import_manager.get(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ")
    return result
