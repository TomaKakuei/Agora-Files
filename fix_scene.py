import re

mapping = {
    "isLiveSessionMode": "liveSessionManager.isLiveSessionMode",
    "refreshLiveUi": "liveUiController.refreshLiveUi",
    "refreshImmersiveHud": "liveUiController.refreshImmersiveHud",
    "applyRoomHighlight": "worldRenderer.applyRoomHighlight",
    "applyPresenceFocus": "cameraController.applyPresenceFocus",
}

with open("frontend/src/WorldScene.js", "r") as f:
    content = f.read()

for old, new in mapping.items():
    content = re.sub(rf"scene\.#{old}\b", f"scene.{new}", content)

with open("frontend/src/WorldScene.js", "w") as f:
    f.write(content)

print("Replaced scene.# calls")
