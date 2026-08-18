from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.ai.factory import create_ai_provider
from app.config import AI_PROVIDER, GOOGLE_SHEETS_ENABLED, RAG_ENABLED
from app.conversation.context import conversation_context_store
from app.conversation.executor import ConversationExecutor
from app.conversation.image_service import ProductImageConversationService
from app.conversation.models import ChatRequest, ConversationResponse, ResetRequest
from app.conversation.service import ConversationService
from app.database.product_repository import ProductRepository
from app.routes.admin_product_router import router as admin_product_router
from app.routes.admin_knowledge_router import router as admin_knowledge_router
from app.routes.admin_prompt_router import router as admin_prompt_router
from app.services.sheets_service import SheetsService


logger = logging.getLogger("uvicorn.error")
STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_knowledge_search():
    if not RAG_ENABLED:
        return None
    from app.knowledge.service import KnowledgeSearchService

    service = KnowledgeSearchService()
    logger.info(
        "RAG V2 ready provider=%s model=%s dimension=%s",
        service.embedding_service.provider_name,
        service.embedding_service.model,
        service.embedding_service.dimension,
    )
    return service.search


@asynccontextmanager
async def lifespan(app: FastAPI):
    ai = create_ai_provider()
    executor = ConversationExecutor(
        products=ProductRepository(),
        knowledge_search=create_knowledge_search(),
    )
    sheets_service = SheetsService()
    sheets_service.validate()
    app.state.conversation_service = ConversationService(
        ai,
        executor,
        sheets_service=sheets_service,
    )
    app.state.image_conversation_service = ProductImageConversationService(
        ai=ai,
        context_store=conversation_context_store,
        repository=executor.products,
    )
    logger.info("Conversation V2 ready provider=%s model=%s", ai.provider_name, ai.model)
    logger.info("Google Sheets order export enabled=%s", GOOGLE_SHEETS_ENABLED)
    yield


app = FastAPI(
    title="Đông Hải Conversation Bot V2",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(admin_product_router)
app.include_router(admin_knowledge_router)
app.include_router(admin_prompt_router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def web_chat():
    return RedirectResponse(url="/admin/products", status_code=307)


@app.get("/health")
def health(request: Request):
    service = getattr(request.app.state, "conversation_service", None)
    database = None
    database_error = None
    try:
        database = ProductRepository().health()
    except Exception as error:
        database_error = str(error)
    return {
        "status": "ok" if service else "starting",
        "ai_provider": service.ai.provider_name if service else AI_PROVIDER,
        "ai_model": service.ai.model if service else None,
        "database": database,
        "database_error": database_error,
        "rag_enabled": RAG_ENABLED,
        "google_sheets_enabled": GOOGLE_SHEETS_ENABLED,
    }


@app.post("/api/chat", response_model=ConversationResponse)
def chat(data: ChatRequest, request: Request):
    service = getattr(request.app.state, "conversation_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="AI service chưa sẵn sàng")
    try:
        return service.chat(
            message=data.message.strip(),
            session_id=data.session_id,
            channel=data.channel,
        )
    except Exception as error:
        logger.exception("Conversation V2 failed")
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.post("/api/chat/image", response_model=ConversationResponse)
async def chat_image(
    request: Request,
    image: UploadFile = File(...),
    session_id: str = Form(...),
    channel: str = Form("web"),
    caption: str = Form(""),
):
    service = getattr(request.app.state, "image_conversation_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Image AI chưa sẵn sàng")
    try:
        image_bytes = await image.read()
        return service.recognize(
            image_bytes=image_bytes,
            mime_type=(image.content_type or "application/octet-stream").casefold(),
            caption=caption,
            session_id=session_id,
            channel=channel,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        logger.exception("Conversation V2 image failed")
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.post("/api/chat/reset")
def reset(data: ResetRequest):
    conversation_context_store.reset(data.session_id, data.channel)
    return {"status": "reset"}
