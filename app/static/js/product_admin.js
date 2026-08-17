const $ = (id) => document.getElementById(id);
let timer = null,
  lastStatus = "",
  catalogPage = 1,
  catalogPages = 1;
let lightboxUrls = [],
  lightboxIndex = 0,
  lightboxProductName = "",
  lightboxPreviousFocus = null;
const catalogPageSize = 20,
  phases = ["shopify", "catalog", "images", "database", "embedding"];
function setBusy(v) {
  $("skuButton").disabled = v;
  $("excelButton").disabled = v;
  $("statusCard").hidden = false;
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
    if (["queued", "running"].includes(j.status))
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
    }
    lastStatus = j.status;
  } catch (e) {
    setBusy(false);
    toast("Mất kết nối", e.message, true);
  }
}
function render(j) {
  const running = ["queued", "running"].includes(j.status);
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
async function loadCatalog() {
  const query = $("catalogSearch").value.trim(),
    offset = (catalogPage - 1) * catalogPageSize;
  $("catalogRows").innerHTML =
    '<tr><td colspan="8" class="empty"><div class="empty-state"><div class="empty-icon">◷</div><span>Đang tải danh sách…</span></div></td></tr>';
  try {
    const data = await asJson(
      await fetch(
        `/admin/products/api/catalog?search=${encodeURIComponent(query)}&limit=${catalogPageSize}&offset=${offset}`,
      ),
    );
    catalogPages = Math.max(1, Math.ceil(data.total / catalogPageSize));
    if (catalogPage > catalogPages) {
      catalogPage = catalogPages;
      return loadCatalog();
    }
    $("catalogTotal").textContent = data.total;
    $("catalogModel").textContent = data.embedding_model;
    $("catalogPage").textContent = catalogPage;
    $("catalogPages").textContent = catalogPages;
    $("catalogPrev").disabled = catalogPage <= 1;
    $("catalogNext").disabled = catalogPage >= catalogPages;
    $("catalogRows").innerHTML = data.products.length
      ? data.products
          .map(
            (p) =>
              `<tr><td><b>${esc(p.product_code)}</b></td><td class="product-title"><b title="${esc(p.title)}">${esc(p.title)}</b><small title="${esc(p.product_type || "")}">${esc(p.product_type || "—")}</small></td><td>${esc(p.colors || "—")}</td><td>${p.variant_count}</td><td>${p.local_image_count}/${p.image_count}</td><td>${p.embedding_count}</td><td><span class="ready${p.ai_ready ? "" : " no"}">${p.ai_ready ? "✓ Sẵn sàng" : "! Chưa đủ"}</span></td><td>${dateText(p.updated_at)}</td></tr>`,
          )
          .join("")
      : '<tr><td colspan="8" class="empty"><div class="empty-state"><div class="empty-icon">⌕</div><span>Không tìm thấy sản phẩm.</span></div></td></tr>';
  } catch (e) {
    $("catalogRows").innerHTML =
      `<tr><td colspan="8" class="empty bad"><div class="empty-state"><div class="empty-icon">!</div><span>${esc(e.message)}</span></div></td></tr>`;
    toast("Không tải được catalog", e.message, true);
  }
}
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
$("catalogSearchButton").onclick = () => {
  catalogPage = 1;
  loadCatalog();
};
$("catalogRefreshButton").onclick = () => {
  $("catalogSearch").value = "";
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
let chatBusy = false;
let chatHistory = [];
let activeProductCodes = [];
function getChatSessionId() {
  let sessionId = localStorage.getItem("dong_hai_chat_session");
  if (!sessionId) {
    sessionId = crypto.randomUUID();
    localStorage.setItem("dong_hai_chat_session", sessionId);
  }
  return sessionId;
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
function addMsg(text, who) {
  const el = document.createElement("div");
  el.className = `ck-msg ${who}`;
  el.textContent = text;
  $("chatBody").appendChild(el);
  $("chatBody").scrollTop = $("chatBody").scrollHeight;
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
function addProductAlbums(products) {
  (products || []).forEach((product) => {
    const urls = (product.image_urls || []).slice(0, 4);
    if (!urls.length) return;
    const album = document.createElement("div");
    album.className = `ck-product-album count-${urls.length}${urls.length === 1 ? " single" : ""}`;
    const productName =
      product.product_name || product.product_code || "Sản phẩm";
    urls.forEach((url, imageIndex) => {
      const image = document.createElement("img");
      image.src = url;
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
      image.onerror = () => image.remove();
      album.appendChild(image);
    });
    $("chatBody").appendChild(album);
  });
  $("chatBody").scrollTop = $("chatBody").scrollHeight;
}
function setChatBusy(busy) {
  chatBusy = busy;
  $("chatSend").disabled = busy;
  $("chatAttach").disabled = busy;
}
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
