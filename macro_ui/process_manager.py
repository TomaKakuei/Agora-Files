from __future__ import annotations
import os
import sys
import time
import json
import subprocess
from pathlib import Path
from typing import Any

__all__ = [
    "_run_process_payload", "_systemd_unit_property", "_run_status",
    "_asset_worker_payload", "_pid_alive", "discover_runs",
    "current_run_record", "asset_worker_status",
    "launch_asset_bundle_worker", "launch_run_subprocess"
]
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
from agora_ui.scenario_schemas import ScenarioMapGridSpec
from .components.html_utils import _resolve_asset_path, _static_url_if_local

def _run_process_payload(run_dir: Path) -> dict[str, Any]:
    process_path = run_dir / PROCESS_RECORD_PATH
    if not process_path.is_file():
        return {}
    try:
        payload = _read_json(process_path)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _systemd_unit_property(unit_name: str, prop: str) -> str:
    if not unit_name:
        return ""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show", unit_name, f"--property={prop}", "--value"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return ""
    return result.stdout.strip()


def _run_status(run_dir: Path) -> str:
    final_manifest = run_dir / "final_manifest.json"
    if final_manifest.is_file():
        return "complete"
    process_payload = _run_process_payload(run_dir)
    unit_name = str(process_payload.get("unit_name", "")).strip()
    if unit_name:
        sub_state = _systemd_unit_property(unit_name, "SubState")
        if sub_state in {"running", "start", "start-pre", "start-post"}:
            return "running"
        if sub_state == "failed":
            return "failed"
    pid = int(process_payload.get("pid", 0) or 0)
    if _pid_alive(pid):
        return "running"
    if (run_dir / "run_config.json").is_file():
        return "stopped"
    return "unknown"


def discover_runs(package_root: Path = PACKAGE_ROOT) -> list[dict[str, Any]]:
    output_root = package_root / "output"
    if not output_root.is_dir():
        return []
    runs: list[dict[str, Any]] = []
    for run_dir in sorted(output_root.rglob("*")):
        if not run_dir.is_dir():
            continue
        if not (
            (run_dir / "run_config.json").is_file()
            or (run_dir / "profile_generation_run.json").is_file()
            or (run_dir / PROCESS_RECORD_PATH).is_file()
        ):
            continue
        run_config = RunConfigSpec.model_validate(_read_json(run_dir / "run_config.json")).model_dump() if (run_dir / "run_config.json").is_file() else {}
        profile_generation = _read_json(run_dir / "profile_generation_run.json") if (run_dir / "profile_generation_run.json").is_file() else {}
        process_payload = _run_process_payload(run_dir)
        config_path = _resolve_run_config_path(run_dir)
        config = _read_world_config(config_path) if config_path.is_file() else {}
        rounds = int(run_config.get("rounds", config.get("runtime", {}).get("rounds", 0)) or 0)
        completed_round = _completed_rounds(run_dir)
        runs.append(
            {
                "run_id": str(run_config.get("run_id") or profile_generation.get("run_id") or process_payload.get("run_id") or run_dir.name),
                "run_dir": str(run_dir),
                "created_at": str(run_config.get("created_at") or profile_generation.get("created_at") or process_payload.get("launched_at") or ""),
                "status": _run_status(run_dir),
                "rounds_target": rounds,
                "rounds_completed": completed_round,
                "activation_probability": float(run_config.get("activation_probability", config.get("runtime", {}).get("activation_probability", 0.0)) or 0.0),
                "agent_count": int(profile_generation.get("agent_count", config.get("runtime", {}).get("agent_count", 0)) or 0),
                "world_name": str(config.get("scenario_meta", {}).get("world_name", run_dir.name)),
                "world_id": str(config.get("scenario_meta", {}).get("world_id", "")),
                "story_filename": str(run_config.get("story_filename", "")),
            }
        )
    runs.sort(key=lambda item: (item.get("created_at", ""), item.get("run_id", "")), reverse=True)
    return runs


def current_run_record(package_root: Path = PACKAGE_ROOT) -> dict[str, Any] | None:
    runs = discover_runs(package_root)
    for run in runs:
        if run.get("status") == "running":
            return run
    return runs[0] if runs else None


def _asset_worker_payload(run_dir: Path) -> dict[str, Any]:
    path = run_dir / ASSET_WORKER_RECORD_PATH
    if not path.is_file():
        return {}
    try:
        payload = _read_json(path)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def asset_worker_status(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    worker_payload = _asset_worker_payload(run_dir)
    config_path = _resolve_run_config_path(run_dir)
    config = _read_world_config(config_path) if config_path.is_file() else {}
    scenario_dir = _resolve_scenario_dir(run_dir)
    scenario_manifest_path = scenario_dir / "manifest.json"
    if scenario_manifest_path.is_file():
        ScenarioManifestSpec.model_validate(_read_json(scenario_manifest_path)).model_dump()
    initial_agents = _load_agents_from_scenario(scenario_dir) or _load_cached_runtime_agents(run_dir)
    final_state_path = run_dir / "final_agent_profiles.json"
    final_state = AgentStateBundleSpec.model_validate(_read_json(final_state_path)).model_dump() if final_state_path.is_file() else {}
    final_agents = final_state.get("agents", initial_agents) if isinstance(final_state, dict) else initial_agents
    rooms = [dict(room) for room in config.get("space", {}).get("rooms", []) if isinstance(room, dict)]
    replay_assets_dir = run_dir / REPLAY_DIRNAME / "assets"
    room_image_count = len(list((replay_assets_dir / "images" / "rooms").glob("*.*")))
    agent_image_count = len(list((replay_assets_dir / "images" / "agents").glob("*.*")))
    item_image_count = len(list((replay_assets_dir / "images" / "items").glob("*.*")))
    expected_room_count = len(rooms)
    portraits_enabled = _character_portraits_enabled(config)
    expected_agent_count = len([agent for agent in final_agents if isinstance(agent, dict)]) if portraits_enabled else 0
    item_mode = _item_image_mode(config)
    expected_item_count = 0
    if item_mode != "off":
        seen_item_ids: set[str] = set()
        for agent in final_agents:
            if not isinstance(agent, dict):
                continue
            for item in agent.get("inventory", []) or []:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("item_id", "")).strip()
                if not item_id or item_id in seen_item_ids or int(item.get("quantity", 0) or 0) <= 0:
                    continue
                if item_mode == "important_only" and not _item_is_important_artifact(item):
                    continue
                existing_local = _resolve_asset_path(item.get("image_path", ""))
                if existing_local is not None and existing_local.is_file():
                    continue
                seen_item_ids.add(item_id)
        expected_item_count = len(seen_item_ids)
    unit_name = str(worker_payload.get("unit_name", "")).strip()
    sub_state = _systemd_unit_property(unit_name, "SubState") if unit_name else ""
    status = "idle"
    if unit_name and sub_state in {"running", "start", "start-pre", "start-post"}:
        status = "running"
    elif unit_name and sub_state == "failed":
        status = "failed"
    elif (
        expected_room_count and room_image_count >= expected_room_count
        and (expected_agent_count == 0 or agent_image_count >= expected_agent_count)
        and (expected_item_count == 0 or item_image_count >= expected_item_count)
    ):
        status = "complete"
    elif room_image_count or agent_image_count or item_image_count:
        status = "partial"
    elif worker_payload.get("status") == "launch_failed":
        status = "failed"
    return {
        "status": status,
        "unit_name": unit_name,
        "room_images": room_image_count,
        "expected_room_images": expected_room_count,
        "agent_images": agent_image_count,
        "expected_agent_images": expected_agent_count,
        "item_images": item_image_count,
        "expected_item_images": expected_item_count,
        "stdout_path": str(worker_payload.get("stdout_path", "")),
        "launcher_returncode": worker_payload.get("launcher_returncode", None),
        "launcher_stderr": str(worker_payload.get("launcher_stderr", "")),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def launch_asset_bundle_worker(
    *,
    package_root: Path = PACKAGE_ROOT,
    run_dir: Path,
    force_refresh_images: bool = False,
    wait_for_scenario_seconds: int = 180,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    log_dir = run_dir / "runtime"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / "asset_worker.log"
    py_bin = str(DEFAULT_PY_BIN if DEFAULT_PY_BIN.is_file() else Path(sys.executable))
    worker_cmd = [
        py_bin,
        "-m",
        "macro_ui.build_macro_ui",
        "--run-dir",
        str(run_dir),
        "--wait-for-scenario-seconds",
        str(int(wait_for_scenario_seconds)),
    ]
    if force_refresh_images:
        worker_cmd.append("--force-refresh-images")
    unit_name = f"agora-replay-assets-{_slug(run_dir.name)}"
    shell_command = (
        f". /home/yz_wang/.config/agora_ui_runtime.env && "
        f"export PYTHONPATH={json.dumps(str(package_root))}:$PYTHONPATH && "
        f"exec {' '.join(json.dumps(part) for part in worker_cmd)} >> {json.dumps(str(stdout_path))} 2>&1"
    )
    systemd_cmd = [
        "systemd-run",
        "--user",
        f"--unit={unit_name}",
        f"--working-directory={package_root}",
        "/bin/bash",
        "-lc",
        shell_command,
    ]
    with stdout_path.open("a", encoding="utf-8") as handle:
        handle.write(f"[ASSET_WORKER] {datetime.now(timezone.utc).isoformat()} {' '.join(worker_cmd)}\n")
        handle.flush()
    result = subprocess.run(
        systemd_cmd,
        cwd=str(package_root),
        capture_output=True,
        text=True,
        check=False,
    )
    payload = {
        "unit_name": unit_name,
        "run_dir": str(run_dir),
        "launched_at": datetime.now(timezone.utc).isoformat(),
        "stdout_path": str(stdout_path),
        "command": worker_cmd,
        "launcher_command": systemd_cmd,
        "launcher_returncode": int(result.returncode),
        "launcher_stdout": result.stdout.strip(),
        "launcher_stderr": result.stderr.strip(),
        "status": "launched" if result.returncode == 0 else "launch_failed",
    }
    _write_json(run_dir / ASSET_WORKER_RECORD_PATH, payload)
    return payload




DEFAULT_PY_BIN = Path("/home/yz_wang/.conda/envs/new_py310/bin/python")
RUN_INPUTS_DIRNAME = "run_inputs"
REPLAY_DIRNAME = "replay"
PROCESS_RECORD_PATH = Path("runtime/process.json")
ASSET_WORKER_RECORD_PATH = Path("runtime/asset_worker.json")
PACKAGE_EXPORTS_DIRNAME = "package_exports"
PACKAGE_META_FILENAME = "package_meta.json"

DEFAULT_GIVEN_NAMES = [
    "Airi", "Akio", "Amaya", "Asahi", "Aya", "Chihiro", "Daichi", "Emi", "Fumika", "Hana",
    "Haruto", "Hikari", "Hinata", "Ichika", "Itsuki", "Jun", "Kaede", "Kaoru", "Koharu", "Makoto",
    "Mei", "Midori", "Minato", "Nao", "Noboru", "Nozomi", "Riku", "Rio", "Rin", "Risa",
    "Saki", "Seina", "Shin", "Shiori", "Suzu", "Takumi", "Touma", "Tsukasa", "Yori", "Yui",
    "Alden", "Brisa", "Caelum", "Darian", "Elio", "Fiora", "Galen", "Iria", "Joren", "Liora",
    "Maren", "Nerin", "Orin", "Perrin", "Quilla", "Sorrel", "Tarin", "Vesper", "Wren", "Zephyr",
]
DEFAULT_FAMILY_NAMES = [
    "Aster", "Ashdown", "Briar", "Cinderfell", "Dawnmere", "Emberfall", "Fairwind", "Foxglove", "Glenmere", "Hawthorne",
    "Ironbloom", "Juniper", "Kestrel", "Larkspur", "Moonridge", "Nightbrook", "Oakfen", "Pinecrest", "Quill", "Rainmere",
    "Starfall", "Stonewell", "Sunmeadow", "Thornfield", "Vale", "Verdant", "Westmere", "Windmere", "Wrenford", "Yarrow",
]
DEFAULT_VISUAL_VARIATION = {
    "age_bands": ["young adult", "adult", "seasoned adult"],
    "skin_tones": [
        "warm brown", "light olive", "golden tan", "cool fair", "deep umber", "sun-browned",
        "soft bronze", "freckled fair", "neutral beige", "rich sienna",
    ],
    "hair_colors": [
        "black", "dark brown", "auburn", "silver", "ash blond", "copper", "deep blue-black",
        "chestnut", "platinum blond", "dark teal",
    ],
    "hair_styles": [
        "braided hair", "short layered hair", "long tied-back hair", "curly shoulder-length hair",
        "wavy cropped hair", "undercut with loose fringe", "straight bob hair", "high ponytail",
        "loose locs", "messy medium hair",
    ],
    "body_types": [
        "lean", "broad-shouldered", "compact athletic", "tall wiry", "soft sturdy", "slight agile",
        "muscular", "graceful long-limbed",
    ],
    "signature_accessories": [
        "a rune charm", "a stitched satchel", "a patterned scarf", "a brass ear cuff", "fingerless gloves",
        "a lacquered hair pin", "a weathered shoulder cape", "a leather wrist wrap", "a tiny talisman", "an enamel brooch",
    ],
    "silhouette_traits": [
        "a clear layered silhouette", "a distinctive asymmetrical hem", "a strong traveling silhouette",
        "a compact practical outline", "a cloak-forward silhouette", "a clean ceremonial outline",
    ],
}



def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def launch_run_subprocess(
    *,
    package_root: Path = PACKAGE_ROOT,
    run_id: str,
    regular_agent_count: int,
    rounds: int,
    activation_probability: float,
    seed: int,
    main_characters_always_activate: bool,
    max_videos_per_round: int,
    segment_seconds: int,
    max_images_per_round: int,
    source_config: dict[str, Any] | None = None,
    package_access_code: str = "",
    resume_run_dir: Path | None = None,
) -> dict[str, Any]:
    output_root = package_root / "output" / "replay_runs"
    run_dir = output_root / run_id
    package_path = build_run_local_config(
        package_root=package_root,
        run_dir=run_dir,
        run_id=run_id,
        regular_agent_count=regular_agent_count,
        rounds=rounds,
        activation_probability=activation_probability,
        seed=seed,
        main_characters_always_activate=main_characters_always_activate,
        max_videos_per_round=max_videos_per_round,
        segment_seconds=segment_seconds,
        max_images_per_round=max_images_per_round,
        source_config=source_config,
    )
    scenario_dir = run_dir / RUN_INPUTS_DIRNAME / "scenario"
    log_dir = run_dir / "runtime"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / "launcher.log"
    _write_json(
        log_dir / "launch_request.json",
        {
            "run_id": run_id,
            "regular_agent_count": regular_agent_count,
            "rounds": rounds,
            "activation_probability": activation_probability,
            "seed": seed,
            "main_characters_always_activate": main_characters_always_activate,
            "max_videos_per_round": max_videos_per_round,
            "max_images_per_round": max_images_per_round,
            "segment_seconds": segment_seconds,
            "package_access_code": str(package_access_code or ""),
            "resume_run_dir": str(resume_run_dir) if resume_run_dir is not None else "",
            "auto_resume_on_failure": True,
        },
    )
    py_bin = str(DEFAULT_PY_BIN if DEFAULT_PY_BIN.is_file() else Path(sys.executable))
    def _runner_cmd(resume_source: Path | None) -> list[str]:
        cmd = [
            py_bin,
            "-m",
            "agora_ui.run_interaction_simulation",
            "--config",
            str(package_path),
            "--scenario-dir",
            str(scenario_dir),
            "--output-dir",
            str(output_root),
            "--run-id",
            run_id,
            "--rounds",
            str(int(rounds)),
            "--activation",
            str(float(activation_probability)),
            "--seed",
            str(int(seed)),
            "--max-videos-per-round",
            str(int(max_videos_per_round)),
            "--max-images-per-round",
            str(int(max_images_per_round)),
        ]
        if resume_source is not None:
            cmd.extend(["--resume-run-dir", str(resume_source)])
        return cmd

    runner_cmd = _runner_cmd(resume_run_dir)
    retry_runner_cmd = _runner_cmd(run_dir)
    unit_name = f"agora-replay-{_slug(run_id)}"
    shell_command = (
        f"{{ "
        f". /home/yz_wang/.config/agora_ui_runtime.env && "
        f"export MKL_SERVICE_FORCE_INTEL=1 PYTHONPATH={json.dumps(str(package_root))}:$PYTHONPATH && "
        f"set +e; "
        f"{' '.join(json.dumps(part) for part in runner_cmd)}; "
        f"exit_code=$?; "
        f"if [ $exit_code -ne 0 ]; then "
        f"echo '[LAUNCH_RETRY] auto-resuming from checkpoint'; "
        f"{' '.join(json.dumps(part) for part in retry_runner_cmd)}; "
        f"exit_code=$?; "
        f"fi; "
        f"exit $exit_code; "
        f"}} >> {json.dumps(str(stdout_path))} 2>&1"
    )
    systemd_cmd = [
        "systemd-run",
        "--user",
        f"--unit={unit_name}",
        f"--working-directory={package_root}",
        "/bin/bash",
        "-lc",
        shell_command,
    ]
    with stdout_path.open("a", encoding="utf-8") as handle:
        handle.write(f"[LAUNCH] {datetime.now(timezone.utc).isoformat()} {' '.join(runner_cmd)}\n")
        handle.flush()
    result = subprocess.run(
        systemd_cmd,
        cwd=str(package_root),
        capture_output=True,
        text=True,
        check=False,
    )
    process_payload = {
        "unit_name": unit_name,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "launched_at": datetime.now(timezone.utc).isoformat(),
        "stdout_path": str(stdout_path),
        "command": runner_cmd,
        "launcher_command": systemd_cmd,
        "launcher_returncode": int(result.returncode),
        "launcher_stdout": result.stdout.strip(),
        "launcher_stderr": result.stderr.strip(),
    }
    if result.returncode != 0:
        process_payload["status"] = "launch_failed"
    _write_json(run_dir / PROCESS_RECORD_PATH, process_payload)
    return process_payload

