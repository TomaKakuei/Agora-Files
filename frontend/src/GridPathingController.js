import { firstNonEmpty, safeArray, tileKey } from "./utils.js";

export class GridPathingController {
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

  preferredRoomForTile(currentRoomId, currentCoord, targetRooms, targetCoord, { allowBoundaryBypass = false } = {}) {
    const resolved = this.resolveTransitionRoom(currentRoomId, currentCoord, targetRooms, targetCoord);
    if (resolved) {
      return resolved;
    }
    if (!allowBoundaryBypass) {
      return "";
    }
    return targetRooms.find((roomId) => roomId !== currentRoomId) || targetRooms[0] || "";
  }

  resolveMoveDestination(currentRoomId, currentCoord, direction) {
    const deltas = {
      up: { dx: 0, dy: -1 },
      down: { dx: 0, dy: 1 },
      left: { dx: -1, dy: 0 },
      right: { dx: 1, dy: 0 },
    };
    const delta = deltas[firstNonEmpty(direction, "")];
    if (!delta) {
      return { ok: false, reason: "direction" };
    }
    const currentX = Number(currentCoord?.x ?? 0);
    const currentY = Number(currentCoord?.y ?? 0);
    const currentZ = Number(currentCoord?.z ?? 0);
    const collisionConfig = this.worldRenderer.movementCollisionConfig();
    if (collisionConfig.disableWorldGeometry) {
      const probeX = currentX + delta.dx;
      const probeY = currentY + delta.dy;
      const targetRooms = Array.from(this.roomsForTile(probeX, probeY, currentZ));
      if (!targetRooms.length) {
        return { ok: false, reason: "boundary" };
      }
      const nextRoomId = this.preferredRoomForTile(
        currentRoomId,
        { x: currentX, y: currentY, z: currentZ },
        targetRooms,
        { x: probeX, y: probeY, z: currentZ },
        { allowBoundaryBypass: true },
      );
      if (!nextRoomId) {
        return { ok: false, reason: "room_transition" };
      }
      return {
        ok: true,
        nextRoomId,
        nextX: probeX,
        nextY: probeY,
        nextZ: currentZ,
        usedWallHop: false,
      };
    }
    let encounteredInternalWall = false;
    for (let step = 1; step <= collisionConfig.internalWallHopTiles; step += 1) {
      const probeX = currentX + (delta.dx * step);
      const probeY = currentY + (delta.dy * step);
      const targetRooms = Array.from(this.roomsForTile(probeX, probeY, currentZ));
      if (!targetRooms.length) {
        return { ok: false, reason: encounteredInternalWall ? "obstacle" : "boundary" };
      }
      const isInternalWall = this.worldRenderer.tileHasCollisionKind(targetRooms, probeX, probeY, currentZ, "internalWallTiles");
      const isOuterWall = this.worldRenderer.tileHasCollisionKind(targetRooms, probeX, probeY, currentZ, "outerWallTiles");
      if (isOuterWall && !isInternalWall) {
        return { ok: false, reason: "obstacle" };
      }
      if (isInternalWall) {
        encounteredInternalWall = true;
        continue;
      }
      const nextRoomId = this.preferredRoomForTile(
        currentRoomId,
        { x: currentX, y: currentY, z: currentZ },
        targetRooms,
        { x: probeX, y: probeY, z: currentZ },
        { allowBoundaryBypass: encounteredInternalWall || step > 1 },
      );
      if (!nextRoomId) {
        return { ok: false, reason: encounteredInternalWall ? "obstacle" : "room_transition" };
      }
      return {
        ok: true,
        nextRoomId,
        nextX: probeX,
        nextY: probeY,
        nextZ: currentZ,
        usedWallHop: encounteredInternalWall,
      };
    }
    return { ok: false, reason: "obstacle" };
  }

  autoPlacementTile(roomId, indexHint = 0) {
    const collision = this.roomCollisionIndex.get(roomId);
    const candidates = safeArray(collision?.autoPlaceTiles);
    if (candidates.length) {
      return candidates[indexHint % candidates.length];
    }
    return null;
  }

  nearestWalkableTile(roomId, startX, startY) {
    const collision = this.roomCollisionIndex.get(roomId);
    const candidates = safeArray(collision?.walkableTiles);
    if (!candidates.length) {
      return null;
    }
    return candidates
      .map((tile) => ({
        ...tile,
        distance: Math.abs(tile.x - startX) + Math.abs(tile.y - startY),
      }))
      .sort((left, right) => left.distance - right.distance || left.y - right.y || left.x - right.x)[0];
  }

  nearestAvailableWalkableTile(roomId, startX, startY, usedTiles) {
    const collision = this.roomCollisionIndex.get(roomId);
    const candidates = safeArray(collision?.walkableTiles);
    if (!candidates.length) {
      return null;
    }
    return candidates
      .filter((tile) => !usedTiles.has(tileKey(tile.x, tile.y, tile.z)))
      .map((tile) => ({
        ...tile,
        distance: Math.abs(tile.x - startX) + Math.abs(tile.y - startY),
      }))
      .sort((left, right) => left.distance - right.distance || left.y - right.y || left.x - right.x)[0] || null;
  }

  nextAvailableAutoTile(roomId, usedTiles, indexHint = 0) {
    const collision = this.roomCollisionIndex.get(roomId);
    const candidates = safeArray(collision?.autoPlaceTiles);
    if (!candidates.length) {
      return null;
    }
    for (let offset = 0; offset < candidates.length; offset += 1) {
      const tile = candidates[(indexHint + offset) % candidates.length];
      if (!usedTiles.has(tileKey(tile.x, tile.y, tile.z))) {
        return tile;
      }
    }
    return candidates[indexHint % candidates.length] || null;
  }

  resolveRenderableAgentTile(agent, roomId, usedTiles, indexHint = 0) {
    const coordX = Number(agent.coordinates?.x);
    const coordY = Number(agent.coordinates?.y);
    const coordZ = Number(agent.coordinates?.z ?? 0);
    const hasCoords = Number.isFinite(coordX) && Number.isFinite(coordY);
    const currentKey = hasCoords ? tileKey(coordX, coordY, coordZ) : "";
    if (hasCoords && !this.worldRenderer.isBlockedTile(roomId, coordX, coordY, coordZ) && !usedTiles.has(currentKey)) {
      usedTiles.add(currentKey);
      return { x: coordX, y: coordY, z: coordZ, source: "authored" };
    }
    if (hasCoords) {
      const nearest = this.nearestAvailableWalkableTile(roomId, coordX, coordY, usedTiles);
      if (nearest) {
        usedTiles.add(tileKey(nearest.x, nearest.y, nearest.z));
        return { x: nearest.x, y: nearest.y, z: Number(nearest.z ?? 0), source: "snapped" };
      }
    }
    const autoTile = this.nextAvailableAutoTile(roomId, usedTiles, indexHint);
    if (autoTile) {
      usedTiles.add(tileKey(autoTile.x, autoTile.y, autoTile.z));
      return { x: autoTile.x, y: autoTile.y, z: Number(autoTile.z ?? 0), source: "auto" };
    }
    if (hasCoords) {
      usedTiles.add(currentKey);
      return { x: coordX, y: coordY, z: coordZ, source: "fallback" };
    }
    return null;
  }


  roomsForTile(x, y, z = 0) {
    return this.roomTileIndex.get(tileKey(x, y, z)) || new Set();
  }


  resolveTransitionRoom(currentRoomId, currentCoord, targetRooms, targetCoord) {
    if (targetRooms.includes(currentRoomId)) {
      return currentRoomId;
    }
    const movementConfig = this.povController.povConfig()?.movement || {};
    if (!movementConfig.allow_room_transitions) {
      return "";
    }
    const doorwayDistance = Number(movementConfig.doorway_snap_distance_tiles || 1);
    const linked = targetRooms.find((roomId) => this.roomsConnectedByDoor(currentRoomId, roomId, currentCoord, targetCoord, doorwayDistance));
    return linked || "";
  }

  roomsConnectedByDoor(fromRoomId, toRoomId, currentCoord, targetCoord, threshold) {
    const distanceToDoor = (doorPosition, coord) =>
      Math.abs(Number(doorPosition?.x ?? 0) - Number(coord?.x ?? 0)) +
      Math.abs(Number(doorPosition?.y ?? 0) - Number(coord?.y ?? 0));
    const hasDoor = (roomId, linkedRoomId) =>
      safeArray(this.roomLookup.get(roomId)?.doorways).some((doorway) => (
        doorway.connects_to_room_id === linkedRoomId &&
        distanceToDoor(doorway.position, currentCoord) <= threshold &&
        distanceToDoor(doorway.position, targetCoord) <= threshold + 1
      ));
    return hasDoor(fromRoomId, toRoomId) || hasDoor(toRoomId, fromRoomId);
  }

}
