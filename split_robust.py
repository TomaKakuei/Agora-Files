import re
import ast
import json

def split_file(input_file):
    with open(input_file, "r") as f:
        source = f.read()
    
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

    def get_source_segment(node, source_lines):
        # Extracts exact source lines for a node (preserves comments and docstrings within the node)
        start = node.lineno - 1
        # Include decorators
        if hasattr(node, 'decorator_list') and node.decorator_list:
            start = node.decorator_list[0].lineno - 1
        end = node.end_lineno
        return "\n".join(source_lines[start:end])

    source_lines = source.splitlines()
    
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

    def extract_code(nodes):
        return "\n\n".join(get_source_segment(n, source_lines) for n in nodes)

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
    
    # core
    core_code = extract_code(core_nodes)
    core_code = core_code.replace("from .flex_client", "from ..flex_client")
    core_code = core_code.replace("from .foundation_schemas", "from ..foundation_schemas")
    core_code = core_code.replace("from .jsonc_utils", "from ..jsonc_utils")
    core_code = core_code.replace("SCRIPT_DIR = Path(__file__).resolve().parent.parent", "SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent")
    
    # Add __all__ to core
    core_exports = [
        "SCRIPT_DIR", "DEFAULT_TEMPLATE_DIR", "DEFAULT_WORLD_TEMPLATE",
        "DEFAULT_WORLD_AGENTS", "DEFAULT_WORLD_CONTROL", "DEFAULT_OUTPUT_ROOT",
        "CoordKey", "RoomAdjacency", "RuntimeRooms", "RuntimePositions",
        "ReachableTarget", "MovementDecision", "_resolve_path", "_now_run_id",
        "_now_iso", "_coord_key", "_time_to_minutes", "_minutes_to_time"
    ]
    core_all = f"\n__all__ = {json.dumps(core_exports)}\n"
    
    with open("agora_ui/world_rule_debug/core.py", "w") as f:
        f.write(core_code + "\n" + core_all)
        
    def write_file(name, imports, code):
        with open(name, "w") as f:
            f.write(imports + "\n\n" + code + "\n")

    compiler_code = extract_code(compiler_nodes)
    pathing_code = extract_code(pathing_nodes)
    decision_code = extract_code(decision_nodes)
    simulation_code = extract_code(simulation_nodes)
    main_code = extract_code(main_nodes)

    write_file("agora_ui/world_rule_debug/compiler.py", imports + "\nfrom .core import *", compiler_code)
    write_file("agora_ui/world_rule_debug/pathing.py", imports + "\nfrom .core import *", pathing_code)
    write_file("agora_ui/world_rule_debug/decision.py", imports + "\nfrom .core import *\nfrom .pathing import _enumerate_reachable_targets", decision_code)
    write_file("agora_ui/world_rule_debug/simulation.py", imports + "\nfrom .core import *\nfrom .pathing import _build_room_adjacency\nfrom .decision import _plan_decision_for_agent", simulation_code)

    main_imports = imports + "\nfrom .world_rule_debug.core import *\nfrom .world_rule_debug.compiler import *\nfrom .world_rule_debug.simulation import _simulate_world\n"
    write_file("agora_ui/run_world_rule_debug.py", main_imports, main_code)
    
if __name__ == "__main__":
    split_file("/home/yz_wang/yz_main/Agora_UI_Run/agora_ui/run_world_rule_debug.py")
