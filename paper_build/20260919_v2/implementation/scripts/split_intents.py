import re
from pathlib import Path

def extract_functions(source: str, function_names: list[str]) -> tuple[str, str]:
    lines = source.split("\n")
    extracted = []
    remaining = []
    in_target_func = False
    
    for line in lines:
        match = re.match(r'^(\s*)def\s+([a-zA-Z0-9_]+)\(', line)
        if match:
            indent = len(match.group(1))
            name = match.group(2)
            if name in function_names and indent == 0:
                in_target_func = True
                extracted.append(line)
                continue
            elif in_target_func and indent == 0:
                in_target_func = False

        if in_target_func:
            extracted.append(line)
        else:
            remaining.append(line)
            
    return "\n".join(extracted), "\n".join(remaining)

def main():
    base_dir = Path(__file__).resolve().parent.parent
    source_file = base_dir / "intents.py"
    source_code = source_file.read_text()
    
    # 1. Schemas
    schema_funcs = [
        "_normalize_shared_action_core", "_relationship_vector_payload", 
        "_extra_world_functions_config", "_recent_global_world_events", 
        "_store_extra_world_event", "_run_extra_world_functions", 
        "_bounded_relationship_delta", "_normalize_relationship_adjustments", 
        "_vertex_relationship_metadata", "_attach_relationship_metadata_once"
    ]
    schema_code, source_code = extract_functions(source_code, schema_funcs)
    
    # 2. Builders
    builder_funcs = [
        "_build_custom_intent", "_build_trade_intents", "_rooms_by_distance", 
        "_reachable_positions_from_config", "_build_move_intent", 
        "_build_image_intent", "_first_image_route", "_first_move_route", 
        "_route_lookup", "_fallback_request_for_quota"
    ]
    builder_code, source_code = extract_functions(source_code, builder_funcs)
    
    common_imports = "from __future__ import annotations\nimport json\nimport random\nimport re\nimport time\nimport traceback\nfrom collections import deque\nfrom typing import Any\nfrom ..adjudicator_schemas import AgentRuntimeProfileSpec, AgentStateBundleSpec, GridPosition\nfrom ..vertex_json_client import VertexJsonClient\nfrom .memory import _agent_state_from_profile, _read_text, _sanitize_for_prompt\n"
    
    (base_dir / "intent_schemas.py").write_text(common_imports + "\n" + schema_code)
    (base_dir / "intent_builders.py").write_text(common_imports + "from .intent_schemas import *\n\n" + builder_code)
    
    # Add imports to top of intents.py
    import_inject = (
        "from .intent_schemas import *\n"
        "from .intent_builders import *\n"
    )
    
    parts = source_code.split("\n\n\n", 1)
    if len(parts) == 2:
        new_source = parts[0] + "\n" + import_inject + "\n\n\n" + parts[1]
    else:
        new_source = import_inject + "\n" + source_code
        
    source_file.write_text(new_source)
    print("Extraction complete for intents.py!")

if __name__ == "__main__":
    main()
