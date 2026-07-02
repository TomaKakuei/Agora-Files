const fs = require('fs');

const classFile = fs.readFileSync('src/WorldScene.js', 'utf8');
const lines = classFile.split('\n');

const modules = {
  LiveSessionManager: {
    methods: [
      '#createLiveSession', '#releaseLiveSession', '#fetchLiveState', '#submitLiveAction',
      '#connectLiveWebSocket', '#disconnectLiveWebSocket', '#scheduleLiveWsReconnect',
      '#startLiveWsHeartbeat', '#stopLiveWsHeartbeat', '#sendLiveWsMessage',
      '#handleLiveWsMessage', '#configureLiveRealtime', '#liveRealtimeReady',
      '#applyLiveState', '#applyCompactLiveState', '#applyLiveWsStateDelta',
      '#upsertLiveAgentDelta', '#liveStateFingerprint', '#runtimeFingerprint',
      '#liveSessionUrls', '#liveReadyAgentSet', '#liveAvailableRoutes',
      '#filterLiveReadyAgents', '#flushFrozenLiveState', '#queueFrozenLiveState',
      '#liveSignature', '#isLiveSessionMode'
    ],
    imports: 'import { firstNonEmpty, safeArray, liveEventPayload, newClientActionId } from "./utils.js";\n\n'
  },
  LiveMovementController: {
    methods: [
      '#submitPendingLiveMove', '#queuePendingLiveMove', '#clearPendingLiveMove',
      '#refreshPendingLiveMoveState', '#applyLiveMovePrediction', '#restorePredictedLiveState',
      '#replayQueuedLiveMovePredictions', '#reconcilePendingLiveMove', '#reconcilePendingLiveMessages',
      '#reconcilePendingLiveTradeQuotes', '#reconcilePendingLiveTaskAssignments',
      '#liveMovePacingConfig', '#canQueueLiveMove', '#effectiveLiveStepCooldown',
      '#queuePendingLiveMessage', '#queuePendingLiveTradeQuote', '#queuePendingLiveTaskAssignment',
      '#removePendingLiveMessage', '#removePendingLiveTradeQuote', '#removePendingLiveTaskAssignment',
      '#clearPendingLiveMoveByInputSeq', '#clearMovementInputs'
    ],
    imports: 'import { firstNonEmpty, safeArray, newClientActionId } from "./utils.js";\n\n'
  },
  LiveUiController: {
    methods: [
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
    ],
    imports: 'import { firstNonEmpty, safeArray, escapeHtml, agentInitials } from "./utils.js";\n\n'
  }
};

let currentMethod = null;
let currentMethodLines = [];
let braceCount = 0;
let inMethod = false;

const parsedMethods = new Map();

for (let i = 0; i < lines.length; i++) {
  const line = lines[i];
  
  if (!inMethod) {
    const match = line.match(/^  (async )?([#a-zA-Z0-9_]+)\s*\(/);
    if (match && !['if', 'for'].includes(match[2])) {
      inMethod = true;
      currentMethod = match[2];
      currentMethodLines = [line];
      braceCount = (line.match(/\{/g) || []).length - (line.match(/\}/g) || []).length;
      
      if (braceCount === 0 && line.includes('{') && line.includes('}')) {
        parsedMethods.set(currentMethod, [...currentMethodLines]);
        inMethod = false;
        currentMethod = null;
      }
    }
  } else {
    currentMethodLines.push(line);
    braceCount += (line.match(/\{/g) || []).length - (line.match(/\}/g) || []).length;
    
    if (braceCount <= 0) {
      parsedMethods.set(currentMethod, [...currentMethodLines]);
      inMethod = false;
      currentMethod = null;
    }
  }
}

for (const [modName, modConfig] of Object.entries(modules)) {
  const out = [modConfig.imports];
  out.push(`export class ${modName} {\n  constructor(worldScene) {\n    this.scene = worldScene;\n  }\n\n`);
  
  for (const m of modConfig.methods) {
    const methodLines = parsedMethods.get(m);
    if (methodLines) {
      for (let i = 0; i < methodLines.length; i++) {
        let line = methodLines[i];
        line = line.replace(/this\.#/g, 'this.');
        if (line.trim().startsWith('#')) {
          line = line.replace('#', '');
        }
        out.push(line + '\n');
      }
      out.push('\n');
    }
  }
  out.push('}\n');
  fs.writeFileSync(`src/${modName}.js`, out.join(''));
  console.log(`Created ${modName}.js`);
}
