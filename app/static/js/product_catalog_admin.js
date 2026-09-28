const $ = (id) => document.getElementById(id);

let catalogPage = 1;
let catalogPages = 1;
let catalogPageSize = 20;
let productDetailPreviousFocus = null;
let currentProductDetailCode = null;

function esc(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (character) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[character],
  );
}

async function asJson(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(
      typeof data.detail === "string" ? data.detail : "Yêu cầu thất bại",
    );
  }
  return data;
}

function dateText(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("vi-VN", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
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

function toast(title, message, error = false) {
  const node = document.createElement("div");
  node.className = `toast${error ? " error" : ""}`;
  node.innerHTML =
    '<div class="toast-symbol"></div><div><b></b><p></p></div>';
  node.querySelector(".toast-symbol").textContent = error ? "!" : "✓";
  node.querySelector("b").textContent = title;
  node.querySelector("p").textContent = message;
  $("toastStack").appendChild(node);
  requestAnimationFrame(() => node.classList.add("show"));
  window.setTimeout(() => {
    node.classList.remove("show");
    window.setTimeout(() => node.remove(), 250);
  }, 4500);
}

function statusBadge(product) {
  const active = String(product.status || "ACTIVE").toUpperCase() === "ACTIVE";
  return `<span class="status${active ? "" : " inactive"}">${active ? "Đang hoạt động" : esc(product.status || "Không hoạt động")}</span>`;
}

function aiBadge(product) {
  return `<span class="badge${product.ai_ready ? "" : " inactive"}">${product.ai_ready ? "Sẵn sàng" : "Chưa sẵn sàng"}</span>`;
}

function productImage(product) {
  if (!product.image_url) {
    return '<span class="product-image-placeholder">◇</span>';
  }
  return `<img class="product-list-image" src="${esc(product.image_url)}" alt="${esc(product.title || product.product_code)}" loading="lazy" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'product-image-placeholder',textContent:'◇'}))" />`;
}

function paginationItems(page, pages) {
  if (pages <= 7) return Array.from({ length: pages }, (_, index) => index + 1);
  const selected = new Set([1, pages]);
  const start = page <= 4 ? 2 : page >= pages - 3 ? pages - 4 : page - 2;
  const end = page <= 4 ? 5 : page >= pages - 3 ? pages - 1 : page + 2;
  for (let value = start; value <= end; value += 1) selected.add(value);
  const ordered = [...selected].sort((left, right) => left - right);
  const items = [];
  let previous = 0;
  for (const value of ordered) {
    if (previous && value - previous > 1) items.push("ellipsis");
    items.push(value);
    previous = value;
  }
  return items;
}

function renderPagination() {
  const container = $("catalogPaginationPages");
  container.replaceChildren();
  for (const item of paginationItems(catalogPage, catalogPages)) {
    if (item === "ellipsis") {
      const ellipsis = document.createElement("span");
      ellipsis.className = "pagination-ellipsis";
      ellipsis.textContent = "…";
      container.appendChild(ellipsis);
      continue;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = `pagination-page${item === catalogPage ? " active" : ""}`;
    button.textContent = String(item);
    button.setAttribute("aria-label", `Trang ${item}`);
    if (item === catalogPage) button.setAttribute("aria-current", "page");
    button.onclick = () => {
      if (item === catalogPage) return;
      catalogPage = item;
      loadCatalog();
    };
    container.appendChild(button);
  }
  $("catalogPrev").disabled = catalogPage <= 1;
  $("catalogNext").disabled = catalogPage >= catalogPages;
}

function renderCatalogRows(products) {
  $("catalogRows").innerHTML = products.length
    ? products
        .map(
          (product) => `<tr class="catalog-product-row" data-product-code="${esc(product.product_code)}" tabindex="0" role="button" aria-label="Xem chi tiết ${esc(product.title)}">
            <td>
              <div class="product-cell">
                <div class="product-list-image-wrap">${productImage(product)}</div>
                <div>
                  <b class="document-name" title="${esc(product.title)}">${esc(product.title || "Không có tên")}</b>
                  <div class="document-meta">${esc(product.vendor || "—")}</div>
                </div>
              </div>
            </td>
            <td><b>${esc(product.product_code || "—")}</b></td>
            <td><span class="category">${esc(product.product_type || "—")}</span></td>
            <td>${esc(product.colors || "—")}</td>
            <td><span class="badge${product.ai_ready ? "" : " inactive"}">${Number(product.embedding_count || 0)} / ${Number(product.image_count || 0)}</span></td>
            <td>${statusBadge(product)}</td>
            <td>${aiBadge(product)}</td>
            <td><button class="secondary small view-product" type="button" data-product-code="${esc(product.product_code)}">Xem</button></td>
          </tr>`,
        )
        .join("")
    : '<tr><td colspan="8" class="empty"><div class="empty-state"><div class="empty-icon">◇</div><span>Không tìm thấy sản phẩm.</span></div></td></tr>';
}

async function loadCatalog() {
  const query = $("catalogSearch").value.trim();
  const productType = $("catalogType").value;
  const status = $("catalogStatus").value;
  const offset = (catalogPage - 1) * catalogPageSize;
  $("catalogRows").innerHTML =
    '<tr><td colspan="8" class="empty"><div class="empty-state"><span class="spinner"></span><span>Đang tải sản phẩm…</span></div></td></tr>';
  try {
    const params = new URLSearchParams({
      search: query,
      product_type: productType,
      status,
      limit: String(catalogPageSize),
      offset: String(offset),
    });
    const data = await asJson(
      await fetch(`/admin/products/api/catalog?${params.toString()}`, {
        cache: "no-store",
      }),
    );
    catalogPages = Math.max(1, Math.ceil(Number(data.total || 0) / catalogPageSize));
    if (catalogPage > catalogPages) {
      catalogPage = catalogPages;
      return loadCatalog();
    }
    $("catalogTotal").textContent = Number(data.total || 0).toLocaleString("vi-VN");
    $("catalogTotalFooter").textContent = Number(data.total || 0).toLocaleString("vi-VN");
    $("catalogModel").textContent = data.embedding_model || "—";
    $("catalogProvider").textContent = data.provider === "qdrant" ? "Qdrant" : data.provider || "—";
    $("catalogType").innerHTML =
      '<option value="">Tất cả thể loại</option>' +
      (data.product_types || [])
        .map((value) => `<option value="${esc(value)}"${value === productType ? " selected" : ""}>${esc(value)}</option>`)
        .join("");
    $("catalogStatus").innerHTML =
      '<option value="">Tất cả trạng thái</option>' +
      (data.product_statuses || [])
        .map((value) => `<option value="${esc(value)}"${value === status ? " selected" : ""}>${esc(value)}</option>`)
        .join("");
    $("catalogPage").textContent = catalogPage;
    $("catalogPages").textContent = catalogPages;
    renderCatalogRows(Array.isArray(data.products) ? data.products : []);
    renderPagination();
  } catch (error) {
    $("catalogRows").innerHTML = `<tr><td colspan="8" class="empty bad"><div class="empty-state"><div class="empty-icon">!</div><span>${esc(error.message)}</span></div></td></tr>`;
    toast("Không tải được catalog", error.message, true);
  }
}

function closeProductDetail() {
  if ($("productDetailModal").open) $("productDetailModal").close();
}

function renderProductDetail(data) {
  const product = data.product || {};
  const variants = Array.isArray(data.variants) ? data.variants : [];
  const images = Array.isArray(data.images) ? data.images : [];
  const recognitionImages = Array.isArray(data.recognition_images)
    ? data.recognition_images
    : [];
  const activeImages = images.filter((image) => image.is_active !== false);
  const mainImage = activeImages.find((image) => image.source_url)?.source_url;
  $("productDetailTitle").textContent = product.title || "Chi tiết sản phẩm";
  $("productDetailMeta").textContent = [
    product.product_code,
    product.vendor,
    product.product_type,
  ]
    .filter(Boolean)
    .join(" · ");

  const variantHtml = variants.length
    ? variants
        .map(
          (variant) => `<tr>
            <td><b>${detailValue(variant.sku)}</b></td>
            <td>${detailValue(variant.color)}</td>
            <td>${detailValue(variant.size)}</td>
            <td>${moneyText(variant.price)}</td>
            <td>${detailValue(variant.inventory_quantity)}</td>
            <td><span class="status${variant.available ? "" : " inactive"}">${variant.available ? "Có hàng" : "Hết hàng"}</span></td>
          </tr>`,
        )
        .join("")
    : '<tr><td colspan="6" class="empty">Chưa có biến thể.</td></tr>';

  const imageHtml = activeImages.length
    ? activeImages
        .map(
          (image, index) => `<article class="product-image-card">
            ${image.source_url ? `<img src="${esc(image.source_url)}" alt="${esc(image.alt_text || product.title || `Ảnh ${index + 1}`)}" loading="lazy" />` : ""}
            <div class="product-image-info">
              <strong>${detailValue(image.color || `Ảnh ${index + 1}`)}</strong>
              <span>${image.embedded ? "✓ Đã embedding" : "Chưa embedding"}</span>
            </div>
          </article>`,
        )
        .join("")
    : '<p class="product-empty-text">Sản phẩm chưa có hình ảnh.</p>';

  const recognitionHtml = recognitionImages.length
    ? recognitionImages
        .map(
          (image, index) => `<article class="product-image-card">
            <img src="${esc(image.content_url)}?v=${encodeURIComponent(image.updated_at || "")}" alt="Ảnh nhận diện ${index + 1}" loading="lazy" />
            <div class="product-image-info"><strong>${detailValue(image.color || `Ảnh ${index + 1}`)}</strong><span>${image.embedded ? "✓ Đã cập nhật vector" : "Chưa embedding"}</span></div>
          </article>`,
        )
        .join("")
    : '<p class="product-empty-text">Chưa có ảnh marketing nhận diện.</p>';

  $("productDetailBody").innerHTML = `
    <section class="product-detail-overview">
      <div class="product-main-image-wrap">
        ${mainImage ? `<img class="product-main-image" src="${esc(mainImage)}" alt="${esc(product.title || product.product_code)}" />` : '<div class="product-no-image">◇</div>'}
      </div>
      <div class="product-info-grid">
        <div><span>Mã sản phẩm</span><strong>${detailValue(product.product_code)}</strong></div>
        <div><span>Thương hiệu</span><strong>${detailValue(product.vendor)}</strong></div>
        <div><span>Loại sản phẩm</span><strong>${detailValue(product.product_type)}</strong></div>
        <div><span>Chất liệu</span><strong>${detailValue(product.material)}</strong></div>
        <div><span>Trạng thái</span><strong>${detailValue(product.status)}</strong></div>
        <div><span>Cập nhật</span><strong>${dateText(product.updated_at || product.source_updated_at)}</strong></div>
      </div>
    </section>
    <section class="product-detail-section">
      <h3>Mô tả</h3>
      <p class="product-description">${detailValue(product.description || "Không có mô tả.")}</p>
    </section>
    <section class="product-detail-section">
      <div class="product-section-heading"><h3>Biến thể</h3><span class="count">${variants.length}</span></div>
      <div class="table-wrap"><table><thead><tr><th>SKU</th><th>Màu</th><th>Size</th><th>Giá</th><th>Tồn kho</th><th>Trạng thái</th></tr></thead><tbody>${variantHtml}</tbody></table></div>
    </section>
    <section class="product-detail-section">
      <div class="product-section-heading"><h3>Hình ảnh</h3><span class="count">${activeImages.length}</span></div>
      <div class="product-gallery">${imageHtml}</div>
    </section>
    <section class="product-detail-section recognition-section">
      <div class="product-section-heading"><div><h3>Ảnh marketing nhận diện</h3><p>Ảnh chỉ dùng để tìm đúng sản phẩm, không gửi cho khách.</p></div><span class="count">${recognitionImages.length}</span></div>
      <form id="recognitionImageForm" class="recognition-upload-form">
        <label><span>Chọn ảnh</span><input id="recognitionImageFile" type="file" accept="image/jpeg,image/png,image/webp" required /></label>
        <label><span>Màu sản phẩm</span><input id="recognitionImageColor" type="text" maxlength="100" placeholder="Ví dụ: Đen" /></label>
        <button id="recognitionImageUpload" class="primary" type="submit">Thêm ảnh và tạo vector</button>
      </form>
      <div class="product-gallery">${recognitionHtml}</div>
    </section>`;
  bindRecognitionImageForm(product.product_code || currentProductDetailCode);
}

function bindRecognitionImageForm(productCode) {
  const form = $("recognitionImageForm");
  if (!form || !productCode) return;
  form.onsubmit = async (event) => {
    event.preventDefault();
    const file = $("recognitionImageFile").files?.[0];
    if (!file) return;
    const button = $("recognitionImageUpload");
    button.disabled = true;
    button.textContent = "Đang tạo vector…";
    const body = new FormData();
    body.append("file", file);
    body.append("color", $("recognitionImageColor").value.trim());
    try {
      await asJson(
        await fetch(
          `/admin/products/api/catalog/${encodeURIComponent(productCode)}/recognition-images`,
          { method: "POST", body },
        ),
      );
      toast("Đã thêm ảnh marketing", `Ảnh nhận diện của ${productCode} đã được cập nhật.`);
      const refreshed = await asJson(
        await fetch(`/admin/products/api/catalog/${encodeURIComponent(productCode)}`, {
          cache: "no-store",
        }),
      );
      renderProductDetail(refreshed);
      loadCatalog();
    } catch (error) {
      button.disabled = false;
      button.textContent = "Thêm ảnh và tạo vector";
      toast("Không thêm được ảnh", error.message, true);
    }
  };
}

async function openProductDetail(code, trigger) {
  currentProductDetailCode = code;
  productDetailPreviousFocus = trigger || document.activeElement;
  $("productDetailTitle").textContent = "Đang tải sản phẩm…";
  $("productDetailMeta").textContent = code;
  $("productDetailBody").innerHTML =
    '<div class="product-detail-loading"><span class="spinner"></span>Đang tải sản phẩm…</div>';
  if (!$("productDetailModal").open) $("productDetailModal").showModal();
  document.body.classList.add("product-detail-open");
  try {
    const data = await asJson(
      await fetch(`/admin/products/api/catalog/${encodeURIComponent(code)}`, {
        cache: "no-store",
      }),
    );
    renderProductDetail(data);
  } catch (error) {
    $("productDetailTitle").textContent = "Không tải được sản phẩm";
    $("productDetailBody").innerHTML = `<div class="product-detail-empty">${esc(error.message)}</div>`;
  }
}

$("catalogRows").addEventListener("click", (event) => {
  const row = event.target.closest("tr[data-product-code]");
  if (!row) return;
  openProductDetail(row.dataset.productCode, event.target.closest("button") || row);
});

$("catalogRows").addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const row = event.target.closest("tr[data-product-code]");
  if (!row) return;
  event.preventDefault();
  openProductDetail(row.dataset.productCode, row);
});

$("productDetailClose").onclick = closeProductDetail;
$("productDetailModal").addEventListener("click", (event) => {
  if (event.target === $("productDetailModal")) closeProductDetail();
});
$("productDetailModal").addEventListener("close", () => {
  document.body.classList.remove("product-detail-open");
  if (productDetailPreviousFocus instanceof HTMLElement) productDetailPreviousFocus.focus();
});

$("catalogSearchButton").onclick = () => {
  catalogPage = 1;
  loadCatalog();
};
$("catalogRefreshButton").onclick = () => {
  $("catalogSearch").value = "";
  $("catalogType").value = "";
  $("catalogStatus").value = "";
  catalogPage = 1;
  loadCatalog();
};
$("catalogType").onchange = () => {
  catalogPage = 1;
  loadCatalog();
};
$("catalogStatus").onchange = () => {
  catalogPage = 1;
  loadCatalog();
};
$("catalogSearch").onkeydown = (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  catalogPage = 1;
  loadCatalog();
};
$("catalogPrev").onclick = () => {
  if (catalogPage <= 1) return;
  catalogPage -= 1;
  loadCatalog();
};
$("catalogNext").onclick = () => {
  if (catalogPage >= catalogPages) return;
  catalogPage += 1;
  loadCatalog();
};
$("catalogPageSize").onchange = () => {
  catalogPageSize = Number($("catalogPageSize").value) || 20;
  catalogPage = 1;
  loadCatalog();
};

loadCatalog();
