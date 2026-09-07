from contextlib import asynccontextmanager
import logging
import math
import httpx # type: ignore
from pathlib import Path
from time import perf_counter
from uuid import uuid4
from app.knowledge.remote import RemoteKnowledgeSearch
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile # type: ignore
from fastapi.responses import RedirectResponse# type: ignore
from fastapi.staticfiles import StaticFiles# type: ignore

from app.ai.factory import create_ai_provider
from app.channels import ChannelDispatcher, IncomingChannelMessage
from app.channels.factory import create_channel_providers
from app.config import (
    AI_PROVIDER,
    CHANNEL_PROVIDERS,
    FACEBOOK_CHAT_CHANNEL,
    GOOGLE_SHEETS_ENABLED,
    RAG_ENABLED,
    TELEGRAM_CHAT_CHANNEL,
    WEB_CHAT_CHANNEL,
    RAG_SERVICE_URL,
    RAG_SERVICE_API_KEY,
    RAG_SERVICE_TIMEOUT_SECONDS,
)
from app.conversation.context import conversation_context_store
from app.conversation.executor import ConversationExecutor
from app.conversation.image_service import ProductImageConversationService
from app.conversation.models import ChatRequest, ConversationResponse, ResetRequest
from app.conversation.service import ConversationService
from app.database.product_repository import ProductRepository
from app.logging_config import log_bot_response, setup_logging
from app.middleware import AdminAuthMiddleware
from app.routes.admin_auth_router import router as admin_auth_router
from app.routes.admin_user_router import router as admin_user_router
from app.routes.admin_environment_router import router as admin_environment_router
from app.routes.admin_product_router import router as admin_product_router
from app.routes.admin_knowledge_router import router as admin_knowledge_router
from app.routes.admin_prompt_router import router as admin_prompt_router
from app.routes.admin_conversation_router import router as admin_conversation_router
from app.routes.telegram_router import router as telegram_router
from app.routes.facebook_router import router as facebook_router
from app.services.conversation_history_service import ConversationHistoryService
from app.services.admin_auth_service import admin_auth_service
from app.services.sheets_service import SheetsService
from  app.services.human_mode_service import HumanModeService


logger = logging.getLogger("uvicorn.error")
STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_knowledge_search():
    if not RAG_ENABLED:
        return None

    if not RAG_SERVICE_URL or not RAG_SERVICE_API_KEY:
        raise RuntimeError(
            "Thiếu RAG_SERVICE_URL hoặc RAG_SERVICE_API_KEY trong .env"
        )

    if (
        not math.isfinite(RAG_SERVICE_TIMEOUT_SECONDS)
        or RAG_SERVICE_TIMEOUT_SECONDS <= 0
    ):
        raise RuntimeError(
            "RAG_SERVICE_TIMEOUT_SECONDS phải là số dương hữu hạn"
        )

    service_url = httpx.URL(RAG_SERVICE_URL)
    if service_url.scheme not in {"http", "https"} or not service_url.host:
        raise RuntimeError(
            "RAG_SERVICE_URL phải là địa chỉ HTTP hoặc HTTPS hợp lệ"
        )

    logger.info(
        "RAG backend=remote configured timeout=%.1fs",
        RAG_SERVICE_TIMEOUT_SECONDS,
    )

    def search(question, *, categories=None):
        started = perf_counter()
        remote = None

        try:
            remote = RemoteKnowledgeSearch(
                base_url=RAG_SERVICE_URL,
                api_key=RAG_SERVICE_API_KEY,
                timeout=RAG_SERVICE_TIMEOUT_SECONDS,
            )

            result = remote.search(
                question,
                categories=categories,
            )

            logger.info(
                "RAG REMOTE status=%s sources=%s time=%.3fs",
                result.get("status"),
                len(result.get("sources") or []),
                perf_counter() - started,
            )

            return result

        except (httpx.HTTPError, ValueError) as error:
            response = getattr(error, "response", None)

            logger.warning(
                "RAG REMOTE status=unavailable error=%s "
                "http_status=%s time=%.3fs",
                type(error).__name__,
                getattr(response, "status_code", None),
                perf_counter() - started,
            )

            return {
                "success": False,
                "status": "knowledge_service_unavailable",
                "content": "",
                "sources": [],
            }

        finally:
            if remote is not None:
                remote.close()

    return search

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Configure rotating application logs only when the real ASGI lifespan
    # starts. Importing app.main in unit tests must not pollute production logs.
    setup_logging(service_name="app")
    admin_auth_service.validate()
    logger.info(
        "Admin authentication enabled=%s cookie_secure=%s",
        admin_auth_service.enabled,
        admin_auth_service.cookie_secure,
    )
    ai = create_ai_provider()
    executor = ConversationExecutor(
        products=ProductRepository(),
        knowledge_search=create_knowledge_search(),
    )
    sheets_service = SheetsService()
    sheets_service.validate()
    conversation_service = ConversationService(
        ai,
        executor,
        sheets_service=sheets_service,
    )
    image_conversation_service = ProductImageConversationService(
        ai=ai,
        context_store=conversation_context_store,
        repository=executor.products,
    )
    human_mode_service = HumanModeService()
    conversation_history_service = ConversationHistoryService()
    app.state.conversation_service = conversation_service
    app.state.image_conversation_service = image_conversation_service
    app.state.conversation_history_service = conversation_history_service
    app.state.human_mode_service = human_mode_service
    app.state.admin_auth_service = admin_auth_service
    app.state.admin_user_repository = admin_auth_service.repository
    app.state.channel_dispatcher = ChannelDispatcher(
        conversation_service,
        image_conversation_service,
        conversation_history_service,
        human_mode_service=human_mode_service,
    )
    app.state.channel_providers = create_channel_providers()
    if TELEGRAM_CHAT_CHANNEL in app.state.channel_providers:
        logger.info(
            "Telegram ready channel=%s webhook=/api/telegram/webhook",
            TELEGRAM_CHAT_CHANNEL,
        )
    if FACEBOOK_CHAT_CHANNEL in app.state.channel_providers:
        logger.info(
            "Facebook ready channel=%s webhook=/webhook/facebook",
            FACEBOOK_CHAT_CHANNEL,
        )
    logger.info("Conversation V2 ready provider=%s model=%s", ai.provider_name, ai.model)
    logger.info("Google Sheets order export enabled=%s", GOOGLE_SHEETS_ENABLED)
    yield


app = FastAPI(
    title="Đông Hải Conversation Bot V2",
    version="1.0.0",
    lifespan=lifespan,
)
app.state.runtime_id = uuid4().hex
app.state.admin_auth_service = admin_auth_service
app.state.admin_user_repository = admin_auth_service.repository
app.add_middleware(AdminAuthMiddleware, auth_service=admin_auth_service)
app.include_router(admin_auth_router)
app.include_router(admin_user_router)
app.include_router(admin_environment_router)
app.include_router(admin_product_router)
app.include_router(admin_knowledge_router)
app.include_router(admin_prompt_router)
app.include_router(admin_conversation_router)
app.include_router(telegram_router)
app.include_router(facebook_router)
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
        "runtime_id": request.app.state.runtime_id,
        "ai_provider": service.ai.provider_name if service else AI_PROVIDER,
        "ai_model": service.ai.model if service else None,
        "database": database,
        "database_error": database_error,
        "rag_enabled": RAG_ENABLED,
        "google_sheets_enabled": GOOGLE_SHEETS_ENABLED,
        "channels": {
            WEB_CHAT_CHANNEL: WEB_CHAT_CHANNEL in CHANNEL_PROVIDERS,
            TELEGRAM_CHAT_CHANNEL: TELEGRAM_CHAT_CHANNEL
            in getattr(request.app.state, "channel_providers", {}),
            FACEBOOK_CHAT_CHANNEL: FACEBOOK_CHAT_CHANNEL
            in getattr(request.app.state, "channel_providers", {}),
        },
    }


@app.post("/api/chat", response_model=ConversationResponse)
def chat(data: ChatRequest, request: Request):
    started = perf_counter()
    dispatcher = getattr(request.app.state, "channel_dispatcher", None)
    if WEB_CHAT_CHANNEL not in CHANNEL_PROVIDERS:
        raise HTTPException(status_code=503, detail="Kênh web chưa được bật.")
    if dispatcher is None:
        raise HTTPException(status_code=503, detail="AI service chưa sẵn sàng")
    try:
        response, history_message_id = dispatcher.dispatch_with_history(IncomingChannelMessage(
            channel=WEB_CHAT_CHANNEL,
            user_id=data.session_id,
            text=data.message.strip(),
        ))
        history_service = getattr(
            request.app.state,
            "conversation_history_service",
            None,
        )
        if history_service is not None:
            history_service.mark_sent(history_message_id)
        log_bot_response(
            logger,
            channel=WEB_CHAT_CHANNEL,
            session_id=data.session_id,
            response=response,
            total_seconds=perf_counter() - started,
        )
        return response
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
    started = perf_counter()
    dispatcher = getattr(request.app.state, "channel_dispatcher", None)
    if WEB_CHAT_CHANNEL not in CHANNEL_PROVIDERS:
        raise HTTPException(status_code=503, detail="Kênh web chưa được bật.")
    if dispatcher is None:
        raise HTTPException(status_code=503, detail="Image AI chưa sẵn sàng")
    try:
        image_bytes = await image.read()
        response, history_message_id = dispatcher.dispatch_with_history(IncomingChannelMessage(
            channel=WEB_CHAT_CHANNEL,
            user_id=session_id,
            text=caption,
            image_bytes=image_bytes,
            mime_type=(image.content_type or "application/octet-stream").casefold(),
            media_metadata=[{
                "filename": image.filename,
                "content_type": image.content_type,
            }],
        ))
        history_service = getattr(
            request.app.state,
            "conversation_history_service",
            None,
        )
        if history_service is not None:
            history_service.mark_sent(history_message_id)
        log_bot_response(
            logger,
            channel=WEB_CHAT_CHANNEL,
            session_id=session_id,
            response=response,
            total_seconds=perf_counter() - started,
        )
        return response
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        logger.exception("Conversation V2 image failed")
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.post("/api/chat/reset")
def reset(data: ResetRequest, request: Request):
    dispatcher = getattr(request.app.state, "channel_dispatcher", None)
    if dispatcher is None:
        raise HTTPException(status_code=503, detail="AI service chưa sẵn sàng")
    dispatcher.reset(WEB_CHAT_CHANNEL, data.session_id)
    return {"status": "reset"}
