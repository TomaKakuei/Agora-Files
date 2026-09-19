const Phaser = window.Phaser;
const PIXEL_BUNDLE_VERSION = String(window.__AGORA_PIXEL_BUNDLE_VERSION__ || "dev").trim() || "dev";
window.__AGORA_PIXEL_BUNDLE_VERSION__ = PIXEL_BUNDLE_VERSION;

const root = document.getElementById("game-root");
const worldNameNode = document.getElementById("world-name");
const eventStatusNode = document.getElementById("event-status");
const worldSelectNode = document.getElementById("world-select");
const openMacroLinkNode = document.getElementById("open-macro-link");

function getQueryParams() {
  return new URLSearchParams(window.location.search || "");
}

function resetPersistedPixelStateIfRequested() {
  const params = getQueryParams();
  const raw = String(params.get("reset_client_state") || params.get("reset_local_state") || "").trim().toLowerCase();
  if (!(raw === "1" || raw === "true" || raw === "yes" || raw === "on")) {
    return;
  }
  [
    "agora_pixel_world_code",
    "agora_pixel_world_seed",
    "agora_pixel_live_session_id",
    "agora_pixel_live_persist_session",
  ].forEach((key) => {
    try {
      window.localStorage.removeItem(key);
    } catch (_error) {
      // Ignore browsers that block storage access in headless modes.
    }
  });
}

function headlessKickEnabled() {
  const params = getQueryParams();
  const raw = String(params.get("headless_kick") || params.get("force_manual_render") || "").trim().toLowerCase();
  return raw === "1" || raw === "true" || raw === "yes" || raw === "on";
}

function rendererTypeForLocation(PhaserRuntime) {
  const params = getQueryParams();
  const captureMode = String(params.get("capture_mode") || params.get("snapshot_mode") || "").trim().toLowerCase();
  const renderer = String(params.get("renderer") || "").trim().toLowerCase();
  if (headlessKickEnabled()) {
    return PhaserRuntime.CANVAS;
  }
  if (renderer === "canvas" || captureMode === "export") {
    return PhaserRuntime.CANVAS;
  }
  if (renderer === "webgl") {
    return PhaserRuntime.WEBGL;
  }
  return PhaserRuntime.AUTO;
}

function normalizeSeedValue(value) {
  const raw = String(value ?? "").trim();
  if (!raw) {
    return "";
  }
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? String(Math.trunc(parsed)) : raw;
}

function getInitialWorldSelection(worlds) {
  const params = getQueryParams();
  const queryCode = (params.get("pixel_world") || params.get("access_code") || "").trim();
  if (queryCode) {
    return { access_code: queryCode, seed: "" };
  }
  const querySeed = normalizeSeedValue(params.get("seed"));
  if (querySeed) {
    const matchedWorld = (worlds || []).find((world) => normalizeSeedValue(world?.seed) === querySeed);
    if (matchedWorld?.access_code) {
      return {
        access_code: String(matchedWorld.access_code || "").trim(),
        seed: querySeed,
      };
    }
  }
  const storedCode = (window.localStorage.getItem("agora_pixel_world_code") || "").trim();
  if (storedCode) {
    return {
      access_code: storedCode,
      seed: normalizeSeedValue(window.localStorage.getItem("agora_pixel_world_seed")),
    };
  }
  const firstWorld = worlds[0] || {};
  return {
    access_code: String(firstWorld.access_code || "").trim(),
    seed: normalizeSeedValue(firstWorld.seed),
  };
}

function setWorldSelectOptions(worlds, selectedCode) {
  if (!worldSelectNode) {
    return;
  }
  worldSelectNode.innerHTML = "";
  const worldMap = new Map((worlds || []).map((world) => [String(world.access_code || ""), world]));
  if (selectedCode && !worldMap.has(selectedCode)) {
    const option = document.createElement("option");
    option.value = selectedCode;
    option.textContent = `Selected world ${selectedCode} (not in catalog)`;
    option.selected = true;
    worldSelectNode.appendChild(option);
  }
  if (!worlds.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No PIXEL READ worlds available";
    option.selected = true;
    worldSelectNode.appendChild(option);
    worldSelectNode.disabled = true;
    return;
  }
  worldSelectNode.disabled = false;
  worlds.forEach((world) => {
    const accessCode = String(world.access_code || "").trim();
    if (!accessCode) {
      return;
    }
    const option = document.createElement("option");
    option.value = accessCode;
    const seedLabel = normalizeSeedValue(world.seed);
    option.textContent = `${world.world_name || world.package_name || "Pixel world"} · seed ${seedLabel || "n/a"} · ${accessCode}`;
    if (accessCode === selectedCode) {
      option.selected = true;
    }
    worldSelectNode.appendChild(option);
  });
}

function updateMacroLink(accessCode, worlds) {
  if (!openMacroLinkNode) {
    return;
  }
  const macroUrl = new URL("/macro/", window.location.origin);
  const normalizedCode = String(accessCode || "").trim();
  if (normalizedCode) {
    macroUrl.searchParams.set("access_code", normalizedCode);
    const selectedWorld = (worlds || []).find((world) => String(world?.access_code || "").trim() === normalizedCode);
    const selectedSeed = normalizeSeedValue(selectedWorld?.seed);
    if (selectedSeed) {
      macroUrl.searchParams.set("seed", selectedSeed);
    }
  }
  openMacroLinkNode.href = macroUrl.toString();
}

function applyWorldSelection(accessCode, worlds) {
  const params = getQueryParams();
  if (accessCode) {
    params.set("pixel_world", accessCode);
    window.localStorage.setItem("agora_pixel_world_code", accessCode);
    const selectedWorld = (worlds || []).find((world) => String(world.access_code || "").trim() === accessCode);
    const selectedSeed = normalizeSeedValue(selectedWorld?.seed);
    if (selectedSeed) {
      params.set("seed", selectedSeed);
      window.localStorage.setItem("agora_pixel_world_seed", selectedSeed);
    } else {
      params.delete("seed");
      window.localStorage.removeItem("agora_pixel_world_seed");
    }
  } else {
    params.delete("pixel_world");
    params.delete("seed");
    window.localStorage.removeItem("agora_pixel_world_code");
    window.localStorage.removeItem("agora_pixel_world_seed");
  }
  const query = params.toString();
  const nextUrl = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash || ""}`;
  window.location.assign(nextUrl);
}

async function fetchJson(path) {
  const response = await fetch(`${path}?t=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load ${path}`);
  }
  return response.json();
}

function surfaceStartupError(message) {
  if (worldNameNode) {
    worldNameNode.textContent = "Pixel UI failed to boot";
  }
  if (eventStatusNode) {
    eventStatusNode.textContent = message;
  }
}

function manualStepGame(game, steps = 4) {
  if (!game || typeof game.step !== "function") {
    return;
  }
  const baseNow = window.performance.now();
  for (let index = 0; index < steps; index += 1) {
    game.step(baseNow + (index * 16.6667), 16.6667);
  }
}

function kickstartHeadlessRender(game) {
  if (!headlessKickEnabled() || !game) {
    return;
  }
  let attempts = 0;
  const maxAttempts = 480;
  const tick = () => {
    const frameValue = Number(game.getFrame?.() ?? game.loop?.frame ?? 0);
    if (typeof game.onVisible === "function") {
      game.onVisible();
    }
    if (game.loop && typeof game.loop.wake === "function") {
      game.loop.wake(true);
    }
    manualStepGame(game, frameValue > 0 ? 2 : 6);
    attempts += 1;
    if (attempts >= maxAttempts) {
      window.clearInterval(timer);
    }
  };
  window.setTimeout(tick, 120);
  const timer = window.setInterval(tick, 250);
}

async function loadCatalogWorlds() {
  try {
    const catalog = await fetchJson("/api/pixel/worlds");
    return Array.isArray(catalog.worlds) ? catalog.worlds : [];
  } catch (_error) {
    return [];
  }
}

async function boot() {
  resetPersistedPixelStateIfRequested();
  let worlds = [];
  const querySelected = getInitialWorldSelection([]);
  const hasExplicitSelection = Boolean(querySelected.access_code || querySelected.seed);
  if (!hasExplicitSelection) {
    worlds = await loadCatalogWorlds();
  }
  const selectedSelection = getInitialWorldSelection(worlds);
  const selectedCode = selectedSelection.access_code || "";
  window.__AGORA_PIXEL_WORLD_CODE__ = selectedCode;
  window.__AGORA_HEADLESS_KICK__ = headlessKickEnabled();
  setWorldSelectOptions(worlds, selectedCode);
  updateMacroLink(selectedCode, worlds);
  if (worldSelectNode) {
    worldSelectNode.value = selectedCode;
    worldSelectNode.addEventListener("change", () => {
      applyWorldSelection(worldSelectNode.value.trim(), worlds);
    });
  }
  if (hasExplicitSelection) {
    void loadCatalogWorlds().then((catalogWorlds) => {
      worlds = catalogWorlds;
      setWorldSelectOptions(worlds, selectedCode);
      updateMacroLink(selectedCode, worlds);
      if (worldSelectNode) {
        worldSelectNode.value = selectedCode;
      }
    });
  }

  if (!Phaser) {
    surfaceStartupError("Phaser runtime unavailable");
    return;
  }
  try {
    const { WorldScene } = await import(`./WorldScene.js?v=${encodeURIComponent(PIXEL_BUNDLE_VERSION)}`);
    const game = new Phaser.Game({
      type: rendererTypeForLocation(Phaser),
      parent: root,
      width: root.clientWidth,
      height: root.clientHeight,
      backgroundColor: "#0f0c13",
      pixelArt: true,
      roundPixels: true,
      scene: [WorldScene],
      scale: {
        mode: Phaser.Scale.RESIZE,
        autoCenter: Phaser.Scale.CENTER_BOTH,
      },
    });
    window.__AGORA_PHASER_GAME__ = game;
    window.__AGORA_MANUAL_STEP_GAME__ = (steps = 4) => manualStepGame(game, steps);
    kickstartHeadlessRender(game);
  } catch (error) {
    surfaceStartupError(error?.message || "Unknown startup error");
    throw error;
  }
}

boot().catch((error) => {
  surfaceStartupError(error?.message || "Unknown startup error");
});
