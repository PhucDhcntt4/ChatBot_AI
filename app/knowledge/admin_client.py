"""Server-side adapter for document management; never reads/writes local Knowledge."""
import logging
import math
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
    if (not isinstance(data, dict) or type(data.get("id")) is not int
            or data["id"] <= 0 or not isinstance(data.get("title"), str)):
        raise HTTPException(502, "RAG Service trả dữ liệu tài liệu không hợp lệ")
    result = {key: data[key] for key in PUBLIC_FIELDS if key in data}
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

    def documents(self):
        documents, seen = [], set()
        # Existing UI displays all documents. Follow service pagination, never silently truncate.
        for offset in range(0, 10000, 200):
            data = self.request("GET", "api/v1/documents", params={"limit": 200, "offset": offset})
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

    def delete(self, document_id):
        data = self.request("DELETE", f"api/v1/documents/{document_id}")
        if data.get("deleted") is not True or data.get("id") != document_id:
            raise HTTPException(502, "Chưa xác nhận được kết quả xóa; hãy làm mới danh sách.")
        # Do not return remote file_storage_key or other private storage metadata.
        return {"success": True, "deleted": True, "id": document_id}

    def upload(self, filename, content, category, source_key):
        result = self.request(
            "POST", "api/v1/documents/upload",
            files={"file": (filename, content, "application/octet-stream")},
            data={"source_key": source_key, "title": filename, "category": category},
            timeout=httpx.Timeout(RAG_SERVICE_ADMIN_TIMEOUT_SECONDS, connect=5),
        )
        return {"success": True, "document": public_document(result)}


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
