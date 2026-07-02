import { firstNonEmpty, safeArray, isAbsoluteLikeUrl, normalizeImageCard } from "./utils.js";

export class AssetResolver {
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
    });}

  resolveAssetUrl(value) {
    return this.resolveFrontendUrl(value);
  }

  resolveFrontendBaseUrl() {
    const rawBase = firstNonEmpty(this.assetBaseUrl, window.location.href);
    try {
      const baseUrl = new URL(rawBase, window.location.href);
      const rawText = String(rawBase || "");
      if (!/[?#]/.test(rawText) && !baseUrl.pathname.endsWith("/")) {
        baseUrl.pathname = `${baseUrl.pathname}/`;
      }
      return baseUrl.toString();
    } catch (error) {
      return window.location.href;
    }
  }

  resolveFrontendUrl(value) {
    const text = firstNonEmpty(value, "");
    if (!text) {
      return "";
    }
    if (isAbsoluteLikeUrl(text)) {
      return text;
    }
    try {
      let base = this.assetBaseUrl || window.location.href;
      // If base is a path like "/output/...", we need to prepend window.location.origin to it
      if (base && base.startsWith("/")) {
        base = new URL(base, window.location.origin || "http://127.0.0.1:8125").toString();
      }
      return new URL(text, base).toString();
    } catch (error) {
      return text;
    }
  }

  frontendConfig() {
    if (this.isLiveSessionMode() && this.liveState.state) {
      return {
        event_feed_path: "",
        bootstrap_feed_path: "",
        poll_interval_ms: this.liveState.pollIntervalMs || 1200,
        asset_base_url: this.assetBaseUrl,
      };
    }
    if (this.runtimeState) {
      return {
        event_feed_path: this.runtimeState.asset_feed_url || "./assets/generated/events/latest.json",
        bootstrap_feed_path: this.runtimeState.bootstrap_feed_url || "./assets/generated/events/bootstrap_assets.json",
        poll_interval_ms: this.runtimeState.poll_interval_ms || 3000,
        asset_base_url: this.assetBaseUrl,
      };
    }
    return this.worldConfig?.pixel_asset_pipeline?.frontend || {};
  }

  assetsFromManifest() {
    const directAssets = safeArray(this.assetSetManifest?.assets).filter((asset) => asset && typeof asset === "object");
    if (directAssets.length) {
      return directAssets;
    }
    return safeArray(this.assetSetManifest?.agents)
      .map((record) => record?.asset_bundle?.event)
      .filter((eventPayload) => eventPayload && typeof eventPayload === "object");
  }

  assetSetRevision() {
    return firstNonEmpty(this.assetSetManifest?.revision, "");
  }

  frontendUrlForLocalAssetPath(value) {
    const text = firstNonEmpty(value, "");
    if (!text) {
      return "";
    }
    if (!text.startsWith("/")) {
      return this.resolveFrontendUrl(text);
    }
    const frontendMarker = "/frontend/";
    const markerIndex = text.indexOf(frontendMarker);
    if (markerIndex < 0) {
      return "";
    }
    return this.resolveFrontendUrl(`./${text.slice(markerIndex + frontendMarker.length)}`);
  }

  refreshAgentPortraitLookup() {
    const nextLookup = new Map();
    safeArray(this.assetSetManifest?.agents).forEach((record) => {
      const agentId = firstNonEmpty(record?.agent_id, "");
      const portraitCard = this.portraitCardFromManifestRecord(record);
      if (agentId && portraitCard?.image_url) {
        nextLookup.set(agentId, portraitCard);
      }
    });
    this.agentPortraitById = nextLookup;
  }

  attachAgentPortraits(agentList) {
    return safeArray(agentList).map((agent) => {
      const portraitCard = this.agentPortraitById.get(firstNonEmpty(agent?.agent_id, ""));
      if (!portraitCard?.image_url) {
        return agent;
      }
      return {
        ...agent,
        portrait_image_url: portraitCard.image_url,
        portrait_image_path: portraitCard.source_path,
      };
    });
  }

  portraitCardFromManifestRecord(record) {
    const agentId = firstNonEmpty(record?.agent_id, "");
    if (!agentId) {
      return null;
    }
    const bundle = record?.asset_bundle || {};
    const eventPayload = bundle?.event || {};
    const atlasUrl = this.resolveFrontendUrl(firstNonEmpty(eventPayload?.atlas_url, ""));
    const referenceImageUrl = this.frontendUrlForLocalAssetPath(bundle?.reference_image_summary?.image_path)
      || (atlasUrl ? atlasUrl.replace(/agent_atlas\.png(?:\?.*)?$/, "reference_agent.png") : "");
    const spriteImageUrl = this.frontendUrlForLocalAssetPath(bundle?.sprite_summary?.image_path)
      || this.frontendUrlForLocalAssetPath(bundle?.reused_raw_summary?.image_path)
      || (atlasUrl ? atlasUrl.replace(/agent_atlas\.png(?:\?.*)?$/, "raw_character_128.png") : "");
    const legacySourceUrl = this.frontendUrlForLocalAssetPath(bundle?.sprite_summary?.source)
      || this.frontendUrlForLocalAssetPath(bundle?.reused_raw_summary?.source);
    const portraitUrl = firstNonEmpty(referenceImageUrl, spriteImageUrl, legacySourceUrl, atlasUrl, "");
    if (!portraitUrl) {
      return null;
    }
    return normalizeImageCard({
      label: firstNonEmpty(eventPayload?.display_name, agentId, "Agent portrait"),
      image_url: portraitUrl,
      source_path: firstNonEmpty(
        bundle?.reference_image_summary?.image_path,
        bundle?.sprite_summary?.image_path,
        bundle?.reused_raw_summary?.image_path,
        bundle?.sprite_summary?.source,
        bundle?.reused_raw_summary?.source,
        "",
      ),
      description: firstNonEmpty(bundle?.concept_summary?.summary, ""),
    });
  }

  applyAgentPortraitsToState() {
    if (!this.currentAgents.length) {
      return;
    }
    this.currentAgents = this.attachAgentPortraits(this.currentAgents);
    if (this.selectedAgentRecord?.agent_id) {
      this.selectedAgentRecord = this.currentAgents.find((agent) => agent.agent_id === this.selectedAgentRecord.agent_id) || this.selectedAgentRecord;
    }
    this.renderAgentSelector();
    this.renderSelectedTargetBubble();
    this.refreshImmersiveHud();
  }

}
