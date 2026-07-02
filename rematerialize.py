import json
import os
import shutil
from agora_ui.run_interaction_simulation import materialize_scenario

from pathlib import Path

base_dir = "output/world_creator_drafts/creator_20260608_051817_8e89884e/revisions/r001"
config_path = os.path.join(base_dir, "world_config.json")
scenario_dir = Path(os.path.join(base_dir, "scenario"))

# Clean existing scenario
if os.path.exists(scenario_dir):
    shutil.rmtree(scenario_dir)

# Load config
with open(config_path, "r") as f:
    config = json.load(f)

# Re-materialize
materialize_scenario(config, scenario_dir)

print(f"Scenario re-materialized with {len(os.listdir(os.path.join(scenario_dir, 'Agents')))} agents!")
