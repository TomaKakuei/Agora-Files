import os
import sys
import time
import sqlite3
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from _playwright_firefox import launch_headless_firefox_page

def main():
    print("=== STARTING HEADLESS DANYANG GLASSES CITY STEP-BY-STEP REGRESSION (STEP 1: DB GENERATION & VERIFICATION) ===")
    
    base_url = "http://127.0.0.1:8125"
    
    # Start browser automation to create the draft and verify it
    with sync_playwright() as p:
        print("\nLaunching Firefox browser in headless mode...")
        with launch_headless_firefox_page(p) as (_context, page):
        
            # Capture console logs and page errors
            page.on("console", lambda msg: print(f"[BROWSER CONSOLE] {msg.type}: {msg.text}"))
            page.on("pageerror", lambda err: print(f"[BROWSER ERROR] {err}"))

            print("Navigating to Agora Creator UI...")
            try:
                page.goto(f"{base_url}/creator/index.html", timeout=15000, wait_until="domcontentloaded")
                print("Successfully loaded Creator UI.")
            except Exception as e:
                print(f"Failed to load UI. Is the server running? Error: {e}")
                sys.exit(1)

            print("Filling out the World Description form...")

            unique_suffix = int(time.time())
            world_name = f"丹阳眼镜城_{unique_suffix}"
            print(f"Generated unique world name: {world_name}")

            # Select and fill inputs on `#create-form`
            page.fill('#create-form input[name="world_name"]', world_name)
            page.fill('#create-form input[name="genre"]', 'modern commercial wholesale center, optical glasses market')
            page.fill('#create-form input[name="player_count_target"]', '4')
            page.fill('#create-form input[name="agent_count_target"]', '25') # Failsafe, fast profile generation
            page.select_option('#create-form select[name="focus"]', 'economy and trade-heavy world')
            page.fill('#create-form input[name="seed"]', '12345')
            page.fill('#create-form textarea[name="brief"]',
                      '模拟丹阳眼镜城。A massive modern wholesale market for optical glasses, lenses, and frames. Use modern aesthetics, clean tiles, and glass cases. Merchants haggling over bulk prices, opticians testing lenses, and couriers shipping boxes.')

            print("\nSubmitting form to generate Draft Database (this involves LLM dynamic entity/character calls and sandbox validation)...")
            start_time = time.time()

            try:
                # Click submit button
                page.click('#create-form button[type="submit"]')
                print("Form submitted. Waiting for the Draft Review Panel to become visible (Timeout: 60 minutes)...")

                # Wait for Draft Review Panel to be active (class "hidden" removed)
                page.wait_for_selector('#draft-review:not(.hidden)', timeout=3600000)
                elapsed = int(time.time() - start_time)
                print(f"\n=== DRAFT GENERATED SUCCESSFULLY IN {elapsed}s ===")
            except Exception as e:
                print(f"Error during draft generation: {e}")
                sys.exit(1)

            # Get draft ID from local storage
            draft_id = page.evaluate("window.localStorage.getItem('agora_world_creator_current_draft')")
            print(f"Current Draft ID in LocalStorage: {draft_id}")

            if not draft_id:
                print("Error: Draft ID was not set in local storage!")
                sys.exit(1)

            # Verify draft state from the UI elements
            status_pill_text = page.locator('#draft-status-pill').inner_text().strip()
            print(f"UI Status Pill Text: {status_pill_text}")

            error_banner = page.locator('#draft-error-banner')
            if error_banner.is_visible():
                print(f"UI Draft Error Banner detected: {error_banner.inner_text().strip()}")
                sys.exit(1)

            compiler_badge = page.locator('#compiler-review .compiler-review-badge').inner_text().strip()
            print(f"UI Compiler Review Badge: {compiler_badge}")

            # Check scenario materialization row in the checklist
            materialize_row = page.locator('#validation-checklist .checklist-row').first
            materialize_class = materialize_row.get_attribute('class')
            print(f"UI Scenario Materialization Row class: {materialize_class}")
            if "ok" not in materialize_class:
                print("Scenario materialization failed in the validation checklist!")
                sys.exit(1)

            # Directly query the SQLite database file on disk to confirm there are no Panjiayuan tiles
            package_root = str(Path(__file__).resolve().parent.parent)
            db_path = f"{package_root}/output/world_creator_drafts/{draft_id}/revisions/r001/world_package.db"
            print(f"\nVerifying SQLite DB on disk: {db_path}")

            if not os.path.exists(db_path):
                print("Error: world_package.db file not found on disk!")
                sys.exit(1)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Check world_config.json
            cursor.execute("SELECT content FROM files WHERE path = 'run_inputs/world_config.json'")
            row = cursor.fetchone()
            if not row:
                print("Error: world_config.json not found in files table!")
                conn.close()
                sys.exit(1)

            config = json.loads(row[0].decode('utf-8'))
            rooms = config.get("scenario_meta", {}).get("rooms", [])

            print("\n--- Room Tiles in world_config.json ---")
            forbidden_floors = ["jade_tile", "bamboo_planks"]
            forbidden_walls = ["red_pillar_wall", "bamboo_wall"]

            for r in rooms:
                name = r.get("name")
                visual = r.get("visual", {})
                floor = visual.get("floor_tile")
                wall = visual.get("wall_tile")
                print(f"Room: {name:25} | Floor Tile: {floor:15} | Wall Tile: {wall:20}")

                assert floor not in forbidden_floors, f"CRITICAL: Forbidden floor tile '{floor}' found in room '{name}'!"
                assert wall not in forbidden_walls, f"CRITICAL: Forbidden wall tile '{wall}' found in room '{name}'!"

            # Check map_grid.json
            cursor.execute("SELECT content FROM files WHERE path = 'run_inputs/scenario/map_grid.json'")
            row_grid = cursor.fetchone()
            if not row_grid:
                print("Error: map_grid.json not found in files table!")
                conn.close()
                sys.exit(1)

            grid = json.loads(row_grid[0].decode('utf-8'))
            grid_rooms = grid.get("rooms", [])
            print("\n--- Room Tiles in map_grid.json ---")
            for gr in grid_rooms:
                name = gr.get("name")
                visual = gr.get("visual", {})
                floor = visual.get("floor_tile")
                wall = visual.get("wall_tile")
                print(f"Room: {name:25} | Floor Tile: {floor:15} | Wall Tile: {wall:20}")
                assert floor not in forbidden_floors, f"CRITICAL: Forbidden floor tile '{floor}' in map_grid room '{name}'!"
                assert wall not in forbidden_walls, f"CRITICAL: Forbidden wall tile '{wall}' in map_grid room '{name}'!"

            conn.close()
            print("\n=== UI DATABASE GENERATION CONFIRMED: OK ===")
            print("Verification passed! Modern tiles correctly used, traditional Panjiayuan tiles are completely absent.")
            print(f"\nStep 1 complete! Draft ID: {draft_id} is successfully verified.")
            print("You can now safely proceed to the Art and QA pipeline.")

if __name__ == "__main__":
    main()
