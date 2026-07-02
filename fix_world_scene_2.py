import re

mapping = {
    "applyAgentPortraitsToState": "assetResolver.applyAgentPortraitsToState",
    "assetsFromManifest": "assetResolver.assetsFromManifest",
    "attachAgentPortraits": "assetResolver.attachAgentPortraits",
    "frontendConfig": "assetResolver.frontendConfig",
    "refreshAgentPortraitLookup": "assetResolver.refreshAgentPortraitLookup",
    "resolveFrontendUrl": "assetResolver.resolveFrontendUrl",
    "applyRoomHighlight": "worldRenderer.applyRoomHighlight",
    "buildRoomCollisionIndex": "worldRenderer.buildRoomCollisionIndex",
    "buildRoomTileIndex": "worldRenderer.buildRoomTileIndex",
    "directionAliasMap": "worldRenderer.directionAliasMap",
    "drawWorld": "worldRenderer.drawWorld",
    "fitWorld": "worldRenderer.fitWorld",
    "isBlockedTile": "worldRenderer.isBlockedTile",
    "movementCollisionConfig": "worldRenderer.movementCollisionConfig",
    "renderGroundItems": "worldRenderer.renderGroundItems",
    "tileHasCollisionKind": "worldRenderer.tileHasCollisionKind",
    "applyPresenceFocus": "cameraController.applyPresenceFocus",
    "installCameraControls": "cameraController.installCameraControls",
    "setViewMode": "cameraController.setViewMode",
    "createLiveSession": "liveSessionManager.createLiveSession",
    "fetchLiveState": "liveSessionManager.fetchLiveState",
    "submitLiveAction": "liveSessionManager.submitLiveAction",
}

with open("frontend/src/WorldScene.js", "r") as f:
    content = f.read()

for old, new in mapping.items():
    content = re.sub(rf"this\.#{old}\b", f"this.{new}", content)

with open("frontend/src/WorldScene.js", "w") as f:
    f.write(content)

print("Replaced second batch of method calls.")

# Now fix LiveSessionManager.js to make those methods public
with open("frontend/src/LiveSessionManager.js", "r") as f:
    lsm = f.read()

lsm = lsm.replace("async #createLiveSession", "async createLiveSession")
lsm = lsm.replace("async #fetchLiveState", "async fetchLiveState")
lsm = lsm.replace("async #submitLiveAction", "async submitLiveAction")

with open("frontend/src/LiveSessionManager.js", "w") as f:
    f.write(lsm)

print("Made LiveSessionManager methods public.")
