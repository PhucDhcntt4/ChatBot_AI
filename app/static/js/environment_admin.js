const environmentState = {
  data: null,
  changes: new Map(),
  secretsVisible: false,
};

const environmentElement = (id) => document.getElementById(id);

async function environmentApi(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || "Không thể xử lý cấu hình môi trường.");
  }
  return data;
}

function showEnvironmentNotice(message, error = false) {
  const notice = environmentElement("environmentNotice");
  notice.textContent = message;
  notice.classList.add("show");
  notice.classList.toggle("error", error);
}

function clearEnvironmentNotice() {
  const notice = environmentElement("environmentNotice");
  notice.textContent = "";
  notice.className = "notice";
}

function updateSaveState() {
  const count = environmentState.changes.size;
  const button = environmentElement("saveEnvironment");
  button.disabled = count === 0;
  button.textContent = count ? `Lưu thay đổi (${count})` : "Lưu thay đổi";
  document.title = `${count ? `(${count}) ` : ""}Biến môi trường · Đông Hải AI`;
}

function recordChange(row, variable, input, forceClear = false) {
  let changed = false;
  let value = input.value;
  if (forceClear) value = "";
  changed = value !== variable.value;

  if (changed) {
    environmentState.changes.set(variable.name, value);
  } else {
    environmentState.changes.delete(variable.name);
  }
  row.classList.toggle("changed", changed);
  updateSaveState();
}

function createVariableEditor(variable, row) {
  const editor = document.createElement("div");
  editor.className = "environment-editor";
  let input;

  if (variable.kind === "boolean") {
    input = document.createElement("select");
    for (const value of ["true", "false"]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value === "true" ? "Bật (true)" : "Tắt (false)";
      input.appendChild(option);
    }
    input.value = variable.value.toLowerCase();
    input.addEventListener("change", () => recordChange(row, variable, input));
    editor.appendChild(input);
    return editor;
  }

  input = document.createElement("input");
  input.type = variable.sensitive ? "password" : variable.kind === "number" ? "number" : "text";
  input.name = variable.name;
  input.autocomplete = "off";
  if (variable.kind === "number") input.step = "any";

  if (variable.sensitive) {
    input.value = variable.value;
    input.placeholder = variable.configured
      ? "Giá trị đang được ẩn"
      : "Chưa cấu hình";
    const wrapper = document.createElement("div");
    wrapper.className = "environment-secret-editor";
    const toggleButton = document.createElement("button");
    toggleButton.type = "button";
    toggleButton.className = "environment-toggle-secret";
    toggleButton.textContent = "Hiện";
    toggleButton.addEventListener("click", () => {
      const visible = input.type === "password";
      input.type = visible ? "text" : "password";
      input.dataset.secretVisible = visible ? "true" : "false";
      toggleButton.textContent = visible ? "Ẩn" : "Hiện";
    });
    const clearButton = document.createElement("button");
    clearButton.type = "button";
    clearButton.className = "environment-clear-secret";
    clearButton.textContent = "Xóa giá trị";
    clearButton.addEventListener("click", () => {
      const marked = clearButton.classList.toggle("marked");
      clearButton.textContent = marked ? "Sẽ xóa" : "Xóa giá trị";
      input.value = marked ? "" : variable.value;
      input.disabled = marked;
      recordChange(row, variable, input, marked);
    });
    input.addEventListener("input", () => {
      clearButton.classList.remove("marked");
      clearButton.textContent = "Xóa giá trị";
      recordChange(row, variable, input);
    });
    wrapper.append(input, toggleButton, clearButton);
    editor.appendChild(wrapper);
    return editor;
  }

  input.value = variable.value;
  input.addEventListener("input", () => recordChange(row, variable, input));
  editor.appendChild(input);
  return editor;
}

function renderEnvironment(data) {
  const container = environmentElement("environmentSections");
  container.replaceChildren();

  for (const section of data.sections || []) {
    const sectionNode = document.createElement("section");
    sectionNode.className = "environment-section";
    sectionNode.dataset.search = [
      section.title,
      ...(section.notes || []),
      ...(section.variables || []).map((item) => item.name),
    ].join(" ").toLowerCase();

    const head = document.createElement("header");
    head.className = "environment-section-head";
    const title = document.createElement("h3");
    title.textContent = section.title || "Cấu hình chung";
    head.appendChild(title);
    for (const note of section.notes || []) {
      const noteNode = document.createElement("p");
      noteNode.className = "environment-section-note";
      noteNode.textContent = `# ${note}`;
      head.appendChild(noteNode);
    }
    sectionNode.appendChild(head);

    for (const variable of section.variables || []) {
      const row = document.createElement("div");
      row.className = "environment-row";
      row.dataset.search = `${variable.name} ${variable.description || ""}`.toLowerCase();

      const information = document.createElement("div");
      const nameLine = document.createElement("div");
      nameLine.className = "environment-name";
      const name = document.createElement("code");
      name.textContent = variable.name;
      nameLine.appendChild(name);
      if (variable.sensitive) {
        const badge = document.createElement("span");
        badge.className = "environment-badge";
        badge.textContent = "Bí mật";
        nameLine.appendChild(badge);
      }
      if (variable.duplicate) {
        const badge = document.createElement("span");
        badge.className = "environment-badge";
        badge.textContent = "Trùng khóa";
        nameLine.appendChild(badge);
      }
      information.appendChild(nameLine);

      const description = document.createElement("p");
      description.className = `environment-description${variable.description ? "" : " empty"}`;
      description.textContent = variable.description
        ? `# ${variable.description}`
        : "Chưa có ghi chú # trong file .env";
      information.appendChild(description);

      row.append(information, createVariableEditor(variable, row));
      sectionNode.appendChild(row);
    }
    container.appendChild(sectionNode);
  }

  if (!container.children.length) {
    const empty = document.createElement("div");
    empty.className = "environment-empty";
    empty.textContent = "File .env chưa có biến môi trường nào.";
    container.appendChild(empty);
  }
}

function filterEnvironment() {
  const query = environmentElement("environmentSearch").value.trim().toLowerCase();
  document.querySelectorAll(".environment-section").forEach((section) => {
    let visibleRows = 0;
    section.querySelectorAll(".environment-row").forEach((row) => {
      const visible = !query || row.dataset.search.includes(query);
      row.hidden = !visible;
      if (visible) visibleRows += 1;
    });
    const sectionMatches = !query || section.dataset.search.includes(query);
    section.hidden = query ? !visibleRows && !sectionMatches : false;
  });
}

async function loadEnvironment() {
  const reloadButton = environmentElement("reloadEnvironment");
  reloadButton.disabled = true;
  clearEnvironmentNotice();
  try {
    const data = await environmentApi("/admin/environment/api");
    environmentState.data = data;
    environmentState.changes.clear();
    environmentState.secretsVisible = false;
    environmentElement("toggleEnvironmentSecrets").textContent = "Hiện giá trị";
    renderEnvironment(data);
    filterEnvironment();
    updateSaveState();
    const updated = data.updated_at
      ? new Date(data.updated_at).toLocaleString("vi-VN")
      : "không rõ";
    environmentElement("environmentSummary").textContent =
      `${data.variable_count || 0} biến · cập nhật file gần nhất ${updated}`;
  } catch (error) {
    showEnvironmentNotice(error.message, true);
  } finally {
    reloadButton.disabled = false;
  }
}

function openEnvironmentConfirmation() {
  if (!environmentState.changes.size) return;
  const list = environmentElement("environmentChangedNames");
  list.replaceChildren();
  [...environmentState.changes.keys()].sort().forEach((name) => {
    const item = document.createElement("code");
    item.textContent = name;
    list.appendChild(item);
  });
  environmentElement("environmentConfirmDialog").showModal();
}

async function saveEnvironment() {
  if (!environmentState.changes.size) return;
  const button = environmentElement("confirmSaveEnvironment");
  button.disabled = true;
  try {
    const result = await environmentApi("/admin/environment/api", {
      method: "PUT",
      body: JSON.stringify({
        changes: [...environmentState.changes.entries()].map(([name, value]) => ({ name, value })),
      }),
    });
    environmentElement("environmentConfirmDialog").close();
    environmentState.changes.clear();
    updateSaveState();
    showEnvironmentNotice(
      `Đã lưu ${result.updated_count} biến môi trường. Ứng dụng đang tự nạp lại cấu hình mới…`,
    );
    if (result.reload_scheduled) {
      waitForEnvironmentReload(result.previous_runtime_id);
    }
  } catch (error) {
    environmentElement("environmentConfirmDialog").close();
    showEnvironmentNotice(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function waitForEnvironmentReload(previousRuntimeId) {
  await new Promise((resolve) => window.setTimeout(resolve, 1000));
  for (let attempt = 0; attempt < 30; attempt += 1) {
    try {
      const response = await fetch(`/health?environment_reload=${Date.now()}`, {
        cache: "no-store",
      });
      if (response.ok) {
        const health = await response.json();
        if (
          !previousRuntimeId ||
          (health.runtime_id && health.runtime_id !== previousRuntimeId)
        ) {
          window.location.reload();
          return;
        }
      }
    } catch (_) {
      // The short connection failure is expected while Uvicorn restarts.
    }
    await new Promise((resolve) => window.setTimeout(resolve, 750));
  }
  showEnvironmentNotice(
    "File .env đã được lưu nhưng ứng dụng chưa khởi động lại. Hãy chạy lại start.ps1 hoặc khởi động lại service app và worker.",
    true,
  );
}

environmentElement("environmentSearch").addEventListener("input", filterEnvironment);
environmentElement("toggleEnvironmentSecrets").addEventListener("click", () => {
  environmentState.secretsVisible = !environmentState.secretsVisible;
  document.querySelectorAll('.environment-editor input[type="password"], .environment-editor input[data-secret-visible="true"]').forEach((input) => {
    input.type = environmentState.secretsVisible ? "text" : "password";
    input.dataset.secretVisible = environmentState.secretsVisible ? "true" : "false";
    const toggle = input.parentElement?.querySelector(".environment-toggle-secret");
    if (toggle) toggle.textContent = environmentState.secretsVisible ? "Ẩn" : "Hiện";
  });
  environmentElement("toggleEnvironmentSecrets").textContent =
    environmentState.secretsVisible ? "Ẩn giá trị" : "Hiện giá trị";
});
environmentElement("reloadEnvironment").addEventListener("click", () => {
  if (
    environmentState.changes.size &&
    !window.confirm("Bỏ toàn bộ thay đổi chưa lưu và tải lại file .env?")
  ) return;
  loadEnvironment();
});
environmentElement("saveEnvironment").addEventListener("click", openEnvironmentConfirmation);
environmentElement("confirmSaveEnvironment").addEventListener("click", saveEnvironment);

loadEnvironment();
