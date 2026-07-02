import os
import sqlite3
import json

def main():
    draft_id = "creator_20260601_094725_22b68786"
    package_root = str(Path(__file__).resolve().parent.parent)
    db_path = f"{package_root}/output/world_creator_drafts/{draft_id}/revisions/r001/world_package.db"
    
    print(f"=== ASSERTING AND VERIFYING DRAFT: {draft_id} ===")
    print(f"Database Path: {db_path}")
    
    if not os.path.exists(db_path):
        print("Error: world_package.db file not found!")
        return
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Verify files table exists and can be queried
    cursor.execute("SELECT path FROM files")
    paths = [r[0] for r in cursor.fetchall()]
    print(f"\nFiles inside package database: {len(paths)} files found.")
    
    # Check world_config.json
    cursor.execute("SELECT content FROM files WHERE path = 'run_inputs/world_config.json'")
    row = cursor.fetchone()
    if not row:
        print("Error: world_config.json not found in database!")
        conn.close()
        return
        
    config = json.loads(row[0].decode('utf-8'))
    rooms = config.get("space", {}).get("rooms", []) or config.get("scenario_meta", {}).get("rooms", [])
    
    print("\n--- Room Tiles in world_config.json ---")
    forbidden_floors = ["jade_tile", "bamboo_planks"]
    forbidden_walls = ["red_pillar_wall", "bamboo_wall"]
    
    clean_count = 0
    glass_count = 0
    other_floors = []
    
    for r in rooms:
        name = r.get("name")
        visual = r.get("visual", {})
        floor = visual.get("floor_tile")
        wall = visual.get("wall_tile")
        print(f"Room: {name:30} | Floor Tile: {floor:15} | Wall Tile: {wall:20}")
        
        if floor == "clean_tile":
            clean_count += 1
        else:
            other_floors.append(floor)
            
        if wall == "glass_case_wall":
            glass_count += 1
            
        assert floor not in forbidden_floors, f"CRITICAL LEAK: Forbidden floor tile '{floor}' found in room '{name}'!"
        assert wall not in forbidden_walls, f"CRITICAL LEAK: Forbidden wall tile '{wall}' found in room '{name}'!"
        
    # Check map_grid.json
    cursor.execute("SELECT content FROM files WHERE path = 'run_inputs/scenario/map_grid.json'")
    row_grid = cursor.fetchone()
    if not row_grid:
        print("Error: map_grid.json not found in database!")
        conn.close()
        return
        
    grid = json.loads(row_grid[0].decode('utf-8'))
    grid_rooms = grid.get("rooms", [])
    print("\n--- Room Tiles in map_grid.json ---")
    for gr in grid_rooms:
        name = gr.get("name")
        visual = gr.get("visual", {})
        floor = visual.get("floor_tile")
        wall = visual.get("wall_tile")
        print(f"Room: {name:30} | Floor Tile: {floor:15} | Wall Tile: {wall:20}")
        assert floor not in forbidden_floors, f"CRITICAL LEAK: Forbidden floor tile '{floor}' in map_grid room '{name}'!"
        assert wall not in forbidden_walls, f"CRITICAL LEAK: Forbidden wall tile '{wall}' in map_grid room '{name}'!"
        
    conn.close()
    print("\n=== VERIFICATION SUCCESS ===")
    print(f"1. Database generated successfully and contains {len(paths)} serialized resource files.")
    print(f"2. Traditional Panjiayuan Chinese tiles (jade_tile, bamboo_planks, red_pillar_wall, bamboo_wall) are 100% ABSENT.")
    print(f"3. Modern commercial tiles used: {clean_count} rooms with clean_tile, {glass_count} rooms with glass_case_wall.")
    print("Everything is verified OK!")

if __name__ == "__main__":
    main()
