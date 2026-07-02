import re

mapping = {
    # LiveSessionManager
    "connectLiveWebSocket": "liveSessionManager.connectLiveWebSocket",
    "disconnectLiveWebSocket": "liveSessionManager.disconnectLiveWebSocket",
    "scheduleLiveWsReconnect": "liveSessionManager.scheduleLiveWsReconnect",
    "startLiveWsHeartbeat": "liveSessionManager.startLiveWsHeartbeat",
    "stopLiveWsHeartbeat": "liveSessionManager.stopLiveWsHeartbeat",
    "sendLiveWsMessage": "liveSessionManager.sendLiveWsMessage",
    "handleLiveWsMessage": "liveSessionManager.handleLiveWsMessage",
    "configureLiveRealtime": "liveSessionManager.configureLiveRealtime",
    "liveRealtimeReady": "liveSessionManager.liveRealtimeReady",
    "applyLiveState": "liveSessionManager.applyLiveState",
    "applyCompactLiveState": "liveSessionManager.applyCompactLiveState",
    "applyLiveWsStateDelta": "liveSessionManager.applyLiveWsStateDelta",
    "upsertLiveAgentDelta": "liveSessionManager.upsertLiveAgentDelta",
    "liveStateFingerprint": "liveSessionManager.liveStateFingerprint",
    "runtimeFingerprint": "liveSessionManager.runtimeFingerprint",
    "liveSessionUrls": "liveSessionManager.liveSessionUrls",
    "liveReadyAgentSet": "liveSessionManager.liveReadyAgentSet",
    "liveAvailableRoutes": "liveSessionManager.liveAvailableRoutes",
    "filterLiveReadyAgents": "liveSessionManager.filterLiveReadyAgents",
    "flushFrozenLiveState": "liveSessionManager.flushFrozenLiveState",
    "queueFrozenLiveState": "liveSessionManager.queueFrozenLiveState",
    "liveSignature": "liveSessionManager.liveSignature",
    "isLiveSessionMode": "liveSessionManager.isLiveSessionMode",

    # LiveMovementController
    "submitPendingLiveMove": "liveMovementController.submitPendingLiveMove",
    "queuePendingLiveMove": "liveMovementController.queuePendingLiveMove",
    "clearPendingLiveMove": "liveMovementController.clearPendingLiveMove",
    "refreshPendingLiveMoveState": "liveMovementController.refreshPendingLiveMoveState",
    "applyLiveMovePrediction": "liveMovementController.applyLiveMovePrediction",
    "restorePredictedLiveState": "liveMovementController.restorePredictedLiveState",
    "replayQueuedLiveMovePredictions": "liveMovementController.replayQueuedLiveMovePredictions",
    "reconcilePendingLiveMove": "liveMovementController.reconcilePendingLiveMove",
    "reconcilePendingLiveMessages": "liveMovementController.reconcilePendingLiveMessages",
    "reconcilePendingLiveTradeQuotes": "liveMovementController.reconcilePendingLiveTradeQuotes",
    "reconcilePendingLiveTaskAssignments": "liveMovementController.reconcilePendingLiveTaskAssignments",
    "liveMovePacingConfig": "liveMovementController.liveMovePacingConfig",
    "canQueueLiveMove": "liveMovementController.canQueueLiveMove",
    "effectiveLiveStepCooldown": "liveMovementController.effectiveLiveStepCooldown",
    "queuePendingLiveMessage": "liveMovementController.queuePendingLiveMessage",
    "queuePendingLiveTradeQuote": "liveMovementController.queuePendingLiveTradeQuote",
    "queuePendingLiveTaskAssignment": "liveMovementController.queuePendingLiveTaskAssignment",
    "removePendingLiveMessage": "liveMovementController.removePendingLiveMessage",
    "removePendingLiveTradeQuote": "liveMovementController.removePendingLiveTradeQuote",
    "removePendingLiveTaskAssignment": "liveMovementController.removePendingLiveTaskAssignment",
    "clearPendingLiveMoveByInputSeq": "liveMovementController.clearPendingLiveMoveByInputSeq",
    "clearMovementInputs": "liveMovementController.clearMovementInputs",

    # LiveUiController
    "refreshLiveUi": "liveUiController.refreshLiveUi",
    "refreshImmersiveHud": "liveUiController.refreshImmersiveHud",
    "renderAgentSelector": "liveUiController.renderAgentSelector",
    "renderSelectedTargetBubble": "liveUiController.renderSelectedTargetBubble",
    "syncLiveComposerElements": "liveUiController.syncLiveComposerElements",
    "armLiveComposerFocusGuard": "liveUiController.armLiveComposerFocusGuard",
    "showSpeechBubble": "liveUiController.showSpeechBubble",
    "surfaceLiveEventBubbles": "liveUiController.surfaceLiveEventBubbles",
    "showLiveErrorOverlay": "liveUiController.showLiveErrorOverlay",
    "hideLiveErrorOverlay": "liveUiController.hideLiveErrorOverlay",
    "refreshWorldNotes": "liveUiController.refreshWorldNotes",
    "updateStreamingBubble": "liveUiController.updateStreamingBubble",
    "handleAiThinking": "liveUiController.handleAiThinking",
    "handleAiStreamChunk": "liveUiController.handleAiStreamChunk",
    "focusPrimaryLiveComposer": "liveUiController.focusPrimaryLiveComposer",
    "freezeLiveComposerPanels": "liveUiController.freezeLiveComposerPanels",
    "handleLiveComposerBlur": "liveUiController.handleLiveComposerBlur",
    "captureLiveComposerFocus": "liveUiController.captureLiveComposerFocus",
    "submitPrimaryLiveComposer": "liveUiController.submitPrimaryLiveComposer",
    "beginLiveComposerFreeze": "liveUiController.beginLiveComposerFreeze",
    "liveInputFreezeActive": "liveUiController.liveInputFreezeActive",
    "targetBubbleAgent": "liveUiController.targetBubbleAgent",
    "pendingLiveSpeechEntries": "liveUiController.pendingLiveSpeechEntries",

    # PovController
    "initializeLocalPovModules": "povController.initializeLocalPovModules",
    "localPovEnabled": "povController.localPovEnabled",
    "protagonistAgentId": "povController.protagonistAgentId",
    "bindLocalMovementKeys": "povController.bindLocalMovementKeys",
    "attemptLocalMove": "povController.attemptLocalMove",
    "refreshLocalInteractionPanels": "povController.refreshLocalInteractionPanels",
    "logLocalAction": "povController.logLocalAction",
    "ensureProtagonistWalkableSpawn": "povController.ensureProtagonistWalkableSpawn",
    "povConfig": "povController.povConfig",
    "inventoryExchangeConfig": "povController.inventoryExchangeConfig",
    "negotiationConfig": "povController.negotiationConfig",
    "presentAgentExchange": "povController.presentAgentExchange",
    "activeAgentRecords": "povController.activeAgentRecords",

    # ExportRenderer
    "isExportCaptureMode": "exportRenderer.isExportCaptureMode",
    "primeExportFallbackAssets": "exportRenderer.primeExportFallbackAssets",
    "ensureExportFallbackCanvas": "exportRenderer.ensureExportFallbackCanvas",
    "scheduleExportFallbackRender": "exportRenderer.scheduleExportFallbackRender",
    "kickHeadlessRender": "exportRenderer.kickHeadlessRender",
}

with open("frontend/src/WorldScene.js", "r") as f:
    content = f.read()

for old, new in mapping.items():
    content = re.sub(rf"this\.#{old}\b", f"this.{new}", content)

with open("frontend/src/WorldScene.js", "w") as f:
    f.write(content)
print("Replaced all extracted method calls.")
