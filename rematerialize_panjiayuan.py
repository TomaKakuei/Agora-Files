import json
import os
import shutil
from pathlib import Path
from agora_ui.run_interaction_simulation import materialize_scenario

base_dir = "output/world_creator_drafts/creator_20260605_200912_9f9769cf/revisions/r001"
config_path = os.path.join(base_dir, "world_config.json")
scenario_dir = Path(os.path.join(base_dir, "scenario"))

if os.path.exists(scenario_dir):
    shutil.rmtree(scenario_dir)

with open(config_path, "r") as f:
    config = json.load(f)

materialize_scenario(config, scenario_dir)
print(f"Scenario re-materialized with {len(os.listdir(os.path.join(scenario_dir, 'Agents')))} agents!")
