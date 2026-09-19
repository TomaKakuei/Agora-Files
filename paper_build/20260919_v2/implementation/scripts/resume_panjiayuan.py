import time
import sys
import requests

def main():
    base_url = "http://localhost:8125/api"
    draft_id = "creator_20260603_072739_9bedb5af"
    print(f"Resuming Draft ID: {draft_id}")
    
    # 2. Start Art Pipeline
    print(f"POST /api/world-builder/drafts/{draft_id}/art")
    try:
        resp = requests.post(f"{base_url}/world-builder/drafts/{draft_id}/art", timeout=30)
        # Note: 409 means art is already running
        if resp.status_code != 409:
            resp.raise_for_status()
        else:
            print("Art pipeline already running")
    except Exception as e:
        print("Failed to start art pipeline:", e)
        if 'resp' in locals():
            print(resp.text)
        
    # 3. Poll Art Status
    print("Polling art status...")
    while True:
        try:
            resp = requests.get(f"{base_url}/world-builder/drafts/{draft_id}/art/status", timeout=10)
            resp.raise_for_status()
            art_status = resp.json().get("art", {}).get("status", "")
            print(f"Art Status: {art_status}")
            if art_status not in ["art_queued", "art_running", "qa_failed_retrying"]:
                print(f"Art pipeline finished with status: {art_status}")
                break
        except Exception as e:
            print("Error polling art status:", e)
        time.sleep(10)
            
    # 4. Publish
    print(f"POST /api/world-builder/drafts/{draft_id}/publish")
    try:
        resp = requests.post(f"{base_url}/world-builder/drafts/{draft_id}/publish", timeout=60)
        resp.raise_for_status()
        publish_data = resp.json()
        print("Publish successful!")
        print("Access Code:", publish_data.get("publish", {}).get("access_code"))
    except Exception as e:
        print("Failed to publish:", e)
        sys.exit(1)

if __name__ == "__main__":
    main()
