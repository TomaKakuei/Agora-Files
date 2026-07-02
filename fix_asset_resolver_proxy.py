import os
import re

filepath = "frontend/src/AssetResolver.js"
with open(filepath, 'r') as f:
    content = f.read()

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
            worldScene.assetResolver
        ];
        for (const ctrl of controllers) {
            if (ctrl && prop in ctrl) {
                return typeof ctrl[prop] === 'function' ? ctrl[prop].bind(ctrl) : ctrl[prop];
            }
        }
        return undefined;
      }
    });"""

constructor_match = re.search(r'constructor\(worldScene\)\s*\{\s*this\.scene\s*=\s*worldScene;\s*', content)
if constructor_match:
    new_content = content[:constructor_match.end()] + new_proxy_code + content[constructor_match.end():]
    with open(filepath, 'w') as f:
        f.write(new_content)
    print("Added proxy to AssetResolver.js")
else:
    print("Constructor not found in AssetResolver.js")

