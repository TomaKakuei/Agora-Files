import { firstNonEmpty, safeArray, tileKey, liveEventPayload, newClientActionId, routeLabel, escapeHtml, agentInitials, primaryAgentImage } from "./utils.js";

export class LiveComposerUi {
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

  ensureLiveComposerElements() {
    if (this.liveComposerElements?.wrapper?.isConnected !== false && this.liveComposerElements?.input && this.liveComposerElements?.sendButton && this.liveComposerElements?.targetSelect) {
      return this.liveComposerElements;
    }
    const wrapper = document.createElement("div");
    wrapper.className = "live-composer";

    const targetSelect = document.createElement("select");
    targetSelect.className = "live-target-select composer-target-select";
    targetSelect.dataset.liveTargetSelect = "true";
    targetSelect.addEventListener("change", (event) => {
      this.liveState.targetAgentId = event.target.value || "";
    });

    const input = document.createElement("input");
    input.className = "live-message-input";
    input.type = "text";
    input.maxLength = 220;
    input.placeholder = "Speak into the room...";
    input.dataset.liveMessageInput = "true";
    input.addEventListener("compositionstart", () => {
      this.liveState.isComposingText = true;
      this.liveUiController.beginLiveComposerFreeze();
    });
    input.addEventListener("compositionend", (event) => {
      this.liveState.isComposingText = false;
      this.liveState.actionDraft = event.target.value || "";
      if (!this.liveState.actionDraft) {
        this.liveState.typingFreezeActive = false;
        if (this.input?.keyboard) {
          this.input.keyboard.enabled = true;
        }
        this.liveSessionManager.flushFrozenLiveState();
        return;
      }
      this.liveUiController.beginLiveComposerFreeze();
    });
    input.addEventListener("input", (event) => {
      this.liveState.actionDraft = event.target.value || "";
      if (event.isComposing || this.liveState.isComposingText) {
        this.liveUiController.beginLiveComposerFreeze();
        return;
      }
      if (!this.liveState.actionDraft) {
        this.liveState.typingFreezeActive = false;
        if (this.input?.keyboard) {
          this.input.keyboard.enabled = true;
        }
        this.liveSessionManager.flushFrozenLiveState();
      } else {
        this.liveUiController.beginLiveComposerFreeze();
      }
    });
    input.addEventListener("blur", () => {
      this.liveUiController.handleLiveComposerBlur("[data-live-message-input]");
    });
    input.addEventListener("keydown", (event) => {
      event.stopPropagation();
      this.liveUiController.beginLiveComposerFreeze();
      if (event.isComposing || this.liveState.isComposingText || event.keyCode === 229) {
        return;
      }
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        this.liveUiController.submitPrimaryLiveComposer();
      }
    });
    input.addEventListener("keyup", (event) => {
      event.stopPropagation();
    });

    const sendButton = document.createElement("button");
    sendButton.className = "mini-button";
    sendButton.type = "button";
    sendButton.dataset.liveSendMessage = "true";
    sendButton.textContent = "Send";
    sendButton.addEventListener("click", () => {
      this.liveUiController.submitPrimaryLiveComposer();
    });

    wrapper.appendChild(targetSelect);
    wrapper.appendChild(input);
    wrapper.appendChild(sendButton);
    this.liveComposerElements = { wrapper, targetSelect, input, sendButton };
    return this.liveComposerElements;
  }





  renderMovementModule() {
    const container = document.getElementById("movement-module");
    if (!container) {
      return;
    }
    if (this.liveUiController.freezeLiveComposerPanels()) {
      return;
    }
    if (this.liveSessionManager.isLiveSessionMode()) {
      const session = this.liveState.session || {};
      const agent = this.currentAgents.find((candidate) => candidate.agent_id === session.claimed_agent_id) || this.selectedAgentRecord;
      const room = this.roomLookup.get(agent?.room_id || this.selectedRoomId || "");
      const target = this.dialogueTargetRecord({ authoritative: true });
      const targetTask = target?.active_task || null;
      const moveRoutes = this.liveSessionManager.liveAvailableRoutes("move");
      const selectedMoveRouteId = moveRoutes.some((route) => route.route_id === this.liveState.selectedMoveRouteId)
        ? this.liveState.selectedMoveRouteId
        : (moveRoutes[0]?.route_id || "");
      const selectedMoveRoute = moveRoutes.find((route) => route.route_id === selectedMoveRouteId) || null;
      const pendingTaskAssignments = safeArray(this.liveState.pendingTaskAssignments)
        .filter((entry) => !target || firstNonEmpty(entry?.targetAgentId, "") === target.agent_id);
      const roomOptions = Array.from(this.roomLookup.values())
        .map((entry) => `<option value="${entry.room_id}" ${entry.room_id === (this.selectedRoomId || room?.room_id || "") ? "selected" : ""}>${entry.name || entry.room_id}</option>`)
        .join("");
      container.innerHTML = `
        <div class="module-card">
          <div class="module-copy">Live session ${session.session_id || "pending"} owns ${agent?.display_name || "your avatar"}.</div>
          <div class="module-chip-row">
            <span class="module-chip">Room: ${room?.name || agent?.room_id || "unknown"}</span>
            <span class="module-chip">State: ${session.status || "active"}</span>
            <span class="module-chip">Cursor: ${this.liveState.lastEventId || 0}</span>
            <span class="module-chip">Move Routes: ${moveRoutes.length || 0}</span>
          </div>
          <div class="module-chip-row">
            <span class="module-chip">Target: ${target?.display_name || "none"}</span>
            <span class="module-chip">Target Task: ${targetTask ? `${targetTask.kind} (${targetTask.status})` : "idle"}</span>
            <span class="module-chip">Selected Route: ${selectedMoveRoute?.route_id || "none"}</span>
          </div>
          <div class="live-move-pad">
            <button class="mini-button" type="button" data-live-move="up">Move Up</button>
            <div class="live-move-row">
              <button class="mini-button" type="button" data-live-move="left">Move Left</button>
              <button class="mini-button" type="button" data-live-move="down">Move Down</button>
              <button class="mini-button" type="button" data-live-move="right">Move Right</button>
            </div>
          </div>
        </div>
        ${target ? `
          <div class="module-card">
            <div class="module-copy">Activate ${target.display_name} with the same move vocabulary the simulation uses.</div>
            ${moveRoutes.length ? `
              <div class="trade-actions">
                <select class="live-target-select" data-live-move-route>
                  ${moveRoutes.map((route) => `<option value="${route.route_id}" ${route.route_id === selectedMoveRouteId ? "selected" : ""}>${route.route_id} · ${routeLabel(route)}</option>`).join("")}
                </select>
              </div>
              <div class="module-copy">${selectedMoveRoute?.selection_guidance || selectedMoveRoute?.story_verb || routeLabel(selectedMoveRoute)}</div>
            ` : '<div class="module-copy">No DB-backed move route is available for this world.</div>'}
            <div class="trade-actions">
              <button class="mini-button" type="button" data-live-follow-target="${target.agent_id}">Follow Me</button>
            </div>
            <div class="trade-actions">
              <select class="live-target-select" data-live-task-room>
                ${roomOptions}
              </select>
              <button class="mini-button" type="button" data-live-send-target="${target.agent_id}" ${moveRoutes.length ? "" : "disabled"}>${selectedMoveRoute ? routeLabel(selectedMoveRoute) : "Go To Room"}</button>
            </div>
            ${pendingTaskAssignments.length ? `
              <div class="trade-list">
                ${pendingTaskAssignments.map((entry) => `
                  <div class="trade-card pending">
                    <div class="trade-title">${entry.targetLabel || "Agent"} queued for ${entry.destinationRoomLabel || entry.destinationRoomId || "requested room"}</div>
                    <div class="trade-copy">Queued on the move-task coordinator. The task is waiting for the single world writer to accept and persist it.</div>
                    <div class="module-chip-row">
                      <span class="module-chip">Status: queued_on_task_coordinator</span>
                      <span class="module-chip">Route: ${entry.routeId || "move"}</span>
                    </div>
                  </div>
                `).join("")}
              </div>
            ` : ""}
            ${targetTask ? `<div class="module-copy">${target.display_name} task note: ${targetTask.note || targetTask.kind}</div>` : ""}
          </div>
        ` : ""}
      `;
      container.querySelectorAll("[data-live-move]").forEach((button) => {
        button.addEventListener("click", () => {
          const direction = button.getAttribute("data-live-move") || "";
          if (!direction) {
            return;
          }
          this.liveMovementController.submitPendingLiveMove(
            direction,
            `${agent?.display_name || "agent"} moves ${direction}.`,
          );
        });
      });
      container.querySelectorAll("[data-live-follow-target]").forEach((button) => {
        button.addEventListener("click", () => {
          const targetAgentId = button.getAttribute("data-live-follow-target") || "";
          if (!targetAgentId) {
            return;
          }
          void this.liveSessionManager.submitLiveAction({
            action_type: "assign_follow_task",
            target_agent_id: targetAgentId,
            action_text: `${agent?.display_name || "agent"} asks ${target?.display_name || "the target"} to follow.`,
          }).catch((error) => {
            document.getElementById("event-status").textContent = error?.message || "Follow task failed";
          });
        });
      });
      container.querySelectorAll("[data-live-move-route]").forEach((select) => {
        select.addEventListener("change", (event) => {
          this.liveState.selectedMoveRouteId = event.target.value || "";
          this.renderMovementModule();
        });
      });
      container.querySelectorAll("[data-live-send-target]").forEach((button) => {
        button.addEventListener("click", () => {
          const targetAgentId = button.getAttribute("data-live-send-target") || "";
          const select = container.querySelector("[data-live-task-room]");
          const routeSelect = container.querySelector("[data-live-move-route]");
          const destinationRoomId = select instanceof HTMLSelectElement ? String(select.value || "").trim() : "";
          const routeId = routeSelect instanceof HTMLSelectElement ? String(routeSelect.value || "").trim() : "";
          const route = moveRoutes.find((entry) => entry.route_id === routeId) || selectedMoveRoute;
          if (!targetAgentId || !destinationRoomId || !route) {
            return;
          }
          this.liveState.selectedMoveRouteId = route.route_id;
          const clientActionId = newClientActionId();
          const destinationRoom = this.roomLookup.get(destinationRoomId);
          this.liveMovementController.queuePendingLiveTaskAssignment({
            clientActionId,
            targetAgentId,
            targetLabel: firstNonEmpty(target?.display_name, targetAgentId),
            destinationRoomId,
            destinationRoomLabel: firstNonEmpty(destinationRoom?.name, destinationRoomId),
            routeId: route.route_id,
            taskKind: "move_to_room",
          });
          this.renderMovementModule();
          void this.liveSessionManager.submitLiveAction({
            action_type: "assign_move_task",
            client_action_id: clientActionId,
            target_agent_id: targetAgentId,
            destination_room_id: destinationRoomId,
            route_id: route.route_id,
            action_text: `${agent?.display_name || "agent"} uses ${route.route_id} and sends ${target?.display_name || "the target"} toward ${destinationRoomId}.`,
          }).catch((error) => {
            this.liveMovementController.removePendingLiveTaskAssignment(clientActionId);
            this.renderMovementModule();
            document.getElementById("event-status").textContent = error?.message || "Move task failed";
          });
        });
      });
      return;
    }
    if (!this.povController.localPovEnabled()) {
      container.innerHTML = '<div class="muted">Local POV movement is only enabled for bootstrap exploration.</div>';
      return;
    }
    const protagonist = this.currentAgents.find((agent) => agent.agent_id === this.povController.protagonistAgentId());
    const room = this.roomLookup.get(protagonist?.room_id || "");
    const movementConfig = this.povController.povConfig()?.movement || {};
    container.innerHTML = `
      <div class="module-card">
        <div class="module-copy">${movementConfig.helper_text || "Move locally through the guild footprint."}</div>
        <div class="module-chip-row">
          <span class="module-chip">Hero: ${protagonist?.display_name || "unknown"}</span>
          <span class="module-chip">Tile: ${Number(protagonist?.coordinates?.x ?? 0)}, ${Number(protagonist?.coordinates?.y ?? 0)}</span>
          <span class="module-chip">Room: ${room?.name || protagonist?.room_id || "unknown"}</span>
        </div>
      </div>
    `;
  }

  renderItemModule() {
    const container = document.getElementById("pov-items");
    if (!container) {
      return;
    }
    if (this.liveUiController.freezeLiveComposerPanels()) {
      return;
    }
    if (this.liveSessionManager.isLiveSessionMode()) {
      const session = this.liveState.session || {};
      const claimedAgent = this.controllerAgentRecord({ authoritative: true }) || this.selectedAgentRecord;
      const room = this.roomLookup.get(claimedAgent?.room_id || this.selectedRoomId || this.selectedAgentRecord?.room_id || "");
      const activeRoomAgents = this.povController.activeAgentRecords({ authoritative: true })
        .filter((agent) => agent.room_id === (room?.room_id || claimedAgent?.room_id || ""));
      const target = this.dialogueTargetRecord({ authoritative: true });
      const inventory = safeArray(claimedAgent?.inventory);
      const selectedItem = inventory.find((item) => item.item_id === this.liveState.selectedItemId) || null;
      container.innerHTML = `
        <div class="module-card">
          <div class="module-copy">Live inventory state is persisted in SQLite and routed through the room action log.</div>
          <div class="module-chip-row">
            <span class="module-chip">Claimed: ${claimedAgent?.display_name || session.claimed_agent_id || "unknown"}</span>
            <span class="module-chip">Active agents: ${activeRoomAgents.length}</span>
            <span class="module-chip">Cursor: ${this.liveState.lastEventId || 0}</span>
            <span class="module-chip">Selected: ${selectedItem?.name || "none"}</span>
            <span class="module-chip">Target: ${target?.display_name || "room broadcast"}</span>
          </div>
        </div>
        ${inventory.length ? `<div class="inventory-grid">
          ${inventory.map((item) => `
            <div class="inventory-card ${item.item_id === this.liveState.selectedItemId ? "active" : ""}" data-item-id="${item.item_id}">
              <div class="inventory-header">
                <div class="inventory-header-rich">
                  <span class="item-icon-chip" style="${this.itemSwatchStyle(item.item_id)}"></span>
                  <div class="inventory-title">${item.name || item.metadata?.name || item.item_id}</div>
                </div>
                <div class="inventory-qty">x${item.quantity}</div>
              </div>
              <div class="inventory-copy">${item.description || "No item description."}</div>
              <div class="inventory-actions">
                <button class="mini-button" type="button" data-live-item-select="${item.item_id}">Equip</button>
                <button class="mini-button" type="button" data-live-item-self="${item.item_id}" ${Number(item.quantity || 0) <= 0 ? "disabled" : ""}>Use on Self</button>
                ${target ? `<button class="mini-button" type="button" data-live-item-target="${item.item_id}" ${Number(item.quantity || 0) <= 0 ? "disabled" : ""}>Use on ${target.display_name}</button>` : ""}
              </div>
            </div>
          `).join("")}
        </div>` : '<div class="module-card"><div class="module-copy">The claimed live agent has no usable items right now.</div></div>'}
      `;
      container.querySelectorAll("[data-live-item-select]").forEach((button) => {
        button.addEventListener("click", () => {
          this.liveState.selectedItemId = button.getAttribute("data-live-item-select") || "";
          this.renderItemModule();
          this.refreshTradeModule();
        });
      });
      container.querySelectorAll("[data-live-item-self]").forEach((button) => {
        button.addEventListener("click", () => {
          const itemId = button.getAttribute("data-live-item-self") || "";
          if (!itemId) {
            return;
          }
          void this.liveSessionManager.submitLiveAction({
            action_type: "use_item",
            item_id: itemId,
            quantity: 1,
            target_agent_id: "",
            action_text: `${claimedAgent?.display_name || "agent"} uses ${itemId}.`,
          }).catch((error) => {
            document.getElementById("event-status").textContent = error?.message || "Live item action failed";
          });
        });
      });
      container.querySelectorAll("[data-live-item-target]").forEach((button) => {
        button.addEventListener("click", () => {
          const itemId = button.getAttribute("data-live-item-target") || "";
          const targetAgentId = this.dialogueTargetRecord({ authoritative: true })?.agent_id || "";
          if (!itemId || !targetAgentId) {
            return;
          }
          void this.liveSessionManager.submitLiveAction({
            action_type: "use_item",
            item_id: itemId,
            quantity: 1,
            target_agent_id: targetAgentId,
            action_text: `${claimedAgent?.display_name || "agent"} uses ${itemId} with ${target?.display_name || "target"}.`,
          }).catch((error) => {
            document.getElementById("event-status").textContent = error?.message || "Live item action failed";
          });
        });
      });
      return;
    }
    if (!this.povController.localPovEnabled()) {
      container.innerHTML = '<div class="muted">Item interaction waits for a local POV protagonist.</div>';
      return;
    }
    const protagonistState = this.localAgentState(this.povController.protagonistAgentId());
    const target = this.dialogueTargetRecord();
    const protagonist = this.currentAgents.find((agent) => agent.agent_id === this.povController.protagonistAgentId());
    const inventory = safeArray(protagonistState.inventory);
    const floorLoot = safeArray(this.localPovState.groundItems).filter((item) => item.room_id === protagonist?.room_id);
    if (!inventory.length && !floorLoot.length) {
      container.innerHTML = '<div class="muted">No JSON-seeded inventory is available for the current protagonist.</div>';
      return;
    }
    container.innerHTML = `
      ${floorLoot.length ? `
        <div class="module-card">
          <div class="inventory-title">Nearby Floor Items</div>
          <div class="inventory-grid">
            ${floorLoot.map((item) => `
              <div class="inventory-card">
                <div class="inventory-header">
                  <div class="inventory-header-rich">
                    <span class="item-icon-chip" style="${this.itemSwatchStyle(item.item_id)}"></span>
                    <div class="inventory-title">${item.label}</div>
                  </div>
                  <div class="inventory-qty">x${item.quantity}</div>
                </div>
                <div class="inventory-copy">${item.description || "No item description."}</div>
                <div class="inventory-actions">
                  <button class="mini-button" type="button" data-pickup-loot="${item.loot_id}">Pick Up</button>
                </div>
              </div>
            `).join("")}
          </div>
        </div>
      ` : ""}
      ${inventory.length ? `<div class="inventory-grid">
        ${inventory.map((item) => `
          <div class="inventory-card ${item.item_id === this.localPovState.selectedItemId ? "active" : ""}" data-item-id="${item.item_id}">
            <div class="inventory-header">
              <div class="inventory-header-rich">
                <span class="item-icon-chip" style="${this.itemSwatchStyle(item.item_id)}"></span>
                <div class="inventory-title">${item.name || item.metadata?.name || item.item_id}</div>
              </div>
              <div class="inventory-qty">x${item.quantity}</div>
            </div>
            <div class="inventory-copy">${item.description || "No item description."}</div>
            <div class="inventory-actions">
              <button class="mini-button" type="button" data-item-select="${item.item_id}">Equip</button>
              <button class="mini-button" type="button" data-item-self="${item.item_id}" ${item.quantity <= 0 ? "disabled" : ""}>Use on Self</button>
              ${target ? `<button class="mini-button" type="button" data-item-target="${item.item_id}" ${item.quantity <= 0 ? "disabled" : ""}>Use on ${target.display_name}</button>` : ""}
              ${target ? `<button class="mini-button" type="button" data-item-trade="${item.item_id}" ${item.quantity <= 0 ? "disabled" : ""}>Trade to ${target.display_name}</button>` : ""}
              <button class="mini-button" type="button" data-item-drop="${item.item_id}" ${item.quantity <= 0 ? "disabled" : ""}>Drop Here</button>
            </div>
          </div>
        `).join("")}
      </div>` : '<div class="module-card"><div class="module-copy">The protagonist inventory is empty. Pick something up from the room to continue.</div></div>'}
    `;
    container.querySelectorAll("[data-pickup-loot]").forEach((button) => {
      button.addEventListener("click", () => this.pickupGroundItem(button.getAttribute("data-pickup-loot") || ""));
    });
    container.querySelectorAll("[data-item-select]").forEach((button) => {
      button.addEventListener("click", () => {
        this.localPovState.selectedItemId = button.getAttribute("data-item-select") || "";
        this.renderItemModule();
      });
    });
    container.querySelectorAll("[data-item-self]").forEach((button) => {
      button.addEventListener("click", () => this.performItemUse(button.getAttribute("data-item-self") || "", ""));
    });
    container.querySelectorAll("[data-item-target]").forEach((button) => {
      button.addEventListener("click", () => this.performItemUse(button.getAttribute("data-item-target") || "", this.localPovState.dialogueTargetId));
    });
    container.querySelectorAll("[data-item-trade]").forEach((button) => {
      button.addEventListener("click", () => {
        this.localPovState.selectedItemId = button.getAttribute("data-item-trade") || "";
        this.tradeSelectedItem();
      });
    });
    container.querySelectorAll("[data-item-drop]").forEach((button) => {
      button.addEventListener("click", () => {
        this.localPovState.selectedItemId = button.getAttribute("data-item-drop") || "";
        this.dropSelectedItem();
      });
    });
  }

  renderDialogueModule() {
    const container = document.getElementById("pov-dialogue");
    if (!container) {
      return;
    }
    if (this.liveUiController.freezeLiveComposerPanels()) {
      return;
    }
    if (this.liveSessionManager.isLiveSessionMode()) {
      const target = this.dialogueTargetRecord({ authoritative: true });
      const claimedAgentId = this.liveState.session?.claimed_agent_id || "";
      const claimedAgent = this.controllerAgentRecord({ authoritative: true });
      const roomAgents = this.povController.activeAgentRecords({ authoritative: true }).filter((agent) => (
        agent.room_id === claimedAgent?.room_id &&
        agent.agent_id !== claimedAgentId
      ));
      const composer = this.liveUiController.syncLiveComposerElements(roomAgents, target?.agent_id || this.liveState.targetAgentId || "");
      const card = document.createElement("div");
      card.className = "module-card";
      const copy = document.createElement("div");
      copy.className = "module-copy";
      copy.textContent = target
        ? `Composing a live message to ${target.display_name}.`
        : "Choose a nearby agent in the room to aim the live composer.";
      const chipRow = document.createElement("div");
      chipRow.className = "module-chip-row";
      [
        `Claimed: ${claimedAgentId || "unknown"}`,
        `Room agents: ${roomAgents.length}`,
        `Live room: ${this.liveState.state?.room?.active ? "active" : "idle"}`,
      ].forEach((label) => {
        const chip = document.createElement("span");
        chip.className = "module-chip";
        chip.textContent = label;
        chipRow.appendChild(chip);
      });
      card.appendChild(copy);
      card.appendChild(composer.wrapper);
      card.appendChild(chipRow);

      container.replaceChildren(card);
      return;
    }
    if (!this.povController.localPovEnabled()) {
      container.innerHTML = '<div class="muted">Dialogue actions wait for bootstrap POV mode.</div>';
      return;
    }
    const target = this.dialogueTargetRecord();
    const dialogueConfig = this.povController.povConfig()?.dialogue || {};
    const actions = safeArray(dialogueConfig.actions);
    container.innerHTML = `
      <div class="module-card">
        <div class="module-copy">${target ? `Speaking with ${target.display_name}.` : "Choose a nearby guild member to open the dialogue module."}</div>
        ${target ? `
          <div class="dialogue-actions">
            ${actions.map((action) => `<button class="mini-button" type="button" data-dialogue-action="${action.action_id}">${action.label}</button>`).join("")}
          </div>
        ` : ""}
      </div>
    `;
    container.querySelectorAll("[data-dialogue-action]").forEach((button) => {
      button.addEventListener("click", () => this.performDialogueAction(button.getAttribute("data-dialogue-action") || ""));
    });
  }

  refreshTradeModule() {
    const container = document.getElementById("pov-trade");
    if (!container) {
      return;
    }
    if (this.liveUiController.freezeLiveComposerPanels()) {
      return;
    }
    if (this.liveSessionManager.isLiveSessionMode()) {
      const target = this.dialogueTargetRecord({ authoritative: true });
      const session = this.liveState.session || {};
      const claimedAgent = this.controllerAgentRecord({ authoritative: true }) || this.selectedAgentRecord;
      const room = this.roomLookup.get(claimedAgent?.room_id || this.selectedRoomId || this.selectedAgentRecord?.room_id || "");
      const tradeRoutes = this.liveSessionManager.liveAvailableRoutes("item_trade");
      const selectedTradeRouteId = tradeRoutes.some((route) => route.route_id === this.liveState.selectedTradeRouteId)
        ? this.liveState.selectedTradeRouteId
        : (tradeRoutes[0]?.route_id || "");
      const selectedTradeRoute = tradeRoutes.find((route) => route.route_id === selectedTradeRouteId) || null;
      const selectedItem = safeArray(claimedAgent?.inventory).find((entry) => entry.item_id === this.liveState.selectedItemId) || null;
      const targetInventory = safeArray(target?.inventory).filter((entry) => Number(entry.quantity || 0) > 0);
      const targetPrices = target?.item_prices && typeof target.item_prices === "object" ? target.item_prices : {};
      const currencyItemId = claimedAgent?.currency_item_id || "gold";
      const pendingTradeQuotes = safeArray(this.liveState.pendingTradeQuotes)
        .filter((entry) => !target || firstNonEmpty(entry?.targetAgentId, "") === target.agent_id);
      const pendingOffers = safeArray(claimedAgent?.pending_trade_offers)
        .filter((offer) => offer.buyer_agent_id === claimedAgent?.agent_id)
        .filter((offer) => !target || offer.seller_agent_id === target.agent_id)
        .filter((offer) => ["pending_resolution", "quoted", "accepted_pending_delivery", "completed", "rejected", "failed_unavailable", "failed_insufficient_funds"].includes(offer.status));
      container.innerHTML = `
        <div class="module-card">
          <div class="module-copy">${target ? `Trading live with ${target.display_name}. Quotes and inventory changes are DB-driven.` : `Pick a nearby room target to inspect live sell quotes in ${room?.name || this.selectedRoomId || "unknown"}.`}</div>
          <div class="module-chip-row">
            <span class="module-chip">Target: ${target?.display_name || "none"}</span>
            <span class="module-chip">Room active: ${this.liveState.state?.room?.active ? "yes" : "no"}</span>
            <span class="module-chip">Your ${currencyItemId}: ${Number(claimedAgent?.currency_quantity || 0)}</span>
            <span class="module-chip">Selected Gift Item: ${selectedItem?.name || this.liveState.selectedItemId || "none"}</span>
            <span class="module-chip">Trade Routes: ${tradeRoutes.length || 0}</span>
            <span class="module-chip">Selected Route: ${selectedTradeRoute?.route_id || "none"}</span>
          </div>
        </div>
        ${target ? `
          <div class="module-card">
            ${selectedItem ? `
              <div class="trade-actions">
                <button class="mini-button" type="button" data-live-trade-gift="${selectedItem.item_id}" ${Number(selectedItem.quantity || 0) <= 0 ? "disabled" : ""}>Gift ${selectedItem.name}</button>
              </div>
            ` : ""}
            <div class="module-copy">Ask ${target.display_name} for a DB-backed quote using the same trade routes the simulation knows.</div>
            ${tradeRoutes.length ? `
              <div class="trade-actions">
                <select class="live-target-select" data-live-trade-route>
                  ${tradeRoutes.map((route) => `<option value="${route.route_id}" ${route.route_id === selectedTradeRouteId ? "selected" : ""}>${route.route_id} · ${routeLabel(route)}</option>`).join("")}
                </select>
              </div>
              <div class="module-copy">${selectedTradeRoute?.selection_guidance || selectedTradeRoute?.story_verb || routeLabel(selectedTradeRoute)}</div>
            ` : '<div class="module-copy">No DB-backed trade route is available for this world.</div>'}
            <div class="trade-list">
              ${targetInventory.length ? targetInventory.map((entry) => `
                <div class="trade-card pending">
                  <div class="trade-title">${entry.name || entry.item_id}</div>
                  <div class="trade-copy">Listed price: ${Number(targetPrices?.[entry.item_id] ?? entry?.metadata?.price ?? 0)} ${currencyItemId} · qty ${Number(entry.quantity || 0)}</div>
                  <div class="trade-actions">
                    <button class="mini-button" type="button" data-live-ask-quote="${entry.item_id}" ${Number(entry.quantity || 0) <= 0 || !tradeRoutes.length ? "disabled" : ""}>${selectedTradeRoute ? routeLabel(selectedTradeRoute) : "Ask Quote"}</button>
                  </div>
                </div>
              `).join("") : '<div class="muted">Target has no tradable items right now.</div>'}
            </div>
          </div>
        ` : ""}
        <div class="trade-list">
          ${pendingTradeQuotes.length ? pendingTradeQuotes.map((entry) => `
            <div class="trade-card pending">
              <div class="trade-title">${entry.itemLabel || entry.itemId || "Quote request"} · pending</div>
              <div class="trade-copy">Queued on the trade coordinator. Waiting for ${entry.targetLabel || "the target"} to resolve and persist the quote request.</div>
              <div class="module-chip-row">
                <span class="module-chip">Status: queued_on_trade_coordinator</span>
                <span class="module-chip">Route: ${entry.routeId || "trade"}</span>
              </div>
            </div>
          `).join("") : ""}
          ${pendingOffers.length ? pendingOffers.map((offer) => `
            <div class="trade-card pending">
              <div class="trade-title">${offer.item_name} x${Number(offer.quantity || 1)} · ${Number(offer.total_price || 0)} ${offer.currency_item_id || currencyItemId}</div>
              <div class="trade-copy">${offer.response_text || offer.quote_text || "Pending DB-backed quote."}</div>
              <div class="module-chip-row">
                <span class="module-chip">Status: ${offer.status}</span>
                <span class="module-chip">Seller: ${this.currentAgents.find((agent) => agent.agent_id === offer.seller_agent_id)?.display_name || offer.seller_agent_id}</span>
              </div>
              ${offer.status === "quoted" ? `
                <div class="trade-actions">
                  <button class="mini-button" type="button" data-live-accept-quote="${offer.offer_id}">Accept</button>
                  <button class="mini-button" type="button" data-live-reject-quote="${offer.offer_id}">Reject</button>
                </div>
              ` : ""}
            </div>
          `).join("") : (!pendingTradeQuotes.length ? '<div class="muted">No live trade quotes yet.</div>' : "")}
        </div>
      `;
      container.querySelectorAll("[data-live-trade-gift]").forEach((button) => {
        button.addEventListener("click", () => {
          const itemId = button.getAttribute("data-live-trade-gift") || "";
          const targetAgentId = target?.agent_id || "";
          if (!itemId || !targetAgentId) {
            return;
          }
          void this.liveSessionManager.submitLiveAction({
            action_type: "trade_item",
            item_id: itemId,
            quantity: 1,
            target_agent_id: targetAgentId,
            return_item_id: "",
            action_text: `${claimedAgent?.display_name || "agent"} gifts ${itemId} to ${target.display_name}.`,
          }).catch((error) => {
            document.getElementById("event-status").textContent = error?.message || "Live trade failed";
          });
        });
      });
      container.querySelectorAll("[data-live-ask-quote]").forEach((button) => {
        button.addEventListener("click", () => {
          const itemId = button.getAttribute("data-live-ask-quote") || "";
          const targetAgentId = target?.agent_id || "";
          const routeSelect = container.querySelector("[data-live-trade-route]");
          const routeId = routeSelect instanceof HTMLSelectElement ? String(routeSelect.value || "").trim() : "";
          const route = tradeRoutes.find((entry) => entry.route_id === routeId) || selectedTradeRoute;
          if (!itemId || !targetAgentId || !route) {
            return;
          }
          this.liveState.selectedTradeRouteId = route.route_id;
          const clientActionId = newClientActionId();
          const selectedTargetInventoryEntry = targetInventory.find((entry) => entry.item_id === itemId) || null;
          this.liveMovementController.queuePendingLiveTradeQuote({
            clientActionId,
            itemId,
            itemLabel: firstNonEmpty(selectedTargetInventoryEntry?.name, itemId),
            routeId: route.route_id,
            targetAgentId,
            targetLabel: firstNonEmpty(target?.display_name, targetAgentId),
          });
          this.refreshTradeModule();
          void this.liveSessionManager.submitLiveAction({
            action_type: "request_trade_quote",
            client_action_id: clientActionId,
            item_id: itemId,
            quantity: 1,
            target_agent_id: targetAgentId,
            route_id: route.route_id,
            action_text: `${claimedAgent?.display_name || "agent"} uses ${route.route_id} and asks ${target?.display_name || "the target"} to quote ${itemId}.`,
          }).catch((error) => {
            this.liveMovementController.removePendingLiveTradeQuote(clientActionId);
            this.refreshTradeModule();
            document.getElementById("event-status").textContent = error?.message || "Live quote failed";
          });
        });
      });
      container.querySelectorAll("[data-live-trade-route]").forEach((select) => {
        select.addEventListener("change", (event) => {
          this.liveState.selectedTradeRouteId = event.target.value || "";
          this.refreshTradeModule();
        });
      });
      container.querySelectorAll("[data-live-accept-quote]").forEach((button) => {
        button.addEventListener("click", () => {
          const offerId = button.getAttribute("data-live-accept-quote") || "";
          if (!offerId) {
            return;
          }
          void this.liveSessionManager.submitLiveAction({
            action_type: "accept_trade_quote",
            offer_id: offerId,
            action_text: `${claimedAgent?.display_name || "agent"} accepts the live quote.`,
          }).catch((error) => {
            document.getElementById("event-status").textContent = error?.message || "Accept quote failed";
          });
        });
      });
      container.querySelectorAll("[data-live-reject-quote]").forEach((button) => {
        button.addEventListener("click", () => {
          const offerId = button.getAttribute("data-live-reject-quote") || "";
          if (!offerId) {
            return;
          }
          void this.liveSessionManager.submitLiveAction({
            action_type: "reject_trade_quote",
            offer_id: offerId,
            action_text: `${claimedAgent?.display_name || "agent"} rejects the live quote.`,
          }).catch((error) => {
            document.getElementById("event-status").textContent = error?.message || "Reject quote failed";
          });
        });
      });
      return;
    }
    if (!this.povController.localPovEnabled()) {
      container.innerHTML = '<div class="muted">Trade negotiation waits for bootstrap POV mode.</div>';
      return;
    }
    const target = this.dialogueTargetRecord();
    const selectedItemId = this.localPovState.selectedItemId;
    const protagonistState = this.localAgentState(this.povController.protagonistAgentId());
    const selectedItem = protagonistState.inventory.find((entry) => entry.item_id === selectedItemId);
    const pending = safeArray(this.localPovState.tradeOffers).filter((entry) => entry.status === "countered");
    container.innerHTML = `
      <div class="module-card">
        <div class="module-copy">${target ? `Negotiating with ${target.display_name}.` : "Pick a nearby target first. The selected item becomes your offer anchor."}</div>
        ${selectedItem ? `
          <div class="module-chip-row">
            <span class="module-chip">Selected Item: ${selectedItem.name}</span>
            <span class="module-chip">Qty: ${selectedItem.quantity}</span>
          </div>
        ` : '<div class="module-copy">Equip an item in the inventory panel to open offer actions.</div>'}
        ${target && selectedItem ? `
          <div class="trade-actions">
            <button class="mini-button" type="button" data-trade-gift="1" ${selectedItem.quantity <= 0 ? "disabled" : ""}>Offer as Gift</button>
            <button class="mini-button" type="button" data-trade-request="1" ${selectedItem.quantity <= 0 ? "disabled" : ""}>Request Trade</button>
          </div>
        ` : ""}
      </div>
      <div class="trade-list">
        ${pending.length ? pending.map((offer) => `
          <div class="trade-card pending">
            <div class="trade-title">Counteroffer from ${this.currentAgents.find((agent) => agent.agent_id === offer.target_agent_id)?.display_name || offer.target_agent_id}</div>
            <div class="trade-copy">${offer.copy}</div>
            <div class="trade-actions">
              <button class="mini-button" type="button" data-accept-offer="${offer.offer_id}">Accept</button>
              <button class="mini-button" type="button" data-reject-offer="${offer.offer_id}">Reject</button>
            </div>
          </div>
        `).join("") : '<div class="muted">No pending counteroffers.</div>'}
      </div>
    `;
    container.querySelectorAll("[data-trade-gift]").forEach((button) => {
      button.addEventListener("click", () => this.quoteSelectedItem(false));
    });
    container.querySelectorAll("[data-trade-request]").forEach((button) => {
      button.addEventListener("click", () => this.quoteSelectedItem(true));
    });
    container.querySelectorAll("[data-accept-offer]").forEach((button) => {
      button.addEventListener("click", () => this.acceptTradeOffer(button.getAttribute("data-accept-offer") || ""));
    });
    container.querySelectorAll("[data-reject-offer]").forEach((button) => {
      button.addEventListener("click", () => this.rejectTradeOffer(button.getAttribute("data-reject-offer") || ""));
    });
  }

  agentSummaryMarkup(agent, { showInventory = false, compact = false } = {}) {
    if (!agent) {
      return '<div class="muted">No agent is available yet.</div>';
    }
    const portrait = primaryAgentImage(agent);
    const inventory = safeArray(agent.inventory).filter((entry) => Number(entry.quantity || 0) > 0);
    const inventoryMarkup = showInventory
      ? `
        <div class="agent-bubble-inventory">
          ${inventory.length ? inventory.slice(0, compact ? 4 : 6).map((entry) => `
            <div class="agent-bubble-item">
              <div>
                <strong>${escapeHtml(entry.name || entry.item_id)}</strong>
                <div class="agent-bubble-item-meta">${escapeHtml(entry.description || entry.item_id)}</div>
              </div>
              <span class="module-chip">x${Number(entry.quantity || 0)}</span>
            </div>
          `).join("") : '<div class="muted">No items carried right now.</div>'}
        </div>
      `
      : "";
    return `
      <div class="agent-bubble">
        <div class="agent-bubble-head">
          ${portrait?.image_url
            ? `<img class="agent-photo" src="${escapeHtml(portrait.image_url)}" alt="${escapeHtml(agent.display_name)}" data-agent-photo="${escapeHtml(agent.agent_id)}" />`
            : `<div class="agent-photo-fallback">${escapeHtml(agentInitials(agent))}</div>`}
          <div class="agent-bubble-copy">
            <div class="agent-bubble-title">${escapeHtml(agent.display_name)}</div>
            <div class="agent-bubble-subline">${escapeHtml(agent.role_name || "Agent")} · ${escapeHtml(agent.room_name || agent.room_id || "unknown room")}</div>
            <div class="agent-bubble-text">${escapeHtml(agent.current_focus || agent.activity_directive || "Holding position inside the world.")}</div>
            <div class="module-chip-row">
              <span class="agent-role-pill">${escapeHtml(agent.live_motion_mode || agent.control_mode || "idle")}</span>
              <span class="module-chip">Inventory ${inventory.length}</span>
              ${agent.main_character ? '<span class="module-chip">Main Character</span>' : ""}
            </div>
          </div>
        </div>
        ${agent.mainline_summary ? `<div class="module-copy">${escapeHtml(agent.mainline_summary)}</div>` : ""}
        ${inventoryMarkup}
      </div>
    `;
  }


  renderPendingActions() {
    const container = document.getElementById("pending-actions");
    if (!container) {
      return;
    }
    if (!this.liveSessionManager.isLiveSessionMode()) {
      container.innerHTML = '<div class="muted">Pending actions only appear during live sessions.</div>';
      return;
    }
    const entries = [];
    safeArray(this.liveState.pendingMoves).forEach((pendingMove, index) => {
      entries.push({
        type: "move",
        title: `Move ${pendingMove?.direction || "pending"}${index > 0 ? ` · queue ${index + 1}` : ""}`,
        copy: firstNonEmpty(pendingMove?.actionText, "Movement is waiting for the world writer."),
        status: index === 0 ? "Queued on coordinator" : "Buffered locally",
      });
    });
    safeArray(this.liveState.pendingMessages).forEach((entry) => {
      entries.push({
        type: "message",
        title: entry.targetLabel ? `Message to ${entry.targetLabel}` : "Room broadcast",
        copy: firstNonEmpty(entry.actionText, "Pending live message."),
        status: "Awaiting reply",
      });
    });
    safeArray(this.liveState.pendingTradeQuotes).forEach((entry) => {
      entries.push({
        type: "trade",
        title: `${entry.itemLabel || entry.itemId || "Trade quote"} · ${entry.targetLabel || "target"}`,
        copy: `Trade quote is queued on ${entry.routeId || "trade"} and waiting for persistence.`,
        status: "Awaiting quote",
      });
    });
    safeArray(this.liveState.pendingTaskAssignments).forEach((entry) => {
      entries.push({
        type: "task",
        title: `${entry.targetLabel || "Agent"} -> ${entry.destinationRoomLabel || entry.destinationRoomId || "room"}`,
        copy: `Task ${entry.taskKind || "move_to_room"} is queued on ${entry.routeId || "move"}.`,
        status: "Awaiting task write",
      });
    });

    if (!entries.length) {
      container.innerHTML = '<div class="muted">No live actions are waiting right now.</div>';
      return;
    }
    container.innerHTML = entries.map((entry) => `
      <div class="pending-card ${escapeHtml(entry.type)}">
        <div class="pending-head">
          <strong>${escapeHtml(entry.title)}</strong>
          <span class="status-pill pending">${escapeHtml(entry.status)}</span>
        </div>
        <div class="module-copy">${escapeHtml(entry.copy)}</div>
      </div>
    `).join("");
  }

  conversationHistoryEntries() {
    if (!this.liveSessionManager.isLiveSessionMode()) {
      return safeArray(this.localPovState.dialogueLog)
        .slice(0, 14)
        .map((entry) => ({
          pending: false,
          label: firstNonEmpty(entry?.speaker, "Dialogue"),
          text: firstNonEmpty(entry?.text, ""),
        }));
    }

    const pendingIds = new Set(
      this.liveUiController.pendingLiveSpeechEntries()
        .map((entry) => firstNonEmpty(entry?.clientActionId, ""))
        .filter(Boolean),
    );
    const pendingEntries = this.liveUiController.pendingLiveSpeechEntries().map((entry) => ({
      pending: true,
      label: entry.targetLabel ? `Pending to ${entry.targetLabel}` : "Pending room broadcast",
      text: firstNonEmpty(entry.text, "Pending live message."),
    }));
    const resolvedEntries = safeArray(this.liveState.eventLog)
      .slice()
      .reverse()
      .filter((event) => {
        const eventType = firstNonEmpty(event?.event_type, "");
        const payload = liveEventPayload(event);
        const actionType = firstNonEmpty(payload?.action_type, "");
        const clientActionId = firstNonEmpty(payload?.client_action_id, "");
        if (eventType === "human_action") {
          if (clientActionId && pendingIds.has(clientActionId)) {
            return false;
          }
          return !actionType || actionType === "message";
        }
        return eventType === "agent_response" || eventType === "room_chatter";
      })
      .map((event) => {
        const eventType = firstNonEmpty(event?.event_type, "");
        const speakerId = firstNonEmpty(event?.agent_id, event?.target_agent_id, "");
        const speakerLabel = eventType === "human_action"
          ? "You"
          : (this.currentAgents.find((agent) => agent.agent_id === speakerId)?.display_name || eventType);
        return {
          pending: false,
          label: speakerLabel,
          text: firstNonEmpty(event?.response_text, event?.action_text, "Dialogue event."),
        };
      });
    return [...pendingEntries, ...resolvedEntries].slice(0, 14);
  }


  renderActionLog() {
    const container = document.getElementById("pov-log");
    if (!container) return;
    const entries = this.conversationHistoryEntries();
    if (!entries.length) {
      container.innerHTML = '<div class="muted">Dialogue history will appear here once someone starts speaking.</div>';
      return;
    }
    container.innerHTML = entries.map((entry) => `<div class="${entry.pending ? "dialogue-line pending" : "dialogue-line"}"><strong>${escapeHtml(entry.label)}</strong><div>${escapeHtml(entry.text)}</div></div>`).join("");
  }
}
