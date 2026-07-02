import os
import glob
import re

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

files_to_patch = [
    "frontend/src/LiveSessionManager.js",
    "frontend/src/LiveUiController.js",
    "frontend/src/LiveMovementController.js",
    "frontend/src/PovController.js",
    "frontend/src/CameraController.js",
    "frontend/src/ExportRenderer.js",
    "frontend/src/WorldRenderer.js",
    "frontend/src/AssetResolver.js"
]

for filepath in files_to_patch:
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Replace the old proxy (match the old signature)
    old_proxy_pattern = r'return new Proxy\(this, \{\s*get\(target, prop\) \{\s*if \(prop in target\) return target\[prop\];\s*if \(prop in worldScene\) return typeof worldScene\[prop\] === \'function\' \? worldScene\[prop\]\.bind\(worldScene\) : worldScene\[prop\];\s*const controllers = \[[^\]]*\];\s*for \(const ctrl of controllers\) \{\s*if \(ctrl && prop in ctrl\) \{\s*return typeof ctrl\[prop\] === \'function\' \? ctrl\[prop\]\.bind\(ctrl\) : ctrl\[prop\];\s*\}\s*\}\s*return undefined;\s*\}\s*\}\);'
    
    new_content, count = re.subn(old_proxy_pattern, new_proxy_code, content)
    
    if count == 0:
        # try simple proxy
        old_proxy_pattern2 = r'return new Proxy\(this, \{\s*get\(target, prop\) \{\s*if \(prop in target\) return target\[prop\];\s*if \(prop in worldScene\) return typeof worldScene\[prop\] === \'function\' \? worldScene\[prop\]\.bind\(worldScene\) : worldScene\[prop\];\s*return undefined;\s*\}\s*\}\);'
        new_content, count = re.subn(old_proxy_pattern2, new_proxy_code, content)

    if count == 0:
        print(f"Proxy not found or already updated in {filepath}")
    else:
        with open(filepath, 'w') as f:
            f.write(new_content)
        print(f"Updated proxy in {filepath}")

