import requests
import time
import sys

DRAFT_ID = "creator_20260604_024800_9bd1bc13"
BASE_URL = "http://localhost:8125/api"

print("Polling art status...")
while True:
    try:
        st = requests.get(f"{BASE_URL}/world-builder/drafts/{DRAFT_ID}/art/status").json()
        status = st.get("art", {}).get("status")
        print(f"Art Status: {status}")
        if status not in ("art_queued", "art_running"):
            print(f"Art pipeline finished with status: {status}")
            break
    except Exception as e:
        print("Error checking art status:", e)
    time.sleep(5)

print("Publishing...")
resp = requests.post(f"{BASE_URL}/world-builder/drafts/{DRAFT_ID}/publish")
if resp.status_code == 200:
    print("Published successfully!")
    print(resp.json())
else:
    print(f"Failed to publish: {resp.text}")
