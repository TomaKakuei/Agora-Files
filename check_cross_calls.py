import re
import os
import glob

# Map of method name to controller
controllers = {
    "LiveSessionManager": "liveSessionManager",
    "LiveUiController": "liveUiController",
    "LiveMovementController": "liveMovementController",
    "PovController": "povController",
    "CameraController": "cameraController",
    "ExportRenderer": "exportRenderer",
}

methods = {}

# Build index of methods
for cls, prop in controllers.items():
    with open(f"frontend/src/{cls}.js", 'r') as f:
        content = f.read()
    
    matches = re.findall(r'^\s+([a-zA-Z0-9_]+)\(', content, re.MULTILINE)
    for m in matches:
        if m != "constructor" and m != "get":
            methods[m] = prop

# Check each controller
for cls in controllers.keys():
    with open(f"frontend/src/{cls}.js", 'r') as f:
        content = f.read()
    
    # Find all this.method calls
    calls = set(re.findall(r'this\.([a-zA-Z0-9_]+)\(', content))
    
    for call in calls:
        if call in methods and methods[call] != controllers[cls]:
            print(f"{cls} calls this.{call}() which belongs to {methods[call]}")

