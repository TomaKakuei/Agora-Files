import { firstNonEmpty, safeArray, tileKey, Phaser } from "./utils.js";

export class InputController {
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

  bindLiveMovementKeys() {
    this.bindMovementKeys(this.liveState, this.movementKeyConfig());
  }

  movementKeyConfig() {
    const keyConfig = this.povController.povConfig()?.movement?.keys || {};
    if (Object.keys(keyConfig).length) {
      return keyConfig;
    }
    return {
      up: ["W", "ARROWUP"],
      down: ["S", "ARROWDOWN"],
      left: ["A", "ARROWLEFT"],
      right: ["D", "ARROWRIGHT"],
    };
  }

  bindMovementKeys(targetState, keyConfig) {
    const keyCodes = Phaser.Input.Keyboard.KeyCodes;
    const movementKeys = new Map();
    Object.entries(keyConfig).forEach(([direction, aliases]) => {
      movementKeys.set(
        direction,
        safeArray(aliases)
          .map((alias) => keyCodes[String(alias || "").toUpperCase()])
          .filter(Boolean)
          .map((code) => this.input.keyboard.addKey(code)),
      );
    });
    targetState.movementKeys = movementKeys;
  }


  installWindowMovementControls() {
    if (this.windowKeyHandlersInstalled) {
      return;
    }
    const aliasMap = this.worldRenderer.directionAliasMap();
    const shouldIgnore = (event) => {
      const target = event?.target;
      if (!target || !(target instanceof HTMLElement)) {
        return false;
      }
      const tag = String(target.tagName || "").toUpperCase();
      return target.isContentEditable || tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || Boolean(target.closest("input, textarea, select, [contenteditable='true']"));
    };
    this.windowKeyDownHandler = (event) => {
      if (shouldIgnore(event)) {
        return;
      }
      const direction = aliasMap[String(event.key || "").toLowerCase()];
      if (!direction) {
        return;
      }
      event.preventDefault();
      this.windowMovementState.add(direction);
    };
    this.windowKeyUpHandler = (event) => {
      const direction = aliasMap[String(event.key || "").toLowerCase()];
      if (!direction) {
        return;
      }
      this.windowMovementState.delete(direction);
    };
    window.addEventListener("keydown", this.windowKeyDownHandler);
    window.addEventListener("keyup", this.windowKeyUpHandler);
    this.windowKeyHandlersInstalled = true;
  }

  movementPressed(targetState, direction) {
    const phaserPressed = safeArray(targetState.movementKeys.get(direction)).some((key) => key.isDown);
    return phaserPressed || this.windowMovementState.has(direction);
  }

  tickLocalPov() {
    if (!this.povController.localPovEnabled() || this.viewMode !== "pov") {
      return;
    }
    const movementConfig = this.povController.povConfig()?.movement || {};
    if (!movementConfig.enabled) {
      return;
    }
    const now = this.time.now;
    if (now - this.localPovState.lastStepAt < Number(movementConfig.step_cooldown_ms || 180)) {
      return;
    }

    const intents = [
      { direction: "up", dx: 0, dy: -1 },
      { direction: "down", dx: 0, dy: 1 },
      { direction: "left", dx: -1, dy: 0 },
      { direction: "right", dx: 1, dy: 0 },
    ];
    const nextIntent = intents.find(({ direction }) => this.movementPressed(this.localPovState, direction));
    if (!nextIntent) {
      return;
    }
    if (this.povController.attemptLocalMove(nextIntent)) {
      this.localPovState.lastStepAt = now;
    }
  }

  tickLiveSession() {
    if (!this.liveState.enabled || !this.liveState.sessionId || this.viewMode !== "pov") {
      return;
    }
    if (this.liveUiController.liveInputFreezeActive()) {
      this.liveMovementController.clearMovementInputs(this.liveState);
      return;
    }
    const movementConfig = this.povController.povConfig()?.movement || {};
    if (movementConfig.enabled === false) {
      return;
    }
    const now = this.time.now;
    const intents = [
      { direction: "up", action_type: "move", actionText: "", payload: { direction: "up" } },
      { direction: "down", action_type: "move", actionText: "", payload: { direction: "down" } },
      { direction: "left", action_type: "move", actionText: "", payload: { direction: "left" } },
      { direction: "right", action_type: "move", actionText: "", payload: { direction: "right" } },
    ];
    const nextIntent = intents.find(({ direction }) => this.movementPressed(this.liveState, direction));
    if (!nextIntent) {
      return;
    }
    const liveStepCooldownMs = this.liveMovementController.effectiveLiveStepCooldown(movementConfig);
    if (now - this.liveState.lastStepAt < liveStepCooldownMs) {
      return;
    }
    const submitted = this.liveMovementController.submitPendingLiveMove(
      nextIntent.direction,
      `${this.selectedAgentRecord?.display_name || "agent"} moves ${nextIntent.direction}.`,
    );
    if (submitted) {
      this.liveState.lastStepAt = now;
    }
  }





  liveMoveLeadSnapshot() {
    const predictedClaimedAgent = this.controllerAgentRecord();
    const authoritativeClaimedAgent = this.controllerAgentRecord({ authoritative: true });
    const pendingMoves = safeArray(this.liveState.pendingMoves);
    const pendingCount = pendingMoves.length;
    const lastQueuedDirection = firstNonEmpty(pendingMoves[pendingCount - 1]?.direction, "");
    if (!predictedClaimedAgent || !authoritativeClaimedAgent) {
      return {
        pendingCount,
        leadTiles: pendingCount,
        roomMismatch: false,
        lastQueuedDirection,
      };
    }
    const roomMismatch = firstNonEmpty(predictedClaimedAgent.room_id, "") !== firstNonEmpty(authoritativeClaimedAgent.room_id, "");
    const leadTiles = roomMismatch
      ? Math.max(1, pendingCount)
      : (
        Math.abs(Number(predictedClaimedAgent.coordinates?.x ?? 0) - Number(authoritativeClaimedAgent.coordinates?.x ?? 0))
        + Math.abs(Number(predictedClaimedAgent.coordinates?.y ?? 0) - Number(authoritativeClaimedAgent.coordinates?.y ?? 0))
      );
    return {
      pendingCount,
      leadTiles,
      roomMismatch,
      lastQueuedDirection,
    };
  }





  playMovementAnimation(agentId, direction) {
    const animations = this.povController.povConfig()?.movement?.animations || {};
    const walkCandidates = [
      firstNonEmpty(animations[direction], ""),
      `walk_${direction}`,
      direction === "up" ? "walk_right" : "walk_down",
      "walk_down",
    ].filter(Boolean);
    const walkState = walkCandidates.find((stateName) => this.agentManager.hasAgentAnimation(agentId, stateName)) || "walk_down";
    const idleCandidates = [firstNonEmpty(animations.idle, ""), "idle_down"].filter(Boolean);
    const idleState = idleCandidates.find((stateName) => this.agentManager.hasAgentAnimation(agentId, stateName)) || "idle_down";
    this.agentManager.setAgentAnimation(agentId, walkState);
    if (this.localPovState.idleResetTimer) {
      this.localPovState.idleResetTimer.remove(false);
    }
    this.localPovState.idleResetTimer = this.time.delayedCall(130, () => {
      this.agentManager.setAgentAnimation(agentId, idleState);
    });
  }

  seedLocalPovAgentState() {
    safeArray(this.currentAgents).forEach((agent) => {
      const mainConfig = this.mainCharacterConfigs.get(agent.agent_id);
      const rawInventory = mainConfig?.inventory || agent.inventory;
      const inventory = safeArray(rawInventory).map((entry) => {
        const itemMeta = this.itemCatalog.get(entry.item_id) || {};
        return {
          item_id: entry.item_id,
          quantity: Number(entry.quantity || 0),
          name: firstNonEmpty(entry.name, itemMeta.name, entry.item_id, "Item"),
          description: firstNonEmpty(entry.description, itemMeta.description, ""),
        };
      });
      this.localPovState.agentState.set(agent.agent_id, {
        inventory,
        currency_quantity: Number(mainConfig?.currency_quantity || agent.currency_quantity || 0),
        recent_dialogue: [],
      });
    });
  }

}
