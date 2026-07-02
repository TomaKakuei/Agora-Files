const Phaser = window.Phaser;

function buildAnimationMap(atlasData) {
  if (atlasData.animations) {
    return atlasData.animations;
  }
  const grouped = {};
  Object.keys(atlasData.frames || {}).forEach((frameName) => {
    const stateName = frameName.replace(/_\d+\.png$/, "");
    if (!grouped[stateName]) {
      grouped[stateName] = {
        frames: [],
        frameRate: stateName.startsWith("idle") ? 4 : 7,
        repeat: stateName.startsWith("idle") ? 0 : -1,
        static: stateName.startsWith("idle"),
      };
    }
    grouped[stateName].frames.push(frameName);
  });
  return grouped;
}

export class AgentManager {
  constructor(scene, uiBridge) {
    this.scene = scene;
    this.uiBridge = uiBridge;
    this.agentSprites = new Map();
    this.selectionIndicators = new Map();
    this.agentRecords = new Map();
    this.loadedRevisions = new Map();
    this.loadedTextureKeys = new Map();
    this.loadedAnimationMaps = new Map();
    this.movementTweens = new Map();
    this.idleResetTimers = new Map();
    this.latestEventPath = null;
    this.selectedAgentId = "";
  }

  #resolveAssetUrl(url) {
    if (typeof this.scene?.resolveAssetUrl === "function") {
      return this.scene.assetResolver.resolveAssetUrl(url);
    }
    const value = String(url || "").trim();
    if (!value) {
      return "";
    }
    try {
      return new URL(value, window.location.href).toString();
    } catch (error) {
      return value;
    }
  }

  #baseScaleFor(agentRecord) {
    if (typeof this.scene.agentDisplayScaleFor === "function") {
      return this.scene.agentDisplayScaleFor(agentRecord);
    }
    return 1;
  }

  #applySelectionVisual(sprite, agentRecord) {
    const baseScale = this.#baseScaleFor(agentRecord);
    const selected = this.selectedAgentId === agentRecord.agent_id;
    sprite.setTint(selected ? 0xffffff : 0xd8d8d8);
    sprite.setScale(selected ? baseScale * 1.16 : baseScale);
    sprite.setDepth(selected ? 34 : (agentRecord.main_character ? 28 : 20));
    const indicator = this.selectionIndicators.get(agentRecord.agent_id);
    if (indicator) {
      indicator.setPosition(sprite.x, sprite.y + 16);
      indicator.setVisible(selected);
      indicator.setDepth(selected ? 33 : 18);
    }
  }

  createPlaceholderTexture() {
    if (this.scene.textures.exists("agent-placeholder")) {
      return "agent-placeholder";
    }
    const graphics = this.scene.make.graphics({ x: 0, y: 0, add: false });
    graphics.fillStyle(0x2b2535, 1);
    graphics.fillRect(0, 0, 24, 24);
    graphics.fillStyle(0xe7b05a, 1);
    graphics.fillRect(6, 2, 12, 8);
    graphics.fillStyle(0x7ad0cb, 1);
    graphics.fillRect(4, 11, 16, 10);
    graphics.lineStyle(2, 0x131017, 1);
    graphics.strokeRect(0, 0, 24, 24);
    graphics.generateTexture("agent-placeholder", 24, 24);
    graphics.destroy();
    return "agent-placeholder";
  }

  registerAgent(agentRecord, x, y) {
    const textureKey = this.createPlaceholderTexture();
    const indicator = this.scene.add.ellipse(x, y + 16, 34, 16, 0x78d6d6, 0.18);
    indicator.setStrokeStyle(3, 0xf0b25b, 1);
    indicator.setVisible(false);
    indicator.setDepth(18);
    const sprite = this.scene.add.sprite(x, y, textureKey);
    sprite.setOrigin(0.5, 1);
    sprite.setScale(this.#baseScaleFor(agentRecord));
    sprite.setInteractive({ useHandCursor: true });
    sprite.on("pointerdown", () => this.selectAgent(agentRecord.agent_id));
    this.selectionIndicators.set(agentRecord.agent_id, indicator);
    this.agentSprites.set(agentRecord.agent_id, sprite);
    this.agentRecords.set(agentRecord.agent_id, agentRecord);
    this.#applySelectionVisual(sprite, agentRecord);
    return sprite;
  }

  syncAgentRecord(agentRecord, x, y, options = {}) {
    const existingSprite = this.agentSprites.get(agentRecord.agent_id);
    const sprite = existingSprite || this.registerAgent(agentRecord, x, y);
    const shouldAnimate = Boolean(options.animateMovement && existingSprite);
    const deltaX = x - sprite.x;
    const deltaY = y - sprite.y;
    this.agentRecords.set(agentRecord.agent_id, agentRecord);
    if (shouldAnimate && Math.hypot(deltaX, deltaY) > 1) {
      this.#animateSpriteMove(agentRecord, sprite, x, y, deltaX, deltaY, options);
    } else {
      const activeTween = this.movementTweens.get(agentRecord.agent_id);
      if (activeTween) {
        activeTween.stop();
        this.movementTweens.delete(agentRecord.agent_id);
      }
      sprite.setPosition(x, y);
    }
    this.#applySelectionVisual(sprite, agentRecord);
    if (this.selectedAgentId === agentRecord.agent_id && !options.suppressSelectedUiUpdate) {
      this.uiBridge.setSelectedAgent(agentRecord);
    }
    return sprite;
  }

  setAgentAnimation(agentId, stateName) {
    const sprite = this.agentSprites.get(agentId);
    if (!sprite) {
      return;
    }
    const animations = this.loadedAnimationMaps.get(agentId) || {};
    const stateConfig = animations[stateName];
    if (!stateConfig) {
      return;
    }
    const firstFrame = stateConfig.frames?.[0];
    if (stateConfig.static || (stateConfig.frames || []).length <= 1 || stateConfig.repeat === 0) {
      sprite.anims.stop();
      if (firstFrame) {
        sprite.setTexture(this.loadedTextureKeys.get(agentId) || sprite.texture.key, firstFrame);
      }
      return;
    }
    const animKey = `${agentId}:${stateName}`;
    if (this.scene.anims.exists(animKey)) {
      sprite.play(animKey, true);
    }
  }

  #directionFromDelta(deltaX, deltaY) {
    if (Math.abs(deltaX) >= Math.abs(deltaY)) {
      return deltaX < 0 ? "left" : "right";
    }
    return deltaY < 0 ? "up" : "down";
  }

  #animationCandidatesForDirection(direction) {
    return [
      `walk_${direction}`,
      direction === "up" ? "walk_right" : "",
      "walk_down",
    ].filter(Boolean);
  }

  #idleAnimationFor(agentId) {
    return ["idle_down", "walk_down"].find((stateName) => this.hasAgentAnimation(agentId, stateName)) || "idle_down";
  }

  #animateSpriteMove(agentRecord, sprite, x, y, deltaX, deltaY, options = {}) {
    const agentId = agentRecord.agent_id;
    const activeTween = this.movementTweens.get(agentId);
    if (activeTween) {
      activeTween.stop();
      this.movementTweens.delete(agentId);
    }
    const idleTimer = this.idleResetTimers.get(agentId);
    if (idleTimer) {
      idleTimer.remove(false);
      this.idleResetTimers.delete(agentId);
    }

    const direction = this.#directionFromDelta(deltaX, deltaY);
    const walkState = this.#animationCandidatesForDirection(direction)
      .find((stateName) => this.hasAgentAnimation(agentId, stateName));
    if (walkState) {
      this.setAgentAnimation(agentId, walkState);
    }
    const requestedDuration = Number(options.movementDurationMs || 0);
    const duration = requestedDuration > 0
      ? Phaser.Math.Clamp(requestedDuration, 16, 420)
      : Phaser.Math.Clamp(Math.hypot(deltaX, deltaY) * 5, 120, 420);

    const tween = this.scene.tweens.add({
      targets: sprite,
      x,
      y,
      duration,
      ease: "Sine.easeInOut",
      onUpdate: () => this.#applySelectionVisual(sprite, agentRecord),
      onComplete: () => {
        this.movementTweens.delete(agentId);
        sprite.setPosition(x, y);
        this.#applySelectionVisual(sprite, agentRecord);
        const timer = this.scene.time.delayedCall(90, () => {
          this.setAgentAnimation(agentId, this.#idleAnimationFor(agentId));
          this.idleResetTimers.delete(agentId);
        });
        this.idleResetTimers.set(agentId, timer);
      },
    });
    this.movementTweens.set(agentId, tween);
  }

  hasAgentAnimation(agentId, stateName) {
    const animations = this.loadedAnimationMaps.get(agentId) || {};
    return Boolean(animations[stateName]?.frames?.length);
  }

  selectAgent(agentId) {
    const record = this.agentRecords.get(agentId);
    if (!record) {
      return;
    }
    this.selectedAgentId = agentId;
    this.uiBridge.setSelectedAgent(record);
    this.refreshSelectionVisuals();
  }

  refreshSelectionVisuals() {
    this.agentSprites.forEach((sprite, currentId) => {
      const currentRecord = this.agentRecords.get(currentId);
      if (currentRecord) {
        this.#applySelectionVisual(sprite, currentRecord);
      }
    });
  }

  async loadOrUpdateAgentAtlas(eventPayload) {
    const currentRevision = this.loadedRevisions.get(eventPayload.id);
    if (currentRevision === eventPayload.revision) {
      return;
    }
    const request = this.#atlasRequestForEvent(eventPayload);
    try {
      const report = await this.#loadAtlasBatch([request]);
      if (!report.loaded.length) {
        throw new Error(`Failed to load atlas ${request.atlasKey}`);
      }
      await this.#finalizeLoadedAtlas(eventPayload, request);
    } catch (error) {
      console.error(`Failed to load atlas for agent ${eventPayload.id}:`, error);
      const sprite = this.agentSprites.get(eventPayload.id);
      if (sprite && (!request.previousTexture || request.previousTexture === "agent-placeholder")) {
        sprite.setTexture("agent-placeholder");
      }
    }
  }

  async pollAssetFeed(feedPath) {
    const resolvedPath = this.#resolveAssetUrl(feedPath);
    this.latestEventPath = resolvedPath;
    try {
      const response = await fetch(`${resolvedPath}?t=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) {
        return;
      }
      const payload = await response.json();
      if (payload.event === "new_asset_ready") {
        await this.loadOrUpdateAgentAtlas(payload);
      }
    } catch (error) {
      console.error(`Failed to poll asset feed from ${feedPath}:`, error);
    }
  }

  async loadBootstrapAssets(feedPath) {
    const resolvedPath = this.#resolveAssetUrl(feedPath);
    try {
      const response = await fetch(`${resolvedPath}?t=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) {
        return;
      }
      const payload = await response.json();
      await this.loadBootstrapAssetList(payload.assets || []);
    } catch (error) {
      console.error(`Failed to load bootstrap assets from ${feedPath}:`, error);
    }
  }

  async loadBootstrapAssetList(assets) {
    const pendingRequests = [];
    const failures = [];
    for (const assetEvent of assets || []) {
      const currentRevision = this.loadedRevisions.get(assetEvent.id);
      if (currentRevision === assetEvent.revision) {
        continue;
      }
      pendingRequests.push(this.#atlasRequestForEvent(assetEvent));
    }
    if (!pendingRequests.length) {
      return;
    }
    const report = await this.#loadAtlasBatch(pendingRequests);
    await Promise.all(report.loaded.map(async (request) => {
      try {
        await this.#finalizeLoadedAtlas(request.eventPayload, request);
      } catch (error) {
        failures.push({ agentId: request.eventPayload.id, error });
      }
    }));
    report.failed.forEach((request) => {
      const sprite = this.agentSprites.get(request.eventPayload.id);
      if (sprite && (!request.previousTexture || request.previousTexture === "agent-placeholder")) {
        sprite.setTexture("agent-placeholder");
      }
      failures.push({
        agentId: request.eventPayload.id,
        error: new Error(`Failed to load atlas ${request.atlasKey}`),
      });
    });
    if (failures.length) {
      failures.forEach(({ agentId, error }) => {
        console.error(`Failed to load bootstrap asset for agent ${agentId}:`, error);
      });
      throw new Error(`Bootstrap asset hydration failed for ${failures.length} agent(s)`);
    }
  }

  #atlasRequestForEvent(eventPayload) {
    return {
      eventPayload,
      atlasKey: `${eventPayload.id}::${eventPayload.revision}`,
      atlasUrl: this.#resolveAssetUrl(eventPayload.atlas_url),
      jsonUrl: this.#resolveAssetUrl(eventPayload.json_url),
      previousTexture: this.loadedTextureKeys.get(eventPayload.id),
    };
  }

  async #animationsForAtlas(eventPayload, request) {
    if (request.atlasJson && typeof request.atlasJson === "object") {
      return buildAnimationMap(request.atlasJson);
    }
    const inlineAnimations = eventPayload?.animations;
    if (inlineAnimations && typeof inlineAnimations === "object" && Object.keys(inlineAnimations).length) {
      return inlineAnimations;
    }
    const response = await fetch(request.jsonUrl, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Failed to load atlas json ${request.jsonUrl}`);
    }
    const atlasJson = await response.json();
    return buildAnimationMap(atlasJson);
  }

  async #finalizeLoadedAtlas(eventPayload, request) {
    const animations = await this.#animationsForAtlas(eventPayload, request);
    this.#rebuildAnimations(eventPayload.id, request.atlasKey, animations);
    this.loadedAnimationMaps.set(eventPayload.id, animations);
    this.loadedTextureKeys.set(eventPayload.id, request.atlasKey);
    this.#swapTexture(eventPayload.id, request.atlasKey, eventPayload.default_animation || "idle_down", animations);
    if (
      request.previousTexture
      && request.previousTexture !== request.atlasKey
      && this.scene.textures.exists(request.previousTexture)
    ) {
      this.scene.textures.remove(request.previousTexture);
    }
    this.loadedRevisions.set(eventPayload.id, eventPayload.revision);
    this.uiBridge.pushAssetEvent(eventPayload);
  }

  #loadAtlasBatch(requests) {
    if (!requests.length) {
      return Promise.resolve({ loaded: [], failed: [] });
    }
    return Promise.all(requests.map(async (request) => {
      try {
        const [atlasJson, atlasImage] = await Promise.all([
          fetch(request.jsonUrl, { cache: "no-store" }).then((response) => {
            if (!response.ok) {
              throw new Error(`Failed to load atlas json ${request.jsonUrl}`);
            }
            return response.json();
          }),
          this.#loadAtlasImage(request.atlasUrl),
        ]);
        if (this.scene.textures.exists(request.atlasKey)) {
          this.scene.textures.remove(request.atlasKey);
        }
        this.scene.textures.addAtlas(request.atlasKey, atlasImage, atlasJson);
        if (!this.scene.textures.exists(request.atlasKey)) {
          throw new Error(`Texture manager did not register atlas ${request.atlasKey}`);
        }
        return { ok: true, request: { ...request, atlasJson } };
      } catch (error) {
        return { ok: false, request, error };
      }
    })).then((results) => ({
      loaded: results.filter((entry) => entry.ok).map((entry) => entry.request),
      failed: results.filter((entry) => !entry.ok).map((entry) => entry.request),
    }));
  }

  #loadAtlasImage(atlasUrl) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => reject(new Error(`Failed to load atlas image ${atlasUrl}`));
      image.src = atlasUrl;
    });
  }

  #rebuildAnimations(agentId, atlasKey, animations) {
    Object.entries(animations).forEach(([stateName, stateConfig]) => {
      const animKey = `${agentId}:${stateName}`;
      if (this.scene.anims.exists(animKey)) {
        this.scene.anims.remove(animKey);
      }
      const frameNames = stateConfig.frames || [];
      if (!frameNames.length) {
        return;
      }
      this.scene.anims.create({
        key: animKey,
        frames: frameNames.map((frameName) => ({ key: atlasKey, frame: frameName })),
        frameRate: stateConfig.frameRate || 6,
        repeat: stateConfig.repeat ?? -1,
      });
    });
  }

  #swapTexture(agentId, atlasKey, defaultAnimation, animations) {
    const sprite = this.agentSprites.get(agentId);
    if (!sprite) {
      return;
    }
    sprite.setOrigin(0.5, 1);
    const fallbackAnimation = animations[defaultAnimation] ? defaultAnimation : Object.keys(animations)[0];
    const firstFrame = fallbackAnimation ? animations[fallbackAnimation]?.frames?.[0] : null;
    if (firstFrame) {
      sprite.setTexture(atlasKey, firstFrame);
    }
    if (fallbackAnimation) {
      this.setAgentAnimation(agentId, fallbackAnimation);
    }
  }
}
