import json
from pathlib import Path
from agora_ui.run_interaction_simulation.core import materialize_scenario
from agora_ui.vertex_json_client import VertexJsonClient
from agora_ui.package_db import pack_world_package
import shutil
from agora_ui.agent_factory import _vertex_initial_inventory_payloads

package_root = Path("/home/yz_wang/yz_main/agora_2.0/output/package_exports/3bb232f739244202")
materialized = package_root / "materialized"
world_config = json.loads((materialized / "run_inputs" / "world_config.json").read_text())

main_chars = world_config.get("main_characters", [])
for mc in main_chars:
    if "public_state" not in mc:
        mc["public_state"] = {}
    mc["public_state"]["api_profile_stage"] = "main_character_generation"
    # Provide dummy coordinates to pass strict runtime validation
    if "coordinates" not in mc:
        mc["coordinates"] = {"x": 0, "y": 0, "z": 0}
    elif "room_id" in mc["coordinates"]:
        del mc["coordinates"]["room_id"]
        mc["coordinates"]["z"] = 0
        
    # Remove extra fields that fail validation
    mc.pop("enabled", None)
    mc.pop("role_id", None)
    mc.pop("archetype", None)
    mc.pop("home_room_id", None)
    mc.pop("currency_quantity", None)
    mc.pop("always_activate", None)
    mc.pop("agent_number", None)

client = VertexJsonClient(world_config)
enriched_chars = _vertex_initial_inventory_payloads(
    client=client,
    config=world_config,
    payloads=main_chars
)
world_config["main_characters"] = enriched_chars
(materialized / "run_inputs" / "world_config.json").write_text(json.dumps(world_config, indent=2))
(materialized / "world_definition.json").write_text(json.dumps(world_config, indent=2))

agents_dir = materialized / "run_inputs" / "scenario" / "Agents"
if agents_dir.exists():
    shutil.rmtree(agents_dir)

materialize_scenario(
    config=world_config,
    scenario_dir=materialized / "run_inputs" / "scenario"
)
pack_world_package(
    package_dir=materialized,
    db_path=package_root / "live_state.db"
)
print("Repaired package 3bb232f739244202")
