import sys
from pathlib import Path
sys.path.append('/home/yz_wang/yz_main/agora_2.0')
from asset_pipeline.build_live_ready_feed import _best_existing_ready_event, _read_json

repo_root = Path('/home/yz_wang/yz_main/agora_2.0')
config = _read_json(repo_root / "output/world_creator_drafts/creator_20260604_024800_9bd1bc13/revisions/r001/art_runtime/run_inputs/world_config.json")
processing = config["pixel_asset_pipeline"]["processing"]
sheet_layout = config["pixel_asset_pipeline"]["sheet_layout"]

event, report = _best_existing_ready_event(
    repo_root=repo_root,
    agent_id="panjiayuan_market_run_10_main_01",
    sheet_layout=sheet_layout,
    processing=processing,
    expected_world_id="panjiayuan_market_run_10",
    expected_world_revision="creator_20260604_024800_9bd1bc13_r001",
    allow_foreign_revision_fallback=False,
    preferred_revision="creator_20260604_024800_9bd1bc13_r001"
)
print("Event:", event is not None)
print("Report:", report)
