import ast

source = open("agora_ui/run_world_rule_debug.py").read()
tree = ast.parse(source)

core_nodes = []
compiler_nodes = []
pathing_nodes = []
decision_nodes = []
simulation_nodes = []
main_nodes = []

compiler_funcs = {"_room_sort_key", "_load_world", "_load_world_agents", "_load_world_control", "_build_rooms", "_resolve_initial_room", "_compile_world"}
pathing_funcs = {"_position_in_shape", "_manhattan_distance", "_build_room_adjacency", "_expand_neighbors", "_enumerate_reachable_targets"}
decision_funcs = {"_heuristic_decision", "_build_decision_prompt", "_flex_decision", "_plan_decision_for_agent"}
simulation_funcs = {"_ordered_active_agents", "_build_snapshot_payload", "_trace_from_idle_agent", "_idle_status_from_decision", "_trace_from_decision_result", "_trace_from_unmoved_decision", "_trace_from_move_decision", "_build_initial_runtime_state", "_resolved_decision_concurrency", "_select_single_round_agent", "_plan_single_round_decision", "_settle_single_round", "_plan_multi_round_decisions", "_settle_multi_round", "_simulate_world"}
main_funcs = {"_build_arg_parser", "_main_async", "main"}

for node in tree.body:
    if isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef, ast.Assign, ast.AnnAssign)):
        core_nodes.append(node)
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.name in compiler_funcs:
            compiler_nodes.append(node)
        elif node.name in pathing_funcs:
            pathing_nodes.append(node)
        elif node.name in decision_funcs:
            decision_nodes.append(node)
        elif node.name in simulation_funcs:
            simulation_nodes.append(node)
        elif node.name in main_funcs:
            main_nodes.append(node)
        else:
            core_nodes.append(node)
    else:
        main_nodes.append(node)

def unparse_nodes(nodes):
    return "\n\n".join(ast.unparse(n).strip() for n in nodes)

def write_file(name, imports, nodes):
    with open(name, "w") as f:
        f.write(imports + "\n\n" + unparse_nodes(nodes) + "\n")

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

core_source = unparse_nodes(core_nodes)
core_source = core_source.replace("from .flex_client", "from ..flex_client")
core_source = core_source.replace("from .foundation_schemas", "from ..foundation_schemas")
core_source = core_source.replace("from .jsonc_utils", "from ..jsonc_utils")
core_source = core_source.replace("SCRIPT_DIR = Path(__file__).resolve().parent.parent", "SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent")

with open("agora_ui/world_rule_debug/__init__.py", "w") as f:
    f.write("")

with open("agora_ui/world_rule_debug/core.py", "w") as f:
    f.write(core_source)

write_file("agora_ui/world_rule_debug/compiler.py", imports + "\nfrom .core import *\nfrom .pathing import _coord_key", compiler_nodes)
write_file("agora_ui/world_rule_debug/pathing.py", imports + "\nfrom .core import *", pathing_nodes)
write_file("agora_ui/world_rule_debug/decision.py", imports + "\nfrom .core import *\nfrom .pathing import _enumerate_reachable_targets", decision_nodes)
write_file("agora_ui/world_rule_debug/simulation.py", imports + "\nfrom .core import *\nfrom .pathing import _build_room_adjacency\nfrom .decision import _plan_decision_for_agent", simulation_nodes)
write_file("agora_ui/run_world_rule_debug_new.py", imports + "\nfrom .world_rule_debug.core import *\nfrom .world_rule_debug.compiler import *\nfrom .world_rule_debug.simulation import _simulate_world", main_nodes)

