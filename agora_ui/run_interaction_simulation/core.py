from __future__ import annotations
import argparse
import base64
import hashlib
import json
import math
import mimetypes
import os
import random
import shutil
import subprocess
import sys
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import asyncio
import copy
import traceback
from collections import Counter, deque
from datetime import datetime
from pathlib import Path
from typing import Any
from PIL import Image
from ..adjudicator_schemas import (
    AgentIntentBatchSpec,
    AgentRuntimeProfileSpec,
    AgentStateBundleSpec,
    InventoryItemSpec,
    RelationshipVectorSpec,
)
from ..flex_api import first_json_value_from_text
from ..foundation_schemas import GridPosition
from ..package_db import is_world_package_db, materialize_world_package
from ..jsonc_utils import dump_json, load_jsonc_path
from ..universal_adjudicator import core as adjudicator
from ..extra_world_functions import (
    extra_world_functions_config,
    recent_global_world_events,
    run_extra_world_functions,
)
from ..world_definition import default_wallet_payload
from ..world_definition import legacy_currency_inventory_entry
from ..world_definition import sync_world_definition_into_config
from ..agent_factory import (
    SafeDict,
    _format,
    _room_spawn_cells,
    _spawn_coordinate_for_room,
    _runner_config,
    _world_label,
    _domain_label,
    _story_filename,
    _run_name,
    _agent_id_prefix,
    _image_generation_config,
    _inventory_item,
    _currency_item,
    _starting_wallet_range,
    _role_sequence,
    _room_for_agent,
    _room_by_id,
    _main_character_specs,
    _main_character_ids,
    _force_cinematic_agent_ids,
    _main_character_payload,
    _variation_token,
    _display_name_for_agent,
    _build_agent_payloads,
    _vertex_agent_profile_payloads,
    _inventory_generation_config,
    _merge_inventory_items,
    _vertex_initial_inventory_payloads,
)
from ..vertex_json_client import VertexJsonClient
from ..vertex_image_client import VertexSDKImageClient

from .utils import *
from .config import *
from .grid import *
from .agents_state import *




SCRIPT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_ENV = "AGORA_SIM_CONFIG"
DEFAULT_PY_BIN = Path(sys.executable)




# Sub-modules imports
import inspect
from . import memory, memory_compression, prompts, intents, intent_schemas, intent_builders
for mod in (memory, memory_compression, prompts, intents, intent_schemas, intent_builders):
    for name, obj in inspect.getmembers(mod):
        if not name.startswith('__'):
            globals()[name] = obj

def _mirror_runtime_image(
    image_path: str,
    *,
    run_id: str,
    image_cache: dict[str, str],
) -> str:
    source = Path(str(image_path).strip()).expanduser()
    if not str(source).strip() or not source.is_file():
        return ""
    resolved = source.resolve()
    cache_key = str(resolved)
    if cache_key in image_cache:
        return image_cache[cache_key]
    extension = resolved.suffix.lower() or ".png"
    digest = hashlib.sha1(cache_key.encode("utf-8")).hexdigest()[:16]
    destination_dir = SCRIPT_DIR / "frontend" / "assets" / "runtime_state" / run_id / "images"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{digest}{extension}"
    if not destination.exists():
        shutil.copy2(resolved, destination)
    browser_url = f"./assets/runtime_state/{run_id}/images/{destination.name}"
    image_cache[cache_key] = browser_url
    return browser_url


def materialize_scenario(
    config: dict[str, Any],
    scenario_dir: Path,
    *,
    agent_payloads: list[dict[str, Any]] | None = None,
) -> dict[str, Path]:
    scenario_dir.mkdir(parents=True, exist_ok=True)
    agents_dir = scenario_dir / "Agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    rooms = [dict(room) for room in config.get("space", {}).get("rooms", [])]
    grid_shape = _resolved_grid_shape(config)
    map_visual = dict(config.get("space", {}).get("map_visual", {}))
    movement = dict(config.get("space", {}).get("movement", {}))
    targeting = dict(config.get("space", {}).get("targeting", {}))
    custom_actions = list(config.get("actions", {}).get("allowed_custom_actions", []))
    rule_config = dict(config.get("world_rules", {}))
    item_rules = dict(rule_config.get("item_rules", {}))
    image_rules = dict(rule_config.get("image_rules", {}))
    custom_rule_config = dict(rule_config.get("custom_action_rules", {}))
    social_rules = [str(item) for item in rule_config.get("social_rules", [])]
    manifest_config = dict(config.get("manifest", {})) if isinstance(config.get("manifest", {}), dict) else {}
    asset_config = dict(manifest_config.get("asset_bindings", {})) if isinstance(manifest_config.get("asset_bindings", {}), dict) else {}

    world_rules = {
        "world_mode": str(config.get("runtime", {}).get("world_mode", "Fixed")),
        "topology": {"grid_shape": grid_shape, "rooms": rooms},
        "movement": movement,
        "item_rules": item_rules,
        "image_rules": image_rules,
        "custom_action_rules": {
            "default_duration_steps": int(custom_rule_config.get("default_duration_steps", 2)),
            "max_range_steps": int(targeting.get("max_range_steps", 3)),
            "allowed_actions": [str(x) for x in custom_actions],
        },
        "social_rules": social_rules,
        "discovered_rules": [],
    }

    agents = agent_payloads if agent_payloads is not None else _build_agent_payloads(config)
    active_agent_paths: list[str] = []
    initial_positions: dict[str, dict[str, int]] = {}
    initial_room_ids: dict[str, str] = {}
    for agent in agents:
        rel_path = f"./Agents/{agent['agent_id']}.json"
        active_agent_paths.append(rel_path)
        initial_positions[str(agent["agent_id"])] = dict(agent["coordinates"])
        initial_room_ids[str(agent["agent_id"])] = str(agent["room_id"])
        AgentRuntimeProfileSpec.model_validate(agent)
        dump_json(agents_dir / f"{agent['agent_id']}.json", agent)

    map_grid = {
        "grid_shape": grid_shape,
        "map_visual": map_visual,
        "rooms": rooms,
        "initial_positions": initial_positions,
        "initial_room_ids": initial_room_ids,
    }

    manifest = {
        "scenario_meta": dict(config.get("scenario_meta", {})),
        "engine_config": {
            "world_mode": str(config.get("runtime", {}).get("world_mode", "Fixed")),
            "adjudicator_api": {
                "provider": str(config.get("runtime", {}).get("provider", "Local")),
                "model": "",
                "temperature": 0.0,
                "flex_api_url": "http://127.0.0.1:8000/v1",
                "server_script": "",
            },
            "agent_default_api": {
                "provider": "Vertex_AI",
                "model": str(config.get("runtime", {}).get("vertex_model", "")),
                "temperature": 0.6,
                "flex_api_url": "http://127.0.0.1:8000/v1",
                "server_script": "vertex_flex_server.py",
            },
            "simulation_params": {
                "max_timesteps": int(config.get("runtime", {}).get("rounds", 10)),
                "parallel_execution": True,
                "tick_rate_ms": 0,
                "concurrency_limit": int(config.get("runtime", {}).get("agent_count", 100)),
            },
        },
        "asset_bindings": {
            "world_rules_path": str(asset_config.get("world_rules_path", "./world_rules.json")),
            "map_grid_path": str(asset_config.get("map_grid_path", "./map_grid.json")),
            "active_agents": active_agent_paths,
            "relationship_tensor_path": str(asset_config.get("relationship_tensor_path", "")),
            "localized_visual_state_path": str(asset_config.get("localized_visual_state_path", "")),
            "intents_path": str(asset_config.get("intents_path", "./agent_intents.json")),
            "intent_batches_path": str(asset_config.get("intent_batches_path", "./intent_batches")),
            "prompt_path": str(asset_config.get("prompt_path", "../../data/templates/foundation/universal_adjudicator_prompt.jsonc")),
        },
    }

    empty_batch = {"timestep_index": 1, "intents": []}
    batches_dir = scenario_dir / "intent_batches"
    batches_dir.mkdir(parents=True, exist_ok=True)
    dump_json(scenario_dir / "world_rules.json", world_rules)
    dump_json(scenario_dir / "map_grid.json", map_grid)
    dump_json(scenario_dir / "manifest.json", manifest)
    dump_json(scenario_dir / "agent_intents.json", empty_batch)
    dump_json(batches_dir / "001_round_001.json", empty_batch)

    return {
        "manifest": scenario_dir / "manifest.json",
        "world_rules": scenario_dir / "world_rules.json",
        "map_grid": scenario_dir / "map_grid.json",
        "agents_dir": agents_dir,
    }


class LongLiveTwoPromptGenerator:
    def __init__(self, config: dict[str, Any], run_dir: Path) -> None:
        ll = config.get("longlive", {})
        self.longlive_root = _resolve(ll.get("longlive_root", ""))
        self.template_config = _resolve(ll.get("template_config", ""))
        self.segment_seconds = int(ll.get("segment_seconds", 10))
        self.output_video_fps = float(ll.get("output_video_fps", 16.0))
        self.timeout_seconds = int(ll.get("timeout_seconds", 7200))
        self.run_dir = run_dir
        self.python_bin = str(DEFAULT_PY_BIN if DEFAULT_PY_BIN.is_file() else Path(sys.executable))

    @staticmethod
    def _parse_nvidia_smi_gpu_table() -> list[dict[str, int]]:
        if not shutil.which("nvidia-smi"):
            return []
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=index,memory.free,memory.total,memory.used",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception:
            return []
        if result.returncode != 0:
            return []
        rows: list[dict[str, int]] = []
        for line in result.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 4:
                continue
            try:
                rows.append(
                    {
                        "index": int(parts[0]),
                        "memory_free_mb": int(float(parts[1])),
                        "memory_total_mb": int(float(parts[2])),
                        "memory_used_mb": int(float(parts[3])),
                    }
                )
            except Exception:
                continue
        return rows

    def _select_cuda_device(self) -> dict[str, Any] | None:
        gpu_rows = self._parse_nvidia_smi_gpu_table()
        if not gpu_rows:
            return None
        gpu_rows.sort(
            key=lambda row: (
                -int(row.get("memory_free_mb", 0)),
                int(row.get("memory_used_mb", 0)),
                int(row.get("index", 0)),
            )
        )
        best = dict(gpu_rows[0])
        best["memory_free_gb"] = round(int(best.get("memory_free_mb", 0)) / 1024.0, 2)
        best["memory_total_gb"] = round(int(best.get("memory_total_mb", 0)) / 1024.0, 2)
        best["memory_used_gb"] = round(int(best.get("memory_used_mb", 0)) / 1024.0, 2)
        return best

    def _latent_schedule(self, prompt_count: int) -> tuple[int, list[int], int, float]:
        first_segment_latent = int(round(self.segment_seconds * self.output_video_fps / 4.0)) + 1
        first_segment_latent = max(2, first_segment_latent)
        incremental_latent = max(1, int(round(self.segment_seconds * self.output_video_fps / 4.0)))
        total_latent = first_segment_latent + max(0, prompt_count - 1) * incremental_latent
        switch_indices = [
            first_segment_latent + incremental_latent * idx
            for idx in range(0, max(0, prompt_count - 1))
        ]
        total_rgb_frames = 4 * (total_latent - 1) + 1
        intended_seconds = max(1.0, float(prompt_count * self.segment_seconds))
        return total_latent, switch_indices, total_rgb_frames, total_rgb_frames / intended_seconds

    def run(
        self,
        *,
        prompts: list[str],
        job_id: str,
        seed: int,
        disabled: bool,
    ) -> dict[str, Any]:
        job_dir = self.run_dir / "longlive_jobs" / job_id
        prompt_dir = job_dir / "prompts"
        config_dir = job_dir / "configs"
        logs_dir = job_dir / "logs"
        videos_dir = job_dir / "videos"
        for path in (prompt_dir, config_dir, logs_dir, videos_dir):
            path.mkdir(parents=True, exist_ok=True)

        prompts_jsonl = prompt_dir / "prompts.jsonl"
        prompts_jsonl.write_text(json.dumps({"prompts": prompts}, ensure_ascii=False) + "\n", encoding="utf-8")

        total_latent, switch_indices, total_rgb_frames, effective_fps = self._latent_schedule(len(prompts))
        config_path = config_dir / "longlive_config.yaml"
        command_log = logs_dir / "longlive.log"
        base_record = {
            "job_id": job_id,
            "status": "disabled" if disabled else "pending",
            "prompts_jsonl_path": str(prompts_jsonl),
            "config_path": str(config_path),
            "command_log_path": str(command_log),
            "video_path": "",
            "snapshot_path": "",
            "num_output_frames": total_latent,
            "total_rgb_frames": total_rgb_frames,
            "switch_frame_indices": switch_indices,
            "output_video_fps": effective_fps,
            "gpu_selection": {},
        }
        if disabled:
            return base_record
        if not self.template_config.is_file():
            raise FileNotFoundError(f"LongLive template config not found: {self.template_config}")
        try:
            from omegaconf import OmegaConf
        except Exception as exc:
            raise RuntimeError("OmegaConf is required for LongLive config generation") from exc
        cfg = OmegaConf.load(self.template_config)
        raw_dir = job_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        cfg.data_path = str(prompts_jsonl)
        cfg.output_folder = str(raw_dir)
        cfg.num_output_frames = int(total_latent)
        cfg.num_samples = 1
        cfg.save_with_index = True
        block_size = int(getattr(cfg, "num_frame_per_block", 1) or 1)
        if block_size <= 0 or int(total_latent) % block_size != 0:
            cfg.num_frame_per_block = 1
        cfg.seed = int(seed)
        cfg.inference_iter = -1
        cfg.switch_frame_indices = ",".join(str(item) for item in switch_indices)
        cfg.output_video_fps = float(effective_fps)
        OmegaConf.save(cfg, str(config_path))

        cmd = [self.python_bin, "interactive_inference.py", "--config_path", str(config_path)]
        selected_gpu = self._select_cuda_device()
        if selected_gpu is None:
            base_record["status"] = "failed_no_gpu"
            base_record["gpu_selection"] = {
                "source": "nvidia-smi",
                "selected": False,
                "reason": "no_cuda_devices_detected",
            }
            with command_log.open("w", encoding="utf-8") as handle:
                handle.write(f"[CMD] {' '.join(cmd)}\n")
                handle.write("[GPU_SELECTION] no CUDA devices detected\n")
            return base_record
        selected_index = int(selected_gpu["index"])
        env = os.environ.copy()
        env.setdefault("MKL_SERVICE_FORCE_INTEL", "1")
        env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
        env["CUDA_VISIBLE_DEVICES"] = str(selected_index)
        env["NVIDIA_VISIBLE_DEVICES"] = str(selected_index)
        base_record["gpu_selection"] = {
            "source": "nvidia-smi",
            "selected": True,
            "gpu_index": selected_index,
            "memory_free_mb": selected_gpu.get("memory_free_mb", 0),
            "memory_total_mb": selected_gpu.get("memory_total_mb", 0),
            "memory_used_mb": selected_gpu.get("memory_used_mb", 0),
            "memory_free_gb": selected_gpu.get("memory_free_gb", 0.0),
            "memory_total_gb": selected_gpu.get("memory_total_gb", 0.0),
            "memory_used_gb": selected_gpu.get("memory_used_gb", 0.0),
        }
        with command_log.open("w", encoding="utf-8") as handle:
            handle.write(f"[CMD] {' '.join(cmd)}\n")
            handle.write(
                f"[GPU_SELECTION] selected={selected_index} "
                f"free_mb={selected_gpu.get('memory_free_mb', 0)} "
                f"total_mb={selected_gpu.get('memory_total_mb', 0)} "
                f"used_mb={selected_gpu.get('memory_used_mb', 0)}\n"
            )
            handle.flush()
            result = subprocess.run(
                cmd,
                cwd=str(self.longlive_root),
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                env=env,
            )
        if result.returncode != 0:
            base_record["status"] = "failed"
            base_record["returncode"] = result.returncode
            return base_record
        mp4s = sorted(raw_dir.glob("*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not mp4s:
            base_record["status"] = "failed_no_video"
            return base_record
        video_path = videos_dir / "cinematic_interaction.mp4"
        shutil.copy2(mp4s[0], video_path)
        base_record["status"] = "ok"
        base_record["video_path"] = str(video_path)
        return base_record


def _load_world_rules(scenario_dir: Path) -> Any:
    return adjudicator._load_world_rules(scenario_dir / "world_rules.json")


def _build_control(config: dict[str, Any]) -> Any:
    from ..adjudicator_schemas import AdjudicatorControlSpec

    meta = config.get("scenario_meta", {})
    return AdjudicatorControlSpec(
        run_name=_run_name(config),
        adjudication_backend="local",
        world_description=str(meta.get("description", "")),
        simulation_objective=str(meta.get("simulation_objective", "")),
        social_norms=[],
        timestep_index=1,
        priority_order=["Move", "Custom", "Item", "Image"],
    )


def run_simulation(args: argparse.Namespace) -> Path:
    if args.config is None:
        env_config = os.environ.get(DEFAULT_CONFIG_ENV, "").strip()
        if not env_config:
            raise ValueError(f"--config is required unless {DEFAULT_CONFIG_ENV} is set")
        config_path = _resolve(env_config)
    else:
        config_path = _resolve(args.config)
    package_snapshot = None
    if is_world_package_db(config_path):
        package_snapshot = materialize_world_package(config_path)
        config_path = package_snapshot.config_path
        args.scenario_dir = package_snapshot.scenario_dir
    config = load_jsonc_path(config_path)
    if not isinstance(config, dict):
        raise ValueError("world config must be a JSON object")
    config = sync_world_definition_into_config(config)
    from ..runtime import RuntimeExecutionContext, build_runtime_engine, compile_orchestration_config

    plan = compile_orchestration_config(config)
    engine = build_runtime_engine()
    ctx = RuntimeExecutionContext(
        args=args,
        config_path=config_path,
        config=config,
        plan=plan,
    )
    engine.execute(ctx)
    return ctx.require("run_dir")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a JSON-defined multi-agent interaction simulation.")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--scenario-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--rounds", type=int, default=None)
    parser.add_argument("--activation", type=float, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--max-videos-per-round", type=int, default=None)
    parser.add_argument("--max-images-per-round", type=int, default=None)
    parser.add_argument("--disable-longlive", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--disable-image-generation", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--skip-report", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument(
        "--reuse-agent-profile-cache",
        type=Path,
        default=None,
        help="Reuse runtime_agent entries from an existing agent_profile_api_cache directory instead of regenerating profiles.",
    )
    parser.add_argument(
        "--resume-run-dir",
        type=Path,
        default=None,
        help="Resume from the completed rounds in a prior run directory, starting after the last complete timeline/timestep pair.",
    )
    return parser.parse_args()


def main() -> None:
    run_simulation(_parse_args())

__all__ = ['SCRIPT_DIR', 'DEFAULT_CONFIG_ENV', 'DEFAULT_PY_BIN', '_mirror_runtime_image', 'materialize_scenario', '_find_inventory_item', '_find_inventory_item_by_id', '_item_quantity', '_catalog_price', '_recording_context', '_room_prompt_context', '_visible_prop_context', '_recent_joint_history', '_normalize_shared_action_core', '_relationship_vector_payload', '_memory_config', '_runtime_memory', '_set_runtime_memory', '_memory_limit', '_limit_text', '_inventory_prompt_summary', '_property_prompt_summary', '_sanitize_recent_entry', '_sanitize_long_task', '_sanitize_visual_artifact', '_sanitize_textual_artifact', '_artist_feedback_follow_up_config', '_active_artist_feedback_follow_up', '_compress_image_for_reasoning', '_item_is_important_artifact', '_catalog_item_visual_records', '_initialize_runtime_memory', '_archive_recent_entry', '_task_thread_ids', '_shared_task_thread_ids', '_recent_interaction_count', '_strong_relationship_ids', '_location_awareness_payload', '_artifact_reasoning_parts', '_visual_artifacts_for_agent', '_select_route_source_artifact', '_replace_inventory_item_image', '_update_agent_runtime_memory', '_rebuild_runtime_memories_from_history', '_compact_agent_prompt_payload', '_local_visual_context', '_extra_world_functions_config', '_recent_global_world_events', '_store_extra_world_event', '_run_extra_world_functions', '_bounded_relationship_delta', '_normalize_relationship_adjustments', '_vertex_relationship_metadata', '_attach_relationship_metadata_once', '_build_custom_intent', '_build_trade_intents', '_rooms_by_distance', '_reachable_positions_from_config', '_build_move_intent', '_image_values', '_image_prompt_from_route', '_vertex_still_image_prompt', '_vertex_text_revision', '_build_image_intent', 'LongLiveTwoPromptGenerator', '_cinematic_values', '_vertex_action_request', '_vertex_video_prompts', '_first_image_route', '_first_move_route', '_route_lookup', '_fallback_request_for_quota', '_build_intents_for_request', '_load_world_rules', '_build_control', '_validate_target_legality', '_vertex_story_summary', 'run_simulation', '_parse_args', 'main']
