import re

with open("frontend/src/WorldScene.js", "r") as f:
    content = f.read()

# I extracted:
# LiveComposerUi methods
ui_methods = [
    "ensureLiveComposerElements", "renderMovementModule", "renderItemModule",
    "renderDialogueModule", "refreshTradeModule", "agentSummaryMarkup",
    "renderPendingActions", "conversationHistoryEntries", "renderActionLog"
]

# ActionController methods
action_methods = [
    "setDialogueTarget", "performDialogueAction", "useSelectedItemOnSelf",
    "useSelectedItemOnTarget", "performItemUse", "pickupGroundItem",
    "dropSelectedItem", "tradeSelectedItem", "quoteSelectedItem",
    "resolveGiftQuote", "resolveTradeQuote", "pickInventoryCandidate",
    "chooseCounterRequestedItem", "acceptTradeOffer", "rejectTradeOffer"
]

# GridPathingController methods
pathing_methods = [
    "preferredRoomForTile", "resolveMoveDestination", "autoPlacementTile",
    "nearestWalkableTile", "nearestAvailableWalkableTile", "nextAvailableAutoTile",
    "resolveRenderableAgentTile", "roomsForTile", "resolveTransitionRoom",
    "roomsConnectedByDoor"
]

# ItemController methods
item_methods = [
    "seedGroundItems", "itemIconStyle", "itemIconTextureKey",
    "ensureItemIconTexture", "itemSwatchStyle"
]

# InputController methods
input_methods = [
    "bindLiveMovementKeys", "movementKeyConfig", "bindMovementKeys",
    "installWindowMovementControls", "movementPressed", "tickLocalPov",
    "tickLiveSession", "liveMoveLeadSnapshot", "playMovementAnimation",
    "seedLocalPovAgentState"
]

# RoomUiController methods
room_ui_methods = [
    "focusRoom", "buildRoomNavigator", "refreshRoomNavigatorCounts",
    "markRoomNavSelection", "updateSpeechBubblePositions"
]

# AgentStateController methods
agent_methods = [
    "localAgentState", "nearbyAgentsFor", "agentRecordById",
    "dialogueTargetRecord", "pulseAgentResponse", "liveAgentDigest",
    "restoreLiveComposerFocus", "controllerAgentRecord"
]

mappings = {}
for m in ui_methods: mappings[m] = "liveComposerUi"
for m in action_methods: mappings[m] = "actionController"
for m in pathing_methods: mappings[m] = "gridPathingController"
for m in item_methods: mappings[m] = "itemController"
for m in input_methods: mappings[m] = "inputController"
for m in room_ui_methods: mappings[m] = "roomUiController"
for m in agent_methods: mappings[m] = "agentStateController"

# Now find where these are called on `this.`
for m, ctrl in mappings.items():
    content = re.sub(r'this\.' + m + r'\(', f'this.{ctrl}.{m}(', content)

with open("frontend/src/WorldScene.js", "w") as f:
    f.write(content)

print("Updated WorldScene.js calls!")
