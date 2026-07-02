import json
from pathlib import Path
from agora_ui.run_interaction_simulation.core import materialize_scenario
from agora_ui.vertex_json_client import VertexJsonClient
from agora_ui.package_db import pack_world_package
import shutil
from agora_ui.agent_factory import _vertex_initial_inventory_payloads, _catalog_by_id

package_root = Path("/home/yz_wang/yz_main/agora_2.0/output/package_exports/3bb232f739244202")
materialized = package_root / "materialized"
world_config = json.loads((materialized / "run_inputs" / "world_config.json").read_text())

print("Catalog length:", len(_catalog_by_id(world_config)))
print("Allowed item IDs length:", len(world_config.get("inventory_generation", {}).get("allowed_item_ids", [])))

main_chars = world_config.get("main_characters", [])
for mc in main_chars:
    if "public_state" not in mc:
        mc["public_state"] = {}
    mc["public_state"]["api_profile_stage"] = "main_character_generation"
    if "coordinates" not in mc:
        mc["coordinates"] = {"x": 0, "y": 0, "room_id": mc.get("home_room_id", "world")}
    mc.pop("enabled", None)
    mc.pop("role_id", None)
    mc.pop("archetype", None)
    mc.pop("home_room_id", None)
    mc.pop("currency_quantity", None)
    mc.pop("always_activate", None)

client = VertexJsonClient(world_config)
print("Calling Vertex API...")
try:
    enriched_chars = _vertex_initial_inventory_payloads(
        client=client,
        config=world_config,
        payloads=main_chars[:1]
    )
    print("Result inventory:", enriched_chars[0].get("inventory"))
except Exception as e:
    print("Exception:", e)
