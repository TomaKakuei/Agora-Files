import time
import sys
import requests

def main():
    base_url = "http://localhost:8125/api"
    draft_id = sys.argv[1]
    
    print(f"Polling draft status for {draft_id}...")
    while True:
        try:
            resp = requests.get(f"{base_url}/world-builder/drafts/{draft_id}", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                status = data.get("status")
                print(f"Draft Status: {status}")
                if status == "draft_ready":
                    print("Draft is ready!")
                    break
                elif status == "draft_failed":
                    print("Draft failed!")
                    sys.exit(1)
        except Exception as e:
            print("Error polling draft status:", e)
        time.sleep(10)
        
    # 2. Start Art Pipeline
    print(f"POST /api/world-builder/drafts/{draft_id}/art")
    try:
        resp = requests.post(f"{base_url}/world-builder/drafts/{draft_id}/art", timeout=30)
        if resp.status_code != 409:
            resp.raise_for_status()
    except Exception as e:
        print("Failed to start art pipeline:", e)
        sys.exit(1)
        
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
        
    print("Finished.")

if __name__ == "__main__":
    main()
