const logState = { offset: 0, limit: 200, total: 0, loading: false };
const logElement = (id) => document.getElementById(id);

async function logApi(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || "Không thể tải lịch sử hệ thống.");
  }
  return data;
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function showLogNotice(message, error = false) {
  const notice = logElement("logNotice");
  notice.textContent = message;
  notice.className = `notice show${error ? " error" : ""}`;
}

function clearLogNotice() {
  const notice = logElement("logNotice");
  notice.textContent = "";
  notice.className = "notice";
}

function createLogEntry(entry) {
  const article = document.createElement("article");
  article.className = "log-entry";

  const head = document.createElement("header");
  head.className = "log-entry-head";
  const level = document.createElement("span");
  const levelName = entry.level || "LOG";
  level.className = `log-level ${levelName.toLowerCase()}`;
  level.textContent = levelName;
  const time = document.createElement("time");
  time.className = "log-entry-time";
  time.textContent = entry.timestamp || "Không có thời gian";
  const logger = document.createElement("span");
  logger.className = "log-context";
  logger.textContent = entry.logger || "system";
  const file = document.createElement("span");
  file.className = "log-entry-file";
  file.textContent = entry.file || "";
  head.append(level, time, logger, file);

  const message = document.createElement("pre");
  message.className = "log-entry-body";
  message.textContent = entry.context
    ? `${entry.context}\n${entry.message || ""}`
    : entry.message || "";
  article.append(head, message);
  return article;
}

function renderLogs(data) {
  const list = logElement("logList");
  list.replaceChildren();
  for (const entry of data.entries || []) list.appendChild(createLogEntry(entry));

  logState.total = Number(data.total || 0);
  const count = (data.entries || []).length;
  const first = count ? data.offset + 1 : 0;
  const last = data.offset + count;
  logElement("logSummary").textContent =
    `${logState.total.toLocaleString("vi-VN")} bản ghi · đang hiển thị ${first}–${last}`;
  logElement("logEmpty").hidden = count > 0;
  logElement("logTruncated").hidden = !data.truncated;
  logElement("previousLogs").disabled = data.offset <= 0;
  logElement("nextLogs").disabled = !data.has_more;
  logElement("logPage").textContent =
    `Trang ${Math.floor(data.offset / data.limit) + 1} / ${Math.max(1, Math.ceil(logState.total / data.limit))}`;
}

function currentLogQuery() {
  const params = new URLSearchParams({
    file: logElement("logFile").value,
    level: logElement("logLevel").value,
    search: logElement("logSearch").value.trim(),
    offset: String(logState.offset),
    limit: String(logState.limit),
  });
  return params.toString();
}

async function loadLogs(reset = false) {
  if (logState.loading) return;
  if (reset) logState.offset = 0;
  logState.loading = true;
  logElement("refreshLogs").disabled = true;
  clearLogNotice();
  try {
    const data = await logApi(`/admin/system-logs/api/entries?${currentLogQuery()}`);
    renderLogs(data);
  } catch (error) {
    showLogNotice(error.message, true);
  } finally {
    logState.loading = false;
    logElement("refreshLogs").disabled = false;
  }
}

async function loadLogFiles() {
  const data = await logApi("/admin/system-logs/api/files");
  const select = logElement("logFile");
  const current = select.value;
  select.replaceChildren(new Option("Tất cả file log", "__all__"));
  for (const file of data.files || []) {
    const updated = new Date(file.updated_at).toLocaleString("vi-VN");
    select.appendChild(new Option(
      `${file.name} · ${formatBytes(file.size)} · ${updated}`,
      file.name,
    ));
  }
  if ([...select.options].some((option) => option.value === current)) {
    select.value = current;
  }
}

let searchTimer;
logElement("logSearch").addEventListener("input", () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => loadLogs(true), 350);
});
logElement("logFile").addEventListener("change", () => loadLogs(true));
logElement("logLevel").addEventListener("change", () => loadLogs(true));
logElement("refreshLogs").addEventListener("click", async () => {
  try {
    await loadLogFiles();
    await loadLogs(true);
  } catch (error) {
    showLogNotice(error.message, true);
  }
});
logElement("clearLogs").addEventListener("click", async () => {
  if (logState.loading) return;
  const file = logElement("logFile").value;
  const scope = file === "__all__" ? "toàn bộ file log" : `file ${file}`;
  if (!window.confirm(
    `Bạn chắc chắn muốn xóa nội dung ${scope}?\n\nHành động này không thể hoàn tác. File log vẫn được giữ lại để hệ thống tiếp tục ghi.`
  )) return;

  const button = logElement("clearLogs");
  button.disabled = true;
  try {
    const params = new URLSearchParams({ file });
    const result = await logApi(`/admin/system-logs/api/entries?${params}`, {
      method: "DELETE",
    });
    await loadLogFiles();
    await loadLogs(true);
    showLogNotice(
      `Đã giải phóng ${result.file_count} file, dung lượng ${formatBytes(result.cleared_bytes)}. Các bản ghi mới vẫn tiếp tục được ghi.`
    );
  } catch (error) {
    showLogNotice(error.message, true);
  } finally {
    button.disabled = false;
  }
});
logElement("previousLogs").addEventListener("click", () => {
  logState.offset = Math.max(0, logState.offset - logState.limit);
  loadLogs();
});
logElement("nextLogs").addEventListener("click", () => {
  if (logState.offset + logState.limit >= logState.total) return;
  logState.offset += logState.limit;
  loadLogs();
});

(async () => {
  try {
    await loadLogFiles();
    await loadLogs(true);
  } catch (error) {
    showLogNotice(error.message, true);
  }
})();
