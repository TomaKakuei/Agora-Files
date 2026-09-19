import os
import sys
from pathlib import Path

# Need to make sure the root is in PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from agora_ui import world_builder

def main():
    package_root = Path(__file__).resolve().parent.parent
    payload = {
        "world_name": "Panjiayuan V3",
        "genre": "traditional chinese antique market",
        "player_count_target": 4,
        "agent_count_target": 25,
        "focus": "economy, haggling, and artifact trading",
        "seed": 42,
        "brief": "A bustling Panjiayuan market with agents. Massive open spaces to avoid crowding. Traditional Chinese setting, trading antiques, jade, and bronze."
    }
    
    print("Creating draft...")
    draft = world_builder.create_draft(package_root, payload)
    draft_id = draft.get("draft_id")
    print(f"Draft ID: {draft_id}")
    
    # Normally create_draft is async. Let's wait for it.
    import time
    while True:
        status = world_builder.get_draft_response(package_root, draft_id).get("status")
        print(f"Status: {status}")
        if status == "draft_ready":
            break
        elif status == "draft_failed":
            print("Draft failed!")
            # Read logs
            log_dir = package_root / "world_creator_drafts" / draft_id
            print(f"Checking logs in {log_dir}")
            sys.exit(1)
        time.sleep(10)
        
    print("Launching art worker...")
    world_builder.launch_art_worker(package_root, draft_id)
    
    while True:
        art_status = world_builder.art_status(package_root, draft_id).get("status")
        print(f"Art Status: {art_status}")
        if art_status not in ["art_queued", "art_running", "qa_failed_retrying"]:
            break
        time.sleep(10)
        
    print("Done!")

if __name__ == "__main__":
    main()
