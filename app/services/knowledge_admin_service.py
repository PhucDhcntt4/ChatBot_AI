import hashlib
import re
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from threading import RLock
from uuid import uuid4

from app.config import KNOWLEDGE_DIR, RAG_CHUNK_OVERLAP, RAG_CHUNK_SIZE
from app.database.knowledge_repository import KnowledgeRepository
from app.knowledge.chunking import TextChunk, chunk_text
from app.knowledge.embedding_service import create_text_embedding_service


CATEGORY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")
SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf"}


def delete_source_file(source_key: str) -> bool:
    """Delete only files whose resolved path stays inside knowledge/."""
    knowledge_root = KNOWLEDGE_DIR.resolve()
    source_path = (KNOWLEDGE_DIR.parent / source_key).resolve()
    if not source_path.is_relative_to(knowledge_root):
        raise ValueError("Đường dẫn tài liệu không hợp lệ")
    if not source_path.is_file():
        return False
    source_path.unlink()
    parent = source_path.parent
    if parent != knowledge_root and not any(parent.iterdir()):
        parent.rmdir()
    return True


def normalize_category(value: str) -> str:
    category = value.strip().casefold().replace(" ", "_")
    if not CATEGORY_PATTERN.fullmatch(category):
        raise ValueError("Category chỉ gồm chữ thường, số, dấu _ hoặc -")
    return category


def safe_filename(value: str) -> str:
    name = Path(value).name.strip()
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).stem).strip("._")
    suffix = Path(name).suffix.casefold()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError("Chỉ hỗ trợ tài liệu .txt, .md và .pdf")
    return f"{stem or 'document'}{suffix}"


def read_document(content: bytes, suffix: str) -> str:
    if suffix in {".txt", ".md"}:
        try:
            return content.decode("utf-8-sig").strip()
        except UnicodeDecodeError as error:
            raise ValueError("Tài liệu text phải được lưu bằng UTF-8") from error
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as error:
        raise RuntimeError("Thiếu thư viện pypdf để đọc PDF") from error
    pages = []
    for index, page in enumerate(PdfReader(BytesIO(content)).pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(f"## Trang {index}\n\n{text}")
    if not pages:
        raise ValueError("PDF không có văn bản; PDF scan cần OCR trước khi tải lên")
    return "\n\n".join(pages)


def checksum(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def embedding_text(title: str, chunk: TextChunk) -> str:
    return "\n\n".join(
        part for part in (title, chunk.heading, chunk.content) if part
    )


@dataclass
class KnowledgeJob:
    id: str
    filename: str
    category: str
    status: str = "queued"
    phase: str = "waiting"
    message: str = "Đang chờ xử lý"
    chunk_count: int = 0
    error: str | None = None

    def public(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "category": self.category,
            "status": self.status,
            "phase": self.phase,
            "message": self.message,
            "chunk_count": self.chunk_count,
            "error": self.error,
        }


class KnowledgeImportManager:
    def __init__(self) -> None:
        self._jobs: dict[str, KnowledgeJob] = {}
        self._lock = RLock()

    def create(self, filename: str, category: str) -> KnowledgeJob:
        job = KnowledgeJob(uuid4().hex, filename, normalize_category(category))
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.public() if job else None

    def run(self, job_id: str, content: bytes) -> None:
        with self._lock:
            job = self._jobs[job_id]
        try:
            job.status = "running"
            job.phase = "reading"
            job.message = "Đang đọc và chia tài liệu"
            suffix = Path(job.filename).suffix.casefold()
            text = read_document(content, suffix)
            if not text:
                raise ValueError("Tài liệu không có nội dung")
            title_match = re.search(r"^#\s+(.+?)\s*$", text, re.MULTILINE)
            title = (
                title_match.group(1).strip()
                if title_match
                else Path(job.filename).stem.replace("_", " ")
            )
            chunks = chunk_text(text, RAG_CHUNK_SIZE, RAG_CHUNK_OVERLAP)
            if not chunks:
                raise ValueError("Không tạo được chunk từ tài liệu")

            job.phase = "embedding"
            job.message = f"Đang tạo embedding cho {len(chunks)} chunk"
            embedding_service = create_text_embedding_service()
            embeddings = embedding_service.embed_documents(
                [embedding_text(title, chunk) for chunk in chunks]
            )
            stored_chunks = [
                {
                    "chunk_index": chunk.index,
                    "heading": chunk.heading,
                    "content": chunk.content,
                    "content_checksum": checksum(chunk.content),
                    "embedding": embedding,
                }
                for chunk, embedding in zip(chunks, embeddings, strict=True)
            ]

            job.phase = "database"
            job.message = "Đang lưu PostgreSQL"
            # Keep uploaded documents beside the built-in knowledge groups:
            # knowledge/{category}/{filename}. An extra "uploads" level makes
            # the category tree harder to understand and is not needed by RAG.
            category_dir = KNOWLEDGE_DIR / job.category
            category_dir.mkdir(parents=True, exist_ok=True)
            target = category_dir / job.filename
            target.write_bytes(content)
            source_key = target.relative_to(KNOWLEDGE_DIR.parent).as_posix()
            KnowledgeRepository().replace_document(
                source_key=source_key,
                title=title,
                category=job.category,
                source_checksum=checksum(text),
                embedding_provider=embedding_service.provider_name,
                embedding_model=embedding_service.model,
                embedding_dimension=embedding_service.dimension,
                metadata={"file_name": job.filename, "file_type": suffix},
                chunks=stored_chunks,
            )
            job.chunk_count = len(stored_chunks)
            job.status = "completed"
            job.phase = "completed"
            job.message = "Đã nhập tài liệu và tạo embedding"
        except Exception as error:
            job.status = "failed"
            job.phase = "failed"
            job.error = str(error)
            job.message = "Không thể nhập tài liệu"


knowledge_import_manager = KnowledgeImportManager()
