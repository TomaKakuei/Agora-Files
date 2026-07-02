with open("frontend/src/WorldScene.js", "r") as f:
    content = f.read()

import re

target = """      agentsInRoom.forEach((agent, index) => { console.log("this.gridPathingController:", this.gridPathingController);
        const fallbackTile = this.gridPathingController.resolveRenderableAgentTile(agent, roomId, usedTiles, index)
          || this.gridPathingController.autoPlacementTile(roomId, index)
          || { x: bounds.minX, y: bounds.minY, z: 0 };"""

replacement = """      agentsInRoom.forEach((agent, index) => {
        let fallbackTile;
        try {
          fallbackTile = this.gridPathingController.resolveRenderableAgentTile(agent, roomId, usedTiles, index)
            || this.gridPathingController.autoPlacementTile(roomId, index)
            || { x: bounds.minX, y: bounds.minY, z: 0 };
        } catch (e) {
          throw new Error("DEBUG: this.gridPathingController=" + typeof this.gridPathingController + " | " + (this.gridPathingController ? typeof this.gridPathingController.resolveRenderableAgentTile : "null") + " | " + e.message);
        }"""

if target in content:
    content = content.replace(target, replacement)
    with open("frontend/src/WorldScene.js", "w") as f:
        f.write(content)
    print("Patched successfully!")
else:
    print("Target not found!")
