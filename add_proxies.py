import os
import glob

proxy_code = """    return new Proxy(this, {
      get(target, prop) {
        if (prop in target) return target[prop];
        if (prop in worldScene) return typeof worldScene[prop] === 'function' ? worldScene[prop].bind(worldScene) : worldScene[prop];
        return undefined;
      }
    });
"""

files_to_patch = [
    "frontend/src/LiveSessionManager.js",
    "frontend/src/LiveUiController.js",
    "frontend/src/LiveMovementController.js",
    "frontend/src/PovController.js",
    "frontend/src/CameraController.js",
    "frontend/src/ExportRenderer.js"
]

for filepath in files_to_patch:
    with open(filepath, 'r') as f:
        content = f.read()
    
    if "return new Proxy(this," in content:
        print(f"Proxy already exists in {filepath}")
        continue
        
    # Find the constructor
    import re
    constructor_match = re.search(r'constructor\(worldScene\)\s*\{\s*this\.scene\s*=\s*worldScene;\s*', content)
    if not constructor_match:
        print(f"Could not find constructor in {filepath}")
        continue
        
    new_content = content[:constructor_match.end()] + proxy_code + content[constructor_match.end():]
    
    with open(filepath, 'w') as f:
        f.write(new_content)
    print(f"Added proxy to {filepath}")
