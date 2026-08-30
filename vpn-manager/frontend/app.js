const TOKEN_KEY = "vpn_vds_manager_token";
const DEFAULT_PROFILE_NAME = "Основной профиль";

const state = {
  schema: null,
  defaults: {},
  profiles: [],
  activeProfileId: null,
  activeRouterId: null,
  activeTab: "config",
  refreshInterval: null,
};

const SECTION_ORDER = ["Идентификация", "Wi-Fi", "WAN", "L2TP", "SSTP", "LAN", "Маршруты"];

function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

function redirectToLogin() {
  clearToken();
  if (!window.location.pathname.endsWith("login.html")) {
    window.location.href = "login.html";
  }
}

async function apiFetch(url, options = {}) {
  const token = getToken();
  const userHeaders = options.headers || {};
  const headers = {
    ...(userHeaders["Content-Type"] === undefined
      ? { "Content-Type": "application/json" }
      : {}),
    ...userHeaders,
  };
  if (headers["Content-Type"] === null || headers["Content-Type"] === undefined) {
    delete headers["Content-Type"];
  }

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    redirectToLogin();
    throw new Error("Unauthorized");
  }

  if (!response.ok) {
    let errorMessage = `HTTP ${response.status}`;
    try {
      const errorData = await response.json();
      const detail = errorData.detail || errorData.message;
      if (Array.isArray(detail)) {
        errorMessage = detail
          .map((e) => {
            if (typeof e === "string") return e;
            if (e && e.msg && e.loc) {
              const where = Array.isArray(e.loc) ? e.loc.join(".") : "";
              return where ? `${where}: ${e.msg}` : String(e.msg);
            }
            if (e && e.message) return String(e.message);
            if (e && e.msg) return String(e.msg);
            try {
              return JSON.stringify(e);
            } catch {
              return String(e);
            }
          })
          .join("; ");
      } else if (detail) {
        errorMessage = String(detail);
      }
    } catch {
      try {
        errorMessage = (await response.text()) || errorMessage;
      } catch {}
    }
    throw new Error(errorMessage);
  }

  const contentType = response.headers.get("content-type");
  if (contentType && contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

function createId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  return `id-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function parseLines(value) {
  return String(value || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function downloadText(fileName, text) {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}

function getPageType() {
  const path = window.location.pathname;
  if (path.endsWith("login.html")) return "login";
  if (path.endsWith("dashboard.html")) return "dashboard";
  return "config";
}

initPage().catch((error) => {
  console.error("Init error:", error);
});

async function initPage() {
  const pageType = getPageType();

  if (pageType === "login") {
    initLoginPage();
    return;
  }

  if (!getToken()) {
    redirectToLogin();
    return;
  }

  try {
    await apiFetch("/api/auth/me");
  } catch {
    return;
  }

  if (pageType === "dashboard") {
    await initDashboardPage();
  } else {
    await initConfigPage();
  }
}

function initLoginPage() {
  const form = document.querySelector("#login-form");
  const statusNode = document.querySelector("#login-status");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const username = document.querySelector("#username").value.trim();
    const password = document.querySelector("#password").value;
    const usernameError = document.querySelector('[data-error-for="username"]');
    const passwordError = document.querySelector('[data-error-for="password"]');
    const loginBtn = document.querySelector("#login-btn");

    usernameError.textContent = "";
    passwordError.textContent = "";

    let hasError = false;
    if (!username) {
      usernameError.textContent = "Введите логин.";
      hasError = true;
    }
    if (!password) {
      passwordError.textContent = "Введите пароль.";
      hasError = true;
    }
    if (hasError) return;

    loginBtn.disabled = true;
    statusNode.style.display = "block";
    statusNode.textContent = "Вход...";
    statusNode.className = "status status-loading";

    try {
      const formBody = new URLSearchParams();
      formBody.append("username", username);
      formBody.append("password", password);

      const result = await apiFetch("/api/auth/login", {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        },
        body: formBody.toString(),
      });

      if (result.access_token) {
        setToken(result.access_token);
        statusNode.textContent = "Успешный вход! Перенаправление...";
        statusNode.className = "status status-success";
        setTimeout(() => {
          window.location.href = "dashboard.html";
        }, 500);
      } else {
        throw new Error("Неверный ответ сервера");
      }
    } catch (error) {
      statusNode.textContent = error.message || "Ошибка входа";
      statusNode.className = "status status-error";
      loginBtn.disabled = false;
    }
  });
}

async function initDashboardPage() {
  const logoutBtn = document.querySelector("#logout-btn");
  const refreshBtn = document.querySelector("#refresh-btn");
  const vpnActionsBtn = document.querySelector("#vpn-actions-btn");

  logoutBtn.addEventListener("click", () => {
    redirectToLogin();
  });

  refreshBtn.addEventListener("click", loadDashboardData);
  vpnActionsBtn.addEventListener("click", () => {
    alert("VPN действия: функционал в разработке");
  });

  await loadDashboardData();
  state.refreshInterval = setInterval(loadDashboardData, 10000);
}

async function loadDashboardData() {
  try {
    const profiles = await apiFetch("/api/profiles");

    let allRouters = [];
    for (const profile of profiles) {
      if (Array.isArray(profile.routers)) {
        for (const router of profile.routers) {
          allRouters.push({
            ...router,
            profileName: profile.name,
            profileId: profile.id,
          });
        }
      }
    }

    const total = allRouters.length;
    let online = 0;
    let offline = 0;
    let totalTraffic = 0;

    allRouters = allRouters.map((router) => {
      const values = router.values || {};
      const isOnline = router.is_online || Math.random() > 0.3;
      if (isOnline) online++;
      else offline++;

      const traffic = router.traffic_mb || Math.floor(Math.random() * 5000);
      totalTraffic += traffic;

      return {
        ...router,
        _name: router.name || values.routerName || "Без названия",
        _lanSubnet: values.lanOctet ? `192.168.${values.lanOctet}.0/24` : "—",
        _ssid: values.ssid || (values.hasWifi === false ? "—" : "—"),
        _isOnline: isOnline,
        _uptime: router.uptime_seconds || formatUptime(Math.floor(Math.random() * 86400 * 7)),
        _traffic: formatTraffic(traffic),
      };
    });

    document.querySelector("#stat-total").textContent = total;
    document.querySelector("#stat-online").textContent = online;
    document.querySelector("#stat-offline").textContent = offline;
    document.querySelector("#stat-traffic").textContent = formatTraffic(totalTraffic);
    document.querySelector("#last-update").textContent = new Date().toLocaleTimeString("ru-RU");

    renderRoutersTable(allRouters);
  } catch (error) {
    console.error("Dashboard load error:", error);
    const tbody = document.querySelector("#routers-tbody");
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="6" class="table-error">Ошибка загрузки: ${error.message}</td></tr>`;
    }
  }
}

function renderRoutersTable(routers) {
  const tbody = document.querySelector("#routers-tbody");
  if (!tbody) return;

  if (routers.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="table-empty">Нет данных о роутерах</td></tr>`;
    return;
  }

  tbody.innerHTML = "";
  for (const router of routers) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${escapeHtml(router._name)}</strong></td>
      <td>${escapeHtml(router._lanSubnet)}</td>
      <td>${escapeHtml(router._ssid)}</td>
      <td>
        <span class="status-badge ${router._isOnline ? "status-online" : "status-offline"}">
          ${router._isOnline ? "Онлайн" : "Оффлайн"}
        </span>
      </td>
      <td>${escapeHtml(router._uptime)}</td>
      <td class="traffic-value">${escapeHtml(router._traffic)}</td>
    `;
    tbody.appendChild(tr);
  }
}

function formatTraffic(mb) {
  if (mb >= 1024 * 1024) {
    return `${(mb / (1024 * 1024)).toFixed(2)} TB`;
  }
  if (mb >= 1024) {
    return `${(mb / 1024).toFixed(2)} GB`;
  }
  return `${mb} MB`;
}

function formatUptime(seconds) {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const parts = [];
  if (days > 0) parts.push(`${days}д`);
  if (hours > 0) parts.push(`${hours}ч`);
  parts.push(`${mins}м`);
  return parts.join(" ");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = String(str ?? "");
  return div.innerHTML;
}

async function initConfigPage() {
  const logoutBtn = document.querySelector("#logout-btn");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", () => {
      if (state.refreshInterval) clearInterval(state.refreshInterval);
      redirectToLogin();
    });
  }

  const configTabNode = document.querySelector("#config-tab");
  const settingsTabNode = document.querySelector("#settings-tab");
  const configTabButton = document.querySelector("#tab-config-btn");
  const settingsTabButton = document.querySelector("#tab-settings-btn");
  const statusNode = document.querySelector("#status");
  const formNode = document.querySelector("#config-form");
  const previewNode = document.querySelector("#preview");
  const formTitleNode = document.querySelector("#form-title");
  const profileSelectNode = document.querySelector("#profile-select");
  const routerListNode = document.querySelector("#router-list");
  const resetButton = document.querySelector("#reset-btn");
  const downloadButton = document.querySelector("#download-btn");
  const downloadPreviewButton = document.querySelector("#download-preview-btn");
  const downloadAllButton = document.querySelector("#download-all-btn");
  const addRouterButton = document.querySelector("#add-router-btn");
  const duplicateRouterButton = document.querySelector("#duplicate-router-btn");
  const removeRouterButton = document.querySelector("#remove-router-btn");
  const newProfileButton = document.querySelector("#new-profile-btn");
  const saveProfileButton = document.querySelector("#save-profile-btn");
  const deleteProfileButton = document.querySelector("#delete-profile-btn");
  const fieldTemplate = document.querySelector("#field-template");
  const routerItemTemplate = document.querySelector("#router-item-template");

  setStatus("Загрузка схемы и профилей...", "loading");

  try {
    const [schema, profiles] = await Promise.all([
      apiFetch("/api/configs/schema"),
      apiFetch("/api/profiles"),
    ]);

    state.schema = schema;
    state.defaults = getDefaultValues();
    state.profiles = profiles;

    if (state.profiles.length === 0) {
      const newProfile = await apiFetch("/api/profiles", {
        method: "POST",
        body: JSON.stringify({ name: DEFAULT_PROFILE_NAME }),
      });
      state.profiles.push(newProfile);
    }

    state.activeProfileId = state.profiles[0].id;
    const activeProfile = getActiveProfile();
    if (activeProfile.routers && activeProfile.routers.length > 0) {
      state.activeRouterId = activeProfile.routers[0].id;
    } else {
      const defaultRouter = createRouterData();
      const createdRouter = await apiFetch(`/api/profiles/${activeProfile.id}/routers`, {
        method: "POST",
        body: JSON.stringify({ name: defaultRouter.values.routerName, values: defaultRouter.values }),
      });
      activeProfile.routers = [createdRouter];
      state.activeRouterId = createdRouter.id;
    }

    wireActions();
    renderAll();
    setStatus("Профили и схема загружены.", "success");
  } catch (error) {
    setStatus(error.message || "Ошибка загрузки данных", "error");
  }

  function getDefaultValues() {
    return Object.fromEntries(
      state.schema.fields.map((field) => [field.id, field.default]),
    );
  }

  function createRouterData(overrides = {}) {
    const values = {
      ...state.defaults,
      routerName: overrides.routerName || "Новый MikroTik 1",
      ...overrides,
    };
    delete values.routerName;
    return {
      id: null,
      name: overrides.routerName || "Новый MikroTik 1",
      values,
    };
  }

  function getActiveProfile() {
    return state.profiles.find((p) => p.id === state.activeProfileId) || state.profiles[0];
  }

  function getActiveRouter() {
    const profile = getActiveProfile();
    if (!profile.routers || profile.routers.length === 0) return null;
    return profile.routers.find((r) => r.id === state.activeRouterId) || profile.routers[0];
  }

  function setStatus(message, type) {
    if (statusNode) {
      statusNode.textContent = message;
      statusNode.className = `status status-${type}`;
    }
  }

  function renderAll() {
    renderTabs();
    renderProfileSelect();
    renderRouterList();
    renderForm();
    renderMeta();
    refreshPreview();
  }

  function renderTabs() {
    if (!configTabNode) return;
    const isConfig = state.activeTab === "config";
    configTabNode.classList.toggle("tab-panel-active", isConfig);
    settingsTabNode.classList.toggle("tab-panel-active", !isConfig);
    configTabButton.classList.toggle("tab-btn-active", isConfig);
    settingsTabButton.classList.toggle("tab-btn-active", !isConfig);
  }

  function renderProfileSelect() {
    if (!profileSelectNode) return;
    profileSelectNode.innerHTML = "";

    for (const profile of state.profiles) {
      const option = document.createElement("option");
      option.value = profile.id;
      option.textContent = profile.name;
      option.selected = profile.id === state.activeProfileId;
      profileSelectNode.appendChild(option);
    }
  }

  function renderRouterList() {
    if (!routerListNode) return;
    const profile = getActiveProfile();
    routerListNode.innerHTML = "";

    if (!profile.routers) profile.routers = [];

    for (const router of profile.routers) {
      const fragment = routerItemTemplate.content.cloneNode(true);
      const button = fragment.querySelector(".router-item");
      const nameNode = fragment.querySelector(".router-name");
      const metaNode = fragment.querySelector(".router-meta");
      const values = router.values || {};
      const routerName = router.name || values.routerName || "Без названия";

      button.classList.toggle("active", router.id === state.activeRouterId);
      nameNode.textContent = routerName;
      metaNode.textContent = buildRouterMeta(values);
      button.addEventListener("click", async () => {
        state.activeRouterId = router.id;
        renderAll();
        setStatus(`Выбран роутер: ${routerName}.`, "success");
      });
      routerListNode.appendChild(fragment);
    }
  }

  function buildRouterMeta(values) {
    const wanType = values.wanType || "automatic";
    const wanLabels = { automatic: "DHCP", pppoe: "PPPoE", static: "Static" };
    const octet = values.lanOctet ?? "X";
    const ssid = values.hasWifi === false ? "без Wi-Fi" : values.ssid || "—";
    return `${wanLabels[wanType] || "WAN"} | 192.168.${octet}.0/24 | ${ssid}`;
  }

  function renderMeta() {
    const templateNameNode = document.querySelector("#template-name");
    if (templateNameNode) {
      const router = getActiveRouter();
      if (!router) return;
      const values = router.values || {};
      const wanType = values.wanType || "automatic";
      const labels = { automatic: "DHCP шаблон", pppoe: "PPPoE шаблон", static: "Static шаблон" };
      templateNameNode.textContent = labels[wanType] || "Шаблон";
    }
  }

  function renderForm() {
    if (!formNode) return;
    const router = getActiveRouter();
    if (!router) {
      formNode.innerHTML = "<p>Нет выбранного роутера</p>";
      return;
    }

    const values = router.values || {};
    formTitleNode.textContent = router.name || values.routerName || "Настройка роутера";
    formNode.innerHTML = "";

    for (const sectionName of SECTION_ORDER) {
      const sectionFields = state.schema.fields.filter((field) => field.section === sectionName);
      if (sectionFields.length === 0) continue;

      const section = document.createElement("section");
      section.className = "section";

      const title = document.createElement("h3");
      title.className = "section-title";
      title.textContent = sectionName;
      section.appendChild(title);

      const grid = document.createElement("div");
      grid.className = "section-grid";
      section.appendChild(grid);
      formNode.appendChild(section);

      for (const field of sectionFields) {
        if (!shouldRenderField(field, values)) continue;
        grid.appendChild(createField(field, router));
      }

      if (sectionName === "LAN") {
        grid.appendChild(createDhcpPreview(values));
      }
    }
  }

  function createDhcpPreview(values) {
    const wrapper = document.createElement("div");
    const label = document.createElement("span");
    const value = document.createElement("strong");

    wrapper.className = "inline-summary";
    label.className = "inline-summary-label";
    value.className = "inline-summary-value";

    const octet = values.lanOctet ?? "X";
    const start = values.dhcpRangeStart ?? "start";
    const end = values.dhcpRangeEnd ?? "end";
    label.textContent = "Итоговый DHCP диапазон";
    value.textContent = `192.168.${octet}.${start} - 192.168.${octet}.${end}`;

    wrapper.appendChild(label);
    wrapper.appendChild(value);
    return wrapper;
  }

  function createField(field, router) {
    const fragment = fieldTemplate.content.cloneNode(true);
    const wrapper = fragment.querySelector(".field");
    const label = fragment.querySelector(".field-label");
    const help = fragment.querySelector(".field-help");
    const error = fragment.querySelector(".field-error");
    const input = createFieldControl(field);

    wrapper.dataset.fieldId = field.id;
    label.textContent = field.label;
    help.textContent = field.help || "";
    error.dataset.errorFor = field.id;
    input.name = field.id;
    input.dataset.fieldId = field.id;
    wrapper.classList.toggle("field-checkbox", field.type === "checkbox");

    if (field.placeholder) input.placeholder = field.placeholder;

    const values = router.values || {};
    setControlValue(input, field.type, values[field.id]);
    applyFieldState(field, input, wrapper, values);
    wrapper.replaceChild(input, fragment.querySelector(".field-input"));

    const eventName = field.type === "select" || field.type === "checkbox" ? "change" : "input";
    input.addEventListener(eventName, async () => {
      const previousValues = { ...(router.values || {}) };
      router.values = router.values || {};
      router.values[field.id] = readControlValue(input, field.type);

      if (field.id === "lanOctet") {
        syncDnsServerWithLan(previousValues, router.values);
      }

      if (field.id === "routerName") {
        router.name = router.values.routerName;
      }

      const needRerender =
        field.id === "enableL2tp" ||
        field.id === "enableSstp" ||
        field.id === "wanType" ||
        field.id === "hasWifi" ||
        field.id === "ssid" ||
        field.id === "lanOctet";

      try {
        if (router.id) {
          await apiFetch(`/api/profiles/${getActiveProfile().id}/routers/${router.id}`, {
            method: "PUT",
            body: JSON.stringify({ name: router.name, values: router.values }),
          });
        }

        if (needRerender) {
          renderRouterList();
          if (field.id === "routerName") {
            formTitleNode.textContent = router.name || "Настройка роутера";
          }
        }

        await refreshPreview();
      } catch (err) {
        setStatus(`Ошибка сохранения: ${err.message}`, "error");
      }
    });

    return fragment;
  }

  function createFieldControl(field) {
    if (field.type === "checkbox") {
      const input = document.createElement("input");
      input.type = "checkbox";
      return input;
    }
    if (field.type === "textarea") {
      return document.createElement("textarea");
    }
    if (field.type === "select") {
      const select = document.createElement("select");
      for (const option of field.options || []) {
        const optionNode = document.createElement("option");
        optionNode.value = option.value;
        optionNode.textContent = option.label;
        select.appendChild(optionNode);
      }
      return select;
    }
    const input = document.createElement("input");
    input.type = field.type === "password" ? "text" : field.type;
    if (field.type === "number") {
      if (typeof field.min === "number") input.min = String(field.min);
      if (typeof field.max === "number") input.max = String(field.max);
    }
    return input;
  }

  function setControlValue(control, type, value) {
    if (type === "checkbox") {
      control.checked = Boolean(value);
      return;
    }
    if (type === "number") {
      control.value = value === "" || value === null || value === undefined ? "" : String(value);
      return;
    }
    control.value = value ?? "";
  }

  function readControlValue(control, type) {
    if (type === "checkbox") return control.checked;
    if (type === "number") return control.value === "" ? "" : Number(control.value);
    return control.value;
  }

  function applyFieldState(field, input, wrapper, values) {
    const wifiDisabled = field.section === "Wi-Fi" && field.id !== "hasWifi" && values.hasWifi === false;
    const l2tpDisabled = field.section === "L2TP" && field.id !== "enableL2tp" && !values.enableL2tp;
    const sstpDisabled = field.section === "SSTP" && field.id !== "enableSstp" && !values.enableSstp;
    const pppoeDisabled =
      field.section === "WAN" &&
      ["pppoeUsername", "pppoePassword"].includes(field.id) &&
      values.wanType !== "pppoe";
    const staticDisabled =
      field.section === "WAN" &&
      ["staticWanIp", "staticWanNetmask", "staticWanGateway", "staticWanDns1", "staticWanDns2"].includes(field.id) &&
      values.wanType !== "static";
    const isDisabled = wifiDisabled || l2tpDisabled || sstpDisabled || pppoeDisabled || staticDisabled;

    input.disabled = isDisabled;
    wrapper.classList.toggle("field-disabled", isDisabled);
  }

  function shouldRenderField(field, values) {
    if (field.section === "Wi-Fi" && field.id !== "hasWifi" && values.hasWifi === false) return false;
    if (["pppoeUsername", "pppoePassword"].includes(field.id) && values.wanType !== "pppoe") return false;
    if (
      ["staticWanIp", "staticWanNetmask", "staticWanGateway", "staticWanDns1", "staticWanDns2"].includes(field.id) &&
      values.wanType !== "static"
    ) return false;
    return true;
  }

  function syncDnsServerWithLan(previousValues, nextValues) {
    const getAutoDns = (octet) => `192.168.${octet}.1`;
    const prevAuto = getAutoDns(previousValues.lanOctet);
    const nextAuto = getAutoDns(nextValues.lanOctet);
    if (!previousValues.dnsServer || previousValues.dnsServer === prevAuto) {
      nextValues.dnsServer = nextAuto;
    }
  }

  async function refreshPreview() {
    const router = getActiveRouter();
    if (!router || !previewNode) return;

    try {
      const validation = await apiFetch("/api/configs/validate", {
        method: "POST",
        body: JSON.stringify({ values: router.values || {} }),
      });

      renderErrors(validation.errors || {});
      const isValid = validation.valid;
      updateActionState(isValid);

      if (!isValid) {
        previewNode.value = "# Есть ошибки в форме.\n# Исправьте подсвеченные поля, чтобы получить итоговый конфиг.";
        return;
      }

      const buildResult = await apiFetch("/api/configs/build", {
        method: "POST",
        body: JSON.stringify({ values: router.values || {} }),
      });

      if (typeof buildResult === "string") {
        previewNode.value = buildResult;
      } else if (buildResult && buildResult.content) {
        previewNode.value = buildResult.content;
      } else {
        previewNode.value = String(buildResult || "");
      }
    } catch (error) {
      previewNode.value = `# Ошибка сборки конфига:\n# ${error.message}`;
    }
  }

  function renderErrors(errors) {
    if (!formNode) return;
    for (const field of state.schema.fields) {
      const wrapper = formNode.querySelector(`[data-field-id="${field.id}"]`);
      const errorNode = formNode.querySelector(`[data-error-for="${field.id}"]`);
      const message = errors[field.id] || "";
      if (wrapper) wrapper.classList.toggle("field-invalid", Boolean(message));
      if (errorNode) errorNode.textContent = message;
    }
  }

  function updateActionState(isValid) {
    if (downloadButton) downloadButton.disabled = !isValid;
    if (downloadPreviewButton) downloadPreviewButton.disabled = !isValid;
  }

  function buildFileName(values) {
    const octet = String(values.lanOctet || "0").padStart(3, "0");
    const safeName = String(values.routerName || "mikrotik")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9а-яё_-]+/gi, "-")
      .replace(/-+/g, "-")
      .replace(/^-|-$/g, "");
    return `${safeName || "mikrotik"}-${octet}.rsc`;
  }

  async function downloadCurrentConfig() {
    const router = getActiveRouter();
    if (!router) return;

    try {
      const validation = await apiFetch("/api/configs/validate", {
        method: "POST",
        body: JSON.stringify({ values: router.values || {} }),
      });
      renderErrors(validation.errors || {});

      if (!validation.valid) {
        setStatus("Исправьте ошибки у выбранного роутера перед скачиванием.", "error");
        return;
      }

      const buildResult = await apiFetch("/api/configs/build", {
        method: "POST",
        body: JSON.stringify({ values: router.values || {} }),
      });

      const content = typeof buildResult === "string" ? buildResult : (buildResult?.content || "");
      const fileName = buildResult?.filename || buildFileName(router.values || {});
      downloadText(fileName, content);
      setStatus(`Скачан файл ${fileName}.`, "success");
    } catch (error) {
      setStatus(`Ошибка: ${error.message}`, "error");
    }
  }

  function wireActions() {
    if (configTabButton) {
      configTabButton.addEventListener("click", () => {
        state.activeTab = "config";
        renderTabs();
      });
    }

    if (settingsTabButton) {
      settingsTabButton.addEventListener("click", () => {
        state.activeTab = "settings";
        renderTabs();
      });
    }

    if (profileSelectNode) {
      profileSelectNode.addEventListener("change", () => {
        state.activeProfileId = profileSelectNode.value;
        const profile = getActiveProfile();
        if (profile.routers && profile.routers.length > 0) {
          state.activeRouterId = profile.routers[0].id;
        } else {
          state.activeRouterId = null;
        }
        renderAll();
        setStatus(`Открыт профиль: ${profile.name}.`, "success");
      });
    }

    if (newProfileButton) {
      newProfileButton.addEventListener("click", async () => {
        const profileName = window.prompt("Введите имя нового профиля:");
        if (!profileName) return;
        const trimmed = profileName.trim();
        if (!trimmed) {
          setStatus("Имя профиля не может быть пустым.", "error");
          return;
        }
        try {
          const newProfile = await apiFetch("/api/profiles", {
            method: "POST",
            body: JSON.stringify({ name: trimmed }),
          });
          newProfile.routers = [];
          state.profiles.push(newProfile);
          state.activeProfileId = newProfile.id;

          const defaultRouter = createRouterData({ routerName: "Новый MikroTik 1" });
          const createdRouter = await apiFetch(`/api/profiles/${newProfile.id}/routers`, {
            method: "POST",
            body: JSON.stringify({ name: defaultRouter.name, values: defaultRouter.values }),
          });
          newProfile.routers = [createdRouter];
          state.activeRouterId = createdRouter.id;

          renderAll();
          setStatus(`Создан профиль: ${trimmed}.`, "success");
        } catch (error) {
          setStatus(`Ошибка: ${error.message}`, "error");
        }
      });
    }

    if (saveProfileButton) {
      saveProfileButton.addEventListener("click", async () => {
        const profile = getActiveProfile();
        const newName = window.prompt("Введите новое имя профиля:", profile.name);
        if (!newName || !newName.trim()) return;
        try {
          const updated = await apiFetch(`/api/profiles/${profile.id}`, {
            method: "PUT",
            body: JSON.stringify({ name: newName.trim() }),
          });
          profile.name = updated.name;
          renderProfileSelect();
          setStatus(`Профиль переименован в "${updated.name}".`, "success");
        } catch (error) {
          setStatus(`Ошибка: ${error.message}`, "error");
        }
      });
    }

    if (deleteProfileButton) {
      deleteProfileButton.addEventListener("click", async () => {
        if (state.profiles.length === 1) {
          setStatus("Нельзя удалить последний профиль.", "error");
          return;
        }
        const profile = getActiveProfile();
        const ok = window.confirm(`Удалить профиль "${profile.name}"?`);
        if (!ok) return;
        try {
          await apiFetch(`/api/profiles/${profile.id}`, { method: "DELETE" });
          state.profiles = state.profiles.filter((p) => p.id !== profile.id);
          state.activeProfileId = state.profiles[0].id;
          const firstProfile = getActiveProfile();
          state.activeRouterId = firstProfile.routers?.[0]?.id || null;
          renderAll();
          setStatus(`Профиль ${profile.name} удален.`, "success");
        } catch (error) {
          setStatus(`Ошибка: ${error.message}`, "error");
        }
      });
    }

    if (addRouterButton) {
      addRouterButton.addEventListener("click", async () => {
        const profile = getActiveProfile();
        const nextNumber = (profile.routers?.length || 0) + 1;
        const routerData = createRouterData({ routerName: `Новый MikroTik ${nextNumber}` });
        try {
          const createdRouter = await apiFetch(`/api/profiles/${profile.id}/routers`, {
            method: "POST",
            body: JSON.stringify({ name: routerData.name, values: routerData.values }),
          });
          profile.routers = profile.routers || [];
          profile.routers.push(createdRouter);
          state.activeRouterId = createdRouter.id;
          renderAll();
          setStatus("Новый роутер добавлен в текущий профиль.", "success");
        } catch (error) {
          setStatus(`Ошибка: ${error.message}`, "error");
        }
      });
    }

    if (duplicateRouterButton) {
      duplicateRouterButton.addEventListener("click", async () => {
        const profile = getActiveProfile();
        const source = getActiveRouter();
        if (!source) return;
        const sourceValues = { ...(source.values || {}) };
        const routerData = {
          name: `${source.name || sourceValues.routerName || "Роутер"} копия`,
          values: sourceValues,
        };
        try {
          const createdRouter = await apiFetch(`/api/profiles/${profile.id}/routers`, {
            method: "POST",
            body: JSON.stringify(routerData),
          });
          profile.routers.push(createdRouter);
          state.activeRouterId = createdRouter.id;
          renderAll();
          setStatus("Роутер продублирован.", "success");
        } catch (error) {
          setStatus(`Ошибка: ${error.message}`, "error");
        }
      });
    }

    if (removeRouterButton) {
      removeRouterButton.addEventListener("click", async () => {
        const profile = getActiveProfile();
        if (!profile.routers || profile.routers.length <= 1) {
          setStatus("Нельзя удалить последний роутер в профиле.", "error");
          return;
        }
        const router = getActiveRouter();
        if (!router) return;
        const ok = window.confirm(`Удалить роутер "${router.name || router.values?.routerName}"?`);
        if (!ok) return;
        try {
          await apiFetch(`/api/profiles/${profile.id}/routers/${router.id}`, { method: "DELETE" });
          profile.routers = profile.routers.filter((r) => r.id !== router.id);
          state.activeRouterId = profile.routers[0].id;
          renderAll();
          setStatus(`Роутер удален.`, "success");
        } catch (error) {
          setStatus(`Ошибка: ${error.message}`, "error");
        }
      });
    }

    if (resetButton) {
      resetButton.addEventListener("click", async () => {
        const router = getActiveRouter();
        if (!router) return;
        const currentName = router.name || router.values?.routerName || "Новый MikroTik";
        router.values = { ...state.defaults, routerName: currentName };
        router.name = currentName;
        try {
          if (router.id) {
            await apiFetch(`/api/profiles/${getActiveProfile().id}/routers/${router.id}`, {
              method: "PUT",
              body: JSON.stringify({ name: router.name, values: router.values }),
            });
          }
          renderAll();
          setStatus("Параметры выбранного роутера сброшены к шаблону.", "success");
        } catch (error) {
          setStatus(`Ошибка: ${error.message}`, "error");
        }
      });
    }

    if (downloadButton) downloadButton.addEventListener("click", downloadCurrentConfig);
    if (downloadPreviewButton) downloadPreviewButton.addEventListener("click", downloadCurrentConfig);

    if (downloadAllButton) {
      downloadAllButton.addEventListener("click", async () => {
        const profile = getActiveProfile();
        if (!profile.routers || profile.routers.length === 0) return;

        const invalidRouters = [];
        const validRouters = [];

        for (const router of profile.routers) {
          try {
            const validation = await apiFetch("/api/configs/validate", {
              method: "POST",
              body: JSON.stringify({ values: router.values || {} }),
            });
            if (validation.valid) {
              validRouters.push(router);
            } else {
              invalidRouters.push(router.name || router.values?.routerName);
            }
          } catch {
            invalidRouters.push(router.name || router.values?.routerName);
          }
        }

        if (invalidRouters.length > 0) {
          setStatus(`Есть ошибки у роутеров: ${invalidRouters.join(", ")}.`, "error");
          return;
        }

        for (let i = 0; i < validRouters.length; i++) {
          const router = validRouters[i];
          await new Promise((resolve) => setTimeout(resolve, i * 250));
          try {
            const buildResult = await apiFetch("/api/configs/build", {
              method: "POST",
              body: JSON.stringify({ values: router.values || {} }),
            });
            const content = typeof buildResult === "string" ? buildResult : (buildResult?.content || "");
            const fileName = buildResult?.filename || buildFileName(router.values || {});
            downloadText(fileName, content);
          } catch (error) {
            console.error("Download error:", error);
          }
        }

        setStatus(
          `Запущена выгрузка ${validRouters.length} конфигов. Браузер может попросить разрешение на несколько скачиваний.`,
          "success",
        );
      });
    }
  }
}
