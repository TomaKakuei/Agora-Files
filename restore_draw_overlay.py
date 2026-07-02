import re

method_code = """
  async #drawGeneratedMapOverlay() {
    if (this.liveSessionManager.isLiveSessionMode() && this.exportRenderer.isExportCaptureMode()) {
      return;
    }
    const mapAssetUrl = this.assetResolver.resolveFrontendUrl(this.assetResolver.frontendConfig().map_asset_url || (this.assetSetManifest?.map_asset_url || ""));
    if (!mapAssetUrl) {
      return;
    }
    const versionSuffix = encodeURIComponent(this.assetResolver.assetSetRevision() || Date.now());
    const resolvedUrl = `${mapAssetUrl}${mapAssetUrl.includes("?") ? "&" : "?"}v=${versionSuffix}`;
    const textureKey = `generated-map:${mapAssetUrl}:${versionSuffix}`;
    await this.#loadImage(textureKey, resolvedUrl);
    if (this.generatedMapKey && this.generatedMapKey !== textureKey && this.textures.exists(this.generatedMapKey)) {
      this.textures.remove(this.generatedMapKey);
    }
    this.generatedMapKey = textureKey;
    if (this.generatedMapImage) {
      this.generatedMapImage.destroy();
      this.generatedMapImage = null;
    }
    const { width, height, margin } = this.worldDimensions;
    const image = this.add.image(width / 2, height / 2, textureKey);
    image.setDisplaySize(Math.max(1, width - margin * 2), Math.max(1, height - margin * 2));
    image.setDepth(-8);
    image.setAlpha(1);
    this.generatedMapImage = image;
  }
"""

with open("frontend/src/WorldScene.js", "r") as f:
    content = f.read()

content = content.replace("async #hydrateGeneratedAssets", method_code + "\n  async #hydrateGeneratedAssets")

with open("frontend/src/WorldScene.js", "w") as f:
    f.write(content)

print("Restored drawGeneratedMapOverlay")
