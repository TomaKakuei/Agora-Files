import { firstNonEmpty, safeArray, escapeHtml, agentInitials, newClientActionId, primaryAgentImage, Phaser } from "./utils.js";

export class LiveUiController {
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

  refreshLiveUi({ force = false } = {}) {
    if (!this.isLiveSessionMode()) {
      this.refreshImmersiveHud();
      this.refreshLocalInteractionPanels();
      return;
    }
    const refreshIfChanged = (key, callback) => {
      const signature = this.liveSignature(key);
      if (force || this.liveUiSignatures[key] !== signature) {
        this.liveUiSignatures[key] = signature;
        callback();
      }
    };
    refreshIfChanged("movement", () => this.renderMovementModule());
    refreshIfChanged("items", () => this.renderItemModule());
    refreshIfChanged("trade", () => this.refreshTradeModule());
    refreshIfChanged("dialogue", () => this.renderDialogueModule());
    refreshIfChanged("log", () => this.renderActionLog());
    refreshIfChanged("hud", () => this.refreshImmersiveHud());
    refreshIfChanged("selector", () => this.renderAgentSelector());
    refreshIfChanged("pending", () => this.renderPendingActions());
    refreshIfChanged("target", () => this.renderSelectedTargetBubble());
  }

  refreshImmersiveHud() {
    const hud = document.getElementById("pov-hud");
    if (!hud) {
      return;
    }
    if (this.freezeLiveComposerPanels()) {
      return;
    }
    const agent = this.controllerAgentRecord();
    if (!agent) {
      hud.innerHTML = '<div class="muted">Selecting a guild member...</div>';
      this.renderAgentSelector();
      this.renderSelectedTargetBubble();
      return;
    }
    const inventory = safeArray(agent.inventory).filter((entry) => Number(entry.quantity || 0) > 0);
    const room = this.roomLookup.get(agent.room_id || "");
    const portrait = primaryAgentImage(agent);
    hud.innerHTML = `
      <div class="pov-card">
        <div class="agent-bubble-head">
          ${portrait?.image_url
            ? `<img class="agent-photo" src="${escapeHtml(portrait.image_url)}" alt="${escapeHtml(agent.display_name)}" data-controller-photo="true" />`
            : `<div class="agent-photo-fallback">${escapeHtml(agentInitials(agent))}</div>`}
          <div class="agent-bubble-copy">
            <div class="agent-bubble-title">${escapeHtml(agent.display_name)}</div>
            <div class="agent-bubble-subline">${escapeHtml(agent.role_name || "Agent")} · ${escapeHtml(room?.name || agent.room_id || "unknown room")}</div>
            <div class="agent-bubble-text">${escapeHtml(agent.current_focus || agent.activity_directive || "Holding position inside the world.")}</div>
          </div>
        </div>
        <div class="module-chip-row">
          <span class="pov-badge">${escapeHtml(this.isLiveSessionMode() ? "Claimed Agent" : "Controller")}</span>
          <span class="module-chip">View ${escapeHtml(this.viewMode === "pov" ? "POV" : "Atlas")}</span>
          <span class="module-chip">Items ${inventory.length}</span>
          <span class="module-chip">Target ${escapeHtml(this.targetBubbleAgent()?.display_name || "none")}</span>
        </div>
        <div class="pov-stat-grid">
          <div class="pov-stat">
            <div class="pov-stat-label">Immediate Goal</div>
            <div class="pov-stat-value">${escapeHtml(agent.activity_directive || "No directive broadcast.")}</div>
          </div>
          <div class="pov-stat">
            <div class="pov-stat-label">Memory Drift</div>
            <div class="pov-stat-value">${escapeHtml(agent.mainline_summary || "No public summary available yet.")}</div>
          </div>
        </div>
        ${this.isLiveSessionMode() ? `
          <div class="module-card">
            <div class="module-copy">The composer stays pinned above so typing stays stable while the room updates.</div>
            <div class="module-chip-row">
              <button class="mini-button" type="button" data-open-live-composer>Focus Composer</button>
            </div>
          </div>
        ` : ""}
      </div>
    `;
    if (this.isLiveSessionMode()) {
      hud.querySelector("[data-open-live-composer]")?.addEventListener("click", () => {
        this.focusPrimaryLiveComposer();
      });
    }
    if (portrait?.image_url && this.openImageModal) {
      hud.querySelector("[data-controller-photo]")?.addEventListener("click", () => {
        this.openImageModal(portrait);
      });
    }
    this.renderAgentSelector();
    this.renderSelectedTargetBubble();
    this.refreshLocalInteractionPanels();
  }

  renderAgentSelector() {
    const container = document.getElementById("agent-selector");
    if (!container) {
      return;
    }
    const controller = this.isLiveSessionMode()
      ? this.controllerAgentRecord({ authoritative: true })
      : this.controllerAgentRecord();
    if (!controller) {
      container.innerHTML = '<div class="muted">No object agent is available yet.</div>';
      return;
    }

    let visibleTargets = [];
    if (this.isLiveSessionMode()) {
      visibleTargets = this.activeAgentRecords({ authoritative: true })
        .filter((agent) => agent.agent_id !== controller.agent_id)
        .filter((agent) => agent.room_id === controller.room_id);
    } else {
      visibleTargets = this.nearbyAgentsFor(controller, this.povConfig()?.dialogue?.interaction_radius_tiles || 99);
    }
    visibleTargets = visibleTargets
      .slice()
      .sort((left, right) => left.display_name.localeCompare(right.display_name));

    const selectedTarget = this.isLiveSessionMode()
      ? this.targetBubbleAgent({ authoritative: true })
      : this.targetBubbleAgent();
    if (selectedTarget && !visibleTargets.some((agent) => agent.agent_id === selectedTarget.agent_id)) {
      if (this.isLiveSessionMode()) {
        this.liveState.targetAgentId = "";
      } else {
        this.localPovState.dialogueTargetId = "";
      }
    }
    const resolvedTargetId = (this.isLiveSessionMode()
      ? this.targetBubbleAgent({ authoritative: true })
      : this.targetBubbleAgent())?.agent_id || "";

    container.innerHTML = `
      <div class="selector-card">
        <div class="module-copy">Pick the object agent that dialogue, trade, and target-aware actions should use.</div>
        <select class="agent-selector-select" ${visibleTargets.length ? "" : "disabled"} data-agent-selector>
          <option value="">No object target</option>
          ${visibleTargets.map((agent) => `<option value="${escapeHtml(agent.agent_id)}" ${agent.agent_id === resolvedTargetId ? "selected" : ""}>${escapeHtml(agent.display_name)} · ${escapeHtml(agent.role_name || "Agent")}</option>`).join("")}
        </select>
        <div class="module-chip-row">
          <span class="module-chip">Controller: ${escapeHtml(controller.display_name)}</span>
          <span class="module-chip">Visible Targets: ${visibleTargets.length}</span>
        </div>
      </div>
    `;
    container.querySelector("[data-agent-selector]")?.addEventListener("change", (event) => {
      const nextId = String(event.target.value || "").trim();
      this.setDialogueTarget(nextId);
      const target = this.isLiveSessionMode()
        ? this.agentRecordById(nextId, { authoritative: true })
        : this.currentAgents.find((agent) => agent.agent_id === nextId) || null;
      if (target?.room_id && this.viewMode === "atlas") {
        this.focusRoom(target.room_id, { zoom: 0.82 });
      } else {
        this.renderSelectedTargetBubble();
      }
    });
  }

  renderSelectedTargetBubble() {
    const shell = document.getElementById("selected-target-bubble");
    const container = document.getElementById("selected-target-card");
    if (!shell || !container) {
      return;
    }
    const target = this.targetBubbleAgent({ authoritative: this.isLiveSessionMode() });
    if (!target) {
      shell.classList.add("is-hidden");
      container.innerHTML = '<div class="muted">Choose an object agent to inspect.</div>';
      return;
    }
    shell.classList.remove("is-hidden");
    container.innerHTML = `
      ${this.agentSummaryMarkup(target, { showInventory: true, compact: true })}
      <div class="agent-bubble-actions">
        <span class="module-chip">Targeting ${escapeHtml(target.display_name)}</span>
        <button class="mini-button" type="button" data-clear-target="true">Clear</button>
      </div>
    `;
    container.querySelector("[data-clear-target]")?.addEventListener("click", () => {
      this.setDialogueTarget("");
      this.renderAgentSelector();
    });
    const portrait = primaryAgentImage(target);
    if (portrait?.image_url && this.openImageModal) {
      container.querySelector("[data-agent-photo]")?.addEventListener("click", () => {
        this.openImageModal(portrait);
      });
    }
  }

  syncLiveComposerElements(roomAgents, targetAgentId) {
    const composer = this.ensureLiveComposerElements();
    const { targetSelect, input } = composer;
    const previousValue = String(targetSelect.value || "");
    targetSelect.innerHTML = "";
    const broadcastOption = document.createElement("option");
    broadcastOption.value = "";
    broadcastOption.textContent = "Room broadcast";
    targetSelect.appendChild(broadcastOption);
    roomAgents.forEach((agent) => {
      const option = document.createElement("option");
      option.value = agent.agent_id;
      option.textContent = agent.display_name;
      targetSelect.appendChild(option);
    });
    const resolvedTarget = roomAgents.some((agent) => agent.agent_id === targetAgentId)
      ? targetAgentId
      : (roomAgents.some((agent) => agent.agent_id === previousValue) ? previousValue : "");
    this.liveState.targetAgentId = resolvedTarget;
    targetSelect.value = resolvedTarget;
    if (String(input.value || "") !== String(this.liveState.actionDraft || "")) {
      input.value = String(this.liveState.actionDraft || "");
    }
    return composer;
  }

  armLiveComposerFocusGuard(selector) {
    void selector;
  }

  showSpeechBubble(agentId, text) {
    const sprite = this.agentManager.agentSprites.get(agentId);
    if (!sprite) {
      return;
    }
    const existing = this.localPovState.speechBubbles.get(agentId);
    if (existing?.container) {
      existing.container.destroy();
    }
    const line = String(text || "").trim();
    const maxBubbleWidth = Math.max(220, Math.min(340, Math.round(this.scale.width * 0.28)));
    const bubbleText = this.add.text(0, 0, line, {
      fontFamily: "monospace",
      fontSize: "14px",
      color: "#f7f4ef",
      align: "center",
      wordWrap: { width: maxBubbleWidth, useAdvancedWrap: true },
    }).setOrigin(0.5, 1);
    const width = Math.max(160, Math.min(maxBubbleWidth + 28, bubbleText.width + 28));
    const height = Math.max(42, bubbleText.height + 22);
    const backdrop = this.add.rectangle(0, -height / 2 + 4, width, height, 0x1b1620, 0.9)
      .setStrokeStyle(2, 0xf0b25b, 0.82);
    const tail = this.add.triangle(0, 6, 0, 0, 14, 0, 7, 10, 0x1b1620, 0.9)
      .setStrokeStyle(2, 0xf0b25b, 0.82);
    const container = this.add.container(sprite.x, sprite.y - 82, [backdrop, tail, bubbleText]);
    container.setDepth(72);
    bubbleText.setPosition(0, -12);
    this.localPovState.speechBubbles.set(agentId, { container });
    const configuredDuration = Number(this.povConfig()?.dialogue?.bubble_duration_ms || 14000);
    const duration = Phaser.Math.Clamp(
      Math.max(configuredDuration, 9000) + Math.min(line.length, 220) * 42,
      12000,
      28000,
    );
    this.tweens.add({
      targets: container,
      y: container.y - 6,
      duration: 180,
      ease: "Sine.easeOut",
      yoyo: false,
    });
    this.time.delayedCall(duration, () => {
      this.tweens.add({
        targets: container,
        alpha: 0,
        y: container.y - 8,
        duration: 220,
        onComplete: () => {
          container.destroy();
          if (this.localPovState.speechBubbles.get(agentId)?.container === container) {
            this.localPovState.speechBubbles.delete(agentId);
          }
        },
      });
    });
  }

  surfaceLiveEventBubbles(events) {
    if (!this.isLiveSessionMode() || !safeArray(events).length) {
      return;
    }
    safeArray(events)
      .filter((entry) => Number(entry?.event_id || 0) > Number(this.liveState.lastBubbleEventId || 0))
      .forEach((entry) => {
        const eventId = Number(entry?.event_id || 0);
        const eventType = String(entry?.event_type || "").trim();
        const actorAgentId = String(entry?.agent_id || "").trim();
        const targetAgentId = String(entry?.target_agent_id || "").trim();
        const actionText = String(entry?.action_text || "").trim();
        const responseText = String(entry?.response_text || "").trim();
        if (eventType === "human_action" && actorAgentId && actionText && !/^move\b/i.test(actionText)) {
          this.showSpeechBubble(actorAgentId, actionText);
        }
        if ((eventType === "agent_response" || eventType === "room_chatter") && (targetAgentId || actorAgentId) && responseText) {
          this.showSpeechBubble(targetAgentId || actorAgentId, responseText);
        }
        this.liveState.lastBubbleEventId = Math.max(Number(this.liveState.lastBubbleEventId || 0), eventId);
      });
  }

  showLiveErrorOverlay({ title, message, badge = "LIVE FAILURE" }) {
    const overlay = this.ensureLiveErrorOverlay();
    overlay.badge.textContent = String(badge || "LIVE FAILURE");
    overlay.title.textContent = String(title || "Live Error");
    overlay.body.textContent = String(message || "Unknown live error.");
    overlay.root.style.display = "flex";
    overlay.root.setAttribute("aria-hidden", "false");
    console.error(String(title || "Live Error"), String(message || "Unknown live error."));
  }

  hideLiveErrorOverlay() {
    if (!this.liveErrorOverlay?.root) {
      return;
    }
    this.liveErrorOverlay.root.style.display = "none";
    this.liveErrorOverlay.root.setAttribute("aria-hidden", "true");
  }

  refreshWorldNotes() {
    const worldName =
      this.runtimeState?.world_name || this.liveState.state?.world_name || this.assetSetManifest?.world_name || this.worldConfig?.scenario_meta?.world_name || "Agora World";
    document.getElementById("world-name").textContent = worldName;

    const notes = document.getElementById("world-notes");
    if (!notes) {
      if (this.runtimeState) {
        document.getElementById("event-status").textContent = `Watching ${this.runtimeState.run_id}`;
      } else if (this.isLiveSessionMode()) {
        document.getElementById("event-status").textContent = `Live session ${this.liveState.sessionId || "starting"}`;
      } else if (this.assetSetRevision()) {
        document.getElementById("event-status").textContent = `Loaded asset set ${this.assetSetRevision()}`;
      }
      return;
    }
    notes.innerHTML = "";
    const agentCount = this.currentAgents.length || this.frontendBootstrap?.agent_count || 0;
    const worldWidth = Number(this.worldDimensions?.width || 0);
    const worldHeight = Number(this.worldDimensions?.height || 0);
    const lines = [
      this.runtimeState
        ? `Run: ${this.runtimeState.run_id} (${this.runtimeState.status}${this.runtimeState.round_index ? ` / round ${this.runtimeState.round_index}` : ""})`
        : this.isLiveSessionMode()
          ? `Session: ${this.liveState.sessionId || "pending"} (${this.liveState.session?.status || "active"})`
        : "Run: bootstrap sample data",
      `Mode: ${this.runtimeState ? "live" : this.isLiveSessionMode() ? "live session" : this.runtimeMode}`,
      `Rooms: ${safeArray(this.mapGrid?.rooms).length}`,
      `Agents: ${agentCount}`,
      `Tile size: ${this.mapGrid?.map_visual?.tile_width || 32}x${this.mapGrid?.map_visual?.tile_height || 32}`,
      `Render scale: ${this.mapGrid?.map_visual?.render_scale || 1}x`,
      `World canvas: ${Math.round(worldWidth)}x${Math.round(worldHeight)}`,
      `Style: ${this.mapGrid?.map_visual?.style || "pixel_art"}`,
    ];
    if (!this.runtimeState && this.assetSetRevision()) {
      lines.push(`Asset Set: ${this.assetSetRevision()}`);
    }
    if (this.isLiveSessionMode() && this.liveState.state?.room) {
      lines.push(`Claimed Agent: ${this.liveState.session?.claimed_agent_id || "unknown"}`);
      lines.push(`Current Room: ${this.liveState.state.room.room_id || "unknown"}`);
      lines.push(`Active In Room: ${safeArray(this.liveState.state.active_room_agents).length}`);
    }
    if (this.runtimeState?.updated_at) {
      lines.push(`Updated: ${this.runtimeState.updated_at}`);
    } else if (this.isLiveSessionMode() && this.liveState.state?.updated_at) {
      lines.push(`Updated: ${this.liveState.state.updated_at}`);
    }
    lines.forEach((text) => {
      const item = document.createElement("div");
      item.className = "info-item";
      item.textContent = text;
      notes.appendChild(item);
    });
    if (this.runtimeState) {
      document.getElementById("event-status").textContent = `Watching ${this.runtimeState.run_id}`;
    } else if (this.isLiveSessionMode()) {
      document.getElementById("event-status").textContent = `Live session ${this.liveState.sessionId || "starting"}`;
    } else if (this.assetSetRevision()) {
      document.getElementById("event-status").textContent = `Loaded asset set ${this.assetSetRevision()}`;
    }
  }

  updateStreamingBubble(agentId, text, isThinking) {
    const sprite = this.agentManager.agentSprites.get(agentId);
    if (!sprite) return;

    let existing = this.localPovState.speechBubbles.get(agentId);
    let bubbleText, backdrop, tail, container;
    
    const maxBubbleWidth = Math.max(220, Math.min(340, Math.round(this.scale.width * 0.28)));
    const textColor = isThinking ? "#aaaaaa" : "#f7f4ef";

    if (existing?.container && existing?.isStreaming) {
      container = existing.container;
      bubbleText = existing.bubbleText;
      backdrop = existing.backdrop;
      tail = existing.tail;
      
      if (!isThinking) {
        bubbleText.text = text;
      } else {
        bubbleText.text = text;
      }
      bubbleText.setColor(textColor);
      
      const width = Math.max(160, Math.min(maxBubbleWidth + 28, bubbleText.width + 28));
      const height = Math.max(42, bubbleText.height + 22);
      
      backdrop.setSize(width, height);
      backdrop.setPosition(0, -height / 2 + 4);
      
      if (existing.timeoutId) {
        clearTimeout(existing.timeoutId);
      }
      
    } else {
      if (existing?.container) {
        existing.container.destroy();
      }
      
      bubbleText = this.add.text(0, 0, text, {
        fontFamily: "monospace",
        fontSize: "14px",
        color: textColor,
        align: "center",
        wordWrap: { width: maxBubbleWidth, useAdvancedWrap: true },
      }).setOrigin(0.5, 1);
      
      const width = Math.max(160, Math.min(maxBubbleWidth + 28, bubbleText.width + 28));
      const height = Math.max(42, bubbleText.height + 22);
      
      backdrop = this.add.rectangle(0, -height / 2 + 4, width, height, 0x1b1620, 0.9)
        .setStrokeStyle(2, 0x76b900, 0.82); 
      tail = this.add.triangle(0, 6, 0, 0, 14, 0, 7, 10, 0x1b1620, 0.9)
        .setStrokeStyle(2, 0x76b900, 0.82);
        
      container = this.add.container(sprite.x, sprite.y - 82, [backdrop, tail, bubbleText]);
      container.setDepth(72);
      bubbleText.setPosition(0, -12);
      
      this.localPovState.speechBubbles.set(agentId, { 
        container, 
        bubbleText, 
        backdrop, 
        tail, 
        isStreaming: true 
      });
      
      this.tweens.add({
        targets: container,
        y: container.y - 6,
        duration: 180,
        ease: "Sine.easeOut",
        yoyo: false,
      });
    }

    if (!isThinking) {
      existing = this.localPovState.speechBubbles.get(agentId);
      if (existing) {
        const configuredDuration = Number(this.povConfig()?.dialogue?.bubble_duration_ms || 14000);
        const duration = Phaser.Math.Clamp(
          Math.max(configuredDuration, 9000) + Math.min(text.length, 220) * 42,
          12000,
          28000,
        );
        
        existing.timeoutId = setTimeout(() => {
          if (this.localPovState.speechBubbles.get(agentId)?.container === container) {
            this.localPovState.speechBubbles.delete(agentId);
            this.tweens.add({
              targets: container,
              alpha: 0,
              y: container.y - 12,
              duration: 350,
              onComplete: () => {
                container.destroy();
              },
            });
          }
        }, duration);
      }
    }
  }

  handleAiThinking(payload) {
    const targetAgentId = payload?.target_agent_id;
    if (!targetAgentId) return;
    const agent = this.agentManager.agentSprites.get(targetAgentId)?.getData("agent");
    const name = agent?.display_name || "Agent";
    this.updateStreamingBubble(targetAgentId, "...", true);
  }

  handleAiStreamChunk(payload) {
    const targetAgentId = payload?.target_agent_id;
    if (!targetAgentId) return;
    const chunk = String(payload?.chunk || "");
    this.updateStreamingBubble(targetAgentId, chunk, false);
  }

  focusPrimaryLiveComposer() {
    const input = document.querySelector("[data-live-message-input]");
    if (!(input instanceof HTMLInputElement)) {
      return;
    }
    input.scrollIntoView({ block: "nearest", inline: "nearest" });
    input.focus({ preventScroll: true });
    const caret = String(input.value || "").length;
    try {
      input.setSelectionRange(caret, caret);
    } catch (error) {
      // Ignore browsers that reject selection updates during focus handoff.
    }
  }

  freezeLiveComposerPanels() {
    return this.isLiveSessionMode()
      && this.liveInputFreezeActive()
      && Boolean(document.querySelector("[data-live-message-input]"));
  }

  handleLiveComposerBlur(selector) {
    const input = document.querySelector(selector);
    this.liveState.isComposingText = false;
    if (!(input instanceof HTMLInputElement) || !String(input.value || "").trim()) {
      this.liveState.typingFreezeActive = false;
      if (this.input?.keyboard) {
        this.input.keyboard.enabled = true;
      }
      this.flushFrozenLiveState();
    }
  }

  captureLiveComposerFocus() {
    const active = document.activeElement;
    if (active instanceof HTMLInputElement && active.matches("[data-live-message-input]")) {
      return {
        selector: "[data-live-message-input]",
        value: active.value,
        selectionStart: active.selectionStart,
        selectionEnd: active.selectionEnd,
        restoreFocus: true,
      };
    }
    const fallbackInput = document.querySelector("[data-live-message-input]");
    const passiveActiveTarget = !active || active === document.body || active === document.documentElement;
    if (!passiveActiveTarget || !(fallbackInput instanceof HTMLInputElement) || !fallbackInput.value) {
      return null;
    }
    return {
      selector: "[data-live-message-input]",
      value: fallbackInput.value,
      selectionStart: fallbackInput.selectionStart,
      selectionEnd: fallbackInput.selectionEnd,
      restoreFocus: true,
    };
  }

  submitPrimaryLiveComposer() {
    const composer = this.ensureLiveComposerElements();
    const input = composer?.input;
    if (!(input instanceof HTMLInputElement)) {
      return;
    }
    const text = String(input.value || "").trim();
    if (!text) {
      return;
    }
    const targetAgentId = this.liveState.targetAgentId || "";
    const targetLabel = this.dialogueTargetRecord({ authoritative: true })?.display_name || "";
    const clientActionId = newClientActionId();
    // Clear the composer immediately once the request is on its way; the pending row
    // stays visible until the matching server events arrive for this client_action_id.
    this.queuePendingLiveMessage({
      clientActionId,
      actionText: text,
      targetAgentId,
      targetLabel,
    });
    input.value = "";
    this.liveState.actionDraft = "";
    this.liveState.isComposingText = false;
    this.liveState.typingFreezeActive = false;
    if (this.input?.keyboard) {
      this.input.keyboard.enabled = true;
    }
    this.flushFrozenLiveState({ force: true });
    void this.submitLiveAction({
      action_type: "message",
      client_action_id: clientActionId,
      action_text: text,
      target_agent_id: targetAgentId,
    }).then(() => {
      this.renderDialogueModule();
    }).catch((error) => {
      this.removePendingLiveMessage(clientActionId);
      input.value = text;
      this.liveState.actionDraft = text;
      this.liveState.isComposingText = false;
      this.beginLiveComposerFreeze();
      document.getElementById("event-status").textContent = error?.message || "Live message failed";
    });
  }

  beginLiveComposerFreeze() {
    if (!this.isLiveSessionMode()) {
      return;
    }
    this.liveState.typingFreezeActive = true;
    if (this.input?.keyboard) {
      this.input.keyboard.enabled = false;
    }
    this.clearMovementInputs(this.liveState);
  }

  liveInputFreezeActive() {
    if (!this.isLiveSessionMode()) {
      return false;
    }
    if (this.liveState.isComposingText) {
      return true;
    }
    if (this.liveState.typingFreezeActive && String(this.liveState.actionDraft || "").trim()) {
      return true;
    }
    const active = document.activeElement;
    if (
      active instanceof HTMLInputElement &&
      active.matches("[data-live-message-input]") &&
      String(active.value || "").trim()
    ) {
      return true;
    }
    const draft = String(this.liveState.actionDraft || "").trim();
    if (!draft) {
      return false;
    }
    const fallbackInput = document.querySelector("[data-live-message-input]");
    return fallbackInput instanceof HTMLInputElement && String(fallbackInput.value || "").trim() === draft;
  }

  targetBubbleAgent({ authoritative = false } = {}) {
    const target = this.dialogueTargetRecord({ authoritative });
    const controller = this.controllerAgentRecord({ authoritative });
    if (!target) {
      return null;
    }
    if (controller?.agent_id && target.agent_id === controller.agent_id) {
      return null;
    }
    return target;
  }

  pendingLiveSpeechEntries() {
    return safeArray(this.liveState.pendingMessages)
      .slice()
      .sort((left, right) => Number(right?.createdAt || 0) - Number(left?.createdAt || 0))
      .map((entry) => ({
        type: "pending",
        text: firstNonEmpty(entry?.actionText, "Pending live message."),
        pending: true,
        clientActionId: firstNonEmpty(entry?.clientActionId, ""),
        targetLabel: firstNonEmpty(entry?.targetLabel, ""),
      }));
  }

}
