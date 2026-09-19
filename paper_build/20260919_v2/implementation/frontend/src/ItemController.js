import { firstNonEmpty, safeArray, tileKey, Phaser } from "./utils.js";

export class ItemController {
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

  seedGroundItems() {
    this.localPovState.groundItems = safeArray(this.povController.povConfig()?.inventory_exchange?.room_loot).map((entry) => {
      const itemMeta = this.itemCatalog.get(entry.item_id) || {};
      return {
        loot_id: entry.loot_id,
        room_id: entry.room_id,
        item_id: entry.item_id,
        quantity: Number(entry.quantity || 1),
        label: firstNonEmpty(entry.label, itemMeta.name, entry.item_id, "Item"),
        name: firstNonEmpty(itemMeta.name, entry.item_id, "Item"),
        description: firstNonEmpty(itemMeta.description, ""),
        price: Number(itemMeta.price || 0),
        coordinates: {
          x: Number(entry.coordinates?.x ?? 0),
          y: Number(entry.coordinates?.y ?? 0),
          z: Number(entry.coordinates?.z ?? 0),
        },
      };
    });
  }

  itemIconStyle(itemId) {
    return this.povController.inventoryExchangeConfig()?.item_icon_styles?.[itemId] || {
      shape: "scroll",
      primary: "#d4c7a4",
      secondary: "#fff4d5",
      accent: "#7b5e34",
    };
  }

  itemIconTextureKey(itemId) {
    return `pov-item-icon:${itemId}`;
  }

  ensureItemIconTexture(itemId) {
    const textureKey = this.itemIconTextureKey(itemId);
    if (this.textures.exists(textureKey)) {
      return textureKey;
    }
    const style = this.itemIconStyle(itemId);
    const size = 28;
    const graphics = this.make.graphics({ x: 0, y: 0, add: false });
    const primary = Phaser.Display.Color.HexStringToColor(style.primary || "#d4c7a4").color;
    const secondary = Phaser.Display.Color.HexStringToColor(style.secondary || "#fff4d5").color;
    const accent = Phaser.Display.Color.HexStringToColor(style.accent || "#7b5e34").color;
    graphics.fillStyle(0x1b1620, 0.0);
    if (style.shape === "potion") {
      graphics.fillStyle(primary, 1);
      graphics.fillRoundedRect(9, 9, 10, 12, 3);
      graphics.fillStyle(secondary, 1);
      graphics.fillRect(11, 5, 6, 4);
      graphics.fillStyle(accent, 1);
      graphics.fillRect(12, 3, 4, 2);
    } else if (style.shape === "crystal") {
      graphics.fillStyle(primary, 1);
      graphics.fillPoints([{ x: 14, y: 3 }, { x: 23, y: 12 }, { x: 18, y: 25 }, { x: 8, y: 22 }, { x: 5, y: 11 }], true);
      graphics.fillStyle(secondary, 1);
      graphics.fillTriangle(13, 8, 18, 13, 12, 18);
    } else if (style.shape === "ingot") {
      graphics.fillStyle(primary, 1);
      graphics.fillRoundedRect(5, 10, 18, 10, 3);
      graphics.fillStyle(secondary, 1);
      graphics.fillRect(8, 12, 10, 3);
    } else if (style.shape === "map") {
      graphics.fillStyle(primary, 1);
      graphics.fillRoundedRect(4, 5, 20, 18, 2);
      graphics.fillStyle(secondary, 1);
      graphics.fillRect(7, 8, 14, 12);
      graphics.fillStyle(accent, 1);
      graphics.fillRect(10, 11, 8, 2);
      graphics.fillRect(13, 14, 5, 2);
    } else if (style.shape === "satchel") {
      graphics.fillStyle(primary, 1);
      graphics.fillRoundedRect(6, 9, 16, 13, 4);
      graphics.fillStyle(accent, 1);
      graphics.fillRect(10, 6, 8, 3);
      graphics.fillStyle(secondary, 1);
      graphics.fillRect(12, 13, 4, 3);
    } else if (style.shape === "toolkit") {
      graphics.fillStyle(primary, 1);
      graphics.fillRoundedRect(5, 10, 18, 11, 3);
      graphics.fillStyle(accent, 1);
      graphics.fillRect(12, 7, 4, 4);
      graphics.fillStyle(secondary, 1);
      graphics.fillRect(9, 13, 10, 2);
    } else if (style.shape === "herbs") {
      graphics.fillStyle(primary, 1);
      graphics.fillEllipse(10, 12, 8, 14);
      graphics.fillEllipse(18, 11, 8, 14);
      graphics.fillEllipse(14, 18, 8, 10);
      graphics.fillStyle(accent, 1);
      graphics.fillRect(13, 16, 2, 8);
      graphics.fillStyle(secondary, 1);
      graphics.fillCircle(18, 7, 2);
    } else {
      graphics.fillStyle(primary, 1);
      graphics.fillRoundedRect(6, 4, 16, 20, 3);
      graphics.fillStyle(secondary, 1);
      graphics.fillRect(9, 8, 10, 12);
      graphics.fillStyle(accent, 1);
      graphics.fillRect(11, 6, 6, 2);
    }
    graphics.lineStyle(2, accent, 1);
    graphics.strokeRoundedRect(4, 3, 20, 22, 4);
    graphics.generateTexture(textureKey, size, size);
    graphics.destroy();
    return textureKey;
  }

  itemSwatchStyle(itemId) {
    const style = this.itemIconStyle(itemId);
    return `background: linear-gradient(135deg, ${style.secondary || "#fff4d5"}, ${style.primary || "#d4c7a4"}); border-color: ${style.accent || "#7b5e34"};`;
  }


}
