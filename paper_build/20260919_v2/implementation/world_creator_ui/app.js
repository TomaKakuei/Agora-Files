const DRAFT_STORAGE_KEY = "agora_world_creator_current_draft";

const createForm = document.getElementById("create-form");
const reviseForm = document.getElementById("revise-form");
const resumeIdentifierInput = document.getElementById("resume-identifier");
const resumeDraftButton = document.getElementById("resume-draft");
const clearCurrentDraftButton = document.getElementById("clear-current-draft");
const reloadCurrentDraftButton = document.getElementById("reload-current-draft");
const refreshDraftButton = document.getElementById("refresh-draft");
const startArtButton = document.getElementById("start-art");
const refreshArtButton = document.getElementById("refresh-art");
const publishWorldButton = document.getElementById("publish-world");
const adoptCritiqueButton = document.getElementById("adopt-critique");
const generateFromCritiqueButton = document.getElementById("generate-from-critique");
const reviseFeedbackInput = document.getElementById("revise-feedback");
const globalStatus = document.getElementById("global-status");

const draftEmpty = document.getElementById("draft-empty");
const draftReview = document.getElementById("draft-review");
const draftStatusPill = document.getElementById("draft-status-pill");
const draftTitle = document.getElementById("draft-title");
const draftErrorBanner = document.getElementById("draft-error-banner");
const generationStatusBox = document.getElementById("generation-status-box");
const summaryCards = document.getElementById("summary-cards");
const compilerReview = document.getElementById("compiler-review");
const revisionDelta = document.getElementById("revision-delta");
const gameplayLoops = document.getElementById("gameplay-loops");
const playerEntryPoints = document.getElementById("player-entry-points");
const eventFunctions = document.getElementById("event-functions");
const validationChecklist = document.getElementById("validation-checklist");
const worldSummary = document.getElementById("world-summary");
const packageValidation = document.getElementById("package-validation");
const downloadDbLink = document.getElementById("download-db-link");
const historyList = document.getElementById("history-list");
const artStatusBox = document.getElementById("art-status-box");
const artTimeline = document.getElementById("art-timeline");
const publishStatusBox = document.getElementById("publish-status-box");
const publishActions = document.getElementById("publish-actions");
const publishAccessCode = document.getElementById("publish-access-code");
const openPublishedWorld = document.getElementById("open-published-world");
const openWorldRecord = document.getElementById("open-world-record");
const downloadPublishedDb = document.getElementById("download-published-db");
const demoFixtureDraft = window.__AGORA_CREATOR_DEMO_DRAFT__ || null;

let currentDraftId = window.localStorage.getItem(DRAFT_STORAGE_KEY) || "";
let currentDraft = null;
let artPollTimer = null;
let draftPollTimer = null;
const searchParams = new URLSearchParams(window.location.search);

function setGlobalStatus(message, isError = false) {
  globalStatus.textContent = message;
  globalStatus.style.background = isError ? "rgba(184, 77, 77, 0.96)" : "rgba(31, 46, 46, 0.94)";
  globalStatus.classList.add("visible");
  window.clearTimeout(setGlobalStatus._timer);
  setGlobalStatus._timer = window.setTimeout(() => {
    globalStatus.classList.remove("visible");
  }, 2600);
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function explainRevisionError(errorMessage = "") {
  const message = String(errorMessage || "").trim();
  const lowered = message.toLowerCase();
  if (!message) {
    return "";
  }
  if (lowered.includes("gemini api key is required")) {
    return "The creator backend does not currently have a Gemini / AI Studio API key loaded.";
  }
  if (lowered.includes("models/gemini-3.1-pro") && lowered.includes("not found")) {
    return "The requested AI Studio model alias is not available on this API endpoint. The backend is falling back and needs a supported model mapping.";
  }
  if (lowered.includes("json response was not an object")) {
    return "The model responded, but not in the strict JSON object shape the world compiler expected. This is now a compiler/output-format issue, not a missing-key issue.";
  }
  return message;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload?.detail || detail;
    } catch (_) {
      // Ignore non-JSON error responses.
    }
    throw new Error(detail);
  }
  return response.json();
}

function statusColor(status) {
  if (status === "published") {
    return "rgba(14, 124, 102, 0.16)";
  }
  if (status === "art_failed" || status === "draft_failed") {
    return "rgba(184, 77, 77, 0.16)";
  }
  if (status === "art_running" || status === "art_queued" || status === "revision_generating" || status === "draft_generating") {
    return "rgba(215, 127, 66, 0.16)";
  }
  return "rgba(14, 124, 102, 0.12)";
}

function formatListChips(values = [], tone = "neutral") {
  return (Array.isArray(values) ? values : [])
    .filter((value) => String(value || "").trim())
    .map((value) => `<span class="insight-chip ${tone}">${escapeHtml(value)}</span>`)
    .join("");
}

function critiqueTextList(values = []) {
  return (Array.isArray(values) ? values : []).map((value) => String(value || "").trim()).filter(Boolean);
}

function hasActionableCritique(critique = {}) {
  return Boolean(
    critiqueTextList(critique?.diagnosis).length
    || critiqueTextList(critique?.custom_actions).length
    || critiqueTextList(critique?.player_entry_points).length
    || critiqueTextList(critique?.conflict_hooks).length
    || critiqueTextList(critique?.social_rules).length
    || (Array.isArray(critique?.loop_reinforcements) && critique.loop_reinforcements.length)
    || (Array.isArray(critique?.room_adjustments) && critique.room_adjustments.length)
    || (Array.isArray(critique?.role_adjustments) && critique.role_adjustments.length)
    || (Array.isArray(critique?.main_character_adjustments) && critique.main_character_adjustments.length)
  );
}

function renderCritiqueListSection(title, values = []) {
  const items = critiqueTextList(values);
  if (!items.length) {
    return "";
  }
  return `
    <div class="compiler-review-section">
      <div class="compiler-review-title">${escapeHtml(title)}</div>
      <ul class="plain-list tight">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
    </div>
  `;
}

function renderCritiqueObjectSection(title, entries = [], renderItem) {
  const items = Array.isArray(entries) ? entries : [];
  if (!items.length) {
    return "";
  }
  return `
    <div class="compiler-review-section">
      <div class="compiler-review-title">${escapeHtml(title)}</div>
      <div class="compiler-review-stack">
        ${items.map((entry) => renderItem(entry)).join("")}
      </div>
    </div>
  `;
}

function renderCompilerReview(critique = {}, packageValidationPayload = {}) {
  const diagnosis = Array.isArray(critique?.diagnosis) ? critique.diagnosis : [];
  const repaired = Boolean(packageValidationPayload?.compiler_critique_applied);
  const actionable = hasActionableCritique(critique);
  const badgeClass = repaired ? "compiler-review-badge repaired" : actionable ? "compiler-review-badge pending" : "compiler-review-badge";
  const badgeLabel = repaired ? "Auto-Repaired" : actionable ? "Critique Available" : "Clean First Pass";
  const diagnosisHtml = diagnosis.length
    ? renderCritiqueListSection("Diagnosis", diagnosis)
    : '<div class="compiler-review-copy">The compiler did not report any high-priority structural issues for this revision.</div>';
  const detailSections = [
    renderCritiqueListSection("Suggested Actions", critique?.custom_actions),
    renderCritiqueListSection("Entry Point Fixes", critique?.player_entry_points),
    renderCritiqueListSection("Conflict Pressure", critique?.conflict_hooks),
    renderCritiqueListSection("Social Rules", critique?.social_rules),
    renderCritiqueObjectSection("Loop Reinforcements", critique?.loop_reinforcements, (entry) => `
      <div class="compiler-detail-card">
        <strong>${escapeHtml(entry?.label || "loop")}</strong>
        <div class="compiler-review-copy">${escapeHtml(entry?.summary || "")}</div>
        ${entry?.pressure ? `<div class="compiler-review-copy"><strong>Pressure:</strong> ${escapeHtml(entry.pressure)}</div>` : ""}
        ${Array.isArray(entry?.rooms) && entry.rooms.length ? `<div class="insight-chip-row">${formatListChips(entry.rooms, "neutral")}</div>` : ""}
      </div>
    `),
    renderCritiqueObjectSection("Room Adjustments", critique?.room_adjustments, (entry) => `
      <div class="compiler-detail-card">
        <strong>${escapeHtml(entry?.room_name || "room")}</strong>
        ${entry?.purpose_hint ? `<div class="compiler-review-copy">${escapeHtml(entry.purpose_hint)}</div>` : ""}
        ${Array.isArray(entry?.activity_tags) && entry.activity_tags.length ? `<div class="insight-chip-row">${formatListChips(entry.activity_tags, "neutral")}</div>` : ""}
      </div>
    `),
    renderCritiqueObjectSection("Role Adjustments", critique?.role_adjustments, (entry) => `
      <div class="compiler-detail-card">
        <strong>${escapeHtml(entry?.role_name || "role")}</strong>
        ${entry?.home_base ? `<div class="compiler-review-copy"><strong>Home Base:</strong> ${escapeHtml(entry.home_base)}</div>` : ""}
        ${entry?.activity_hint ? `<div class="compiler-review-copy"><strong>Activity:</strong> ${escapeHtml(entry.activity_hint)}</div>` : ""}
        ${Array.isArray(entry?.starting_items) && entry.starting_items.length ? `<div class="insight-chip-row">${formatListChips(entry.starting_items, "warm")}</div>` : ""}
      </div>
    `),
    renderCritiqueObjectSection("Main Character Adjustments", critique?.main_character_adjustments, (entry) => `
      <div class="compiler-detail-card">
        <strong>${escapeHtml(entry?.display_name || "character")}</strong>
        ${entry?.home_base ? `<div class="compiler-review-copy"><strong>Home Base:</strong> ${escapeHtml(entry.home_base)}</div>` : ""}
        ${entry?.activity_hint ? `<div class="compiler-review-copy"><strong>Activity:</strong> ${escapeHtml(entry.activity_hint)}</div>` : ""}
        ${entry?.arc_goal ? `<div class="compiler-review-copy"><strong>Arc Goal:</strong> ${escapeHtml(entry.arc_goal)}</div>` : ""}
      </div>
    `),
  ].filter(Boolean).join("");
  compilerReview.innerHTML = `
    <div class="compiler-review-head">
      <div class="compiler-review-title">Compiler Status</div>
      <div class="${badgeClass}">${escapeHtml(badgeLabel)}</div>
    </div>
    ${diagnosisHtml}
    ${detailSections}
  `;
}

function buildCritiqueRevisionRequest(critique = {}, draft = {}) {
  if (!hasActionableCritique(critique)) {
    return "";
  }
  const worldName = String(draft?.world_name || "this world").trim();
  const lines = [
    `Revise ${worldName} by applying the current compiler critique while preserving the overall setting, strongest gameplay loops, and current room count unless a critique item specifically asks for structural changes.`,
  ];
  const diagnosis = critiqueTextList(critique?.diagnosis);
  if (diagnosis.length) {
    lines.push("Address these diagnosis items:");
    for (const item of diagnosis) {
      lines.push(`- ${item}`);
    }
  }
  const customActions = critiqueTextList(critique?.custom_actions);
  if (customActions.length) {
    lines.push("Tighten the custom action set so it explicitly covers:");
    for (const item of customActions) {
      lines.push(`- ${item}`);
    }
  }
  const playerEntryPoints = critiqueTextList(critique?.player_entry_points);
  if (playerEntryPoints.length) {
    lines.push("Strengthen player entry points with these priorities:");
    for (const item of playerEntryPoints) {
      lines.push(`- ${item}`);
    }
  }
  const conflictHooks = critiqueTextList(critique?.conflict_hooks);
  if (conflictHooks.length) {
    lines.push("Sharpen ongoing conflict pressure around:");
    for (const item of conflictHooks) {
      lines.push(`- ${item}`);
    }
  }
  const socialRules = critiqueTextList(critique?.social_rules);
  if (socialRules.length) {
    lines.push("Clarify social rules such as:");
    for (const item of socialRules) {
      lines.push(`- ${item}`);
    }
  }
  for (const entry of Array.isArray(critique?.loop_reinforcements) ? critique.loop_reinforcements : []) {
    const label = String(entry?.label || "").trim();
    const summary = String(entry?.summary || "").trim();
    if (!label || !summary) {
      continue;
    }
    let line = `Reinforce the gameplay loop "${label}" by ${summary}`;
    const rooms = critiqueTextList(entry?.rooms);
    const roles = critiqueTextList(entry?.roles);
    const pressure = String(entry?.pressure || "").trim();
    if (rooms.length) {
      line += `, especially through rooms like ${rooms.join(", ")}`;
    }
    if (roles.length) {
      line += ` and roles like ${roles.join(", ")}`;
    }
    if (pressure) {
      line += `. Keep pressure on ${pressure}`;
    }
    lines.push(line.endsWith(".") ? line : `${line}.`);
  }
  for (const entry of Array.isArray(critique?.room_adjustments) ? critique.room_adjustments : []) {
    const roomName = String(entry?.room_name || "").trim();
    if (!roomName) {
      continue;
    }
    let line = `Adjust the room "${roomName}"`;
    if (entry?.purpose_hint) {
      line += ` so its purpose reads as ${String(entry.purpose_hint).trim()}`;
    }
    const tags = critiqueTextList(entry?.activity_tags);
    if (tags.length) {
      line += ` and it supports activities like ${tags.join(", ")}`;
    }
    lines.push(line.endsWith(".") ? line : `${line}.`);
  }
  for (const entry of Array.isArray(critique?.role_adjustments) ? critique.role_adjustments : []) {
    const roleName = String(entry?.role_name || "").trim();
    if (!roleName) {
      continue;
    }
    let line = `Adjust the role group "${roleName}"`;
    if (entry?.home_base) {
      line += ` so its home base is ${String(entry.home_base).trim()}`;
    }
    if (entry?.activity_hint) {
      line += ` and its activity reads as ${String(entry.activity_hint).trim()}`;
    }
    const items = critiqueTextList(entry?.starting_items);
    if (items.length) {
      line += `. Give it starting items such as ${items.join(", ")}`;
    }
    lines.push(line.endsWith(".") ? line : `${line}.`);
  }
  for (const entry of Array.isArray(critique?.main_character_adjustments) ? critique.main_character_adjustments : []) {
    const displayName = String(entry?.display_name || "").trim();
    if (!displayName) {
      continue;
    }
    let line = `Adjust the main character "${displayName}"`;
    if (entry?.home_base) {
      line += ` so they are based in ${String(entry.home_base).trim()}`;
    }
    if (entry?.activity_hint) {
      line += ` and their core activity becomes ${String(entry.activity_hint).trim()}`;
    }
    if (entry?.arc_goal) {
      line += `. Their arc goal should be ${String(entry.arc_goal).trim()}`;
    }
    lines.push(line.endsWith(".") ? line : `${line}.`);
  }
  lines.push("Keep the revision internally consistent, update event generators to match any changed loops or roles, and return a stronger compile-ready draft.");
  return lines.join("\n");
}

function previewKeySet(items = [], key) {
  const values = new Set();
  for (const item of Array.isArray(items) ? items : []) {
    if (item && typeof item === "object") {
      const value = String(item[key] || "").trim();
      if (value) {
        values.add(value);
      }
    } else {
      const value = String(item || "").trim();
      if (value) {
        values.add(value);
      }
    }
  }
  return values;
}

function sortedDiff(currentSet, previousSet) {
  return Array.from(currentSet).filter((value) => !previousSet.has(value)).sort();
}

function renderDiffChips(label, values, tone = "neutral") {
  if (!values.length) {
    return "";
  }
  return `
    <div class="history-delta">
      <div class="compiler-review-title">${escapeHtml(label)}</div>
      <div class="insight-chip-row">${formatListChips(values, tone)}</div>
    </div>
  `;
}

function computeRevisionDelta(history = [], currentRevisionId = "") {
  const entries = Array.isArray(history) ? history : [];
  const currentIndex = entries.findIndex((entry) => String(entry?.revision_id || "") === String(currentRevisionId || ""));
  if (currentIndex <= 0) {
    return { hasPrevious: false };
  }
  const current = entries[currentIndex] || {};
  const previous = entries[currentIndex - 1] || {};
  const currentPreview = current?.compiled_preview || {};
  const previousPreview = previous?.compiled_preview || {};
  return {
    hasPrevious: true,
    previousRevisionId: String(previous?.revision_id || ""),
    addedLoops: sortedDiff(previewKeySet(currentPreview?.gameplay_loops, "label"), previewKeySet(previousPreview?.gameplay_loops, "label")),
    removedLoops: sortedDiff(previewKeySet(previousPreview?.gameplay_loops, "label"), previewKeySet(currentPreview?.gameplay_loops, "label")),
    addedPlayerHooks: sortedDiff(previewKeySet(currentPreview?.player_entry_points), previewKeySet(previousPreview?.player_entry_points)),
    removedPlayerHooks: sortedDiff(previewKeySet(previousPreview?.player_entry_points), previewKeySet(currentPreview?.player_entry_points)),
    addedEventFunctions: sortedDiff(previewKeySet(currentPreview?.event_functions, "function_id"), previewKeySet(previousPreview?.event_functions, "function_id")),
    removedEventFunctions: sortedDiff(previewKeySet(previousPreview?.event_functions, "function_id"), previewKeySet(currentPreview?.event_functions, "function_id")),
    becameAutoRepaired: Boolean(current?.package_validation?.compiler_critique_applied) && !Boolean(previous?.package_validation?.compiler_critique_applied),
    becameCleanPass: !Boolean(current?.package_validation?.compiler_critique_applied) && Boolean(previous?.package_validation?.compiler_critique_applied),
  };
}

function renderRevisionDelta(history = [], currentRevisionId = "") {
  const delta = computeRevisionDelta(history, currentRevisionId);
  if (!delta.hasPrevious) {
    revisionDelta.innerHTML = '<div class="compiler-review-copy">This is the first revision, so there is no previous draft to compare against yet.</div>';
    return;
  }
  const repairNote = delta.becameAutoRepaired
    ? '<div class="compiler-review-copy"><strong>Compiler pass:</strong> this revision required auto-repair while the previous one did not.</div>'
    : delta.becameCleanPass
      ? '<div class="compiler-review-copy"><strong>Compiler pass:</strong> this revision became a clean first pass without auto-repair.</div>'
      : `<div class="compiler-review-copy"><strong>Compared against:</strong> ${escapeHtml(delta.previousRevisionId || "previous revision")}.</div>`;
  revisionDelta.innerHTML = `
    ${repairNote}
    ${renderDiffChips("Loops Added", delta.addedLoops, "neutral")}
    ${renderDiffChips("Loops Removed", delta.removedLoops, "warm")}
    ${renderDiffChips("Player Hooks Added", delta.addedPlayerHooks, "neutral")}
    ${renderDiffChips("Player Hooks Removed", delta.removedPlayerHooks, "warm")}
    ${renderDiffChips("Event Generators Added", delta.addedEventFunctions, "neutral")}
    ${renderDiffChips("Event Generators Removed", delta.removedEventFunctions, "warm")}
  `;
}

function renderGameplayLoops(preview = {}) {
  const loops = Array.isArray(preview?.gameplay_loops) ? preview.gameplay_loops : [];
  if (!loops.length) {
    gameplayLoops.innerHTML = '<div class="empty-state small">No gameplay loops compiled yet.</div>';
    return;
  }
  gameplayLoops.innerHTML = loops.map((loop) => `
    <article class="insight-card">
      <h4>${escapeHtml(loop?.label || "Loop")}</h4>
      <p>${escapeHtml(loop?.summary || "")}</p>
      <div class="insight-chip-row">${formatListChips(loop?.roles || [], "neutral")}</div>
      <div class="insight-chip-row">${formatListChips(loop?.rooms || [], "warm")}</div>
      <div class="compiler-review-copy"><strong>Pressure:</strong> ${escapeHtml(loop?.pressure || "n/a")}</div>
    </article>
  `).join("");
}

function renderPlayerEntryPoints(preview = {}) {
  const entries = Array.isArray(preview?.player_entry_points) ? preview.player_entry_points : [];
  if (!entries.length) {
    playerEntryPoints.innerHTML = '<div class="empty-state small">No player entry points compiled yet.</div>';
    return;
  }
  playerEntryPoints.innerHTML = `<ul class="plain-list">${entries.map((entry) => `<li>${escapeHtml(entry)}</li>`).join("")}</ul>`;
}

function renderEventFunctions(preview = {}) {
  const functions = Array.isArray(preview?.event_functions) ? preview.event_functions : [];
  if (!functions.length) {
    eventFunctions.innerHTML = '<div class="empty-state small">No persistent event generators compiled yet.</div>';
    return;
  }
  eventFunctions.innerHTML = functions.map((entry) => `
    <article class="insight-card">
      <h4>${escapeHtml(entry?.function_id || "event_function")}</h4>
      <p>${escapeHtml(entry?.purpose || "")}</p>
      <div class="insight-chip-row">
        <span class="insight-chip neutral">p=${escapeHtml(entry?.activation_probability ?? 0)}</span>
        <span class="insight-chip warm">max ${escapeHtml(entry?.max_events ?? 0)} / round</span>
      </div>
      <div class="compiler-review-copy"><strong>Event Policy:</strong> ${escapeHtml(entry?.event_policy || "")}</div>
      <div class="compiler-review-copy"><strong>Continuity:</strong> ${escapeHtml(entry?.continuity_policy || "")}</div>
    </article>
  `).join("");
}

function renderDraftError(status, errorMessage = "") {
  const normalized = explainRevisionError(errorMessage);
  if (status === "draft_failed" && normalized) {
    draftErrorBanner.classList.remove("hidden");
    draftErrorBanner.innerHTML = `<strong>Draft generation stopped early.</strong> ${escapeHtml(normalized)}`;
    return;
  }
  draftErrorBanner.classList.add("hidden");
  draftErrorBanner.textContent = "";
}

function renderValidationChecklist(packageValidationPayload = {}, preview = {}, status = "draft_ready", errorMessage = "") {
  const blockedByEarlyFailure = status === "draft_failed" && !Object.keys(packageValidationPayload || {}).length;
  const readableError = explainRevisionError(errorMessage) || "unknown error";
  const rows = [
    {
      state: blockedByEarlyFailure ? "fail" : packageValidationPayload?.materialize_ok ? "ok" : "fail",
      label: "Scenario materialization",
      copy: blockedByEarlyFailure
        ? `Draft generation stopped before scenario materialization began. Root cause: ${readableError}`
        : packageValidationPayload?.materialize_ok
          ? "The compiled config materialized into a scenario package."
          : "Materialization failed or did not finish cleanly.",
    },
    {
      state: blockedByEarlyFailure ? "warn" : packageValidationPayload?.pixel_read ? "ok" : "warn",
      label: "Pixel readiness",
      copy: blockedByEarlyFailure
        ? "Pixel-read was not evaluated because the draft never finished compiling."
        : packageValidationPayload?.pixel_read
          ? "This revision already satisfies the current pixel-read checks."
          : "Pixel-read is not yet satisfied. The art and QA pipeline still needs to complete.",
    },
    {
      state: blockedByEarlyFailure ? "warn" : packageValidationPayload?.compiler_critique_applied ? "warn" : "ok",
      label: "Compiler critique",
      copy: blockedByEarlyFailure
        ? "Compiler critique was not reached because the model call failed before compilation completed."
        : packageValidationPayload?.compiler_critique_applied
          ? "The compiler found issues and auto-repaired this revision before final validation."
          : "This revision passed without requiring critique-driven repair.",
    },
    {
      state: blockedByEarlyFailure ? "warn" : Array.isArray(preview?.event_functions) && preview.event_functions.length ? "ok" : "warn",
      label: "Persistent event engine",
      copy: blockedByEarlyFailure
        ? "No world-specific event generators were compiled because the world never reached the compile/materialize stage."
        : Array.isArray(preview?.event_functions) && preview.event_functions.length
          ? "World-specific event generators were compiled for sustained updates."
          : "No world-specific event generators were compiled yet.",
    },
  ];
  validationChecklist.innerHTML = rows.map((row) => `
    <div class="checklist-row ${escapeHtml(row.state)}">
      <div class="checklist-mark">${row.state === "ok" ? "✓" : row.state === "fail" ? "!" : "•"}</div>
      <div class="checklist-copy"><strong>${escapeHtml(row.label)}:</strong> ${escapeHtml(row.copy)}</div>
    </div>
  `).join("");
}

function timelineStatusTone(returncode) {
  return Number(returncode) === 0 ? "ok" : "fail";
}

function renderArtTimeline(art = {}) {
  const logs = Array.isArray(art?.logs) ? art.logs : [];
  const qaSummary = art?.qa_summary || {};
  if (!logs.length && !Object.keys(qaSummary).length) {
    artTimeline.innerHTML = '<div class="empty-state small">No art timeline yet. Start the art pipeline to populate this panel.</div>';
    return;
  }
  const commandCards = logs.map((entry, index) => {
    const command = Array.isArray(entry?.command) ? entry.command.join(" ") : String(entry?.command || "");
    const tone = timelineStatusTone(entry?.returncode);
    return `
      <article class="timeline-card">
        <div class="timeline-head">
          <div class="timeline-title">Step ${index + 1}</div>
          <span class="insight-chip ${tone === "ok" ? "neutral" : "warm"}">exit ${escapeHtml(entry?.returncode ?? "?")}</span>
        </div>
        <div class="timeline-meta">${escapeHtml(command || "command")}</div>
        ${entry?.stderr ? `<div class="compiler-review-copy"><strong>stderr:</strong> ${escapeHtml(entry.stderr)}</div>` : ""}
        ${entry?.stdout ? `<div class="compiler-review-copy"><strong>stdout:</strong> ${escapeHtml(entry.stdout)}</div>` : ""}
      </article>
    `;
  }).join("");
  const qaCard = Object.keys(qaSummary).length ? `
    <article class="timeline-card">
      <div class="timeline-head">
        <div class="timeline-title">QA Summary</div>
        <span class="insight-chip ${qaSummary?.pixel_read ? "neutral" : "warm"}">${qaSummary?.pixel_read ? "pixel read" : "needs work"}</span>
      </div>
      ${Array.isArray(qaSummary?.missing_resources) && qaSummary.missing_resources.length
        ? `<div class="compiler-review-copy"><strong>Missing:</strong> ${escapeHtml(qaSummary.missing_resources.join(", "))}</div>`
        : '<div class="compiler-review-copy">No missing resources were reported in the latest QA summary.</div>'}
    </article>
  ` : "";
  artTimeline.innerHTML = `${commandCards}${qaCard}`;
}

function renderPublishActions(publish = {}) {
  const accessCode = String(publish?.access_code || "").trim();
  if (!accessCode) {
    publishActions.classList.add("hidden");
    publishAccessCode.textContent = "-";
    openPublishedWorld.href = "#";
    openWorldRecord.href = "#";
    downloadPublishedDb.href = "#";
    return;
  }
  publishActions.classList.remove("hidden");
  publishAccessCode.textContent = accessCode;
  openPublishedWorld.href = publish?.world_url || `/pixel/?pixel_world=${encodeURIComponent(accessCode)}`;
  openWorldRecord.href = `/api/pixel/worlds/${encodeURIComponent(accessCode)}`;
  downloadPublishedDb.href = publish?.package_db_url || "#";
}

function renderSummaryCards(summary = {}) {
  const cards = [
    { label: "Rooms", value: summary.room_count ?? 0 },
    { label: "Agents", value: summary.agent_count ?? 0 },
    { label: "Main Characters", value: summary.main_character_count ?? 0 },
    { label: "Role Groups", value: summary.role_group_count ?? 0 },
    { label: "Ordinary Routes", value: summary.ordinary_route_count ?? 0 },
    { label: "Cinematic Routes", value: summary.cinematic_route_count ?? 0 },
    { label: "Custom Actions", value: summary.custom_action_count ?? 0 },
    { label: "Gameplay Loops", value: summary.gameplay_loop_count ?? 0 },
    { label: "Player Hooks", value: summary.player_entry_point_count ?? 0 },
    { label: "Item Image Mode", value: summary.item_image_mode || "n/a" },
  ];
  summaryCards.innerHTML = cards.map((card) => `
    <div class="summary-card">
      <div class="summary-card-label">${escapeHtml(card.label)}</div>
      <div class="summary-card-value">${escapeHtml(card.value)}</div>
    </div>
  `).join("");
}

function renderHistory(history = []) {
  if (!Array.isArray(history) || !history.length) {
    historyList.innerHTML = '<div class="empty-state small">No revisions yet.</div>';
    return;
  }
  const chronological = history.slice();
  historyList.innerHTML = chronological.slice().reverse().map((entry) => {
    const delta = computeRevisionDelta(chronological, entry?.revision_id || "");
    return `
    <div class="history-card">
      <h3>${escapeHtml(entry.revision_id || "revision")}</h3>
      <div class="history-meta">${escapeHtml(entry.status || "")}</div>
      <div class="history-meta">${escapeHtml(entry.world_name || "")}</div>
      <div class="history-meta">${escapeHtml(entry.created_at || "")}</div>
      <div class="history-meta">
        loops ${escapeHtml(entry?.compiled_preview?.gameplay_loops?.length ?? 0)}
        · player hooks ${escapeHtml(entry?.compiled_preview?.player_entry_points?.length ?? 0)}
        · ${entry?.package_validation?.compiler_critique_applied ? "auto-repaired" : "clean pass"}
      </div>
      ${delta.hasPrevious ? `
      <div class="history-delta">
        <div class="insight-chip-row">
          ${delta.addedLoops.length ? formatListChips(delta.addedLoops, "neutral") : ""}
          ${delta.addedEventFunctions.length ? formatListChips(delta.addedEventFunctions, "warm") : ""}
        </div>
      </div>` : ""}
    </div>
  `;}).join("");
}

function renderDraft(draft) {
  currentDraft = draft;
  currentDraftId = String(draft?.draft_id || "").trim();
  if (currentDraftId) {
    window.localStorage.setItem(DRAFT_STORAGE_KEY, currentDraftId);
  }
  if (resumeIdentifierInput) {
    resumeIdentifierInput.value = draft?.world_name || draft?.world_id || currentDraftId || "";
  }
  draftEmpty.classList.add("hidden");
  draftReview.classList.remove("hidden");

  draftStatusPill.textContent = draft.status || "unknown";
  draftStatusPill.style.background = statusColor(draft.status);
  draftTitle.textContent = `${draft.world_name || "Untitled World"} · ${draft.current_revision || ""}`;
  const revisionData = draft.current_revision_data || {};
  const packageValidationPayload = revisionData.package_validation || {};
  const compiledPreview = revisionData.compiled_preview || {};
  renderDraftError(draft.status, revisionData.error || "");
  renderSummaryCards(revisionData.structured_summary || {});
  renderCompilerReview(revisionData.compiler_critique || {}, packageValidationPayload);
  renderRevisionDelta(draft.history || [], draft.current_revision || "");
  renderGameplayLoops(compiledPreview);
  renderPlayerEntryPoints(compiledPreview);
  renderEventFunctions(compiledPreview);
  renderValidationChecklist(packageValidationPayload, compiledPreview, draft.status, revisionData.error || "");
  worldSummary.textContent = draft.world_summary_markdown || "No summary generated.";
  packageValidation.textContent = JSON.stringify(packageValidationPayload, null, 2);
  const generationPayload = draft.generation || { status: draft.status || "draft_ready" };
  generationStatusBox.textContent = JSON.stringify(generationPayload, null, 2);
  downloadDbLink.href = draft.package_download_url || "#";
  renderHistory(draft.history || []);
  const artPayload = draft.art || { status: draft.art_status || "draft_ready" };
  artStatusBox.textContent = JSON.stringify(artPayload, null, 2);
  renderArtTimeline(artPayload);
  const publishPayload = draft.publish || { status: draft.publish_status || "draft_ready" };
  publishStatusBox.textContent = JSON.stringify(publishPayload, null, 2);
  renderPublishActions(publishPayload);
  const actionableCritique = hasActionableCritique(revisionData.compiler_critique || {});
  adoptCritiqueButton.disabled = !actionableCritique;
  generateFromCritiqueButton.disabled = !actionableCritique;
}

function prefillRevisionFromCritique({ autoSubmit = false } = {}) {
  if (!currentDraft) {
    setGlobalStatus("Create or load a draft first.", true);
    return;
  }
  const revisionData = currentDraft.current_revision_data || {};
  const critique = revisionData.compiler_critique || {};
  const prompt = buildCritiqueRevisionRequest(critique, currentDraft);
  if (!prompt) {
    setGlobalStatus("This revision has no actionable compiler critique to adopt.", true);
    return;
  }
  reviseFeedbackInput.value = prompt;
  reviseFeedbackInput.focus();
  reviseFeedbackInput.setSelectionRange(reviseFeedbackInput.value.length, reviseFeedbackInput.value.length);
  if (autoSubmit) {
    reviseForm.requestSubmit();
    return;
  }
  setGlobalStatus("Compiler critique copied into the revision request. Edit it if you want, then generate the next revision.");
}

async function loadDraft(draftId = currentDraftId) {
  const normalized = String(draftId || "").trim();
  if (!normalized) {
    return;
  }
  const payload = await fetchJson(`/api/world-builder/drafts/${encodeURIComponent(normalized)}`);
  renderDraft(payload);
}

async function resolveDraft(identifier = "") {
  const normalized = String(identifier || "").trim();
  if (!normalized) {
    throw new Error("Enter a world name, world ID, or draft ID first.");
  }
  const payload = await fetchJson(`/api/world-builder/resolve?identifier=${encodeURIComponent(normalized)}`);
  renderDraft(payload.draft || {});
  maybeStartDraftPolling();
  maybeStartArtPolling();
  return payload;
}

async function refreshHistory() {
  if (!currentDraftId) {
    return;
  }
  const payload = await fetchJson(`/api/world-builder/drafts/${encodeURIComponent(currentDraftId)}/history`);
  if (currentDraft) {
    currentDraft.history = payload.history || [];
    renderHistory(currentDraft.history);
  }
}

function maybeStartArtPolling() {
  window.clearInterval(artPollTimer);
  const status = String(currentDraft?.art?.status || currentDraft?.art_status || "");
  if (!["art_queued", "art_running", "qa_failed_retrying"].includes(status) || !currentDraftId) {
    return;
  }
  artPollTimer = window.setInterval(async () => {
    try {
      const payload = await fetchJson(`/api/world-builder/drafts/${encodeURIComponent(currentDraftId)}/art/status`);
      if (currentDraft) {
        currentDraft.art = payload.art || {};
        currentDraft.art_status = currentDraft.art.status || currentDraft.art_status;
        artStatusBox.textContent = JSON.stringify(currentDraft.art, null, 2);
        renderArtTimeline(currentDraft.art);
        if (!["art_queued", "art_running", "qa_failed_retrying"].includes(String(currentDraft.art.status || ""))) {
          window.clearInterval(artPollTimer);
          await loadDraft(currentDraftId);
        }
      }
    } catch (error) {
      window.clearInterval(artPollTimer);
      setGlobalStatus(error.message || "Unable to refresh art status", true);
    }
  }, 3500);
}

function maybeStartDraftPolling() {
  window.clearInterval(draftPollTimer);
  const status = String(currentDraft?.status || "");
  if (!["draft_generating", "revision_generating"].includes(status) || !currentDraftId) {
    return;
  }
  draftPollTimer = window.setInterval(async () => {
    try {
      await loadDraft(currentDraftId);
      const nextStatus = String(currentDraft?.status || "");
      if (!["draft_generating", "revision_generating"].includes(nextStatus)) {
        window.clearInterval(draftPollTimer);
      }
    } catch (error) {
      window.clearInterval(draftPollTimer);
      setGlobalStatus(error.message || "Unable to refresh draft status", true);
    }
  }, 3500);
}

createForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(createForm);
  const payload = {
    world_name: String(formData.get("world_name") || "").trim(),
    genre: String(formData.get("genre") || "").trim(),
    player_count_target: Number(formData.get("player_count_target") || 4),
    agent_count_target: Number(formData.get("agent_count_target") || 40),
    focus: String(formData.get("focus") || "").trim(),
    seed: Number(formData.get("seed") || 42627),
    brief: String(formData.get("brief") || "").trim(),
  };
  try {
    setGlobalStatus("Generating draft world package...");
    const draft = await fetchJson("/api/world-builder/drafts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    renderDraft(draft);
    maybeStartDraftPolling();
    maybeStartArtPolling();
    setGlobalStatus("Draft queued. Generation is running in the background.");
  } catch (error) {
    setGlobalStatus(error.message || "Failed to create draft", true);
  }
});

reviseForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!currentDraftId) {
    setGlobalStatus("Create or load a draft first.", true);
    return;
  }
  const feedback = String(reviseFeedbackInput.value || "").trim();
  if (!feedback) {
    setGlobalStatus("Enter a revision request first.", true);
    return;
  }
  try {
    setGlobalStatus("Generating next revision...");
    const draft = await fetchJson(`/api/world-builder/drafts/${encodeURIComponent(currentDraftId)}/revise`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ feedback }),
    });
    renderDraft(draft);
    maybeStartDraftPolling();
    reviseFeedbackInput.value = "";
    setGlobalStatus("Revision queued. Generation is running in the background.");
  } catch (error) {
    setGlobalStatus(error.message || "Failed to revise draft", true);
  }
});

adoptCritiqueButton.addEventListener("click", () => {
  prefillRevisionFromCritique({ autoSubmit: false });
});

generateFromCritiqueButton.addEventListener("click", () => {
  prefillRevisionFromCritique({ autoSubmit: true });
});

reloadCurrentDraftButton.addEventListener("click", async () => {
  if (!currentDraftId) {
    setGlobalStatus("No current draft stored yet.", true);
    return;
  }
  try {
    await loadDraft(currentDraftId);
    maybeStartDraftPolling();
    maybeStartArtPolling();
    setGlobalStatus("Draft reloaded.");
  } catch (error) {
    setGlobalStatus(error.message || "Failed to reload draft", true);
  }
});

refreshDraftButton.addEventListener("click", async () => {
  try {
    await loadDraft(currentDraftId);
    await refreshHistory();
    maybeStartDraftPolling();
    maybeStartArtPolling();
    setGlobalStatus("Draft refreshed.");
  } catch (error) {
    setGlobalStatus(error.message || "Failed to refresh draft", true);
  }
});

resumeDraftButton.addEventListener("click", async () => {
  try {
    setGlobalStatus("Looking up world creator draft...");
    const payload = await resolveDraft(resumeIdentifierInput?.value || "");
    const matchedBy = String(payload?.matched_by || "identifier").replaceAll("_", " ");
    setGlobalStatus(`Resumed world by ${matchedBy}.`);
  } catch (error) {
    setGlobalStatus(error.message || "Failed to resume world", true);
  }
});

clearCurrentDraftButton.addEventListener("click", () => {
  window.clearInterval(artPollTimer);
  window.clearInterval(draftPollTimer);
  window.localStorage.removeItem(DRAFT_STORAGE_KEY);
  currentDraftId = "";
  currentDraft = null;
  if (resumeIdentifierInput) {
    resumeIdentifierInput.value = "";
  }
  draftReview.classList.add("hidden");
  draftEmpty.classList.remove("hidden");
  draftStatusPill.textContent = "draft_ready";
  draftTitle.textContent = "";
  generationStatusBox.textContent = "Generation worker has not started yet.";
  historyList.innerHTML = '<div class="empty-state small">No revisions yet.</div>';
  setGlobalStatus("Cleared current draft pointer.");
});

startArtButton.addEventListener("click", async () => {
  if (!currentDraftId) {
    setGlobalStatus("Create or load a draft first.", true);
    return;
  }
  try {
    setGlobalStatus("Queueing art pipeline...");
    await fetchJson(`/api/world-builder/drafts/${encodeURIComponent(currentDraftId)}/art`, {
      method: "POST",
    });
    await loadDraft(currentDraftId);
    maybeStartArtPolling();
    setGlobalStatus("Art worker queued.");
  } catch (error) {
    setGlobalStatus(error.message || "Failed to start art pipeline", true);
  }
});

refreshArtButton.addEventListener("click", async () => {
  if (!currentDraftId) {
    setGlobalStatus("Create or load a draft first.", true);
    return;
  }
  try {
    const payload = await fetchJson(`/api/world-builder/drafts/${encodeURIComponent(currentDraftId)}/art/status`);
    if (currentDraft) {
      currentDraft.art = payload.art || {};
      artStatusBox.textContent = JSON.stringify(currentDraft.art, null, 2);
      renderArtTimeline(currentDraft.art);
    }
    setGlobalStatus("Art status refreshed.");
  } catch (error) {
    setGlobalStatus(error.message || "Failed to refresh art status", true);
  }
});

publishWorldButton.addEventListener("click", async () => {
  if (!currentDraftId) {
    setGlobalStatus("Create or load a draft first.", true);
    return;
  }
  try {
    setGlobalStatus("Publishing world...");
    const draft = await fetchJson(`/api/world-builder/drafts/${encodeURIComponent(currentDraftId)}/publish`, {
      method: "POST",
    });
    renderDraft(draft);
    setGlobalStatus("World published.");
  } catch (error) {
    setGlobalStatus(error.message || "Failed to publish world", true);
  }
});

window.addEventListener("load", async () => {
  if (searchParams.get("fixture") === "demo") {
    if (demoFixtureDraft) {
      renderDraft(JSON.parse(JSON.stringify(demoFixtureDraft)));
      setGlobalStatus("Loaded demo fixture.");
      return;
    }
    setGlobalStatus("Demo fixture script was not available.", true);
  }
  if (!currentDraftId) {
    return;
  }
  try {
    await loadDraft(currentDraftId);
    maybeStartDraftPolling();
    maybeStartArtPolling();
  } catch (_) {
    window.localStorage.removeItem(DRAFT_STORAGE_KEY);
    currentDraftId = "";
  }
});
