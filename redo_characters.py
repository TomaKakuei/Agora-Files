import os
import sys
import json
from pathlib import Path

# Add project root to PYTHONPATH
sys.path.insert(0, "/home/yz_wang/yz_main/agora_2.0")

from agora_ui.vertex_json_client import VertexJsonClient
from agora_ui.world_builder.core import _world_creator_provider
from agora_ui.world_builder.nodes.roles import generate_roles_spec
from agora_ui.world_pipeline import build_world_pipeline
from agora_ui.world_builder.builder import _build_world_config_from_spec
from agora_ui.run_interaction_simulation import materialize_scenario
from agora_ui.package_db import pack_world_package
import shutil

draft_id = "creator_20260608_051817_8e89884e"
package_root = Path("/home/yz_wang/yz_main/agora_2.0").resolve()
revision_id = "r001"
revision_path = package_root / "output" / "world_creator_drafts" / draft_id / "revisions" / revision_id

print(f"Redoing characters for {draft_id} {revision_id}...")

with open(revision_path / "builder_spec.json", "r") as f:
    builder_spec = json.load(f)

rooms = builder_spec.get("rooms", [])
items = builder_spec.get("item_catalog", [])

provider = _world_creator_provider()
print("Regenerating roles (This may take a minute)...")
roles, main_chars = generate_roles_spec(
    provider, builder_spec, rooms, items, 
    agent_count_target=25, min_merchant_items=8
)

builder_spec["role_groups"] = roles
builder_spec["main_characters"] = main_chars

with open(revision_path / "builder_spec.json", "w") as f:
    json.dump(builder_spec, f, indent=2)

print("Rebuilding pipeline artifacts...")
request = {"focus": builder_spec.get("simulation_objective", "")}
pipeline_artifacts = build_world_pipeline(builder_spec, request)

with open(revision_path / "agents_spec.json", "w") as f:
    json.dump(pipeline_artifacts["agents_spec"], f, indent=2)

from agora_ui.world_builder.validation import _validation_workspace
print("Rebuilding config and DB...")
config = _build_world_config_from_spec(package_root, builder_spec, request, pipeline_artifacts=pipeline_artifacts)

# Skip redundant secondary API generation to preserve our custom inventory and save Vertex tokens
config["inventory_generation"] = {"enabled": False}

db_path, package_validation, payloads = _validation_workspace(package_root, config, finalize_agents=True, provider=provider)

with open(revision_path / "world_config.json", "w") as f:
    json.dump(config, f, indent=2, ensure_ascii=False)

shutil.copy2(db_path, revision_path / "world_package.db")
db_path.unlink(missing_ok=True)
print("Materializing scenario...")
materialize_scenario(config, revision_path / "scenario", agent_payloads=payloads)

# Queue art pipeline
from agora_ui.world_builder.art import run_art_pipeline
print("Running art pipeline...")
art_status = run_art_pipeline(package_root=package_root, draft_id=draft_id, revision_id=revision_id)
print(f"Art pipeline finished: {art_status['status']}")
print("DONE.")
