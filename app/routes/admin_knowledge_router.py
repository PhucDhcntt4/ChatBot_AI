"""Keep the bot's Knowledge UI; document data is owned exclusively by RAG Service."""
from pathlib import Path

from fastapi import APIRouter, Depends, Path as PathParam
from fastapi.responses import HTMLResponse

from app.config import RAG_SEARCH_DOC_TYPE_ID
from app.knowledge.admin_client import admin_client


router = APIRouter(prefix="/admin/knowledge", tags=["Knowledge Admin"])
PAGE_PATH = Path(__file__).resolve().parent.parent / "static" / "knowledge_admin.html"


def get_client():
    with admin_client() as client:
        yield client


@router.get("", response_class=HTMLResponse)
def page():
    return HTMLResponse(PAGE_PATH.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.get("/api/documents")
def documents(client=Depends(get_client)):
    # The bot Knowledge page manages the same document type that conversations
    # are allowed to search. A zero value intentionally means "all types".
    return client.documents(
        doc_type_id=RAG_SEARCH_DOC_TYPE_ID or None,
    )


@router.get("/api/documents/{document_id}")
def document_detail(
    document_id: str = PathParam(pattern=r"^[1-9][0-9]{0,19}$"),
    client=Depends(get_client),
):
    return client.detail(document_id)

