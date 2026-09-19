import { firstNonEmpty, safeArray, liveEventPayload, newClientActionId, isAiStudioErrorMessage, normalizeAgentRecord, normalizeAvailableRoute, resolveWebSocketUrl, postJson, cloneAgentRecord } from "./utils.js";

export class LiveSessionManager {
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

  async createLiveSession({ displayName, roomId = "", speedSecondsPerRound = 1.2 } = {}) {
    const urls = this.liveSessionUrls();
    if (!urls.session) {
      throw new Error("Live session endpoint is unavailable.");
    }
    const response = await postJson(urls.session, {
      display_name: displayName || "Human Interactor",
      room_id: roomId || "",
      speed_seconds_per_round: Number(speedSecondsPerRound || 1.2),
    });
    this.liveState.session = response.session || response.state?.session || null;
    this.liveState.sessionId = firstNonEmpty(this.liveState.session?.session_id, this.liveState.sessionId);
    this.liveState.endpoints.heartbeat = this.liveState.sessionId
      ? `${urls.session}/${encodeURIComponent(this.liveState.sessionId)}/heartbeat`
      : "";
    this.configureLiveRealtime(response);
    return response;
  }

  async #releaseLiveSession() {
    const urls = this.liveSessionUrls();
    if (!this.liveState.sessionId || !urls.session) {
      return;
    }
    this.disconnectLiveWebSocket({ suppressReconnect: true });
    try {
      const response = await fetch(`${urls.session}/${encodeURIComponent(this.liveState.sessionId)}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        throw new Error(`Failed to release live session ${this.liveState.sessionId}`);
      }
    } catch (error) {
      // Best-effort release only.
    }
  }

  async fetchLiveState(since = 0) {
    const urls = this.liveSessionUrls();
    if (!urls.state || !this.liveState.sessionId) {
      return null;
    }
    const stateUrl = new URL(urls.state, window.location.href);
    stateUrl.searchParams.set("session_id", this.liveState.sessionId);
    stateUrl.searchParams.set("since", String(Math.max(0, Number(since || 0))));
    stateUrl.searchParams.set("compact", "1");
    const currentWorldRevision = Number(this.liveState.state?.world_revision || 0);
    if (currentWorldRevision > 0) {
      stateUrl.searchParams.set("if_world_revision", String(currentWorldRevision));
    }
    stateUrl.searchParams.set("t", String(Date.now()));
    const response = await fetch(stateUrl.toString(), { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Failed to load ${stateUrl.pathname}`);
    }
    this.liveState.lastRestPollAt = Date.now();
    return response.json();
  }

  async submitLiveAction(actionPayload) {
    const urls = this.liveSessionUrls();
    if (!urls.action || !this.liveState.sessionId) {
      throw new Error("Live action endpoint is unavailable.");
    }
    const payload = {
      session_id: this.liveState.sessionId,
      action_type: "message",
      action_text: "",
      target_agent_id: this.liveState.targetAgentId || "",
      direction: "",
      room_id: this.selectedRoomId || "",
      coordinates: null,
      ...(actionPayload || {}),
    };
    if (this.liveRealtimeReady()) {
      const clientActionId = payload.client_action_id || String(Math.floor(Math.random() * 1e9));
      payload.client_action_id = clientActionId;
      const wsMessage = {
        type: "action",
        payload: payload,
      };
      const sent = this.sendLiveWsMessage(wsMessage);
      if (sent) {
        this.liveState.frozenPayload = null;
        this.liveState.frozenFingerprint = "";
        this.liveState.typingFreezeActive = false;
        this.hideLiveErrorOverlay();
        return {
          status: "accepted",
          client_action_id: clientActionId,
          latest_event_id: this.liveState.lastEventId,
        };
      }
    }
    try {
      const response = await postJson(urls.action, payload);
      this.liveState.frozenPayload = null;
      this.liveState.frozenFingerprint = "";
      this.liveState.typingFreezeActive = false;
      this.hideLiveErrorOverlay();
      const nextState = response?.state && typeof response.state === "object" && !Array.isArray(response.state)
        ? response.state
        : null;
      if (nextState?.session || nextState?.agents || nextState?.rooms) {
        this.applyLiveState(nextState, { focusClaimedAgent: false, allowTypingFreeze: false });
      } else if (Number(response?.latest_event_id || 0) > Number(this.liveState.lastEventId || 0)) {
        this.liveState.lastEventId = Number(response.latest_event_id || this.liveState.lastEventId || 0);
      }
      return response;
    } catch (error) {
      const message = String(error?.message || error || "Live action failed");
      const statusNode = document.getElementById("event-status");
      if (statusNode) {
        statusNode.textContent = message;
      }
      if (isAiStudioErrorMessage(message)) {
        this.showLiveErrorOverlay({
          title: "AI STUDIO ERROR",
          message: `Live action could not complete because the AI Studio reply failed.\n\n${message}`,
        });
      }
      throw error;
    }
  }

  connectLiveWebSocket() {
    if (!this.isLiveSessionMode() || !this.liveState.sessionId || !this.liveState.realtimeEnabled) {
      return;
    }
    if (this.liveState.websocketConnected || this.liveState.websocketConnecting) {
      return;
    }
    const wsUrl = this.resolvedLiveWsUrl(this.liveState.sessionId);
    if (!wsUrl) {
      return;
    }
    this.liveState.websocketConnecting = true;
    this.liveState.websocketReconnectBlocked = false;
    this.liveState.wsUrl = wsUrl;
    const socket = new WebSocket(wsUrl);
    this.liveState.websocket = socket;
    socket.addEventListener("open", () => {
      this.liveState.websocketConnected = true;
      this.liveState.websocketConnecting = false;
      this.liveState.websocketTransportActive = true;
      this.liveState.websocketReconnectAttempts = 0;
      this.liveState.websocketLastMessageAt = Date.now();
      this.startLiveWsHeartbeat();
      const statusNode = document.getElementById("event-status");
      if (statusNode) {
        statusNode.textContent = `Live realtime connected (${this.liveState.sessionId || "session"})`;
      }
    });
    socket.addEventListener("message", (event) => {
      this.liveState.websocketLastMessageAt = Date.now();
      let payload = null;
      try {
        payload = JSON.parse(String(event.data || "{}"));
      } catch (_error) {
        payload = null;
      }
      if (payload && typeof payload === "object") {
        this.handleLiveWsMessage(payload);
      }
    });
    socket.addEventListener("close", () => {
      this.liveState.websocketConnected = false;
      this.liveState.websocketConnecting = false;
      this.liveState.websocket = null;
      this.stopLiveWsHeartbeat();
      if (this.isLiveSessionMode() && this.liveState.sessionId && !this.liveState.websocketReconnectBlocked) {
        this.scheduleLiveWsReconnect();
      }
    });
    socket.addEventListener("error", () => {
      this.liveState.websocketTransportActive = false;
    });
  }

  disconnectLiveWebSocket({ suppressReconnect = false } = {}) {
    this.liveState.websocketReconnectBlocked = suppressReconnect;
    if (suppressReconnect && this.liveState.websocketReconnectTimer) {
      window.clearTimeout(this.liveState.websocketReconnectTimer);
      this.liveState.websocketReconnectTimer = 0;
    }
    this.stopLiveWsHeartbeat();
    const socket = this.liveState.websocket;
    this.liveState.websocket = null;
    this.liveState.websocketConnected = false;
    this.liveState.websocketConnecting = false;
    if (socket && socket.readyState < WebSocket.CLOSING) {
      try {
        socket.close(1000, "scene_shutdown");
      } catch (_error) {
        // Ignore close errors during unload.
      }
    }
  }

  scheduleLiveWsReconnect() {
    if (this.liveState.websocketReconnectTimer || !this.liveState.realtimeEnabled) {
      return;
    }
    const attempt = Number(this.liveState.websocketReconnectAttempts || 0) + 1;
    this.liveState.websocketReconnectAttempts = attempt;
    const delay = Math.min(4000, 350 + (attempt - 1) * 400);
    this.liveState.websocketReconnectTimer = window.setTimeout(() => {
      this.liveState.websocketReconnectTimer = 0;
      this.connectLiveWebSocket();
    }, delay);
  }

  startLiveWsHeartbeat() {
    this.stopLiveWsHeartbeat();
    const heartbeatMs = Math.max(1200, Math.min(4000, Math.floor((this.liveState.realtimeFlushIntervalMs || 1000) * 2)));
    this.liveState.websocketHeartbeatTimer = window.setInterval(() => {
      if (!this.liveRealtimeReady()) {
        return;
      }
      this.sendLiveWsMessage({
        type: "ping",
        client_time_ms: Date.now(),
      });
    }, heartbeatMs);
  }

  stopLiveWsHeartbeat() {
    if (this.liveState.websocketHeartbeatTimer) {
      window.clearInterval(this.liveState.websocketHeartbeatTimer);
      this.liveState.websocketHeartbeatTimer = 0;
    }
  }

  sendLiveWsMessage(payload) {
    if (!this.liveRealtimeReady()) {
      return false;
    }
    try {
      this.liveState.websocket.send(JSON.stringify(payload || {}));
      return true;
    } catch (_error) {
      return false;
    }
  }

  handleLiveWsMessage(payload) {
    const messageType = firstNonEmpty(payload?.type, payload?.message_type, "");
    if (messageType === "hello") {
      this.configureLiveRealtime(payload);
      if (payload?.state && this.roomNodes.size) {
        this.applyLiveState(payload.state, {
          focusClaimedAgent: false,
          allowTypingFreeze: false,
        });
      }
      return;
    }
    if (messageType === "state_delta") {
      this.applyLiveWsStateDelta(payload);
      return;
    }
    if (messageType === "action_result") {
      const nextState = payload?.state && typeof payload.state === "object" && !Array.isArray(payload.state)
        ? payload.state
        : null;
      if (nextState) {
        this.applyLiveState(nextState, { focusClaimedAgent: false });
      }
      return;
    }
    if (messageType === "ai_thinking") {
      this.handleAiThinking(payload);
      return;
    }
    if (messageType === "ai_stream_chunk") {
      this.handleAiStreamChunk(payload);
      return;
    }
    if (messageType === "error") {
      const statusNode = document.getElementById("event-status");
      if (statusNode) {
        statusNode.textContent = firstNonEmpty(payload?.detail, "Live realtime error");
      }
    }
  }

  configureLiveRealtime(payload) {
    const realtime = payload?.realtime && typeof payload.realtime === "object"
      ? payload.realtime
      : payload?.state?.realtime && typeof payload.state.realtime === "object"
        ? payload.state.realtime
        : {};
    this.liveState.realtimeEnabled = realtime?.enabled !== false;
    this.liveState.realtimeTickIntervalMs = Math.max(33, Number(realtime?.tick_interval_ms || this.liveState.realtimeTickIntervalMs || 50));
    this.liveState.realtimeFlushIntervalMs = Math.max(250, Number(realtime?.flush_interval_ms || this.liveState.realtimeFlushIntervalMs || 1000));
    const wsUrl = firstNonEmpty(realtime?.ws_url, this.liveState.wsUrl, "");
    if (wsUrl) {
      this.liveState.wsUrl = resolveWebSocketUrl(wsUrl);
    } else if (this.liveState.sessionId) {
      this.liveState.wsUrl = this.resolvedLiveWsUrl(this.liveState.sessionId);
    }
  }

  liveRealtimeReady() {
    return Boolean(
      this.isLiveSessionMode()
      && this.liveState.realtimeEnabled
      && this.liveState.websocketConnected
      && this.liveState.websocket
      && this.liveState.websocket.readyState === WebSocket.OPEN
    );
  }

  applyLiveState(payload, { focusClaimedAgent = false, allowTypingFreeze = true } = {}) {
    if (!payload || typeof payload !== "object") {
      return;
    }
    this.configureLiveRealtime(payload);
    const nextFingerprint = this.liveStateFingerprint(payload);
    if (allowTypingFreeze && this.liveInputFreezeActive()) {
      this.queueFrozenLiveState(payload, nextFingerprint);
      return;
    }
    this.liveState.state = payload;
    this.liveState.session = payload.session || this.liveState.session || null;
    this.liveState.sessionId = firstNonEmpty(this.liveState.session?.session_id, this.liveState.sessionId);
    this.liveState.lastEventId = Number(payload.latest_event_id || this.liveState.lastEventId || 0);
    this.liveState.eventLog = safeArray(payload.events);
    this.reconcilePendingLiveMove(this.liveState.eventLog);
    this.reconcilePendingLiveMessages(this.liveState.eventLog);
    this.liveState.pollIntervalMs = Number(payload.poll_interval_ms || this.liveState.pollIntervalMs || 1200);
    this.liveState.fingerprint = nextFingerprint;
    const availableRoutes = safeArray(payload.available_routes).map((route) => normalizeAvailableRoute(route)).filter(Boolean);
    const moveRoutes = availableRoutes.filter((route) => route.kind === "move");
    const tradeRoutes = availableRoutes.filter((route) => route.kind === "item_trade");
    if (!moveRoutes.some((route) => route.route_id === this.liveState.selectedMoveRouteId)) {
      this.liveState.selectedMoveRouteId = moveRoutes[0]?.route_id || "";
    }
    if (!tradeRoutes.some((route) => route.route_id === this.liveState.selectedTradeRouteId)) {
      this.liveState.selectedTradeRouteId = tradeRoutes[0]?.route_id || "";
    }
    const previousClaimedRoomId = this.liveState.lastClaimedAgentRoomId || "";
    this.liveState.authoritativeAgents = this.filterLiveReadyAgents(payload.agents, payload)
      .map((agent) => cloneAgentRecord(agent));
    this.currentAgents = this.liveState.authoritativeAgents.map((agent) => cloneAgentRecord(agent));
    this.homeRoomId = firstNonEmpty(payload.room?.room_id, this.homeRoomId, this.currentAgents[0]?.room_id || "");
    const claimedAgentId = this.liveState.session?.claimed_agent_id || "";
    const fallbackSelectedAgent =
      this.currentAgents.find((agent) => agent.agent_id === claimedAgentId) ||
      this.currentAgents.find((agent) => agent.agent_id === this.selectedAgentRecord?.agent_id) ||
      this.currentAgents.find((agent) => agent.main_character) ||
      this.currentAgents[0] ||
      null;
    if (focusClaimedAgent || !this.selectedAgentRecord || !this.currentAgents.some((agent) => agent.agent_id === this.selectedAgentRecord.agent_id)) {
      this.selectedAgentRecord = fallbackSelectedAgent;
    } else {
      this.selectedAgentRecord = this.currentAgents.find((agent) => agent.agent_id === this.selectedAgentRecord.agent_id) || fallbackSelectedAgent;
    }
    this.replayQueuedLiveMovePredictions();
    const claimedAgent = this.currentAgents.find((agent) => agent.agent_id === claimedAgentId) || fallbackSelectedAgent;
    const claimedRoomId = claimedAgent?.room_id || firstNonEmpty(payload.room?.room_id, "");
    if (focusClaimedAgent || !this.selectedRoomId || (claimedRoomId && previousClaimedRoomId && claimedRoomId !== previousClaimedRoomId)) {
      this.selectedRoomId = firstNonEmpty(claimedRoomId, payload.room?.room_id, this.selectedRoomId, this.homeRoomId);
    } else if (!this.roomLookup.has(this.selectedRoomId)) {
      this.selectedRoomId = firstNonEmpty(claimedRoomId, payload.room?.room_id, this.homeRoomId);
    }
    this.liveState.lastClaimedAgentRoomId = claimedRoomId || previousClaimedRoomId;
    this.liveState.targetAgentId = this.currentAgents.some((agent) => agent.agent_id === this.liveState.targetAgentId)
      ? this.liveState.targetAgentId
      : "";
    if (!this.liveState.targetAgentId && claimedAgent) {
      this.liveState.targetAgentId = this.currentAgents.find((agent) => agent.room_id === claimedAgent.room_id && agent.agent_id !== claimedAgent.agent_id)?.agent_id || "";
    }
    this.reconcilePendingLiveTradeQuotes(this.liveState.eventLog, safeArray(claimedAgent?.pending_trade_offers));
    this.reconcilePendingLiveTaskAssignments(this.liveState.eventLog, this.currentAgents);
    const claimedInventory = safeArray(claimedAgent?.inventory);
    if (!claimedInventory.some((item) => item.item_id === this.liveState.selectedItemId && Number(item.quantity || 0) > 0)) {
      this.liveState.selectedItemId = claimedInventory.find((item) => Number(item.quantity || 0) > 0)?.item_id || "";
    }
    this.syncAgents(this.currentAgents, {
      preserveCoordinates: this.isLiveSessionMode(),
      animateMovement: !focusClaimedAgent,
      movementDurationMs: this.liveState.realtimeEnabled ? this.liveState.realtimeTickIntervalMs + 18 : 0,
    });
    this.surfaceLiveEventBubbles(safeArray(payload.events));
    if (this.selectedAgentRecord?.agent_id) {
      if (this.agentManager.selectedAgentId !== this.selectedAgentRecord.agent_id) {
        this.agentManager.selectAgent(this.selectedAgentRecord.agent_id);
      } else {
        this.agentManager.refreshSelectionVisuals();
      }
    }
    this.refreshWorldNotes();
    this.refreshLiveUi({ force: focusClaimedAgent });
    this.scheduleExportFallbackRender();
    this.kickHeadlessRender(4);
  }

  applyCompactLiveState(payload) {
    if (!payload || typeof payload !== "object") {
      return;
    }
    this.liveState.session = payload.session || this.liveState.session || null;
    this.liveState.sessionId = firstNonEmpty(this.liveState.session?.session_id, this.liveState.sessionId);
    this.liveState.lastEventId = Number(payload.latest_event_id || this.liveState.lastEventId || 0);
    this.liveState.pollIntervalMs = Number(payload.poll_interval_ms || this.liveState.pollIntervalMs || 1200);
    this.liveState.state = {
      ...(this.liveState.state && typeof this.liveState.state === "object" ? this.liveState.state : {}),
      session: this.liveState.session,
      latest_event_id: this.liveState.lastEventId,
      world_revision: Number(payload.world_revision || this.liveState.state?.world_revision || 0),
      poll_interval_ms: this.liveState.pollIntervalMs,
      updated_at: firstNonEmpty(payload.updated_at, this.liveState.state?.updated_at, ""),
      events: safeArray(payload.events),
      mode: firstNonEmpty(payload.mode, "compact"),
      unchanged: Boolean(payload.unchanged),
    };
    this.liveState.eventLog = safeArray(payload.events);
  }

  applyLiveWsStateDelta(payload) {
    if (!payload || typeof payload !== "object") {
      return;
    }
    const agentDeltas = safeArray(payload.agents).filter((agent) => agent && typeof agent === "object");
    if (!agentDeltas.length) {
      return;
    }
    this.liveState.websocketLastMessageAt = Date.now();
    const claimedAgentId = firstNonEmpty(this.liveState.session?.claimed_agent_id, "");
    const previousClaimedRoomId = this.liveState.lastClaimedAgentRoomId || "";
    if (!safeArray(this.liveState.authoritativeAgents).length) {
      this.liveState.authoritativeAgents = this.filterLiveReadyAgents(this.liveState.state?.agents || [], this.liveState.state)
        .map((agent) => cloneAgentRecord(agent));
    }
    const authoritativeAgents = this.liveState.authoritativeAgents.map((agent) => cloneAgentRecord(agent));
    let claimedDelta = null;
    agentDeltas.forEach((delta) => {
      const updatedAgent = this.upsertLiveAgentDelta(authoritativeAgents, delta);
      if (updatedAgent && updatedAgent.agent_id === claimedAgentId) {
        claimedDelta = { ...delta, agent: updatedAgent };
      }
    });
    this.liveState.authoritativeAgents = authoritativeAgents;
    if (this.liveState.state && typeof this.liveState.state === "object") {
      const stateAgents = this.filterLiveReadyAgents(authoritativeAgents, this.liveState.state).map((agent) => cloneAgentRecord(agent));
      this.liveState.state = {
        ...this.liveState.state,
        agents: stateAgents,
        world_revision: Math.max(Number(this.liveState.state.world_revision || 0), Number(payload.world_revision || 0)),
        updated_at: new Date().toISOString(),
      };
    }
    if (claimedDelta?.agent) {
      const nextRoomId = firstNonEmpty(claimedDelta.agent.room_id, previousClaimedRoomId);
      this.liveState.lastClaimedAgentRoomId = nextRoomId || previousClaimedRoomId;
      if (this.liveState.session) {
        this.liveState.session = {
          ...this.liveState.session,
          room_id: nextRoomId,
        };
      }
      if (claimedDelta.last_input_seq !== undefined) {
        this.clearPendingLiveMoveByInputSeq(claimedDelta.last_input_seq);
      }
    }
    this.currentAgents = this.liveState.authoritativeAgents.map((agent) => cloneAgentRecord(agent));
    this.replayQueuedLiveMovePredictions();
    const claimedAgent = this.controllerAgentRecord() || this.controllerAgentRecord({ authoritative: true });
    const claimedRoomChanged = Boolean(claimedAgent && previousClaimedRoomId && claimedAgent.room_id && claimedAgent.room_id !== previousClaimedRoomId);
    if (claimedAgent?.agent_id && this.selectedAgentRecord?.agent_id === claimedAgent.agent_id) {
      this.selectedAgentRecord = claimedAgent;
    }
    if (claimedRoomChanged) {
      this.selectedRoomId = claimedAgent?.room_id || this.selectedRoomId;
    }
    this.syncAgents(this.currentAgents, {
      preserveCoordinates: true,
      animateMovement: true,
      movementDurationMs: this.liveState.realtimeTickIntervalMs + 18,
      refreshUi: false,
    });
    if (this.selectedAgentRecord?.agent_id) {
      if (this.agentManager.selectedAgentId !== this.selectedAgentRecord.agent_id) {
        this.agentManager.selectAgent(this.selectedAgentRecord.agent_id);
      } else {
        this.agentManager.refreshSelectionVisuals();
      }
    }
    this.refreshWorldNotes();
    if (claimedRoomChanged) {
      this.refreshLiveUi({ force: true });
      this.renderGroundItems();
    } else {
      this.refreshImmersiveHud();
    }
    this.scheduleExportFallbackRender();
  }

  upsertLiveAgentDelta(targetAgents, delta) {
    const agentId = firstNonEmpty(delta?.agent_id, "");
    if (!agentId) {
      return null;
    }
    const index = safeArray(targetAgents).findIndex((agent) => firstNonEmpty(agent?.agent_id, "") === agentId);
    const base = index >= 0
      ? cloneAgentRecord(targetAgents[index])
      : normalizeAgentRecord({
        agent_id: agentId,
        display_name: agentId,
        room_id: firstNonEmpty(delta?.room_id, ""),
        coordinates: delta?.coordinates || {},
      });
    const nextAgent = {
      ...base,
      room_id: firstNonEmpty(delta?.room_id, base.room_id),
      coordinates: {
        ...(base.coordinates || {}),
        ...(delta?.coordinates && typeof delta.coordinates === "object" ? delta.coordinates : {}),
      },
      claimed_by_session_id: firstNonEmpty(delta?.claimed_by_session_id, base.claimed_by_session_id),
      control_mode: firstNonEmpty(delta?.control_mode, base.control_mode),
      facing: firstNonEmpty(delta?.facing, base.facing, "down"),
      animation: firstNonEmpty(delta?.animation, base.animation),
      last_input_seq: Math.max(0, Number(delta?.last_input_seq ?? base.last_input_seq ?? 0)),
    };
    if (index >= 0) {
      targetAgents[index] = nextAgent;
    } else {
      targetAgents.push(nextAgent);
    }
    return nextAgent;
  }

  liveStateFingerprint(payload) {
    const session = payload?.session || {};
    const room = payload?.room || {};
    const agentSummary = safeArray(payload?.agents)
      .map((agent) => {
        const inventory = safeArray(agent?.inventory)
          .map((item) => `${item?.item_id || ""}:${Number(item?.quantity || 0)}`)
          .join(",");
        const coords = agent?.coordinates || {};
        return [
          agent?.agent_id || "",
          agent?.room_id || "",
          Number(coords?.x ?? 0),
          Number(coords?.y ?? 0),
          Number(coords?.z ?? 0),
          agent?.control_mode || "",
          agent?.live_motion_mode || "",
          agent?.claimed_by_session_id || "",
          agent?.current_focus || "",
          inventory,
        ].join("@");
      })
      .sort()
      .join("|");
    return [
      payload?.latest_event_id || 0,
      session?.session_id || "",
      session?.claimed_agent_id || "",
      session?.room_id || "",
      session?.status || "",
      room?.room_id || "",
      room?.human_count || 0,
      room?.active || 0,
      room?.activation_generation || 0,
      room?.active_agent_count || 0,
      agentSummary,
    ].join(":");
  }

  runtimeFingerprint(runtimeState) {
    return [
      runtimeState.run_id || "",
      runtimeState.status || "",
      runtimeState.round_index || 0,
      runtimeState.updated_at || runtimeState.generated_at || "",
    ].join(":");
  }

  liveSessionUrls() {
    const code = this.liveWorldCode();
    return {
      session: firstNonEmpty(this.liveState.endpoints.session, code ? `/api/pixel/worlds/${encodeURIComponent(code)}/live/sessions` : ""),
      state: firstNonEmpty(this.liveState.endpoints.state, code ? `/api/pixel/worlds/${encodeURIComponent(code)}/live/state` : ""),
      action: firstNonEmpty(this.liveState.endpoints.action, code ? `/api/pixel/worlds/${encodeURIComponent(code)}/live/actions` : ""),
      heartbeat: firstNonEmpty(this.liveState.endpoints.heartbeat, this.liveState.sessionId ? `${firstNonEmpty(this.liveState.endpoints.session, code ? `/api/pixel/worlds/${encodeURIComponent(code)}/live/sessions` : "")}/${encodeURIComponent(this.liveState.sessionId)}/heartbeat` : ""),
      wsTemplate: firstNonEmpty(this.liveState.endpoints.wsTemplate, code ? `/api/pixel/worlds/${encodeURIComponent(code)}/live/ws/{session_id}` : ""),
    };
  }

  liveReadyAgentSet(payload = this.liveState.state) {
    const explicitIds = safeArray(payload?.live_ready_agent_ids)
      .map((agentId) => String(agentId || "").trim())
      .filter(Boolean);
    if (explicitIds.length) {
      return new Set(explicitIds);
    }
    const derivedIds = safeArray(payload?.agents)
      .filter((agent) => agent && agent.live_ready !== false)
      .map((agent) => String(agent.agent_id || "").trim())
      .filter(Boolean);
    return new Set(derivedIds);
  }

  liveAvailableRoutes(kind = "") {
    const routes = safeArray(this.liveState.state?.available_routes)
      .map((route) => normalizeAvailableRoute(route))
      .filter(Boolean);
    if (!kind) {
      return routes;
    }
    return routes.filter((route) => route.kind === kind);
  }

  filterLiveReadyAgents(agentPayload, payload = this.liveState.state) {
    const readyIds = this.liveReadyAgentSet(payload);
    this.liveState.liveReadyAgentIds = Array.from(readyIds);
    if (!readyIds.size) {
      return this.attachAgentPortraits(safeArray(agentPayload).map(normalizeAgentRecord));
    }
    return this.attachAgentPortraits(safeArray(agentPayload)
      .filter((agent) => readyIds.has(String(agent?.agent_id || "").trim()))
      .map((agent) => normalizeAgentRecord({ ...agent, live_ready: true })));
  }

  flushFrozenLiveState({ force = false } = {}) {
    const payload = this.liveState.frozenPayload;
    if (!payload || (!force && this.liveInputFreezeActive())) {
      return false;
    }
    this.liveState.frozenPayload = null;
    this.liveState.frozenFingerprint = "";
    this.liveState.typingFreezeActive = false;
    if (this.input?.keyboard) {
      this.input.keyboard.enabled = true;
    }
    this.applyLiveState(payload, { focusClaimedAgent: false, allowTypingFreeze: false });
    return true;
  }

  queueFrozenLiveState(payload, fingerprint = "") {
    this.liveState.frozenPayload = payload;
    this.liveState.frozenFingerprint = fingerprint || this.liveStateFingerprint(payload);
    this.liveState.typingFreezeActive = true;
    if (payload?.session) {
      this.liveState.session = payload.session;
      this.liveState.sessionId = firstNonEmpty(payload.session.session_id, this.liveState.sessionId);
    }
    this.liveState.pollIntervalMs = Number(payload?.poll_interval_ms || this.liveState.pollIntervalMs || 1200);
  }

  liveSignature(kind) {
    const session = this.liveState.session || {};
    const claimedAgent = this.currentAgents.find((agent) => agent.agent_id === session.claimed_agent_id) || this.selectedAgentRecord;
    const authoritativeClaimedAgent = this.controllerAgentRecord({ authoritative: true }) || claimedAgent;
    const target = this.dialogueTargetRecord({ authoritative: this.isLiveSessionMode() });
    const authoritativeAgents = this.activeAgentRecords({ authoritative: true });
    const routeDigest = this.liveAvailableRoutes()
      .map((route) => `${route.route_id}:${route.kind}:${route.action}:${route.story_verb}`)
      .join(",");
    if (kind === "movement") {
      const pendingMoveCount = safeArray(this.liveState.pendingMoves).length;
      return [
        session.session_id || "",
        session.claimed_agent_id || "",
        session.status || "",
        claimedAgent?.room_id || "",
        this.liveState.lastEventId || 0,
        pendingMoveCount ? `moving:${pendingMoveCount}` : "ready",
        routeDigest,
      ].join("|");
    }
    if (kind === "items") {
      return [
        this.liveAgentDigest(authoritativeClaimedAgent),
        this.liveAgentDigest(target),
        this.liveState.selectedItemId || "",
        this.liveState.targetAgentId || "",
      ].join("|");
    }
    if (kind === "dialogue") {
      const roomAgents = authoritativeAgents
        .filter((agent) => agent.room_id === authoritativeClaimedAgent?.room_id && agent.agent_id !== session.claimed_agent_id)
        .map((agent) => `${agent.agent_id}:${agent.display_name}`)
        .sort()
        .join(",");
      const events = safeArray(this.liveState.eventLog)
        .slice(-10)
        .map((event) => `${event.event_id || ""}:${event.event_type || ""}:${event.agent_id || ""}:${event.target_agent_id || ""}:${event.action_text || ""}:${event.response_text || ""}`)
        .join("|");
      return [roomAgents, this.liveState.targetAgentId || "", this.liveState.lastEventId || 0, events].join("|");
    }
    if (kind === "trade") {
      return [this.liveAgentDigest(authoritativeClaimedAgent), this.liveAgentDigest(target), this.liveState.selectedItemId || "", routeDigest].join("|");
    }
    if (kind === "log") {
      return [
        safeArray(this.liveState.pendingMessages).map((entry) => `${entry.clientActionId || ""}:${entry.actionText || ""}`).join(","),
        safeArray(this.liveState.eventLog)
          .map((event) => `${event.event_id || ""}:${event.event_type || ""}:${event.action_text || ""}:${event.response_text || ""}`)
          .join("|"),
      ].join("|");
    }
    if (kind === "hud") {
      return [
        this.viewMode,
        this.liveAgentDigest(this.controllerAgentRecord() || claimedAgent),
        this.liveAgentDigest(this.targetBubbleAgent()),
      ].join("|");
    }
    if (kind === "selector") {
      const controller = this.controllerAgentRecord({ authoritative: true }) || authoritativeClaimedAgent;
      const visibleTargets = safeArray(authoritativeAgents)
        .filter((agent) => agent.agent_id !== controller?.agent_id)
        .filter((agent) => !controller?.room_id || agent.room_id === controller.room_id)
        .map((agent) => `${agent.agent_id}:${agent.display_name}:${agent.room_id}`)
        .join(",");
      return [this.liveState.targetAgentId || "", visibleTargets, this.liveAgentDigest(controller)].join("|");
    }
    if (kind === "pending") {
      return [
        safeArray(this.liveState.pendingMoves).map((entry) => `${entry.clientActionId || ""}:${entry.direction || ""}`).join(","),
        safeArray(this.liveState.pendingMessages).map((entry) => `${entry.clientActionId || ""}:${entry.actionText || ""}`).join(","),
        safeArray(this.liveState.pendingTradeQuotes).map((entry) => `${entry.clientActionId || ""}:${entry.itemId || ""}:${entry.targetAgentId || ""}`).join(","),
        safeArray(this.liveState.pendingTaskAssignments).map((entry) => `${entry.clientActionId || ""}:${entry.targetAgentId || ""}:${entry.destinationRoomId || ""}`).join(","),
      ].join("|");
    }
    if (kind === "target") {
      return this.liveAgentDigest(this.targetBubbleAgent());
    }
    return "";
  }

  isLiveSessionMode() {
    return this.runtimeMode === "live";
  }

}
