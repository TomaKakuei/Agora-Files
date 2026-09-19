import { firstNonEmpty, safeArray, tileKey, occupantCountMap, Phaser } from "./utils.js";

export class RoomUiController {
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

  focusRoom(roomId, { zoom = 0.82 } = {}) {
    const node = this.roomNodes.get(roomId);
    if (!node) {
      return;
    }
    this.selectedRoomId = roomId;
    if (this.viewMode === "pov") {
      this.viewMode = "atlas";
      document.getElementById("view-mode-badge").textContent = "Atlas Mode";
      document.getElementById("pov-mode-button")?.classList.toggle("active", false);
      document.getElementById("atlas-mode-button")?.classList.toggle("active", true);
    }
    this.cameras.main.stopFollow();
    this.cameras.main.pan(node.centerX, node.centerY, 380, "Sine.easeOut", true);
    this.cameras.main.zoomTo(Phaser.Math.Clamp(zoom, 0.18, 2.2), 300);
    this.worldRenderer.applyRoomHighlight();
    this.cameraController.applyPresenceFocus();
    this.liveUiController.refreshImmersiveHud();
    this.markRoomNavSelection();
    this.exportRenderer.scheduleExportFallbackRender();
  }

  buildRoomNavigator() {
    const container = document.getElementById("room-nav");
    if (!container) {
      return;
    }
    container.innerHTML = "";
    safeArray(this.mapGrid?.rooms).forEach((room) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "room-nav-button";
      button.dataset.roomId = room.room_id;
      button.innerHTML = `
        <div class="room-nav-title">
          <strong>${room.name}</strong>
          <span>${room.room_id}</span>
        </div>
        <div class="room-nav-meta">
          <span>${safeArray(room.visual?.decor_tags).slice(0, 2).join(" / ") || "room"}</span>
          <span data-role="count">0 agents</span>
        </div>
      `;
      button.addEventListener("click", () => this.focusRoom(room.room_id, { zoom: 0.82 }));
      container.appendChild(button);
    });
    this.markRoomNavSelection();
    this.refreshRoomNavigatorCounts(this.currentAgents);
  }

  refreshRoomNavigatorCounts(agentList) {
    const counts = occupantCountMap(agentList);
    document.querySelectorAll("#room-nav .room-nav-button").forEach((button) => {
      const roomId = button.dataset.roomId || "";
      const count = counts.get(roomId) || 0;
      const slot = button.querySelector('[data-role="count"]');
      if (slot) {
        slot.textContent = `${count} agent${count === 1 ? "" : "s"}`;
      }
    });
  }

  markRoomNavSelection() {
    document.querySelectorAll("#room-nav .room-nav-button").forEach((button) => {
      button.classList.toggle("active", button.dataset.roomId === this.selectedRoomId);
    });
  }




  updateSpeechBubblePositions() {
    this.localPovState.speechBubbles.forEach((record, agentId) => {
      const sprite = this.agentManager.agentSprites.get(agentId);
      if (!sprite || !record?.container?.active) {
        return;
      }
      record.container.setPosition(sprite.x, sprite.y - 74);
    });
  }


}
