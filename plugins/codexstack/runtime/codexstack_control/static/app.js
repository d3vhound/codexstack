"use strict";

const state = {
  config: null,
  runs: new Map(),
  selectedId: null,
  events: new Map(),
  eventOrder: [],
  eventCursor: null,
  eventEpoch: 0,
  eventsLoading: false,
  runsLoading: true,
  runsError: null,
  eventsError: null,
  runsPolling: false,
  eventsPolling: false,
  connected: false,
  previewUrl: null,
  activeTab: "changes",
  deepLink: null,
  noticeTimer: null,
  startBusy: false,
  busyRuns: new Set(),
  desktopUrl: null,
  desktopUrlExpiresAt: 0,
  pendingStart: null,
  pendingMessages: new Map(),
  drafts: new Map(),
  eventNodes: new Map()
};

const MAX_EVENTS = 500;
const PENDING_START_KEY = "codexstack.pendingStart";
const PENDING_MESSAGE_PREFIX = "codexstack.pendingMessage.";

const dom = {};

const statusMeta = {
  starting: { label: "Starting", action: "Provisioning sandbox" },
  working: { label: "Working", action: "Agent is working" },
  verifying: { label: "Verifying", action: "Running verification" },
  needs_input: { label: "Needs input", action: "Waiting for direction" },
  review: { label: "Ready for review", action: "Review the delivered changes" },
  done: { label: "Finished", action: "Work completed" },
  failed: { label: "Failed", action: "Run needs attention" },
  stopped: { label: "Stopped", action: "Sandbox is stopped" }
};

const groups = [
  { name: "Active", statuses: ["starting", "working", "verifying"] },
  { name: "Needs you", statuses: ["needs_input"] },
  { name: "Review", statuses: ["review"] },
  { name: "Done", statuses: ["done", "failed", "stopped"] }
];

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function byId(id) {
  return document.getElementById(id);
}

function makeElement(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined) node.textContent = String(options.text);
  if (options.type) node.type = options.type;
  if (options.title) node.title = options.title;
  if (options.hidden !== undefined) node.hidden = options.hidden;
  if (options.disabled !== undefined) node.disabled = options.disabled;
  if (options.role) node.setAttribute("role", options.role);
  if (options.ariaLabel) node.setAttribute("aria-label", options.ariaLabel);
  if (options.href) node.href = options.href;
  for (const child of children) {
    if (child !== null && child !== undefined) node.append(child);
  }
  return node;
}

function replaceChildren(node, children) {
  node.replaceChildren(...children.filter((child) => child !== null && child !== undefined));
}

function randomId() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function getControlToken() {
  return sessionStorage.getItem("codexstack.controlToken") || "";
}

function sessionObject(key) {
  try {
    const value = JSON.parse(sessionStorage.getItem(key) || "null");
    return value && typeof value === "object" && !Array.isArray(value) ? value : null;
  } catch (error) {
    return null;
  }
}

function setPendingStart(value) {
  state.pendingStart = value;
  if (value) sessionStorage.setItem(PENDING_START_KEY, JSON.stringify(value));
  else sessionStorage.removeItem(PENDING_START_KEY);
}

function pendingMessageKey(runId) {
  return `${PENDING_MESSAGE_PREFIX}${runId}`;
}

function getPendingMessage(runId) {
  if (state.pendingMessages.has(runId)) return state.pendingMessages.get(runId);
  const value = sessionObject(pendingMessageKey(runId));
  if (value) state.pendingMessages.set(runId, value);
  return value;
}

function setPendingMessage(runId, value) {
  if (value) {
    state.pendingMessages.set(runId, value);
    sessionStorage.setItem(pendingMessageKey(runId), JSON.stringify(value));
  } else {
    state.pendingMessages.delete(runId);
    sessionStorage.removeItem(pendingMessageKey(runId));
  }
}

function mutationMethod(method) {
  return !["GET", "HEAD", "OPTIONS"].includes(method);
}

async function api(path, options = {}) {
  const method = options.method || "GET";
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  const token = getControlToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  if (mutationMethod(method)) {
    headers.set("X-CodexStack-CSRF", state.config?.csrfToken || "");
  }

  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
      cache: "no-store"
    });
  } catch (error) {
    setConnection(false);
    throw new ApiError(navigator.onLine ? "Control service is unreachable." : "You are offline.", 0);
  }

  setConnection(true);
  let payload = null;
  try {
    payload = await response.json();
  } catch (error) {
    payload = null;
  }

  if (!response.ok) {
    if (response.status === 401) openAccessDialog();
    const message = payload?.error?.message || payload?.error || payload?.message || `Request failed with status ${response.status}.`;
    throw new ApiError(String(message), response.status);
  }
  return payload || {};
}

function setConnection(connected) {
  state.connected = connected;
  const offline = !navigator.onLine || !connected;
  dom.connectionDot.classList.toggle("is-online", !offline);
  dom.connectionDot.classList.toggle("is-offline", offline);
  dom.connectionLabel.textContent = offline ? "Disconnected" : "Connected";
}

function showNotice(message, isError = false, duration = 4200) {
  window.clearTimeout(state.noticeTimer);
  dom.notice.textContent = String(message);
  dom.notice.classList.toggle("is-error", isError);
  dom.notice.hidden = false;
  state.noticeTimer = window.setTimeout(() => {
    dom.notice.hidden = true;
  }, duration);
}

function displayStatus(status) {
  return statusMeta[status] || { label: humanize(status || "unknown"), action: "Status reported by Box" };
}

function humanize(value) {
  return String(value || "Unknown")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function relativeTime(value) {
  if (!value) return "Time unavailable";
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return String(value);
  const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (seconds < 10) return "Just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function exactValue(value) {
  if (value === null || value === undefined || value === "") return "Pending";
  return String(value);
}

function safeHttpUrl(value) {
  if (!value) return null;
  try {
    const url = new URL(String(value));
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch (error) {
    return null;
  }
}

function openUrl(url) {
  const safe = safeHttpUrl(url);
  if (!safe) {
    showNotice("The service returned an invalid URL.", true);
    return false;
  }
  const opened = window.open(safe, "_blank", "noopener,noreferrer");
  if (!opened) {
    showNotice("Your browser blocked the new tab. Allow popups, then try again.", true);
    return false;
  }
  return true;
}

function currentRun() {
  return state.selectedId ? state.runs.get(state.selectedId) || null : null;
}

function readDeepLink() {
  const match = window.location.pathname.match(/^\/runs\/([^/]+)\/?$/);
  if (!match) return null;
  let id;
  try {
    id = decodeURIComponent(match[1]);
  } catch (error) {
    return null;
  }
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(id)) return null;
  const requested = new URLSearchParams(window.location.search).get("open");
  return { id, tab: ["changes", "preview", "desktop"].includes(requested) ? requested : "changes" };
}

function writeRunLocation(replace = false) {
  if (!state.selectedId) return;
  const path = `/runs/${encodeURIComponent(state.selectedId)}`;
  const query = state.activeTab === "changes" ? "" : `?open=${encodeURIComponent(state.activeTab)}`;
  const method = replace ? "replaceState" : "pushState";
  window.history[method]({ runId: state.selectedId, tab: state.activeTab }, "", `${path}${query}`);
}

function runPriority(run) {
  const priority = { needs_input: 0, review: 1, working: 2, verifying: 2, starting: 3, failed: 4, done: 5, stopped: 6 };
  return priority[run.status] ?? 7;
}

function sortedRuns() {
  return [...state.runs.values()].sort((a, b) => {
    const statusDifference = runPriority(a) - runPriority(b);
    if (statusDifference !== 0) return statusDifference;
    return new Date(b.updatedAt || b.createdAt || 0) - new Date(a.updatedAt || a.createdAt || 0);
  });
}

function renderRunRail() {
  const query = dom.runSearch.value.trim().toLowerCase();
  const runs = sortedRuns().filter((run) => {
    if (!query) return true;
    return [run.title, run.repo, run.branch, run.status, run.statusDetail]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query));
  });

  if (state.runsLoading) {
    dom.railState.hidden = false;
    dom.railState.classList.remove("is-error");
    replaceChildren(dom.railState, [
      makeElement("span", { className: "spinner" }),
      makeElement("span", { text: "Loading agents" })
    ]);
    dom.runGroups.hidden = true;
    return;
  }

  if (state.runsError && state.runs.size === 0) {
    dom.railState.hidden = false;
    dom.railState.classList.add("is-error");
    dom.railState.textContent = "Could not load agents. Retrying.";
    dom.runGroups.hidden = true;
    return;
  }

  dom.railState.hidden = true;
  dom.railState.classList.remove("is-error");
  dom.runGroups.hidden = false;
  const groupNodes = groups.map((group) => {
    const section = makeElement("section", { className: "run-group" });
    const matching = runs.filter((run) => group.statuses.includes(run.status));
    const heading = makeElement("div", { className: "group-heading" }, [
      makeElement("span", { text: group.name }),
      makeElement("span", { text: matching.length })
    ]);
    section.append(heading);
    if (matching.length === 0) {
      section.append(makeElement("div", { className: "group-empty", text: query ? "No matches" : "None" }));
    } else {
      for (const run of matching) section.append(buildRunCard(run));
    }
    return section;
  });
  replaceChildren(dom.runGroups, groupNodes);
}

function buildRunCard(run) {
  const meta = displayStatus(run.status);
  const button = makeElement("button", {
    className: `run-card status-${run.status || "neutral"}${run.id === state.selectedId ? " is-selected" : ""}`,
    type: "button",
    ariaLabel: `${run.title || run.repo || "Agent run"}, ${meta.label}`
  });
  if (run.id === state.selectedId) button.setAttribute("aria-current", "true");
  const dot = makeElement("span", { className: "status-dot" });
  dot.setAttribute("aria-hidden", "true");
  const copy = makeElement("span", { className: "run-card-copy" }, [
    makeElement("span", { className: "run-card-title", text: run.title || run.repo || "Untitled agent" }),
    makeElement("span", { className: "run-card-repo", text: run.repo || "Repository pending" }),
    makeElement("span", { className: "run-card-action", text: run.statusDetail || meta.action })
  ]);
  button.append(dot, copy);
  button.addEventListener("click", () => selectRun(run.id, true));
  return button;
}

function renderSelectedRun() {
  const run = currentRun();
  dom.setupBanner.hidden = state.config?.boxConfigured !== false;
  if (!run) {
    dom.activityHeading.textContent = "Agent activity";
    dom.selectedStatus.textContent = "No run";
    dom.selectedStatus.className = "status-pill status-neutral";
    dom.runMeta.textContent = "Select an agent to inspect its work.";
    dom.runStateDetail.hidden = true;
    dom.runStateDetail.textContent = "";
    replaceChildren(dom.headerActions, []);
    dom.emptyStage.hidden = false;
    dom.timeline.hidden = true;
    renderComposer();
    renderProof();
    return;
  }

  const meta = displayStatus(run.status);
  dom.activityHeading.textContent = run.title || run.repo || "Agent run";
  dom.selectedStatus.textContent = meta.label;
  dom.selectedStatus.className = `status-pill status-${run.status || "neutral"}`;
  replaceChildren(dom.runMeta, buildRunMeta(run));
  dom.runStateDetail.textContent = run.lastError
    ? `${run.statusDetail || "Run needs attention"} (${run.lastError})`
    : run.statusDetail || "";
  dom.runStateDetail.classList.toggle("is-error", Boolean(run.lastError));
  dom.runStateDetail.hidden = !dom.runStateDetail.textContent;
  replaceChildren(dom.headerActions, buildHeaderActions(run));
  dom.emptyStage.hidden = true;
  dom.timeline.hidden = false;
  renderComposer();
  renderProof();
}

function buildRunMeta(run) {
  const children = [];
  children.push(document.createTextNode(run.repo || "Repository pending"));
  if (run.branch) {
    children.push(document.createTextNode("  ·  "));
    children.push(makeElement("code", { text: run.branch }));
  }
  if (run.model) children.push(document.createTextNode(`  ·  ${run.model}`));
  children.push(document.createTextNode(`  ·  ${relativeTime(run.updatedAt || run.createdAt)}`));
  return children;
}

function buildHeaderActions(run) {
  const actions = [];
  const busy = runBusy(run.id);
  const resumable = run.status === "stopped" || (
    run.slotReleased === true && ["archived", "stopped"].includes(run.boxState)
  );
  if (resumable) {
    const resume = makeElement("button", { className: "button button-secondary button-compact", text: busy ? "Resuming" : "Resume 12h", type: "button", disabled: busy });
    resume.addEventListener("click", () => mutateRun("resume", { ttlSeconds: 43200, idempotencyKey: randomId() }, "Agent resumed."));
    actions.push(resume);
  } else if (!run.slotReleased) {
    if (run.status === "needs_input" && !run.slotReleased) {
      const handoff = makeElement("button", {
        className: "button button-quiet button-compact",
        text: busy ? "Working" : "Verify handoff",
        type: "button",
        disabled: busy || !run.promptId
      });
      handoff.addEventListener("click", () => mutateRun("handoff", {}, "Handoff prepared."));
      actions.push(handoff);
    }
    const stop = makeElement("button", { className: "button button-secondary button-compact", text: "Stop", type: "button", disabled: busy });
    stop.addEventListener("click", async () => {
      if (!window.confirm("Stop this agent and its sandbox?")) return;
      await mutateRun("stop", { idempotencyKey: randomId() }, "Agent stopped.");
    });
    actions.push(stop);
  }
  return actions;
}

function runBusy(runId) {
  return Boolean(runId && state.busyRuns.has(runId));
}

function renderComposer() {
  const run = currentRun();
  const disabledStatus = !run || !run.promptId || run.slotReleased || ["starting", "verifying", "stopped", "failed"].includes(run.status);
  dom.composerInput.disabled = disabledStatus || runBusy(run?.id);
  dom.composerInput.placeholder = !run?.promptId
    ? "No managed prompt revision; inspect or start a new run"
    : run?.status === "needs_input"
      ? "Answer the agent or clarify the next step"
      : "Send the next instruction";
  dom.composerContext.textContent = run ? `${run.repo || "Repository"} · ${displayStatus(run.status).label}` : "Select an active agent";
  updateComposerButtons();
}

function updateComposerButtons() {
  const run = currentRun();
  const hasText = dom.composerInput.value.trim().length > 0;
  const canMessage = Boolean(run?.promptId) && !run?.slotReleased && !["starting", "verifying", "stopped", "failed"].includes(run.status) && !runBusy(run?.id);
  const canInterrupt = Boolean(run?.promptId) && !run?.slotReleased && run.status === "working" && !runBusy(run?.id);
  dom.sendButton.disabled = !hasText || !canMessage;
  dom.redirectButton.disabled = !hasText || !canInterrupt;
}

function eventKey(event) {
  if (event.id !== undefined && event.id !== null) return String(event.id);
  if (event.eventId !== undefined && event.eventId !== null) return String(event.eventId);
  const dataId = event.data?.id || event.data?.promptId || event.data?.toolCallId || "";
  return `${event.type || "event"}:${event.timestamp || "time"}:${dataId}`;
}

function ingestEvents(events) {
  for (const event of events || []) {
    const key = eventKey(event);
    if (!state.events.has(key)) state.eventOrder.push(key);
    state.events.set(key, event);
  }
  while (state.eventOrder.length > MAX_EVENTS) {
    const key = state.eventOrder.shift();
    state.events.delete(key);
    const rendered = state.eventNodes.get(key);
    if (rendered) rendered.node.remove();
    state.eventNodes.delete(key);
  }
  if (state.selectedId) renderProof();
}

function renderEvents() {
  if (!state.selectedId) return;
  const nearBottom = dom.activityScroll.scrollHeight - dom.activityScroll.scrollTop - dom.activityScroll.clientHeight < 140;
  if (state.eventsLoading && state.eventOrder.length === 0) {
    state.eventNodes.clear();
    replaceChildren(dom.timeline, [
      makeElement("div", { className: "timeline-loading" }, [
        makeElement("span", { className: "spinner" }),
        makeElement("span", { text: "Loading agent activity" })
      ])
    ]);
    return;
  }
  if (state.eventsError && state.eventOrder.length === 0) {
    state.eventNodes.clear();
    replaceChildren(dom.timeline, [
      makeElement("div", { className: "timeline-loading timeline-error", text: "Activity is unavailable. Retrying." })
    ]);
    return;
  }
  if (state.eventOrder.length === 0) {
    state.eventNodes.clear();
    replaceChildren(dom.timeline, [
      makeElement("div", { className: "timeline-loading", text: "Waiting for the first Box event." })
    ]);
    return;
  }
  if (state.eventNodes.size === 0) replaceChildren(dom.timeline, []);
  for (const key of state.eventOrder) {
    const event = state.events.get(key);
    const signature = JSON.stringify(event);
    const rendered = state.eventNodes.get(key);
    if (rendered?.signature === signature) continue;
    if (rendered?.node.contains(document.activeElement)) continue;
    const card = buildEventCard(event);
    if (rendered) {
      const open = [...rendered.node.querySelectorAll("details")].map((item) => item.open);
      card.querySelectorAll("details").forEach((item, index) => {
        item.open = open[index] || false;
      });
      rendered.node.replaceWith(card);
    } else {
      dom.timeline.append(card);
    }
    state.eventNodes.set(key, { node: card, signature });
  }
  if (nearBottom) requestAnimationFrame(() => {
    dom.activityScroll.scrollTop = dom.activityScroll.scrollHeight;
  });
}

function buildEventCard(event) {
  const type = String(event?.type || "unknown");
  const normalized = type.toLowerCase().replace(/[^a-z0-9_]+/g, "_");
  const data = event?.data && typeof event.data === "object" ? event.data : {};
  const streaming = Boolean(data.is_streaming || data.isStreaming);
  const card = makeElement("article", { className: `event-card event-${normalized}${streaming ? " event-streaming" : ""}` });
  const node = makeElement("span", { className: "event-node" });
  node.setAttribute("aria-hidden", "true");
  const labelWrap = makeElement("div", { className: "event-label" }, [
    document.createTextNode(eventLabel(type))
  ]);
  if (streaming) labelWrap.append(makeElement("span", { className: "streaming-label", text: "Streaming" }));
  const header = makeElement("header", { className: "event-header" }, [
    labelWrap,
    makeElement("time", { className: "event-time", text: formatTimestamp(event?.timestamp) })
  ]);
  card.append(node, header);

  if (normalized === "git_checkpoint") {
    card.append(buildCheckpoint(data));
    return card;
  }

  const content = extractContent(data, event);
  if (content) card.append(makeElement("div", { className: "event-content", text: content }));
  const tools = extractTools(data);
  if (tools.length) card.append(buildToolList(tools));
  if (!content && tools.length === 0) {
    card.append(makeElement("pre", { className: "generic-data", text: formatValue(event?.data ?? event) }));
  }
  return card;
}

function eventLabel(type) {
  const normalized = String(type).toLowerCase();
  if (normalized === "prompt") return "Prompt";
  if (normalized === "response") return "Codex";
  if (normalized === "git_checkpoint") return "Git checkpoint";
  return humanize(type);
}

function formatTimestamp(value) {
  if (!value) return "Time pending";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return String(value);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function extractContent(data, event) {
  const value = data.content ?? data.message ?? data.prompt ?? data.text ?? (typeof event?.data === "string" ? event.data : "");
  return contentToText(value);
}

function contentToText(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(contentToText).filter(Boolean).join("\n");
  if (typeof value === "object") {
    if (value.text !== undefined) return contentToText(value.text);
    if (value.content !== undefined) return contentToText(value.content);
  }
  return formatValue(value);
}

function extractTools(data) {
  const value = data.tools ?? data.tool_calls ?? data.toolCalls;
  if (!value && data.use && typeof data.use === "object") return [{ key: "tool", value: data }];
  if (!value) return [];
  if (Array.isArray(value)) return value.map((tool, index) => ({ key: String(index + 1), value: tool }));
  if (typeof value === "object") return Object.entries(value).map(([key, tool]) => ({ key, value: tool }));
  return [{ key: "tool", value }];
}

function buildToolList(tools) {
  const list = makeElement("div", { className: "tool-list" });
  for (const entry of tools) {
    const tool = entry.value && typeof entry.value === "object" ? entry.value : { output: entry.value };
    const use = tool.use && typeof tool.use === "object" ? tool.use : {};
    const result = tool.result;
    const name = use.name || tool.name || tool.tool_name || tool.toolName || tool.tool || entry.key || "Tool";
    const inputValue = use.input ?? tool.input ?? tool.args ?? tool.arguments;
    const command = tool.command || inputValue?.command;
    const stateText = tool.status || tool.state || result?.status || (tool.error || result?.error ? "failed" : "");
    const details = makeElement("details", { className: "tool-row" });
    const summaryName = command ? `${name} · ${String(command)}` : String(name);
    const summary = makeElement("summary", { className: "tool-summary" }, [
      makeElement("span", { className: "tool-name", text: summaryName }),
      makeElement("span", { className: "tool-state", text: stateText })
    ]);
    const body = makeElement("div", { className: "tool-body" });
    const input = inputValue;
    const output = tool.output ?? result ?? tool.error;
    if (input !== undefined) appendToolSection(body, "Input", input);
    if (output !== undefined) appendToolSection(body, tool.error ? "Error" : "Result", output);
    if (input === undefined && output === undefined) appendToolSection(body, "Details", tool);
    details.append(summary, body);
    list.append(details);
  }
  return list;
}

function appendToolSection(parent, label, value) {
  parent.append(
    makeElement("span", { className: "tool-section-label", text: label }),
    makeElement("pre", { className: "tool-output", text: formatValue(value) })
  );
}

function formatValue(value) {
  if (value === undefined) return "";
  if (value === null) return "null";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch (error) {
    return String(value);
  }
}

function buildCheckpoint(data) {
  const card = makeElement("div", { className: "checkpoint-card" });
  const pushed = data.pushed === true ? "Pushed checkpoint" : "Checkpoint created";
  card.append(makeElement("div", { className: "checkpoint-title", text: pushed }));
  if (data.commitMessage) card.append(makeElement("div", { className: "checkpoint-message", text: data.commitMessage }));
  const meta = makeElement("div", { className: "checkpoint-meta" });
  if (data.commitSha) meta.append(makeElement("span", { text: data.commitSha }));
  if (data.branch) meta.append(makeElement("span", { text: data.branch }));
  if (data.filesChanged !== undefined) meta.append(makeElement("span", { text: `${data.filesChanged} files` }));
  if (data.additions !== undefined || data.deletions !== undefined) {
    meta.append(makeElement("span", { text: `+${data.additions || 0} / -${data.deletions || 0}` }));
  }
  card.append(meta);
  return card;
}

function renderProof() {
  const run = currentRun();
  const hasRun = Boolean(run);
  dom.proofEmpty.hidden = hasRun;
  dom.changesContent.hidden = !hasRun;
  dom.requestPreview.disabled = !hasPreview(run) || run?.slotReleased || runBusy(run?.id);
  dom.requestPreview.textContent = hasPreview(run) ? "Load preview" : "No preview declared";
  dom.openDesktop.disabled = !run?.boxId || run?.slotReleased || runBusy(run?.id);
  if (!run) {
    replaceChildren(dom.changesContent, []);
    clearPreview();
    return;
  }
  replaceChildren(dom.changesContent, [
    buildChangesSection(),
    buildEvidenceSection(run),
    buildSetupSection(run),
    buildVerificationSection(run),
    buildPullRequestSection(run),
    buildRunControls(run)
  ]);
}

function buildSetupSection(run) {
  const section = makeElement("section", { className: "evidence-section" });
  section.append(makeElement("h2", { className: "section-heading", text: "Setup" }));
  const entries = normalizeReceipts(run.setupReceipts, run.workerConfig?.setup, "Setup");
  const stack = makeElement("div", { className: "proof-stack" });
  if (entries.length === 0) {
    stack.append(makeElement("div", { className: "proof-item" }, [
      makeElement("div", { className: "proof-item-head", text: "No setup commands declared" })
    ]));
  } else {
    for (const entry of entries) stack.append(buildProofItem(entry));
  }
  section.append(stack);
  return section;
}

function hasPreview(run) {
  return Boolean(run?.workerConfig?.preview);
}

function latestCheckpoint() {
  for (let index = state.eventOrder.length - 1; index >= 0; index -= 1) {
    const event = state.events.get(state.eventOrder[index]);
    if (String(event?.type || "").toLowerCase() === "git_checkpoint") return event.data || {};
  }
  return null;
}

function buildChangesSection() {
  const section = makeElement("section", { className: "evidence-section" });
  section.append(makeElement("h2", { className: "section-heading", text: "Changes" }));
  const checkpoint = latestCheckpoint();
  if (!checkpoint) {
    section.append(makeElement("div", { className: "proof-item" }, [
      makeElement("div", { className: "proof-item-head", text: "No git checkpoint yet" })
    ]));
    return section;
  }

  const files = Array.isArray(checkpoint.files) ? checkpoint.files : [];
  if (files.length > 0) {
    const list = makeElement("div", { className: "change-list" });
    for (const file of files) {
      const value = file && typeof file === "object" ? file : { path: file };
      const path = value.path || value.file || value.name || "Unknown file";
      const stats = [];
      if (value.status) stats.push(String(value.status));
      if (value.additions !== undefined) stats.push(`+${value.additions}`);
      if (value.deletions !== undefined) stats.push(`-${value.deletions}`);
      list.append(makeElement("div", { className: "change-file" }, [
        makeElement("span", { className: "change-path", text: path, title: path }),
        makeElement("span", { className: "change-stats", text: stats.join("  ") || "changed" })
      ]));
    }
    section.append(list);
    return section;
  }

  const list = makeElement("div", { className: "evidence-list" });
  const rows = [
    ["Files", checkpoint.filesChanged],
    ["Additions", checkpoint.additions === undefined ? undefined : `+${checkpoint.additions}`],
    ["Deletions", checkpoint.deletions === undefined ? undefined : `-${checkpoint.deletions}`],
    ["Commit", checkpoint.commitSha],
    ["Pushed", checkpoint.pushed === undefined ? undefined : checkpoint.pushed ? "Yes" : "No"]
  ].filter(([, value]) => value !== undefined && value !== null && value !== "");
  for (const [key, value] of rows) {
    list.append(makeElement("div", { className: "evidence-row" }, [
      makeElement("span", { className: "evidence-key", text: key }),
      makeElement("span", { className: "evidence-value", text: value, title: String(value) })
    ]));
  }
  if (rows.length === 0) {
    list.append(makeElement("div", { className: "evidence-row" }, [
      makeElement("span", { className: "evidence-key", text: "State" }),
      makeElement("span", { className: "evidence-value", text: "Checkpoint received" })
    ]));
  }
  section.append(list);
  return section;
}

function buildEvidenceSection(run) {
  const section = makeElement("section", { className: "evidence-section" });
  section.append(makeElement("h2", { className: "section-heading", text: "Git evidence" }));
  const list = makeElement("div", { className: "evidence-list" });
  const rows = [
    ["Branch", exactValue(run.branch)],
    ["Base", exactValue(run.baseRef)],
    ["Base SHA", exactValue(run.baseSha)],
    ["Head SHA", exactValue(run.headSha)]
  ];
  for (const [key, value] of rows) {
    list.append(makeElement("div", { className: "evidence-row" }, [
      makeElement("span", { className: "evidence-key", text: key }),
      makeElement("span", { className: "evidence-value", text: value, title: value })
    ]));
  }
  section.append(list);
  return section;
}

function buildVerificationSection(run) {
  const section = makeElement("section", { className: "evidence-section" });
  section.append(makeElement("h2", { className: "section-heading", text: "Verification" }));
  const stack = makeElement("div", { className: "proof-stack" });
  const entries = normalizeVerification(run);
  if (entries.length === 0) {
    stack.append(makeElement("div", { className: "proof-item" }, [
      makeElement("div", { className: "proof-item-head", text: run.status === "verifying" ? "Verification is running" : "No verification evidence yet" })
    ]));
  } else {
    for (const entry of entries) stack.append(buildProofItem(entry));
  }
  section.append(stack);
  return section;
}

function normalizeVerification(run) {
  return normalizeReceipts(run.verifyReceipts, run.workerConfig?.verify, "Check");
}

function normalizeReceipts(rawReceipts, rawDeclared, label) {
  const declared = Array.isArray(rawDeclared) ? rawDeclared : rawDeclared ? [rawDeclared] : [];
  const receipts = Array.isArray(rawReceipts)
    ? rawReceipts
    : rawReceipts && typeof rawReceipts === "object"
      ? Object.values(rawReceipts)
      : [];
  if (receipts.length > 0) {
    return receipts.map((receipt, index) => normalizeReceipt(receipt, index, declared[index], label));
  }

  return declared.map((command, index) => {
    const value = command && typeof command === "object" && !Array.isArray(command) ? command : { argv: command };
    const argv = value.argv ?? value.command ?? command;
    return {
      name: value.name || `${label} ${index + 1}`,
      body: `argv: ${formatArgv(argv)}`,
      status: "pending"
    };
  });
}

function normalizeReceipt(receipt, index, declaredCommand, label) {
  const value = receipt && typeof receipt === "object" ? receipt : { output: receipt };
  const argv = value.argv ?? value.command?.argv ?? value.command ?? declaredCommand;
  const exitCode = value.exitCode ?? value.exit_code ?? value.code;
  const success = value.success ?? value.ok ?? value.passed;
  let status = String(value.status || "unknown");
  if (success === true || exitCode === 0) status = "passed";
  if (success === false || (typeof exitCode === "number" && exitCode !== 0)) status = "failed";
  const lines = [];
  if (argv !== undefined) lines.push(`argv: ${formatArgv(argv)}`);
  lines.push(`success: ${success === undefined ? status === "passed" ? "true" : status === "failed" ? "false" : "pending" : String(success)}`);
  if (exitCode !== undefined) lines.push(`exit: ${exitCode}`);
  const output = value.output ?? value.stdout ?? value.stderr ?? value.message;
  if (output !== undefined && output !== "") lines.push(formatValue(output));
  return {
    name: value.name || value.label || `${label} ${index + 1}`,
    body: lines.join("\n"),
    status
  };
}

function formatArgv(argv) {
  if (Array.isArray(argv)) return JSON.stringify(argv.map((part) => String(part)));
  return formatValue(argv);
}

function buildProofItem(entry) {
  const status = entry.status.toLowerCase();
  let modifier = "";
  if (["passed", "success", "done", "ok"].includes(status)) modifier = " is-success";
  if (["failed", "failure", "error"].includes(status)) modifier = " is-failure";
  if (["running", "pending", "working"].includes(status)) modifier = " is-running";
  const item = makeElement("div", { className: `proof-item${modifier}` });
  item.append(makeElement("div", { className: "proof-item-head", text: entry.name }));
  if (entry.body !== "") item.append(makeElement("div", { className: "proof-item-body", text: formatValue(entry.body) }));
  return item;
}

function buildPullRequestSection(run) {
  const section = makeElement("section", { className: "evidence-section" });
  section.append(makeElement("h2", { className: "section-heading", text: "Pull request" }));
  const url = safeHttpUrl(run.prUrl);
  if (!url) {
    section.append(makeElement("div", { className: "proof-item" }, [
      makeElement("div", { className: "proof-item-head", text: run.status === "review" ? "Pull request evidence pending" : "Not opened yet" })
    ]));
    return section;
  }
  const verified = run.status === "review";
  const card = makeElement("div", { className: "pr-card" }, [
    makeElement("h3", { text: verified ? "Delivery verified" : "Pull request available" }),
    makeElement("p", { text: verified ? "GitHub was queried independently after push." : "GitHub delivery is available." })
  ]);
  if (verified) {
    const evidence = makeElement("div", { className: "evidence-list pr-evidence" });
    const rows = [
      ["State", "OPEN"],
      ["Draft", "No"],
      ["Base", exactValue(run.baseRef)],
      ["Head", exactValue(run.branch)],
      ["Head SHA", exactValue(run.headSha)]
    ];
    for (const [key, value] of rows) {
      evidence.append(makeElement("div", { className: "evidence-row" }, [
        makeElement("span", { className: "evidence-key", text: key }),
        makeElement("span", { className: "evidence-value", text: value, title: value })
      ]));
    }
    card.append(evidence);
  }
  const open = makeElement("button", { className: "button button-primary button-full", text: "Open PR", type: "button" });
  open.addEventListener("click", () => openUrl(url));
  card.append(open);
  section.append(card);
  return section;
}

function buildRunControls(run) {
  const section = makeElement("section", { className: "evidence-section" });
  section.append(makeElement("h2", { className: "section-heading", text: "Sandbox" }));
  const list = makeElement("div", { className: "evidence-list" });
  const values = [
    ["Box", exactValue(run.boxId)],
    ["Prompt", exactValue(run.promptId)],
    ["Model", exactValue(run.model)]
  ];
  for (const [key, value] of values) {
    list.append(makeElement("div", { className: "evidence-row" }, [
      makeElement("span", { className: "evidence-key", text: key }),
      makeElement("span", { className: "evidence-value", text: value, title: value })
    ]));
  }
  section.append(list);
  return section;
}

function selectTab(name, updateLocation = true) {
  if (!["changes", "preview", "desktop"].includes(name)) return;
  state.activeTab = name;
  const names = ["changes", "preview", "desktop"];
  for (const item of names) {
    const active = item === name;
    byId(`${item}-tab`).classList.toggle("is-active", active);
    byId(`${item}-tab`).setAttribute("aria-selected", String(active));
    byId(`${item}-tab`).tabIndex = active ? 0 : -1;
    byId(`${item}-panel`).hidden = !active;
  }
  if (updateLocation && state.selectedId) writeRunLocation();
}

function selectRun(id, openDetail = false, updateLocation = true) {
  if (!state.runs.has(id)) return;
  if (state.selectedId && dom.composerInput) {
    state.drafts.set(state.selectedId, dom.composerInput.value);
  }
  state.selectedId = id;
  state.events.clear();
  state.eventOrder = [];
  state.eventNodes.clear();
  replaceChildren(dom.timeline, []);
  state.eventCursor = null;
  state.eventEpoch += 1;
  state.eventsLoading = true;
  state.eventsError = null;
  state.desktopUrl = null;
  state.desktopUrlExpiresAt = 0;
  clearPreview();
  renderRunRail();
  renderSelectedRun();
  dom.composerInput.value = state.drafts.get(id) || "";
  updateComposerButtons();
  renderEvents();
  if (updateLocation) writeRunLocation();
  if (openDetail && window.matchMedia("(max-width: 760px)").matches) {
    document.body.classList.add("detail-open");
    requestAnimationFrame(() => dom.activityHeading.focus());
  }
  pollSelectedEvents(state.eventEpoch, true);
}

function chooseInitialRun() {
  if (state.selectedId && state.runs.has(state.selectedId)) return;
  const first = sortedRuns()[0];
  if (first) {
    selectRun(first.id, false, false);
    writeRunLocation(true);
  }
}

function updateRun(run) {
  if (!run?.id) return;
  state.runs.set(run.id, run);
  if (state.config) {
    state.config.activeRuns = [...state.runs.values()].filter(
      (item) => item.status !== "stopped" && item.slotReleased !== true
    ).length;
  }
  if (run.id === state.selectedId) {
    renderSelectedRun();
  }
  renderRunRail();
}

async function loadConfig() {
  try {
    state.config = await api("/api/config");
    dom.setupBanner.hidden = state.config.boxConfigured !== false;
    updateCapacity();
  } catch (error) {
    if (error.status !== 401) showNotice(error.message, true);
    state.config = { maxParallel: 4, csrfToken: "", boxConfigured: false };
    dom.setupBanner.hidden = false;
  }
}

async function pollRuns() {
  if (state.runsPolling) return;
  state.runsPolling = true;
  try {
    const payload = await api("/api/runs?limit=1000");
    const received = new Map();
    for (const run of payload.runs || []) {
      if (run?.id) received.set(run.id, run);
    }
    state.runs = received;
    if (state.config && Number.isInteger(payload.activeRuns)) {
      state.config.activeRuns = payload.activeRuns;
    }
    state.runsLoading = false;
    state.runsError = null;
    if (state.selectedId && !state.runs.has(state.selectedId)) {
      state.selectedId = null;
      state.events.clear();
      state.eventOrder = [];
    }
    if (state.deepLink) {
      const target = state.deepLink;
      state.deepLink = null;
      if (!state.runs.has(target.id)) {
        try {
          const direct = await api(`/api/runs/${encodeURIComponent(target.id)}`);
          if (direct.run?.id) state.runs.set(direct.run.id, direct.run);
        } catch (error) {
          if (error.status !== 404) throw error;
        }
      }
      if (state.runs.has(target.id)) {
        selectRun(target.id, true, false);
        selectTab(target.tab, false);
        if (target.tab !== "changes" && window.matchMedia("(max-width: 1099px)").matches) {
          setMobilePane("proof", true);
        }
      } else {
        showNotice("The requested agent run was not found.", true);
      }
    }
    chooseInitialRun();
    renderRunRail();
    renderSelectedRun();
    updateCapacity();
  } catch (error) {
    state.runsLoading = false;
    state.runsError = error.message;
    renderRunRail();
    if (error.status !== 401) showNotice(error.message, true);
  } finally {
    state.runsPolling = false;
  }
}

async function pollSelectedEvents(epoch, immediate = false) {
  if (!immediate) await new Promise((resolve) => window.setTimeout(resolve, 1300));
  if (epoch !== state.eventEpoch || !state.selectedId) return;
  if (state.eventsPolling) {
    pollSelectedEvents(epoch, false);
    return;
  }
  state.eventsPolling = true;
  const selectedId = state.selectedId;
  try {
    const query = state.eventCursor ? `?cursor=${encodeURIComponent(state.eventCursor)}` : "";
    const payload = await api(`/api/runs/${encodeURIComponent(selectedId)}/events${query}`);
    if (epoch !== state.eventEpoch || selectedId !== state.selectedId) return;
    if (payload.run) updateRun(payload.run);
    ingestEvents(payload.events);
    if (payload.nextCursor !== undefined && payload.nextCursor !== null) state.eventCursor = String(payload.nextCursor);
    state.eventsLoading = false;
    state.eventsError = null;
    renderEvents();
  } catch (error) {
    state.eventsLoading = false;
    state.eventsError = error.message;
    renderEvents();
    if (error.status !== 401) showNotice(error.message, true);
  } finally {
    state.eventsPolling = false;
    if (epoch === state.eventEpoch && state.selectedId) pollSelectedEvents(epoch, false);
  }
}

function updateCapacity() {
  const max = Number(state.config?.maxParallel || 4);
  const active = Number.isInteger(state.config?.activeRuns)
    ? state.config.activeRuns
    : [...state.runs.values()].filter((run) => run.status !== "stopped" && run.slotReleased !== true).length;
  dom.capacityNote.textContent = `${active} of ${max} parallel agent slots active.`;
  const blocked = state.config?.boxConfigured === false || state.startBusy || active >= max;
  dom.startRunButton.disabled = blocked;
  dom.newRunButton.disabled = state.config?.boxConfigured === false || state.startBusy;
  dom.emptyNewRun.disabled = state.config?.boxConfigured === false || state.startBusy;
  if (active >= max) dom.capacityNote.textContent = `${max} of ${max} slots active. Finish or stop a run first.`;
}

async function startRun(event) {
  event.preventDefault();
  if (state.startBusy) return;
  const repo = dom.newRepo.value.trim();
  const goal = dom.newGoal.value.trim();
  if (!repo || !goal) return;
  const draft = {
    repo,
    goal,
    ttlSeconds: Number(dom.newTtl.value),
    delivery: "open_pull_request"
  };
  const optional = {
    baseRef: dom.newBase.value.trim(),
    model: dom.newModel.value.trim(),
    reasoningEffort: dom.newEffort.value
  };
  for (const [key, value] of Object.entries(optional)) if (value) draft[key] = value;
  const signature = JSON.stringify(draft);
  if (!state.pendingStart) state.pendingStart = sessionObject(PENDING_START_KEY);
  if (state.pendingStart?.signature !== signature) {
    setPendingStart({ signature, idempotencyKey: randomId() });
  }
  const body = { ...draft, idempotencyKey: state.pendingStart.idempotencyKey };
  setStartBusy(true);
  dom.startRunButton.textContent = "Starting agent";
  try {
    const payload = await api("/api/runs", { method: "POST", body });
    if (payload.run) {
      setPendingStart(null);
      updateRun(payload.run);
      closeDialog(dom.newRunDialog);
      dom.newRunForm.reset();
      dom.newTtl.value = "43200";
      selectRun(payload.run.id, true);
      showNotice("Agent started in an isolated Box.");
    }
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    dom.startRunButton.textContent = "Start and open PR";
    setStartBusy(false);
  }
}

async function sendMessage(interruptFirst) {
  const run = currentRun();
  const message = dom.composerInput.value.trim();
  if (!run || !message || run.slotReleased || runBusy(run.id)) return;
  if (interruptFirst && !window.confirm("Interrupt the current prompt and send this direction next?")) return;
  setRunBusy(run.id, true);
  try {
    let latestRun = run;
    if (interruptFirst && run.status === "working") {
      const interrupted = await api(`/api/runs/${encodeURIComponent(run.id)}/interrupt`, {
        method: "POST",
        body: { expectedPromptId: run.promptId }
      });
      if (interrupted.run) {
        latestRun = interrupted.run;
        updateRun(interrupted.run);
      }
    }
    const expectedPromptId = latestRun.promptId || run.promptId;
    const pending = getPendingMessage(run.id);
    if (
      !pending
      || pending.message !== message
      || pending.expectedPromptId !== expectedPromptId
    ) {
      setPendingMessage(run.id, {
        message,
        idempotencyKey: randomId(),
        expectedPromptId
      });
    }
    const body = getPendingMessage(run.id);
    const payload = await api(`/api/runs/${encodeURIComponent(run.id)}/messages`, { method: "POST", body });
    if (payload.run) {
      setPendingMessage(run.id, null);
      state.drafts.delete(run.id);
      updateRun(payload.run);
    }
    if (currentRun()?.id === run.id) dom.composerInput.value = "";
    showNotice(interruptFirst ? "Current work interrupted. New direction queued." : "Instruction queued.");
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    setRunBusy(run.id, false);
  }
}

async function mutateRun(action, body, successMessage) {
  const run = currentRun();
  if (!run || runBusy(run.id)) return;
  setRunBusy(run.id, true);
  try {
    const payload = await api(`/api/runs/${encodeURIComponent(run.id)}/${action}`, { method: "POST", body });
    if (payload.run) updateRun(payload.run);
    showNotice(successMessage);
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    setRunBusy(run.id, false);
  }
}

function setStartBusy(busy) {
  state.startBusy = busy;
  updateCapacity();
}

function setRunBusy(runId, busy) {
  if (busy) state.busyRuns.add(runId);
  else state.busyRuns.delete(runId);
  if (currentRun()?.id === runId) renderSelectedRun();
}

async function requestPreview() {
  const run = currentRun();
  if (!run || run.slotReleased || !hasPreview(run) || runBusy(run.id)) return;
  const runId = run.id;
  setRunBusy(runId, true);
  dom.requestPreview.textContent = "Loading preview";
  try {
    const payload = await api(`/api/runs/${encodeURIComponent(run.id)}/preview`, { method: "POST", body: {} });
    if (currentRun()?.id !== runId) return;
    const url = safeHttpUrl(payload.url);
    if (!url) throw new ApiError("The preview service returned an invalid URL.", 0);
    state.previewUrl = url;
    dom.previewFrame.src = url;
    dom.previewFrameWrap.hidden = false;
    dom.previewLabel.textContent = run.previewPort ? `Port ${run.previewPort}` : "Live preview";
  } catch (error) {
    if (currentRun()?.id === runId) showNotice(error.message, true);
  } finally {
    setRunBusy(runId, false);
    if (currentRun()?.id !== runId) return;
    dom.requestPreview.textContent = hasPreview(currentRun()) ? "Refresh preview" : "No preview declared";
    dom.requestPreview.disabled = !hasPreview(currentRun()) || currentRun()?.slotReleased || runBusy(currentRun()?.id);
  }
}

async function requestDesktop() {
  const run = currentRun();
  if (!run || run.slotReleased || runBusy(run.id)) return;
  const runId = run.id;
  if (state.desktopUrl && Date.now() < state.desktopUrlExpiresAt) {
    if (openUrl(state.desktopUrl)) {
      state.desktopUrl = null;
      state.desktopUrlExpiresAt = 0;
      dom.openDesktop.textContent = "Open live sandbox";
    }
    return;
  }
  const target = window.open("about:blank", "_blank");
  if (target) {
    target.opener = null;
    target.document.title = "Opening live sandbox";
  }
  setRunBusy(runId, true);
  dom.openDesktop.textContent = "Requesting access";
  try {
    const payload = await api(`/api/runs/${encodeURIComponent(run.id)}/desktop`, { method: "POST", body: {} });
    if (currentRun()?.id !== runId) {
      if (target) target.close();
      return;
    }
    const url = safeHttpUrl(payload.url);
    if (!url) throw new ApiError("The desktop service returned an invalid URL.", 0);
    if (target) target.location.replace(url);
    else {
      state.desktopUrl = url;
      state.desktopUrlExpiresAt = Date.now() + 9 * 60 * 1000;
      dom.openDesktop.textContent = "Open granted sandbox";
      showNotice("Access is ready. Click Open granted sandbox to continue.");
    }
  } catch (error) {
    if (target) target.close();
    if (currentRun()?.id === runId) showNotice(error.message, true);
  } finally {
    setRunBusy(runId, false);
    if (currentRun()?.id !== runId) return;
    if (!state.desktopUrl) dom.openDesktop.textContent = "Open live sandbox";
    dom.openDesktop.disabled = !currentRun()?.boxId || currentRun()?.slotReleased || runBusy(currentRun()?.id);
  }
}

function clearPreview() {
  state.previewUrl = null;
  if (dom.previewFrame) dom.previewFrame.removeAttribute("src");
  if (dom.previewFrameWrap) dom.previewFrameWrap.hidden = true;
  if (dom.requestPreview) dom.requestPreview.textContent = "Load preview";
}

function openNewRunDialog() {
  if (state.config?.boxConfigured === false) {
    showNotice("Connect the Box environment before starting an agent.", true);
    openAccessDialog();
    return;
  }
  updateCapacity();
  openDialog(dom.newRunDialog);
  requestAnimationFrame(() => dom.newRepo.focus());
}

function openAccessDialog() {
  dom.controlToken.value = getControlToken();
  openDialog(dom.accessDialog);
  requestAnimationFrame(() => dom.controlToken.focus());
}

function openDialog(dialog) {
  if (typeof dialog.showModal === "function") {
    if (!dialog.open) dialog.showModal();
  } else {
    dialog.setAttribute("open", "");
  }
}

function closeDialog(dialog) {
  if (typeof dialog.close === "function") dialog.close();
  else dialog.removeAttribute("open");
}

async function saveAccess(event) {
  event.preventDefault();
  const token = dom.controlToken.value.trim();
  if (token) sessionStorage.setItem("codexstack.controlToken", token);
  else sessionStorage.removeItem("codexstack.controlToken");
  closeDialog(dom.accessDialog);
  await loadConfig();
  await pollRuns();
}

function clearAccess() {
  sessionStorage.removeItem("codexstack.controlToken");
  dom.controlToken.value = "";
  showNotice("Control access cleared for this tab.");
}

function setMobilePane(name, focus = false) {
  const proof = name === "proof";
  document.body.classList.toggle("mobile-pane-proof", proof);
  dom.mobileActivity.classList.toggle("is-active", !proof);
  dom.mobileReview.classList.toggle("is-active", proof);
  dom.mobileActivity.setAttribute("aria-pressed", String(!proof));
  dom.mobileReview.setAttribute("aria-pressed", String(proof));
  if (focus) requestAnimationFrame(() => byId(`${state.activeTab}-tab`).focus());
}

function bindDom() {
  const ids = [
    "run-groups", "rail-state", "run-search", "new-run-button", "connection-dot", "connection-label",
    "activity-heading", "selected-status", "run-meta", "run-state-detail", "header-actions", "setup-banner", "setup-access-button",
    "empty-stage", "empty-new-run", "timeline", "activity-scroll", "composer-form", "composer-input",
    "composer-context", "redirect-button", "send-button", "proof-empty", "changes-content", "request-preview",
    "preview-frame-wrap", "preview-frame", "preview-label", "open-preview", "open-desktop", "notice",
    "new-run-dialog", "new-run-form", "close-new-run", "new-repo", "new-goal", "new-base", "new-model",
    "new-effort", "new-ttl", "capacity-note", "start-run-button", "access-dialog", "access-form", "close-access",
    "control-token", "clear-access", "access-button", "mobile-back", "mobile-activity", "mobile-review"
  ];
  for (const id of ids) dom[toCamel(id)] = byId(id);
}

function toCamel(value) {
  return value.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
}

function bindEvents() {
  dom.newRunButton.addEventListener("click", openNewRunDialog);
  dom.emptyNewRun.addEventListener("click", openNewRunDialog);
  dom.closeNewRun.addEventListener("click", () => closeDialog(dom.newRunDialog));
  dom.newRunForm.addEventListener("submit", startRun);
  dom.runSearch.addEventListener("input", renderRunRail);
  dom.runSearch.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      dom.runSearch.value = "";
      renderRunRail();
    }
  });
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      dom.runSearch.focus();
    }
  });
  dom.composerInput.addEventListener("input", () => {
    if (state.selectedId) state.drafts.set(state.selectedId, dom.composerInput.value);
    updateComposerButtons();
  });
  dom.composerInput.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      sendMessage(false);
    }
  });
  dom.composerForm.addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage(false);
  });
  dom.redirectButton.addEventListener("click", () => sendMessage(true));
  dom.requestPreview.addEventListener("click", requestPreview);
  dom.openPreview.addEventListener("click", () => {
    if (state.previewUrl) openUrl(state.previewUrl);
  });
  dom.openDesktop.addEventListener("click", requestDesktop);
  for (const name of ["changes", "preview", "desktop"]) {
    byId(`${name}-tab`).addEventListener("click", () => selectTab(name));
  }
  dom.accessButton.addEventListener("click", openAccessDialog);
  dom.setupAccessButton.addEventListener("click", async () => {
    await loadConfig();
    await pollRuns();
  });
  dom.closeAccess.addEventListener("click", () => closeDialog(dom.accessDialog));
  dom.accessForm.addEventListener("submit", saveAccess);
  dom.clearAccess.addEventListener("click", clearAccess);
  dom.mobileBack.addEventListener("click", () => {
    document.body.classList.remove("detail-open");
    setMobilePane("activity");
    requestAnimationFrame(() => dom.runSearch.focus());
  });
  dom.mobileActivity.addEventListener("click", () => setMobilePane("activity"));
  dom.mobileReview.addEventListener("click", () => setMobilePane("proof"));
  window.addEventListener("online", () => setConnection(state.connected));
  window.addEventListener("offline", () => setConnection(false));
  for (const dialog of [dom.newRunDialog, dom.accessDialog]) {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) closeDialog(dialog);
    });
  }
  const tabNames = ["changes", "preview", "desktop"];
  for (const [index, name] of tabNames.entries()) {
    const tab = byId(`${name}-tab`);
    tab.addEventListener("keydown", (event) => {
      let nextIndex = null;
      if (["ArrowRight", "ArrowDown"].includes(event.key)) nextIndex = (index + 1) % tabNames.length;
      if (["ArrowLeft", "ArrowUp"].includes(event.key)) nextIndex = (index + tabNames.length - 1) % tabNames.length;
      if (event.key === "Home") nextIndex = 0;
      if (event.key === "End") nextIndex = tabNames.length - 1;
      if (nextIndex === null) return;
      event.preventDefault();
      selectTab(tabNames[nextIndex]);
      byId(`${tabNames[nextIndex]}-tab`).focus();
    });
  }
  window.addEventListener("popstate", () => {
    const target = readDeepLink();
    if (!target || !state.runs.has(target.id)) return;
    selectRun(target.id, true, false);
    selectTab(target.tab, false);
    if (window.matchMedia("(max-width: 1099px)").matches) {
      setMobilePane(target.tab === "changes" ? "activity" : "proof", true);
    }
  });
}

async function initialize() {
  bindDom();
  bindEvents();
  state.deepLink = readDeepLink();
  setConnection(false);
  renderRunRail();
  renderSelectedRun();
  await loadConfig();
  await pollRuns();
  window.setInterval(pollRuns, 4000);
  window.setInterval(() => {
    renderRunRail();
    if (currentRun()) renderSelectedRun();
  }, 30000);
}

document.addEventListener("DOMContentLoaded", initialize);
