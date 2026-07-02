import time
import sys
import requests

def main():
    base_url = "http://localhost:8125/api"
    print("Starting Panjiayuan generation via API...")
    
    # 1. Generate Draft
    payload = {
        "world_name": "Panjiayuan Market Run 22",
        "genre": "traditional chinese antique market",
        "player_count_target": 4,
        "agent_count_target": 25,
        "focus": "economy, haggling, and artifact trading",
        "seed": 42627,
        "brief": "A bustling Panjiayuan market (潘家园旧货市场) with agents. A dense antique market of stalls, appraisers, rumors, and provenance disputes. Traditional Chinese setting, trading antiques, jade, and bronze."
    }
    print("POST /api/world-builder/drafts")
    try:
        resp = requests.post(f"{base_url}/world-builder/drafts", json=payload, timeout=1800)
        resp.raise_for_status()
        draft = resp.json()
    except Exception as e:
        print("Draft generation failed:", e)
        if 'resp' in locals():
            print(resp.text)
        sys.exit(1)
        
    draft_id = draft.get("draft_id")
    print(f"Draft generated successfully! Draft ID: {draft_id}")
    
    # 2. Start Art Pipeline
    print(f"POST /api/world-builder/drafts/{draft_id}/art")
    try:
        resp = requests.post(f"{base_url}/world-builder/drafts/{draft_id}/art", timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print("Failed to start art pipeline:", e)
        sys.exit(1)
        
    # 3. Poll Art Status
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
                break
        except Exception as e:
            print("Error polling art status:", e)
            
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
