const fs = require('fs');

const classFile = fs.readFileSync('src/WorldScene.js', 'utf8');
const lines = classFile.split('\n');

const modulesMethods = new Set([
  'resolveAssetUrl', '#resolveFrontendUrl', '#frontendConfig', '#assetsFromManifest', 
  '#assetSetRevision', '#frontendUrlForLocalAssetPath', '#refreshAgentPortraitLookup', 
  '#attachAgentPortraits', '#portraitCardFromManifestRecord', '#applyAgentPortraitsToState',
  '#drawWorld', '#drawGeneratedMapOverlay', '#fitWorld', '#buildRoomTileIndex', 
  '#buildRoomCollisionIndex', '#applyRoomHighlight', '#roomComponentPlacements', 
  '#componentBlocksMovement', '#movementCollisionConfig', '#isBlockedTile', 
  '#tileHasCollisionKind', '#renderGroundItems', '#renderRoomComponents', 
  '#directionAliasMap', 'worldToCanvasY',
  '#installCameraControls', '#setViewMode', '#applyPresenceFocus', 
  '#focusSelectedAgent', '#previewMoveForAgent',
  '#isExportCaptureMode', '#primeExportFallbackAssets', '#ensureExportFallbackCanvas', 
  '#scheduleExportFallbackRender', '#renderExportFallbackCanvas', '#kickHeadlessRender',
  '#loadExportMapImage', '#loadExportFrame',
  '#initializeLocalPovModules', '#localPovEnabled', '#protagonistAgentId', 
  '#bindLocalMovementKeys', '#attemptLocalMove', '#refreshLocalInteractionPanels', 
  '#logLocalAction', '#ensureProtagonistWalkableSpawn', '#povConfig', 
  '#inventoryExchangeConfig', '#negotiationConfig', '#presentAgentExchange',
  '#handleLocalPlayerDeath', '#submitLocalTradeQuote', '#applyLocalDeathSnapshot',
  '#localTraderAgents', '#inventoryTotalMass', '#activeAgentRecords',
  '#createLiveSession', '#releaseLiveSession', '#fetchLiveState', '#submitLiveAction',
  '#connectLiveWebSocket', '#disconnectLiveWebSocket', '#scheduleLiveWsReconnect',
  '#startLiveWsHeartbeat', '#stopLiveWsHeartbeat', '#sendLiveWsMessage',
  '#handleLiveWsMessage', '#configureLiveRealtime', '#liveRealtimeReady',
  '#applyLiveState', '#applyCompactLiveState', '#applyLiveWsStateDelta',
  '#upsertLiveAgentDelta', '#liveStateFingerprint', '#runtimeFingerprint',
  '#liveSessionUrls', '#liveReadyAgentSet', '#liveAvailableRoutes',
  '#filterLiveReadyAgents', '#flushFrozenLiveState', '#queueFrozenLiveState',
  '#liveSignature', '#isLiveSessionMode',
  '#submitPendingLiveMove', '#queuePendingLiveMove', '#clearPendingLiveMove',
  '#refreshPendingLiveMoveState', '#applyLiveMovePrediction', '#restorePredictedLiveState',
  '#replayQueuedLiveMovePredictions', '#reconcilePendingLiveMove', '#reconcilePendingLiveMessages',
  '#reconcilePendingLiveTradeQuotes', '#reconcilePendingLiveTaskAssignments',
  '#liveMovePacingConfig', '#canQueueLiveMove', '#effectiveLiveStepCooldown',
  '#queuePendingLiveMessage', '#queuePendingLiveTradeQuote', '#queuePendingLiveTaskAssignment',
  '#removePendingLiveMessage', '#removePendingLiveTradeQuote', '#removePendingLiveTaskAssignment',
  '#clearPendingLiveMoveByInputSeq', '#clearMovementInputs',
  '#refreshLiveUi', '#refreshImmersiveHud', '#renderAgentSelector',
  '#renderSelectedTargetBubble', '#renderLiveMovementPanel', '#renderLiveTradePanel',
  '#renderLiveTaskPanel', '#renderLiveDialoguePanel', '#renderLiveEventLog',
  '#syncLiveComposerElements', '#armLiveComposerFocusGuard', '#showSpeechBubble',
  '#surfaceLiveEventBubbles', '#showLiveErrorOverlay', '#hideLiveErrorOverlay',
  '#refreshWorldNotes', '#updateStreamingBubble', '#handleAiThinking',
  '#handleAiStreamChunk', '#focusPrimaryLiveComposer', '#freezeLiveComposerPanels',
  '#handleLiveComposerBlur', '#captureLiveComposerFocus', '#submitPrimaryLiveComposer',
  '#beginLiveComposerFreeze', '#liveInputFreezeActive', '#targetBubbleAgent',
  '#pendingLiveSpeechEntries'
]);

let out = [];
let skipMode = false;
let braceCount = 0;

// Add imports
out.push('import { Phaser } from "./utils.js";');
out.push('import { AgentManager } from "./AgentManager.js";');
out.push('import { AssetResolver } from "./AssetResolver.js";');
out.push('import { WorldRenderer } from "./WorldRenderer.js";');
out.push('import { CameraController } from "./CameraController.js";');
out.push('import { LiveSessionManager } from "./LiveSessionManager.js";');
out.push('import { LiveMovementController } from "./LiveMovementController.js";');
out.push('import { LiveUiController } from "./LiveUiController.js";');
out.push('import { PovController } from "./PovController.js";');
out.push('import { ExportRenderer } from "./ExportRenderer.js";');
out.push('import { parseJsonObject, captureModeFromLocation, liveSessionIdFromLocation, runtimeModeFromLocation, selectedPixelWorldCodeFromLocation, persistLiveSessionFromLocation, DEFAULT_RUNTIME_POINTER_PATH } from "./utils.js";');
out.push('');

for (let i = 0; i < lines.length; i++) {
  const line = lines[i];
  
  if (!skipMode) {
    if (i < 599) continue; // Skip utility functions at the top, they are in utils.js now
    
    const match = line.match(/^  (async )?([#a-zA-Z0-9_]+)\s*\(/);
    if (match && modulesMethods.has(match[2])) {
      skipMode = true;
      braceCount = (line.match(/\{/g) || []).length - (line.match(/\}/g) || []).length;
      if (braceCount === 0 && line.includes('{') && line.includes('}')) {
        skipMode = false; // single line method
      }
    } else {
      out.push(line);
    }
  } else {
    braceCount += (line.match(/\{/g) || []).length - (line.match(/\}/g) || []).length;
    if (braceCount <= 0) {
      skipMode = false;
    }
  }
}

// Modify constructor
const fullText = out.join('\n');
const modifiedText = fullText.replace(
  /constructor\(\) \{[\s\S]*?this\.windowKeyUpHandler = null;\n  \}/,
  `constructor() {
    super("world");
    this.assetResolver = new AssetResolver(this);
    this.worldRenderer = new WorldRenderer(this);
    this.cameraController = new CameraController(this);
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
  }`
);

fs.writeFileSync('src/WorldScene_new.js', modifiedText);
console.log('Reduced WorldScene.js written to WorldScene_new.js');
