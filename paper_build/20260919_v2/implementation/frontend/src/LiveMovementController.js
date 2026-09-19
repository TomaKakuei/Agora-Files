import { firstNonEmpty, safeArray, newClientActionId, liveEventPayload, Phaser } from "./utils.js";

export class LiveMovementController {
  constructor(worldScene) {
    this.scene = worldScene;
                      return new Proxy(this, {
      get(target, prop) {
        if (prop in target) return target[prop];
        if (prop in worldScene) return typeof worldScene[prop] === 'function' ? worldScene[prop].bind(worldScene) : worldScene[prop];
        const controllers = [
            worldScene.liveSessionManager,
            worldScene.liveUiController,
            worldScene.liveMovementController,
            worldScene.povController,
            worldScene.cameraController,
            worldScene.exportRenderer,
            worldScene.worldRenderer,
            worldScene.assetResolver,
            worldScene.liveComposerUi,
            worldScene.actionController,
            worldScene.gridPathingController,
            worldScene.itemController,
            worldScene.inputController,
            worldScene.roomUiController,
            worldScene.agentStateController
        ];
        for (const ctrl of controllers) {
            if (ctrl && prop in ctrl) {
                return typeof ctrl[prop] === 'function' ? ctrl[prop].bind(ctrl) : ctrl[prop];
            }
        }
        return undefined;
      },
      set(target, prop, value) {
        if (prop in target) {
            target[prop] = value;
            return true;
        }
        if (prop in worldScene) {
            worldScene[prop] = value;
            return true;
        }
        const controllers = [
            worldScene.liveSessionManager,
            worldScene.liveUiController,
            worldScene.liveMovementController,
            worldScene.povController,
            worldScene.cameraController,
            worldScene.exportRenderer,
            worldScene.worldRenderer,
            worldScene.assetResolver,
            worldScene.liveComposerUi,
            worldScene.actionController,
            worldScene.gridPathingController,
            worldScene.itemController,
            worldScene.inputController,
            worldScene.roomUiController,
            worldScene.agentStateController
        ];
        for (const ctrl of controllers) {
            if (ctrl && prop in ctrl) {
                ctrl[prop] = value;
                return true;
            }
        }
        target[prop] = value;
        return true;
      }
    });
}

  submitPendingLiveMove(direction, actionText) {
    const normalizedDirection = firstNonEmpty(direction, "");
    if (!normalizedDirection || !this.canQueueLiveMove(normalizedDirection)) {
      return false;
    }
    if (this.liveRealtimeReady()) {
      const inputSeq = Number(this.liveState.nextInputSeq || 0) + 1;
      this.liveState.nextInputSeq = inputSeq;
      const clientActionId = `ws_move_${inputSeq}`;
      this.queuePendingLiveMove({
        clientActionId,
        direction: normalizedDirection,
        actionText: firstNonEmpty(actionText, `Move ${normalizedDirection}`),
        inputSeq,
      });
      const predicted = this.applyLiveMovePrediction(normalizedDirection, { sync: true, animateMovement: false });
      const queued = this.sendLiveWsMessage({
        type: "input",
        direction: normalizedDirection,
        input_seq: inputSeq,
        client_time_ms: Date.now(),
      });
      if (!queued) {
        this.clearPendingLiveMove(clientActionId);
        if (predicted) {
          this.restorePredictedLiveState();
        }
        return false;
      }
      return true;
    }
    const clientActionId = newClientActionId();
    this.queuePendingLiveMove({
      clientActionId,
      direction: normalizedDirection,
      actionText: firstNonEmpty(actionText, `Move ${normalizedDirection}`),
    });
    this.applyLiveMovePrediction(normalizedDirection);
    void this.submitLiveAction({
      action_type: "move",
      client_action_id: clientActionId,
      direction: normalizedDirection,
      action_text: firstNonEmpty(actionText, `${this.selectedAgentRecord?.display_name || "agent"} moves ${normalizedDirection}.`),
    }).catch((error) => {
      this.clearPendingLiveMove(clientActionId);
      this.restorePredictedLiveState();
      document.getElementById("event-status").textContent = error?.message || "Live move failed";
    });
    return true;
  }

  queuePendingLiveMove(entry) {
    const clientActionId = firstNonEmpty(entry?.clientActionId, "");
    if (!clientActionId) {
      return;
    }
    const nextEntry = {
      clientActionId,
      direction: firstNonEmpty(entry?.direction, ""),
      actionText: firstNonEmpty(entry?.actionText, ""),
      inputSeq: Math.max(0, Number(entry?.inputSeq || 0)),
      createdAt: Date.now(),
    };
    this.liveState.pendingMoves = [
      ...safeArray(this.liveState.pendingMoves).filter((item) => item?.clientActionId !== clientActionId),
      nextEntry,
    ].slice(-this.liveMovePacingConfig().maxBufferedMoves);
    this.refreshPendingLiveMoveState();
  }

  clearPendingLiveMove(clientActionId = "") {
    const normalized = firstNonEmpty(clientActionId, "");
    if (!normalized) {
      this.liveState.pendingMoves = safeArray(this.liveState.pendingMoves).slice(1);
    } else {
      this.liveState.pendingMoves = safeArray(this.liveState.pendingMoves)
        .filter((item) => item?.clientActionId !== normalized);
    }
    this.refreshPendingLiveMoveState();
  }

  refreshPendingLiveMoveState() {
    const queue = safeArray(this.liveState.pendingMoves)
      .filter((entry) => firstNonEmpty(entry?.clientActionId, ""));
    this.liveState.pendingMoves = queue;
    this.liveState.pendingMove = queue[0] || null;
    this.liveState.moveInFlight = queue.length > 0;
  }

  applyLiveMovePrediction(direction, { sync = true, animateMovement = true } = {}) {
    const claimedAgentId = firstNonEmpty(this.liveState.session?.claimed_agent_id, "");
    if (!claimedAgentId) {
      return false;
    }
    const claimedAgent = this.currentAgents.find((agent) => agent.agent_id === claimedAgentId);
    const preview = this.previewMoveForAgent(claimedAgent, direction, { allowPeerOverlap: true });
    if (!preview?.ok || !claimedAgent) {
      return false;
    }
    claimedAgent.coordinates = {
      ...(claimedAgent.coordinates || {}),
      x: preview.nextX,
      y: preview.nextY,
      z: preview.nextZ,
    };
    claimedAgent.room_id = preview.nextRoomId;
    if (this.selectedAgentRecord?.agent_id === claimedAgentId) {
      this.selectedAgentRecord = claimedAgent;
    }
    this.selectedRoomId = preview.nextRoomId || this.selectedRoomId;
    this.liveState.lastClaimedAgentRoomId = preview.nextRoomId || this.liveState.lastClaimedAgentRoomId;
    claimedAgent.facing = firstNonEmpty(direction, claimedAgent.facing, "down");
    claimedAgent.animation = `walk_${firstNonEmpty(direction, "down")}`;
    if (sync) {
      this.playMovementAnimation(claimedAgentId, direction);
      this.syncAgents(this.currentAgents, {
        preserveCoordinates: true,
        animateMovement,
        refreshUi: false,
        movementDurationMs: animateMovement ? this.liveState.realtimeTickIntervalMs : 0,
      });
    }
    return true;
  }

  restorePredictedLiveState() {
    if (!this.isLiveSessionMode() || !this.liveState.state) {
      return;
    }
    this.applyLiveState(this.liveState.state, {
      focusClaimedAgent: false,
      allowTypingFreeze: false,
    });
  }

  replayQueuedLiveMovePredictions() {
    for (const pendingMove of safeArray(this.liveState.pendingMoves)) {
      if (!this.applyLiveMovePrediction(pendingMove?.direction, { sync: false, animateMovement: false })) {
        break;
      }
    }
  }

  reconcilePendingLiveMove(events = []) {
    const pendingIds = new Set(
      safeArray(this.liveState.pendingMoves)
        .map((entry) => firstNonEmpty(entry?.clientActionId, ""))
        .filter(Boolean),
    );
    if (!pendingIds.size) {
      return;
    }
    const completedIds = new Set();
    safeArray(events).forEach((event) => {
      if (firstNonEmpty(event?.event_type, "") !== "human_action") {
        return;
      }
      const payload = liveEventPayload(event);
      const clientActionId = firstNonEmpty(payload?.client_action_id, "");
      if (clientActionId && pendingIds.has(clientActionId)) {
        completedIds.add(clientActionId);
      }
    });
    if (!completedIds.size) {
      return;
    }
    this.liveState.pendingMoves = safeArray(this.liveState.pendingMoves)
      .filter((entry) => !completedIds.has(firstNonEmpty(entry?.clientActionId, "")));
    this.refreshPendingLiveMoveState();
  }

  reconcilePendingLiveMessages(events = []) {
    const completedIds = new Set();
    safeArray(events).forEach((event) => {
      const payload = liveEventPayload(event);
      const clientActionId = firstNonEmpty(payload?.client_action_id, "");
      if (!clientActionId) {
        return;
      }
      const eventType = firstNonEmpty(event?.event_type, "");
      const messageStatus = firstNonEmpty(payload?.message_status, "");
      if (eventType === "agent_response" || ["completed", "cancelled"].includes(messageStatus)) {
        completedIds.add(clientActionId);
      }
    });
    if (!completedIds.size) {
      return;
    }
    this.liveState.pendingMessages = safeArray(this.liveState.pendingMessages)
      .filter((item) => !completedIds.has(firstNonEmpty(item?.clientActionId, "")));
  }

  reconcilePendingLiveTradeQuotes(events = [], offers = []) {
    const completedIds = new Set();
    safeArray(events).forEach((event) => {
      if (firstNonEmpty(event?.event_type, "") !== "agent_response") {
        return;
      }
      const payload = liveEventPayload(event);
      if (firstNonEmpty(payload?.kind, "") !== "trade_quote") {
        return;
      }
      const clientActionId = firstNonEmpty(payload?.client_action_id, "");
      if (clientActionId) {
        completedIds.add(clientActionId);
      }
    });
    safeArray(offers).forEach((offer) => {
      const clientActionId = firstNonEmpty(offer?.client_action_id, "");
      if (!clientActionId) {
        return;
      }
      const status = firstNonEmpty(offer?.status, "");
      if (["quoted", "accepted_pending_delivery", "completed", "rejected", "failed_unavailable", "failed_insufficient_funds"].includes(status)) {
        completedIds.add(clientActionId);
      }
    });
    if (!completedIds.size) {
      return;
    }
    this.liveState.pendingTradeQuotes = safeArray(this.liveState.pendingTradeQuotes)
      .filter((item) => !completedIds.has(firstNonEmpty(item?.clientActionId, "")));
  }

  reconcilePendingLiveTaskAssignments(events = [], agents = []) {
    const completedIds = new Set();
    safeArray(events).forEach((event) => {
      if (firstNonEmpty(event?.event_type, "") !== "agent_response") {
        return;
      }
      const payload = liveEventPayload(event);
      if (firstNonEmpty(payload?.kind, "") !== "task_assign") {
        return;
      }
      const clientActionId = firstNonEmpty(payload?.client_action_id, "");
      if (clientActionId) {
        completedIds.add(clientActionId);
      }
    });
    safeArray(agents).forEach((agent) => {
      const task = agent?.active_task;
      if (!task || typeof task !== "object") {
        return;
      }
      const requestedByAgentId = firstNonEmpty(task?.requested_by_agent_id, "");
      safeArray(this.liveState.pendingTaskAssignments).forEach((pending) => {
        if (
          firstNonEmpty(pending?.targetAgentId, "") === firstNonEmpty(agent?.agent_id, "")
          && firstNonEmpty(task?.kind, "") === firstNonEmpty(pending?.taskKind, "")
          && requestedByAgentId === firstNonEmpty(this.liveState.session?.claimed_agent_id, "")
          && (!firstNonEmpty(pending?.destinationRoomId, "") || firstNonEmpty(task?.target_room_id, "") === firstNonEmpty(pending?.destinationRoomId, ""))
        ) {
          completedIds.add(firstNonEmpty(pending?.clientActionId, ""));
        }
      });
    });
    if (!completedIds.size) {
      return;
    }
    this.liveState.pendingTaskAssignments = safeArray(this.liveState.pendingTaskAssignments)
      .filter((item) => !completedIds.has(firstNonEmpty(item?.clientActionId, "")));
  }

  liveMovePacingConfig(movementConfig = this.povConfig()?.movement || {}) {
    const configuredCooldownMs = Math.max(60, Number(movementConfig.step_cooldown_ms || 180));
    const realtimeInputPauseMs = Math.max(100, Number(movementConfig.live_input_pause_ms || 100));
    const realtimeBaseCooldownMs = (this.liveRealtimeReady() || this.liveState.websocketConnecting)
      ? Math.max(100, Number(this.liveState.realtimeTickIntervalMs || 50) + realtimeInputPauseMs)
      : configuredCooldownMs;
    const baseCooldownMs = Math.min(configuredCooldownMs, realtimeBaseCooldownMs);
    return {
      baseCooldownMs,
      maxBufferedMoves: Phaser.Math.Clamp(Number(movementConfig.live_max_buffered_moves || movementConfig.max_buffered_moves || 2), 1, 6),
      maxPredictionLeadTiles: Phaser.Math.Clamp(Number(movementConfig.live_max_prediction_lead_tiles || movementConfig.max_prediction_lead_tiles || 2), 1, 5),
      pendingMovePenaltyMs: Math.max(0, Number(movementConfig.live_pending_move_penalty_ms || 80)),
      leadTilePenaltyMs: Math.max(0, Number(movementConfig.live_lead_tile_penalty_ms || 110)),
      roomMismatchPenaltyMs: Math.max(0, Number(movementConfig.live_room_mismatch_penalty_ms || 0)),
      maxStepCooldownMs: Math.max(baseCooldownMs, Number(movementConfig.live_max_step_cooldown_ms || 520)),
    };
  }

  canQueueLiveMove(direction = "") {
    const normalizedDirection = firstNonEmpty(direction, "");
    if (!normalizedDirection) {
      return false;
    }
    const pacing = this.liveMovePacingConfig();
    const lead = this.liveMoveLeadSnapshot();
    return lead.pendingCount < pacing.maxBufferedMoves;
  }

  effectiveLiveStepCooldown(movementConfig = this.povConfig()?.movement || {}) {
    const pacing = this.liveMovePacingConfig(movementConfig);
    const lead = this.liveMoveLeadSnapshot();
    const dynamicCooldown =
      pacing.baseCooldownMs
      + Math.max(0, lead.pendingCount - 1) * pacing.pendingMovePenaltyMs
      + Math.max(0, lead.leadTiles - 1) * pacing.leadTilePenaltyMs
      + (lead.roomMismatch ? pacing.roomMismatchPenaltyMs : 0);
    return Phaser.Math.Clamp(dynamicCooldown, pacing.baseCooldownMs, pacing.maxStepCooldownMs);
  }

  queuePendingLiveMessage(entry) {
    const clientActionId = firstNonEmpty(entry?.clientActionId, "");
    if (!clientActionId) {
      return;
    }
    const nextEntry = {
      clientActionId,
      actionText: firstNonEmpty(entry?.actionText, ""),
      targetAgentId: firstNonEmpty(entry?.targetAgentId, ""),
      targetLabel: firstNonEmpty(entry?.targetLabel, ""),
      createdAt: Date.now(),
    };
    this.liveState.pendingMessages = [
      nextEntry,
      ...safeArray(this.liveState.pendingMessages).filter((item) => item?.clientActionId !== clientActionId),
    ].slice(0, 8);
  }

  queuePendingLiveTradeQuote(entry) {
    const clientActionId = firstNonEmpty(entry?.clientActionId, "");
    if (!clientActionId) {
      return;
    }
    const nextEntry = {
      clientActionId,
      itemId: firstNonEmpty(entry?.itemId, ""),
      itemLabel: firstNonEmpty(entry?.itemLabel, ""),
      routeId: firstNonEmpty(entry?.routeId, ""),
      targetAgentId: firstNonEmpty(entry?.targetAgentId, ""),
      targetLabel: firstNonEmpty(entry?.targetLabel, ""),
      createdAt: Date.now(),
    };
    this.liveState.pendingTradeQuotes = [
      nextEntry,
      ...safeArray(this.liveState.pendingTradeQuotes).filter((item) => item?.clientActionId !== clientActionId),
    ].slice(0, 8);
  }

  queuePendingLiveTaskAssignment(entry) {
    const clientActionId = firstNonEmpty(entry?.clientActionId, "");
    if (!clientActionId) {
      return;
    }
    const nextEntry = {
      clientActionId,
      targetAgentId: firstNonEmpty(entry?.targetAgentId, ""),
      targetLabel: firstNonEmpty(entry?.targetLabel, ""),
      destinationRoomId: firstNonEmpty(entry?.destinationRoomId, ""),
      destinationRoomLabel: firstNonEmpty(entry?.destinationRoomLabel, ""),
      routeId: firstNonEmpty(entry?.routeId, ""),
      taskKind: firstNonEmpty(entry?.taskKind, "move_to_room"),
      createdAt: Date.now(),
    };
    this.liveState.pendingTaskAssignments = [
      nextEntry,
      ...safeArray(this.liveState.pendingTaskAssignments).filter((item) => item?.clientActionId !== clientActionId),
    ].slice(0, 8);
  }

  removePendingLiveMessage(clientActionId) {
    const normalized = firstNonEmpty(clientActionId, "");
    if (!normalized) {
      return;
    }
    this.liveState.pendingMessages = safeArray(this.liveState.pendingMessages)
      .filter((item) => item?.clientActionId !== normalized);
  }

  removePendingLiveTradeQuote(clientActionId) {
    const normalized = firstNonEmpty(clientActionId, "");
    if (!normalized) {
      return;
    }
    this.liveState.pendingTradeQuotes = safeArray(this.liveState.pendingTradeQuotes)
      .filter((item) => item?.clientActionId !== normalized);
  }

  removePendingLiveTaskAssignment(clientActionId) {
    const normalized = firstNonEmpty(clientActionId, "");
    if (!normalized) {
      return;
    }
    this.liveState.pendingTaskAssignments = safeArray(this.liveState.pendingTaskAssignments)
      .filter((item) => item?.clientActionId !== normalized);
  }

  clearPendingLiveMoveByInputSeq(maxInputSeq = 0) {
    const normalizedMax = Math.max(0, Number(maxInputSeq || 0));
    if (!normalizedMax) {
      return;
    }
    this.liveState.pendingMoves = safeArray(this.liveState.pendingMoves)
      .filter((item) => Math.max(0, Number(item?.inputSeq || 0)) > normalizedMax);
    this.refreshPendingLiveMoveState();
  }

  clearMovementInputs(targetState) {
    this.windowMovementState.clear();
    if (!targetState?.movementKeys) {
      return;
    }
    for (const keys of targetState.movementKeys.values()) {
      safeArray(keys).forEach((key) => {
        if (typeof key?.reset === "function") {
          key.reset();
        } else if (key && typeof key === "object") {
          key.isDown = false;
          key.isUp = true;
        }
      });
    }
  }

}
