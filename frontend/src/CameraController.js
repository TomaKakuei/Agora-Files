import { safeArray, Phaser } from "./utils.js";

export class CameraController {
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

  installCameraControls() {
    this.input.on("wheel", (_pointer, _objects, _dx, dy) => {
      const camera = this.cameras.main;
      const nextZoom = Phaser.Math.Clamp(camera.zoom - dy * 0.0012, 0.08, 2.6);
      camera.setZoom(nextZoom);
    });

    this.input.on("pointerdown", (pointer, targets) => {
      if (targets?.length) {
        return;
      }
      if (this.viewMode === "pov") {
        this.setViewMode("atlas", { instant: true });
      }
      this.isDraggingCamera = true;
      this.dragOrigin = {
        x: pointer.x,
        y: pointer.y,
        scrollX: this.cameras.main.scrollX,
        scrollY: this.cameras.main.scrollY,
      };
      this.cameras.main.stopFollow();
    });

    this.input.on("pointermove", (pointer) => {
      if (!this.isDraggingCamera || !this.dragOrigin) {
        return;
      }
      const camera = this.cameras.main;
      camera.scrollX = this.dragOrigin.scrollX - (pointer.x - this.dragOrigin.x) / camera.zoom;
      camera.scrollY = this.dragOrigin.scrollY - (pointer.y - this.dragOrigin.y) / camera.zoom;
    });

    this.input.on("pointerup", () => {
      this.isDraggingCamera = false;
      this.dragOrigin = null;
    });

    document.getElementById("fit-world-button")?.addEventListener("click", () => this.fitWorld());
    document.getElementById("home-room-button")?.addEventListener("click", () => {
      if (this.homeRoomId) {
        this.setViewMode("atlas", { instant: true });
        this.focusRoom(this.homeRoomId, { zoom: 0.82 });
      } else {
        this.fitWorld();
      }
    });
    document.getElementById("pov-mode-button")?.addEventListener("click", () => this.setViewMode("pov"));
    document.getElementById("atlas-mode-button")?.addEventListener("click", () => this.setViewMode("atlas"));
    document.getElementById("recenter-agent-button")?.addEventListener("click", () => this.focusSelectedAgent({ instant: false }));
  }

  setViewMode(mode, { instant = false } = {}) {
    this.viewMode = mode === "atlas" ? "atlas" : "pov";
    const badgeText = this.viewMode === "pov"
      ? (this.isLiveSessionMode() ? "Live Follow" : "POV Mode")
      : "Atlas Mode";
    document.getElementById("view-mode-badge").textContent = badgeText;
    document.getElementById("pov-mode-button")?.classList.toggle("active", this.viewMode === "pov");
    document.getElementById("atlas-mode-button")?.classList.toggle("active", this.viewMode === "atlas");
    if (this.viewMode === "pov") {
      const protagonistId = this.protagonistAgentId();
      if (this.localPovEnabled() && protagonistId) {
        this.agentManager.selectAgent(protagonistId);
        this.selectedAgentRecord = this.currentAgents.find((agent) => agent.agent_id === protagonistId) || this.selectedAgentRecord;
      }
      this.focusSelectedAgent({ instant });
    } else {
      this.fitWorld();
    }
    this.applyPresenceFocus();
    this.refreshImmersiveHud();
    this.scheduleExportFallbackRender();
  }

  applyPresenceFocus() {
    const selectedId = this.selectedAgentRecord?.agent_id || "";
    const selectedRoomId = this.selectedAgentRecord?.room_id || this.selectedRoomId;
    this.agentManager.agentSprites.forEach((sprite, agentId) => {
      const record = this.agentManager.agentRecords.get(agentId);
      if (!record) {
        return;
      }
      const selected = agentId === selectedId;
      const sameRoom = record.room_id === selectedRoomId;
      if (this.viewMode === "pov") {
        sprite.setAlpha(selected ? 1 : sameRoom ? 0.84 : 0.16);
      } else {
        sprite.setAlpha(selected ? 1 : 0.96);
      }
    });
  }

  focusSelectedAgent({ instant = false } = {}) {
    const record = this.selectedAgentRecord;
    if (!record) {
      this.fitWorld();
      return;
    }
    const sprite = this.agentManager.agentSprites.get(record.agent_id);
    if (!sprite) {
      return;
    }
    this.selectedRoomId = record.room_id || this.selectedRoomId;
    const camera = this.cameras.main;
    camera.stopFollow();
    const targetZoom = Phaser.Math.Clamp(1.62 / Math.max(1, this.displayMetrics.renderScale * 0.52), 0.54, 1.7);
    if (instant) {
      camera.setZoom(targetZoom);
      camera.centerOn(sprite.x, sprite.y);
      camera.startFollow(sprite, true, 0.12, 0.12);
    } else {
      camera.pan(sprite.x, sprite.y, 320, "Sine.easeOut", true);
      camera.zoomTo(targetZoom, 260);
      camera.startFollow(sprite, true, 0.12, 0.12);
    }
    this.applyRoomHighlight();
    this.applyPresenceFocus();
    this.scheduleExportFallbackRender();
  }

  previewMoveForAgent(agent, direction, { allowPeerOverlap = false } = {}) {
    if (!agent) {
      return null;
    }
    const preview = this.resolveMoveDestination(agent.room_id, agent.coordinates || {}, direction);
    if (!preview?.ok) {
      return preview;
    }
    return {
      ok: true,
      nextRoomId: preview.nextRoomId,
      nextX: preview.nextX,
      nextY: preview.nextY,
      nextZ: preview.nextZ,
      usedWallHop: Boolean(preview.usedWallHop),
    };
  }

}
