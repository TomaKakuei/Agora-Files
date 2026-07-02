import re

content = open("agora_ui/run_world_rule_debug.py").read()

compiler_funcs = ["_room_sort_key", "_load_world", "_load_world_agents", "_load_world_control", "_build_rooms", "_resolve_initial_room", "_compile_world"]
pathing_funcs = ["_position_in_shape", "_manhattan_distance", "_build_room_adjacency", "_expand_neighbors", "_enumerate_reachable_targets"]
decision_funcs = ["_heuristic_decision", "_build_decision_prompt", "_flex_decision", "_plan_decision_for_agent"]
simulation_funcs = ["_ordered_active_agents", "_build_snapshot_payload", "_trace_from_idle_agent", "_idle_status_from_decision", "_trace_from_decision_result", "_trace_from_unmoved_decision", "_trace_from_move_decision", "_build_initial_runtime_state", "_resolved_decision_concurrency", "_select_single_round_agent", "_plan_single_round_decision", "_settle_single_round", "_plan_multi_round_decisions", "_settle_multi_round", "_simulate_world"]
main_funcs = ["_build_arg_parser", "_main_async", "main"]

def extract_funcs(names):
    blocks = []
    for name in names:
        pattern = r"(^async def " + name + r"\(|^def " + name + r"\().*?(?=^async def |^def |^@dataclass|^if __name__ ==)"
        match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
        if match:
            blocks.append(match.group(0).strip())
        else:
            print(f"Warning: could not find {name}")
    return "\n\n\n".join(blocks)

compiler_code = extract_funcs(compiler_funcs)
pathing_code = extract_funcs(pathing_funcs)
decision_code = extract_funcs(decision_funcs)
simulation_code = extract_funcs(simulation_funcs)
main_code = extract_funcs(main_funcs)

# Core is everything before the first def _room_sort_key
core_pattern = r"^(.*?)(?=\ndef _room_sort_key\()"
core_match = re.search(core_pattern, content, re.MULTILINE | re.DOTALL)
core_code = core_match.group(0).strip() if core_match else ""

imports = """from __future__ import annotations

import argparse
import asyncio
import json
import random
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from ..flex_client import AsyncFlexClient
from ..foundation_schemas import (
    CompiledRoomSpec,
    CompiledWorldAgent,
    CompiledWorldSpec,
    GridPosition,
    GridShape,
    MovementPolicy,
    RoomSpec,
    WorldAgentSpec,
    WorldAgentsSpec,
    WorldControlSpec,
    WorldRuleDebugManifest,
    WorldRuleTraceRecord,
    WorldSpec,
)
from ..jsonc_utils import dump_json, load_jsonc_path
"""

core_code = core_code.replace("from .flex_client", "from ..flex_client")
core_code = core_code.replace("from .foundation_schemas", "from ..foundation_schemas")
core_code = core_code.replace("from .jsonc_utils", "from ..jsonc_utils")
core_code = core_code.replace("SCRIPT_DIR = Path(__file__).resolve().parent.parent", "SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent")

def write_file(name, imports, code):
    with open(name, "w") as f:
        f.write(imports + "\n\n" + code + "\n")

write_file("agora_ui/world_rule_debug/core.py", "", core_code)
write_file("agora_ui/world_rule_debug/compiler.py", imports + "\nfrom .core import *\nfrom .pathing import _coord_key", compiler_code)
write_file("agora_ui/world_rule_debug/pathing.py", imports + "\nfrom .core import *", pathing_code)
write_file("agora_ui/world_rule_debug/decision.py", imports + "\nfrom .core import *\nfrom .pathing import _enumerate_reachable_targets", decision_code)
write_file("agora_ui/world_rule_debug/simulation.py", imports + "\nfrom .core import *\nfrom .pathing import _build_room_adjacency, _coord_key\nfrom .decision import _plan_decision_for_agent", simulation_code)

main_imports = imports + "\nfrom .world_rule_debug.core import *\nfrom .world_rule_debug.compiler import *\nfrom .world_rule_debug.simulation import _simulate_world\n"
if_main = "\nif __name__ == \"__main__\":\n    main()\n"
write_file("agora_ui/run_world_rule_debug_new.py", main_imports, main_code + "\n" + if_main)

