import { firstNonEmpty, safeArray, headlessKickFromLocation } from "./utils.js";

export class ExportRenderer {
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

  isExportCaptureMode() {
    return this.captureMode === "export";
  }

  primeExportFallbackAssets() {
    const assetMap = new Map();
    this.assetsFromManifest().forEach((assetEvent) => {
      const agentId = String(assetEvent?.id || "").trim();
      if (agentId) {
        assetMap.set(agentId, assetEvent);
      }
    });
    this.exportFallback.assetEvents = assetMap;
    const mapAssetUrl = this.resolveFrontendUrl(this.frontendConfig().map_asset_url || firstNonEmpty(this.assetSetManifest?.map_asset_url, ""));
    if (mapAssetUrl && this.exportFallback.mapImageUrl !== mapAssetUrl) {
      this.exportFallback.mapImageUrl = mapAssetUrl;
      this.exportFallback.mapImage = null;
    }
  }

  ensureExportFallbackCanvas() {
    if (!this.isExportCaptureMode()) {
      return null;
    }
    const root = document.getElementById("game-root");
    if (!root) {
      return null;
    }
    if (!this.exportFallback.canvas) {
      const canvas = document.createElement("canvas");
      canvas.className = "export-fallback-canvas";
      root.appendChild(canvas);
      this.exportFallback.canvas = canvas;
      this.exportFallback.ctx = canvas.getContext("2d");
    }
    return this.exportFallback.canvas;
  }

  scheduleExportFallbackRender() {
    if (!this.isExportCaptureMode()) {
      return;
    }
    if (this.exportFallback.renderPromise) {
      return;
    }
    this.exportFallback.renderPromise = Promise.resolve().then(async () => {
      try {
        await this.renderExportFallbackCanvas();
      } finally {
        this.exportFallback.renderPromise = null;
      }
    });
  }

  async #renderExportFallbackCanvas() {
    const canvas = this.ensureExportFallbackCanvas();
    const ctx = this.exportFallback.ctx;
    if (!canvas || !ctx) {
      return;
    }
    this.primeExportFallbackAssets();
    const root = document.getElementById("game-root");
    const rootWidth = Math.max(1, Number(root?.clientWidth || 0));
    const rootHeight = Math.max(1, Number(root?.clientHeight || 0));
    if (canvas.width !== rootWidth || canvas.height !== rootHeight) {
      canvas.width = rootWidth;
      canvas.height = rootHeight;
    }
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.imageSmoothingEnabled = false;

    const roomId = this.selectedRoomId || this.homeRoomId || this.currentAgents[0]?.room_id || "";
    const roomNode = this.roomNodes.get(roomId);
    if (!roomNode) {
      return;
    }
    const mapImage = await this.loadExportMapImage().catch(() => null);
    const padding = 36;
    const roomWidth = Math.max(1, roomNode.bounds.widthTiles * this.displayMetrics.tileWidth);
    const roomHeight = Math.max(1, roomNode.bounds.heightTiles * this.displayMetrics.tileHeight);
    const scale = Math.max(1.25, Math.min((canvas.width - padding * 2) / roomWidth, (canvas.height - padding * 2) / roomHeight));
    const viewportWidthWorld = canvas.width / scale;
    const viewportHeightWorld = canvas.height / scale;
    const viewportX = roomNode.centerX - viewportWidthWorld / 2;
    const viewportY = roomNode.centerY - viewportHeightWorld / 2;
    const worldToCanvasX = (value) => (value - viewportX) * scale;
    const worldToCanvasY = (value) => (value - viewportY) * scale;

    ctx.fillStyle = "#ead7b4";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (mapImage) {
      ctx.drawImage(
        mapImage,
        worldToCanvasX(0),
        worldToCanvasY(0),
        this.worldDimensions.width * scale,
        this.worldDimensions.height * scale,
      );
    }

    this.roomNodes.forEach((node, currentRoomId) => {
      const x = worldToCanvasX(node.centerX - (node.bounds.widthTiles * this.displayMetrics.tileWidth) / 2);
      const y = worldToCanvasY(node.centerY - (node.bounds.heightTiles * this.displayMetrics.tileHeight) / 2);
      const width = node.bounds.widthTiles * this.displayMetrics.tileWidth * scale;
      const height = node.bounds.heightTiles * this.displayMetrics.tileHeight * scale;
      ctx.strokeStyle = currentRoomId === roomId ? "#f0b25b" : "rgba(55, 35, 20, 0.35)";
      ctx.lineWidth = currentRoomId === roomId ? 4 : 2;
      ctx.strokeRect(x, y, width, height);
      if (currentRoomId === roomId) {
        ctx.fillStyle = "rgba(240, 178, 91, 0.12)";
        ctx.fillRect(x, y, width, height);
      }
    });

    const visibleAgents = this.currentAgents.filter((agent) => agent.room_id === roomId);
    const spriteScale = this.agentDisplayScaleFor() * scale;
    await Promise.all(visibleAgents.map(async (agent) => {
      const frame = await this.loadExportFrame(agent.agent_id);
      const worldX = this.worldDimensions.margin + (Number(agent.coordinates?.x ?? 0) + 0.5) * this.displayMetrics.tileWidth;
      const worldY = this.worldDimensions.margin + (Number(agent.coordinates?.y ?? 0) + 0.68) * this.displayMetrics.tileHeight;
      const canvasX = worldToCanvasX(worldX);
      const canvasY = worldToCanvasY(worldY);
      if (frame?.image && frame?.frame) {
        const drawWidth = frame.frame.w * spriteScale;
        const drawHeight = frame.frame.h * spriteScale;
        ctx.drawImage(
          frame.image,
          frame.frame.x,
          frame.frame.y,
          frame.frame.w,
          frame.frame.h,
          canvasX - drawWidth / 2,
          canvasY - drawHeight * 0.82,
          drawWidth,
          drawHeight,
        );
      } else {
        ctx.fillStyle = agent.agent_id === this.selectedAgentRecord?.agent_id ? "#78d6d6" : "#6b3d22";
        ctx.fillRect(canvasX - 6, canvasY - 10, 12, 12);
      }
      if (agent.agent_id === this.selectedAgentRecord?.agent_id) {
        ctx.strokeStyle = "#78d6d6";
        ctx.lineWidth = 3;
        ctx.strokeRect(canvasX - 14, canvasY - 22, 28, 28);
      }
    }));

    ctx.fillStyle = "rgba(17, 12, 16, 0.78)";
    ctx.fillRect(12, 12, 300, 58);
    ctx.fillStyle = "#f7f4ef";
    ctx.font = "16px monospace";
    ctx.fillText(roomNode.room.name || roomId, 24, 36);
    ctx.fillStyle = "#cfd7d5";
    ctx.font = "12px monospace";
    ctx.fillText(`${visibleAgents.length} agents active in room`, 24, 56);
  }

  kickHeadlessRender(steps = 3) {
    if (!headlessKickFromLocation()) {
      return;
    }
    try {
      const game = this.game || this.sys?.game || window.__AGORA_PHASER_GAME__ || null;
      if (typeof game?.onVisible === "function") {
        game.onVisible();
      }
      if (game?.loop && typeof game.loop.wake === "function") {
        game.loop.wake(true);
      }
      if (typeof window.__AGORA_MANUAL_STEP_GAME__ === "function") {
        window.__AGORA_MANUAL_STEP_GAME__(steps);
      } else if (game && typeof game.step === "function") {
        const baseNow = window.performance.now();
        for (let index = 0; index < steps; index += 1) {
          game.step(baseNow + (index * 16.6667), 16.6667);
        }
      }
      window.__AGORA_WORLD_SCENE_MANUAL_STEPS__ = Number(window.__AGORA_WORLD_SCENE_MANUAL_STEPS__ || 0) + steps;
    } catch (error) {
      window.__AGORA_WORLD_SCENE_MANUAL_STEP_ERROR__ = String(error?.message || error);
    }
  }

  async #loadExportMapImage() {
    if (!this.exportFallback.mapImageUrl) {
      return null;
    }
    if (this.exportFallback.mapImage) {
      return this.exportFallback.mapImage;
    }
    const image = await new Promise((resolve, reject) => {
      const candidate = new Image();
      candidate.onload = () => resolve(candidate);
      candidate.onerror = () => reject(new Error(`Failed to load export map image: ${this.exportFallback.mapImageUrl}`));
      candidate.src = this.exportFallback.mapImageUrl;
    });
    this.exportFallback.mapImage = image;
    return image;
  }

  async #loadExportFrame(agentId) {
    const normalized = String(agentId || "").trim();
    if (!normalized) {
      return null;
    }
    if (this.exportFallback.frameCache.has(normalized)) {
      return this.exportFallback.frameCache.get(normalized);
    }
    const assetEvent = this.exportFallback.assetEvents.get(normalized);
    if (!assetEvent) {
      this.exportFallback.frameCache.set(normalized, null);
      return null;
    }
    const atlasUrl = this.resolveFrontendUrl(assetEvent.atlas_url || "");
    const jsonUrl = this.resolveFrontendUrl(assetEvent.json_url || "");
    const animations = assetEvent.animations || {};
    const defaultAnimation = firstNonEmpty(assetEvent.default_animation, "idle_down");
    const frameName = firstNonEmpty(animations?.[defaultAnimation]?.defaultFrame, animations?.[defaultAnimation]?.frames?.[0], "idle_down_0.png");
    const promise = Promise.all([
      fetch(jsonUrl, { cache: "no-store" }).then((response) => {
        if (!response.ok) {
          throw new Error(`Failed to load export atlas json: ${jsonUrl}`);
        }
        return response.json();
      }),
      new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () => reject(new Error(`Failed to load export atlas image: ${atlasUrl}`));
        image.src = atlasUrl;
      }),
    ]).then(([atlasData, atlasImage]) => {
      const frame = atlasData?.frames?.[frameName]?.frame;
      if (!frame) {
        return null;
      }
      return {
        image: atlasImage,
        frame: {
          x: Number(frame.x || 0),
          y: Number(frame.y || 0),
          w: Number(frame.w || 32),
          h: Number(frame.h || 32),
        },
      };
    }).catch(() => null);
    this.exportFallback.frameCache.set(normalized, promise);
    return promise;
  }

}
