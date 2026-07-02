

export const Phaser = window.Phaser;
export const DEFAULT_WORLD_CONFIG_PATH = "../sample_json/world_config.json";
export const DEFAULT_MAP_GRID_PATH = "../sample_json/scenario/map_grid.json";
export const DEFAULT_BOOTSTRAP_PATH = "./bootstrap_agents.json";
export const DEFAULT_RUNTIME_POINTER_PATH = "../output/replay_runs/latest_frontend_state.json";

export const ROOM_COLORS = {
  warm_lantern: 0x7b5133,
  gold_paper: 0x8e6a35,
  amber_tavern: 0x724833,
  dusty_brown: 0x5e4a3a,
  ember_orange: 0x7a3f26,
  soft_mint: 0x42645e,
  clear_day: 0x54694f,
  violet_arcane: 0x5c4479,
  focused_blue: 0x445d79,
  low_lantern: 0x53483c,
};

export function colorForRoom(room) {
  const key = room.visual?.ambient_palette;
  return ROOM_COLORS[key] || 0x4c4657;
}

export function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

export function firstNonEmpty(...values) {
  return values.find((value) => typeof value === "string" && value.trim()) || "";
}

export function parseJsonObject(value) {
  if (!value) {
    return {};
  }
  if (typeof value === "object" && !Array.isArray(value)) {
    return value;
  }
  try {
    const parsed = JSON.parse(String(value));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch (_error) {
    return {};
  }
}

export function liveEventPayload(event) {
  return parseJsonObject(event?.payload_json);
}

export function newClientActionId() {
  return `live_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
}

export function tileKey(x, y, z = 0) {
  return `${x},${y},${z}`;
}

export function formatTemplate(template, values) {
  return String(template || "").replace(/\{(\w+)\}/g, (_match, key) => {
    const value = values[key];
    return value === undefined || value === null || value === "" ? "unknown" : String(value);
  });
}

export function normalizeImageCard(card, fallback = {}) {
  const label = firstNonEmpty(card?.label, card?.artifact_label, card?.name, fallback.label, "Untitled image");
  const itemId = firstNonEmpty(card?.item_id, fallback.itemId, "");
  const imageUrl = firstNonEmpty(card?.image_url, card?.image_path, fallback.imageUrl, "");
  const sourcePath = firstNonEmpty(card?.source_path, card?.image_path, fallback.sourcePath, "");
  const description = firstNonEmpty(card?.description, fallback.description, "");
  const reasoningImageUrl = firstNonEmpty(card?.reasoning_image_url, card?.reasoning_image_path, "");
  return {
    label,
    item_id: itemId,
    image_url: imageUrl,
    source_path: sourcePath,
    description,
    reasoning_image_url: reasoningImageUrl,
  };
}

export function extractObjectImages(agent) {
  if (safeArray(agent.object_images).length) {
    return safeArray(agent.object_images)
      .map((card) => normalizeImageCard(card))
      .filter((card) => card.image_url);
  }
  return safeArray(agent.inventory)
    .filter((item) => firstNonEmpty(item?.image_url, item?.image_path))
    .map((item) => normalizeImageCard(item, {
      label: firstNonEmpty(item?.metadata?.name, item?.description, item?.item_id, "Inventory item"),
      itemId: item?.item_id || "",
      imageUrl: firstNonEmpty(item?.image_url, item?.image_path),
      sourcePath: item?.image_path || "",
      description: item?.description || "",
    }));
}

export function extractArtifactImages(agent) {
  if (safeArray(agent.artifact_images).length) {
    return safeArray(agent.artifact_images)
      .map((card) => normalizeImageCard(card))
      .filter((card) => card.image_url);
  }
  const runtimeMemory = agent.public_state?.runtime_memory || {};
  return safeArray(runtimeMemory.visual_artifacts)
    .filter((artifact) => firstNonEmpty(artifact?.image_url, artifact?.image_path))
    .map((artifact) => normalizeImageCard(artifact, {
      label: firstNonEmpty(artifact?.artifact_label, artifact?.item_id, "Artifact"),
      itemId: artifact?.item_id || "",
      imageUrl: firstNonEmpty(artifact?.image_url, artifact?.image_path),
      sourcePath: artifact?.image_path || "",
    }));
}

export function normalizeInventoryEntries(entries) {
  return safeArray(entries)
    .filter((entry) => entry && typeof entry === "object")
    .map((entry) => ({
      item_id: firstNonEmpty(entry?.item_id, ""),
      quantity: Math.max(0, Number(entry?.quantity || 0)),
      name: firstNonEmpty(entry?.name, entry?.metadata?.name, entry?.item_id, "Item"),
      description: firstNonEmpty(entry?.description, entry?.metadata?.description, ""),
      image_url: firstNonEmpty(entry?.image_url, entry?.image_path, ""),
      image_path: firstNonEmpty(entry?.image_path, ""),
      metadata: entry?.metadata && typeof entry.metadata === "object" ? entry.metadata : {},
    }))
    .filter((entry) => entry.item_id);
}

export function normalizeTradeOffer(offer) {
  return {
    offer_id: firstNonEmpty(offer?.offer_id, ""),
    seller_agent_id: firstNonEmpty(offer?.seller_agent_id, ""),
    buyer_agent_id: firstNonEmpty(offer?.buyer_agent_id, ""),
    item_id: firstNonEmpty(offer?.item_id, ""),
    item_name: firstNonEmpty(offer?.item_name, offer?.item_id, "Item"),
    quantity: Math.max(1, Number(offer?.quantity || 1)),
    unit_price: Math.max(0, Number(offer?.unit_price || 0)),
    total_price: Math.max(0, Number(offer?.total_price || 0)),
    currency_item_id: firstNonEmpty(offer?.currency_item_id, "gold"),
    status: firstNonEmpty(offer?.status, "quoted"),
    quote_text: firstNonEmpty(offer?.quote_text, ""),
    response_text: firstNonEmpty(offer?.response_text, ""),
    note: firstNonEmpty(offer?.note, ""),
    created_at: firstNonEmpty(offer?.created_at, ""),
    completed_at: firstNonEmpty(offer?.completed_at, ""),
  };
}

export function normalizeActiveTask(task) {
  if (!task || typeof task !== "object") {
    return null;
  }
  const taskId = firstNonEmpty(task?.task_id, "");
  const kind = firstNonEmpty(task?.kind, "");
  if (!taskId || !kind) {
    return null;
  }
  return {
    task_id: taskId,
    kind,
    status: firstNonEmpty(task?.status, "active"),
    requested_by_agent_id: firstNonEmpty(task?.requested_by_agent_id, ""),
    target_agent_id: firstNonEmpty(task?.target_agent_id, ""),
    target_room_id: firstNonEmpty(task?.target_room_id, ""),
    target_coordinates: task?.target_coordinates && typeof task.target_coordinates === "object" ? task.target_coordinates : null,
    offer_id: firstNonEmpty(task?.offer_id, ""),
    item_id: firstNonEmpty(task?.item_id, ""),
    quantity: Math.max(1, Number(task?.quantity || 1)),
    note: firstNonEmpty(task?.note, ""),
  };
}

export function normalizeAvailableRoute(route) {
  if (!route || typeof route !== "object") {
    return null;
  }
  const routeId = firstNonEmpty(route?.route_id, "");
  const kind = firstNonEmpty(route?.kind, "");
  if (!routeId || !kind) {
    return null;
  }
  return {
    route_id: routeId,
    kind,
    action: firstNonEmpty(route?.action, ""),
    status_effect: firstNonEmpty(route?.status_effect, ""),
    duration_steps: Math.max(1, Number(route?.duration_steps || 1)),
    weight: Math.max(0, Number(route?.weight || 0)),
    story_verb: firstNonEmpty(route?.story_verb, ""),
    selection_guidance: firstNonEmpty(route?.selection_guidance, ""),
  };
}

export function normalizeAgentRecord(agent) {
  const publicState = agent.public_state || {};
  const runtimeMemory = publicState.runtime_memory || {};
  return {
    agent_id: agent.agent_id,
    display_name: firstNonEmpty(agent.display_name, agent.agent_id, "Unknown Agent"),
    room_id: firstNonEmpty(agent.room_id, publicState.home_room_id, "unknown"),
    coordinates: agent.coordinates || {},
    main_character: Boolean(agent.main_character ?? publicState.main_character),
    role_name: firstNonEmpty(agent.role_name, publicState.role_name, "Agent"),
    activity_directive: firstNonEmpty(agent.activity_directive, publicState.activity_directive, ""),
    appearance_prompt: firstNonEmpty(agent.appearance_prompt, ""),
    current_focus: firstNonEmpty(agent.current_focus, runtimeMemory.current_focus, ""),
    mainline_summary: firstNonEmpty(agent.mainline_summary, runtimeMemory.mainline_summary, ""),
    inventory: normalizeInventoryEntries(agent.inventory),
    currency_quantity: Math.max(0, Number(agent.currency_quantity || 0)),
    currency_item_id: firstNonEmpty(agent.currency_item_id, "gold"),
    item_prices: agent?.item_prices && typeof agent.item_prices === "object" ? agent.item_prices : (publicState.item_prices || {}),
    pending_trade_offers: safeArray(agent.pending_trade_offers).map((offer) => normalizeTradeOffer(offer)).filter((offer) => offer.offer_id),
    active_task: normalizeActiveTask(agent.active_task),
    recent_dialogue: safeArray(agent.recent_dialogue).map((entry) => String(entry || "")).filter(Boolean).slice(-6),
    live_motion_mode: firstNonEmpty(agent.live_motion_mode, ""),
    live_room_active: Boolean(agent.live_room_active),
    claimed_by_session_id: firstNonEmpty(agent.claimed_by_session_id, ""),
    control_mode: firstNonEmpty(agent.control_mode, ""),
    facing: firstNonEmpty(agent.facing, "down"),
    animation: firstNonEmpty(agent.animation, ""),
    last_input_seq: Math.max(0, Number(agent.last_input_seq || 0)),
    room_name: firstNonEmpty(agent.room_name, ""),
    live_ready: agent?.live_ready !== false,
    portrait_image_url: firstNonEmpty(agent.portrait_image_url, agent.image_url, ""),
    portrait_image_path: firstNonEmpty(agent.portrait_image_path, agent.image_path, ""),
    object_images: extractObjectImages(agent),
    artifact_images: extractArtifactImages(agent),
  };
}

export function cloneAgentRecord(agent) {
  if (!agent || typeof agent !== "object") {
    return agent;
  }
  return {
    ...agent,
    coordinates: agent.coordinates && typeof agent.coordinates === "object"
      ? { ...agent.coordinates }
      : {},
    inventory: safeArray(agent.inventory).map((entry) => ({ ...entry })),
    pending_trade_offers: safeArray(agent.pending_trade_offers).map((offer) => ({ ...offer })),
    recent_dialogue: safeArray(agent.recent_dialogue),
    object_images: safeArray(agent.object_images).map((card) => ({ ...card })),
    artifact_images: safeArray(agent.artifact_images).map((card) => ({ ...card })),
    facing: firstNonEmpty(agent.facing, "down"),
    animation: firstNonEmpty(agent.animation, ""),
    last_input_seq: Math.max(0, Number(agent.last_input_seq || 0)),
  };
}

export function resolveWebSocketUrl(value) {
  const text = firstNonEmpty(value, "");
  if (!text) {
    return "";
  }
  try {
    const resolved = new URL(text, window.location.href);
    const pageProtocol = String(window.location.protocol || "").toLowerCase();
    const socketProtocol = String(resolved.protocol || "").toLowerCase();
    if (pageProtocol === "https:" || socketProtocol === "https:" || socketProtocol === "wss:") {
      resolved.protocol = "wss:";
    } else {
      resolved.protocol = "ws:";
    }
    return resolved.toString();
  } catch (_error) {
    return "";
  }
}

export function routeLabel(route) {
  return firstNonEmpty(route?.action, route?.story_verb, route?.route_id, "route");
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function agentInitials(agent) {
  const source = firstNonEmpty(agent?.display_name, agent?.agent_id, "A");
  const tokens = source.split(/\s+/).filter(Boolean).slice(0, 2);
  if (!tokens.length) {
    return "A";
  }
  return tokens.map((token) => token.charAt(0).toUpperCase()).join("");
}

export function primaryAgentImage(agent) {
  const portraitUrl = firstNonEmpty(agent?.portrait_image_url, agent?.portrait_image_path, "");
  if (portraitUrl) {
    return normalizeImageCard({
      label: firstNonEmpty(agent?.display_name, agent?.agent_id, "Agent portrait"),
      image_url: portraitUrl,
      source_path: firstNonEmpty(agent?.portrait_image_path, ""),
      description: firstNonEmpty(agent?.role_name, agent?.appearance_prompt, ""),
    });
  }
  const objectCard = safeArray(agent?.object_images).find((card) => firstNonEmpty(card?.image_url, ""));
  if (objectCard) {
    return objectCard;
  }
  const artifactCard = safeArray(agent?.artifact_images).find((card) => firstNonEmpty(card?.image_url, ""));
  if (artifactCard) {
    return artifactCard;
  }
  const inventoryImage = safeArray(agent?.inventory).find((entry) => firstNonEmpty(entry?.image_url, entry?.image_path, ""));
  if (!inventoryImage) {
    return null;
  }
  return normalizeImageCard(inventoryImage, {
    label: firstNonEmpty(inventoryImage?.name, inventoryImage?.item_id, "Inventory item"),
    itemId: inventoryImage?.item_id || "",
    imageUrl: firstNonEmpty(inventoryImage?.image_url, inventoryImage?.image_path, ""),
    sourcePath: firstNonEmpty(inventoryImage?.image_path, ""),
    description: firstNonEmpty(inventoryImage?.description, ""),
  });
}

export function runtimeModeFromLocation() {
  const params = new URLSearchParams(window.location.search || "");
  const value = (params.get("mode") || params.get("live") || "").trim().toLowerCase();
  if (value === "0" || value === "false" || value === "bootstrap" || value === "local" || value === "replay") {
    return "bootstrap";
  }
  if (value === "1" || value === "true" || value === "live") {
    return "live";
  }
  if (
    params.get("pixel_world") ||
    params.get("access_code") ||
    params.get("seed") ||
    window.localStorage.getItem("agora_pixel_world_code") ||
    window.localStorage.getItem("agora_pixel_live_session_id")
  ) {
    return "live";
  }
  return "live";
}

export function selectedPixelWorldCodeFromLocation() {
  const params = new URLSearchParams(window.location.search || "");
  return firstNonEmpty(
    window.__AGORA_PIXEL_WORLD_CODE__ || "",
    params.get("pixel_world") || "",
    params.get("access_code") || "",
  );
}

export function liveSessionIdFromLocation() {
  const params = new URLSearchParams(window.location.search || "");
  return firstNonEmpty(
    params.get("session_id") || "",
    params.get("live_session_id") || "",
    window.localStorage.getItem("agora_pixel_live_session_id"),
  );
}

export function persistLiveSessionFromLocation() {
  const params = new URLSearchParams(window.location.search || "");
  const raw = firstNonEmpty(
    params.get("persist_session") || "",
    params.get("keep_session") || "",
    window.localStorage.getItem("agora_pixel_live_persist_session") || "",
  ).trim().toLowerCase();
  return raw === "1" || raw === "true" || raw === "yes" || raw === "on";
}

export function captureModeFromLocation() {
  const params = new URLSearchParams(window.location.search || "");
  return firstNonEmpty(params.get("capture_mode") || params.get("snapshot_mode") || "").trim().toLowerCase();
}

export function headlessKickFromLocation() {
  const params = new URLSearchParams(window.location.search || "");
  const raw = firstNonEmpty(params.get("headless_kick") || params.get("force_manual_render") || "").trim().toLowerCase();
  return raw === "1" || raw === "true" || raw === "yes" || raw === "on";
}

export function isAbsoluteLikeUrl(value) {
  return /^(?:[a-z]+:)?\/\//i.test(value) || value.startsWith("data:") || value.startsWith("blob:");
}

export function groupAgentsByRoom(agentList) {
  const grouped = new Map();
  agentList.forEach((agent) => {
    const roomId = agent.room_id || "unknown";
    if (!grouped.has(roomId)) {
      grouped.set(roomId, []);
    }
    grouped.get(roomId).push(agent);
  });
  return grouped;
}

export function occupantCountMap(agentList) {
  const counts = new Map();
  agentList.forEach((agent) => {
    const roomId = agent.room_id || "unknown";
    counts.set(roomId, (counts.get(roomId) || 0) + 1);
  });
  return counts;
}

export function roomBoundsInTiles(room, fallbackWidthTiles, fallbackHeightTiles) {
  const footprint = safeArray(room?.footprint_tiles);
  if (footprint.length) {
    const xs = footprint.map((tile) => Number(tile?.x ?? 0));
    const ys = footprint.map((tile) => Number(tile?.y ?? 0));
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    return {
      minX,
      minY,
      maxX,
      maxY,
      widthTiles: maxX - minX + 1,
      heightTiles: maxY - minY + 1,
    };
  }
  const minX = Number(room?.x ?? 0);
  const minY = Number(room?.y ?? 0);
  const widthTiles = Number(room?.width_tiles ?? fallbackWidthTiles ?? 1);
  const heightTiles = Number(room?.height_tiles ?? fallbackHeightTiles ?? 1);
  return {
    minX,
    minY,
    maxX: minX + widthTiles - 1,
    maxY: minY + heightTiles - 1,
    widthTiles,
    heightTiles,
  };
}

export function roomTilesInGrid(room, mapGrid) {
  const footprint = safeArray(room?.footprint_tiles);
  if (footprint.length) {
    return footprint.map((tile) => ({
      x: Number(tile?.x ?? 0),
      y: Number(tile?.y ?? 0),
      z: Number(tile?.z ?? 0),
    }));
  }
  const bounds = roomBoundsInTiles(room, mapGrid?.map_visual?.room_width_tiles || 6, mapGrid?.map_visual?.room_height_tiles || 4);
  const tiles = [];
  for (let y = bounds.minY; y <= bounds.maxY; y += 1) {
    for (let x = bounds.minX; x <= bounds.maxX; x += 1) {
      tiles.push({ x, y, z: 0 });
    }
  }
  return tiles;
}

export function anchorOriginInTiles(anchor, bounds, widthTiles, heightTiles) {
  const anchors = {
    north_west: { x: bounds.minX, y: bounds.minY },
    north_mid: { x: Math.round(bounds.minX + ((bounds.widthTiles - widthTiles) / 2)), y: bounds.minY },
    north_east: { x: bounds.maxX - widthTiles + 1, y: bounds.minY },
    west_mid: { x: bounds.minX, y: Math.round(bounds.minY + ((bounds.heightTiles - heightTiles) / 2)) },
    center: {
      x: Math.round(bounds.minX + ((bounds.widthTiles - widthTiles) / 2)),
      y: Math.round(bounds.minY + ((bounds.heightTiles - heightTiles) / 2)),
    },
    east_mid: { x: bounds.maxX - widthTiles + 1, y: Math.round(bounds.minY + ((bounds.heightTiles - heightTiles) / 2)) },
    south_west: { x: bounds.minX, y: bounds.maxY - heightTiles + 1 },
    south_mid: { x: Math.round(bounds.minX + ((bounds.widthTiles - widthTiles) / 2)), y: bounds.maxY - heightTiles + 1 },
    south_east: { x: bounds.maxX - widthTiles + 1, y: bounds.maxY - heightTiles + 1 },
  };
  return anchors[String(anchor || "center")] || anchors.center;
}

export async function fetchJson(path, { method = "GET", ...options } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new Error("timer")), 30000);
  const response = await fetch(`${path}?t=${Date.now()}`, {
    cache: "no-store",
    signal: controller.signal,
    ...options,
  }).finally(() => clearTimeout(timer));
  if (!response.ok) {
    throw new Error(`Failed to load ${path}`);
  }
  return response.json();
}

export async function postJson(path, body = {}, { method = "POST" } = {}) {
  const response = await fetch(path, {
    method,
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body ?? {}),
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    let detail = String(text || "").trim();
    if (detail) {
      try {
        const payload = JSON.parse(detail);
        if (payload && typeof payload === "object") {
          detail = firstNonEmpty(payload.detail, payload.error, payload.message, detail);
        }
      } catch (error) {
        // Non-JSON error bodies should still surface their raw text.
      }
    }
    throw new Error(detail || `Failed to call ${path}`);
  }
  return response.json();
}

export function isAiStudioErrorMessage(message) {
  const text = String(message || "").trim().toLowerCase();
  if (!text) {
    return false;
  }
  return text.includes("ai studio")
    || text.includes("google_ai_studio")
    || text.includes("vertex rest api failed")
    || text.includes("live_agent_response")
    || text.includes("generativelanguage.googleapis.com")
    || text.includes("temporary failure in name resolution");
}

export function appendInfoItem(container, label, value) {
  const item = document.createElement("div");
  item.className = "info-item";
  const title = document.createElement("strong");
  title.textContent = label;
  const content = document.createElement("div");
  content.textContent = value;
  item.append(title, content);
  container.appendChild(item);
}

export function appendMediaSection(container, titleText, cards, openImageModal) {
  const section = document.createElement("section");
  section.className = "media-section";
  const title = document.createElement("h3");
  title.textContent = `${titleText} (${cards.length})`;
  section.appendChild(title);
  if (!cards.length) {
    const empty = document.createElement("div");
    empty.className = "muted media-empty";
    empty.textContent = "No image attached in the latest runtime state.";
    section.appendChild(empty);
    container.appendChild(section);
    return;
  }
  const grid = document.createElement("div");
  grid.className = "media-grid";
  cards.forEach((card) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "media-card";
    button.addEventListener("click", () => openImageModal(card));

    const preview = document.createElement("img");
    preview.className = "media-thumb";
    preview.src = card.image_url;
    preview.alt = card.label;
    preview.loading = "lazy";
    button.appendChild(preview);

    const body = document.createElement("div");
    body.className = "media-card-body";
    const label = document.createElement("strong");
    label.textContent = card.label;
    body.appendChild(label);
    if (card.item_id) {
      const meta = document.createElement("div");
      meta.className = "media-meta";
      meta.textContent = card.item_id;
      body.appendChild(meta);
    }
    if (card.description) {
      const description = document.createElement("div");
      description.className = "media-caption";
      description.textContent = card.description;
      body.appendChild(description);
    }
    button.appendChild(body);
    grid.appendChild(button);
  });
  section.appendChild(grid);
  container.appendChild(section);
}

