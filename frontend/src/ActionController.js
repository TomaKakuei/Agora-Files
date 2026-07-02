import { firstNonEmpty, safeArray, tileKey, formatTemplate } from "./utils.js";

export class ActionController {
  constructor(worldScene) {
    this.scene = worldScene;
      return new Proxy(this, {
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
    });
}

  setDialogueTarget(agentId) {
    if (this.liveSessionManager.isLiveSessionMode()) {
      if (!agentId) {
        this.liveState.targetAgentId = "";
        this.liveUiController.refreshLiveUi({ force: true });
        return;
      }
      if (this.liveState.targetAgentId === agentId) {
        return;
      }
      if (this.povController.activeAgentRecords({ authoritative: true }).some((agent) => agent.agent_id === agentId)) {
        this.liveState.targetAgentId = agentId;
        this.liveUiController.refreshLiveUi({ force: true });
      }
      return;
    }
    if (!agentId) {
      if (!this.localPovState.dialogueTargetId) {
        return;
      }
      this.localPovState.dialogueTargetId = "";
      this.povController.refreshLocalInteractionPanels();
      this.liveUiController.renderAgentSelector();
      this.liveUiController.renderSelectedTargetBubble();
      return;
    }
    if (this.localPovState.dialogueTargetId === agentId) {
      return;
    }
    const protagonist = this.currentAgents.find((agent) => agent.agent_id === this.povController.protagonistAgentId());
    const nearby = this.nearbyAgentsFor(protagonist, this.povController.povConfig()?.dialogue?.interaction_radius_tiles || 3);
    if (nearby.some((agent) => agent.agent_id === agentId)) {
      this.localPovState.dialogueTargetId = agentId;
      this.povController.refreshLocalInteractionPanels();
      this.liveUiController.renderAgentSelector();
      this.liveUiController.renderSelectedTargetBubble();
    }
  }

  performDialogueAction(actionId) {
    const protagonist = this.currentAgents.find((agent) => agent.agent_id === this.povController.protagonistAgentId());
    const target = this.dialogueTargetRecord();
    const dialogueConfig = this.povController.povConfig()?.dialogue || {};
    const action = safeArray(dialogueConfig.actions).find((candidate) => candidate.action_id === actionId);
    if (!protagonist || !target || !action) {
      return;
    }
    const room = this.roomLookup.get(protagonist.room_id || "");
    const templateVars = {
      self: protagonist.display_name,
      target: target.display_name,
      room: room?.name || protagonist.room_id || "the room",
      decor: safeArray(room?.visual?.decor_tags).slice(0, 2).join(" and ") || "the room",
      target_focus: target.current_focus || target.activity_directive || "they are weighing their next step",
    };
    const speakerLine = formatTemplate(action.speaker_line, templateVars);
    const targetReply = formatTemplate(action.target_reply, templateVars);
    protagonist.current_focus = speakerLine;
    target.current_focus = targetReply;
    this.povController.presentAgentExchange(protagonist.agent_id, speakerLine, target.agent_id, targetReply);
    this.localPovState.dialogueLog.unshift(
      { speaker: protagonist.display_name, text: speakerLine },
      { speaker: target.display_name, text: targetReply },
    );
    this.localPovState.dialogueLog = this.localPovState.dialogueLog.slice(0, Number(this.povController.povConfig()?.recent_log_limit || 14));
    this.povController.logLocalAction("dialogue", `${protagonist.display_name} used ${action.label.toLowerCase()} with ${target.display_name}.`);
    this.syncAgents(this.currentAgents);
    this.povController.refreshLocalInteractionPanels();
  }

  useSelectedItemOnSelf() {
    const itemId = this.localPovState.selectedItemId;
    if (itemId) {
      this.performItemUse(itemId, "");
    }
  }

  useSelectedItemOnTarget(agentId) {
    const itemId = this.localPovState.selectedItemId;
    if (itemId) {
      this.performItemUse(itemId, agentId);
    }
  }

  performItemUse(itemId, targetAgentId = "") {
    const protagonist = this.currentAgents.find((agent) => agent.agent_id === this.povController.protagonistAgentId());
    const protagonistState = this.localAgentState(this.povController.protagonistAgentId());
    const inventoryEntry = safeArray(protagonistState.inventory).find((item) => item.item_id === itemId);
    if (!protagonist || !inventoryEntry || inventoryEntry.quantity <= 0) {
      return;
    }
    const itemConfig = this.povController.povConfig()?.item_use?.effects?.[itemId] || {};
    const itemMeta = this.itemCatalog.get(itemId) || {};
    const target = targetAgentId ? this.currentAgents.find((agent) => agent.agent_id === targetAgentId) : null;
    if (target && !this.nearbyAgentsFor(protagonist, this.povController.povConfig()?.item_use?.interaction_radius_tiles || 2).some((agent) => agent.agent_id === targetAgentId)) {
      return;
    }
    const room = this.roomLookup.get(protagonist.room_id || "");
    const templateVars = {
      self: protagonist.display_name,
      target: target?.display_name || protagonist.display_name,
      room: room?.name || protagonist.room_id || "the guild",
      decor: safeArray(room?.visual?.decor_tags).slice(0, 2).join(" and ") || "the room",
      item_name: firstNonEmpty(itemMeta.name, inventoryEntry.name, itemId),
      target_focus: target?.current_focus || target?.activity_directive || "their next task",
    };
    const quantityCost = Number(itemConfig.consume_quantity || 0);
    const actionText = target
      ? formatTemplate(itemConfig.target_outcome || "{self} uses {item_name} with {target}.", templateVars)
      : formatTemplate(itemConfig.self_outcome || "{self} uses {item_name}.", templateVars);
    if (quantityCost > 0) {
      inventoryEntry.quantity = Math.max(0, inventoryEntry.quantity - quantityCost);
    }
    protagonist.current_focus = actionText;
    if (target) {
      target.current_focus = actionText;
      this.localPovState.dialogueTargetId = target.agent_id;
      this.povController.presentAgentExchange(protagonist.agent_id, actionText, target.agent_id, `${target.display_name} acknowledges the item exchange.`);
    } else {
      this.liveUiController.showSpeechBubble(protagonist.agent_id, actionText);
      this.pulseAgentResponse(protagonist.agent_id, protagonist.agent_id);
    }
    if (inventoryEntry.quantity <= 0 && this.localPovState.selectedItemId === itemId) {
      this.localPovState.selectedItemId =
        protagonistState.inventory.find((item) => item.quantity > 0)?.item_id || "";
    }
    this.povController.logLocalAction("item", actionText);
    this.syncAgents(this.currentAgents);
    this.povController.refreshLocalInteractionPanels();
  }

  pickupGroundItem(lootId) {
    if (!this.povController.localPovEnabled()) {
      return;
    }
    const protagonist = this.currentAgents.find((agent) => agent.agent_id === this.povController.protagonistAgentId());
    const protagonistState = this.localAgentState(this.povController.protagonistAgentId());
    const lootIndex = this.localPovState.groundItems.findIndex((item) => item.loot_id === lootId);
    if (!protagonist || lootIndex < 0) {
      return;
    }
    const loot = this.localPovState.groundItems[lootIndex];
    const radius = Number(this.povController.povConfig()?.inventory_exchange?.pickup_radius_tiles || 1);
    const distance =
      Math.abs(Number(loot.coordinates?.x ?? 0) - Number(protagonist.coordinates?.x ?? 0)) +
      Math.abs(Number(loot.coordinates?.y ?? 0) - Number(protagonist.coordinates?.y ?? 0));
    if (distance > radius || loot.room_id !== protagonist.room_id) {
      this.povController.logLocalAction("pickup", `${protagonist.display_name} is too far away to pick up ${loot.label}.`);
      return;
    }
    const slot = protagonistState.inventory.find((item) => item.item_id === loot.item_id);
    if (slot) {
      slot.quantity += Number(loot.quantity || 1);
    } else {
      protagonistState.inventory.push({
        item_id: loot.item_id,
        quantity: Number(loot.quantity || 1),
        name: loot.name,
        description: loot.description,
      });
    }
    protagonist.current_focus = `${protagonist.display_name} picks up ${loot.label} from ${loot.room_id}.`;
    this.localPovState.groundItems.splice(lootIndex, 1);
    if (!this.localPovState.selectedItemId) {
      this.localPovState.selectedItemId = loot.item_id;
    }
    this.liveUiController.showSpeechBubble(protagonist.agent_id, `Picked up ${loot.label}.`);
    this.pulseAgentResponse(protagonist.agent_id, protagonist.agent_id);
    this.povController.logLocalAction("pickup", `${protagonist.display_name} picked up ${loot.label}.`);
    this.syncAgents(this.currentAgents);
    this.povController.refreshLocalInteractionPanels();
  }

  dropSelectedItem() {
    const protagonist = this.currentAgents.find((agent) => agent.agent_id === this.povController.protagonistAgentId());
    const protagonistState = this.localAgentState(this.povController.protagonistAgentId());
    const itemId = this.localPovState.selectedItemId;
    const item = protagonistState.inventory.find((entry) => entry.item_id === itemId);
    if (!protagonist || !item || item.quantity <= 0 || !this.povController.povConfig()?.inventory_exchange?.drop_enabled) {
      return;
    }
    item.quantity -= 1;
    const dropped = {
      loot_id: `dropped_${Date.now()}_${item.item_id}`,
      room_id: protagonist.room_id,
      item_id: item.item_id,
      quantity: 1,
      label: item.name,
      name: item.name,
      description: item.description,
      coordinates: {
        x: Number(protagonist.coordinates?.x ?? 0),
        y: Number(protagonist.coordinates?.y ?? 0),
        z: Number(protagonist.coordinates?.z ?? 0),
      },
    };
    this.localPovState.groundItems.push(dropped);
    protagonist.current_focus = `${protagonist.display_name} drops ${item.name} onto the floor for later.`;
    if (item.quantity <= 0 && this.localPovState.selectedItemId === item.item_id) {
      this.localPovState.selectedItemId = protagonistState.inventory.find((entry) => entry.quantity > 0)?.item_id || "";
    }
    this.liveUiController.showSpeechBubble(protagonist.agent_id, `Dropped ${item.name}.`);
    this.pulseAgentResponse(protagonist.agent_id, protagonist.agent_id);
    this.povController.logLocalAction("drop", `${protagonist.display_name} dropped ${item.name}.`);
    this.syncAgents(this.currentAgents);
    this.povController.refreshLocalInteractionPanels();
  }

  tradeSelectedItem(returnItemId = "") {
    const protagonist = this.currentAgents.find((agent) => agent.agent_id === this.povController.protagonistAgentId());
    const target = this.dialogueTargetRecord();
    const protagonistState = this.localAgentState(this.povController.protagonistAgentId());
    const targetState = this.localAgentState(target?.agent_id || "");
    const itemId = this.localPovState.selectedItemId;
    const item = protagonistState.inventory.find((entry) => entry.item_id === itemId);
    if (!protagonist || !target || !item || item.quantity <= 0) {
      return;
    }
    const radius = Number(this.povController.povConfig()?.inventory_exchange?.trade_radius_tiles || 2);
    if (!this.nearbyAgentsFor(protagonist, radius).some((agent) => agent.agent_id === target.agent_id)) {
      return;
    }
    item.quantity -= 1;
    const targetSlot = targetState.inventory.find((entry) => entry.item_id === item.item_id);
    if (targetSlot) {
      targetSlot.quantity += 1;
    } else {
      targetState.inventory.push({
        item_id: item.item_id,
        quantity: 1,
        name: item.name,
        description: item.description,
      });
    }
    let receivedName = "";
    if (returnItemId) {
      const returnSlot = targetState.inventory.find((entry) => entry.item_id === returnItemId && entry.quantity > 0);
      if (returnSlot) {
        returnSlot.quantity -= 1;
        const protagonistReceive = protagonistState.inventory.find((entry) => entry.item_id === returnSlot.item_id);
        if (protagonistReceive) {
          protagonistReceive.quantity += 1;
        } else {
          protagonistState.inventory.push({
            item_id: returnSlot.item_id,
            quantity: 1,
            name: returnSlot.name,
            description: returnSlot.description,
          });
        }
        receivedName = returnSlot.name;
      }
    }
    const tradeLine = receivedName
      ? `${protagonist.display_name} trades ${item.name} to ${target.display_name} for ${receivedName}.`
      : `${protagonist.display_name} trades ${item.name} to ${target.display_name}.`;
    protagonist.current_focus = tradeLine;
    target.current_focus = receivedName
      ? `${target.display_name} accepts ${item.name} and returns ${receivedName}.`
      : `${target.display_name} accepts ${item.name} from ${protagonist.display_name}.`;
    if (item.quantity <= 0 && this.localPovState.selectedItemId === item.item_id) {
      this.localPovState.selectedItemId = protagonistState.inventory.find((entry) => entry.quantity > 0)?.item_id || "";
    }
    this.povController.presentAgentExchange(
      protagonist.agent_id,
      receivedName ? `Trade ${item.name.toLowerCase()} for ${receivedName.toLowerCase()}?` : `Take this ${item.name.toLowerCase()}.`,
      target.agent_id,
      receivedName ? `${target.display_name} agrees and offers ${receivedName}.` : `${target.display_name} accepts the trade.`,
    );
    this.povController.logLocalAction("trade", tradeLine);
    this.syncAgents(this.currentAgents);
    this.povController.refreshLocalInteractionPanels();
  }

  quoteSelectedItem(asTradeRequest = false) {
    const protagonist = this.currentAgents.find((agent) => agent.agent_id === this.povController.protagonistAgentId());
    const target = this.dialogueTargetRecord();
    const protagonistState = this.localAgentState(this.povController.protagonistAgentId());
    const itemId = this.localPovState.selectedItemId;
    const item = protagonistState.inventory.find((entry) => entry.item_id === itemId);
    if (!protagonist || !target || !item || item.quantity <= 0 || !this.povController.negotiationConfig().enabled) {
      return;
    }
    const radius = Number(this.povController.inventoryExchangeConfig()?.trade_radius_tiles || 2);
    if (!this.nearbyAgentsFor(protagonist, radius).some((agent) => agent.agent_id === target.agent_id)) {
      return;
    }
    if (!asTradeRequest) {
      this.resolveGiftQuote(protagonist, target, item);
      return;
    }
    this.resolveTradeQuote(protagonist, target, item);
  }

  resolveGiftQuote(protagonist, target, item) {
    const templates = this.povController.negotiationConfig().response_templates || {};
    const giftRatio = Number(this.povController.negotiationConfig().gift_accept_ratio || 0.15);
    const itemMeta = this.itemCatalog.get(item.item_id) || {};
    const itemValue = Math.max(1, Number(itemMeta.price || 0));
    const targetState = this.localAgentState(target.agent_id);
    const sameItemCount = targetState.inventory.find((entry) => entry.item_id === item.item_id)?.quantity || 0;
    const accepts = (itemValue / 20 >= giftRatio && sameItemCount < 2) || target.main_character;
    if (accepts) {
      const protagonistState = this.localAgentState(this.povController.protagonistAgentId());
      item.quantity -= 1;
      const targetSlot = targetState.inventory.find((entry) => entry.item_id === item.item_id);
      if (targetSlot) {
        targetSlot.quantity += 1;
      } else {
        targetState.inventory.push({
          item_id: item.item_id,
          quantity: 1,
          name: item.name,
          description: item.description,
        });
      }
      const line = formatTemplate(templates.gift_accept || "{target} accepts the offer from {self}.", {
        self: protagonist.display_name,
        target: target.display_name,
      });
      protagonist.current_focus = `${protagonist.display_name} offers ${item.name} to ${target.display_name}.`;
      target.current_focus = line;
      this.povController.presentAgentExchange(protagonist.agent_id, `Please take this ${item.name.toLowerCase()}.`, target.agent_id, line);
      if (item.quantity <= 0 && this.localPovState.selectedItemId === item.item_id) {
        this.localPovState.selectedItemId = protagonistState.inventory.find((entry) => entry.quantity > 0)?.item_id || "";
      }
      this.povController.logLocalAction("offer", `${target.display_name} accepted ${item.name} from ${protagonist.display_name}.`);
    } else {
      const line = formatTemplate(templates.gift_reject || "{target} refuses the offer.", {
        self: protagonist.display_name,
        target: target.display_name,
      });
      protagonist.current_focus = `${protagonist.display_name} offers ${item.name} to ${target.display_name}.`;
      target.current_focus = line;
      this.povController.presentAgentExchange(protagonist.agent_id, `Would this ${item.name.toLowerCase()} help?`, target.agent_id, line);
      this.povController.logLocalAction("offer", `${target.display_name} refused ${item.name} from ${protagonist.display_name}.`);
    }
    this.syncAgents(this.currentAgents);
    this.povController.refreshLocalInteractionPanels();
  }

  resolveTradeQuote(protagonist, target, offeredItem) {
    const negotiation = this.povController.negotiationConfig();
    const templates = negotiation.response_templates || {};
    const offerValue = Math.max(1, Number(this.itemCatalog.get(offeredItem.item_id)?.price || 0));
    const targetState = this.localAgentState(target.agent_id);
    const preferredReturns = safeArray(negotiation.room_return_preferences?.[target.room_id]);
    const candidateReturn = this.pickInventoryCandidate(targetState.inventory, preferredReturns);
    if (!candidateReturn) {
      const rejectLine = formatTemplate(templates.trade_reject || "{target} refuses the deal.", {
        self: protagonist.display_name,
        target: target.display_name,
      });
      this.povController.presentAgentExchange(protagonist.agent_id, `Trade ${offeredItem.name.toLowerCase()}?`, target.agent_id, rejectLine);
      this.povController.logLocalAction("trade", `${target.display_name} had nothing ready to trade back.`);
      this.syncAgents(this.currentAgents);
      this.povController.refreshLocalInteractionPanels();
      return;
    }
    const returnValue = Math.max(1, Number(this.itemCatalog.get(candidateReturn.item_id)?.price || 0));
    const acceptRatio = Number(negotiation.trade_accept_ratio || 0.8);
    if (offerValue >= returnValue * acceptRatio) {
      this.tradeSelectedItem(candidateReturn.item_id);
      return;
    }
    if (!negotiation.counteroffer_enabled) {
      const rejectLine = formatTemplate(templates.trade_reject || "{target} refuses the deal.", {
        self: protagonist.display_name,
        target: target.display_name,
      });
      this.povController.presentAgentExchange(protagonist.agent_id, `Trade ${offeredItem.name.toLowerCase()}?`, target.agent_id, rejectLine);
      this.povController.logLocalAction("trade", `${target.display_name} rejected the trade request.`);
      return;
    }
    const protagonistState = this.localAgentState(this.povController.protagonistAgentId());
    const requestedItemId = this.chooseCounterRequestedItem(protagonistState.inventory, candidateReturn.item_id);
    const requestedItem = protagonistState.inventory.find((entry) => entry.item_id === requestedItemId && entry.quantity > 0);
    if (!requestedItem) {
      const rejectLine = formatTemplate(templates.trade_reject || "{target} refuses the deal.", {
        self: protagonist.display_name,
        target: target.display_name,
      });
      this.povController.presentAgentExchange(protagonist.agent_id, `Trade ${offeredItem.name.toLowerCase()}?`, target.agent_id, rejectLine);
      this.povController.logLocalAction("trade", `${target.display_name} rejected the trade request.`);
      return;
    }
    const offer = {
      offer_id: `trade_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      status: "countered",
      target_agent_id: target.agent_id,
      offered_item_id: offeredItem.item_id,
      offered_item_name: offeredItem.name,
      requested_item_id: requestedItem.item_id,
      requested_item_name: requestedItem.name,
      return_item_id: candidateReturn.item_id,
      return_item_name: candidateReturn.name,
      copy: formatTemplate(templates.trade_counter || "{target} counters.", {
        self: protagonist.display_name,
        target: target.display_name,
        requested_item: requestedItem.name,
        return_item: candidateReturn.name,
      }),
    };
    this.localPovState.tradeOffers.unshift(offer);
    this.localPovState.tradeOffers = this.localPovState.tradeOffers.slice(0, Number(this.povController.povConfig()?.recent_log_limit || 14));
    protagonist.current_focus = `${protagonist.display_name} opens a trade request with ${target.display_name}.`;
    target.current_focus = offer.copy;
    this.povController.presentAgentExchange(protagonist.agent_id, `Trade ${offeredItem.name.toLowerCase()}?`, target.agent_id, offer.copy);
    this.povController.logLocalAction("trade", `${target.display_name} counteroffered instead of accepting outright.`);
    this.syncAgents(this.currentAgents);
    this.povController.refreshLocalInteractionPanels();
  }

  pickInventoryCandidate(inventory, preferredIds = []) {
    const preferred = safeArray(preferredIds)
      .map((itemId) => safeArray(inventory).find((entry) => entry.item_id === itemId && entry.quantity > 0))
      .find(Boolean);
    if (preferred) {
      return preferred;
    }
    return safeArray(inventory)
      .filter((entry) => entry.quantity > 0)
      .sort((left, right) => (Number(this.itemCatalog.get(right.item_id)?.price || 0) - Number(this.itemCatalog.get(left.item_id)?.price || 0)))[0] || null;
  }

  chooseCounterRequestedItem(inventory, excludeItemId = "") {
    const fallback = safeArray(this.povController.negotiationConfig().fallback_requested_items)
      .find((itemId) => itemId !== excludeItemId && safeArray(inventory).some((entry) => entry.item_id === itemId && entry.quantity > 0));
    if (fallback) {
      return fallback;
    }
    return safeArray(inventory)
      .filter((entry) => entry.item_id !== excludeItemId && entry.quantity > 0)
      .sort((left, right) => Number(this.itemCatalog.get(right.item_id)?.price || 0) - Number(this.itemCatalog.get(left.item_id)?.price || 0))[0]?.item_id || "";
  }

  acceptTradeOffer(offerId) {
    const offer = this.localPovState.tradeOffers.find((entry) => entry.offer_id === offerId);
    if (!offer || offer.status !== "countered") {
      return;
    }
    const protagonist = this.currentAgents.find((agent) => agent.agent_id === this.povController.protagonistAgentId());
    const target = this.currentAgents.find((agent) => agent.agent_id === offer.target_agent_id);
    const protagonistState = this.localAgentState(this.povController.protagonistAgentId());
    const targetState = this.localAgentState(offer.target_agent_id);
    const give = protagonistState.inventory.find((entry) => entry.item_id === offer.requested_item_id && entry.quantity > 0);
    const receive = targetState.inventory.find((entry) => entry.item_id === offer.return_item_id && entry.quantity > 0);
    if (!protagonist || !target || !give || !receive) {
      offer.status = "expired";
      this.refreshTradeModule();
      return;
    }
    give.quantity -= 1;
    receive.quantity -= 1;
    const protagonistReceive = protagonistState.inventory.find((entry) => entry.item_id === receive.item_id);
    if (protagonistReceive) {
      protagonistReceive.quantity += 1;
    } else {
      protagonistState.inventory.push({ item_id: receive.item_id, quantity: 1, name: receive.name, description: receive.description });
    }
    const targetReceive = targetState.inventory.find((entry) => entry.item_id === give.item_id);
    if (targetReceive) {
      targetReceive.quantity += 1;
    } else {
      targetState.inventory.push({ item_id: give.item_id, quantity: 1, name: give.name, description: give.description });
    }
    offer.status = "accepted";
    const line = formatTemplate(this.povController.negotiationConfig().response_templates?.counter_accept || "{self} accepts the counteroffer.", {
      self: protagonist.display_name,
      target: target.display_name,
    });
    protagonist.current_focus = line;
    target.current_focus = `${target.display_name} closes the trade with ${protagonist.display_name}.`;
    this.povController.presentAgentExchange(protagonist.agent_id, line, target.agent_id, `${target.display_name} hands over ${receive.name}.`);
    this.povController.logLocalAction("trade", `${protagonist.display_name} accepted ${target.display_name}'s counteroffer.`);
    this.syncAgents(this.currentAgents);
    this.povController.refreshLocalInteractionPanels();
  }

  rejectTradeOffer(offerId) {
    const offer = this.localPovState.tradeOffers.find((entry) => entry.offer_id === offerId);
    if (!offer || offer.status !== "countered") {
      return;
    }
    const protagonist = this.currentAgents.find((agent) => agent.agent_id === this.povController.protagonistAgentId());
    const target = this.currentAgents.find((agent) => agent.agent_id === offer.target_agent_id);
    offer.status = "rejected";
    const line = formatTemplate(this.povController.negotiationConfig().response_templates?.counter_reject || "{self} rejects the counteroffer.", {
      self: protagonist?.display_name || "The protagonist",
      target: target?.display_name || "the target",
    });
    if (protagonist) {
      protagonist.current_focus = line;
    }
    if (target) {
      target.current_focus = `${target.display_name} lets the negotiation fall away.`;
      this.povController.presentAgentExchange(protagonist?.agent_id || "", line, target.agent_id, `${target.display_name} withdraws the offer.`);
    }
    this.povController.logLocalAction("trade", line);
    this.syncAgents(this.currentAgents);
    this.povController.refreshLocalInteractionPanels();
  }



}
