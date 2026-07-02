import os
import sys
import time
import sqlite3
import json
import glob
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

from _playwright_firefox import launch_headless_firefox_page

def main():
    print("=== STARTING HEADLESS DANYANG GLASSES CITY RESILIENT PIPELINE ===")
    
    draft_id = "creator_20260601_090130_58194b92"
    base_url = "http://127.0.0.1:8125"
    
    print(f"Targeting active background draft ID: {draft_id}")
    print("Polling server API to monitor dynamic character profile generation...")
    
    # 1. Poll the FastAPI server directly until the background generation completes
    start_time = time.time()
    generation_completed = False
    
    while True:
        try:
            resp = requests.get(f"{base_url}/api/world-builder/drafts/{draft_id}", timeout=10)
            if resp.status_code == 200:
                draft = resp.json()
                status = draft.get("status", "")
                world_name = draft.get("world_name", "")
                
                # Check how many agent profiles have been written on disk so far
                profile_count = 0
                try:
                    profile_search = glob.glob(f"/home/yz_wang/yz_main/Agora_UI_Run/output/world_creator_drafts/{draft_id}/revisions/r001/scenario/Agents/*.json")
                    profile_count = len(profile_search)
                except Exception:
                    pass
                
                print(f"Draft Status: {status:20} | World: {world_name} | Generated Agents: {profile_count}/65 | Elapsed: {int(time.time() - start_time)}s")
                
                if status == "draft_ready":
                    print("\n=== DRAFT DATABASE GENERATION SUCCESSFULLY COMPLETED ON SERVER ===")
                    generation_completed = True
                    break
                elif status == "draft_failed":
                    error_msg = draft.get("current_revision_data", {}).get("error", "Unknown builder compile error")
                    print(f"\nCRITICAL: Draft generation failed on the server: {error_msg}")
                    sys.exit(1)
            else:
                print(f"Server returned status code: {resp.status_code}")
        except Exception as e:
            print(f"Waiting for server connection... {e}")
            
        time.sleep(20)
        
    if not generation_completed:
        print("Draft compilation timed out on the server!")
        sys.exit(1)
        
    # 2. Start browser automation to verify the UI database and trigger art
    with sync_playwright() as p:
        print("\nLaunching Firefox browser in headless mode...")
        with launch_headless_firefox_page(p) as (_context, page):
            # Capture console logs, page errors, and requests
            page.on("console", lambda msg: print(f"[BROWSER CONSOLE] {msg.type}: {msg.text}"))
            page.on("pageerror", lambda err: print(f"[BROWSER ERROR] {err}"))
            page.on("request", lambda req: print(f"[BROWSER REQ] {req.method} {req.url}"))
            page.on("response", lambda resp: print(f"[BROWSER RESP] {resp.status} {resp.url}"))

            print("Navigating to Agora Creator UI...")
            try:
                page.goto(f"{base_url}/creator/index.html", timeout=15000, wait_until="domcontentloaded")
                print("Successfully loaded Creator UI.")
            except Exception as e:
                print(f"Failed to load UI. Is the server running? Error: {e}")
                sys.exit(1)

            print(f"Resuming Draft ID: {draft_id} via the UI form...")
            page.fill('#resume-identifier', draft_id)
            page.click('#resume-draft')

            print("Waiting for the UI to transition and display the Draft Review Panel...")
            try:
                page.wait_for_selector('#draft-review:not(.hidden)', timeout=30000)
                print("Draft Review Panel is now active on the UI.")
            except Exception as e:
                print(f"Failed to resume draft on the UI: {e}")
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

            # Step-by-Step confirmation: Now start the art and QA pipeline
            print("\nProceeding to build Art...")
            page.click('#start-art')
            print("Art and QA pipeline queued via UI click. Polling status...")

            art_start_time = time.time()
            completed = False
            last_timeline_length = 0

            while time.time() - art_start_time < 900: # 15 minutes max timeout
                time.sleep(10)

                try:
                    page.click('#refresh-art')
                except Exception:
                    pass

                art_status_text = page.locator('#art-status-box').inner_text()

                try:
                    art_payload = json.loads(art_status_text)
                    status = art_payload.get("status", "")
                    logs = art_payload.get("logs", [])

                    if len(logs) > last_timeline_length:
                        for i in range(last_timeline_length, len(logs)):
                            step = logs[i]
                            cmd = " ".join(step.get("command", []))
                            code = step.get("returncode")
                            print(f"Art Step {i+1}: returncode={code} | Command: {cmd}")
                        last_timeline_length = len(logs)

                    print(f"Current Art Status: {status} (elapsed: {int(time.time() - art_start_time)}s)")

                    if status in ["art_ready", "publish_ready", "published"]:
                        print("Art and QA pipeline completed successfully!")
                        completed = True
                        break
                    elif status == "art_failed":
                        print("Art and QA pipeline failed!")
                        print(art_status_text)
                        sys.exit(1)
                except Exception as parse_err:
                    print(f"Art Status Box Text: {art_status_text[:200]}")

            if not completed:
                print("Art and QA pipeline timed out after 15 minutes!")
                sys.exit(1)
            
        # Step-by-Step confirmation: Publish the world
        print("\nPublishing World...")
        page.click('#publish-world')
        
        print("Waiting for access code...")
        try:
            page.wait_for_selector('#publish-access-code:not(:text("-"))', timeout=60000)
            access_code = page.locator('#publish-access-code').inner_text().strip()
            print(f"\n=== REGRESSION SUCCESS: PUBLISHED ACCESS CODE: {access_code} ===")
        except Exception as e:
            print(f"Publish timed out or failed to retrieve access code: {e}")
            sys.exit(1)
            
        browser.close()

if __name__ == "__main__":
    main()
