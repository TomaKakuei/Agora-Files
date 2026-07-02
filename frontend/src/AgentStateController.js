import { firstNonEmpty, safeArray, tileKey } from "./utils.js";

export class AgentStateController {
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

  localAgentState(agentId) {
    if (!this.localPovState.agentState.has(agentId)) {
      this.localPovState.agentState.set(agentId, { inventory: [], currency_quantity: 0, recent_dialogue: [] });
    }
    return this.localPovState.agentState.get(agentId);
  }






  nearbyAgentsFor(agent, radiusOverride = null) {
    if (!agent) {
      return [];
    }
    const visibleRadius = Number((radiusOverride ?? this.povController.povConfig()?.visible_radius_tiles) || 99);
    const roomPeers = this.currentAgents.filter(
      (candidate) => candidate.agent_id !== agent.agent_id && candidate.room_id === agent.room_id,
    );
    const withDistance = roomPeers.map((candidate) => {
      const dx = Number(candidate.coordinates?.x ?? 0) - Number(agent.coordinates?.x ?? 0);
      const dy = Number(candidate.coordinates?.y ?? 0) - Number(agent.coordinates?.y ?? 0);
      return {
        ...candidate,
        distance: Math.abs(dx) + Math.abs(dy),
      };
    });
    return withDistance
      .filter((candidate) => candidate.distance <= visibleRadius)
      .sort((left, right) => left.distance - right.distance || left.display_name.localeCompare(right.display_name));
  }


  agentRecordById(agentId, { authoritative = false } = {}) {
    const normalizedAgentId = firstNonEmpty(agentId, "");
    if (!normalizedAgentId) {
      return null;
    }
    return this.povController.activeAgentRecords({ authoritative })
      .find((agent) => agent.agent_id === normalizedAgentId) || null;
  }

  dialogueTargetRecord({ authoritative = false } = {}) {
    if (this.liveSessionManager.isLiveSessionMode()) {
      return this.agentRecordById(this.liveState.targetAgentId, { authoritative }) || null;
    }
    return this.currentAgents.find((agent) => agent.agent_id === this.localPovState.dialogueTargetId) || null;
  }

  pulseAgentResponse(agentId, otherAgentId = "") {
    const sprite = this.agentManager.agentSprites.get(agentId);
    if (!sprite) {
      return;
    }
    const responseMs = Number(this.povController.povConfig()?.dialogue?.response_animation_ms || 480);
    const agent = this.currentAgents.find((candidate) => candidate.agent_id === agentId);
    const other = otherAgentId ? this.currentAgents.find((candidate) => candidate.agent_id === otherAgentId) : null;
    let facingState = "walk_down";
    if (agent && other) {
      const dx = Number(other.coordinates?.x ?? 0) - Number(agent.coordinates?.x ?? 0);
      if (Math.abs(dx) > 0) {
        facingState = dx >= 0 ? "walk_right" : "walk_left";
      }
    }
    this.agentManager.setAgentAnimation(agentId, facingState);
    this.tweens.add({
      targets: sprite,
      scaleX: sprite.scaleX * 1.08,
      scaleY: sprite.scaleY * 1.08,
      y: sprite.y - 6,
      duration: Math.max(120, responseMs / 2),
      yoyo: true,
      ease: "Sine.easeInOut",
      onComplete: () => {
        const idleState = this.povController.povConfig()?.movement?.animations?.idle || "idle_down";
        this.agentManager.setAgentAnimation(agentId, idleState);
      },
    });
  }

  liveAgentDigest(agent) {
    if (!agent) {
      return "";
    }
    const inventory = safeArray(agent.inventory)
      .map((item) => `${item.item_id}:${Number(item.quantity || 0)}:${item.name || ""}`)
      .join(",");
    const coords = agent.coordinates || {};
    return [
      agent.agent_id,
      agent.display_name,
      agent.room_id,
      Number(coords.x ?? 0),
      Number(coords.y ?? 0),
      Number(coords.z ?? 0),
      agent.current_focus || "",
      agent.mainline_summary || "",
      agent.live_motion_mode || agent.control_mode || "",
      inventory,
    ].join("|");
  }



  restoreLiveComposerFocus(snapshot) {
    if (!snapshot) {
      return;
    }
    const input = document.querySelector(snapshot.selector);
    if (!input || !(input instanceof HTMLInputElement)) {
      return;
    }
    input.value = snapshot.value;
    this.liveState.actionDraft = snapshot.value;
    if (snapshot.restoreFocus) {
      try {
        input.ownerDocument?.defaultView?.focus();
        input.ownerDocument?.defaultView?.frameElement?.focus?.();
      } catch (error) {
        // Headless iframes can reject window focus while the parent harness is polling.
      }
      input.focus({ preventScroll: true });
      try {
        input.setSelectionRange(snapshot.selectionStart, snapshot.selectionEnd);
      } catch (error) {
        // Some browsers reject selection restoration for unfocused inputs.
      }
    }
  }



  controllerAgentRecord({ authoritative = false } = {}) {
    const activeAgents = this.povController.activeAgentRecords({ authoritative });
    const claimedAgentId = firstNonEmpty(this.liveState.session?.claimed_agent_id, "");
    const selectedAgent = this.selectedAgentRecord?.agent_id
      ? activeAgents.find((agent) => agent.agent_id === this.selectedAgentRecord.agent_id) || null
      : null;
    if (claimedAgentId) {
      return activeAgents.find((agent) => agent.agent_id === claimedAgentId)
        || selectedAgent
        || activeAgents.find((agent) => agent.main_character)
        || activeAgents[0]
        || null;
    }
    const protagonistId = firstNonEmpty(this.povController.protagonistAgentId(), "");
    if (protagonistId) {
      return activeAgents.find((agent) => agent.agent_id === protagonistId)
        || selectedAgent
        || activeAgents[0]
        || null;
    }
    return selectedAgent
      || activeAgents.find((agent) => agent.main_character)
      || activeAgents[0]
      || null;
  }


}
