from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.config import PROMPT_DIR
from app.conversation.cta import CTA_TEMPLATES, parse_cta_templates


router = APIRouter(prefix="/admin/prompts", tags=["Prompt Admin"])
PAGE_PATH = Path(__file__).resolve().parent.parent / "static" / "prompt_admin.html"
VERSIONS_DIR = PROMPT_DIR / ".versions"
PROMPT_FILES = {
    "conversation_planner.txt": "Planner hội thoại",
    "conversation_presenter.txt": "Presenter hội thoại",
    "image_intent.txt": "Phân loại ảnh",
    "product_recognition.txt": "Xác minh sản phẩm",
    "product_reply.txt": "Trả lời nhận diện ảnh",
    "cta_templates.txt": "Câu CTA",
}


class PromptUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)


def _path(name: str) -> Path:
    if name not in PROMPT_FILES:
        raise HTTPException(status_code=404, detail="Prompt không được phép chỉnh sửa")
    return PROMPT_DIR / name


def _validate(name: str, content: str) -> None:
    if not content.strip():
        raise ValueError("Nội dung prompt không được để trống")
    if name == "cta_templates.txt":
        parse_cta_templates(content, name)


def _apply_runtime(request: Request, name: str, content: str) -> None:
    conversation = getattr(request.app.state, "conversation_service", None)
    image_service = getattr(request.app.state, "image_conversation_service", None)
    if name == "conversation_planner.txt" and conversation:
        conversation.ai.planner_prompt = content
    elif name == "conversation_presenter.txt" and conversation:
        conversation.ai.presenter_prompt = content
    elif name == "image_intent.txt" and image_service:
        image_service.intent_service.prompt = content
    elif name == "product_recognition.txt" and image_service:
        image_service.handler.recognition.prompt = content
    elif name == "product_reply.txt" and image_service:
        image_service.handler.reply_prompt = content
    elif name == "cta_templates.txt":
        parsed = parse_cta_templates(content, name)
        CTA_TEMPLATES.clear()
        CTA_TEMPLATES.update(parsed)


@router.get("", response_class=HTMLResponse)
def page():
    return HTMLResponse(
        PAGE_PATH.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/files")
def files():
    items = []
    for name, label in PROMPT_FILES.items():
        path = PROMPT_DIR / name
        stat = path.stat()
        items.append({
            "name": name,
            "label": label,
            "size": stat.st_size,
            "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return {"files": items}


@router.get("/api/files/{name}")
def file_content(name: str):
    path = _path(name)
    return {
        "name": name,
        "label": PROMPT_FILES[name],
        "content": path.read_text(encoding="utf-8"),
    }


@router.put("/api/files/{name}")
def save_prompt(name: str, data: PromptUpdate, request: Request):
    path = _path(name)
    content = data.content.replace("\r\n", "\n").replace("\r", "\n")
    try:
        _validate(name, content)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    previous = path.read_text(encoding="utf-8")
    version_dir = VERSIONS_DIR / name
    version_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    (version_dir / f"{timestamp}.txt").write_text(previous, encoding="utf-8")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
    _apply_runtime(request, name, content)
    return {
        "status": "saved",
        "name": name,
        "applied": True,
        "updated_at": datetime.now().isoformat(),
    }
