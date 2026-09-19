import random
from typing import Any, List, Dict, Tuple, Set

def _rects_overlap(r1: Dict[str, int], r2: Dict[str, int]) -> bool:
    return not (
        r1["x"] + r1["w"] <= r2["x"] or
        r1["x"] >= r2["x"] + r2["w"] or
        r1["y"] + r1["h"] <= r2["y"] or
        r1["y"] >= r2["y"] + r2["h"]
    )

def _shared_edge_length(r1: Dict[str, int], r2: Dict[str, int]) -> int:
    # Check if they share an x-edge (they touch horizontally)
    if r1["x"] + r1["w"] == r2["x"] or r2["x"] + r2["w"] == r1["x"]:
        overlap_y_start = max(r1["y"], r2["y"])
        overlap_y_end = min(r1["y"] + r1["h"], r2["y"] + r2["h"])
        return max(0, overlap_y_end - overlap_y_start)
    
    # Check if they share a y-edge (they touch vertically)
    if r1["y"] + r1["h"] == r2["y"] or r2["y"] + r2["h"] == r1["y"]:
        overlap_x_start = max(r1["x"], r2["x"])
        overlap_x_end = min(r1["x"] + r1["w"], r2["x"] + r2["w"])
        return max(0, overlap_x_end - overlap_x_start)
    
    return 0

def pack_rooms(rooms: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Packs rooms into a strict rectangular grid.
    Returns the updated rooms (with x_pos, y_pos), bounding box dimensions, thin walls, and outer walls.
    """
    if not rooms:
        return {"rooms": [], "width_tiles": 0, "height_tiles": 0, "thin_walls": [], "outer_walls": []}
    
    # Store original order
    for i, r in enumerate(rooms):
        r["__original_index"] = i
    
    # Sort rooms by size (largest first helps with tight packing)
    sorted_rooms = sorted(rooms, key=lambda r: r.get("width_tiles", 5) * r.get("height_tiles", 5), reverse=True)
    
    placed: List[Dict[str, int]] = []
    
    # Place first room at origin
    r0 = sorted_rooms[0]
    r0_geom = {"x": 0, "y": 0, "w": int(r0.get("width_tiles", 5)), "h": int(r0.get("height_tiles", 5)), "id": str(r0.get("name", "0"))}
    placed.append(r0_geom)
    
    for r in sorted_rooms[1:]:
        w = int(r.get("width_tiles", 5))
        h = int(r.get("height_tiles", 5))
        rid = str(r.get("name", "temp"))
        
        # Candidate positions: anywhere along the perimeter of already placed rooms
        candidates: List[Tuple[int, int]] = []
        for p in placed:
            # Try placing around p
            # Top
            candidates.extend([(p["x"] + dx, p["y"] - h) for dx in range(-w + 3, p["w"] - 2)])
            # Bottom
            candidates.extend([(p["x"] + dx, p["y"] + p["h"]) for dx in range(-w + 3, p["w"] - 2)])
            # Left
            candidates.extend([(p["x"] - w, p["y"] + dy) for dy in range(-h + 3, p["h"] - 2)])
            # Right
            candidates.extend([(p["x"] + p["w"], p["y"] + dy) for dy in range(-h + 3, p["h"] - 2)])
            
        random.shuffle(candidates) # add some organic variation
        
        best_pos = None
        best_score = 999999 # We want to minimize distance to origin for a compact layout
        
        for (cx, cy) in candidates:
            c_geom = {"x": cx, "y": cy, "w": w, "h": h, "id": rid}
            
            # Check overlap
            if any(_rects_overlap(c_geom, p) for p in placed):
                continue
                
            # Check adjacency constraints (must share at least 3 tiles with AT LEAST ONE placed room)
            valid_adjacency = False
            for p in placed:
                if _shared_edge_length(c_geom, p) >= 3:
                    valid_adjacency = True
                    break
            
            if valid_adjacency:
                score = cx*cx + cy*cy # Distance squared to origin
                if score < best_score:
                    best_score = score
                    best_pos = c_geom
                    
        if not best_pos:
            raise ValueError(f"Failed to find a valid layout position for room {rid} with constraints.")
            
        placed.append(best_pos)
        
    # Offset all rooms so min_x and min_y are 0
    min_x = min(p["x"] for p in placed)
    min_y = min(p["y"] for p in placed)
    max_x = max(p["x"] + p["w"] for p in placed)
    max_y = max(p["y"] + p["h"] for p in placed)
    
    # Update room specs
    for i, p in enumerate(placed):
        sorted_rooms[i]["x_pos"] = p["x"] - min_x
        sorted_rooms[i]["y_pos"] = p["y"] - min_y
        
    global_w = max_x - min_x
    global_h = max_y - min_y
    
    # Validation: BFS
    # Build adjacency graph
    adj: Dict[int, List[int]] = {i: [] for i in range(len(placed))}
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            if _shared_edge_length(placed[i], placed[j]) >= 3:
                adj[i].append(j)
                adj[j].append(i)
                
    # Run BFS from node 0
    visited = set([0])
    queue = [0]
    while queue:
        curr = queue.pop(0)
        for nxt in adj[curr]:
            if nxt not in visited:
                visited.add(nxt)
                queue.append(nxt)
                
    if len(visited) != len(placed):
        raise ValueError("BFS Graph Validation failed: The packed layout contains unreachable rooms (disconnected graph).")
        
    # Extract thin walls (shared edges)
    thin_walls = []
    # Build a solid boolean grid of the layout (1 = inside a room, 0 = outside)
    grid = [[0 for _ in range(global_w)] for _ in range(global_h)]
    
    for p in placed:
        # shifted coordinates
        sx = p["x"] - min_x
        sy = p["y"] - min_y
        for y in range(sy, sy + p["h"]):
            for x in range(sx, sx + p["w"]):
                grid[y][x] = 1

    # Detect outer perimeter via Edge Tracing / Marching
    outer_walls = []
    # Any cell that is inside (1) and adjacent to outside (0) or grid edge is perimeter.
    for y in range(global_h):
        for x in range(global_w):
            if grid[y][x] == 1:
                # check 4 neighbors
                if y == 0 or grid[y-1][x] == 0:
                    outer_walls.append({"x": x, "y": y, "dir": "top"})
                if y == global_h - 1 or grid[y+1][x] == 0:
                    outer_walls.append({"x": x, "y": y, "dir": "bottom"})
                if x == 0 or grid[y][x-1] == 0:
                    outer_walls.append({"x": x, "y": y, "dir": "left"})
                if x == global_w - 1 or grid[y][x+1] == 0:
                    outer_walls.append({"x": x, "y": y, "dir": "right"})
                    
    # Detect thin internal walls
    # A thin wall is a boundary between two different rooms.
    # To find this, we can populate grid with room IDs instead of 1.
    id_grid = [[-1 for _ in range(global_w)] for _ in range(global_h)]
    for i, p in enumerate(placed):
        sx = p["x"] - min_x
        sy = p["y"] - min_y
        for y in range(sy, sy + p["h"]):
            for x in range(sx, sx + p["w"]):
                id_grid[y][x] = i
                
    for y in range(global_h):
        for x in range(global_w):
            if id_grid[y][x] != -1:
                # check right neighbor
                if x + 1 < global_w and id_grid[y][x+1] != -1 and id_grid[y][x+1] != id_grid[y][x]:
                    thin_walls.append({"x": x, "y": y, "dir": "right"})
                # check bottom neighbor
                if y + 1 < global_h and id_grid[y+1][x] != -1 and id_grid[y+1][x] != id_grid[y][x]:
                    thin_walls.append({"x": x, "y": y, "dir": "bottom"})

    final_rooms = sorted(sorted_rooms, key=lambda r: r["__original_index"])
    for r in final_rooms:
        del r["__original_index"]

    return {
        "rooms": final_rooms,
        "width_tiles": global_w,
        "height_tiles": global_h,
        "thin_walls": thin_walls,
        "outer_walls": outer_walls
    }

