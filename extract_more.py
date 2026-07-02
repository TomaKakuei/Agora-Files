import re
import os

with open("frontend/src/WorldScene.js", "r") as f:
    content = f.read()

methods = []
for m in re.finditer(r'\n  ([a-zA-Z0-9_]+)\(', content):
    methods.append((m.group(1), m.start() + 1))

methods.append(("_EOF", len(content)))

method_blocks = {}
for i in range(len(methods) - 1):
    name, start = methods[i]
    end = methods[i+1][1]
    block = content[start:end]
    method_blocks[name] = block

item_methods = [
    "seedGroundItems", "itemIconStyle", "itemIconTextureKey",
    "ensureItemIconTexture", "itemSwatchStyle"
]

input_methods = [
    "bindLiveMovementKeys", "movementKeyConfig", "bindMovementKeys",
    "installWindowMovementControls", "movementPressed", "tickLocalPov",
    "tickLiveSession", "liveMoveLeadSnapshot", "playMovementAnimation",
    "seedLocalPovAgentState"
]

room_ui_methods = [
    "focusRoom", "buildRoomNavigator", "refreshRoomNavigatorCounts",
    "markRoomNavSelection", "updateSpeechBubblePositions"
]

def create_class(class_name, method_names):
    code = f'import {{ firstNonEmpty, safeArray, safeString, distanceToDoor, tileKey, formatRelativeTime }} from "./utils.js";\n\n'
    code += f'export class {class_name} {{\n'
    code += f'  constructor(worldScene) {{\n'
    code += f'    this.scene = worldScene;\n'
    code += f'  }}\n\n'
    for m in method_names:
        if m in method_blocks:
            code += method_blocks[m]
    code += f'}}\n'
    with open(f"frontend/src/{class_name}.js", "w") as f:
        f.write(code)

create_class("ItemController", item_methods)
create_class("InputController", input_methods)
create_class("RoomUiController", room_ui_methods)

all_extracted = set(item_methods + input_methods + room_ui_methods)
new_content = ""
prev_end = 0

for i in range(len(methods) - 1):
    name, start = methods[i]
    if name not in all_extracted:
        new_content += content[prev_end:start]
        prev_end = start
    else:
        new_content += content[prev_end:start]
        prev_end = methods[i+1][1]

new_content += content[prev_end:]

with open("frontend/src/WorldScene.js", "w") as f:
    f.write(new_content)

print("Extraction 2 complete!")
