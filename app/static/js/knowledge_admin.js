const $ = (id) => document.getElementById(id);
const html = (value) => {
  const element = document.createElement("div");
  element.textContent = String(value ?? "");
  return element.innerHTML;
};

async function json(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "Yêu cầu thất bại");
  return data;
}

function dateText(value) {
  return value ? new Date(value).toLocaleString("vi-VN") : "—";
}

function extOf(name) {
  const match = /\.([a-z0-9]+)$/i.exec(name || "");
  return match ? match[1].toUpperCase() : "?";
}

const CATEGORY_LABELS = new Map([
  ["store", "Cửa hàng"],
  ["size_guide", "Hướng dẫn chọn size"],
  ["warranty", "Bảo hành"],
  ["returns", "Đổi trả"],
  ["shipping", "Giao hàng"],
  ["promotion", "Khuyến mãi"],
  ["customer_care", "Chăm sóc khách hàng"],
  ["brand", "Thương hiệu"],
  ["link", "Liên kết"],
]);

const EMPTY_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M9 15h6"/><path d="M9 11h1"/></svg>';
const ALERT_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4"/><path d="M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>';

let documentsCache = [];
let activeDocumentId = null;

async function loadDocuments() {
  try {
    const data = await json(await fetch("/admin/knowledge/api/documents"));
    documentsCache = data.documents;
    $("documentCount").textContent = `${data.total} tài liệu`;
    $("documentRows").innerHTML = data.documents.length
      ? data.documents.map((item) => `<div class="doc-row" tabindex="0" role="button" data-document-id="${item.id}">
          <span class="ext">${html(extOf(item.title))}</span>
          <div class="row-main"><b>${html(item.title)}</b><span class="mono">${html(item.source_key)}</span></div>
          <div class="row-side">
            <span class="status-dot ${item.is_active ? "on" : "off"}">${item.is_active ? "Đang dùng" : "Tạm dừng"}</span>
            <span class="row-date">${dateText(item.updated_at)}</span>
            <svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>
          </div>
        </div>`).join("")
      : `<div class="empty-row">${EMPTY_ICON}<div class="empty-title">Chưa có tài liệu</div><div class="empty-hint">Hãy nhập tài liệu tại RAG Service rồi bấm Làm mới.</div></div>`;
  } catch (error) {
    documentsCache = [];
    $("documentCount").textContent = "Không tải được danh sách";
    $("documentRows").innerHTML = `<div class="empty-row">${ALERT_ICON}<div class="empty-title">Không tải được dữ liệu</div><div class="empty-hint">${html(error.message)}</div></div>`;
  }
}

function openDocModal(id) {
  const item = documentsCache.find((document) => String(document.id) === String(id));
  if (!item) return;
  activeDocumentId = String(id);
  $("docModalExt").textContent = extOf(item.title);
  $("docModalTitle").textContent = item.title;
  $("docModalSource").textContent = item.source_key;
  $("docModalCategory").textContent = CATEGORY_LABELS.get(item.category) || item.category;
  $("docModalChunks").textContent = `${item.chunk_count} chunk`;
  $("docModalModel").textContent = item.embedding_model;
  const status = $("docModalStatus");
  status.textContent = item.is_active ? "Đang dùng" : "Tạm dừng";
  status.className = `status-dot ${item.is_active ? "on" : "off"}`;
  $("docModalUpdated").textContent = `Cập nhật ${dateText(item.updated_at)}`;
  $("docModal").hidden = false;
  loadDocContent(item.id);
}

async function loadDocContent(id) {
  const box = $("docModalContent");
  box.className = "modal-content-box";
  box.textContent = "Đang tải nội dung...";
  try {
    const data = await json(await fetch(`/admin/knowledge/api/documents/${id}`));
    if (activeDocumentId !== String(id)) return;
    const content = data.content || data.source_text || data.preview ||
      (Array.isArray(data.chunks) ? data.chunks.map((chunk) => chunk.content || chunk.text).join("\n\n") : "");
    if (content) {
      box.textContent = content;
    } else {
      box.className = "modal-content-box muted";
      box.textContent = "Tài liệu chưa có nội dung xem trước.";
    }
  } catch (error) {
    if (activeDocumentId !== String(id)) return;
    box.className = "modal-content-box muted";
    box.textContent = error.message;
  }
}

function closeDocModal() {
  activeDocumentId = null;
  $("docModal").hidden = true;
}

$("refreshDocuments").onclick = loadDocuments;
$("documentRows").addEventListener("click", (event) => {
  const row = event.target.closest(".doc-row");
  if (row) openDocModal(row.dataset.documentId);
});
$("documentRows").addEventListener("keydown", (event) => {
  const row = event.target.closest(".doc-row");
  if (row && (event.key === "Enter" || event.key === " ")) {
    event.preventDefault();
    openDocModal(row.dataset.documentId);
  }
});
$("docModalClose").onclick = closeDocModal;
$("docModal").addEventListener("click", (event) => {
  if (event.target.id === "docModal") closeDocModal();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("docModal").hidden) closeDocModal();
});

loadDocuments();
