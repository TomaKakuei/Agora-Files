import os
import sys
import time
import json

from playwright.sync_api import sync_playwright

from _playwright_firefox import launch_headless_firefox_page

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/regression_step2_art.py <draft_id>")
        sys.exit(1)
        
    draft_id = sys.argv[1].strip()
    print(f"=== STARTING HEADLESS DANYANG GLASSES CITY STEP-BY-STEP REGRESSION (STEP 2: ART & PUBLISH) ===")
    print(f"Resuming Draft ID: {draft_id}")
    
    base_url = "http://127.0.0.1:8125"
    
    with sync_playwright() as p:
        print("\nLaunching Firefox browser in headless mode...")
        with launch_headless_firefox_page(p) as (_context, page):
            # Capture console logs and page errors
            page.on("console", lambda msg: print(f"[BROWSER CONSOLE] {msg.type}: {msg.text}"))
            page.on("pageerror", lambda err: print(f"[BROWSER ERROR] {err}"))

            print("Navigating to Agora Creator UI...")
            try:
                page.goto(f"{base_url}/creator/index.html", wait_until="domcontentloaded", timeout=15000)
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

            # Step-by-Step confirmation: Now start the art and QA pipeline
            print("\nProceeding to build Art...")
            page.click('#start-art')
            print("Art and QA pipeline queued via UI click. Polling status...")

            art_start_time = time.time()
            completed = False
            last_timeline_length = 0

            while time.time() - art_start_time < 2400: # 40 minutes max timeout
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
                page.wait_for_selector('#publish-access-code:not(:text("-"))', timeout=300000)
                access_code = page.locator('#publish-access-code').inner_text().strip()
                print(f"\n=== REGRESSION SUCCESS: PUBLISHED ACCESS CODE: {access_code} ===")
            except Exception as e:
                print(f"Publish timed out or failed to retrieve access code: {e}")
                sys.exit(1)

if __name__ == "__main__":
    main()
