import os
import glob

new_proxy_code = """    return new Proxy(this, {
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
    });"""

files_to_patch = [
    "frontend/src/LiveSessionManager.js",
    "frontend/src/LiveUiController.js",
    "frontend/src/LiveMovementController.js",
    "frontend/src/PovController.js",
    "frontend/src/CameraController.js",
    "frontend/src/ExportRenderer.js",
    "frontend/src/WorldRenderer.js",
    "frontend/src/AssetResolver.js",
    "frontend/src/LiveComposerUi.js",
    "frontend/src/ActionController.js",
    "frontend/src/GridPathingController.js",
    "frontend/src/ItemController.js",
    "frontend/src/InputController.js",
    "frontend/src/RoomUiController.js",
    "frontend/src/AgentStateController.js"
]

for filepath in files_to_patch:
    if not os.path.exists(filepath):
        continue
    with open(filepath, 'r') as f:
        content = f.read()
    
    start_str = "return new Proxy(this, {"
    end_str = "    });"
    start_idx = content.find(start_str)
    
    if start_idx != -1:
        end_idx = content.find(end_str, start_idx) + len(end_str)
        new_content = content[:start_idx] + new_proxy_code + content[end_idx:]
    else:
        # Add proxy before the end of the constructor
        # Find constructor(worldScene) { ... }
        cons_str = "constructor(worldScene) {"
        cons_idx = content.find(cons_str)
        if cons_idx != -1:
            end_cons_idx = content.find("}", cons_idx)
            new_content = content[:end_cons_idx] + new_proxy_code + "\n" + content[end_cons_idx:]
        else:
            print(f"Could not patch {filepath}")
            continue
            
    with open(filepath, 'w') as f:
        f.write(new_content)
    print(f"Updated Proxy in {filepath}")

