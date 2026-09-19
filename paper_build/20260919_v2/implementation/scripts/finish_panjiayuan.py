import requests
import time
import sys

DRAFT_ID = "creator_20260604_024800_9bd1bc13"
BASE_URL = "http://localhost:8125/api"

print("Waiting for draft generation to finish on server side...")
while True:
    try:
        resp = requests.get(f"{BASE_URL}/world-builder/drafts/{DRAFT_ID}")
        if resp.status_code == 200:
            data = resp.json()
            status = data.get("draft", {}).get("current_revision_data", {}).get("status")
            if status in ("draft_ready", "draft_failed"):
                print(f"Draft finished with status: {status}")
                if status == "draft_failed":
                    print("Error:", data.get("draft", {}).get("current_revision_data", {}).get("error"))
                    sys.exit(1)
                break
    except Exception as e:
        print(f"Error checking status: {e}")
    time.sleep(10)

print(f"Starting art pipeline for {DRAFT_ID}...")
resp = requests.post(f"{BASE_URL}/world-builder/drafts/{DRAFT_ID}/art")
resp.raise_for_status()

print("Polling art status...")
while True:
    time.sleep(10)
    st = requests.get(f"{BASE_URL}/world-builder/drafts/{DRAFT_ID}/art/status").json()
    status = st.get("status")
    print(f"Art Status: {status}")
    if status not in ("art_queued", "art_running"):
        print(f"Art pipeline finished with status: {status}")
        break

print("Publishing...")
resp = requests.post(f"{BASE_URL}/world-builder/drafts/{DRAFT_ID}/publish")
if resp.status_code == 200:
    print("Published successfully!")
    print(resp.json())
else:
    print(f"Failed to publish: {resp.text}")

