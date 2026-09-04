const userPage = {
  users: [],
  currentUserId: null,
  passwordUserId: null,
};

const userElement = (id) => document.getElementById(id);

function escapeUserHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function showUserNotice(message, error = false) {
  const notice = userElement("userNotice");
  notice.textContent = message;
  notice.className = `notice show${error ? " error" : ""}`;
}

async function userApi(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (response.status === 401) {
    const next = encodeURIComponent(window.location.pathname);
    window.location.replace(`/admin/login?next=${next}`);
    throw new Error("Phiên đăng nhập đã hết hạn.");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(data.detail || "Không thể thực hiện yêu cầu.");
  return data;
}

function userDate(value) {
  if (!value) return "Chưa đăng nhập";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : new Intl.DateTimeFormat("vi-VN", {
        dateStyle: "short",
        timeStyle: "short",
        timeZone: "Asia/Ho_Chi_Minh",
      }).format(date);
}

function roleOptions(role) {
  return [
    ["admin", "Quản trị viên"],
    ["manager", "Quản lý"],
    ["staff", "Nhân viên"],
  ]
    .map(
      ([value, label]) =>
        `<option value="${value}"${value === role ? " selected" : ""}>${label}</option>`,
    )
    .join("");
}

function initialsOf(user) {
  const source = (user.display_name || user.username || "?").trim();
  const parts = source.split(/\s+/).filter(Boolean);
  const letters =
    parts.length > 1
      ? parts[0][0] + parts[parts.length - 1][0]
      : source.slice(0, 2);
  return letters.toUpperCase();
}

function renderUsers() {
  const rows = userElement("userRows");
  if (!userPage.users.length) {
    rows.innerHTML =
      '<tr><td class="user-empty" colspan="5">Chưa có tài khoản.</td></tr>';
    return;
  }
  rows.innerHTML = userPage.users
    .map((user) => {
      const isSelf = Number(user.id) === Number(userPage.currentUserId);
      const roleCell = isSelf
        ? '<span class="badge protected-value" title="Không thể tự hạ quyền tài khoản đang đăng nhập">Quản trị viên</span>'
        : `<select class="row-role">${roleOptions(user.role)}</select>`;
      const statusCell = isSelf
        ? '<span class="badge user-status active" title="Không thể tự khóa tài khoản đang đăng nhập">Đang hoạt động</span>'
        : `<button class="status-switch${user.is_active ? " on" : ""}" type="button" role="switch" aria-checked="${Boolean(user.is_active)}" title="${user.is_active ? "Đang hoạt động — bấm để khóa" : "Đã khóa — bấm để mở lại"}"><span class="track"><span class="thumb"></span></span><span class="switch-label">${user.is_active ? "Hoạt động" : "Đã khóa"}</span></button>`;
      const actionsCell =
        '<div class="user-actions"><button class="password-button" type="button">Mật khẩu</button></div>';
      return `<tr data-user-id="${Number(user.id)}" data-active="${user.is_active ? "1" : "0"}">
      <td><div class="user-identity"><span class="user-avatar">${initialsOf(user)}</span><div class="user-id-text"><b>${escapeUserHtml(user.username)}</b>${user.display_name ? `<small>${escapeUserHtml(user.display_name)}</small>` : ""}${isSelf ? '<span class="current-user-note">Tài khoản của bạn</span>' : ""}</div></div></td>
      <td>${roleCell}</td>
      <td>${statusCell}</td>
      <td class="muted">${escapeUserHtml(userDate(user.last_login_at))}</td>
      <td>${actionsCell}</td>
    </tr>`;
    })
    .join("");

  rows.querySelectorAll(".row-role").forEach((select) => {
    select.addEventListener("change", () =>
      saveUserRole(select.closest("tr"), select),
    );
  });
  rows.querySelectorAll(".password-button").forEach((button) => {
    button.addEventListener("click", () =>
      openPasswordDialog(button.closest("tr")),
    );
  });
  rows.querySelectorAll(".status-switch").forEach((button) => {
    button.addEventListener("click", () =>
      toggleUserStatus(button.closest("tr"), button).catch((error) =>
        showUserNotice(error.message, true),
      ),
    );
  });
}

async function loadUsers() {
  try {
    const data = await userApi("/admin/users/api");
    userPage.users = data.users || [];
    userPage.currentUserId = data.current_user_id;
    userElement("userSummary").textContent =
      `${userPage.users.length} tài khoản · ${userPage.users.filter((item) => item.is_active).length} đang hoạt động`;
    renderUsers();
  } catch (error) {
    showUserNotice(error.message, true);
  }
}

async function saveUserRole(row, roleControl) {
  const id = Number(row.dataset.userId);
  const original = userPage.users.find((item) => Number(item.id) === id);
  const role = roleControl.value;
  roleControl.disabled = true;
  try {
    await userApi(`/admin/users/api/${id}`, {
      method: "PUT",
      body: JSON.stringify({
        display_name: original?.display_name ?? null,
        role,
        is_active: original?.is_active ?? true,
      }),
    });
    showUserNotice(`Đã đổi vai trò của ${original.username}.`);
    await loadUsers();
  } catch (error) {
    roleControl.value = original.role;
    showUserNotice(error.message, true);
  } finally {
    if (roleControl.isConnected) roleControl.disabled = false;
  }
}

async function toggleUserStatus(row, button) {
  const id = Number(row.dataset.userId);
  const original = userPage.users.find((item) => Number(item.id) === id);
  const nextActive = row.dataset.active !== "1";
  if (
    !nextActive &&
    !window.confirm(
      `Khóa tài khoản ${original?.username || id}? Phiên đăng nhập hiện tại của tài khoản này sẽ bị thu hồi.`,
    )
  )
    return;
  button.disabled = true;
  try {
    await userApi(`/admin/users/api/${id}`, {
      method: "PUT",
      body: JSON.stringify({
        display_name: original?.display_name ?? null,
        role: original?.role,
        is_active: nextActive,
      }),
    });
    row.dataset.active = nextActive ? "1" : "0";
    button.classList.toggle("on", nextActive);
    button.setAttribute("aria-checked", String(nextActive));
    button.title = nextActive
      ? "Đang hoạt động — bấm để khóa"
      : "Đã khóa — bấm để mở lại";
    button.querySelector(".switch-label").textContent = nextActive
      ? "Hoạt động"
      : "Đã khóa";
    showUserNotice(nextActive ? "Đã mở lại tài khoản." : "Đã khóa tài khoản.");
    await loadUsers();
  } catch (error) {
    showUserNotice(error.message, true);
  } finally {
    button.disabled = false;
  }
}

function openPasswordDialog(row) {
  const id = Number(row.dataset.userId);
  const user = userPage.users.find((item) => Number(item.id) === id);
  userPage.passwordUserId = id;
  userElement("passwordTarget").textContent =
    `Tài khoản: ${user?.username || id}`;
  userElement("passwordForm").reset();
  userElement("passwordDialog").showModal();
}

userElement("openCreateUser").addEventListener("click", () => {
  userElement("createUserForm").reset();
  userElement("createUserDialog").showModal();
});
document
  .querySelectorAll(".close-dialog")
  .forEach((button) =>
    button.addEventListener("click", () =>
      userElement("createUserDialog").close(),
    ),
  );
document
  .querySelectorAll(".close-password")
  .forEach((button) =>
    button.addEventListener("click", () =>
      userElement("passwordDialog").close(),
    ),
  );
userElement("refreshUsers").addEventListener("click", loadUsers);

userElement("createUserForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const password = userElement("createPassword").value;
  if (password !== userElement("createPasswordConfirm").value) {
    showUserNotice("Hai lần nhập mật khẩu không giống nhau.", true);
    return;
  }
  const button = userElement("createUserButton");
  button.disabled = true;
  try {
    await userApi("/admin/users/api", {
      method: "POST",
      body: JSON.stringify({
        username: userElement("createUsername").value.trim(),
        display_name: userElement("createDisplayName").value.trim() || null,
        role: userElement("createRole").value,
        password,
      }),
    });
    userElement("createUserDialog").close();
    showUserNotice("Đã tạo tài khoản mới.");
    await loadUsers();
  } catch (error) {
    showUserNotice(error.message, true);
  } finally {
    button.disabled = false;
  }
});

userElement("passwordForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const password = userElement("newPassword").value;
  if (password !== userElement("newPasswordConfirm").value) {
    showUserNotice("Hai lần nhập mật khẩu không giống nhau.", true);
    return;
  }
  const button = userElement("savePasswordButton");
  button.disabled = true;
  try {
    const data = await userApi(
      `/admin/users/api/${userPage.passwordUserId}/password`,
      {
        method: "POST",
        body: JSON.stringify({ password }),
      },
    );
    userElement("passwordDialog").close();
    if (data.session_revoked) {
      window.location.replace("/admin/login");
      return;
    }
    showUserNotice("Đã đổi mật khẩu và thu hồi các phiên cũ.");
    await loadUsers();
  } catch (error) {
    showUserNotice(error.message, true);
  } finally {
    button.disabled = false;
  }
});

loadUsers();
