const $ = (id) => document.getElementById(id);
const PAGE_SIZE = 20;
let offset = 0,
  total = 0,
  activeSession = null,
  searchTimer = null;
let activeHumanMode = false;
let humanModeBusy = false;
let activeHumanModeRemaining = null;
let globalAllPaused = false;
let globalPausedCount = 0;
let globalRemaining = null;
let globalHumanModeBusy = false;
let durationBusy = false;
let savedHumanModeDuration = 600;
let activeCache = false;
let pendingCacheClear = null;
let cacheClearBusy = false;
const CLEAR_CACHE_ICON =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>';
const EMPTY_ICON =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M8 12h8"/><path d="M8 16h5"/><rect x="3" y="5" width="18" height="15" rx="3"/></svg>';
const CHANNEL_LABEL = {
  web: "Web",
  telegram: "Telegram",
  facebook: "Facebook",
};

async function responseJson(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "Không thể xử lý yêu cầu");
  return data;
}
function escapeHtml(value) {
  const node = document.createElement("div");
  node.textContent = value == null ? "" : String(value);
  return node.innerHTML;
}
function ttlLabel(seconds) {
  if (seconds == null) return "Không hết hạn";
  if (seconds < 60) return `${seconds} giây`;
  if (seconds < 3600) return `${Math.ceil(seconds / 60)} phút`;
  if (seconds < 86400) return `${Math.ceil(seconds / 3600)} giờ`;
  return `${Math.ceil(seconds / 86400)} ngày`;
}
function countdownLabel(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const secs = value % 60;
  if (hours) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}
function ensureDurationOption(seconds) {
  const select = $("humanModeDuration");
  const value = String(seconds);
  if (![...select.options].some((option) => option.value === value)) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = ttlLabel(seconds);
    select.appendChild(option);
  }
  select.value = value;
}
function stageLabel(stage) {
  return (
    {
      browsing: "Đang xem",
      collecting_product: "Chọn sản phẩm",
      collecting_contact: "Nhập liên hệ",
      awaiting_final_confirmation: "Chờ xác nhận",
      confirmed: "Đã xác nhận",
      cancelled: "Đã hủy",
      archived: "Đã lưu",
    }[stage] || stage
  );
}
function notice(message, error = false) {
  const element = $("sessionNotice");
  element.textContent = message;
  element.className = `notice show${error ? " error" : " success"}`;
  window.setTimeout(() => element.classList.remove("show"), 3500);
}
function renderRows(items) {
  if (!items.length) {
    $("sessionRows").innerHTML =
      `<tr class="empty-row"><td colspan="7">${EMPTY_ICON}<div class="empty-title">Chưa có hội thoại</div><div class="empty-hint">Hãy kiểm tra bộ lọc hoặc chờ người dùng nhắn tin.</div></td></tr>`;
    return;
  }
  $("sessionRows").innerHTML = items
    .map((item) => {
      const isHuman = Boolean(item.human_mode);
      const botEnabled = !isHuman;
      const remaining = isHuman
        ? Math.max(0, Number(item.human_mode_remaining_seconds) || 0)
        : 0;
      return `
    <tr class="session-row" data-channel="${escapeHtml(item.channel)}" data-session="${escapeHtml(item.session_id)}" data-human="${isHuman ? "1" : "0"}" data-human-remaining="${remaining}">
      <td><b>${escapeHtml(item.session_id)}</b><small>${escapeHtml(item.last_message || "Chưa có tin nhắn")}</small></td>
      <td><span class="badge channel-${escapeHtml(item.channel)}">${escapeHtml(CHANNEL_LABEL[item.channel] || item.channel)}</span></td>
      <td>${escapeHtml(item.customer_name || "—")}<small>${escapeHtml(item.customer_phone || "")}</small></td>
      <td><span class="pill stage-pill stage-${escapeHtml(item.sales_stage)}">${escapeHtml(stageLabel(item.sales_stage))}</span>${item.latest_product_code ? `<small>${escapeHtml(item.latest_product_code)}</small>` : ""}</td>
      <td class="num">${item.message_count}</td>
      <td><span class="ttl-pill">${item.cache_active ? escapeHtml(ttlLabel(item.ttl_seconds)) : "Đã lưu"}</span></td>
      <td>
        <div class="row-actions">
          <button class="mode-switch${botEnabled ? " on" : ""}" type="button" role="switch" aria-checked="${botEnabled}" title="${botEnabled ? "Bot đang bật — bấm để chuyển nhân viên" : "Bot đang tắt — bấm để bật lại bot"}">
            <span class="track"><span class="thumb"></span></span><span class="switch-label">${botEnabled ? "Bật" : `Tắt · ${countdownLabel(remaining)}`}</span>
          </button>
          <button class="delete-session row-clear-cache icon-only${item.cache_active ? "" : " is-empty"}" type="button" title="${item.cache_active ? "Xóa cache Redis, giữ lịch sử PostgreSQL" : "Cache Redis đã được xóa"}" aria-label="${item.cache_active ? "Xóa cache Redis" : "Cache Redis đã được xóa"}" ${item.cache_active ? "" : "disabled"}>${CLEAR_CACHE_ICON}</button>
        </div>
      </td>
    </tr>`;
    })
    .join("");
}
async function loadSessions() {
  const params = new URLSearchParams({ limit: PAGE_SIZE, offset });
  const channel = $("channelFilter").value,
    search = $("sessionSearch").value.trim();
  if (channel) params.set("channel", channel);
  if (search) params.set("search", search);
  const [data, globalStatus] = await Promise.all([
    responseJson(await fetch(`/admin/conversations/api/sessions?${params}`)),
    responseJson(await fetch("/admin/conversations/api/human-mode")),
  ]);
  globalAllPaused = Boolean(globalStatus.all_paused);
  globalPausedCount = Number(globalStatus.paused) || 0;
  globalRemaining = globalAllPaused
    ? Number(globalStatus.remaining_seconds) || 0
    : null;
  const configuredDuration = Number(globalStatus.default_ttl_seconds);
  if (configuredDuration >= 60) {
    savedHumanModeDuration = configuredDuration;
    ensureDurationOption(configuredDuration);
  }
  renderGlobalHumanMode();
  total = data.total;
  if (offset && offset >= total) {
    offset = Math.max(
      0,
      Math.floor((Math.max(total, 1) - 1) / PAGE_SIZE) * PAGE_SIZE,
    );
    return loadSessions();
  }
  renderRows(data.sessions);
  const start = total ? offset + 1 : 0,
    end = Math.min(offset + PAGE_SIZE, total);
  $("sessionSummary").textContent =
    `${total} hội thoại · đang hiển thị ${start}–${end}`;
  $("pageLabel").textContent =
    `Trang ${Math.floor(offset / PAGE_SIZE) + 1} / ${Math.max(1, Math.ceil(total / PAGE_SIZE))}`;
  $("previousPage").disabled = offset === 0;
  $("nextPage").disabled = offset + PAGE_SIZE >= total;
}
function renderGlobalHumanMode() {
  const button = $("toggleGlobalHumanMode");
  const botEnabled = !globalAllPaused;
  button.classList.toggle("is-on", botEnabled);
  button.setAttribute("aria-checked", String(botEnabled));
  button.disabled = globalHumanModeBusy;
  $("humanModeDuration").disabled = globalHumanModeBusy || durationBusy;
  const state = $("globalBotState");
  if (globalAllPaused) {
    state.textContent = `Đang tắt · Tự bật lại sau ${countdownLabel(globalRemaining)}`;
    state.classList.add("is-off");
  } else if (globalPausedCount) {
    state.textContent = `${globalPausedCount} hội thoại đang do nhân viên xử lý`;
    state.classList.add("is-off");
  } else {
    state.textContent = "Đang bật cho toàn bộ hội thoại";
    state.classList.remove("is-off");
  }
}
async function toggleGlobalHumanMode({ renew = false } = {}) {
  if (globalHumanModeBusy) return;
  const shouldEnableHuman = renew || !globalAllPaused;
  globalHumanModeBusy = true;
  renderGlobalHumanMode();
  try {
    const response = await responseJson(
      await fetch("/admin/conversations/api/human-mode", {
        method: shouldEnableHuman ? "POST" : "DELETE",
        headers: shouldEnableHuman
          ? { "Content-Type": "application/json" }
          : undefined,
        body: shouldEnableHuman
          ? JSON.stringify({
              ttl_seconds: Number($("humanModeDuration").value),
            })
          : undefined,
      }),
    );
    globalAllPaused = shouldEnableHuman && response.paused > 0;
    globalPausedCount = shouldEnableHuman ? response.paused : 0;
    globalRemaining = shouldEnableHuman
      ? Number(response.remaining_seconds) || 0
      : null;
    notice(
      shouldEnableHuman
        ? `Đã tạm dừng bot cho ${response.paused} hội thoại.`
        : `Đã bật lại bot cho ${response.resumed} hội thoại.`,
    );
    await loadSessions();
  } finally {
    globalHumanModeBusy = false;
    renderGlobalHumanMode();
  }
}
async function openSession(channel, sessionId) {
  const baseUrl = `/admin/conversations/api/sessions/${encodeURIComponent(channel)}/${encodeURIComponent(sessionId)}`;
  const [item, humanMode] = await Promise.all([
    responseJson(await fetch(baseUrl)),
    responseJson(await fetch(`${baseUrl}/human-mode`)),
  ]);
  activeSession = { channel, sessionId };
  activeCache = Boolean(item.cache_active);
  activeHumanMode = Boolean(humanMode.enabled);
  activeHumanModeRemaining = activeHumanMode
    ? Math.max(0, Number(humanMode.details?.remaining_seconds) || 0)
    : null;
  $("conversationTitle").textContent =
    item.customer_name || "Chi tiết hội thoại";
  $("conversationMeta").textContent = `${channel} · ${sessionId}`;
  $("conversationBadges").innerHTML =
    `<span class="pill">${escapeHtml(stageLabel(item.sales_stage))}</span><span class="pill">${item.message_count} tin nhắn</span>${item.latest_product_code ? `<span class="pill">${escapeHtml(item.latest_product_code)}</span>` : ""}<span class="pill ${activeHumanMode ? "human-active" : "bot-active"}" id="humanModeBadge">${activeHumanMode ? "Nhân viên đang xử lý" : "Bot đang trả lời"}</span>`;
  const history = item.context.history || [];
  $("conversationHistory").innerHTML = history.length
    ? history
        .map(
          (message) =>
            `<div class="history-message ${message.role}"><span>${message.role === "user" ? "Khách hàng" : "Trợ lý"}</span><p>${escapeHtml(message.text)}</p></div>`,
        )
        .join("")
    : '<div class="empty-history">Hội thoại chưa có tin nhắn.</div>';
  $("conversationFooter").textContent =
    activeCache
      ? `Cache Redis còn lại: ${ttlLabel(item.ttl_seconds)}`
      : "Cache đã được giải phóng · lịch sử PostgreSQL vẫn được lưu";
  const clearCacheButton = $("clearCurrentCache");
  if (clearCacheButton) clearCacheButton.hidden = !activeCache;
  renderHumanModeButton();
  $("conversationModal").hidden = false;
  document.body.style.overflow = "hidden";
}
function renderHumanModeButton() {
  const button = $("toggleHumanMode");
  const botEnabled = !activeHumanMode;
  button.classList.toggle("is-on", botEnabled);
  button.setAttribute("aria-checked", String(botEnabled));
  button.title = botEnabled
    ? "Bot đang bật — bấm để chuyển nhân viên xử lý"
    : "Bot đang tắt — bấm để bật lại bot";
  button.disabled = humanModeBusy;
  const state = $("humanModeState");
  state.textContent = botEnabled
    ? "Đang bật"
    : `Tự bật lại sau ${countdownLabel(activeHumanModeRemaining)}`;
  state.classList.toggle("is-off", !botEnabled);
  $("humanModeDuration").disabled =
    humanModeBusy || globalHumanModeBusy || durationBusy;
}
function syncRowHumanMode(channel, sessionId, isHuman, remainingSeconds = null) {
  const row = document.querySelector(
    `.session-row[data-channel="${CSS.escape(channel)}"][data-session="${CSS.escape(sessionId)}"]`,
  );
  if (!row) return;
  row.dataset.human = isHuman ? "1" : "0";
  row.dataset.humanRemaining = isHuman
    ? String(Math.max(0, Number(remainingSeconds) || 0))
    : "0";
  const button = row.querySelector(".mode-switch");
  if (!button) return;
  const botEnabled = !isHuman;
  button.classList.toggle("on", botEnabled);
  button.setAttribute("aria-checked", String(botEnabled));
  button.title = botEnabled
    ? "Bot đang bật — bấm để chuyển nhân viên"
    : "Bot đang tắt — bấm để bật lại bot";
  button.querySelector(".switch-label").textContent = botEnabled
    ? "Bật"
    : `Tắt · ${countdownLabel(row.dataset.humanRemaining)}`;
}
async function toggleRowHumanMode(row, button) {
  const channel = row.dataset.channel,
    sessionId = row.dataset.session;
  const isHuman = row.dataset.human === "1";
  const url = `/admin/conversations/api/sessions/${encodeURIComponent(channel)}/${encodeURIComponent(sessionId)}/human-mode`;
  button.disabled = true;
  try {
    const response = await responseJson(
      await fetch(url, {
        method: isHuman ? "DELETE" : "POST",
        headers: isHuman ? undefined : { "Content-Type": "application/json" },
        body: isHuman
          ? undefined
          : JSON.stringify({ ttl_seconds: Number($("humanModeDuration").value) }),
      }),
    );
    const next = !isHuman;
    const remaining = response.details?.remaining_seconds ?? null;
    syncRowHumanMode(channel, sessionId, next, remaining);
    if (
      activeSession &&
      activeSession.channel === channel &&
      activeSession.sessionId === sessionId
    ) {
      activeHumanMode = next;
      activeHumanModeRemaining = next ? remaining : null;
      const badge = $("humanModeBadge");
      if (badge) {
        badge.textContent = next ? "Nhân viên đang xử lý" : "Bot đang trả lời";
        badge.className = `pill ${next ? "human-active" : "bot-active"}`;
      }
      renderHumanModeButton();
    }
    notice(
      next
        ? "Đã chuyển hội thoại cho nhân viên."
        : "Đã bật lại bot cho hội thoại.",
    );
  } finally {
    button.disabled = false;
  }
}
async function toggleHumanMode() {
  if (!activeSession || humanModeBusy) return;
  const { channel, sessionId } = activeSession;
  const url = `/admin/conversations/api/sessions/${encodeURIComponent(channel)}/${encodeURIComponent(sessionId)}/human-mode`;
  humanModeBusy = true;
  renderHumanModeButton();
  try {
    const response = await responseJson(
      await fetch(url, {
        method: activeHumanMode ? "DELETE" : "POST",
        headers: activeHumanMode
          ? undefined
          : { "Content-Type": "application/json" },
        body: activeHumanMode
          ? undefined
          : JSON.stringify({
              ttl_seconds: Number($("humanModeDuration").value),
            }),
      }),
    );
    activeHumanMode = !activeHumanMode;
    activeHumanModeRemaining = activeHumanMode
      ? response.details?.remaining_seconds ?? null
      : null;
    const badge = $("humanModeBadge");
    if (badge) {
      badge.textContent = activeHumanMode
        ? "Nhân viên đang xử lý"
        : "Bot đang trả lời";
      badge.className = `pill ${activeHumanMode ? "human-active" : "bot-active"}`;
    }
    syncRowHumanMode(
      channel,
      sessionId,
      activeHumanMode,
      activeHumanModeRemaining,
    );
    notice(
      activeHumanMode
        ? "Đã tắt bot và chuyển hội thoại cho nhân viên."
        : "Đã bật lại bot cho hội thoại.",
    );
  } finally {
    humanModeBusy = false;
    renderHumanModeButton();
  }
}
async function updateHumanModeDuration() {
  if (durationBusy) return;
  const selectedDuration = Number($("humanModeDuration").value);
  durationBusy = true;
  renderGlobalHumanMode();
  try {
    const response = await responseJson(
      await fetch("/admin/conversations/api/human-mode/duration", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ttl_seconds: selectedDuration,
        }),
      }),
    );
    savedHumanModeDuration = Number(response.default_ttl_seconds);
    if (globalAllPaused && response.remaining_seconds != null) {
      globalRemaining = Number(response.remaining_seconds);
    }
    const renewed = Number(response.renewed) || 0;
    notice(
      `Đã đổi thời gian tạm dừng bot thành ${ttlLabel(savedHumanModeDuration)}` +
        (renewed ? ` và gia hạn ${renewed} hội thoại đang tạm dừng.` : "."),
    );
    await loadSessions();
  } catch (error) {
    ensureDurationOption(savedHumanModeDuration);
    throw error;
  } finally {
    durationBusy = false;
    renderGlobalHumanMode();
  }
}
function syncModalBodyState() {
  const conversationModal = $("conversationModal");
  const cacheModal = $("clearCacheConfirmModal");
  const isOpen =
    Boolean(conversationModal && !conversationModal.hidden) ||
    Boolean(cacheModal && !cacheModal.hidden);
  document.body.style.overflow = isOpen ? "hidden" : "";
}
function openClearCacheConfirm(channel, sessionId) {
  const modal = $("clearCacheConfirmModal");
  const text = $("clearCacheConfirmText");
  const cancel = $("clearCacheCancel");
  if (!modal || !text || !cancel) {
    notice("Giao diện đang dùng bộ nhớ đệm cũ. Nhấn Ctrl + F5 rồi thử lại.", true);
    return;
  }
  pendingCacheClear = { channel, sessionId };
  text.textContent = `Xóa cache đang chạy của ${channel}:${sessionId}?`;
  modal.hidden = false;
  syncModalBodyState();
  cancel.focus();
}
function closeClearCacheConfirm() {
  if (cacheClearBusy) return;
  $("clearCacheConfirmModal").hidden = true;
  pendingCacheClear = null;
  syncModalBodyState();
}
async function confirmClearCache() {
  if (!pendingCacheClear || cacheClearBusy) return;
  const { channel, sessionId } = pendingCacheClear;
  cacheClearBusy = true;
  $("clearCacheCancel").disabled = true;
  $("clearCacheConfirm").disabled = true;
  $("clearCacheConfirm").textContent = "Đang xóa cache…";
  try {
    await responseJson(
      await fetch(
        `/admin/conversations/api/sessions/${encodeURIComponent(channel)}/${encodeURIComponent(sessionId)}/cache`,
        { method: "DELETE" },
      ),
    );
    $("clearCacheConfirmModal").hidden = true;
    pendingCacheClear = null;
    if (
      activeSession &&
      activeSession.channel === channel &&
      activeSession.sessionId === sessionId
    ) {
      closeModal();
    }
    syncModalBodyState();
    notice("Đã xóa cache Redis; lịch sử hội thoại vẫn được giữ lại.");
    await loadSessions();
  } finally {
    cacheClearBusy = false;
    $("clearCacheCancel").disabled = false;
    $("clearCacheConfirm").disabled = false;
    $("clearCacheConfirm").textContent = "Xác nhận xóa cache";
  }
}
function closeModal() {
  $("conversationModal").hidden = true;
  activeSession = null;
  activeHumanMode = false;
  activeHumanModeRemaining = null;
  activeCache = false;
  syncModalBodyState();
}
$("sessionRows").addEventListener("click", (event) => {
  const row = event.target.closest(".session-row");
  if (!row) return;
  const switchButton = event.target.closest(".mode-switch");
  if (switchButton) {
    toggleRowHumanMode(row, switchButton).catch((error) =>
      notice(error.message, true),
    );
    return;
  }
  if (event.target.closest(".row-clear-cache")) {
    openClearCacheConfirm(row.dataset.channel, row.dataset.session);
    return;
  }
  openSession(row.dataset.channel, row.dataset.session).catch((error) =>
    notice(error.message, true),
  );
});
$("refreshSessions").onclick = () =>
  loadSessions().catch((error) => notice(error.message, true));
$("channelFilter").onchange = () => {
  offset = 0;
  loadSessions().catch((error) => notice(error.message, true));
};
$("sessionSearch").oninput = () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    offset = 0;
    loadSessions().catch((error) => notice(error.message, true));
  }, 300);
};
$("previousPage").onclick = () => {
  offset = Math.max(0, offset - PAGE_SIZE);
  loadSessions();
};
$("nextPage").onclick = () => {
  offset += PAGE_SIZE;
  loadSessions();
};
$("closeConversation").onclick = closeModal;
$("conversationModal").onclick = (event) => {
  if (event.target === $("conversationModal")) closeModal();
};
$("clearCurrentCache")?.addEventListener("click", () => {
  if (activeSession) {
    openClearCacheConfirm(activeSession.channel, activeSession.sessionId);
  }
});
$("clearCacheCancel")?.addEventListener("click", closeClearCacheConfirm);
$("clearCacheConfirm")?.addEventListener("click", () =>
  confirmClearCache().catch((error) => notice(error.message, true)),
);
$("clearCacheConfirmModal")?.addEventListener("click", (event) => {
  if (event.target === $("clearCacheConfirmModal")) closeClearCacheConfirm();
});
$("toggleHumanMode").onclick = () =>
  toggleHumanMode().catch((error) => notice(error.message, true));
$("toggleGlobalHumanMode").onclick = () =>
  toggleGlobalHumanMode().catch((error) => notice(error.message, true));
$("humanModeDuration").onchange = () =>
  updateHumanModeDuration().catch((error) => notice(error.message, true));
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if ($("clearCacheConfirmModal") && !$("clearCacheConfirmModal").hidden) {
    closeClearCacheConfirm();
  } else if (!$("conversationModal").hidden) {
    closeModal();
  }
});
window.setInterval(() => {
  document.querySelectorAll(".session-row[data-human='1']").forEach((row) => {
    const remaining = Math.max(
      0,
      Number(row.dataset.humanRemaining || 0) - 1,
    );
    if (remaining === 0) {
      syncRowHumanMode(row.dataset.channel, row.dataset.session, false);
      if (
        activeSession &&
        activeSession.channel === row.dataset.channel &&
        activeSession.sessionId === row.dataset.session
      ) {
        activeHumanMode = false;
        activeHumanModeRemaining = null;
        const badge = $("humanModeBadge");
        if (badge) {
          badge.textContent = "Bot đang trả lời";
          badge.className = "pill bot-active";
        }
        renderHumanModeButton();
      }
      return;
    }
    syncRowHumanMode(
      row.dataset.channel,
      row.dataset.session,
      true,
      remaining,
    );
  });
  if (activeHumanMode && activeHumanModeRemaining != null) {
    activeHumanModeRemaining = Math.max(0, activeHumanModeRemaining - 1);
    if (activeHumanModeRemaining === 0) {
      activeHumanMode = false;
      activeHumanModeRemaining = null;
      const badge = $("humanModeBadge");
      if (badge) {
        badge.textContent = "Bot đang trả lời";
        badge.className = "pill bot-active";
      }
    }
    renderHumanModeButton();
  }
  if (globalAllPaused && globalRemaining != null) {
    globalRemaining = Math.max(0, globalRemaining - 1);
    if (globalRemaining === 0) {
      globalAllPaused = false;
      globalPausedCount = 0;
      globalRemaining = null;
    }
    renderGlobalHumanMode();
  }
}, 1000);
loadSessions().catch((error) => notice(error.message, true));
