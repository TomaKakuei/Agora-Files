import os
import sys
import time
import sqlite3
import json
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

from _playwright_firefox import launch_headless_firefox_page

def main():
    print("=== RESUMING AND VERIFYING GENERATED DANYANG GLASSES CITY DRAFT (STEP 1) ===")
    
    draft_id = "creator_20260601_182143_417dce1f"
    base_url = "http://127.0.0.1:8125"
    
    # 1. Poll the FastAPI status first to wait for status to become draft_ready
    print(f"Waiting for Draft ID {draft_id} to finish LLM generation on the server...")
    start_time = time.time()
    
    while True:
        try:
            resp = requests.get(f"{base_url}/api/world-builder/drafts/{draft_id}", timeout=10)
            if resp.status_code == 200:
                draft = resp.json()
                status = draft.get("status", "")
                world_name = draft.get("world_name", "")
                print(f"Status: {status} | World Name: {world_name} | Elapsed: {int(time.time() - start_time)}s")
                
                if status == "draft_ready":
                    print("\n=== SERVER HAS FINISHED DRAFT COMPILATION ===")
                    break
                elif status == "draft_failed":
                    error_msg = draft.get("current_revision_data", {}).get("error", "Unknown build error")
                    print(f"Critical: Draft generation failed: {error_msg}")
                    sys.exit(1)
            else:
                # 404 is expected while the revision is not created yet
                print(f"Draft is still generating... (Server returned {resp.status_code})")
        except Exception as e:
            print(f"Waiting for server... {e}")
            
        time.sleep(15)
        if time.time() - start_time > 1200: # 20 minutes timeout
            print("Timeout waiting for draft generation on the server!")
            sys.exit(1)
            
    # 2. Launch headless browser to resume the draft in the UI to satisfy "你不许绕过UI"
    with sync_playwright() as p:
        print("\nLaunching Firefox browser in headless mode...")
        with launch_headless_firefox_page(p) as (_context, page):
            page.on("console", lambda msg: print(f"[BROWSER CONSOLE] {msg.type}: {msg.text}"))
            page.on("pageerror", lambda err: print(f"[BROWSER ERROR] {err}"))

            print("Navigating to Agora Creator UI...")
            try:
                page.goto(f"{base_url}/creator/index.html", wait_until="domcontentloaded", timeout=15000)
            except Exception as e:
                print(f"Failed to load UI: {e}")
                sys.exit(1)

            print(f"Resuming Draft ID: {draft_id} on the UI...")
            page.fill('#resume-identifier', draft_id)
            page.click('#resume-draft')

            print("Waiting for Draft Review Panel to become active...")
            try:
                page.wait_for_selector('#draft-review:not(.hidden)', timeout=30000)
                print("Successfully loaded Draft Review Panel on the UI.")
            except Exception as e:
                print(f"Failed to load Draft Review Panel: {e}")
                sys.exit(1)

            # Verify checklist and status on the UI
            status_pill_text = page.locator('#draft-status-pill').inner_text().strip()
            print(f"UI Status Pill Text: {status_pill_text}")

            materialize_row = page.locator('#validation-checklist .checklist-row').first
            materialize_class = materialize_row.get_attribute('class')
            print(f"UI Scenario Materialization Row class: {materialize_class}")
            if "ok" not in materialize_class:
                print("Scenario materialization failed in the validation checklist!")
                sys.exit(1)

            # 3. Direct verification of the SQLite DB on disk
            package_root = str(Path(__file__).resolve().parent.parent)
            db_path = f"{package_root}/output/world_creator_drafts/{draft_id}/revisions/r001/world_package.db"
            print(f"\nVerifying SQLite DB on disk: {db_path}")

            if not os.path.exists(db_path):
                print("Error: world_package.db not found on disk!")
                sys.exit(1)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            cursor.execute("SELECT content FROM files WHERE path = 'run_inputs/world_config.json'")
            row = cursor.fetchone()
            if not row:
                print("Error: world_config.json not found in files table!")
                conn.close()
                sys.exit(1)

            config = json.loads(row[0].decode('utf-8'))

            # Verify Boutique Logic Constraints
            agent_count = config.get("runtime", {}).get("agent_count")
            main_chars = config.get("main_characters", [])
            role_groups = config.get("agent_generation", {}).get("role_groups", [])
            print(f"\n--- Verified Boutique Agent Counts ---")
            print(f"Total compiled agents in config: {agent_count}")
            print(f"Main characters count: {len(main_chars)}")
            print(f"Role groups count: {len(role_groups)}")

            assert len(main_chars) == 25, f"CRITICAL: Expected 25 main characters, found {len(main_chars)}!"
            assert len(role_groups) == 0, f"CRITICAL: Expected 0 standard role groups, found {len(role_groups)}!"
            assert agent_count == 25, f"CRITICAL: Expected 25 total agents, found {agent_count}!"

            rooms = config.get("scenario_meta", {}).get("rooms", [])

            print("\n--- Verified Room Tiles in world_config.json ---")
            forbidden_floors = ["jade_tile", "bamboo_planks"]
            forbidden_walls = ["red_pillar_wall", "bamboo_wall"]

            for r in rooms:
                name = r.get("name")
                visual = r.get("visual", {})
                floor = visual.get("floor_tile")
                wall = visual.get("wall_tile")
                print(f"Room: {name:25} | Floor Tile: {floor:15} | Wall Tile: {wall:20}")

                assert floor not in forbidden_floors, f"CRITICAL: Forbidden floor tile '{floor}' in room '{name}'!"
                assert wall not in forbidden_walls, f"CRITICAL: Forbidden wall tile '{wall}' in room '{name}'!"

            conn.close()
            print("\n=== UI DATABASE GENERATION CONFIRMED: 100% OK ===")
            print("Verification passed! EXACTLY 25 boutique agents compiled with zero regular roles.")
            print("Modern commercial tiles correctly used, traditional Panjiayuan tiles are completely absent.")
            print(f"\nStep 1 successfully completed. Verified Draft ID: {draft_id}")

if __name__ == "__main__":
    main()
