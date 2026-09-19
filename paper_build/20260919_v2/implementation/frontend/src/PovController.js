import { firstNonEmpty, safeArray } from "./utils.js";

export class PovController {
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

  initializeLocalPovModules() {
    const config = this.povConfig();
    this.localPovState.enabled = Boolean(config.enabled && !this.runtimeState && !this.isLiveSessionMode());
    this.localPovState.actionLog = [];
    this.localPovState.dialogueLog = [];
    this.localPovState.tradeOffers = [];
    this.localPovState.agentState = new Map();
    this.localPovState.groundItems = [];
    if (!this.localPovState.enabled) {
      this.refreshLocalInteractionPanels();
      return;
    }

    const protagonistId =
      config.protagonist_agent_id ||
      this.mapGrid?.map_visual?.camera?.follow_main_character ||
      this.currentAgents.find((agent) => agent.main_character)?.agent_id ||
      this.currentAgents[0]?.agent_id ||
      "";
    this.localPovState.protagonistAgentId = protagonistId;
    this.ensureProtagonistWalkableSpawn();
    this.seedLocalPovAgentState();
    this.seedGroundItems();
    this.bindLocalMovementKeys();
    if (protagonistId) {
      this.agentManager.selectAgent(protagonistId);
      this.selectedAgentRecord = this.currentAgents.find((agent) => agent.agent_id === protagonistId) || this.selectedAgentRecord;
      this.localPovState.dialogueTargetId = this.nearbyAgentsFor(this.selectedAgentRecord).find(Boolean)?.agent_id || "";
    }
    const protagonistState = this.localAgentState(protagonistId);
    this.localPovState.selectedItemId = protagonistState?.inventory.find((item) => item.quantity > 0)?.item_id || "";
    this.setViewMode("pov", { instant: true });
    this.logLocalAction("system", "POV local modules armed. Move with WASD or the arrow keys.");
    this.renderGroundItems();
    this.refreshLocalInteractionPanels();
  }

  localPovEnabled() {
    return Boolean(!this.runtimeState && !this.isLiveSessionMode() && this.localPovState.enabled);
  }

  protagonistAgentId() {
    return this.localPovState.protagonistAgentId || this.povConfig().protagonist_agent_id || "";
  }

  bindLocalMovementKeys() {
    this.bindMovementKeys(this.localPovState, this.movementKeyConfig());
  }

  attemptLocalMove(intent) {
    const protagonist = this.currentAgents.find((agent) => agent.agent_id === this.protagonistAgentId());
    if (!protagonist) {
      return false;
    }
    const preview = this.resolveMoveDestination(protagonist.room_id, protagonist.coordinates || {}, intent.direction);
    if (!preview?.ok) {
      if (preview?.reason === "boundary") {
        this.logLocalAction("move", `${protagonist.display_name} reaches a wall and cannot move ${intent.direction}.`);
        return false;
      }
      if (preview?.reason === "room_transition") {
        this.logLocalAction("move", `${protagonist.display_name} cannot pass through that boundary yet.`);
        return false;
      }
      this.logLocalAction("move", `${protagonist.display_name} bumps into an obstacle and cannot move ${intent.direction}.`);
      return false;
    }
    protagonist.coordinates = { ...(protagonist.coordinates || {}), x: preview.nextX, y: preview.nextY, z: preview.nextZ };
    protagonist.room_id = preview.nextRoomId;
    this.selectedRoomId = preview.nextRoomId;
    this.playMovementAnimation(protagonist.agent_id, intent.direction);
    this.syncAgents(this.currentAgents, { preserveCoordinates: true });
    return true;
  }

  refreshLocalInteractionPanels() {
    this.renderMovementModule();
    this.renderItemModule();
    this.refreshTradeModule();
    this.renderDialogueModule();
    this.renderActionLog();
    this.renderPendingActions();
  }

  logLocalAction(kind, text) {
    const limit = Number(this.povConfig()?.recent_log_limit || 14);
    this.localPovState.actionLog.unshift({ kind, text, createdAt: new Date().toISOString() });
    this.localPovState.actionLog = this.localPovState.actionLog.slice(0, limit);
    this.renderActionLog();
  }

  ensureProtagonistWalkableSpawn() {
    const protagonistId = this.protagonistAgentId();
    const protagonist = this.currentAgents.find((agent) => agent.agent_id === protagonistId);
    if (!protagonist) {
      return;
    }
    const currentX = Number(protagonist.coordinates?.x ?? Number.NaN);
    const currentY = Number(protagonist.coordinates?.y ?? Number.NaN);
    if (!Number.isFinite(currentX) || !Number.isFinite(currentY)) {
      const fallback = this.autoPlacementTile(protagonist.room_id, 0);
      if (fallback) {
        protagonist.coordinates = { ...(protagonist.coordinates || {}), x: fallback.x, y: fallback.y, z: Number(fallback.z ?? 0) };
      }
      return;
    }
    if (!this.isBlockedTile(protagonist.room_id, currentX, currentY, Number(protagonist.coordinates?.z ?? 0))) {
      return;
    }
    const fallback = this.nearestWalkableTile(protagonist.room_id, currentX, currentY);
    if (fallback) {
      protagonist.coordinates = { ...(protagonist.coordinates || {}), x: fallback.x, y: fallback.y, z: Number(fallback.z ?? 0) };
      this.logLocalAction("system", `${protagonist.display_name} was nudged to a walkable starting tile to avoid clipping into scenery.`);
    }
  }

  povConfig() {
    return this.worldConfig?.pixel_asset_pipeline?.frontend?.pov_local_modules || {};
  }

  inventoryExchangeConfig() {
    return this.povConfig()?.inventory_exchange || {};
  }

  negotiationConfig() {
    return this.inventoryExchangeConfig()?.negotiation || {};
  }

  presentAgentExchange(sourceAgentId, sourceText, targetAgentId, targetText) {
    this.showSpeechBubble(sourceAgentId, sourceText);
    this.pulseAgentResponse(sourceAgentId, targetAgentId);
    if (targetAgentId) {
      this.time.delayedCall(220, () => {
        this.showSpeechBubble(targetAgentId, targetText);
        this.pulseAgentResponse(targetAgentId, sourceAgentId);
      });
    }
  }

  activeAgentRecords({ authoritative = false } = {}) {
    if (authoritative && this.isLiveSessionMode() && safeArray(this.liveState.authoritativeAgents).length) {
      return this.liveState.authoritativeAgents;
    }
    return this.currentAgents;
  }

}
