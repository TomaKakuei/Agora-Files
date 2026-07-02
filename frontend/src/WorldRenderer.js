import { safeArray, tileKey, roomBoundsInTiles, roomTilesInGrid, anchorOriginInTiles, firstNonEmpty, Phaser, colorForRoom } from "./utils.js";

export class WorldRenderer {
  constructor(worldScene) {
    this.scene = worldScene;
    this.roomNodes = new Map();
    this.roomCollisionIndex = new Map();
    this.roomTileIndex = new Map();
    this.displayMetrics = {};
    this.worldDimensions = {};

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

  drawWorld() {
    const mapVisual = this.mapGrid.map_visual || {};
    const mapGeneration = this.worldConfig?.pixel_asset_pipeline?.map_generation || {};
    const renderScale = Math.max(1, Number(mapVisual.render_scale || 1));
    const tileWidth = (mapVisual.tile_width || 32) * renderScale;
    const tileHeight = (mapVisual.tile_height || 32) * renderScale;
    const configuredMargin = Number(mapGeneration.margin_px);
    const margin = Number.isFinite(configuredMargin) && configuredMargin >= 0
      ? Math.round(configuredMargin)
      : 56;
    const backgroundHex = firstNonEmpty(mapGeneration.background_hex, "#efe1c4");
    const worldWidth = (this.mapGrid.grid_shape.x * tileWidth) + margin * 2;
    const worldHeight = (this.mapGrid.grid_shape.y * tileHeight) + margin * 2;
    const cameraPaddingX = Math.max(48, Math.round(tileWidth * 2.5), Math.round(this.scale.width * 0.08));
    const cameraPaddingY = Math.max(48, Math.round(tileHeight * 2.5), Math.round(this.scale.height * 0.08));
    this.displayMetrics = { tileWidth, tileHeight, renderScale };
    this.worldDimensions = { width: worldWidth, height: worldHeight, margin, cameraPaddingX, cameraPaddingY };
    if (this.scene) { this.scene.worldDimensions = this.worldDimensions; }
    this.cameras.main.setBounds(
      -cameraPaddingX,
      -cameraPaddingY,
      worldWidth + cameraPaddingX * 2,
      worldHeight + cameraPaddingY * 2,
    );
    this.cameras.main.setBackgroundColor(backgroundHex);
    this.cameras.main.setZoom(mapVisual.camera?.zoom || 0.32);
    this.add.rectangle(worldWidth / 2, worldHeight / 2, worldWidth, worldHeight, Phaser.Display.Color.HexStringToColor(backgroundHex).color).setDepth(-12);

    if (mapVisual.background_url) {
      const textureKey = "map-bg-" + this.worldName;
      if (this.textures.exists(textureKey)) {
        const image = this.add.image(worldWidth / 2, worldHeight / 2, textureKey);
        image.setDisplaySize(Math.max(1, worldWidth), Math.max(1, worldHeight));
        image.setDepth(-8);
      }
    }

    safeArray(this.mapGrid.rooms).forEach((room) => {
      const bounds = roomBoundsInTiles(room, mapVisual.room_width_tiles || 6, mapVisual.room_height_tiles || 4);
      const roomX = margin + bounds.minX * tileWidth;
      const roomY = margin + bounds.minY * tileHeight;
      const roomPixelWidth = bounds.widthTiles * tileWidth;
      const roomPixelHeight = bounds.heightTiles * tileHeight;
      const roomRect = this.add.rectangle(
        roomX + roomPixelWidth / 2,
        roomY + roomPixelHeight / 2,
        Math.max(12, roomPixelWidth - 8),
        Math.max(12, roomPixelHeight - 8),
        colorForRoom(room),
        0.035,
      ).setStrokeStyle(3, 0x6f5039, 0.55).setDepth(-4);
      roomRect.setInteractive({ useHandCursor: true });
      roomRect.on("pointerdown", () => this.focusRoom(room.room_id, { zoom: 0.82 }));
      const title = this.add.text(roomX + 8, roomY + 8, room.name, {
        fontFamily: "monospace",
        fontSize: `${Math.max(12, Math.round(tileWidth * 0.18))}px`,
        color: "#f6ede1",
        backgroundColor: "rgba(255,245,230,0.72)",
        padding: { left: 4, right: 4, top: 2, bottom: 2 },
      });
      title.setDepth(-2);
      title.setInteractive({ useHandCursor: true });
      title.on("pointerdown", () => this.focusRoom(room.room_id, { zoom: 0.82 }));
      const decor = safeArray(room.visual?.decor_tags).slice(0, 2).join(" | ");
      const footer = this.add.text(roomX + 8, roomY + roomPixelHeight - 18, decor, {
        fontFamily: "monospace",
        fontSize: `${Math.max(10, Math.round(tileWidth * 0.11))}px`,
        color: "#6a5343",
      });
      footer.setDepth(-2);
      this.roomNodes.set(room.room_id, {
        room,
        bounds,
        rect: roomRect,
        title,
        footer,
        centerX: roomX + roomPixelWidth / 2,
        centerY: roomY + roomPixelHeight / 2,
      });
    });
  }

  fitWorld() {
    const camera = this.cameras.main;
    camera.stopFollow();
    const viewportWidth = this.scale.width;
    const viewportHeight = this.scale.height;
    const zoomX = viewportWidth / this.worldDimensions.width;
    const zoomY = viewportHeight / this.worldDimensions.height;
    const targetZoom = Phaser.Math.Clamp(Math.min(zoomX, zoomY) * 0.96, 0.08, 1.15);
    camera.setZoom(targetZoom);
    camera.centerOn(this.worldDimensions.width / 2, this.worldDimensions.height / 2);
    this.applyRoomHighlight();
    this.applyPresenceFocus();
  }

  buildRoomTileIndex(mapGrid) {
    const index = new Map();
    safeArray(mapGrid?.rooms).forEach((room) => {
      const tiles = safeArray(room?.footprint_tiles);
      if (tiles.length) {
        tiles.forEach((tile) => {
          const key = tileKey(Number(tile?.x ?? 0), Number(tile?.y ?? 0), Number(tile?.z ?? 0));
          if (!index.has(key)) {
            index.set(key, new Set());
          }
          index.get(key).add(room.room_id);
        });
        return;
      }
      const bounds = roomBoundsInTiles(room, mapGrid?.map_visual?.room_width_tiles || 6, mapGrid?.map_visual?.room_height_tiles || 4);
      for (let y = bounds.minY; y <= bounds.maxY; y += 1) {
        for (let x = bounds.minX; x <= bounds.maxX; x += 1) {
          const key = tileKey(x, y, 0);
          if (!index.has(key)) {
            index.set(key, new Set());
          }
          index.get(key).add(room.room_id);
        }
      }
    });
    return index;
  }

  buildRoomCollisionIndex(mapGrid, worldConfig) {
    const index = new Map();
    const collisionConfig = this.movementCollisionConfig();
    safeArray(mapGrid?.rooms).forEach((room) => {
      const roomTiles = roomTilesInGrid(room, mapGrid);
      const roomTileKeys = new Set(roomTiles.map((tile) => tileKey(tile.x, tile.y, tile.z)));
      const bounds = roomBoundsInTiles(room, mapGrid?.map_visual?.room_width_tiles || 6, mapGrid?.map_visual?.room_height_tiles || 4);
      const doorTiles = new Set(
        safeArray(room?.doorways)
          .map((doorway) => tileKey(Number(doorway?.position?.x ?? 0), Number(doorway?.position?.y ?? 0), Number(doorway?.position?.z ?? 0)))
          .filter((key) => roomTileKeys.has(key)),
      );
      const outerWallTiles = new Set();
      const internalWallTiles = new Set();
      if (!collisionConfig.disableWorldGeometry && collisionConfig.wallClearanceTiles > 0) {
        roomTiles.forEach((tile) => {
          const key = tileKey(tile.x, tile.y, tile.z);
          if (doorTiles.has(key)) {
            return;
          }
          const neighbors = [
            tileKey(tile.x - 1, tile.y, tile.z),
            tileKey(tile.x + 1, tile.y, tile.z),
            tileKey(tile.x, tile.y - 1, tile.z),
            tileKey(tile.x, tile.y + 1, tile.z),
          ];
          let touchesBoundary = false;
          let touchesOuterBoundary = false;
          let touchesSharedBoundary = false;
          neighbors.forEach((neighborKey) => {
            if (roomTileKeys.has(neighborKey)) {
              return;
            }
            touchesBoundary = true;
            const neighborRooms = this.roomTileIndex.get(neighborKey);
            if (neighborRooms?.size) {
              touchesSharedBoundary = true;
            } else {
              touchesOuterBoundary = true;
            }
          });
          if (!touchesBoundary) {
            return;
          }
          if (touchesOuterBoundary) {
            outerWallTiles.add(key);
          } else if (touchesSharedBoundary) {
            internalWallTiles.add(key);
          }
        });
      }

      const wallTiles = new Set([...outerWallTiles, ...internalWallTiles]);
      const blockedByProps = new Set();
      const blocked = new Set([...outerWallTiles]);
      const standableBlocked = new Set([...wallTiles]);
      const walkableTiles = roomTiles
        .map((tile) => ({ x: tile.x, y: tile.y, z: tile.z, key: tileKey(tile.x, tile.y, tile.z) }))
        .filter((tile) => !standableBlocked.has(tile.key));
      const autoPlaceTiles = walkableTiles.length
        ? walkableTiles
        : roomTiles
          .map((tile) => ({ x: tile.x, y: tile.y, z: tile.z, key: tileKey(tile.x, tile.y, tile.z) }))
          .filter((tile) => !standableBlocked.has(tile.key));

      index.set(room.room_id, {
        bounds,
        roomTileKeys,
        doorTiles,
        outerWallTiles,
        internalWallTiles,
        wallTiles,
        blockedByProps,
        blocked,
        standableBlocked,
        walkableTiles,
        autoPlaceTiles,
      });
    });
    return index;
  }

  applyRoomHighlight() {
    this.roomNodes.forEach((node, roomId) => {
      const active = roomId === this.selectedRoomId;
      node.rect.setStrokeStyle(active ? 6 : 3, active ? 0xf0b25b : 0x6f5039, active ? 0.98 : 0.55);
      node.rect.setAlpha(this.viewMode === "pov" ? (active ? 0.12 : 0.012) : (active ? 0.08 : 0.035));
      node.title.setColor(active ? "#7d3b12" : "#4a3323");
      node.footer.setColor(active ? "#8a4218" : "#6a5343");
      node.title.setAlpha(this.viewMode === "pov" ? (active ? 1 : 0.18) : 1);
      node.footer.setAlpha(this.viewMode === "pov" ? (active ? 0.92 : 0.14) : 1);
    });
    this.markRoomNavSelection();
  }

  roomComponentPlacements(room, mapGrid) {
    const library = this.componentLibrary();
    const props = library?.props || {};
    const presets = library?.room_layout_presets || {};
    const bounds = roomBoundsInTiles(room, mapGrid?.map_visual?.room_width_tiles || 6, mapGrid?.map_visual?.room_height_tiles || 4);
    const placements = [];
    const seen = new Set();
    const pushPlacement = (componentId, anchorOverride = "") => {
      const spec = props?.[componentId];
      if (!spec || typeof spec !== "object") {
        return;
      }
      const anchor = firstNonEmpty(anchorOverride, spec.anchor, "center");
      const key = `${componentId}:${anchor}`;
      if (seen.has(key)) {
        return;
      }
      seen.add(key);
      const widthTiles = Math.max(1, Number(spec?.size_tiles?.w || 1));
      const heightTiles = Math.max(1, Number(spec?.size_tiles?.h || 1));
      const origin = anchorOriginInTiles(anchor, bounds, widthTiles, heightTiles);
      placements.push({
        componentId,
        spec,
        anchor,
        origin,
        widthTiles,
        heightTiles,
      });
    };
    safeArray(room?.visual?.decor_tags).forEach((componentId) => pushPlacement(componentId));
    safeArray(presets?.[room?.room_id]?.supplemental_props).forEach((entry) => {
      pushPlacement(entry?.component_id, entry?.anchor);
    });
    return placements;
  }

  componentBlocksMovement(spec) {
    const collisionFlag = spec?.collision?.block_movement;
    if (typeof collisionFlag === "boolean") {
      return collisionFlag;
    }
    const renderName = String(spec?.render || "");
    const blockingRenders = new Set([
      "table_notice",
      "round_table",
      "crate_stack",
      "anvil",
      "furnace",
      "bed",
      "dummy",
      "table_scroll",
      "table_map",
      "bunks",
    ]);
    return blockingRenders.has(renderName);
  }

  movementCollisionConfig() {
    const collision = this.povController.povConfig()?.movement?.collision || {};
    return {
      disableWorldGeometry: collision?.disable_world_geometry === true,
      wallClearanceTiles: Math.max(0, Math.trunc(Number(collision.wall_clearance_tiles ?? 1))),
      propInsetTiles: Math.max(0, Math.trunc(Number(collision.prop_inset_tiles ?? 0))),
      internalWallHopTiles: Math.max(2, Math.trunc(Number(collision.internal_wall_hop_tiles ?? 4))),
    };
  }

  isBlockedTile(roomId, x, y, z = 0) {
    const collision = this.roomCollisionIndex.get(roomId);
    if (!collision) {
      return false;
    }
    return collision.blocked.has(tileKey(x, y, z));
  }

  tileHasCollisionKind(roomIds, x, y, z, kind) {
    const key = tileKey(x, y, z);
    return safeArray(roomIds).some((roomId) => this.roomCollisionIndex.get(roomId)?.[kind]?.has(key));
  }

  renderGroundItems() {
    this.localPovState.groundItemNodes.forEach((node) => node.destroy());
    this.localPovState.groundItemNodes = new Map();
    if (!this.localPovEnabled()) {
      return;
    }
    const { tileWidth, tileHeight } = this.displayMetrics;
    const margin = this.worldDimensions.margin;
    this.localPovState.groundItems.forEach((item) => {
      const textureKey = this.ensureItemIconTexture(item.item_id);
      const container = this.add.container(
        margin + (Number(item.coordinates?.x ?? 0) + 0.5) * tileWidth,
        margin + (Number(item.coordinates?.y ?? 0) + 0.58) * tileHeight,
      );
      container.setDepth(18);
      const plate = this.add.circle(0, 0, Math.max(14, tileWidth * 0.13), 0x1b1620, 0.88);
      plate.setStrokeStyle(3, 0xf0b25b, 0.92);
      const icon = this.add.image(0, 0, textureKey);
      icon.setDisplaySize(Math.max(22, tileWidth * 0.18), Math.max(22, tileWidth * 0.18));
      container.add([plate, icon]);
      container.setSize(plate.width || 28, plate.height || 28);
      container.setInteractive(new Phaser.Geom.Circle(0, 0, Math.max(14, tileWidth * 0.13)), Phaser.Geom.Circle.Contains);
      container.on("pointerdown", () => this.pickupGroundItem(item.loot_id));
      this.localPovState.groundItemNodes.set(item.loot_id, container);
    });
  }

  directionAliasMap() {
    return {
      w: "up",
      arrowup: "up",
      s: "down",
      arrowdown: "down",
      a: "left",
      arrowleft: "left",
      d: "right",
      arrowright: "right",
    };
  }

}
