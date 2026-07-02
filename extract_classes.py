import re
import os

with open("frontend/src/WorldScene.js", "r") as f:
    content = f.read()

# We need to find the bounds of methods.
# A method looks like `\n  methodName(...) {\n...`
# We can find all methods using a regex:
methods = []
for m in re.finditer(r'\n  ([a-zA-Z0-9_]+)\(', content):
    methods.append((m.group(1), m.start() + 1)) # +1 to skip the leading \n

methods.append(("_EOF", len(content)))

method_blocks = {}
for i in range(len(methods) - 1):
    name, start = methods[i]
    end = methods[i+1][1]
    
    # Actually, the next method might not start immediately after the previous one's end if there are blank lines.
    # Let's find the closing brace of the current method by matching braces.
    # A safer way: start from the opening brace and count '{' and '}'.
    
    block = content[start:end]
    method_blocks[name] = block

ui_methods = [
    "ensureLiveComposerElements", "renderMovementModule", "renderItemModule",
    "renderDialogueModule", "refreshTradeModule", "agentSummaryMarkup",
    "renderPendingActions", "conversationHistoryEntries", "renderActionLog"
]

action_methods = [
    "setDialogueTarget", "performDialogueAction", "useSelectedItemOnSelf",
    "useSelectedItemOnTarget", "performItemUse", "pickupGroundItem",
    "dropSelectedItem", "tradeSelectedItem", "quoteSelectedItem",
    "resolveGiftQuote", "resolveTradeQuote", "pickInventoryCandidate",
    "chooseCounterRequestedItem", "acceptTradeOffer", "rejectTradeOffer"
]

pathing_methods = [
    "preferredRoomForTile", "resolveMoveDestination", "autoPlacementTile",
    "nearestWalkableTile", "nearestAvailableWalkableTile", "nextAvailableAutoTile",
    "resolveRenderableAgentTile", "roomsForTile", "resolveTransitionRoom",
    "roomsConnectedByDoor"
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

create_class("LiveComposerUi", ui_methods)
create_class("ActionController", action_methods)
create_class("GridPathingController", pathing_methods)

# Now remove these from WorldScene.js
all_extracted = set(ui_methods + action_methods + pathing_methods)
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

print("Extraction complete!")
