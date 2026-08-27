(function () {
  const path = window.location.pathname;
  const links = [
    ["/admin/products", "◫", "Sản phẩm"],
    ["/admin/knowledge", "▤", "Knowledge"],
    ["/admin/prompts", "✎", "Prompt"],
    ["/admin/conversations", "☰", "Hội thoại"],
  ];
  const sidebar = document.querySelector(".admin-sidebar");
  if (sidebar) {
    sidebar.innerHTML = `
      <a class="admin-sidebar-brand" href="/admin/products">
        <img src="/static/assets/logo.jpg" alt="Đông Hải"><span>Đông Hải AI</span>
      </a>
      <nav>${links.map(([href, icon, label]) => `<a href="${href}" class="${path.startsWith(href) ? "active" : ""}"><span>${icon}</span>${label}</a>`).join("")}</nav>`;
  }

  if (!document.getElementById("chatPanel")) {
    document.body.insertAdjacentHTML("beforeend", `
      <button class="ck-launcher" id="chatLauncher" type="button" aria-expanded="false"><img src="/static/assets/logo.jpg" alt=""><span>Chat ngay</span></button>
      <section class="ck-panel" id="chatPanel" role="dialog" aria-label="Trợ lý Đông Hải" aria-hidden="true">
        <div class="ck-head">
          <button class="ck-reset" id="chatReset" type="button" title="Hội thoại mới" aria-label="Hội thoại mới">↻</button>
          <img src="/static/assets/logo.jpg" alt="Đông Hải"><h3>Chat với đội ngũ hỗ trợ<br>của chúng tôi</h3>
        </div>
        <div class="ck-body" id="chatBody"><div class="ck-msg bot">👋 Xin chào anh/chị! Em là trợ lý AI của Đông Hải. Anh/chị cần em hỗ trợ gì ạ?</div></div>
        <div class="ck-foot"><div class="ck-input-row">
          <button class="ck-attach" id="chatAttach" type="button" aria-label="Gửi ảnh">📷</button>
          <input id="chatImage" type="file" accept="image/jpeg,image/png,image/webp" hidden>
          <textarea id="chatInput" placeholder="Tin nhắn…" rows="1" aria-label="Nhập tin nhắn"></textarea>
          <button class="ck-send" id="chatSend" type="button" aria-label="Gửi"><svg viewBox="0 0 24 24"><path d="M3.7 4.35a1 1 0 0 1 1.08-.16l15.1 6.9a1 1 0 0 1 0 1.82l-15.1 6.9a1 1 0 0 1-1.38-1.08L4.75 13 12.5 12 4.75 11 3.4 5.27a1 1 0 0 1 .3-.92Z"/></svg></button>
        </div></div><div class="ck-powered">Được phát triển bởi <b>Đông Hải</b></div>
      </section>
      <button class="ck-close" id="chatClose" type="button" aria-label="Đóng trợ lý">×</button>
      <div class="ck-lightbox" id="imageLightbox" role="dialog" aria-modal="true" hidden>
        <button class="ck-lightbox-close" id="lightboxClose" type="button">×</button>
        <button class="ck-lightbox-nav previous" id="lightboxPrev" type="button">‹</button>
        <figure class="ck-lightbox-content"><img id="lightboxImage" src="" alt=""><figcaption id="lightboxCaption"></figcaption></figure>
        <button class="ck-lightbox-nav next" id="lightboxNext" type="button">›</button>
      </div>`);
  }

  window.DongHaiSharedChat = true;
  const $ = (id) => document.getElementById(id);
  const GREETING = "👋 Xin chào anh/chị! Em là trợ lý AI của Đông Hải. Anh/chị cần em hỗ trợ gì ạ?";
  const sessionKey = "dong_hai_chat_session";
  let busy = false, lightboxUrls = [], lightboxIndex = 0;
  function sessionId() { let id = localStorage.getItem(sessionKey); if (!id) { id = crypto.randomUUID(); localStorage.setItem(sessionKey, id); } return id; }
  function transcriptKey(id = sessionId()) { return `dong_hai_chat_transcript:${id}`; }
  function loadTranscript() { try { const data = JSON.parse(localStorage.getItem(transcriptKey()) || "[]"); return Array.isArray(data) ? data : []; } catch { return []; } }
  function persist(item) { const items = loadTranscript(); items.push(item); localStorage.setItem(transcriptKey(), JSON.stringify(items.slice(-60))); }
  function addMessage(text, who, save = true) { const node = document.createElement("div"); node.className = `ck-msg ${who}`; node.textContent = text; $("chatBody").appendChild(node); $("chatBody").scrollTop = $("chatBody").scrollHeight; if (save) persist({type:"message", who, text}); return node; }
  function addAlbums(media, save = true) {
    const stored = [];
    (media || []).forEach((product) => { const urls = (product.image_urls || []).slice(0, 4); if (!urls.length) return; stored.push({...product, image_urls:urls}); const album = document.createElement("div"); album.className = `ck-product-album count-${urls.length}${urls.length === 1 ? " single" : ""}`; urls.forEach((url, index) => { const image = document.createElement("img"); image.src = url; image.alt = `${product.product_name || product.product_code || "Sản phẩm"}, ảnh ${index + 1}`; image.loading = "lazy"; image.onclick = () => openLightbox(urls, index, product.product_name || product.product_code); album.appendChild(image); }); $("chatBody").appendChild(album); });
    if (save && stored.length) persist({type:"albums", products:stored}); $("chatBody").scrollTop = $("chatBody").scrollHeight;
  }
  function restore() { const items = loadTranscript(); if (!items.length) return; $("chatBody").replaceChildren(); items.forEach((item) => item.type === "albums" ? addAlbums(item.products, false) : item.text && addMessage(item.text, item.who === "user" ? "user" : "bot", false)); }
  function renderResponse(data) {
    const blocks = Array.isArray(data.content_blocks) ? data.content_blocks : [];
    if (!blocks.length) { if (data.message) addMessage(data.message, "bot"); addAlbums(data.media); return; }
    blocks.forEach((block) => {
      if (block.type === "text" && block.text) addMessage(block.text, "bot");
      if (block.type === "media" && block.media) addAlbums([block.media]);
    });
  }
  function setBusy(value) { busy = value; $("chatSend").disabled = value; $("chatAttach").disabled = value; $("chatReset").disabled = value; }
  function typing() { const node = document.createElement("div"); node.className = "ck-msg bot typing"; node.innerHTML = "<span></span><span></span><span></span>"; $("chatBody").appendChild(node); return node; }
  function openLightbox(urls, index, name) { lightboxUrls = urls; lightboxIndex = index; showLightbox(name); $("imageLightbox").hidden = false; }
  function showLightbox(name) { const url = lightboxUrls[lightboxIndex]; $("lightboxImage").src = url; $("lightboxCaption").textContent = `${name || "Sản phẩm"} · ${lightboxIndex + 1}/${lightboxUrls.length}`; }
  function closeLightbox() { $("imageLightbox").hidden = true; $("lightboxImage").removeAttribute("src"); lightboxUrls = []; }
  async function sendText() {
    const text = $("chatInput").value.trim(); if (!text || busy) return; setBusy(true); addMessage(text, "user"); $("chatInput").value = ""; const waiting = typing();
    try { const response = await fetch("/api/chat", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({message:text, session_id:sessionId(), channel:"web"})}); const data = await response.json(); if (!response.ok) throw new Error(data.detail || "Không thể gửi tin nhắn"); waiting.remove(); renderResponse(data); } catch (error) { waiting.remove(); addMessage(error.message || "Trợ lý chưa thể kết nối. Anh/chị thử lại giúp em nhé.", "bot"); } finally { setBusy(false); }
  }
  async function sendImage(file) {
    if (!file || busy) return; if (!/^image\/(jpeg|png|webp)$/i.test(file.type) || file.size > 10 * 1024 * 1024) { addMessage("Ảnh cần là JPG, PNG hoặc WEBP và không quá 10 MB ạ.", "bot"); return; }
    setBusy(true); const caption = $("chatInput").value.trim(); const preview = document.createElement("div"); preview.className = "ck-msg user-image"; const image = document.createElement("img"); image.src = URL.createObjectURL(file); preview.appendChild(image); $("chatBody").appendChild(preview); if (caption) addMessage(caption, "user"); $("chatInput").value = ""; const waiting = typing();
    const form = new FormData(); form.append("image", file); form.append("caption", caption); form.append("session_id", sessionId()); form.append("channel", "web");
    try { const response = await fetch("/api/chat/image", {method:"POST", body:form}); const data = await response.json(); if (!response.ok) throw new Error(data.detail || "Không thể xử lý ảnh"); waiting.remove(); renderResponse(data); } catch (error) { waiting.remove(); addMessage(error.message, "bot"); } finally { setBusy(false); $("chatImage").value = ""; }
  }
  $("chatLauncher").onclick = () => { $("chatPanel").classList.add("open"); $("chatLauncher").classList.add("hidden"); $("chatClose").classList.add("open"); $("chatInput").focus(); };
  $("chatClose").onclick = () => { $("chatPanel").classList.remove("open"); $("chatLauncher").classList.remove("hidden"); $("chatClose").classList.remove("open"); };
  $("chatSend").onclick = sendText; $("chatAttach").onclick = () => $("chatImage").click(); $("chatImage").onchange = () => sendImage($("chatImage").files[0]);
  $("chatInput").onkeydown = (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendText(); } };
  $("chatReset").onclick = async () => { if (busy) return; const oldId = sessionId(); setBusy(true); try { await fetch("/api/chat/reset", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({session_id:oldId, channel:"web"})}); localStorage.removeItem(transcriptKey(oldId)); localStorage.setItem(sessionKey, crypto.randomUUID()); $("chatBody").replaceChildren(); addMessage(GREETING, "bot"); } finally { setBusy(false); } };
  $("lightboxClose").onclick = closeLightbox; $("lightboxPrev").onclick = () => { lightboxIndex = (lightboxIndex - 1 + lightboxUrls.length) % lightboxUrls.length; showLightbox(); }; $("lightboxNext").onclick = () => { lightboxIndex = (lightboxIndex + 1) % lightboxUrls.length; showLightbox(); };
  restore();
})();
