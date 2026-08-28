const $ = (id) => document.getElementById(id);
let timer = null,
  statusHideTimer = null,
  lastStatus = "",
  catalogPage = 1,
  catalogPages = 1;
const catalogSyncJobs = new Map();
const catalogSyncTimers = new Map();
const catalogProducts = new Map();
let lightboxUrls = [],
  lightboxIndex = 0,
  lightboxProductName = "",
  lightboxPreviousFocus = null;
const catalogPageSize = 20,
  phases = ["shopify", "catalog", "images", "database", "embedding"];
function setBusy(v) {
  $("skuButton").disabled = v;
  $("excelButton").disabled = v;
  $("syncAllButton").disabled = v;
  if (v) {
    clearTimeout(statusHideTimer);
    $("statusCard").hidden = false;
  }
}
function hideFinishedStatus(delay = 6000) {
  clearTimeout(statusHideTimer);
  statusHideTimer = setTimeout(() => {
    $("statusCard").hidden = true;
  }, delay);
}
function toast(title, message, error = false) {
  const el = document.createElement("div");
  el.className = "toast";
  el.innerHTML = `<div style="font-size:22px">${error ? "!" : "✓"}</div><div><b></b><p></p></div>`;
  el.querySelector("b").textContent = title;
  el.querySelector("p").textContent = message;
  if (error) el.classList.add("error");
  $("toastStack").appendChild(el);
  requestAnimationFrame(() => el.classList.add("show"));
  setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 300);
  }, 5000);
}
async function asJson(r) {
  const d = await r.json();
  if (!r.ok)
    throw new Error(
      typeof d.detail === "string" ? d.detail : "Yêu cầu thất bại",
    );
  return d;
}
async function start(request) {
  try {
    setBusy(true);
    lastStatus = "";
    const response = await request;
    const j = await asJson(response);
    render(j);
    poll(j.id);
    toast("Đã tiếp nhận", `Hệ thống sẽ xử lý ${j.total} mã sản phẩm.`);
  } catch (e) {
    setBusy(false);
    $("statusIcon").className = "spinner error";
    $("statusBadge").textContent = "CÓ LỖI";
    $("statusBadge").className = "badge error";
    $("statusTitle").textContent = "Không thể bắt đầu";
    $("phaseLabel").textContent = e.message;
    toast("Không thể bắt đầu", e.message, true);
  }
}
async function poll(id) {
  clearTimeout(timer);
  try {
    const j = await asJson(await fetch(`/admin/products/api/jobs/${id}`));
    render(j);
    if (["queued", "claimed", "running"].includes(j.status))
      timer = setTimeout(() => poll(id), 1000);
    else {
      setBusy(false);
      catalogPage = 1;
      loadCatalog();
      if (lastStatus !== j.status)
        toast(
          j.failed ? "Hoàn tất có lỗi" : "Đồng bộ hoàn tất",
          j.failed
            ? `${j.succeeded} thành công, ${j.failed} lỗi.`
            : `Đã đồng bộ thành công ${j.succeeded} SKU.`,
          !!j.failed,
        );
      hideFinishedStatus();
    }
    lastStatus = j.status;
  } catch (e) {
    setBusy(false);
    toast("Mất kết nối", e.message, true);
  }
}
function render(j) {
  const running = ["queued", "claimed", "running"].includes(j.status);
  const pct = Math.min(
    100,
    Math.round(
      ((j.completed_units || 0) / Math.max(1, j.total_units || 1)) * 100,
    ),
  );
  $("statusTitle").textContent = running
    ? j.current_sku
      ? `Đang đồng bộ ${j.current_sku}`
      : "Tác vụ đang chờ"
    : j.phase_label;
  $("phaseLabel").textContent = j.phase_label;
  $("progress").style.width = pct + "%";
  $("progressText").textContent = pct + "%";
  $("total").textContent = j.total;
  $("processed").textContent = j.processed;
  $("succeeded").textContent = j.succeeded;
  $("failed").textContent = j.failed;
  $("statusBadge").textContent = running
    ? "ĐANG CHẠY"
    : j.failed
      ? "CÓ LỖI"
      : "HOÀN TẤT";
  $("statusBadge").className =
    `badge${j.failed && !running ? " error" : ""}`;
  $("statusIcon").className =
    `spinner${running ? "" : j.failed ? " error" : " done"}`;
  const idx = phases.indexOf(j.phase);
  document.querySelectorAll(".step").forEach((el, i) => {
    el.className =
      "step" + (i < idx ? " done" : i === idx ? " active" : "");
  });
  if (!running && j.failed === 0)
    document
      .querySelectorAll(".step")
      .forEach((el) => (el.className = "step done"));
  $("messages").textContent = j.messages.length
    ? j.messages.join("\n")
    : "Chưa có nhật ký.";
  $("messages").scrollTop = $("messages").scrollHeight;
  $("results").innerHTML = j.results.length
    ? j.results
        .map(
          (r) =>
            `<tr><td><b>${esc(r.sku)}</b></td><td class="${r.success ? "ok" : "bad"}">${r.success ? "✓ Thành công" : "! Lỗi"}</td><td>${r.shopify_products ?? "—"}</td><td>${r.downloaded ?? "—"}</td><td title="${esc(r.error || "")}">${esc(r.error || `Database sync #${r.sync_run_id}`)}</td></tr>`,
        )
        .join("")
    : '<tr><td colspan="5" class="empty"><div class="empty-state"><div class="empty-icon">◷</div><span>Kết quả sẽ hiển thị tại đây.</span></div></td></tr>';
}
function esc(v) {
  return String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[c],
  );
}
function dateText(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("vi-VN", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}
function moneyText(value) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  return Number.isFinite(number)
    ? `${new Intl.NumberFormat("vi-VN").format(number)} đ`
    : esc(value);
}
function detailValue(value) {
  return value === null || value === undefined || value === ""
    ? "—"
    : esc(value);
}
function catalogAiControl(product) {
  const code = product.product_code;
  const job = catalogSyncJobs.get(code);
  if (job && ["queued", "claimed", "running"].includes(job.status)) {
    return `<select class="catalog-ai-select syncing" data-code="${esc(code)}" aria-label="Trạng thái đồng bộ ${esc(code)}">
      <option value="" selected>Đang đồng bộ…</option>
      <option value="cancel">Dừng đồng bộ</option>
    </select>`;
  }
  if (job?.status === "cancel_requested") {
    return `<select class="catalog-ai-select stopping" data-code="${esc(code)}" disabled aria-label="Đang dừng đồng bộ ${esc(code)}">
      <option selected>Đang dừng…</option>
    </select>`;
  }
  if (product.ai_ready) {
    return `<select class="catalog-ai-select ready-select" data-code="${esc(code)}" aria-label="Đồng bộ lại ${esc(code)}">
      <option value="" selected>✓ Đã đồng bộ</option>
      <option value="sync">Đồng bộ lại</option>
    </select>`;
  }
  return `<select class="catalog-ai-select pending-select" data-code="${esc(code)}" aria-label="Đồng bộ ${esc(code)}">
    <option value="" selected>! Chưa đồng bộ</option>
    <option value="sync">Đồng bộ</option>
  </select>`;
}
function updateCatalogAiControl(code) {
  const product = catalogProducts.get(code);
  const row = [...document.querySelectorAll("#catalogRows tr[data-product-code]")]
    .find((item) => item.dataset.productCode === code);
  const cell = row?.querySelector(".catalog-ai-cell");
  if (product && cell) cell.innerHTML = catalogAiControl(product);
}
function finishCatalogSync(job, code) {
  const timerId = catalogSyncTimers.get(code);
  if (timerId) clearTimeout(timerId);
  catalogSyncTimers.delete(code);
  catalogSyncJobs.delete(code);
  setBusy(catalogSyncJobs.size > 0);
  loadCatalog();
  if (job.status === "cancelled") {
    toast("Đã dừng đồng bộ", `Tác vụ của ${code} đã được dừng.`);
  } else {
    const failed = job.status === "failed" || job.failed;
    toast(
      failed ? "Đồng bộ có lỗi" : "Đã đồng bộ sản phẩm",
      failed ? `${code} chưa được đồng bộ hoàn chỉnh.` : `${code} đã đồng bộ thành công.`,
      !!failed,
    );
  }
  if (catalogSyncJobs.size === 0) hideFinishedStatus();
}
async function pollCatalogSync(jobId, code) {
  try {
    const job = await asJson(
      await fetch(`/admin/products/api/jobs/${encodeURIComponent(jobId)}`),
    );
    catalogSyncJobs.set(code, { id: jobId, status: job.status });
    updateCatalogAiControl(code);
    render(job);
    if (["queued", "claimed", "running", "cancel_requested"].includes(job.status)) {
      const timerId = setTimeout(() => pollCatalogSync(jobId, code), 1000);
      catalogSyncTimers.set(code, timerId);
      return;
    }
    finishCatalogSync(job, code);
  } catch (error) {
    catalogSyncJobs.delete(code);
    updateCatalogAiControl(code);
    setBusy(catalogSyncJobs.size > 0);
    toast("Không theo dõi được đồng bộ", error.message, true);
  }
}
async function startCatalogSync(code) {
  try {
    clearTimeout(statusHideTimer);
    $("statusCard").hidden = false;
    const job = await asJson(
      await fetch("/admin/products/api/import-skus", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ skus: [code] }),
      }),
    );
    catalogSyncJobs.set(code, { id: job.id, status: job.status });
    setBusy(true);
    updateCatalogAiControl(code);
    render(job);
    toast("Đã tiếp nhận", `Đang đồng bộ lại sản phẩm ${code}.`);
    pollCatalogSync(job.id, code);
  } catch (error) {
    catalogSyncJobs.delete(code);
    updateCatalogAiControl(code);
    toast("Không thể đồng bộ", error.message, true);
  }
}
async function cancelCatalogSync(code) {
  const active = catalogSyncJobs.get(code);
  if (!active?.id) return;
  try {
    const job = await asJson(
      await fetch(
        `/admin/products/api/jobs/${encodeURIComponent(active.id)}/cancel`,
        { method: "POST" },
      ),
    );
    catalogSyncJobs.set(code, { id: active.id, status: job.status });
    updateCatalogAiControl(code);
    render(job);
    if (job.status === "cancelled") finishCatalogSync(job, code);
    else toast("Đang dừng", `${code} sẽ dừng ở bước an toàn gần nhất.`);
  } catch (error) {
    toast("Không thể dừng đồng bộ", error.message, true);
    updateCatalogAiControl(code);
  }
}
let productDetailPreviousFocus = null;
function closeProductDetail() {
  $("productDetailModal").hidden = true;
  document.body.classList.remove("product-detail-open");
  if (productDetailPreviousFocus instanceof HTMLElement) {
    productDetailPreviousFocus.focus();
  }
}
let syncAllPreviousFocus = null;
function closeSyncAllConfirm() {
  $("syncAllConfirmModal").hidden = true;
  document.body.classList.remove("sync-confirm-open");
  if (syncAllPreviousFocus instanceof HTMLElement) {
    syncAllPreviousFocus.focus();
  }
}
async function openSyncAllConfirm() {
  syncAllPreviousFocus = document.activeElement;
  $("syncAllConfirmText").textContent =
    "Hệ thống đang kiểm tra số lượng sản phẩm cần đồng bộ…";
  $("syncAllConfirm").disabled = true;
  $("syncAllConfirmModal").hidden = false;
  document.body.classList.add("sync-confirm-open");
  $("syncAllCancel").focus();
  try {
    const preview = await asJson(
      await fetch("/admin/products/api/sync-all/preview"),
    );
    const count = Number(preview.active_count || 0);
    $("syncAllConfirmText").textContent = count
      ? `Hệ thống sẽ đồng bộ lại ${new Intl.NumberFormat("vi-VN").format(count)} sản phẩm đang ACTIVE.`
      : "Hiện không có sản phẩm ACTIVE để đồng bộ.";
    $("syncAllConfirm").disabled = count === 0;
  } catch (error) {
    $("syncAllConfirmText").textContent = error.message;
    toast("Không kiểm tra được sản phẩm", error.message, true);
  }
}
function renderProductDetail(data) {
  const p = data.product || {};
  const variants = data.variants || [];
  const images = data.images || [];
  const attributes = data.attributes || [];
  const aliases = data.aliases || [];
  const activeImages = images.filter((image) => image.is_active);
  $("productDetailCode").textContent = p.product_code || "—";
  $("productDetailTitle").textContent = p.title || "Chi tiết sản phẩm";
  const facts = [
    ["Loại sản phẩm", p.product_type],
    ["Thương hiệu", p.vendor],
    ["Chất liệu", p.material],
    ["Đế", p.sole],
    ["Chiều cao", p.height],
    ["Trạng thái", p.status],
    ["Cập nhật Shopify", dateText(p.source_updated_at)],
    ["Cập nhật database", dateText(p.updated_at)],
  ];
  const imageHtml = activeImages.length
    ? activeImages
        .map(
          (image) => `<article class="product-detail-image-card">
            <div class="product-detail-image-frame">
              ${image.source_url ? `<img src="${esc(image.source_url)}" alt="${esc(image.alt_text || p.title || p.product_code)}" loading="lazy" />` : '<span>Không có URL ảnh</span>'}
            </div>
            <div class="product-detail-image-meta">
              <b>${detailValue(image.color || "Không xác định màu")}</b>
              <span>${detailValue(image.width)} × ${detailValue(image.height)}</span>
              <span class="ready${image.embedded ? "" : " no"}">${image.embedded ? "✓ Đã embedding" : "! Chưa embedding"}</span>
            </div>
          </article>`,
        )
        .join("")
    : '<div class="product-detail-empty">Sản phẩm chưa có ảnh đang hoạt động.</div>';
  const variantHtml = variants.length
    ? variants
        .map(
          (variant) => `<tr>
            <td><b>${detailValue(variant.sku)}</b><small>${detailValue(variant.variant_title)}</small></td>
            <td>${detailValue(variant.color)}</td>
            <td>${detailValue(variant.size)}</td>
            <td>${moneyText(variant.price)}</td>
            <td>${moneyText(variant.compare_at_price)}</td>
            <td>${detailValue(variant.inventory_quantity)}</td>
            <td><span class="ready${variant.available ? "" : " no"}">${variant.available ? "Còn hàng" : "Hết hàng"}</span></td>
          </tr>`,
        )
        .join("")
    : '<tr><td colspan="7" class="empty">Chưa có variant.</td></tr>';
  const attributeHtml = attributes.length
    ? attributes
        .map(
          (item) => `<div><dt>${detailValue(item.attribute_key)}</dt><dd>${detailValue(item.attribute_value)}</dd></div>`,
        )
        .join("")
    : '<div class="product-detail-empty">Chưa có thuộc tính bổ sung.</div>';
  const aliasHtml = aliases.length
    ? aliases
        .map(
          (item) => `<span class="product-detail-alias">${detailValue(item.alias)} <small>${detailValue(item.alias_type)}</small></span>`,
        )
        .join("")
    : '<span class="product-detail-empty">Chưa có từ khóa thay thế.</span>';
  $("productDetailBody").innerHTML = `
    <section class="product-detail-section">
      <div class="product-detail-facts">${facts
        .map(
          ([label, value]) => `<div><span>${label}</span><b>${detailValue(value)}</b></div>`,
        )
        .join("")}</div>
      ${p.online_store_url ? `<a class="product-detail-link" href="${esc(p.online_store_url)}" target="_blank" rel="noopener noreferrer">Xem sản phẩm trên website ↗</a>` : ""}
    </section>
    <section class="product-detail-section">
      <h3>Mô tả</h3>
      <p class="product-detail-description">${detailValue(p.description)}</p>
    </section>
    <section class="product-detail-section">
      <div class="product-detail-section-head"><h3>Ảnh sản phẩm</h3><span>${activeImages.length}/${images.length} ảnh đang hoạt động · ${esc(data.embedding_model || "—")}</span></div>
      <div class="product-detail-gallery">${imageHtml}</div>
    </section>
    <section class="product-detail-section">
      <div class="product-detail-section-head"><h3>Toàn bộ variant</h3><span>${variants.length} variant</span></div>
      <div class="table-wrap product-detail-variants"><table><thead><tr><th>SKU / Variant</th><th>Màu</th><th>Size</th><th>Giá</th><th>Giá so sánh</th><th>Tồn kho</th><th>Trạng thái</th></tr></thead><tbody>${variantHtml}</tbody></table></div>
    </section>
    <section class="product-detail-columns">
      <div class="product-detail-section"><h3>Thuộc tính bổ sung</h3><dl class="product-detail-attributes">${attributeHtml}</dl></div>
      <div class="product-detail-section"><h3>Từ khóa / Alias</h3><div class="product-detail-aliases">${aliasHtml}</div></div>
    </section>`;
}
async function openProductDetail(code, trigger) {
  productDetailPreviousFocus = trigger || document.activeElement;
  $("productDetailCode").textContent = code;
  $("productDetailTitle").textContent = "Đang tải sản phẩm…";
  $("productDetailBody").innerHTML =
    '<div class="product-detail-loading">Đang tải thông tin sản phẩm…</div>';
  $("productDetailModal").hidden = false;
  document.body.classList.add("product-detail-open");
  $("productDetailClose").focus();
  try {
    const data = await asJson(
      await fetch(`/admin/products/api/catalog/${encodeURIComponent(code)}`),
    );
    renderProductDetail(data);
  } catch (error) {
    $("productDetailTitle").textContent = "Không tải được sản phẩm";
    $("productDetailBody").innerHTML =
      `<div class="product-detail-empty bad">${esc(error.message)}</div>`;
  }
}
async function loadCatalog() {
  const query = $("catalogSearch").value.trim(),
    productType = $("catalogType").value,
    offset = (catalogPage - 1) * catalogPageSize;
  $("catalogRows").innerHTML =
    '<tr><td colspan="8" class="empty"><div class="empty-state"><div class="empty-icon">◷</div><span>Đang tải danh sách…</span></div></td></tr>';
  try {
    const data = await asJson(
      await fetch(
        `/admin/products/api/catalog?search=${encodeURIComponent(query)}&product_type=${encodeURIComponent(productType)}&limit=${catalogPageSize}&offset=${offset}`,
      ),
    );
    catalogPages = Math.max(1, Math.ceil(data.total / catalogPageSize));
    if (catalogPage > catalogPages) {
      catalogPage = catalogPages;
      return loadCatalog();
    }
    $("catalogTotal").textContent = data.total;
    $("catalogModel").textContent = data.embedding_model;
    $("catalogType").innerHTML =
      '<option value="">Tất cả thể loại</option>' +
      (data.product_types || [])
        .map(
          (type) =>
            `<option value="${esc(type)}"${type === productType ? " selected" : ""}>${esc(type)}</option>`,
        )
        .join("");
    $("catalogPage").textContent = catalogPage;
    $("catalogPages").textContent = catalogPages;
    $("catalogPrev").disabled = catalogPage <= 1;
    $("catalogNext").disabled = catalogPage >= catalogPages;
    catalogProducts.clear();
    data.products.forEach((product) =>
      catalogProducts.set(product.product_code, product),
    );
    $("catalogRows").innerHTML = data.products.length
      ? data.products
          .map(
            (p) =>
              `<tr class="catalog-product-row" data-product-code="${esc(p.product_code)}" tabindex="0" role="button" aria-label="Xem chi tiết ${esc(p.title)}"><td><b>${esc(p.product_code)}</b></td><td class="product-title"><b title="${esc(p.title)}">${esc(p.title)}</b><small title="${esc(p.product_type || "")}">${esc(p.product_type || "—")}</small></td><td>${esc(p.colors || "—")}</td><td>${p.variant_count}</td><td>${p.local_image_count}/${p.image_count}</td><td>${p.embedding_count}</td><td class="catalog-ai-cell">${catalogAiControl(p)}</td><td>${dateText(p.updated_at)}</td></tr>`,
          )
          .join("")
      : '<tr><td colspan="8" class="empty"><div class="empty-state"><div class="empty-icon">⌕</div><span>Không tìm thấy sản phẩm.</span></div></td></tr>';
  } catch (e) {
    $("catalogRows").innerHTML =
      `<tr><td colspan="8" class="empty bad"><div class="empty-state"><div class="empty-icon">!</div><span>${esc(e.message)}</span></div></td></tr>`;
    toast("Không tải được catalog", e.message, true);
  }
}
$("catalogRows").addEventListener("click", (event) => {
  if (event.target.closest(".catalog-ai-select")) return;
  const row = event.target.closest("tr[data-product-code]");
  if (row) openProductDetail(row.dataset.productCode, row);
});
$("catalogRows").addEventListener("change", (event) => {
  const select = event.target.closest(".catalog-ai-select");
  if (!select) return;
  event.stopPropagation();
  const code = select.dataset.code;
  const action = select.value;
  select.value = "";
  if (action === "sync") startCatalogSync(code);
  if (action === "cancel") cancelCatalogSync(code);
});
$("catalogRows").addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const row = event.target.closest("tr[data-product-code]");
  if (!row) return;
  event.preventDefault();
  openProductDetail(row.dataset.productCode, row);
});
$("productDetailClose").onclick = closeProductDetail;
$("productDetailModal").onclick = (event) => {
  if (event.target === $("productDetailModal")) closeProductDetail();
};
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("productDetailModal").hidden) {
    closeProductDetail();
  }
  if (event.key === "Escape" && !$("syncAllConfirmModal").hidden) {
    closeSyncAllConfirm();
  }
});
$("excelFile").onchange = (e) =>
  ($("fileName").textContent =
    e.target.files[0]?.name || "Chưa có file được chọn");
$("skuButton").onclick = () => {
  const skus = $("skuText")
    .value.split(/[\n,;]+/)
    .map((x) => x.trim())
    .filter(Boolean);
  start(
    fetch("/admin/products/api/import-skus", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skus }),
    }),
  );
};
$("excelButton").onclick = () => {
  const f = $("excelFile").files[0];
  if (!f) {
    toast(
      "Thiếu file Excel",
      "Vui lòng chọn file .xlsx trước khi đồng bộ.",
      true,
    );
    return;
  }
  const form = new FormData();
  form.append("file", f);
  start(
    fetch("/admin/products/api/import-excel", {
      method: "POST",
      body: form,
    }),
  );
};
$("syncAllButton").onclick = () => {
  openSyncAllConfirm();
};
$("syncAllCancel").onclick = closeSyncAllConfirm;
$("syncAllConfirmModal").onclick = (event) => {
  if (event.target === $("syncAllConfirmModal")) closeSyncAllConfirm();
};
$("syncAllConfirm").onclick = () => {
  closeSyncAllConfirm();
  start(
    fetch("/admin/products/api/sync-all", {
      method: "POST",
    }),
  );
};
$("catalogSearchButton").onclick = () => {
  catalogPage = 1;
  loadCatalog();
};
$("catalogRefreshButton").onclick = () => {
  $("catalogSearch").value = "";
  $("catalogType").value = "";
  catalogPage = 1;
  loadCatalog();
};
$("catalogType").onchange = () => {
  catalogPage = 1;
  loadCatalog();
};
$("catalogSearch").onkeydown = (e) => {
  if (e.key === "Enter") {
    catalogPage = 1;
    loadCatalog();
  }
};
$("catalogPrev").onclick = () => {
  if (catalogPage > 1) {
    catalogPage--;
    loadCatalog();
  }
};
$("catalogNext").onclick = () => {
  if (catalogPage < catalogPages) {
    catalogPage++;
    loadCatalog();
  }
};
loadCatalog();

// ---- Trợ lý đồng bộ (chatbot) ----
if (!window.DongHaiSharedChat) {
let chatBusy = false;
let chatHistory = [];
let activeProductCodes = [];
const CHAT_TRANSCRIPT_PREFIX = "dong_hai_chat_transcript:";
const CHAT_GREETING = "👋 Xin chào anh/chị! Em là trợ lý AI của Đông Hải. Anh/chị cần em hỗ trợ gì ạ?";
function getChatSessionId() {
  let sessionId = localStorage.getItem("dong_hai_chat_session");
  if (!sessionId) {
    sessionId = crypto.randomUUID();
    localStorage.setItem("dong_hai_chat_session", sessionId);
  }
  return sessionId;
}
function getChatTranscriptKey(sessionId = getChatSessionId()) {
  return `${CHAT_TRANSCRIPT_PREFIX}${sessionId}`;
}
function loadChatTranscript() {
  try {
    const value = JSON.parse(
      localStorage.getItem(getChatTranscriptKey()) || "[]",
    );
    return Array.isArray(value) ? value : [];
  } catch (error) {
    console.warn("Không thể đọc lịch sử chat trên trình duyệt:", error);
    return [];
  }
}
function saveChatTranscript(items) {
  try {
    localStorage.setItem(
      getChatTranscriptKey(),
      JSON.stringify(items.slice(-60)),
    );
  } catch (error) {
    console.warn("Không thể lưu lịch sử chat trên trình duyệt:", error);
  }
}
function appendChatTranscript(item) {
  const items = loadChatTranscript();
  items.push(item);
  saveChatTranscript(items);
}
function rememberChat(role, content) {
  if (!content) return;
  chatHistory.push({ role, content });
  chatHistory = chatHistory.slice(-20);
}
function rememberActiveProducts(codes) {
  const normalized = (codes || [])
    .map((code) => String(code || "").trim().toUpperCase())
    .filter(Boolean);
  if (normalized.length) {
    activeProductCodes = [...new Set(normalized)].slice(0, 5);
  }
}
function chatOpen() {
  $("chatPanel").classList.add("open");
  $("chatPanel").setAttribute("aria-hidden", "false");
  $("chatLauncher").setAttribute("aria-expanded", "true");
  $("chatLauncher").classList.add("hidden");
  $("chatClose").classList.add("open");
  $("chatInput").focus();
}
function chatClose() {
  $("chatPanel").classList.remove("open");
  $("chatPanel").setAttribute("aria-hidden", "true");
  $("chatLauncher").setAttribute("aria-expanded", "false");
  $("chatLauncher").classList.remove("hidden");
  $("chatClose").classList.remove("open");
}
$("chatLauncher").onclick = chatOpen;
$("chatClose").onclick = chatClose;
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("imageLightbox").hidden) {
    closeLightbox();
    return;
  }
  if (e.key === "ArrowLeft" && !$("imageLightbox").hidden) {
    showLightboxImage(lightboxIndex - 1);
    return;
  }
  if (e.key === "ArrowRight" && !$("imageLightbox").hidden) {
    showLightboxImage(lightboxIndex + 1);
    return;
  }
  if (e.key === "Escape" && $("chatPanel").classList.contains("open")) {
    chatClose();
  }
});
$("chatInput").addEventListener("input", function () {
  this.style.height = "40px";
  this.style.height = Math.min(90, this.scrollHeight) + "px";
});
$("chatInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendChatMessage();
  }
});
$("chatSend").onclick = sendChatMessage;
$("chatAttach").onclick = () => {
  if (!chatBusy) $("chatImage").click();
};
$("chatImage").onchange = () => {
  const file = $("chatImage").files[0];
  if (file) sendChatImage(file);
};
function addMsg(text, who, persist = true) {
  const el = document.createElement("div");
  el.className = `ck-msg ${who}`;
  el.textContent = text;
  $("chatBody").appendChild(el);
  $("chatBody").scrollTop = $("chatBody").scrollHeight;
  if (persist && text) {
    appendChatTranscript({ type: "message", who, text });
  }
  return el;
}
function addUserImage(file) {
  const wrapper = document.createElement("div");
  wrapper.className = "ck-msg user-image";
  const image = document.createElement("img");
  const objectUrl = URL.createObjectURL(file);
  image.src = objectUrl;
  image.alt = "Ảnh sản phẩm khách gửi";
  image.onload = () => URL.revokeObjectURL(objectUrl);
  wrapper.appendChild(image);
  $("chatBody").appendChild(wrapper);
  $("chatBody").scrollTop = $("chatBody").scrollHeight;
  appendChatTranscript({
    type: "message",
    who: "user",
    text: "📷 Ảnh sản phẩm đã gửi",
  });
}
function showLightboxImage(index) {
  if (!lightboxUrls.length) return;
  lightboxIndex = (index + lightboxUrls.length) % lightboxUrls.length;
  const image = $("lightboxImage");
  image.src = lightboxUrls[lightboxIndex];
  image.alt = `${lightboxProductName}, ảnh ${lightboxIndex + 1}`;
  $("lightboxCaption").textContent =
    `${lightboxProductName} · ${lightboxIndex + 1}/${lightboxUrls.length}`;
  const hasMultipleImages = lightboxUrls.length > 1;
  $("lightboxPrev").hidden = !hasMultipleImages;
  $("lightboxNext").hidden = !hasMultipleImages;
}
function openLightbox(urls, index, productName) {
  lightboxUrls = [...urls];
  lightboxProductName = productName || "Sản phẩm";
  lightboxPreviousFocus = document.activeElement;
  showLightboxImage(index);
  $("imageLightbox").hidden = false;
  document.body.classList.add("lightbox-open");
  $("lightboxClose").focus();
}
function closeLightbox() {
  $("imageLightbox").hidden = true;
  $("lightboxImage").removeAttribute("src");
  document.body.classList.remove("lightbox-open");
  lightboxUrls = [];
  if (lightboxPreviousFocus instanceof HTMLElement) {
    lightboxPreviousFocus.focus();
  }
}
$("lightboxClose").onclick = closeLightbox;
$("lightboxPrev").onclick = () => showLightboxImage(lightboxIndex - 1);
$("lightboxNext").onclick = () => showLightboxImage(lightboxIndex + 1);
$("imageLightbox").onclick = (event) => {
  if (event.target === $("imageLightbox")) closeLightbox();
};
$("chatBody").addEventListener("click", (event) => {
  const image = event.target.closest(".ck-product-album img");
  if (!image) return;
  const album = image.closest(".ck-product-album");
  const images = [...album.querySelectorAll("img")];
  const urls = images.map((item) => item.currentSrc || item.src);
  const index = images.indexOf(image);
  const productName = image.alt.replace(/, ảnh \d+$/, "") || "Sản phẩm";
  openLightbox(urls, index, productName);
});
function addProductAlbums(products, persist = true) {
  const persistedProducts = [];
  (products || []).forEach((product) => {
    const urls = (product.image_urls || []).slice(0, 4);
    if (!urls.length) return;
    persistedProducts.push({
      product_code: product.product_code,
      product_name: product.product_name,
      image_urls: urls,
    });
    const album = document.createElement("div");
    album.className = `ck-product-album count-${urls.length}${urls.length === 1 ? " single" : ""}`;
    const productName =
      product.product_name || product.product_code || "Sản phẩm";
    urls.forEach((url, imageIndex) => {
      const image = document.createElement("img");
      image.src = url;
      image.dataset.originalUrl = url;
      image.dataset.cdnRetry = "0";
      image.alt = `${product.product_name || product.product_code || "Sản phẩm"}`;
      image.loading = "lazy";
      image.alt = `${productName}, ảnh ${imageIndex + 1}`;
      image.tabIndex = 0;
      image.setAttribute("role", "button");
      image.setAttribute("aria-label", `Xem lớn ${image.alt}`);
      image.onkeydown = (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openLightbox(urls, imageIndex, productName);
        }
      };
      image.onload = () => {
        $("chatBody").scrollTop = $("chatBody").scrollHeight;
      };
      image.onerror = () => {
        // Retry a stale Shopify version URL once without its query string.
        if (image.dataset.cdnRetry === "0") {
          const cleanUrl = image.dataset.originalUrl.split("?")[0];
          if (cleanUrl && cleanUrl !== image.dataset.originalUrl) {
            image.dataset.cdnRetry = "1";
            image.src = cleanUrl;
            return;
          }
        }
        console.warn(
          "Không tải được ảnh sản phẩm từ Shopify CDN:",
          image.dataset.originalUrl,
        );
        image.remove();
        if (!album.querySelector("img")) album.remove();
      };
      album.appendChild(image);
    });
    $("chatBody").appendChild(album);
  });
  if (persist && persistedProducts.length) {
    appendChatTranscript({
      type: "albums",
      products: persistedProducts,
    });
  }
  $("chatBody").scrollTop = $("chatBody").scrollHeight;
}
function restoreChatTranscript() {
  const items = loadChatTranscript();
  if (!items.length) return;

  chatHistory = [];
  $("chatBody").replaceChildren();
  items.forEach((item) => {
    if (item.type === "message" && item.text) {
      addMsg(item.text, item.who === "user" ? "user" : "bot", false);
      rememberChat(
        item.who === "user" ? "user" : "assistant",
        item.text,
      );
    } else if (item.type === "albums" && Array.isArray(item.products)) {
      addProductAlbums(item.products, false);
      rememberActiveProducts(
        item.products.map((product) => product.product_code),
      );
    }
  });
  $("chatBody").scrollTop = $("chatBody").scrollHeight;
}
function setChatBusy(busy) {
  chatBusy = busy;
  $("chatSend").disabled = busy;
  $("chatAttach").disabled = busy;
  $("chatReset").disabled = busy;
}

async function resetChatConversation() {
  if (chatBusy) return;
  const oldSessionId = getChatSessionId();
  setChatBusy(true);
  try {
    const response = await fetch("/api/chat/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: oldSessionId,
        channel: "web",
      }),
    });
    if (!response.ok) throw new Error("Không thể reset hội thoại");

    localStorage.removeItem(getChatTranscriptKey(oldSessionId));
    localStorage.setItem("dong_hai_chat_session", crypto.randomUUID());
    chatHistory = [];
    activeProductCodes = [];
    $("chatBody").replaceChildren();
    addMsg(CHAT_GREETING, "bot");
    $("chatInput").value = "";
    $("chatInput").style.height = "40px";
    $("chatImage").value = "";
    $("chatInput").focus();
  } catch (error) {
    addMsg(
      "Dạ, hiện em chưa thể tạo hội thoại mới. Anh/chị thử lại giúp em nhé.",
      "bot",
    );
  } finally {
    setChatBusy(false);
  }
}

$("chatReset").onclick = resetChatConversation;
function addTyping() {
  const el = document.createElement("div");
  el.className = "ck-msg bot typing";
  el.innerHTML = "<span></span><span></span><span></span>";
  $("chatBody").appendChild(el);
  $("chatBody").scrollTop = $("chatBody").scrollHeight;
  return el;
}

async function sendChatMessage() {
  const text = $("chatInput").value.trim();
  if (!text || chatBusy) return;
  const requestHistory = chatHistory.slice(-20);
  setChatBusy(true);
  addMsg(text, "user");
  $("chatInput").value = "";
  $("chatInput").style.height = "40px";
  const typingEl = addTyping();
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        session_id: getChatSessionId(),
        channel: "web",
      }),
    });
    if (!res.ok) throw new Error("no-endpoint");
    const data = await res.json();
    typingEl.remove();
    addMsg(
      data.message || "Xin lỗi, mình chưa có câu trả lời cho việc này.",
      "bot",
    );
    addProductAlbums(data.media);
    rememberActiveProducts((data.media || []).map((item) => item.product_code));
    rememberChat("user", text);
    rememberChat("assistant", data.message || "");
  } catch (e) {
    typingEl.remove();
    addMsg(
      "Trợ lý chưa kết nối được với backend. Anh/chị vui lòng thử lại sau.",
      "bot",
    );
  } finally {
    setChatBusy(false);
  }
}

async function sendChatImage(file) {
  if (chatBusy) return;
  if (!/^image\/(jpeg|png|webp)$/i.test(file.type)) {
    addMsg("Dạ, ảnh cần có định dạng JPG, PNG hoặc WEBP ạ.", "bot");
    $("chatImage").value = "";
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    addMsg("Dạ, ảnh cần có dung lượng không quá 10 MB ạ.", "bot");
    $("chatImage").value = "";
    return;
  }

  setChatBusy(true);
  const caption = $("chatInput").value.trim();
  addUserImage(file);
  if (caption) addMsg(caption, "user");
  $("chatInput").value = "";
  $("chatInput").style.height = "40px";
  const typingEl = addTyping();
  const form = new FormData();
  form.append("image", file);
  form.append("caption", caption);
  form.append("session_id", getChatSessionId());
  form.append("channel", "web");

  try {
    const response = await fetch("/api/chat/image", {
      method: "POST",
      body: form,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || "Không thể xử lý ảnh.");
    }
    typingEl.remove();
    if (data.message) addMsg(data.message, "bot");
    addProductAlbums(data.media);
    const recognizedCodes = (data.media || []).map((item) => item.product_code).join(", ");
    rememberActiveProducts((data.media || []).map((item) => item.product_code));
    rememberChat(
      "user",
      caption || "Khách đã gửi một ảnh sản phẩm để nhận diện.",
    );
    rememberChat(
      "assistant",
      [
        data.message || "",
        recognizedCodes ? `Mã sản phẩm đã xác minh: ${recognizedCodes}.` : "",
      ]
        .filter(Boolean)
        .join("\n"),
    );
  } catch (error) {
    typingEl.remove();
    addMsg(
      error.message || "Dạ, em chưa thể xử lý ảnh lúc này. Anh/chị thử lại giúp em nhé.",
      "bot",
    );
  } finally {
    $("chatImage").value = "";
    setChatBusy(false);
  }
}

restoreChatTranscript();
}
