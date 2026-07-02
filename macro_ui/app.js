const worldName = document.getElementById("world-name");
const worldDescription = document.getElementById("world-description");
const heroStats = document.getElementById("hero-stats");
const runSummary = document.getElementById("run-summary");
const roundSummary = document.getElementById("round-summary");
const macroMap = document.getElementById("macro-map");
const storyFeed = document.getElementById("story-feed");
const mediaFeed = document.getElementById("media-feed");
const featuredAgents = document.getElementById("featured-agents");
const selectedAgent = document.getElementById("selected-agent");
const selectedAgentSummary = document.getElementById("selected-agent-summary");
const selectedAgentBadge = document.getElementById("selected-agent-badge");
const worldEvents = document.getElementById("world-events");
const mapEnlarge = document.getElementById("map-enlarge");
const mapModal = document.getElementById("map-modal");
const mapModalTitle = document.getElementById("map-modal-title");
const macroMapFull = document.getElementById("macro-map-full");
const mapZoom = document.getElementById("map-zoom");
const mapFit = document.getElementById("map-fit");
const mapClose = document.getElementById("map-close");
const selectedRoom = document.getElementById("selected-room");
const selectedRoomSummary = document.getElementById("selected-room-summary");
const runList = document.getElementById("run-list");
const timelineSlider = document.getElementById("timeline-slider");
const timelineLabel = document.getElementById("timeline-label");
const timelineMeta = document.getElementById("timeline-meta");
const launchForm = document.getElementById("launch-form");
const launchStatus = document.getElementById("launch-status");
const packageStatus = document.getElementById("package-status");
const packageExport = document.getElementById("package-export");
const packagePull = document.getElementById("package-pull");
const resumeCurrentRun = document.getElementById("resume-current-run");
const assetWorkerStatus = document.getElementById("asset-worker-status");
const assetWorkerStart = document.getElementById("asset-worker-start");
const assetWorkerRefresh = document.getElementById("asset-worker-refresh");
const configSections = document.getElementById("config-sections");
const configJson = document.getElementById("config-json");
const configStatus = document.getElementById("config-status");
const configLoadTemplate = document.getElementById("config-load-template");
const configLoadCurrent = document.getElementById("config-load-current");
const configApplyJson = document.getElementById("config-apply-json");
const allAgentsCount = document.getElementById("all-agents-count");
const humanForm = document.getElementById("human-form");
const humanStatus = document.getElementById("human-status");
const humanPresenceSave = document.getElementById("human-presence-save");

let state = {
  runs: [],
  bundle: null,
  currentRunId: "",
  frameIndex: 0,
  selectedAgentId: "",
  relationshipNetwork: null,
  selectedRelationshipNetwork: null,
  configSectionOrder: [],
  assetWorker: null,
  mapZoom: 1,
  selectedRoomId: "",
};

function macroQueryParams() {
  return new URLSearchParams(window.location.search || "");
}

function formField(name) {
  return launchForm.querySelector(`[name="${name}"]`);
}

function prettyJson(value) {
  return JSON.stringify(value, null, 2);
}

function setStatus(node, message) {
  node.textContent = message || "";
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function formatMoneyMinor(amountMinor, currencySymbol = "¥") {
  const value = Number(amountMinor || 0);
  if (!Number.isFinite(value)) {
    return `${currencySymbol}0.00`;
  }
  return `${currencySymbol}${(value / 100).toFixed(2)}`;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      if (payload?.detail) {
        detail = payload.detail;
      }
    } catch (_) {
      // Ignore JSON parse failures for error bodies.
    }
    throw new Error(detail);
  }
  return response.json();
}

function parseJsonText(text, label) {
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`${label} is not valid JSON: ${error.message}`);
  }
}

function regularAgentCountFromConfig(config) {
  return ((config?.agent_generation?.role_groups || []).reduce(
    (sum, group) => sum + Number(group?.count || 0),
    0,
  ) || 0);
}

function syncFormFromConfig(config, { preserveRunId = true } = {}) {
  const scenarioMeta = config?.scenario_meta || {};
  const runtime = config?.runtime || {};
  const runner = config?.runner || {};
  const longlive = config?.longlive || {};
  const imageGeneration = config?.image_generation || {};
  formField("world_name").value = scenarioMeta.world_name || "";
  formField("world_id").value = scenarioMeta.world_id || "";
  formField("domain_label").value = runner.domain_label || "";
  formField("description").value = scenarioMeta.description || "";
  formField("regular_agent_count").value = String(Math.max(8, regularAgentCountFromConfig(config) || 40));
  formField("rounds").value = String(runtime.rounds || 25);
  formField("activation_probability").value = String(runtime.activation_probability ?? 0.3);
  formField("seed").value = String(runtime.seed || 42627);
  formField("max_videos_per_round").value = String(longlive.max_videos_per_round ?? 1);
  formField("max_images_per_round").value = String(imageGeneration.max_images_per_round ?? 1);
  formField("generate_character_portraits").checked = imageGeneration.generate_character_portraits !== false;
  formField("item_image_mode").value = imageGeneration.item_image_mode || "important_only";
  formField("artifact_image_reasoning_enabled").checked = imageGeneration.artifact_image_reasoning_enabled !== false;
  formField("artifact_reasoning_max_edge_px").value = String(imageGeneration.artifact_reasoning_max_edge_px ?? 500);
  formField("segment_seconds").value = String(longlive.segment_seconds ?? 4);
  if (!preserveRunId) {
    formField("run_id").value = `scenario_${formField("regular_agent_count").value}_agents_${formField("seed").value}`;
  }
}

function buildConfigSectionEditors(sectionOrder) {
  configSections.innerHTML = "";
  state.configSectionOrder = [...sectionOrder];
  sectionOrder.forEach((sectionKey, index) => {
    const details = document.createElement("details");
    details.className = "config-section";
    details.open = index < 2;
    details.innerHTML = `
      <summary>${sectionKey}</summary>
      <textarea rows="12" data-section-key="${sectionKey}" spellcheck="false"></textarea>
    `;
    details.querySelector("textarea").addEventListener("input", () => {
      try {
        syncFullJsonFromSections();
        setStatus(configStatus, "");
      } catch (error) {
        setStatus(configStatus, error.message);
      }
    });
    configSections.appendChild(details);
  });
}

function renderConfigEditors(config) {
  const sectionOrder = state.configSectionOrder.length ? state.configSectionOrder : Object.keys(config || {});
  if (!state.configSectionOrder.length || state.configSectionOrder.join("|") !== sectionOrder.join("|")) {
    buildConfigSectionEditors(sectionOrder);
  }
  state.configSectionOrder.forEach((sectionKey) => {
    const textarea = configSections.querySelector(`[data-section-key="${sectionKey}"]`);
    if (textarea) {
      textarea.value = prettyJson(config?.[sectionKey] ?? {});
    }
  });
  configJson.value = prettyJson(config || {});
}

function syncFullJsonFromSections() {
  const worldConfig = {};
  for (const sectionKey of state.configSectionOrder) {
    const textarea = configSections.querySelector(`[data-section-key="${sectionKey}"]`);
    worldConfig[sectionKey] = parseJsonText(textarea.value, sectionKey);
  }
  configJson.value = prettyJson(worldConfig);
  return worldConfig;
}

function currentLaunchConfig() {
  const config = syncFullJsonFromSections();
  config.scenario_meta = config.scenario_meta || {};
  config.runner = config.runner || {};
  config.runtime = config.runtime || {};
  config.longlive = config.longlive || {};
  config.image_generation = config.image_generation || {};
  config.scenario_meta.world_name = formField("world_name").value.trim();
  config.scenario_meta.world_id = formField("world_id").value.trim();
  config.scenario_meta.description = formField("description").value.trim();
  config.runner.domain_label = formField("domain_label").value.trim();
  config.runtime.rounds = Number(formField("rounds").value);
  config.runtime.activation_probability = Number(formField("activation_probability").value);
  config.runtime.seed = Number(formField("seed").value);
  config.longlive.max_videos_per_round = Number(formField("max_videos_per_round").value);
  config.longlive.segment_seconds = Number(formField("segment_seconds").value);
  config.image_generation.max_images_per_round = Number(formField("max_images_per_round").value);
  config.image_generation.generate_character_portraits = formField("generate_character_portraits").checked;
  config.image_generation.item_image_mode = formField("item_image_mode").value || "important_only";
  config.image_generation.artifact_image_reasoning_enabled = formField("artifact_image_reasoning_enabled").checked;
  config.image_generation.artifact_reasoning_max_edge_px = Number(formField("artifact_reasoning_max_edge_px").value || 500);
  configJson.value = prettyJson(config);
  return config;
}

async function loadTemplateConfig() {
  const payload = await fetchJson("/api/config/template");
  buildConfigSectionEditors(payload.section_order || Object.keys(payload.world_config || {}));
  renderConfigEditors(payload.world_config || {});
  syncFormFromConfig(payload.world_config || {}, { preserveRunId: false });
  setStatus(configStatus, `Loaded template. Help: ${payload.readme_url}`);
}

async function loadCurrentRunConfig() {
  if (!state.currentRunId) {
    setStatus(configStatus, "No current run selected yet.");
    return;
  }
  const payload = await fetchJson(`/api/runs/${encodeURIComponent(state.currentRunId)}/config`);
  buildConfigSectionEditors(Object.keys(payload.world_config || {}));
  renderConfigEditors(payload.world_config || {});
  syncFormFromConfig(payload.world_config || {});
  setStatus(configStatus, `Loaded config from ${payload.run_id}.`);
}

async function exportWorldPackage() {
  let worldConfig;
  try {
    worldConfig = currentLaunchConfig();
  } catch (error) {
    setStatus(configStatus, error.message);
    return;
  }
  setStatus(packageStatus, "Exporting DB package...");
  const response = await fetchJson("/api/packages/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      world_config: worldConfig,
      package_name: String(worldConfig?.scenario_meta?.world_name || formField("world_name")?.value || "Agora package").trim(),
      source_label: "macro_ui_start_page",
    }),
  });
  const accessCode = String(response.access_code || response.package?.access_code || "").trim();
  if (accessCode) {
    formField("package_access_code").value = accessCode;
  }
  setStatus(packageStatus, `Exported DB package${accessCode ? ` as ${accessCode}` : ""}.`);
}

async function pullWorldPackage() {
  const accessCode = String(formField("package_access_code")?.value || "").trim();
  if (!accessCode) {
    setStatus(packageStatus, "Enter a 16-character access code first.");
    return;
  }
  setStatus(packageStatus, "Pulling DB package...");
  const response = await fetchJson(`/api/packages/${encodeURIComponent(accessCode)}`);
  const config = response.world_config || {};
  buildConfigSectionEditors(Object.keys(config || {}));
  renderConfigEditors(config || {});
  syncFormFromConfig(config || {}, { preserveRunId: false });
  if (response.package?.access_code) {
    formField("package_access_code").value = String(response.package.access_code);
  }
  setStatus(packageStatus, `Pulled DB package ${accessCode}.`);
}

async function connectPackageFromQueryParams() {
  const params = macroQueryParams();
  const accessCode = String(params.get("access_code") || params.get("pixel_world") || "").trim();
  if (!accessCode) {
    return;
  }
  if (formField("package_access_code")) {
    formField("package_access_code").value = accessCode;
  }
  await pullWorldPackage();
  const seed = String(params.get("seed") || "").trim();
  if (seed && formField("seed") && !String(formField("seed").value || "").trim()) {
    formField("seed").value = seed;
  }
  setStatus(packageStatus, `Connected from Pixel world ${accessCode}.`);
}

function agentMap(bundle, frame) {
  const staticAgents = new Map((bundle?.agents || []).map((agent) => [agent.agent_id, agent]));
  const dynamicAgents = new Map((frame?.agents || []).map((agent) => [agent.agent_id, agent]));
  return { staticAgents, dynamicAgents };
}

function currentFrame() {
  return state.bundle?.frames?.[state.frameIndex] || null;
}

function crowdedRoom(room) {
  return (room.occupant_count || 0) > 6;
}

function runtimeMemory(agent) {
  return (agent && typeof agent.runtime_memory === "object" && agent.runtime_memory) || {};
}

function pressureLabel(room) {
  const band = String(room?.pressure_band || "clear");
  if (band === "compressed") {
    return "Compressed";
  }
  if (band === "crowded") {
    return "Crowded";
  }
  if (band === "busy") {
    return "Busy";
  }
  return "Clear";
}

function agentName(agentId) {
  const agent = agentById(agentId);
  return agent.display_name || agentId;
}

function agentById(agentId) {
  const frame = currentFrame();
  const { staticAgents, dynamicAgents } = agentMap(state.bundle, frame);
  return { ...(staticAgents.get(agentId) || {}), ...(dynamicAgents.get(agentId) || {}) };
}

function roomById(roomId) {
  const frame = currentFrame();
  const frameRoom = (frame?.rooms || []).find((room) => room.room_id === roomId) || {};
  const staticRoom = (state.bundle?.map?.rooms || []).find((room) => room.room_id === roomId) || {};
  return { ...staticRoom, ...frameRoom };
}

function openRoomInModal(roomId) {
  if (!roomId) {
    return;
  }
  state.selectedRoomId = roomId;
  state.mapZoom = 1;
  mapZoom.value = "1";
  mapModal.hidden = false;
  renderFullMapModal({ fitToView: false });
  if (state.bundle && currentFrame()) {
    renderRoomInspector(state.bundle, currentFrame());
  }
}

function formatCoordinates(coords) {
  if (!coords || typeof coords !== "object") {
    return "unknown";
  }
  const x = Number(coords.x ?? 0);
  const y = Number(coords.y ?? 0);
  const z = Number(coords.z ?? 0);
  return `${x}, ${y}, ${z}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#39;");
}

function selectAgent(agentId) {
  state.selectedAgentId = agentId || "";
  renderSelectedAgent();
}

function setHeroStats(bundle) {
  worldName.textContent = bundle.world.world_name;
  worldDescription.textContent = bundle.world.description;
  document.title = `${bundle.world.world_name || "Agora UI"} | Agora_UI`;
  const imageOptions = bundle.world.image_options || {};
  const statItems = [
    `Rooms ${bundle.map.rooms.length}`,
    `Agents ${bundle.agents.length}`,
    `Frames ${bundle.frames.length}`,
    `Round Target ${bundle.run.rounds_target}`,
    `Portraits ${imageOptions.generate_character_portraits === false ? "off" : "on"}`,
    `Items ${imageOptions.item_image_mode || "important_only"}`,
  ];
  heroStats.innerHTML = statItems.map((item) => `<div class="stat-pill">${item}</div>`).join("");
}

function setRunSummary(bundle, frame) {
  const runLines = [
    `Run ${bundle.run.run_id}`,
    `Status ${bundle.run.status}`,
    `Completed ${bundle.run.rounds_completed}/${bundle.run.rounds_target}`,
    `Activation ${bundle.run.activation_probability}`,
    `LongLive ${Object.entries(bundle.run.longlive_counts || {}).map(([k, v]) => `${k} ${v}`).join(" | ") || "none"}`,
  ];
  runSummary.innerHTML = runLines.map((line) => `<div>${line}</div>`).join("");
  const summary = frame?.summary || {};
  const groupCount = Array.isArray(frame?.social_groups) ? frame.social_groups.length : 0;
  const compressedRooms = (frame?.rooms || []).filter((room) => room.pressure_band === "compressed").length;
  const roundLines = [
    `Frame ${frame?.label || "Initial"}`,
    `Activated ${summary.activated_agent_count || 0}`,
    `Stories ${summary.story_event_count || 0}`,
    `Videos ${summary.video_job_count || 0}`,
    `Groups ${groupCount} | Tight Rooms ${compressedRooms}`,
    `Routes ${Object.entries(summary.routes || {}).map(([key, value]) => `${key} ${value}`).join(" | ") || "none"}`,
  ];
  roundSummary.innerHTML = roundLines.map((line) => `<div>${line}</div>`).join("");
}

function renderRunList() {
  runList.innerHTML = "";
  state.runs.forEach((run) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `run-item ${run.run_id === state.currentRunId ? "active" : ""}`;
    button.innerHTML = `
      <strong>${run.world_name}</strong>
      <span>${run.run_id}</span>
      <span>${run.status} | ${run.rounds_completed}/${run.rounds_target}</span>
    `;
    button.addEventListener("click", () => loadRun(run.run_id));
    runList.appendChild(button);
  });
}

function renderTimeline(bundle) {
  const maxIndex = Math.max(0, (bundle.frames || []).length - 1);
  timelineSlider.max = String(maxIndex);
  timelineSlider.value = String(Math.min(state.frameIndex, maxIndex));
  state.frameIndex = Number(timelineSlider.value);
  const frame = currentFrame();
  timelineLabel.textContent = frame?.label || "Initial";
  timelineMeta.textContent = `Stories ${frame?.stories?.length || 0} | Videos ${frame?.longlive_jobs?.length || 0} | Events ${frame?.extra_world_events?.length || 0} | Groups ${frame?.social_groups?.length || 0}`;
}

function mapMetrics(bundle, options = {}) {
  const mapVisual = bundle?.map?.map_visual || {};
  const bounds = bundle?.map?.bounds || {};
  const gridShape = bundle?.map?.grid_shape || { x: 1, y: 1, z: 1 };
  const minX = Number.isFinite(Number(bounds.min_x)) ? Number(bounds.min_x) : 0;
  const maxX = Number.isFinite(Number(bounds.max_x)) ? Number(bounds.max_x) : Math.max(0, Number(gridShape.x || 1) - 1);
  const minY = Number.isFinite(Number(bounds.min_y)) ? Number(bounds.min_y) : 0;
  const maxY = Number.isFinite(Number(bounds.max_y)) ? Number(bounds.max_y) : Math.max(0, Number(gridShape.y || 1) - 1);
  const spanX = Math.max(1, (maxX - minX) + 1);
  const spanY = Math.max(1, (maxY - minY) + 1);
  const requestedTileWidth = Math.max(18, Number(options.requestedTileWidth || mapVisual.tile_width || 26));
  const requestedTileHeight = Math.max(18, Number(mapVisual.tile_height || requestedTileWidth));
  const aspect = requestedTileHeight / requestedTileWidth;
  const fitToWidth = Boolean(options.fitToWidth);
  const containerWidth = Math.max(0, Number(options.containerWidth || 0));
  const minTileWidth = Math.max(16, Number(options.minTileWidth || 18));
  const maxTileWidth = Math.max(minTileWidth, Number(options.maxTileWidth || requestedTileWidth));
  const fitTileWidth = fitToWidth && containerWidth > 0
    ? Math.floor(containerWidth / (spanX + 2.2))
    : requestedTileWidth;
  const tileWidth = fitToWidth
    ? clamp(fitTileWidth, minTileWidth, maxTileWidth)
    : requestedTileWidth;
  const tileHeight = Math.max(16, Math.round(tileWidth * aspect));
  const paddingX = tileWidth;
  const paddingY = tileHeight;
  const width = (spanX * tileWidth) + (paddingX * 2);
  const height = (spanY * tileHeight) + (paddingY * 2);
  return {
    minX,
    minY,
    maxX,
    maxY,
    spanX,
    spanY,
    tileWidth,
    tileHeight,
    paddingX,
    paddingY,
    width,
    height,
  };
}

function agentCodeLabel(agent) {
  const agentId = String(agent?.agent_id || "");
  if (agent.main_character) {
    const compact = (agent.display_name || agentId || "MAIN")
      .split(/\s+/)
      .map((token) => token.slice(0, 1))
      .join("")
      .slice(0, 3)
      .toUpperCase();
    return compact ? `M-${compact}` : "MAIN";
  }
  const numeric = agentId.match(/(\d{1,3})$/)?.[1];
  return numeric ? `A-${numeric}` : (agent.display_name || agentId || "AGENT").slice(0, 8).toUpperCase();
}

function roomTiles(room) {
  if (Array.isArray(room.footprint_tiles) && room.footprint_tiles.length) {
    return room.footprint_tiles.map((tile) => ({
      x: Number(tile.x || 0),
      y: Number(tile.y || 0),
      z: Number(tile.z || 0),
    }));
  }
  const tiles = [];
  const widthTiles = Math.max(1, Number(room.width_tiles || 1));
  const heightTiles = Math.max(1, Number(room.height_tiles || 1));
  for (let dx = 0; dx < widthTiles; dx += 1) {
    for (let dy = 0; dy < heightTiles; dy += 1) {
      tiles.push({
        x: Number(room.x || 0) + dx,
        y: Number(room.y || 0) + dy,
        z: Number(room.z || 0),
      });
    }
  }
  return tiles;
}

function tilePixel(tile, metrics) {
  return {
    left: metrics.paddingX + ((Number(tile.x || 0) - metrics.minX) * metrics.tileWidth),
    top: metrics.paddingY + ((Number(tile.y || 0) - metrics.minY) * metrics.tileHeight),
  };
}

function roomBounds(room) {
  const tiles = roomTiles(room);
  const xs = tiles.map((tile) => Number(tile.x || 0));
  const ys = tiles.map((tile) => Number(tile.y || 0));
  return {
    tiles,
    minX: Math.min(...xs),
    maxX: Math.max(...xs),
    minY: Math.min(...ys),
    maxY: Math.max(...ys),
  };
}

function buildDetailedMapStage(bundle, frame, metricOptions = {}) {
  const metrics = mapMetrics(bundle, metricOptions);
  const stage = document.createElement("div");
  stage.className = "map-stage";
  stage.style.width = `${metrics.width}px`;
  stage.style.height = `${metrics.height}px`;
  stage.style.setProperty("--map-tile-width", `${metrics.tileWidth}px`);
  stage.style.setProperty("--map-tile-height", `${metrics.tileHeight}px`);
  stage.style.setProperty("--room-preview-size", `${clamp(Math.round(metrics.tileWidth * 1.7), 36, 52)}px`);
  stage.style.setProperty("--room-label-width", `${clamp(Math.round(metrics.tileWidth * 5.4), 128, 190)}px`);
  stage.style.setProperty("--room-label-max-width", `${clamp(Math.round(metrics.tileWidth * 6.6), 168, 240)}px`);

  (frame.rooms || []).forEach((room) => {
    const bounds = roomBounds(room);
    const anchor = tilePixel({ x: bounds.minX, y: bounds.minY, z: 0 }, metrics);
    const footprint = document.createElement("article");
    footprint.className = "room-footprint";
    footprint.style.left = `${anchor.left}px`;
    footprint.style.top = `${anchor.top}px`;
    footprint.style.width = `${(bounds.maxX - bounds.minX + 1) * metrics.tileWidth}px`;
    footprint.style.height = `${(bounds.maxY - bounds.minY + 1) * metrics.tileHeight}px`;

    const preview = document.createElement("button");
    preview.type = "button";
    preview.className = "room-label-card";
    preview.innerHTML = `
      ${room.image_url ? `<img class="room-preview-thumb" src="${room.image_url}" alt="${escapeHtml(room.name)}" />` : `<div class="room-preview-thumb fallback">${escapeHtml((room.name || room.room_id || "R").slice(0, 2).toUpperCase())}</div>`}
      <div class="room-label-copy">
        <strong>${escapeHtml(room.name)}</strong>
        <span>${escapeHtml(room.room_id)} | ${escapeHtml(room.visual?.biome || "room")} | ${room.occupant_count} occupants | ${pressureLabel(room)}</span>
      </div>
    `;
    preview.addEventListener("click", () => {
      state.selectedRoomId = room.room_id;
      renderRoomInspector(bundle, frame);
    });
    footprint.appendChild(preview);

    const cellLayer = document.createElement("div");
    cellLayer.className = "room-floor-layer";
    bounds.tiles.forEach((tile) => {
      const tileNode = document.createElement("div");
      tileNode.className = "room-floor-tile";
      tileNode.style.left = `${(tile.x - bounds.minX) * metrics.tileWidth}px`;
      tileNode.style.top = `${(tile.y - bounds.minY) * metrics.tileHeight}px`;
      tileNode.title = `${room.name} @ ${tile.x}, ${tile.y}, ${tile.z}`;
      cellLayer.appendChild(tileNode);
    });
    footprint.appendChild(cellLayer);

    (room.doorways || []).forEach((door) => {
      const position = door.position || door;
      const doorNode = document.createElement("div");
      doorNode.className = "door-marker";
      doorNode.style.left = `${((Number(position.x || 0) - bounds.minX) * metrics.tileWidth) + (metrics.tileWidth * 0.2)}px`;
      doorNode.style.top = `${((Number(position.y || 0) - bounds.minY) * metrics.tileHeight) + (metrics.tileHeight * 0.2)}px`;
      doorNode.title = `Door to ${door.connects_to_room_id || "nearby room"}`;
      footprint.appendChild(doorNode);
    });

    stage.appendChild(footprint);
  });
  return { stage, metrics };
}

function renderCompactMap(bundle, frame) {
  const roomOccupants = new Map((frame.rooms || []).map((room) => [room.room_id, room]));
  const grid = document.createElement("div");
  grid.className = "compact-map-grid";
  (bundle.map.rooms || []).forEach((room) => {
    const frameRoom = roomOccupants.get(room.room_id) || room;
    const card = document.createElement("article");
    card.className = `compact-room-card pressure-${frameRoom.pressure_band || "clear"}`;
    card.innerHTML = `
      <button type="button" class="compact-room-media">
        ${room.image_url ? `<img src="${room.image_url}" alt="${escapeHtml(room.name)}" />` : `<div class="room-preview-thumb fallback">${escapeHtml((room.name || room.room_id || "R").slice(0, 2).toUpperCase())}</div>`}
      </button>
      <div class="compact-room-head">
        <strong>${escapeHtml(room.name)}</strong>
        <span>${escapeHtml(room.room_id)} | ${escapeHtml(room.visual?.biome || "room")} | ${pressureLabel(frameRoom)}</span>
      </div>
      <div class="compact-room-meta">Occupants ${Number(frameRoom.occupant_count || 0)} | Capacity ${Number(frameRoom.capacity_estimate || room.capacity_estimate || 0)} | Density ${Number(frameRoom.occupancy_density || 0).toFixed(2)}</div>
    `;
    card.querySelector(".compact-room-media").addEventListener("click", () => openRoomInModal(room.room_id));
    grid.appendChild(card);
  });
  macroMap.innerHTML = "";
  macroMap.appendChild(grid);
}

function renderRoomInspector(bundle, frame) {
  if (!selectedRoom || !selectedRoomSummary) {
    return;
  }
  const roomId = state.selectedRoomId || frame?.rooms?.[0]?.room_id || bundle?.map?.rooms?.[0]?.room_id || "";
  if (!roomId) {
    selectedRoomSummary.textContent = "No room available.";
    selectedRoom.innerHTML = `<div class="empty-note">No room available.</div>`;
    return;
  }
  state.selectedRoomId = roomId;
  const room = roomById(roomId);
  const occupants = (frame?.agents || [])
    .filter((agent) => String(agent.room_id || "") === roomId)
    .map((agent) => agentById(agent.agent_id))
    .filter((agent) => agent.agent_id);
  selectedRoomSummary.textContent = `${room.name || roomId} | ${room.room_id || roomId} | ${room.occupant_count || occupants.length} occupants`;
  selectedRoom.innerHTML = `
    <article class="selected-card room-card-detail">
      <div class="selected-section">
        ${room.image_url
          ? `<img class="selected-room-image" src="${room.image_url}" alt="${escapeHtml(room.name || roomId)}" />`
          : `<div class="selected-room-image fallback">${escapeHtml((room.name || roomId).slice(0, 2).toUpperCase())}</div>`}
      </div>
      <div class="selected-section">
        <div class="summary-label">Room Snapshot</div>
        <div class="summary-body">
          <div>${escapeHtml(room.name || roomId)}</div>
          <div>${escapeHtml(room.room_id || roomId)} | ${escapeHtml(room.visual?.biome || "room")} | ${pressureLabel(room)}</div>
          <div>Occupants ${Number(room.occupant_count || occupants.length)} | Capacity ${Number(room.capacity_estimate || 0)} | Density ${Number(room.occupancy_density || 0).toFixed(2)}</div>
        </div>
      </div>
      <div class="selected-section">
        <div class="summary-label">Agents In Room</div>
        <div class="room-agent-list">
          ${occupants.length
            ? occupants.map((agent) => `
                <button type="button" class="room-agent-row" data-agent-id="${escapeHtml(agent.agent_id)}">
                  ${agent.image_url
                    ? `<img src="${agent.image_url}" alt="${escapeHtml(agent.display_name || agent.agent_id)}" />`
                    : `<div class="room-agent-fallback">${escapeHtml((agent.display_name || agent.agent_id || "A").slice(0, 2).toUpperCase())}</div>`}
                  <div>
                    <strong>${escapeHtml(agent.display_name || agent.agent_id)}</strong>
                    <div class="agent-detail-meta">${escapeHtml(agent.role_name || "Agent")} | ${escapeHtml(agentCodeLabel(agent))}</div>
                  </div>
                </button>
              `).join("")
            : `<div class="empty-note">No agents in this room for the selected frame.</div>`}
        </div>
      </div>
    </article>
  `;
  selectedRoom.querySelectorAll("[data-agent-id]").forEach((node) => {
    node.addEventListener("click", () => {
      const agentId = node.getAttribute("data-agent-id") || "";
      if (agentId) {
        selectAgent(agentId);
      }
    });
  });
}

function renderFullMapModal({ fitToView = false } = {}) {
  if (!state.bundle || !currentFrame()) {
    macroMapFull.innerHTML = "";
    return;
  }
  const viewport = document.createElement("div");
  viewport.className = "map-viewport";
  const containerWidth = Math.max(640, macroMapFull.clientWidth || 960);
  const containerHeight = Math.max(420, macroMapFull.clientHeight || 760);
  const { stage, metrics } = buildDetailedMapStage(state.bundle, currentFrame(), {
    fitToWidth: false,
    requestedTileWidth: 26,
    minTileWidth: 20,
    maxTileWidth: 28,
  });
  const fitScale = Math.min(containerWidth / metrics.width, containerHeight / metrics.height, 1);
  const effectiveScale = fitToView ? fitScale : Number(state.mapZoom || 1);
  viewport.style.width = `${Math.round(metrics.width * effectiveScale)}px`;
  viewport.style.minWidth = `${containerWidth}px`;
  viewport.style.height = `${Math.max(metrics.height * effectiveScale, 320)}px`;
  stage.style.transform = `scale(${effectiveScale})`;
  viewport.appendChild(stage);
  macroMapFull.innerHTML = "";
  macroMapFull.appendChild(viewport);
  if (fitToView) {
    macroMapFull.scrollTop = 0;
    macroMapFull.scrollLeft = 0;
    state.mapZoom = fitScale;
    mapZoom.value = String(clamp(fitScale, 0.5, 3).toFixed(2));
  }
  if (mapModalTitle) {
    mapModalTitle.textContent = `${state.bundle.world.world_name} Floor Plan`;
  }
}

function renderMap(bundle, frame) {
  renderCompactMap(bundle, frame);
  if (!mapModal.hidden) {
    renderFullMapModal();
  }
}

function renderRelationshipGraph(bundle, frame) {
  const container = document.getElementById("relationship-graph");
  const nodes = new vis.DataSet(
    (bundle.relationship_graph.nodes || []).map((node) => ({
      id: node.id,
      label: node.label,
      title: node.title,
      shape: "dot",
      size: (bundle.agents.find((agent) => agent.agent_id === node.id)?.image_url ? 26 : 16),
      color: node.group === "main"
        ? { background: "#bc5f2c", border: "#7d3e45" }
        : { background: "#6f7b58", border: "#41503a" },
      font: { face: "IBM Plex Mono", color: "#1c1b18", size: 12 },
    })),
  );
  const edges = new vis.DataSet(
    (frame.relationship_edges || []).map((edge) => ({
      from: edge.from,
      to: edge.to,
      label: edge.label,
      width: Math.max(2, Math.abs(edge.weight - 100) / 8),
      color: edge.affection >= 52 ? "#bc5f2c" : "#6f7b58",
      font: { face: "IBM Plex Mono", size: 10, strokeWidth: 0, color: "#4a4235" },
      smooth: { type: "continuous" },
    })),
  );
  if (state.relationshipNetwork) {
    state.relationshipNetwork.destroy();
  }
  state.relationshipNetwork = new vis.Network(
    container,
    { nodes, edges },
    {
      interaction: { hover: true },
      physics: { stabilization: true, barnesHut: { gravitationalConstant: -2200, springLength: 130 } },
      edges: { selectionWidth: 2 },
      nodes: { borderWidth: 1.5 },
    },
  );
  state.relationshipNetwork.on("click", (params) => {
    const nodeId = params.nodes?.[0];
    if (nodeId) {
      selectAgent(nodeId);
    }
  });
}

function renderStories(frame) {
  if (!frame.stories.length) {
    storyFeed.innerHTML = `<div class="empty-note">No story interactions in the selected frame yet.</div>`;
    return;
  }
  storyFeed.innerHTML = "";
  frame.stories.forEach((story) => {
    const card = document.createElement("article");
    card.className = "story-card";
    const relTags = (story.relationship_adjustments || [])
      .map((item) => `<span>${item.source_agent_id} -> ${item.target_agent_id} | T ${item.trust_delta >= 0 ? "+" : ""}${item.trust_delta} | A ${item.affection_delta >= 0 ? "+" : ""}${item.affection_delta}</span>`)
      .join("");
    card.innerHTML = `
      <div class="story-meta">Round ${story.round_index} | ${story.route_id} | ${story.actor_room_id}</div>
      <p><strong>${story.actor_name}</strong> ${story.story_verb} <strong>${story.target_name}</strong></p>
      <p>${story.selection_reason || "No selection note."}</p>
      <div class="relationship-tags">${relTags}</div>
    `;
    card.addEventListener("click", () => selectAgent(story.actor_id));
    storyFeed.appendChild(card);
  });
}

function renderMedia(frame) {
  const items = [];
  frame.longlive_jobs.forEach((job) => items.push({ kind: "video", payload: job }));
  frame.image_jobs.forEach((job) => items.push({ kind: "image", payload: job }));
  if (!items.length) {
    mediaFeed.innerHTML = `<div class="empty-note">No LongLive or still-image jobs were produced in the selected frame.</div>`;
    return;
  }
  mediaFeed.innerHTML = "";
  items.forEach((item) => {
    const card = document.createElement("article");
    card.className = "media-card";
    if (item.kind === "video") {
      const job = item.payload;
      card.innerHTML = `
        ${job.video_url ? `<video controls src="${job.video_url}"></video>` : ""}
        <div class="story-meta">${job.actor_id} -> ${job.target_id} | ${job.status}</div>
        <p>${job.prompt_source || "vertex_api"}</p>
      `;
    } else {
      const job = item.payload;
      card.innerHTML = `
        ${job.image_url ? `<img src="${job.image_url}" alt="${job.artifact_label || "artifact"}" />` : ""}
        <div class="story-meta">${job.route_id || "image"} | ${job.status}</div>
        <p>${job.artifact_label || job.prompt || "Image artifact"}</p>
      `;
    }
    mediaFeed.appendChild(card);
  });
}

function renderFeaturedAgents(bundle) {
  featuredAgents.innerHTML = "";
  if (allAgentsCount) {
    allAgentsCount.textContent = `${bundle.agents.length}`;
  }
  bundle.agents.forEach((agent) => {
    const card = document.createElement("article");
    card.className = "agent-card";
    card.innerHTML = `
      ${agent.image_url ? `<img src="${agent.image_url}" alt="${agent.display_name}" />` : `<div class="agent-fallback">${(agent.display_name || agent.agent_id).slice(0, 2).toUpperCase()}</div>`}
      <div>
        <div class="agent-detail-meta">${agent.role_name || "Agent"} | ${agent.room_id}</div>
        <h3>${agent.display_name}</h3>
        <p>${agent.activity_directive || agent.appearance_prompt}</p>
      </div>
    `;
    card.addEventListener("click", () => selectAgent(agent.agent_id));
    featuredAgents.appendChild(card);
  });
}

function renderWorldEvents(frame) {
  if (!frame.extra_world_events.length) {
    worldEvents.innerHTML = `<div class="empty-note">No extra world events in the selected frame.</div>`;
    return;
  }
  worldEvents.innerHTML = "";
  frame.extra_world_events.forEach((event) => {
    const card = document.createElement("article");
    card.className = "event-card";
    card.innerHTML = `
      <div class="event-meta">${event.event_type} | ${event.room_id}</div>
      <p><strong>${event.title}</strong></p>
      <p>${event.description}</p>
    `;
    worldEvents.appendChild(card);
  });
}

function renderSelectedAgent() {
  const bundle = state.bundle;
  const frame = currentFrame();
  if (!bundle || !frame) {
    selectedAgent.innerHTML = "";
    if (selectedAgentSummary) {
      selectedAgentSummary.textContent = "Click a room occupant, relationship node, or agent card.";
    }
    if (selectedAgentBadge) {
      selectedAgentBadge.textContent = "Open";
    }
    if (state.selectedRelationshipNetwork) {
      state.selectedRelationshipNetwork.destroy();
      state.selectedRelationshipNetwork = null;
    }
    return;
  }
  const agentId = state.selectedAgentId || bundle.agents[0]?.agent_id;
  if (!agentId) {
    selectedAgent.innerHTML = `<div class="empty-note">No agent available.</div>`;
    if (selectedAgentSummary) {
      selectedAgentSummary.textContent = "No agent available in this frame.";
    }
    if (selectedAgentBadge) {
      selectedAgentBadge.textContent = "Empty";
    }
    return;
  }
  const agent = agentById(agentId);
  const staticAgent = bundle.agents.find((item) => item.agent_id === agentId) || {};
  const relatedEdges = (frame.relationship_edges || []).filter((edge) => edge.from === agentId || edge.to === agentId);
  const relatedStories = (frame.stories || []).filter((story) => story.actor_id === agentId || story.target_id === agentId).slice(0, 4);
  const socialGroups = (frame.social_groups || []).filter((group) => Array.isArray(group.member_ids) && group.member_ids.includes(agentId));
  const inventory = Array.isArray(agent.inventory) ? agent.inventory : [];
  const properties = Array.isArray(agent.property_library) ? agent.property_library : [];
  const coreValues = Array.isArray(agent.core_values) ? agent.core_values : [];
  const personalityTags = Array.isArray(agent.personality_tags) ? agent.personality_tags : [];
  const statusNames = Array.isArray(agent.status_effect_names) ? agent.status_effect_names : [];
  const statusEffects = Array.isArray(agent.status_effects) ? agent.status_effects : [];
  const memory = runtimeMemory(agent);
  const longTasks = Array.isArray(memory.active_long_tasks) ? memory.active_long_tasks : [];
  const recentRounds = Array.isArray(memory.recent_rounds) ? memory.recent_rounds : [];
  const cohortIds = Array.isArray(memory.cohort_ids) ? memory.cohort_ids : [];
  const locationAwareness = (memory.location_awareness && typeof memory.location_awareness === "object") ? memory.location_awareness : {};
  const nearbyAgents = Array.isArray(locationAwareness.nearby_agents) ? locationAwareness.nearby_agents : [];
  const relatedAgents = Array.isArray(locationAwareness.related_agents) ? locationAwareness.related_agents : [];
  const currencyLabel = String(agent.currency_item_id || "currency").replaceAll("_", " ");
  const currencySymbol = String(agent.currency_symbol || agent.wallet?.currency_symbol || "¥");
  const relationshipCards = relatedEdges
    .slice()
    .sort((left, right) => Math.abs((right.weight || 0) - 100) - Math.abs((left.weight || 0) - 100))
    .map((edge) => {
    const otherId = edge.from === agentId ? edge.to : edge.from;
    const other = agentById(otherId);
    const tone = edge.affection >= 62 ? "warm" : (edge.influence_fear >= 10 ? "tense" : "steady");
    return `
      <article class="relationship-card ${tone}">
        <div class="relationship-head">
          <strong>${escapeHtml(other.display_name || otherId)}</strong>
          <span>${escapeHtml(edge.label)}</span>
        </div>
        <div class="agent-detail-meta">${escapeHtml(other.role_name || "Agent")} | ${escapeHtml(other.room_id || "no-room")}</div>
      </article>
    `;
  }).join("");
  const agentIntro = [
    agent.role_name || staticAgent.role_name || "Agent",
    personalityTags.slice(0, 3).join(", "),
    coreValues.slice(0, 2).join(", "),
  ].filter(Boolean).join(" | ");
  const statusDetailsHtml = statusEffects.length
    ? statusEffects.map((effect) => `
        <article class="status-card">
          <strong>${escapeHtml(effect.effect || "status")}</strong>
          <div class="agent-detail-meta">${Number(effect.duration_steps || 0)} rounds remaining</div>
          <p>${escapeHtml(effect.description || effect.source || "Active status effect.")}</p>
        </article>
      `).join("")
    : `<div class="empty-note">No active status effects in this frame.</div>`;
  const relationshipTags = relatedEdges.map((edge) => {
    const otherId = edge.from === agentId ? edge.to : edge.from;
    const other = agentById(otherId);
    return `<span>${escapeHtml(other.display_name || otherId)} | ${escapeHtml(edge.label)}</span>`;
  }).join("");
  const inventoryHtml = inventory.length
    ? inventory.map((item) => `
        <article class="inventory-card">
          ${item.image_url
            ? `<img class="inventory-thumb" src="${item.image_url}" alt="${escapeHtml(item.name || item.item_id)}" />`
            : `<div class="inventory-thumb empty">${escapeHtml((item.name || item.item_id || "I").slice(0, 2).toUpperCase())}</div>`}
          <div class="inventory-copy">
            <div class="inventory-topline">
              <strong>${escapeHtml(item.name || item.item_id || "Item")}</strong>
              <span>x${Number(item.quantity || 0)}</span>
            </div>
            <div class="agent-detail-meta">${escapeHtml(item.item_id || "")}${item.mass ? ` | ${Number(item.mass).toFixed(2)} wt` : ""}${item.important_artifact ? " | important artifact" : ""}</div>
            <p>${escapeHtml(item.description || "No item description.")}</p>
          </div>
        </article>
      `).join("")
    : `<div class="empty-note">No inventory items in this frame.</div>`;
  const propertyHtml = properties.length
    ? properties.map((item) => `
        <div class="property-card">
          <strong>${escapeHtml(item.asset_name || item.asset_type || "Property")}</strong>
          <div class="agent-detail-meta">${escapeHtml(item.asset_type || "asset")}</div>
          <p>${escapeHtml(item.description || item.story_use || "")}</p>
        </div>
      `).join("")
    : `<div class="empty-note">No tracked personal assets.</div>`;
  const taskHtml = longTasks.length
    ? longTasks.map((task) => `
        <article class="status-card">
          <strong>${escapeHtml(task.title || task.thread_id || "Task")}</strong>
          <div class="agent-detail-meta">${escapeHtml(task.room_id || "world")} | ${escapeHtml(task.status || "open")}</div>
          <p>${escapeHtml(task.next_step || task.description || "No next step recorded.")}</p>
        </article>
      `).join("")
    : `<div class="empty-note">No active long tasks.</div>`;
  const continuityHtml = recentRounds.length
    ? recentRounds.slice().reverse().map((entry) => `
        <div>${entry.round_index} | ${escapeHtml(entry.story_verb || "interacted with")} ${escapeHtml(entry.other_agent_name || entry.other_agent_id || "someone")} | ${escapeHtml(entry.room_id || "world")}</div>
      `).join("")
    : `<div>No recent rounds stored yet.</div>`;
  const locationHtml = nearbyAgents.length || relatedAgents.length
    ? `
        <div class="location-grid">
          <div>
            <div class="summary-label">Nearby</div>
            <div class="summary-body">
              ${nearbyAgents.length
                ? nearbyAgents.map((entry) => `<div>${escapeHtml(entry.display_name || entry.agent_id)} | ${escapeHtml(entry.room_id || "no-room")} | d${Number(entry.distance || 0)}</div>`).join("")
                : "<div>No nearby agents.</div>"}
            </div>
          </div>
          <div>
            <div class="summary-label">Related Positions</div>
            <div class="summary-body">
              ${relatedAgents.length
                ? relatedAgents.map((entry) => `<div>${escapeHtml(entry.display_name || entry.agent_id)} | ${escapeHtml(entry.room_id || "no-room")} | d${Number(entry.distance || 0)}</div>`).join("")
                : "<div>No tracked related agents.</div>"}
            </div>
          </div>
        </div>
      `
    : `<div class="empty-note">No location awareness stored for this frame.</div>`;
  const cohortHtml = cohortIds.length
    ? cohortIds.map((otherId) => `<span>${escapeHtml(agentName(otherId))}</span>`).join("")
    : `<span>No current cohort.</span>`;
  const socialGroupHtml = socialGroups.length
    ? socialGroups.map((group) => `<span>${escapeHtml(group.label || group.group_id)}</span>`).join("")
    : `<span>No frame-level cluster detected.</span>`;
  if (selectedAgentSummary) {
    selectedAgentSummary.textContent = `${agent.display_name || staticAgent.display_name || agentId} | ${agent.role_name || staticAgent.role_name || "Agent"} | ${agent.room_id || "no-room"}`;
  }
  if (selectedAgentBadge) {
    selectedAgentBadge.textContent = `${relatedEdges.length} links`;
  }
  selectedAgent.innerHTML = `
    <article class="selected-card">
      <div class="selected-hero">
        ${staticAgent.image_url
          ? `<img class="selected-avatar" src="${staticAgent.image_url}" alt="${escapeHtml(staticAgent.display_name || agentId)}" />`
          : `<div class="selected-avatar fallback">${escapeHtml((agent.display_name || staticAgent.display_name || agentId).slice(0, 2).toUpperCase())}</div>`}
        <div class="selected-hero-copy">
          <div class="selected-meta">${escapeHtml(agent.role_name || staticAgent.role_name || "Agent")} | ${escapeHtml(agent.room_id || "no-room")}</div>
          <h3>${escapeHtml(agent.display_name || staticAgent.display_name || agentId)}</h3>
          <p>${escapeHtml(agentIntro || agent.appearance_prompt || staticAgent.appearance_prompt || "No additional detail.")}</p>
          <div class="detail-grid">
            <div><span>Money</span><strong>${escapeHtml(formatMoneyMinor(agent.currency_amount || agent.wallet?.amount_minor || 0, currencySymbol))} <small>${escapeHtml(currencyLabel)}</small></strong></div>
            <div><span>Gender</span><strong>${escapeHtml(agent.gender_presentation || "unspecified")}</strong></div>
            <div><span>Home</span><strong>${escapeHtml(agent.home_room_id || "unknown")}</strong></div>
            <div><span>Coords</span><strong>${escapeHtml(formatCoordinates(agent.coordinates))}</strong></div>
          </div>
        </div>
      </div>
      <div class="status-row">
        ${statusNames.length ? statusNames.map((status) => `<span>${escapeHtml(status)}</span>`).join("") : `<span>stable</span>`}
      </div>
      <div class="tag-group">
        ${coreValues.length ? coreValues.map((value) => `<span>${escapeHtml(value)}</span>`).join("") : ""}
        ${personalityTags.length ? personalityTags.map((value) => `<span>${escapeHtml(value)}</span>`).join("") : ""}
      </div>
      <div class="selected-section">
        <div class="summary-label">Character Snapshot</div>
        <div class="summary-body">
          <div>${escapeHtml(agent.appearance_prompt || staticAgent.appearance_prompt || "No appearance prompt available.")}</div>
          <div>${escapeHtml(agent.activity_directive || "No activity directive.")}</div>
          <div>${escapeHtml(agent.private_notes || "No private notes.")}</div>
        </div>
      </div>
      <div class="selected-section">
        <div class="summary-label">Continuity Focus</div>
        <div class="summary-body">
          <div>${escapeHtml(memory.current_focus || "No current focus recorded.")}</div>
          <div>${escapeHtml(memory.mainline_summary || "No mainline summary recorded.")}</div>
        </div>
      </div>
      <div class="selected-section">
        <div class="summary-label">Highlighted Relationships</div>
        <div class="relationship-card-grid">${relationshipCards || `<div class="empty-note">No non-neutral links in this frame.</div>`}</div>
      </div>
      <div class="selected-section">
        <div class="summary-label">Relationship Web</div>
        <div class="relationship-tags">${relationshipTags || `<span>No non-neutral links in this frame.</span>`}</div>
        <div id="selected-relationship-map" class="graph-canvas mini-graph"></div>
      </div>
      <div class="selected-section">
        <div class="summary-label">Cohort</div>
        <div class="relationship-tags">${cohortHtml}</div>
        <div class="relationship-tags">${socialGroupHtml}</div>
      </div>
      <div class="selected-section">
        <div class="summary-label">Status</div>
        <div class="status-card-grid">${statusDetailsHtml}</div>
      </div>
      <div class="selected-section">
        <div class="summary-label">Long Tasks</div>
        <div class="status-card-grid">${taskHtml}</div>
      </div>
      <div class="selected-section">
        <div class="summary-label">Inventory</div>
        <div class="inventory-grid">
          ${inventoryHtml}
        </div>
      </div>
      <div class="selected-section">
        <div class="summary-label">Personal Assets</div>
        <div class="property-grid">
          ${propertyHtml}
        </div>
      </div>
      <div class="selected-section">
        <div class="summary-label">Recent Interaction</div>
        <div class="summary-body">
        ${relatedStories.length
          ? relatedStories.map((story) => `<div>${escapeHtml(story.actor_name)} ${escapeHtml(story.story_verb)} ${escapeHtml(story.target_name)}</div>`).join("")
          : "<div>No story interactions in the selected frame.</div>"}
        </div>
      </div>
      <div class="selected-section">
        <div class="summary-label">Recent Ten Rounds</div>
        <div class="summary-body">${continuityHtml}</div>
      </div>
      <div class="selected-section">
        <div class="summary-label">Location Awareness</div>
        ${locationHtml}
      </div>
    </article>
  `;
  renderSelectedRelationshipMap(agentId, relatedEdges);
}

function suggestResumeRunId() {
  const resumeField = formField("resume_run_id");
  const runIdField = formField("run_id");
  if (resumeField) {
    resumeField.value = state.currentRunId || "";
  }
  if (runIdField && (!runIdField.value || runIdField.value.startsWith("scenario_"))) {
    runIdField.value = state.currentRunId ? `${state.currentRunId}_resume` : runIdField.value;
  }
}

function renderSelectedRelationshipMap(agentId, relatedEdges) {
  const container = document.getElementById("selected-relationship-map");
  if (state.selectedRelationshipNetwork) {
    state.selectedRelationshipNetwork.destroy();
    state.selectedRelationshipNetwork = null;
  }
  if (!container) {
    return;
  }
  if (!relatedEdges.length) {
    container.innerHTML = `<div class="empty-note">No relationship map for this frame yet.</div>`;
    return;
  }
  const nodeIds = new Set([agentId]);
  relatedEdges.forEach((edge) => {
    nodeIds.add(edge.from);
    nodeIds.add(edge.to);
  });
  const nodes = new vis.DataSet(
    [...nodeIds].map((nodeId) => {
      const agent = agentById(nodeId);
      return {
        id: nodeId,
        label: agent.display_name || nodeId,
        shape: "dot",
        size: nodeId === agentId ? 28 : 18,
        color: nodeId === agentId
          ? { background: "#bc5f2c", border: "#7d3e45" }
          : { background: "#6f7b58", border: "#41503a" },
        font: { face: "IBM Plex Mono", color: "#1c1b18", size: 11 },
      };
    }),
  );
  const edges = new vis.DataSet(
    relatedEdges.map((edge) => ({
      from: edge.from,
      to: edge.to,
      label: edge.label,
      width: Math.max(2, Math.abs(edge.weight - 100) / 10),
      color: edge.affection >= 52 ? "#bc5f2c" : "#6f7b58",
      font: { face: "IBM Plex Mono", size: 9, strokeWidth: 0, color: "#4a4235" },
      smooth: { type: "continuous" },
    })),
  );
  container.innerHTML = "";
  state.selectedRelationshipNetwork = new vis.Network(
    container,
    { nodes, edges },
    {
      interaction: { hover: true },
      physics: { stabilization: true, barnesHut: { gravitationalConstant: -900, springLength: 110 } },
      edges: { selectionWidth: 2 },
      nodes: { borderWidth: 1.5 },
    },
  );
  state.selectedRelationshipNetwork.on("click", (params) => {
    const nodeId = params.nodes?.[0];
    if (nodeId) {
      selectAgent(nodeId);
    }
  });
}

function renderBundle() {
  const bundle = state.bundle;
  const frame = currentFrame();
  if (!bundle || !frame) {
    return;
  }
  setHeroStats(bundle);
  setRunSummary(bundle, frame);
  renderTimeline(bundle);
  renderMap(bundle, frame);
  renderRoomInspector(bundle, frame);
  renderRelationshipGraph(bundle, frame);
  renderStories(frame);
  renderMedia(frame);
  renderFeaturedAgents(bundle);
  renderWorldEvents(frame);
  renderSelectedAgent();
}

function renderAssetWorkerStatus() {
  const worker = state.assetWorker;
  if (!worker) {
    assetWorkerStatus.innerHTML = "<div>No asset worker status yet.</div>";
    return;
  }
  assetWorkerStatus.innerHTML = [
    `Status ${worker.status}`,
    `Rooms ${worker.room_images}/${worker.expected_room_images}`,
    `Agents ${worker.agent_images}/${worker.expected_agent_images}`,
    `Items ${worker.item_images || 0}/${worker.expected_item_images || 0}`,
    worker.stdout_path ? `Log ${worker.stdout_path}` : "",
    worker.launcher_stderr ? `Launcher ${worker.launcher_stderr}` : "",
  ].filter(Boolean).map((line) => `<div>${line}</div>`).join("");
}

async function refreshAssetWorkerStatusForRun(runId) {
  if (!runId) {
    return;
  }
  const payload = await fetchJson(`/api/runs/${encodeURIComponent(runId)}/assets/status`);
  state.assetWorker = payload.asset_worker || null;
  renderAssetWorkerStatus();
}

async function loadRun(runId, { forceRefreshImages = false } = {}) {
  state.currentRunId = runId;
  const bundle = await fetchJson(`/api/runs/${encodeURIComponent(runId)}/bundle?force_refresh_images=${forceRefreshImages ? "true" : "false"}`);
  state.bundle = bundle;
  if (state.frameIndex >= bundle.frames.length) {
    state.frameIndex = Math.max(0, bundle.frames.length - 1);
  }
  if (!state.selectedAgentId) {
    state.selectedAgentId = bundle.agents[0]?.agent_id || "";
  }
  const hasSelectedRoom = bundle.map.rooms?.some((room) => room.room_id === state.selectedRoomId);
  if (!state.selectedRoomId || !hasSelectedRoom) {
    state.selectedRoomId = bundle.frames?.[state.frameIndex]?.rooms?.[0]?.room_id || bundle.map.rooms?.[0]?.room_id || "";
  }
  renderRunList();
  renderBundle();
  await refreshAssetWorkerStatusForRun(runId);
}

async function refreshRunsAndAutoBind() {
  const [{ runs }, currentPayload] = await Promise.all([fetchJson("/api/runs"), fetchJson("/api/runs/current")]);
  state.runs = runs || [];
  const currentRun = currentPayload.current_run || state.runs[0];
  if (!currentRun) {
    runList.innerHTML = `<div class="empty-note">No runs found yet.</div>`;
    return;
  }
  const shouldReload = !state.currentRunId || currentRun.run_id === state.currentRunId || !state.runs.find((run) => run.run_id === state.currentRunId);
  renderRunList();
  if (shouldReload) {
    await loadRun(currentRun.run_id);
  }
}

async function startAssetWorkerForCurrentRun(forceRefreshImages = false) {
  if (!state.currentRunId) {
    setStatus(launchStatus, "Select or launch a run first.");
    return;
  }
  assetWorkerStatus.innerHTML = "<div>Starting asset worker...</div>";
  await fetchJson(`/api/runs/${encodeURIComponent(state.currentRunId)}/assets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ force_refresh_images: forceRefreshImages }),
  });
  await refreshAssetWorkerStatusForRun(state.currentRunId);
}

function humanField(name) {
  return humanForm?.querySelector(`[name="${name}"]`);
}

async function saveHumanPresence() {
  if (!state.currentRunId) {
    setStatus(humanStatus, "Select a live run first.");
    return;
  }
  const payload = {
    display_name: String(humanField("display_name")?.value || "Human Interactor").trim(),
    room_id: String(humanField("room_id")?.value || "").trim(),
    speed_seconds_per_round: Number(humanField("speed_seconds_per_round")?.value || 8),
  };
  await fetchJson(`/api/runs/${encodeURIComponent(state.currentRunId)}/human/presence`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  setStatus(humanStatus, `Saved human presence for ${state.currentRunId}.`);
}

timelineSlider.addEventListener("input", () => {
  state.frameIndex = Number(timelineSlider.value);
  renderBundle();
});

assetWorkerStart.addEventListener("click", async () => {
  try {
    await startAssetWorkerForCurrentRun(false);
  } catch (error) {
    assetWorkerStatus.innerHTML = `<div>${error.message}</div>`;
  }
});

assetWorkerRefresh.addEventListener("click", async () => {
  try {
    await refreshAssetWorkerStatusForRun(state.currentRunId);
  } catch (error) {
    assetWorkerStatus.innerHTML = `<div>${error.message}</div>`;
  }
});

if (humanPresenceSave) {
  humanPresenceSave.addEventListener("click", async () => {
    try {
      await saveHumanPresence();
    } catch (error) {
      setStatus(humanStatus, error.message);
    }
  });
}

mapEnlarge.addEventListener("click", () => {
  state.selectedRoomId = state.selectedRoomId || currentFrame()?.rooms?.[0]?.room_id || "";
  openRoomInModal(state.selectedRoomId || currentFrame()?.rooms?.[0]?.room_id || "");
});

mapClose.addEventListener("click", () => {
  mapModal.hidden = true;
});

mapFit.addEventListener("click", () => {
  renderFullMapModal({ fitToView: true });
});

mapZoom.addEventListener("input", () => {
  state.mapZoom = Number(mapZoom.value || 1);
  renderFullMapModal();
});

mapModal.addEventListener("click", (event) => {
  if (event.target === mapModal) {
    mapModal.hidden = true;
  }
});

window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !mapModal.hidden) {
    mapModal.hidden = true;
  }
});

window.addEventListener("resize", () => {
  if (state.bundle) {
    renderBundle();
  }
});

configLoadTemplate.addEventListener("click", async () => {
  try {
    await loadTemplateConfig();
  } catch (error) {
    setStatus(configStatus, error.message);
  }
});

configLoadCurrent.addEventListener("click", async () => {
  try {
    await loadCurrentRunConfig();
  } catch (error) {
    setStatus(configStatus, error.message);
  }
});

if (packageExport) {
  packageExport.addEventListener("click", async () => {
    try {
      await exportWorldPackage();
    } catch (error) {
      setStatus(packageStatus, error.message);
    }
  });
}

if (packagePull) {
  packagePull.addEventListener("click", async () => {
    try {
      await pullWorldPackage();
    } catch (error) {
      setStatus(packageStatus, error.message);
    }
  });
}

configApplyJson.addEventListener("click", () => {
  try {
    const parsed = parseJsonText(configJson.value, "Full world config");
    buildConfigSectionEditors(Object.keys(parsed || {}));
    renderConfigEditors(parsed || {});
    syncFormFromConfig(parsed || {});
    setStatus(configStatus, "Applied full JSON into section editors.");
  } catch (error) {
    setStatus(configStatus, error.message);
  }
});

launchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  let worldConfig;
  try {
    worldConfig = currentLaunchConfig();
  } catch (error) {
    setStatus(configStatus, error.message);
    return;
  }
  const form = new FormData(launchForm);
  const payload = {
    run_id: String(form.get("run_id") || "").trim(),
    resume_run_id: String(form.get("resume_run_id") || "").trim(),
    package_access_code: String(form.get("package_access_code") || "").trim(),
    world_name: String(form.get("world_name") || "").trim(),
    world_id: String(form.get("world_id") || "").trim(),
    domain_label: String(form.get("domain_label") || "").trim(),
    description: String(form.get("description") || "").trim(),
    regular_agent_count: Number(form.get("regular_agent_count")),
    rounds: Number(form.get("rounds")),
    activation_probability: Number(form.get("activation_probability")),
    seed: Number(form.get("seed")),
    max_videos_per_round: Number(form.get("max_videos_per_round")),
    max_images_per_round: Number(form.get("max_images_per_round")),
    segment_seconds: Number(form.get("segment_seconds")),
    main_characters_always_activate: form.get("main_characters_always_activate") === "on",
    start_asset_worker: form.get("start_asset_worker") === "on",
    world_config: worldConfig,
  };
  launchStatus.textContent = "Launching run...";
  try {
    const response = await fetchJson("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    launchStatus.textContent = `Launched ${response.run_id}`;
    await refreshRunsAndAutoBind();
    await loadRun(response.run_id);
  } catch (error) {
    launchStatus.textContent = `Launch failed: ${error.message}`;
  }
});

if (resumeCurrentRun) {
  resumeCurrentRun.addEventListener("click", () => {
    if (!state.currentRunId) {
      launchStatus.textContent = "Select a run first.";
      return;
    }
    suggestResumeRunId();
    launchStatus.textContent = `Resume source set to ${state.currentRunId}.`;
  });
}

if (humanForm) {
  humanForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.currentRunId) {
      setStatus(humanStatus, "Select a live run first.");
      return;
    }
    const payload = {
      display_name: String(humanField("display_name")?.value || "Human Interactor").trim(),
      room_id: String(humanField("room_id")?.value || "").trim(),
      target_agent_id: String(humanField("target_agent_id")?.value || "").trim(),
      action_text: String(humanField("action_text")?.value || "").trim(),
      speed_seconds_per_round: Number(humanField("speed_seconds_per_round")?.value || 8),
    };
    if (!payload.action_text) {
      setStatus(humanStatus, "Write an action before queueing.");
      return;
    }
    try {
      await fetchJson(`/api/runs/${encodeURIComponent(state.currentRunId)}/human/actions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setStatus(humanStatus, `Queued human action into ${state.currentRunId}.`);
      humanField("action_text").value = "";
    } catch (error) {
      setStatus(humanStatus, error.message);
    }
  });
}

setInterval(async () => {
  try {
    await refreshRunsAndAutoBind();
    if (state.currentRunId) {
      await refreshAssetWorkerStatusForRun(state.currentRunId);
    }
    const workerActive = state.assetWorker && ["running", "launched", "partial"].includes(state.assetWorker.status);
    if ((state.bundle?.run?.status === "running" || workerActive) && state.currentRunId) {
      await loadRun(state.currentRunId);
    }
  } catch (error) {
    console.error(error);
  }
}, 15000);

await loadTemplateConfig();
try {
  await connectPackageFromQueryParams();
} catch (error) {
  setStatus(packageStatus, `Pixel handoff failed: ${error.message}`);
}
await refreshRunsAndAutoBind();
