(() => {
  "use strict";

  const messages = document.getElementById("messages");
  const form = document.getElementById("chatForm");
  const input = document.getElementById("messageInput");
  const sendButton = document.getElementById("sendButton");
  const attachButton = document.getElementById("attachButton");
  const imageInput = document.getElementById("imageInput");
  const resetButton = document.getElementById("resetButton");
  const connectionStatus = document.getElementById("connectionStatus");
  const sessionKey = "dong_hai_v2_session_id";

  function sessionId() {
    let value = sessionStorage.getItem(sessionKey);
    if (!value) {
      value = `web-${crypto.randomUUID()}`;
      sessionStorage.setItem(sessionKey, value);
    }
    return value;
  }

  function scrollBottom() {
    messages.scrollTop = messages.scrollHeight;
  }

  function addMessage(text, who, extraClass = "") {
    const article = document.createElement("article");
    article.className = `message ${who} ${extraClass}`.trim();
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    article.appendChild(bubble);
    messages.appendChild(article);
    scrollBottom();
    return article;
  }

  function addTyping() {
    const item = addMessage("", "bot", "typing");
    item.querySelector(".bubble").innerHTML = "<i></i><i></i><i></i>";
    return item;
  }

  function addMedia(media) {
    (media || []).forEach((group) => {
      const urls = [...new Set(group.image_urls || [])].slice(0, 4);
      if (!urls.length) return;
      const album = document.createElement("div");
      album.className = "album";
      urls.forEach((url) => {
        const image = document.createElement("img");
        image.src = url;
        image.alt = `Sản phẩm ${group.product_code}`;
        image.loading = "lazy";
        album.appendChild(image);
      });
      const label = document.createElement("div");
      label.className = "album-label";
      label.textContent = `${group.product_code}${group.color ? ` · ${group.color}` : ""}`;
      album.appendChild(label);
      messages.appendChild(album);
    });
    scrollBottom();
  }

  function addUserImage(file) {
    const article = document.createElement("article");
    article.className = "message user-preview";
    const image = document.createElement("img");
    image.src = URL.createObjectURL(file);
    image.alt = "Ảnh khách gửi";
    image.addEventListener("load", () => URL.revokeObjectURL(image.src), { once: true });
    article.appendChild(image);
    messages.appendChild(article);
    scrollBottom();
  }

  function resizeInput() {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 110)}px`;
  }

  async function sendMessage(rawMessage) {
    const message = rawMessage.trim();
    if (!message || sendButton.disabled) return;
    addMessage(message, "user");
    input.value = "";
    resizeInput();
    sendButton.disabled = true;
    connectionStatus.textContent = "Đang xử lý...";
    const typing = addTyping();

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          session_id: sessionId(),
          channel: "web",
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Không thể xử lý yêu cầu");
      typing.remove();
      addMessage(data.message, "bot");
      addMedia(data.media);
      const seconds = data.timing?.total;
      connectionStatus.textContent = seconds == null ? "Đã trả lời" : `Đã trả lời trong ${seconds}s`;
    } catch (error) {
      typing.remove();
      addMessage(`Hiện tại em chưa thể xử lý yêu cầu: ${error.message}`, "bot", "error");
      connectionStatus.textContent = "Có lỗi kết nối";
    } finally {
      sendButton.disabled = false;
      input.focus();
    }
  }

  async function sendImage(file) {
    if (!file || sendButton.disabled) return;
    addUserImage(file);
    const caption = input.value.trim();
    if (caption) addMessage(caption, "user");
    input.value = "";
    resizeInput();
    sendButton.disabled = true;
    attachButton.disabled = true;
    connectionStatus.textContent = "Đang nhận diện ảnh...";
    const typing = addTyping();
    const body = new FormData();
    body.append("image", file);
    body.append("session_id", sessionId());
    body.append("channel", "web");
    body.append("caption", caption);
    try {
      const response = await fetch("/api/chat/image", { method: "POST", body });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Không thể nhận diện ảnh");
      typing.remove();
      addMessage(data.message, "bot");
      addMedia(data.media);
      connectionStatus.textContent = `Đã nhận diện trong ${data.timing?.total ?? "—"}s`;
    } catch (error) {
      typing.remove();
      addMessage(`Hiện tại em chưa thể nhận diện ảnh: ${error.message}`, "bot", "error");
      connectionStatus.textContent = "Có lỗi nhận diện ảnh";
    } finally {
      imageInput.value = "";
      sendButton.disabled = false;
      attachButton.disabled = false;
      input.focus();
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage(input.value);
  });

  input.addEventListener("input", resizeInput);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  attachButton.addEventListener("click", () => imageInput.click());
  imageInput.addEventListener("change", () => sendImage(imageInput.files[0]));

  document.getElementById("suggestions").addEventListener("click", (event) => {
    if (event.target.tagName === "BUTTON") sendMessage(event.target.textContent);
  });

  resetButton.addEventListener("click", async () => {
    const id = sessionId();
    await fetch("/api/chat/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: id, channel: "web" }),
    });
    sessionStorage.removeItem(sessionKey);
    messages.innerHTML = "";
    addMessage("👋 Hội thoại mới đã bắt đầu. Anh/chị cần em hỗ trợ gì ạ?", "bot");
    connectionStatus.textContent = "Sẵn sàng";
  });
})();
