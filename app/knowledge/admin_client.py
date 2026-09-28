"""Server-side adapter for document management; never reads/writes local Knowledge."""
import logging
import math
import re
from contextlib import contextmanager

import httpx
from fastapi import HTTPException

from app.config import (
    RAG_SERVICE_URL, RAG_SERVICE_ADMIN_API_KEY,
    RAG_SERVICE_TIMEOUT_SECONDS, RAG_SERVICE_ADMIN_TIMEOUT_SECONDS,
)

logger = logging.getLogger("uvicorn.error")
PUBLIC_FIELDS = (
    "id", "source_key", "title", "category", "is_active", "chunk_count",
    "embedding_provider", "embedding_model", "embedding_dimension",
    "created_at", "updated_at", "file_name", "file_size",
)


def public_document(data):
    if not isinstance(data, dict) or not isinstance(data.get("title"), str):
        raise HTTPException(502, "RAG Service trả dữ liệu tài liệu không hợp lệ")
    raw_id = data.get("id")
    document_id = str(raw_id) if type(raw_id) is int else raw_id
    if (not isinstance(document_id, str)
            or not re.fullmatch(r"[1-9][0-9]{0,19}", document_id)
            or int(document_id) > 2**64 - 1):
        raise HTTPException(502, "RAG Service trả ID tài liệu không hợp lệ")
    result = {key: data[key] for key in PUBLIC_FIELDS if key in data}
    # Keep IDs as decimal strings so browsers never round 64-bit Qdrant IDs.
    result["id"] = document_id
    if "source_text" in data:
        if not isinstance(data["source_text"], str):
            raise HTTPException(502, "Nội dung tài liệu từ RAG Service không hợp lệ")
        result["content"] = data["source_text"]
    return result


class KnowledgeAdminClient:
    def __init__(self, client: httpx.Client):
        self.client = client

    def request(self, method, path, **kwargs):
        try:
            response = self.client.request(method, path, **kwargs)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Invalid response")
            return data
        except httpx.TimeoutException:
            # Upload/delete could already have committed remotely. Never auto-retry writes.
            raise HTTPException(504, "RAG Service phản hồi quá lâu. Hãy làm mới danh sách để kiểm tra kết quả trước khi thử lại.") from None
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            logger.warning("RAG ADMIN request failed status=%s", status)
            messages = {
                401: "Key quản lý RAG không hợp lệ. Kiểm tra RAG_SERVICE_ADMIN_API_KEY.",
                403: "Key không có quyền quản lý. RAG_SERVICE_ADMIN_API_KEY phải là ADMIN_API_KEY của service.",
                404: "Không tìm thấy tài liệu trên RAG Service. Hãy làm mới danh sách.",
                413: "Tài liệu vượt giới hạn dung lượng của RAG Service.",
                422: "RAG Service không thể xử lý tài liệu. Kiểm tra định dạng, văn bản và giới hạn tài liệu.",
                429: "RAG Service đang bận. Vui lòng thử lại sau.",
            }
            raise HTTPException(status if status in {404, 413, 422, 429} else 503,
                                messages.get(status, "RAG Service tạm thời không khả dụng.")) from None
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "Không nhận được dữ liệu hợp lệ từ RAG Service.") from None

    def documents(self, *, doc_type_id: int | None = None, group_id: int | None = None):
        documents, seen = [], set()
        # Follow service pagination without losing the selected taxonomy scope.
        for offset in range(0, 10000, 200):
            params = {"limit": 200, "offset": offset}
            if doc_type_id is not None:
                params["doc_type_id"] = doc_type_id
            if group_id is not None:
                params["group_id"] = group_id
            data = self.request("GET", "api/v1/documents", params=params)
            batch = data.get("documents")
            if not isinstance(batch, list) or len(batch) > 200:
                raise HTTPException(502, "Danh sách tài liệu từ RAG Service không hợp lệ")
            for item in batch:
                document = public_document(item)
                if document["id"] not in seen:
                    documents.append(document)
                    seen.add(document["id"])
            if len(batch) < 200:
                return {"total": len(documents), "documents": documents}
        raise HTTPException(503, "Kho có quá nhiều tài liệu cho danh sách hiện tại; cần bổ sung phân trang giao diện.")

    def detail(self, document_id):
        return public_document(self.request("GET", f"api/v1/documents/{document_id}"))

    def detail_by_source_key(self, source_key):
        if not isinstance(source_key, str) or not source_key.strip():
            raise HTTPException(503, "Chưa cấu hình source_key tài liệu RAG.")
        return public_document(self.request(
            "GET",
            "api/v1/documents/by-source-key",
            params={"source_key": source_key.strip()},
        ))

    def details_by_category(self, category):
        value = str(category or "").strip().casefold()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,99}", value):
            raise HTTPException(503, "Invalid RAG document category.")

        matches = [
            document
            for document in self.documents()["documents"]
            if document.get("category") == value
            and document.get("is_active") is True
        ]
        if not matches:
            raise HTTPException(
                404,
                f"No active documents found in category {value}.",
            )

        return [self.detail(document["id"]) for document in matches]

@contextmanager
def admin_client():
    if not RAG_SERVICE_ADMIN_API_KEY:
        raise HTTPException(503, "Chưa cấu hình RAG_SERVICE_ADMIN_API_KEY trong backend bot.")
    try:
        url = httpx.URL(RAG_SERVICE_URL)
        valid = (url.scheme in {"http", "https"} and url.host
                 and not url.username and not url.password and not url.query and not url.fragment)
    except httpx.InvalidURL:
        valid = False
    if not valid or any(not math.isfinite(v) or v <= 0 for v in (
        RAG_SERVICE_TIMEOUT_SECONDS, RAG_SERVICE_ADMIN_TIMEOUT_SECONDS
    )):
        raise HTTPException(503, "Cấu hình URL/timeout của RAG Service không hợp lệ.")
    with httpx.Client(
        base_url=RAG_SERVICE_URL.rstrip("/") + "/",
        headers={"Authorization": f"Bearer {RAG_SERVICE_ADMIN_API_KEY}"},
        timeout=httpx.Timeout(RAG_SERVICE_TIMEOUT_SECONDS, connect=5),
        follow_redirects=False,
    ) as client:
        yield KnowledgeAdminClient(client)
