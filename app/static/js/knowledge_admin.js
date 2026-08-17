const $ = (id) => document.getElementById(id);
const html = (value) => {
  const el = document.createElement("div");
  el.textContent = String(value ?? "");
  return el.innerHTML;
};
async function json(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "Yêu cầu thất bại");
  return data;
}
function dateText(value) {
  return value ? new Date(value).toLocaleString("vi-VN") : "—";
}
function fileSizeText(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
function extOf(name) {
  const match = /\.([a-z0-9]+)$/i.exec(name || "");
  return match ? match[1].toUpperCase() : "?";
}

const ICON = {
  check:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
  alert:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4"/><path d="M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>',
  spinner:
    '<svg class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 3a9 9 0 1 0 9 9"/></svg>',
  trash:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>',
  empty:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M9 15h6"/><path d="M9 11h1"/></svg>',
};

let documentsCache = [];

async function loadDocuments() {
  try {
    const data = await json(await fetch("/admin/knowledge/api/documents"));
    documentsCache = data.documents;
    $("documentCount").textContent = `${data.total} tài liệu`;
    $("documentRows").innerHTML = data.documents.length
      ? data.documents
          .map(
            (
              item,
            ) => `<div class="doc-row" tabindex="0" role="button" data-document-id="${item.id}">
      <span class="ext">${html(extOf(item.title))}</span>
      <div class="row-main"><b>${html(item.title)}</b><span class="mono">${html(item.source_key)}</span></div>
      <div class="row-side">
        <span class="status-dot ${item.is_active ? "on" : "off"}">${item.is_active ? "Đang dùng" : "Tạm dừng"}</span>
        <span class="row-date">${dateText(item.updated_at)}</span>
        <button class="delete-document" type="button" data-document-id="${item.id}" data-document-title="${html(item.title)}" title="Xóa tài liệu">${ICON.trash}</button>
        <svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>
      </div>
    </div>`,
          )
          .join("")
      : `<div class="empty-row">${ICON.empty}<div class="empty-title">Chưa có tài liệu</div><div class="empty-hint">Tải lên một tệp ở bên trái để bắt đầu tạo embedding.</div></div>`;
  } catch (error) {
    $("documentRows").innerHTML =
      `<div class="empty-row">${ICON.alert}<div class="empty-title">Không tải được dữ liệu</div><div class="empty-hint">${html(error.message)}</div></div>`;
  }
}

async function deleteDocument(id, title, onDone) {
  if (
    !window.confirm(
      `Xóa "${title}"?\n\nCác chunk và embedding liên quan cũng sẽ bị xóa.`,
    )
  )
    return;
  try {
    const result = await json(
      await fetch(`/admin/knowledge/api/documents/${id}`, { method: "DELETE" }),
    );
    showNotice(
      result.warning
        ? `Đã xóa dữ liệu RAG. Cảnh báo: ${result.warning}`
        : `Đã xóa tài liệu "${title}".`,
      result.warning ? "error" : "success",
    );
    await loadDocuments();
    if (onDone) onDone();
  } catch (error) {
    showNotice(error.message, "error");
  }
}

function openDocModal(id) {
  const item = documentsCache.find((doc) => String(doc.id) === String(id));
  if (!item) return;
  $("docModalExt").textContent = extOf(item.title);
  $("docModalTitle").textContent = item.title;
  $("docModalSource").textContent = item.source_key;
  $("docModalCategory").textContent = item.category;
  $("docModalChunks").textContent = `${item.chunk_count} chunk`;
  $("docModalModel").textContent = item.embedding_model;
  const status = $("docModalStatus");
  status.textContent = item.is_active ? "Đang dùng" : "Tạm dừng";
  status.className = `status-dot ${item.is_active ? "on" : "off"}`;
  $("docModalUpdated").textContent = `Cập nhật ${dateText(item.updated_at)}`;
  $("docModalDelete").onclick = () =>
    deleteDocument(item.id, item.title, closeDocModal);
  $("docModal").hidden = false;
  loadDocContent(item.id);
}

async function loadDocContent(id) {
  const box = $("docModalContent");
  box.className = "modal-content-box";
  box.textContent = "Đang tải nội dung...";
  try {
    const data = await json(
      await fetch(`/admin/knowledge/api/documents/${id}`),
    );
    const content =
      data.content ||
      data.preview ||
      (Array.isArray(data.chunks)
        ? data.chunks.map((c) => c.content || c.text).join("\n\n")
        : "");
    if (content) {
      box.textContent = content;
    } else {
      box.className = "modal-content-box muted";
      box.textContent = "Tài liệu chưa có nội dung xem trước.";
    }
  } catch (error) {
    box.className = "modal-content-box muted";
    box.textContent = "Không tải được nội dung chi tiết.";
  }
}

function closeDocModal() {
  $("docModal").hidden = true;
}

function showNotice(message, kind = "info") {
  const el = $("jobNotice");
  const icon =
    kind === "error"
      ? ICON.alert
      : kind === "success"
        ? ICON.check
        : kind === "progress"
          ? ICON.spinner
          : "";
  el.innerHTML = `${icon}<span>${html(message)}</span>`;
  el.className = `notice show${kind === "error" ? " error" : kind === "success" ? " success" : ""}`;
}

const STEP_ORDER = ["upload", "embedding", "database"];
function renderSteps(job) {
  const wrap = $("jobSteps");
  wrap.hidden = false;
  const failedAt =
    job.status === "failed" ? Math.max(0, STEP_ORDER.indexOf(job.phase)) : -1;
  const activeIdx =
    job.status === "completed"
      ? STEP_ORDER.length
      : Math.max(0, STEP_ORDER.indexOf(job.phase));
  STEP_ORDER.forEach((key, idx) => {
    const stepEl = wrap.querySelector(`[data-step="${key}"]`);
    const dot = stepEl.querySelector(".dot");
    stepEl.classList.remove("done", "active", "failed");
    if (failedAt === idx) {
      stepEl.classList.add("failed");
      dot.innerHTML = ICON.alert;
    } else if (job.status === "failed" && idx > failedAt) {
      dot.textContent = String(idx + 1);
    } else if (idx < activeIdx || job.status === "completed") {
      stepEl.classList.add("done");
      dot.innerHTML = ICON.check;
    } else if (idx === activeIdx) {
      stepEl.classList.add("active");
      dot.innerHTML = ICON.spinner;
    } else {
      dot.textContent = String(idx + 1);
    }
  });
}

async function watchJob(id) {
  const job = await json(await fetch(`/admin/knowledge/api/jobs/${id}`));
  showNotice(
    `${job.message}${job.error ? `\n${job.error}` : ""}`,
    job.status === "failed"
      ? "error"
      : job.status === "completed"
        ? "success"
        : "progress",
  );
  renderSteps(job);
  if (["queued", "running"].includes(job.status))
    setTimeout(
      () => watchJob(id).catch((e) => showNotice(e.message, "error")),
      1200,
    );
  else {
    $("uploadButton").disabled = false;
    if (job.status === "completed") loadDocuments();
  }
}

function setSelectedFile(file) {
  const input = $("knowledgeFile");
  if (file) {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
  }
  if (input.files[0]) {
    $("fileChipName").textContent = input.files[0].name;
    $("fileChipSize").textContent = fileSizeText(input.files[0].size);
    $("fileChip").classList.add("show");
  } else {
    $("fileChip").classList.remove("show");
  }
}

$("knowledgeFile").addEventListener("change", () => setSelectedFile());
$("clearFile").addEventListener("click", (event) => {
  event.preventDefault();
  $("knowledgeFile").value = "";
  setSelectedFile();
});
["dragenter", "dragover"].forEach((evt) =>
  $("dropZone").addEventListener(evt, (event) => {
    event.preventDefault();
    $("dropZone").classList.add("dragover");
  }),
);
["dragleave", "drop"].forEach((evt) =>
  $("dropZone").addEventListener(evt, (event) => {
    event.preventDefault();
    $("dropZone").classList.remove("dragover");
  }),
);
$("dropZone").addEventListener("drop", (event) => {
  const file = event.dataTransfer.files[0];
  if (file) setSelectedFile(file);
});

$("uploadForm").onsubmit = async (event) => {
  event.preventDefault();
  const file = $("knowledgeFile").files[0];
  if (!file) return;
  const body = new FormData();
  body.append("file", file);
  body.append("category", $("knowledgeCategory").value.trim());
  $("uploadButton").disabled = true;
  showNotice("Đang tải tài liệu...", "progress");
  try {
    const job = await json(
      await fetch("/admin/knowledge/api/upload", { method: "POST", body }),
    );
    watchJob(job.id);
  } catch (error) {
    $("uploadButton").disabled = false;
    showNotice(error.message, "error");
  }
};
$("refreshDocuments").onclick = loadDocuments;
$("documentRows").addEventListener("click", (event) => {
  const deleteButton = event.target.closest(".delete-document");
  if (deleteButton) {
    event.stopPropagation();
    deleteDocument(
      deleteButton.dataset.documentId,
      deleteButton.dataset.documentTitle || "tài liệu này",
    );
    return;
  }
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
