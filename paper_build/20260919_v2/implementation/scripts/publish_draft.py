import sys
from pathlib import Path
from agora_ui import world_builder
from macro_ui import serve_macro_ui

def main():
    draft_id = "creator_20260603_195958_9a240c82"
    print(f"Publishing {draft_id}...")
    try:
        result = world_builder.publish_draft(serve_macro_ui.PACKAGE_ROOT, draft_id)
        print("Publish Result:", result)
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
