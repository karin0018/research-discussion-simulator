const state = {
  agents: [],
  conversationId: null,
  selectedConversationAgents: [],
  conversations: [],
  godView: null,
  streamNodes: {},
  llmServices: [],
};

async function fetchJSON(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return response.json();
}

function selectedMode() {
  return document.querySelector('input[name="mode"]:checked').value;
}

function selectedAgents() {
  return [...document.querySelectorAll('input[name="agent"]:checked')].map((input) => input.value);
}

function normalizeMessageContent(text) {
  return String(text || "")
    .replace(/\n[ \t]*\n(?:[ \t]*\n)+/g, "\n\n")
    .trim();
}

function updatePanelToggleLabel(panel) {
  const button = panel.querySelector('[data-toggle-panel]');
  if (!button) return;
  button.textContent = panel.classList.contains("is-collapsed") ? "展开" : "收起";
}

function initializePanelToggles() {
  document.querySelectorAll("[data-toggle-panel]").forEach((button) => {
    const panelId = button.dataset.togglePanel;
    const panel = document.getElementById(panelId);
    if (!panel) return;
    updatePanelToggleLabel(panel);
    button.addEventListener("click", () => {
      panel.classList.toggle("is-collapsed");
      updatePanelToggleLabel(panel);
    });
  });
}

function formatDateTime(value) {
  if (!value) return "未知时间";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function renderAgents() {
  const container = document.getElementById("agent-list");
  const select = document.getElementById("knowledge-agent");
  const customList = document.getElementById("custom-agent-list");
  const customCount = document.getElementById("custom-agent-count");
  const historyFilter = document.getElementById("conversation-agent-filter");
  container.innerHTML = "";
  select.innerHTML = "";
  customList.innerHTML = "";
  historyFilter.innerHTML = '<option value="all">全部角色</option>';

  state.agents.forEach((agent, index) => {
    const serviceOptions = state.llmServices
      .map((service) => `<option value="${service.service_id}" ${agent.llm_service === service.service_id ? "selected" : ""}>${service.label}</option>`)
      .join("");
    const currentService = state.llmServices.find((item) => item.service_id === agent.llm_service) || state.llmServices[0];
    const modelOptions = (currentService?.models || []).map((model) => {
      const selected = agent.llm_model === model || (!agent.llm_model && currentService?.default_model === model);
      return `<option value="${model}" ${selected ? "selected" : ""}>${model}</option>`;
    }).join("");
    const wrapper = document.createElement("label");
    wrapper.className = `agent-option${agent.is_custom ? " custom-agent" : ""}`;
    wrapper.innerHTML = `
      <div class="agent-card-header">
        <div>
          <input type="checkbox" name="agent" value="${agent.agent_id}" ${index === 0 ? "checked" : ""} />
          <strong>${agent.name} · ${agent.title}${agent.is_custom ? " · 自定义" : ""}</strong>
        </div>
      </div>
      <div>${agent.expertise.join(" / ")}</div>
      <p class="subtle">${agent.style}</p>
      <div class="agent-runtime-row" data-agent-runtime="${agent.agent_id}">
        <select class="agent-service-select" data-agent-service="${agent.agent_id}">
          ${serviceOptions}
        </select>
        <select class="agent-model-select" data-agent-model="${agent.agent_id}">
          ${modelOptions}
        </select>
        <button type="button" class="agent-mini-button" data-save-agent-llm="${agent.agent_id}">后端</button>
      </div>
    `;
    wrapper.querySelector(".agent-runtime-row").addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
    });
    container.appendChild(wrapper);

    const option = document.createElement("option");
    option.value = agent.agent_id;
    option.textContent = `${agent.name} · ${agent.title}`;
    select.appendChild(option);

    const filterOption = document.createElement("option");
    filterOption.value = agent.agent_id;
    filterOption.textContent = `${agent.name} · ${agent.title}`;
    historyFilter.appendChild(filterOption);

    if (agent.is_custom) {
      const manager = document.createElement("div");
      manager.className = "manager-item";
      manager.innerHTML = `
        <div class="manager-header">
          <strong>${agent.name}</strong>
          <div class="inline-actions">
            <button type="button" class="agent-mini-button" data-edit-agent="${agent.agent_id}">编辑</button>
            <button type="button" class="danger-button" data-delete-agent="${agent.agent_id}">删除</button>
          </div>
        </div>
        <p class="subtle">${agent.title}</p>
        <p class="subtle">${agent.expertise.join(" / ")}</p>
      `;
      customList.appendChild(manager);
    }
  });

  const customAgents = state.agents.filter((agent) => agent.is_custom);
  customCount.textContent = `${customAgents.length} 个`;
  if (!customAgents.length) {
    customList.innerHTML = `<p class="subtle">还没有自定义角色卡。</p>`;
  }
}

function getAgentById(agentId) {
  return state.agents.find((agent) => agent.agent_id === agentId);
}

function refreshAgentModelOptions(agentId) {
  const serviceSelect = document.querySelector(`[data-agent-service="${agentId}"]`);
  const modelSelect = document.querySelector(`[data-agent-model="${agentId}"]`);
  if (!serviceSelect || !modelSelect) return;
  const service = state.llmServices.find((item) => item.service_id === serviceSelect.value);
  if (!service) return;
  const currentValue = modelSelect.value;
  modelSelect.innerHTML = service.models
    .map((model) => `<option value="${model}" ${currentValue === model || (!currentValue && service.default_model === model) ? "selected" : ""}>${model}</option>`)
    .join("");
  if (!service.models.includes(modelSelect.value)) {
    modelSelect.value = service.default_model;
  }
}

function renderUserProfile(profile) {
  document.getElementById("user-profile-name").value = profile.name || "";
  document.getElementById("user-profile-title").value = profile.title || "";
  document.getElementById("user-profile-expertise").value = (profile.expertise || []).join("\n");
  document.getElementById("user-profile-style").value = profile.style || "";
  document.getElementById("user-profile-objective").value = profile.objective || "";
  document.getElementById("user-profile-summary").value = profile.profile_summary || "";
}

function enterEditMode(agent) {
  document.getElementById("editing-agent-id").value = agent.agent_id;
  document.getElementById("agent-name").value = agent.name;
  document.getElementById("agent-title").value = agent.title;
  document.getElementById("agent-expertise").value = agent.expertise.join("\n");
  document.getElementById("agent-style").value = agent.style;
  document.getElementById("agent-objective").value = agent.objective;
  document.getElementById("agent-submit-button").textContent = "保存角色卡";
  document.getElementById("agent-cancel-button").classList.remove("hidden");
  document.getElementById("agent-status").textContent = `正在编辑：${agent.name}`;
}

function exitEditMode(preserveStatus = false) {
  document.getElementById("editing-agent-id").value = "";
  document.getElementById("agent-form").reset();
  document.getElementById("agent-submit-button").textContent = "创建角色卡";
  document.getElementById("agent-cancel-button").classList.add("hidden");
  if (!preserveStatus) {
    document.getElementById("agent-status").textContent = "";
  }
}

function fillAgentSelection(agentId) {
  document.querySelectorAll('input[name="agent"]').forEach((input) => {
    input.checked = input.value === agentId;
  });
  document.querySelector('input[name="mode"][value="one_to_one"]').checked = true;
  enforceModeRules();
}

function appendMessage(message) {
  const template = document.getElementById("message-template");
  const node = template.content.firstElementChild.cloneNode(true);
  node.classList.add(message.speaker_id);
  node.querySelector(".message-meta").textContent = `${message.speaker_name} · ${message.role}`;
  const contentEl = node.querySelector(".message-content");
  const normalized = normalizeMessageContent(message.content);
  if (typeof marked !== "undefined") {
    contentEl.innerHTML = marked.parse(normalized);
  } else {
    contentEl.textContent = normalized;
  }
  document.getElementById("chat-window").appendChild(node);
  document.getElementById("chat-window").scrollTop = document.getElementById("chat-window").scrollHeight;
}

function startStreamingMessage(message) {
  const template = document.getElementById("message-template");
  const node = template.content.firstElementChild.cloneNode(true);
  node.classList.add(message.speaker_id);
  node.querySelector(".message-meta").textContent = `${message.speaker_name} · ${message.role}`;
  node.querySelector(".message-content").textContent = message.content || "";
  document.getElementById("chat-window").appendChild(node);
  state.streamNodes[message.speaker_id] = {
    node,
    content: message.content || "",
  };
  document.getElementById("chat-window").scrollTop = document.getElementById("chat-window").scrollHeight;
}

function appendStreamingDelta(speakerId, delta) {
  const holder = state.streamNodes[speakerId];
  if (!holder) return;
  holder.content += delta;
  holder.node.querySelector(".message-content").textContent = holder.content;
  document.getElementById("chat-window").scrollTop = document.getElementById("chat-window").scrollHeight;
}

function finishStreamingMessage(message) {
  const holder = state.streamNodes[message.speaker_id];
  if (!holder) return;
  holder.content = normalizeMessageContent(message.content || holder.content);
  const contentEl = holder.node.querySelector(".message-content");
  if (typeof marked !== "undefined") {
    contentEl.innerHTML = marked.parse(holder.content || "");
  } else {
    contentEl.textContent = holder.content || "";
  }
}

function resetChat() {
  document.getElementById("chat-window").innerHTML = "";
  state.streamNodes = {};
}

function renderProviderStatus(status) {
  const container = document.getElementById("provider-status-card");
  const cliCommand = Array.isArray(status.cli_command) && status.cli_command.length
    ? status.cli_command.join(" ")
    : "未使用";
  container.innerHTML = `
    <div class="status-pill ${status.enabled ? "ready" : "warning"}">
      ${status.enabled ? "已启用" : "未就绪"}
    </div>
    <div class="status-grid">
      <div class="status-item">
        <span class="status-label">Provider</span>
        <div class="status-value">${status.provider || "unknown"}</div>
      </div>
      <div class="status-item">
        <span class="status-label">Model</span>
        <div class="status-value">${status.model || "未配置"}</div>
      </div>
      <div class="status-item">
        <span class="status-label">Transport</span>
        <div class="status-value">${status.transport || "mock"}</div>
      </div>
      <div class="status-item">
        <span class="status-label">CLI / URL</span>
        <div class="status-value">${status.transport === "cli" ? cliCommand : (status.base_url || "未使用")}</div>
      </div>
    </div>
    <p class="subtle">${status.message || ""}</p>
  `;
}

async function loadAgents() {
  state.agents = await fetchJSON("/api/agents");
  renderAgents();
}

async function loadProviderStatus() {
  const status = await fetchJSON("/api/provider-status");
  renderProviderStatus(status);
}

async function loadUserProfile() {
  const profile = await fetchJSON("/api/user-profile");
  renderUserProfile(profile);
}

function renderGodView(data) {
  state.godView = data;
  const filter = document.getElementById("god-view-filter");
  const current = filter.value || "all";
  filter.innerHTML = '<option value="all">全部角色</option>';
  (data.roles || []).forEach((role) => {
    const option = document.createElement("option");
    option.value = role.agent_id;
    option.textContent = `${role.name}${role.is_user ? " · 用户" : ""}`;
    filter.appendChild(option);
  });
  filter.value = [...filter.options].some((item) => item.value === current) ? current : "all";

  const list = document.getElementById("god-view-list");
  list.innerHTML = "";
  const roles = (data.roles || []).filter((role) => filter.value === "all" || role.agent_id === filter.value);
  if (!roles.length) {
    list.innerHTML = `<p class="subtle">当前没有可展示的角色视角。</p>`;
    return;
  }

  roles.forEach((role) => {
    const card = document.createElement("div");
    card.className = "god-view-card";
    card.innerHTML = `
      <strong>${role.name}${role.is_user ? " · 用户" : ""}</strong>
      <p class="subtle">${role.title || ""}</p>
      <p class="subtle">当前想法：${role.latest_thought || "暂无"}</p>
      <div class="memory-list">
        ${(role.memories || []).slice(0, 3).map((memory) => `
        <div class="memory-item">
            <div class="memory-time">${formatDateTime(memory.created_at)}</div>
            <div>${normalizeMessageContent(memory.summary)}</div>
          </div>
        `).join("") || '<p class="subtle">还没有长期记忆。</p>'}
      </div>
    `;
    list.appendChild(card);
  });
}

async function loadGodView(conversationId = state.conversationId) {
  const url = conversationId
    ? `/api/god-view?conversation_id=${encodeURIComponent(conversationId)}`
    : "/api/god-view";
  const data = await fetchJSON(url);
  renderGodView(data);
}

function renderConversationList() {
  const items = state.conversations;
  const query = document.getElementById("conversation-search").value.trim().toLowerCase();
  const modeFilter = document.getElementById("conversation-mode-filter").value;
  const agentFilter = document.getElementById("conversation-agent-filter").value;
  const container = document.getElementById("conversation-list");
  container.innerHTML = "";

  const grouped = {};
  items
    .filter((item) => {
      if (modeFilter !== "all" && item.mode !== modeFilter) return false;
      if (agentFilter !== "all" && !(item.selected_agents || []).includes(agentFilter)) return false;
      const agentNames = (item.selected_agents || []).map((id) => getAgentById(id)?.name || id).join(" ");
      const haystack = `${item.last_topic || ""} ${item.user_context || ""} ${agentNames}`.toLowerCase();
      return !query || haystack.includes(query);
    })
    .forEach((item) => {
      if (!grouped[item.time_bucket]) grouped[item.time_bucket] = [];
      grouped[item.time_bucket].push(item);
    });

  const buckets = ["今天", "近 7 天", "近 30 天", "更早"];
  let hasItem = false;
  buckets.forEach((bucket) => {
    const bucketItems = grouped[bucket] || [];
    if (!bucketItems.length) return;
    hasItem = true;
    const group = document.createElement("div");
    group.className = "conversation-group";
    group.innerHTML = `<div class="conversation-group-title">${bucket}</div>`;
    bucketItems.forEach((item) => {
      const div = document.createElement("div");
      div.className = "conversation-item";
      const agentNames = (item.selected_agents || []).map((id) => getAgentById(id)?.name || id).join(" / ");
      div.innerHTML = `
        <div class="conversation-header">
          <strong>${item.last_topic || "未命名讨论"}</strong>
          <button type="button" class="danger-button" data-delete-conversation="${item.conversation_id}">删除</button>
        </div>
        <p class="subtle">模式: ${item.mode === "group" ? "一对多" : "一对一"}</p>
        <p class="subtle">角色: ${agentNames || "暂无"}</p>
        <p class="subtle">时间: ${formatDateTime(item.updated_at)}</p>
        <p class="subtle">${item.memory_enabled ? "长期记忆开启" : "长期记忆关闭"}</p>
        <p class="subtle">${item.user_context || "暂无上下文摘要"}</p>
      `;
      div.addEventListener("click", () => loadConversation(item.conversation_id));
      div.querySelector('[data-delete-conversation]').addEventListener("click", async (event) => {
        event.stopPropagation();
        const ok = window.confirm("确定删除这条历史会话吗？");
        if (!ok) return;
        await fetchJSON(`/api/conversations/${item.conversation_id}`, { method: "DELETE" });
        if (state.conversationId === item.conversation_id) {
          await startNewDiscussion();
        }
        await loadConversations();
      });
      group.appendChild(div);
    });
    container.appendChild(group);
  });

  if (!hasItem) {
    container.innerHTML = `<p class="subtle">还没有历史讨论。</p>`;
  }
}

async function loadConversations() {
  state.conversations = await fetchJSON("/api/conversations");
  renderConversationList();
}

async function loadConversation(conversationId) {
  const payload = await fetchJSON(`/api/conversations/${conversationId}`);
  state.conversationId = payload.conversation_id;
  state.selectedConversationAgents = payload.selected_agents || [];
  resetChat();
  (payload.messages || []).forEach((message) => appendMessage(message));
  document.getElementById("session-hint").textContent = `当前会话：${payload.conversation_id}`;
  document.querySelector(`input[name="mode"][value="${payload.mode || "one_to_one"}"]`).checked = true;
  document.getElementById("memory-enabled").checked = payload.memory_enabled !== false;

  const selected = new Set(payload.selected_agents || []);
  document.querySelectorAll('input[name="agent"]').forEach((input) => {
    input.checked = selected.has(input.value);
  });
  enforceModeRules();
  await loadGodView(conversationId);
}

function enforceModeRules() {
  const mode = selectedMode();
  const checkboxes = [...document.querySelectorAll('input[name="agent"]')];
  if (mode === "one_to_one") {
    const checked = checkboxes.filter((input) => input.checked);
    if (checked.length > 1) {
      checked.slice(1).forEach((input) => {
        input.checked = false;
      });
    }
  }
}

function updateConfigFields() {
  const serviceId = document.getElementById("cfg-service").value;
  const service = state.llmServices.find((item) => item.service_id === serviceId);
  const modelSelect = document.getElementById("cfg-model");
  modelSelect.innerHTML = "";
  if (!service) return;
  service.models.forEach((model) => {
    const option = document.createElement("option");
    option.value = model;
    option.textContent = model;
    modelSelect.appendChild(option);
  });
}

async function loadLLMServices() {
  const payload = await fetchJSON("/api/llm-services");
  state.llmServices = payload.services || [];
  updateConfigFields();
}

async function loadLLMConfig() {
  const cfg = await fetchJSON("/api/llm-config");
  if (cfg.service) {
    document.getElementById("cfg-service").value = cfg.service;
  }
  updateConfigFields();
  if (cfg.model) {
    document.getElementById("cfg-model").value = cfg.model;
  }
}

async function startNewDiscussion() {
  const created = await fetchJSON("/api/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mode: selectedMode(),
      selected_agents: selectedAgents(),
      memory_enabled: document.getElementById("memory-enabled").checked,
    }),
  });
  state.conversationId = created.conversation_id;
  state.selectedConversationAgents = created.selected_agents || [];
  resetChat();
  document.getElementById("session-hint").textContent = `当前会话：${created.conversation_id}`;
  await loadConversations();
  await loadGodView(created.conversation_id);
}

async function streamChat(payload) {
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || "stream request failed");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      if (event.type === "conversation") {
        state.conversationId = event.conversation_id;
        document.getElementById("session-hint").textContent = `当前会话：${event.conversation_id}`;
      } else if (event.type === "message_start") {
        startStreamingMessage(event.message);
      } else if (event.type === "message_delta") {
        appendStreamingDelta(event.speaker_id, event.delta);
      } else if (event.type === "message_end") {
        finishStreamingMessage(event.message);
      } else if (event.type === "done") {
        state.conversationId = event.turn.conversation_id;
        state.selectedConversationAgents = event.turn.selected_agents || payload.selected_agents;
        await loadConversations();
        await loadUserProfile();
        await loadGodView(event.turn.conversation_id);
      } else if (event.type === "error") {
        throw new Error(event.detail || "stream failed");
      }
    }

    if (done) break;
  }
}

document.addEventListener("change", (event) => {
  if (event.target.matches('input[name="mode"], input[name="agent"]')) {
    enforceModeRules();
  }
  if (event.target.id === "knowledge-scope") {
    document.getElementById("knowledge-agent").disabled = event.target.value !== "agent";
  }
  if (event.target.id === "cfg-service") {
    updateConfigFields();
  }
  if (event.target.matches("[data-agent-service]")) {
    refreshAgentModelOptions(event.target.dataset.agentService);
  }
  if (event.target.id === "god-view-filter" && state.godView) {
    renderGodView(state.godView);
  }
  if (event.target.id === "conversation-mode-filter" || event.target.id === "conversation-agent-filter") {
    renderConversationList();
  }
});

document.addEventListener("input", (event) => {
  if (event.target.id === "conversation-search") {
    renderConversationList();
  }
});

document.addEventListener("click", (event) => {
  const editTarget = event.target.closest("[data-edit-agent]");
  if (editTarget) {
    const agent = getAgentById(editTarget.dataset.editAgent);
    if (agent) {
      enterEditMode(agent);
    }
    return;
  }

  const deleteTarget = event.target.closest("[data-delete-agent]");
  if (deleteTarget) {
    const agent = getAgentById(deleteTarget.dataset.deleteAgent);
    if (!agent) return;
    const ok = window.confirm(`确定删除自定义角色卡“${agent.name}”吗？`);
    if (!ok) return;
    fetchJSON(`/api/agents/${agent.agent_id}`, { method: "DELETE" })
      .then(async () => {
        if (document.getElementById("editing-agent-id").value === agent.agent_id) {
          exitEditMode();
        }
        await loadAgents();
        await loadGodView();
        document.getElementById("agent-status").textContent = `角色卡已删除：${agent.name}`;
      })
      .catch((error) => {
        document.getElementById("agent-status").textContent = `删除失败：${error.message}`;
      });
  }

  const saveBackendTarget = event.target.closest("[data-save-agent-llm]");
  if (saveBackendTarget) {
    const agentId = saveBackendTarget.dataset.saveAgentLlm;
    const serviceSelect = document.querySelector(`[data-agent-service="${agentId}"]`);
    const modelSelect = document.querySelector(`[data-agent-model="${agentId}"]`);
    if (!serviceSelect || !modelSelect) return;
    fetchJSON(`/api/agents/${agentId}/llm-config`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        service: serviceSelect.value,
        model: modelSelect.value,
      }),
    })
      .then(async () => {
        await loadAgents();
        document.getElementById("session-hint").textContent = `已更新角色后端：${getAgentById(agentId)?.name || agentId}`;
      })
      .catch((error) => {
        document.getElementById("session-hint").textContent = `角色后端更新失败：${error.message}`;
      });
  }
});

document.getElementById("new-discussion-button").addEventListener("click", async () => {
  try {
    await startNewDiscussion();
  } catch (error) {
    document.getElementById("session-hint").textContent = `新会话创建失败：${error.message}`;
  }
});

document.getElementById("chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  let userMessage = document.getElementById("user-message").value.trim();
  const agents = selectedAgents();
  if (!userMessage) return;
  if (!agents.length) {
    alert("请至少选择一位讨论者。");
    return;
  }

  try {
    const fileInput = document.getElementById("chat-file-input");
    if (fileInput && fileInput.files.length > 0) {
      const formData = new FormData();
      formData.append("file", fileInput.files[0]);
      const result = await fetchJSON("/api/chat/upload", { method: "POST", body: formData });
      userMessage = userMessage + "\n\n---\n**附件：** " + result.filename + "\n\n" + result.text;
      fileInput.value = "";
      document.getElementById("chat-attachments").innerHTML = "";
    }

    const displayMessage = document.getElementById("user-message").value.trim();
    document.getElementById("user-message").value = "";

    appendMessage({
      role: "user",
      speaker_id: "user",
      speaker_name: "You",
      content: displayMessage,
    });

    document.getElementById("session-hint").textContent = "讨论进行中...";

    await streamChat({
      conversation_id: state.conversationId,
      mode: selectedMode(),
      selected_agents: agents,
      memory_enabled: document.getElementById("memory-enabled").checked,
      user_message: userMessage,
    });
  } catch (error) {
    appendMessage({
      role: "assistant",
      speaker_id: "moderator",
      speaker_name: "System",
      content: `请求失败：${error.message}`,
    });
    document.getElementById("session-hint").textContent = "请求失败，请检查后端日志。";
  }
});

document.getElementById("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  try {
    const result = await fetchJSON("/api/knowledge/upload", {
      method: "POST",
      body: data,
    });
    document.getElementById("upload-status").textContent =
      `上传成功：${result.filename}，已切分 ${result.chunks} 个知识块。`;
    form.reset();
    document.getElementById("knowledge-agent").disabled = true;
  } catch (error) {
    document.getElementById("upload-status").textContent = `上传失败：${error.message}`;
  }
});

document.getElementById("agent-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const editingAgentId = document.getElementById("editing-agent-id").value.trim();
  const payload = {
    name: document.getElementById("agent-name").value.trim(),
    title: document.getElementById("agent-title").value.trim(),
    expertise: document
      .getElementById("agent-expertise")
      .value
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean),
    style: document.getElementById("agent-style").value.trim(),
    objective: document.getElementById("agent-objective").value.trim(),
  };

  try {
    const method = editingAgentId ? "PUT" : "POST";
    const url = editingAgentId ? `/api/agents/${editingAgentId}` : "/api/agents";
    const agent = await fetchJSON(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    await loadAgents();
    fillAgentSelection(agent.agent_id);
    document.getElementById("knowledge-scope").value = "agent";
    document.getElementById("knowledge-agent").disabled = false;
    document.getElementById("knowledge-agent").value = agent.agent_id;
    exitEditMode(true);
    document.getElementById("agent-status").textContent = editingAgentId
      ? `角色卡已更新：${agent.name}`
      : `角色卡已创建：${agent.name}`;
  } catch (error) {
    document.getElementById("agent-status").textContent = `操作失败：${error.message}`;
  }
});

document.getElementById("user-profile-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    name: document.getElementById("user-profile-name").value.trim(),
    title: document.getElementById("user-profile-title").value.trim(),
    expertise: document
      .getElementById("user-profile-expertise")
      .value
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean),
    style: document.getElementById("user-profile-style").value.trim(),
    objective: document.getElementById("user-profile-objective").value.trim(),
    profile_summary: document.getElementById("user-profile-summary").value.trim(),
  };

  try {
    const profile = await fetchJSON("/api/user-profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    renderUserProfile(profile);
    await loadGodView();
    document.getElementById("user-profile-status").textContent = "用户角色卡已保存。";
  } catch (error) {
    document.getElementById("user-profile-status").textContent = `保存失败：${error.message}`;
  }
});

document.getElementById("agent-cancel-button").addEventListener("click", () => {
  exitEditMode();
});

document.getElementById("chat-file-input").addEventListener("change", (event) => {
  const file = event.target.files[0];
  const container = document.getElementById("chat-attachments");
  container.innerHTML = "";
  if (file) {
    container.innerHTML = `<span class="attach-chip">📎 ${file.name} <button type="button" class="attach-remove">✕</button></span>`;
    container.querySelector(".attach-remove").addEventListener("click", () => {
      event.target.value = "";
      container.innerHTML = "";
    });
  }
});

document.getElementById("llm-config-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    service: document.getElementById("cfg-service").value,
    model: document.getElementById("cfg-model").value,
  };

  try {
    await fetchJSON("/api/llm-config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    document.getElementById("llm-config-status").textContent = "配置已保存。";
    await loadProviderStatus();
  } catch (error) {
    document.getElementById("llm-config-status").textContent = `保存失败：${error.message}`;
  }
});

async function bootstrap() {
  initializePanelToggles();
  await loadProviderStatus();
  await loadLLMServices();
  await loadLLMConfig();
  await loadAgents();
  await loadUserProfile();
  document.getElementById("knowledge-agent").disabled = true;
  await loadConversations();
  await loadGodView();
  resetChat();
}

bootstrap();
