from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Any
from asset_pipeline.process_sprite import DEFAULT_ALIGNMENT_POLICY, DEFAULT_ANIMATION_STATES, AnimationState

DEFAULT_SHEET_LAYOUT = {
    "columns": 4,
    "rows": 4,
    "raw_frame_width": 128,
    "raw_frame_height": 128,
    "animation_states": DEFAULT_ANIMATION_STATES,
}

DEFAULT_PROCESSING = {
    "target_frame_width": 32,
    "target_frame_height": 32,
    "alpha_threshold": 8,
    "remove_near_white_background": True,
    "near_white_threshold": 246,
    "neutral_tolerance": 12,
    "qa_min_transparent_ratio": 0.20,
    "qa_atlas_min_transparent_ratio": 0.20,
    "qa_atlas_max_near_white_opaque_ratio": 0.90,
    "qa_atlas_max_edge_opaque_ratio": 0.90,
    "qa_component_min_largest_ratio": 0.20,
    "qa_component_major_min_ratio": 0.01,
    "qa_component_max_major_components": 10,
    "alignment_policy": DEFAULT_ALIGNMENT_POLICY,
}

def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

def _load_runtime_clients():
    package_root = Path(__file__).resolve().parent.parent
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    from agora_ui.run_interaction_simulation import VertexJsonClient
    return VertexJsonClient

def _normalize_vertex_model_name(model_name: str) -> str:
    text = str(model_name).strip()
    if text == "gemini-3.1-flash-lite-preview":
        return "gemini-3.1-flash-lite"
    return text

def _normalize_world_config_models(world_config: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(world_config))
    runtime = normalized.get("runtime")
    if isinstance(runtime, dict) and runtime.get("vertex_model"):
        runtime["vertex_model"] = _normalize_vertex_model_name(runtime["vertex_model"])
    vertex_api = normalized.get("vertex_api")
    if isinstance(vertex_api, dict):
        if vertex_api.get("model"):
            vertex_api["model"] = _normalize_vertex_model_name(vertex_api["model"])
        if vertex_api.get("fallback_model"):
            vertex_api["fallback_model"] = _normalize_vertex_model_name(vertex_api["fallback_model"])
        stages = vertex_api.get("stages")
        if isinstance(stages, dict):
            for stage_config in stages.values():
                if isinstance(stage_config, dict) and stage_config.get("model"):
                    stage_config["model"] = _normalize_vertex_model_name(stage_config["model"])
    image_generation = normalized.get("image_generation")
    if isinstance(image_generation, dict) and image_generation.get("model"):
        image_generation["model"] = _normalize_vertex_model_name(image_generation["model"])
    return normalized

def _normalize_animation_states(animation_states: list[AnimationState] | list[dict[str, Any]] | None) -> list[AnimationState]:
    source = animation_states or DEFAULT_ANIMATION_STATES
    normalized: list[AnimationState] = []
    for entry in source:
        if isinstance(entry, AnimationState):
            normalized.append(entry)
        else:
            normalized.append(AnimationState(**entry))
    return normalized

def _merged_sheet_layout(
    sheet_layout: dict[str, Any] | None,
    animation_states: list[AnimationState],
) -> dict[str, Any]:
    raw = dict(DEFAULT_SHEET_LAYOUT)
    if isinstance(sheet_layout, dict):
        raw.update(sheet_layout)
    raw["animation_states"] = [state.__dict__ for state in animation_states]
    raw["columns"] = int(raw.get("columns") or max((state.start_col + state.frame_count for state in animation_states), default=4))
    raw["rows"] = int(raw.get("rows") or max((state.row + 1 for state in animation_states), default=4))
    raw["raw_frame_width"] = int(raw.get("raw_frame_width", 128))
    raw["raw_frame_height"] = int(raw.get("raw_frame_height", 128))
    return raw

def _merged_processing(processing: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(DEFAULT_PROCESSING)
    if isinstance(processing, dict):
        raw.update(processing)
    policy = dict(DEFAULT_ALIGNMENT_POLICY)
    if isinstance(raw.get("alignment_policy"), dict):
        policy.update(raw["alignment_policy"])
    raw["alignment_policy"] = policy
    raw["target_frame_width"] = int(raw.get("target_frame_width", 32))
    raw["target_frame_height"] = int(raw.get("target_frame_height", 32))
    raw["alpha_threshold"] = int(raw.get("alpha_threshold", 8))
    raw["near_white_threshold"] = int(raw.get("near_white_threshold", 246))
    raw["neutral_tolerance"] = int(raw.get("neutral_tolerance", 12))
    raw["qa_min_transparent_ratio"] = float(raw.get("qa_min_transparent_ratio", 0.20))
    raw["qa_atlas_min_transparent_ratio"] = float(raw.get("qa_atlas_min_transparent_ratio", 0.20))
    raw["qa_atlas_max_near_white_opaque_ratio"] = float(raw.get("qa_atlas_max_near_white_opaque_ratio", 0.90))
    raw["qa_atlas_max_edge_opaque_ratio"] = float(raw.get("qa_atlas_max_edge_opaque_ratio", 0.90))
    raw["qa_component_min_largest_ratio"] = float(raw.get("qa_component_min_largest_ratio", 0.20))
    raw["qa_component_major_min_ratio"] = float(raw.get("qa_component_major_min_ratio", 0.01))
    raw["qa_component_max_major_components"] = int(raw.get("qa_component_max_major_components", 10))
    raw["remove_near_white_background"] = bool(raw.get("remove_near_white_background", True))
    return raw

__all__ = [
    "DEFAULT_SHEET_LAYOUT",
    "DEFAULT_PROCESSING",
    "_read_json",
    "_write_json",
    "_load_runtime_clients",
    "_normalize_vertex_model_name",
    "_normalize_world_config_models",
    "_normalize_animation_states",
    "_merged_sheet_layout",
    "_merged_processing",
]
