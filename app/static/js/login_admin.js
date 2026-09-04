const $ = (id) => document.getElementById(id);

function notice(message, error = true) {
  const element = $("loginNotice");
  element.textContent = message;
  element.className = `notice show${error ? " error" : " success"}`;
}

$("togglePassword").addEventListener("click", () => {
  const input = $("loginPass");
  const isHidden = input.type === "password";
  input.type = isHidden ? "text" : "password";
  $("togglePassword").querySelector(".eye-open").hidden = isHidden;
  $("togglePassword").querySelector(".eye-closed").hidden = !isHidden;
  $("togglePassword").title = isHidden ? "Ẩn mật khẩu" : "Hiện mật khẩu";
  $("togglePassword").setAttribute(
    "aria-label",
    isHidden ? "Ẩn mật khẩu" : "Hiện mật khẩu",
  );
});

$("forgotLink").addEventListener("click", (event) => {
  event.preventDefault();
  notice("Vui lòng liên hệ quản trị viên hệ thống để đặt lại mật khẩu.", false);
});

$("loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const username = $("loginUser").value.trim();
  const password = $("loginPass").value;
  const remember = $("rememberMe").checked;
  if (!username || !password) return;

  const button = $("loginButton");
  button.disabled = true;
  const originalLabel = button.textContent;
  button.textContent = "Đang đăng nhập…";
  $("loginNotice").className = "notice";

  try {
    const redirectTo = new URLSearchParams(window.location.search).get("next");
    const response = await fetch("/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username,
        password,
        remember,
        redirect_to: redirectTo,
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || "Sai tài khoản hoặc mật khẩu.");
    }
    window.location.replace(data.redirect || "/admin/products");
  } catch (error) {
    notice(error.message || "Không thể đăng nhập.", true);
    button.disabled = false;
    button.textContent = originalLabel;
  }
});
