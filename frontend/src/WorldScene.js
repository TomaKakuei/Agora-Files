import { LiveComposerUi } from "./LiveComposerUi.js";
import { ActionController } from "./ActionController.js";
import { GridPathingController } from "./GridPathingController.js";
import { ItemController } from "./ItemController.js";
import { InputController } from "./InputController.js";
import { RoomUiController } from "./RoomUiController.js";
import { AgentStateController } from "./AgentStateController.js";
import { Phaser, formatTemplate, DEFAULT_BOOTSTRAP_PATH, normalizeAgentRecord, roomBoundsInTiles, newClientActionId, selectedPixelWorldCodeFromLocation, runtimeModeFromLocation, DEFAULT_RUNTIME_POINTER_PATH, resolveWebSocketUrl, fetchJson, appendInfoItem, captureModeFromLocation, groupAgentsByRoom, liveEventPayload, routeLabel, escapeHtml, persistLiveSessionFromLocation, tileKey, isAbsoluteLikeUrl, occupantCountMap, primaryAgentImage, DEFAULT_MAP_GRID_PATH, parseJsonObject, DEFAULT_WORLD_CONFIG_PATH, liveSessionIdFromLocation, firstNonEmpty, agentInitials, safeArray } from "./utils.js";
import { AgentManager } from "./AgentManager.js";
import { AssetResolver } from "./AssetResolver.js";
import { WorldRenderer } from "./WorldRenderer.js";
import { CameraController } from "./CameraController.js";
import { LiveSessionManager } from "./LiveSessionManager.js";
import { LiveMovementController } from "./LiveMovementController.js";
import { LiveUiController } from "./LiveUiController.js";
import { PovController } from "./PovController.js";
import { ExportRenderer } from "./ExportRenderer.js";

export class WorldScene extends Phaser.Scene {
  constructor() {
    super("world");
    this.assetResolver = new AssetResolver(this);
    this.worldRenderer = new WorldRenderer(this);
    this.cameraController = new CameraController(this);
    this.liveComposerUi = new LiveComposerUi(this);
    this.actionController = new ActionController(this);
    this.gridPathingController = new GridPathingController(this);
    this.itemController = new ItemController(this);
    this.inputController = new InputController(this);
    this.roomUiController = new RoomUiController(this);
    this.agentStateController = new AgentStateController(this);
    this.liveSessionManager = new LiveSessionManager(this);
    this.liveMovementController = new LiveMovementController(this);
    this.liveUiController = new LiveUiController(this);
    this.povController = new PovController(this);
    this.exportRenderer = new ExportRenderer(this);
    
    // Original State Initialization (simplified)
    this.worldConfig = null;
    this.mapGrid = null;
    this.frontendBootstrap = null;
    this.roomLookup = new Map();
    this.currentAgents = [];
    this.runtimeState = null;
    this.runtimeFingerprint = "";
    this.runtimePointerPath = DEFAULT_RUNTIME_POINTER_PATH;
    this.runtimeMode = runtimeModeFromLocation();
    this.assetSetManifest = null;
    this.assetSetManifestPath = "";
    this.assetSetManifestPromise = null;
    this.agentPortraitById = new Map();
    this.generatedMapKey = "";
    this.generatedMapImage = null;
    this.worldDimensions = { width: 0, height: 0, margin: 36, cameraPaddingX: 0, cameraPaddingY: 0 };
    this.roomNodes = new Map();
    this.selectedRoomId = "";
    this.homeRoomId = "";
    this.isDraggingCamera = false;
    this.dragOrigin = null;
    this.displayMetrics = { tileWidth: 32, tileHeight: 32, renderScale: 1 };
    this.viewMode = "pov";
    this.selectedAgentRecord = null;
    this.pixelWorldCode = selectedPixelWorldCodeFromLocation();
    this.assetBaseUrl = window.location.href;
    this.pixelWorldRecord = null;
    this.liveSessionIdFromLocation = liveSessionIdFromLocation();
    this.livePersistSession = persistLiveSessionFromLocation();
    this.captureMode = captureModeFromLocation();
    
    this.exportFallback = { canvas: null, ctx: null, assetEvents: new Map(), mapImageUrl: "", mapImage: null, frameCache: new Map(), renderPromise: null };
    
    // Live State
    this.liveState = { enabled: false, sessionId: "", session: null, state: null, endpoints: { session: "", state: "", action: "", heartbeat: "", wsTemplate: "" }, targetAgentId: "", eventLog: [], lastEventId: 0, selectedItemId: "", selectedMoveRouteId: "", selectedTradeRouteId: "", movementKeys: new Map(), lastStepAt: 0, moveInFlight: false, actionDraft: "", pollInFlight: false, pollIntervalMs: 1200, fingerprint: "", lastBubbleEventId: 0, persistSession: this.livePersistSession, lastClaimedAgentRoomId: "", frozenPayload: null, frozenFingerprint: "", typingFreezeActive: false, isComposingText: false, liveReadyAgentIds: [], authoritativeAgents: [], pendingMessages: [], pendingMoves: [], pendingMove: null, pendingTradeQuotes: [], pendingTaskAssignments: [], realtimeEnabled: false, wsUrl: "", websocket: null, websocketConnected: false, websocketConnecting: false, websocketTransportActive: false, websocketReconnectBlocked: false, websocketReconnectTimer: 0, websocketHeartbeatTimer: 0, websocketReconnectAttempts: 0, websocketLastMessageAt: 0, lastRestPollAt: 0, realtimeTickIntervalMs: 50, realtimeFlushIntervalMs: 1000, nextInputSeq: 0 };
    this.liveUiSignatures = { movement: "", items: "", trade: "", dialogue: "", log: "", hud: "", selector: "", pending: "", target: "" };
    this.liveComposerElements = null;
    this.liveErrorOverlay = null;
    
    // POV State
    this.itemCatalog = new Map();
    this.mainCharacterConfigs = new Map();
    this.roomTileIndex = new Map();
    this.roomCollisionIndex = new Map();
    this.localPovState = { enabled: false, protagonistAgentId: "", selectedItemId: "", dialogueTargetId: "", actionLog: [], dialogueLog: [], tradeOffers: [], agentState: new Map(), groundItems: [], groundItemNodes: new Map(), speechBubbles: new Map(), movementKeys: new Map(), lastStepAt: 0, idleResetTimer: null };
    this.windowMovementState = new Set();
    this.windowKeyHandlersInstalled = false;
    this.windowKeyDownHandler = null;
    this.windowKeyUpHandler = null;

    const controllers = [this.liveSessionManager, this.liveUiController, this.liveMovementController, this.povController, this.cameraController, this.exportRenderer, this.worldRenderer, this.assetResolver, this.liveComposerUi, this.actionController, this.gridPathingController, this.itemController, this.inputController, this.roomUiController, this.agentStateController];
    for (const c of controllers) if (c) for (const p of Object.getOwnPropertyNames(Object.getPrototypeOf(c))) if (p !== "constructor" && typeof c[p] === "function" && !(p in this)) this[p] = c[p].bind(c);
  }

  setStartupStatus(message, { worldName = null } = {}) {
    const statusNode = document.getElementById("event-status");
    if (statusNode) statusNode.textContent = message;
    if (worldName !== null) {
      const worldNode = document.getElementById("world-name");
      if (worldNode) worldNode.textContent = worldName;
    }
  }

  async create() {
    try {
      this.setStartupStatus("Booting Pixel UI...", { worldName: "Booting world..." });
      this.uiBridge = this.createUiBridge();
      this.agentManager = new AgentManager(this, this.uiBridge);
      this.events.once("shutdown", () => {
        this.liveSessionManager.disconnectLiveWebSocket({ suppressReconnect: true });
      });
      if (this.liveSessionManager.isLiveSessionMode() && !this.liveState.persistSession) {
        window.addEventListener("pagehide", () => {
          this.liveSessionManager.disconnectLiveWebSocket({ suppressReconnect: true });
          void this.liveSessionManager.releaseLiveSession();
        }, { once: true });
      }

    this.setStartupStatus("Loading world data...");
    await this.loadWorldData();

      this.setStartupStatus("Drawing world shell...");
      this.worldRenderer.drawWorld();
      this.liveUiController.refreshWorldNotes();
      this.exportRenderer.kickHeadlessRender(4);

      this.setStartupStatus("Syncing agents...");
      this.syncAgents(this.currentAgents);
      if (this.liveSessionManager.isLiveSessionMode()) {
        this.setStartupStatus("Connecting realtime movement...");
        this.liveSessionManager.connectLiveWebSocket();
      }

      this.setStartupStatus("Initializing POV modules...");
      this.povController.initializeLocalPovModules();

      this.setStartupStatus("Building room navigator...");
      this.roomUiController.buildRoomNavigator();

      this.setStartupStatus("Installing camera controls...");
      this.cameraController.installCameraControls();
      this.inputController.installWindowMovementControls();
      this.liveUiController.refreshImmersiveHud();
      this.startEventPolling();
      this.startRuntimePolling();
      this.setStartupStatus("Bootstrapped world; hydrating assets...");
      void this.continueAsyncBootstrap();
    } catch (error) {
      const detail = error?.stack || error?.message || String(error);
      this.setStartupStatus(`Startup failed: ${detail.slice(0, 220)}`, { worldName: "Pixel UI startup failed" });
      const notes = document.getElementById("world-notes");
      if (notes) {
        notes.innerHTML = "";
        appendInfoItem(notes, "Startup Error", detail);
      }
      throw error;
    }
  }

  update() {
    if (this.liveSessionManager.isLiveSessionMode()) {
      this.inputController.tickLiveSession();
    } else {
      this.inputController.tickLocalPov();
    }
    this.roomUiController.updateSpeechBubblePositions();
  }

  async loadWorldData() {
    let worldConfigPath = DEFAULT_WORLD_CONFIG_PATH;
    let mapGridPath = DEFAULT_MAP_GRID_PATH;
    let worldConfig = null;
    this.assetBaseUrl = window.location.href;
    let scenarioManifest = null;
    let scenarioAgents = [];
    this.pixelWorldRecord = null;
    this.liveState.enabled = this.runtimeMode === "live";
    this.liveState.sessionId = "";
    this.liveState.session = null;
    this.liveState.state = null;
    this.liveState.endpoints = {
      session: "",
      state: "",
      action: "",
      heartbeat: "",
      wsTemplate: "",
    };
    this.liveState.targetAgentId = "";
    this.liveState.eventLog = [];
    this.liveState.lastEventId = 0;
    this.liveState.selectedItemId = "";
    this.liveState.selectedMoveRouteId = "";
    this.liveState.selectedTradeRouteId = "";
    this.liveState.moveInFlight = false;
    this.liveState.pollInFlight = false;
    this.liveState.pollIntervalMs = 1200;
    this.liveState.authoritativeAgents = [];
    this.liveState.pendingMessages = [];
    this.liveState.pendingMoves = [];
    this.liveState.pendingMove = null;
    this.liveState.pendingTradeQuotes = [];
    this.liveState.pendingTaskAssignments = [];
    this.liveState.realtimeEnabled = false;
    this.liveState.wsUrl = "";
    this.liveState.websocket = null;
    this.liveState.websocketConnected = false;
    this.liveState.websocketConnecting = false;
    this.liveState.websocketTransportActive = false;
    this.liveState.websocketReconnectBlocked = false;
    this.liveState.websocketLastMessageAt = 0;
    this.liveState.websocketReconnectAttempts = 0;
    this.liveState.lastRestPollAt = 0;
    this.liveState.realtimeTickIntervalMs = 50;
    this.liveState.realtimeFlushIntervalMs = 1000;
    this.liveState.nextInputSeq = 0;
    this.liveState.persistSession = persistLiveSessionFromLocation();
    const requestedLiveSessionId = liveSessionIdFromLocation();

    if (this.runtimeMode === "live") {
      if (!this.pixelWorldCode) {
        throw new Error("Live mode requires a pixel_world access code.");
      }
      this.setStartupStatus(`Loading live pixel world: ${this.pixelWorldCode}`);
      const liveRecord = await fetchJson(`/api/pixel/worlds/${encodeURIComponent(this.pixelWorldCode)}`);
      this.pixelWorldRecord = liveRecord.package || null;
      this.assetBaseUrl = firstNonEmpty(liveRecord.asset_base_url, window.location.href);
      mapGridPath = firstNonEmpty(liveRecord.map_grid_url, mapGridPath);
      worldConfigPath = firstNonEmpty(liveRecord.world_config_url, worldConfigPath);
      this.liveState.endpoints = {
        session: firstNonEmpty(liveRecord.live_session_url, ""),
        state: firstNonEmpty(liveRecord.live_state_url, ""),
        action: firstNonEmpty(liveRecord.live_action_url, ""),
        heartbeat: "",
        wsTemplate: firstNonEmpty(liveRecord.live_ws_url_template, ""),
      };
      if (liveRecord.package?.world_name) {
        this.setStartupStatus(`Loading live pixel world: ${liveRecord.package.world_name}`, { worldName: liveRecord.package.world_name });
      }
    } else if (this.pixelWorldCode) {
      try {
        const response = await fetchJson(`/api/pixel/worlds/${encodeURIComponent(this.pixelWorldCode)}`);
        worldConfig = response.world_config || null;
        this.assetBaseUrl = firstNonEmpty(response.asset_base_url, window.location.href);
        mapGridPath = firstNonEmpty(response.map_grid_url, mapGridPath);
        worldConfigPath = firstNonEmpty(response.world_config_url, worldConfigPath);
        this.pixelWorldRecord = response.package || null;
        if (response.package?.world_name) {
          this.setStartupStatus(`Loading pixel world: ${response.package.world_name}`, { worldName: response.package.world_name });
        }
      } catch (error) {
        this.pixelWorldCode = "";
      }
    }
    if (!worldConfig) {
      this.setStartupStatus(`Loading world config: ${worldConfigPath}`);
      worldConfig = await fetchJson(worldConfigPath);
    }
    const loadedWorldName = firstNonEmpty(
      worldConfig?.scenario_meta?.world_name,
      this.pixelWorldRecord?.world_name || "",
    );
    this.setStartupStatus(`Loading map grid: ${mapGridPath}`, loadedWorldName ? { worldName: loadedWorldName } : {});
    const mapGrid = await fetchJson(mapGridPath);
    if (this.runtimeMode !== "live") {
      try {
        const resolvedMapGridUrl = this.assetResolver.resolveFrontendUrl(mapGridPath);
        const scenarioRootUrl = new URL(".", resolvedMapGridUrl).toString();
        const manifestUrl = new URL("manifest.json", resolvedMapGridUrl).toString();
        this.setStartupStatus(`Loading scenario manifest: ${manifestUrl}`);
        scenarioManifest = await fetchJson(manifestUrl);
        const activeAgents = safeArray(scenarioManifest?.asset_bindings?.active_agents || []);
        if (activeAgents.length) {
          this.setStartupStatus(`Loading scenario agents: ${activeAgents.length}`);
          const agentPayloads = await Promise.all(
            activeAgents.map((relativePath) => {
              const resolvedPath = isAbsoluteLikeUrl(relativePath)
                ? relativePath
                : new URL(relativePath, scenarioRootUrl).toString();
              return fetchJson(resolvedPath).catch(() => null);
            }),
          );
          scenarioAgents = agentPayloads.filter((payload) => payload && typeof payload === "object");
        }
      } catch (error) {
        scenarioManifest = null;
        scenarioAgents = [];
      }
    }
    if (!scenarioAgents.length && this.runtimeMode !== "live") {
      this.setStartupStatus(`Loading bootstrap agents: ${DEFAULT_BOOTSTRAP_PATH}`);
      const bootstrapAgents = await fetch(`${DEFAULT_BOOTSTRAP_PATH}?t=${Date.now()}`, { cache: "no-store" })
        .then((response) => (response.ok ? response.json() : { agents: [] }));
      scenarioAgents = safeArray(bootstrapAgents.agents);
    }

    this.worldConfig = worldConfig;
    this.mapGrid = mapGrid;
    this.frontendBootstrap = { manifest: scenarioManifest, agents: scenarioAgents };
    this.assetSetManifest = null;
    this.roomLookup = new Map();
    safeArray(mapGrid.rooms).forEach((room) => this.roomLookup.set(room.room_id, room));
    this.roomTileIndex = this.worldRenderer.buildRoomTileIndex(mapGrid);
    this.roomCollisionIndex = this.worldRenderer.buildRoomCollisionIndex(mapGrid, worldConfig);
    this.itemCatalog = new Map(safeArray(worldConfig?.property_library?.item_catalog).map((item) => [item.item_id, item]));
    this.mainCharacterConfigs = new Map(safeArray(worldConfig?.main_characters).map((agent) => [agent.agent_id, agent]));

    const frontendConfig = worldConfig?.pixel_asset_pipeline?.frontend || {};
    this.assetSetManifestPath = firstNonEmpty(frontendConfig.asset_set_manifest_path, "");
    this.assetSetManifest = null;
    this.assetSetManifestPromise = this.assetSetManifestPath
      ? fetchJson(this.assetResolver.resolveFrontendUrl(this.assetSetManifestPath))
      : null;

    this.runtimeState = null;
    if (this.runtimeMode === "live") {
      const displayName = firstNonEmpty(
        window.localStorage.getItem("agora_pixel_live_display_name"),
        this.pixelWorldRecord?.world_name,
        "Human Interactor",
      );
      let sessionResponse = null;
      if (requestedLiveSessionId) {
        this.liveState.sessionId = requestedLiveSessionId;
        try {
          sessionResponse = await this.liveSessionManager.fetchLiveState(0);
          window.localStorage.setItem("agora_pixel_live_session_id", requestedLiveSessionId);
          if (this.liveState.persistSession) {
            window.localStorage.setItem("agora_pixel_live_persist_session", "1");
          }
        } catch (error) {
          this.liveState.sessionId = "";
          sessionResponse = null;
        }
      }
      if (!sessionResponse) {
      sessionResponse = await this.liveSessionManager.createLiveSession({
          displayName,
          roomId: "",
          speedSecondsPerRound: 4.0,
        });
        window.localStorage.setItem("agora_pixel_live_session_id", this.liveState.sessionId || "");
        if (this.liveState.persistSession) {
          window.localStorage.setItem("agora_pixel_live_persist_session", "1");
        }
      }
      this.liveSessionManager.applyLiveState(sessionResponse.state || sessionResponse, { focusClaimedAgent: true });
      this.inputController.bindLiveMovementKeys();
      this.liveState.session = sessionResponse.session || this.liveState.session;
      this.liveState.sessionId = firstNonEmpty(this.liveState.session?.session_id, this.liveState.sessionId);
      window.localStorage.setItem("agora_pixel_live_session_id", this.liveState.sessionId || "");
      this.liveState.pollIntervalMs = Number(sessionResponse.state?.poll_interval_ms || sessionResponse.poll_interval_ms || 1200);
      this.liveState.lastRestPollAt = Date.now();
      this.liveState.endpoints.heartbeat = this.liveState.sessionId
        ? `${this.liveState.endpoints.session}/${encodeURIComponent(this.liveState.sessionId)}/heartbeat`
        : "";
      this.liveSessionManager.configureLiveRealtime(sessionResponse);
    } else {
      this.currentAgents = this.assetResolver.attachAgentPortraits(scenarioAgents.map(normalizeAgentRecord));
    }

    const homeAgentId = this.runtimeMode === "live"
      ? this.liveState.session?.claimed_agent_id || this.currentAgents.find((agent) => agent.main_character)?.agent_id || this.currentAgents[0]?.agent_id || ""
      : this.mapGrid?.map_visual?.camera?.follow_main_character || "";
    this.homeRoomId = this.currentAgents.find((agent) => agent.agent_id === homeAgentId)?.room_id || this.currentAgents[0]?.room_id || "";
    this.selectedRoomId = this.homeRoomId;
    this.selectedAgentRecord =
      this.currentAgents.find((agent) => agent.agent_id === homeAgentId) ||
      this.currentAgents.find((agent) => agent.main_character) ||
      this.currentAgents[0] ||
      null;

    this.liveUiController.refreshWorldNotes();
  }

  async continueAsyncBootstrap() {
    if (!this.assetSetManifest && this.assetSetManifestPromise) {
      this.setStartupStatus("Loading asset manifest...");
      this.assetSetManifest = await this.assetSetManifestPromise;
      this.assetSetManifestPromise = null;
      this.assetResolver.refreshAgentPortraitLookup();
      this.assetResolver.applyAgentPortraitsToState();
      this.liveUiController.refreshWorldNotes();
    } else if (!this.assetSetManifest && this.assetSetManifestPath) {
      this.setStartupStatus("Loading asset manifest...");
      this.assetSetManifest = await fetchJson(this.assetResolver.resolveFrontendUrl(this.assetSetManifestPath));
      this.assetResolver.refreshAgentPortraitLookup();
      this.assetResolver.applyAgentPortraitsToState();
      this.liveUiController.refreshWorldNotes();
    }
    this.setStartupStatus("Hydrating room map...");
    await this.drawGeneratedMapOverlay();
    this.setStartupStatus("Hydrating agent textures...");
    await this.hydrateGeneratedAssets();
    this.setStartupStatus("Pixel UI ready");
    this.exportRenderer.kickHeadlessRender(6);
    this.exportRenderer.scheduleExportFallbackRender();
  }



  syncAgents(agentList, { preserveCoordinates = false, animateMovement = false, refreshUi = true, movementDurationMs = 0 } = {}) {
    const grouped = groupAgentsByRoom(agentList);
    const { tileWidth, tileHeight } = this.displayMetrics;
    const margin = this.worldDimensions.margin;
    const keepAuthoredCoordinates = preserveCoordinates || this.povController.localPovEnabled();
    const allowCoordinateOverlap = keepAuthoredCoordinates && (this.liveSessionManager.isLiveSessionMode() || this.povController.localPovEnabled());

    grouped.forEach((agentsInRoom, roomId) => {
      const room = this.roomLookup.get(roomId);
      if (!room) {
        return;
      }
      const node = this.roomNodes.get(roomId);
      const bounds = node?.bounds || roomBoundsInTiles(room, 6, 4);
      const usedTiles = new Set();
      agentsInRoom.forEach((agent, index) => {
        let fallbackTile;
        try {
          fallbackTile = this.gridPathingController.resolveRenderableAgentTile(agent, roomId, usedTiles, index)
            || this.gridPathingController.autoPlacementTile(roomId, index)
            || { x: bounds.minX, y: bounds.minY, z: 0 };
        } catch (e) {
          throw new Error("DEBUG: this.gridPathingController=" + typeof this.gridPathingController + " | " + (this.gridPathingController ? typeof this.gridPathingController.resolveRenderableAgentTile : "null") + " | " + e.message);
        }
        const coordX = Number(agent.coordinates?.x);
        const coordY = Number(agent.coordinates?.y);
        const coordZ = Number(agent.coordinates?.z ?? 0);
        const authoredKey = tileKey(coordX, coordY, coordZ);
        const hasAuthoredCoords = Number.isFinite(coordX) && Number.isFinite(coordY);
        const useAuthoredCoords =
          keepAuthoredCoordinates &&
          hasAuthoredCoords &&
          !this.worldRenderer.isBlockedTile(roomId, coordX, coordY, coordZ) &&
          (allowCoordinateOverlap || !usedTiles.has(authoredKey));
        const authoredMatches =
          hasAuthoredCoords &&
          coordX === fallbackTile.x &&
          coordY === fallbackTile.y;
        if (useAuthoredCoords) {
          usedTiles.add(authoredKey);
        } else if (!authoredMatches) {
          agent.coordinates = {
            ...(agent.coordinates || {}),
            x: fallbackTile.x,
            y: fallbackTile.y,
            z: Number(fallbackTile.z ?? 0),
          };
        }
        const renderTile = useAuthoredCoords
          ? { x: coordX, y: coordY, z: coordZ }
          : fallbackTile;
        const x = margin + (renderTile.x + 0.5) * tileWidth;
        const y = margin + (renderTile.y + 0.68) * tileHeight;
        const sprite = this.agentManager.syncAgentRecord(agent, x, y, {
          animateMovement,
          movementDurationMs,
          suppressSelectedUiUpdate: this.liveSessionManager.isLiveSessionMode(),
        });
        if (this.agentManager.selectedAgentId === agent.agent_id) {
          sprite.setDepth(30);
        } else {
          sprite.setDepth(agent.main_character ? 28 : 20);
        }
      });
    });
    if (this.selectedAgentRecord) {
      const refreshedSelected = this.currentAgents.find((agent) => agent.agent_id === this.selectedAgentRecord.agent_id);
      if (refreshedSelected) {
        this.selectedAgentRecord = refreshedSelected;
        this.selectedRoomId = refreshedSelected.room_id || this.selectedRoomId;
      }
    }
    if (refreshUi) {
      this.roomUiController.refreshRoomNavigatorCounts(this.liveSessionManager.isLiveSessionMode() ? this.povController.activeAgentRecords({ authoritative: true }) : agentList);
    }
    this.worldRenderer.applyRoomHighlight();
    this.cameraController.applyPresenceFocus();
    if (refreshUi) {
      this.worldRenderer.renderGroundItems();
      this.liveUiController.refreshImmersiveHud();
      this.exportRenderer.scheduleExportFallbackRender();
      this.exportRenderer.kickHeadlessRender(3);
    }
  }

  
  async drawGeneratedMapOverlay() {
    const mapAssetUrl = this.assetResolver.resolveFrontendUrl(this.assetResolver.frontendConfig().map_asset_url || (this.assetSetManifest?.map_asset_url || ""));
    if (!mapAssetUrl) {
      return;
    }
    const versionSuffix = encodeURIComponent(this.assetResolver.assetSetRevision() || Date.now());
    const resolvedUrl = `${mapAssetUrl}${mapAssetUrl.includes("?") ? "&" : "?"}v=${versionSuffix}`;
    const textureKey = `generated-map:${mapAssetUrl}:${versionSuffix}`;
    await this.loadImage(textureKey, resolvedUrl);
    if (this.generatedMapKey && this.generatedMapKey !== textureKey && this.textures.exists(this.generatedMapKey)) {
      this.textures.remove(this.generatedMapKey);
    }
    this.generatedMapKey = textureKey;
    if (this.generatedMapImage) {
      this.generatedMapImage.destroy();
      this.generatedMapImage = null;
    }
    const { width, height } = this.worldDimensions;
    const image = this.add.image(width / 2, height / 2, textureKey);
    image.setDisplaySize(Math.max(1, width), Math.max(1, height));
    image.setDepth(-8);
    image.setAlpha(1);
    this.generatedMapImage = image;
  }

  async hydrateGeneratedAssets() {
    const frontendConfig = this.assetResolver.frontendConfig();
    const manifestAssets = this.assetResolver.assetsFromManifest();
    if (manifestAssets.length) {
      await this.agentManager.loadBootstrapAssetList(manifestAssets);
    } else if (frontendConfig.bootstrap_feed_path) {
      await this.agentManager.loadBootstrapAssets(this.assetResolver.resolveFrontendUrl(frontendConfig.bootstrap_feed_path));
    }
    const followedId = this.liveSessionManager.isLiveSessionMode()
      ? this.liveState.session?.claimed_agent_id || this.selectedAgentRecord?.agent_id || ""
      : this.mapGrid.map_visual?.camera?.follow_main_character;
    if (followedId) {
      const sprite = this.agentManager.agentSprites.get(followedId);
      if (sprite) {
        this.agentManager.selectAgent(followedId);
        this.cameraController.setViewMode("pov", { instant: true });
      }
    } else {
      if (this.selectedAgentRecord) {
        this.agentManager.selectAgent(this.selectedAgentRecord.agent_id);
        this.cameraController.setViewMode("pov", { instant: true });
      } else {
        this.worldRenderer.fitWorld();
      }
    }
    if (this.liveSessionManager.isLiveSessionMode() && this.captureMode === "export") {
      this.cameraController.setViewMode("atlas", { instant: true });
      const focusRoomId = this.selectedRoomId || this.homeRoomId || this.currentAgents[0]?.room_id || "";
      if (focusRoomId && this.roomNodes.has(focusRoomId)) {
        this.roomUiController.focusRoom(focusRoomId, { zoom: 1.08 });
      } else {
        this.worldRenderer.fitWorld();
      }
    }
  }

  startEventPolling() {
    if (this.liveSessionManager.isLiveSessionMode()) {
      return;
    }
    const frontendConfig = this.assetResolver.frontendConfig();
    const pollPath = frontendConfig.event_feed_path;
    const interval = frontendConfig.poll_interval_ms || 3000;
    if (!pollPath) {
      return;
    }
    this.time.addEvent({
      delay: interval,
      loop: true,
      callback: async () => {
        try {
          await this.agentManager.pollAssetFeed(this.assetResolver.resolveFrontendUrl(pollPath));
        } catch (error) {
          document.getElementById("event-status").textContent = "Asset feed unavailable";
        }
      },
    });
  }

  startRuntimePolling() {
    if (this.liveSessionManager.isLiveSessionMode()) {
      const interval = this.liveState.pollIntervalMs || this.assetResolver.frontendConfig().poll_interval_ms || 1200;
      this.time.addEvent({
        delay: interval,
        loop: true,
        callback: async () => {
          if (!this.liveState.sessionId || this.liveState.pollInFlight) {
            return;
          }
          const nowMs = Date.now();
          const wsRestBackoffMs = Math.max(4000, Number(this.liveState.realtimeFlushIntervalMs || 1000) * 4);
          const wsRecentlyHealthy =
            this.liveState.websocketTransportActive
            && (nowMs - Number(this.liveState.websocketLastMessageAt || 0)) < wsRestBackoffMs;
          const restPollStillFresh = (nowMs - Number(this.liveState.lastRestPollAt || 0)) < wsRestBackoffMs;
          if (wsRecentlyHealthy && restPollStillFresh) {
            return;
          }
          this.liveState.pollInFlight = true;
          try {
            const payload = await this.liveSessionManager.fetchLiveState(this.liveState.lastEventId || 0);
            if (!payload) {
              return;
            }
            if (Boolean(payload?.unchanged) && firstNonEmpty(payload?.mode, "") === "compact") {
              this.liveSessionManager.applyCompactLiveState(payload);
              return;
            }
            const nextFingerprint = this.liveSessionManager.liveStateFingerprint(payload);
            if (this.liveUiController.liveInputFreezeActive()) {
              this.liveSessionManager.queueFrozenLiveState(payload, nextFingerprint);
              return;
            }
            if (this.liveState.frozenPayload) {
              this.liveSessionManager.flushFrozenLiveState({ force: true });
              return;
            }
            if (nextFingerprint === this.liveState.fingerprint) {
              this.liveState.session = payload.session || this.liveState.session;
              this.liveState.state = payload;
              return;
            }
            this.liveSessionManager.applyLiveState(payload, { focusClaimedAgent: false });
          } catch (error) {
            document.getElementById("event-status").textContent = error?.message || "Live state unavailable";
          } finally {
            this.liveState.pollInFlight = false;
          }
        },
      });
      return;
    }
    const interval = this.assetResolver.frontendConfig().poll_interval_ms || 3000;
    this.time.addEvent({
      delay: interval,
      loop: true,
      callback: async () => {
        try {
          const runtimePointer = await this.loadRuntimePointer();
          if (!runtimePointer) {
            return;
          }
          const runtimeState = await this.loadRuntimeState(runtimePointer);
          if (!runtimeState) {
            return;
          }
          const nextFingerprint = this.liveSessionManager.runtimeFingerprint(runtimeState);
          if (nextFingerprint === this.runtimeFingerprint) {
            return;
          }
          this.runtimeState = runtimeState;
          this.runtimeFingerprint = nextFingerprint;
          this.currentAgents = this.assetResolver.attachAgentPortraits(safeArray(runtimeState.agents).map(normalizeAgentRecord));
          this.syncAgents(this.currentAgents);
          this.liveUiController.refreshWorldNotes();
          if (this.agentManager.selectedAgentId) {
            this.agentManager.selectAgent(this.agentManager.selectedAgentId);
          }
        } catch (error) {
          // Keep the world interactive even when the runtime pointer is absent.
        }
      },
    });
  }

  async loadRuntimePointer() {
    try {
      return await fetchJson(this.runtimePointerPath);
    } catch (error) {
      return null;
    }
  }

  async loadRuntimeState(pointer) {
    const stateUrl = pointer?.state_url;
    if (!stateUrl) {
      return null;
    }
    try {
      return await fetchJson(stateUrl);
    } catch (error) {
      return null;
    }
  }



  liveWorldCode() {
    return firstNonEmpty(this.pixelWorldCode, "");
  }



  resolvedLiveWsUrl(sessionId = this.liveState.sessionId) {
    const normalizedSessionId = firstNonEmpty(sessionId, "");
    if (!normalizedSessionId) {
      return "";
    }
    if (this.liveState.wsUrl && this.liveState.wsUrl.includes(encodeURIComponent(normalizedSessionId))) {
      return this.liveState.wsUrl;
    }
    const template = firstNonEmpty(this.liveSessionManager.liveSessionUrls().wsTemplate, "");
    if (!template) {
      return "";
    }
    return resolveWebSocketUrl(formatTemplate(template, { session_id: encodeURIComponent(normalizedSessionId) }));
  }







































































  componentLibrary() {
    return this.worldConfig?.pixel_asset_pipeline?.map_generation?.component_library || {};
  }







  loadImage(textureKey, imageUrl) {
    if (this.textures.exists(textureKey)) {
      return Promise.resolve();
    }
    return new Promise((resolve, reject) => {
      this.load.image(textureKey, imageUrl);
      this.load.once(`filecomplete-image-${textureKey}`, () => resolve());
      this.load.once("loaderror", (file) => {
        if (file.key === textureKey) {
          reject(new Error(`Failed to load image ${textureKey}`));
        }
      });
      this.load.start();
    });
  }

  agentDisplayScaleFor() {
    const mapVisual = this.mapGrid?.map_visual || {};
    const targetSpriteSize = Number(mapVisual.agent_sprite_size || 32);
    return Phaser.Math.Clamp(targetSpriteSize / 32, 0.95, 5.2);
  }

  createUiBridge() {
    const modalRoot = document.getElementById("image-modal");
    const modalImage = document.getElementById("image-modal-image");
    const modalCaption = document.getElementById("image-modal-caption");
    const closeButton = document.getElementById("image-modal-close");

    const closeModal = () => {
      modalRoot.classList.add("hidden");
      modalRoot.setAttribute("aria-hidden", "true");
      modalImage.removeAttribute("src");
      modalCaption.textContent = "";
    };

    const openImageModal = (card) => {
      modalImage.src = card.image_url;
      modalImage.alt = card.label;
      modalCaption.textContent = card.source_path
        ? `${card.label}  |  ${card.source_path}`
        : card.label;
      modalRoot.classList.remove("hidden");
      modalRoot.setAttribute("aria-hidden", "false");
    };

    closeButton.addEventListener("click", closeModal);
    modalRoot.addEventListener("click", (event) => {
      if (event.target === modalRoot) {
        closeModal();
      }
    });
    window.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !modalRoot.classList.contains("hidden")) {
        closeModal();
      }
    });
    this.openImageModal = openImageModal;

    const scene = this;
    const renderSelectedAgent = (agent, { focusSelected = true } = {}) => {
      scene.selectedAgentRecord = agent;
      scene.selectedRoomId = agent.room_id || scene.selectedRoomId;
      if (scene.liveSessionManager.isLiveSessionMode()) {
        scene.liveUiController.refreshLiveUi();
      } else {
        scene.liveUiController.refreshImmersiveHud();
      }
      scene.worldRenderer.applyRoomHighlight();
      scene.cameraController.applyPresenceFocus();
      if (scene.viewMode === "pov" && focusSelected) {
        scene.cameraController.focusSelectedAgent({ instant: false });
      }
    };
    return {
      setSelectedAgent(agent) {
        const controller = scene.controllerAgentRecord();
        if (controller && agent.agent_id !== controller.agent_id) {
          scene.setDialogueTarget(agent.agent_id);
          scene.selectedRoomId = agent.room_id || scene.selectedRoomId;
          scene.agentManager.selectedAgentId = controller.agent_id;
          scene.agentManager.refreshSelectionVisuals();
          if (scene.viewMode === "atlas" && agent.room_id) {
            scene.focusRoom(agent.room_id, { zoom: 0.82 });
          } else {
            renderSelectedAgent(controller, { focusSelected: false });
          }
          return;
        }
        renderSelectedAgent(controller || agent);
      },
      pushAssetEvent(eventPayload) {
        document.getElementById("event-status").textContent = `Loaded ${eventPayload.display_name}`;
        const feed = document.getElementById("asset-feed");
        if (!feed) {
          return;
        }
        const card = document.createElement("div");
        card.className = "feed-item";
        card.innerHTML = `
          <strong>${eventPayload.display_name}</strong>
          <div>Revision: <code>${eventPayload.revision}</code></div>
          <div>Default: ${eventPayload.default_animation}</div>
        `;
        feed.prepend(card);
        while (feed.children.length > 8) {
          feed.removeChild(feed.lastChild);
        }
      },
    };
  }

  ensureLiveErrorOverlay() {
    if (this.liveErrorOverlay?.root?.isConnected !== false && this.liveErrorOverlay?.root) {
      return this.liveErrorOverlay;
    }
    const root = document.createElement("div");
    root.dataset.liveErrorOverlay = "true";
    root.setAttribute("aria-hidden", "true");
    Object.assign(root.style, {
      position: "fixed",
      inset: "0",
      display: "none",
      alignItems: "center",
      justifyContent: "center",
      padding: "24px",
      background: "rgba(28, 5, 8, 0.82)",
      backdropFilter: "blur(6px)",
      zIndex: "99999",
    });

    const panel = document.createElement("section");
    Object.assign(panel.style, {
      width: "min(760px, 92vw)",
      maxHeight: "80vh",
      overflow: "auto",
      padding: "24px 26px",
      borderRadius: "18px",
      border: "3px solid #ff6d5e",
      background: "linear-gradient(180deg, #461014 0%, #23070a 100%)",
      boxShadow: "0 26px 80px rgba(0, 0, 0, 0.45)",
      color: "#fff2ef",
      fontFamily: "\"Trebuchet MS\", \"Segoe UI\", sans-serif",
    });

    const badge = document.createElement("div");
    badge.textContent = "LIVE FAILURE";
    Object.assign(badge.style, {
      display: "inline-block",
      marginBottom: "12px",
      padding: "6px 10px",
      borderRadius: "999px",
      background: "#ffcf66",
      color: "#3d1800",
      fontSize: "12px",
      fontWeight: "800",
      letterSpacing: "0.08em",
    });

    const title = document.createElement("h2");
    Object.assign(title.style, {
      margin: "0 0 10px 0",
      fontSize: "34px",
      lineHeight: "1.02",
      letterSpacing: "0.04em",
    });

    const body = document.createElement("pre");
    Object.assign(body.style, {
      margin: "0",
      whiteSpace: "pre-wrap",
      wordBreak: "break-word",
      fontFamily: "\"SFMono-Regular\", Consolas, monospace",
      fontSize: "15px",
      lineHeight: "1.5",
      color: "#ffd8d2",
    });

    const actions = document.createElement("div");
    Object.assign(actions.style, {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      gap: "12px",
      marginTop: "18px",
    });

    const hint = document.createElement("div");
    hint.textContent = "The live UI is still open, but this action needs the AI Studio backend to recover before replies can continue.";
    Object.assign(hint.style, {
      flex: "1",
      fontSize: "13px",
      lineHeight: "1.45",
      color: "#ffb4aa",
    });

    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.textContent = "Dismiss";
    Object.assign(closeButton.style, {
      border: "0",
      borderRadius: "999px",
      padding: "10px 16px",
      fontSize: "14px",
      fontWeight: "700",
      background: "#fff2ef",
      color: "#4b0d12",
      cursor: "pointer",
    });

    const hideOverlay = () => {
      root.style.display = "none";
      root.setAttribute("aria-hidden", "true");
    };
    closeButton.addEventListener("click", hideOverlay);
    root.addEventListener("click", (e) => { if (e.target === root) hideOverlay(); });
    actions.append(hint, closeButton);
    panel.append(badge, title, body, actions);
    root.appendChild(panel);
    document.body.appendChild(root);
    this.liveErrorOverlay = { root, badge, title, body };
    return this.liveErrorOverlay;
  }
}
