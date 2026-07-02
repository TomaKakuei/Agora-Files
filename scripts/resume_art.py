import time
import sys
import requests

def main():
    base_url = "http://localhost:8125/api"
    draft_id = "creator_20260605_200912_9f9769cf"
    
    print(f"Resuming Art Pipeline for draft {draft_id}...")
    
    # 1. Start Art Pipeline
    print(f"POST /api/world-builder/drafts/{draft_id}/art")
    try:
        resp = requests.post(f"{base_url}/world-builder/drafts/{draft_id}/art", timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print("Failed to start art pipeline:", e)
        if 'resp' in locals():
            print(resp.text)
        sys.exit(1)
        
    # 2. Poll Art Status
    print("Polling art status...")
    while True:
        time.sleep(10)
        try:
            resp = requests.get(f"{base_url}/world-builder/drafts/{draft_id}/art/status", timeout=10)
            resp.raise_for_status()
            art_status = resp.json().get("art", {}).get("status", "")
            print(f"Art Status: {art_status}")
            if art_status not in ["art_queued", "art_running", "qa_failed_retrying"]:
                print(f"Art pipeline finished with status: {art_status}")
                if art_status != "publish_ready":
                    print("Art pipeline did not succeed.")
                    sys.exit(1)
                break
        except Exception as e:
            print("Error polling art status:", e)
            
    # 3. Publish
    print(f"POST /api/world-builder/drafts/{draft_id}/publish")
    try:
        resp = requests.post(f"{base_url}/world-builder/drafts/{draft_id}/publish", timeout=60)
        resp.raise_for_status()
        publish_data = resp.json()
        print("Publish successful!")
        print("Access Code:", publish_data.get("publish", {}).get("access_code"))
    except Exception as e:
        print("Failed to publish:", e)
        if 'resp' in locals():
            print(resp.text)
        sys.exit(1)

if __name__ == "__main__":
    main()
