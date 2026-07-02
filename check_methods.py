import re
import os

with open("frontend/src/WorldScene.js", "r") as f:
    world_scene = f.read()

undeclared = set()
for match in re.finditer(r"this\.#([a-zA-Z0-9_]+)\b", world_scene):
    method = match.group(1)
    if not re.search(rf"^\s*(async\s+)?#{method}\s*\(", world_scene, re.MULTILINE):
        undeclared.add(method)

print("Undeclared methods in WorldScene.js:")
for method in sorted(undeclared):
    print(f"- {method}")
