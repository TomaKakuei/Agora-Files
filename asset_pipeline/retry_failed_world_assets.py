#!/usr/bin/env python3
"""Retry failed guild asset generations for an existing revision using an AI Studio override config."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _locate_package_root(config_path: Path) -> Path:
    current = config_path.resolve()
    for candidate in [current.parent, *current.parents]:
        if (candidate / "agora_ui").is_dir() and (candidate / "asset_pipeline").is_dir():
            return candidate
    raise RuntimeError(f"Could not locate Agora_UI package root from config path: {config_path}")


def _build_retry_config(base_config: dict[str, Any]) -> dict[str, Any]:
    config = json.loads(json.dumps(base_config))

    vertex_api = dict(config.get("vertex_api", {}))
    vertex_api["backend"] = "ai_studio"
    vertex_api["api_key_env"] = "AGORA_AISTUDIO_API_KEY"
    vertex_api["endpoint_base"] = "https://generativelanguage.googleapis.com/v1beta"
    vertex_api["method"] = "generateContent"
    vertex_api["thinking_level"] = str(vertex_api.get("thinking_level", "low") or "low").lower()
    vertex_api.setdefault("retry", {})
    retry = dict(vertex_api["retry"])
    retry["max_attempts"] = int(retry.get("max_attempts", 8))
    retry["initial_sleep_seconds"] = float(retry.get("initial_sleep_seconds", 5.0))
    retry["max_sleep_seconds"] = float(retry.get("max_sleep_seconds", 120.0))
    retry["backoff_multiplier"] = float(retry.get("backoff_multiplier", 2.0))
    vertex_api["retry"] = retry
    config["vertex_api"] = vertex_api

    image_generation = dict(config.get("image_generation", {}))
    image_generation["backend"] = "ai_studio"
    image_generation["api_key_env"] = "AGORA_AISTUDIO_API_KEY"
    image_generation["endpoint_base"] = "https://generativelanguage.googleapis.com/v1beta"
    image_generation["method"] = "generateContent"
    image_generation["thinking_level"] = "minimal"
    config["image_generation"] = image_generation

    concept_generation = dict(config.get("pixel_asset_pipeline", {}).get("concept_generation", {}))
    concept_generation["api_key_env"] = "AGORA_AISTUDIO_API_KEY"
    concept_generation["endpoint_base"] = "https://generativelanguage.googleapis.com/v1beta"
    concept_generation["response_modalities"] = ["TEXT"]
    config.setdefault("pixel_asset_pipeline", {})["concept_generation"] = concept_generation
    return config


def _manifest_path(package_root: Path, revision: str) -> Path:
    return package_root / "frontend" / "assets" / "generated" / "world_asset_sets" / revision / "world_asset_set_manifest.json"


def _asset_bundle_path(package_root: Path, agent_id: str, revision: str) -> Path:
    return package_root / "frontend" / "assets" / "generated" / agent_id / revision / "asset_bundle.json"


def _quality_failed(entry: dict[str, Any]) -> bool:
    bundle = entry.get("asset_bundle")
    if not isinstance(bundle, dict):
        return False
    if str(bundle.get("overall_status", "")).strip().lower() == "fail":
        return True
    quality_report_path = str(bundle.get("quality_report_path", "")).strip()
    if quality_report_path:
        path = Path(quality_report_path)
        if path.is_file():
            try:
                report = _read_json(path)
            except Exception:
                report = {}
            atlas_check = (
                report.get("programmatic_qa", {})
                .get("checks", {})
                .get("atlas_transparency", {})
            )
            if isinstance(atlas_check, dict) and atlas_check.get("pass") is False:
                return True
    return False


def _load_failed_agent_ids(manifest: dict[str, Any]) -> list[str]:
    return [
        entry["agent_id"]
        for entry in manifest.get("agents", [])
        if entry.get("returncode") != 0 or _quality_failed(entry)
    ]


def _update_manifest_assets(package_root: Path, manifest: dict[str, Any], revision: str) -> None:
    assets: list[dict[str, Any]] = []
    for agent_entry in manifest.get("agents", []):
        bundle_path = _asset_bundle_path(package_root, agent_entry["agent_id"], revision)
        if not bundle_path.is_file():
            continue
        agent_entry["asset_bundle_path"] = str(bundle_path)
        asset_bundle = _read_json(bundle_path)
        agent_entry["asset_bundle"] = asset_bundle
        event_payload = asset_bundle.get("event")
        if isinstance(event_payload, dict):
            assets.append(event_payload)
    manifest["assets"] = assets


def _mark_missing_bundle_failure(entry: dict[str, Any], bundle_path: Path) -> None:
    entry["returncode"] = 1
    stderr = str(entry.get("stderr", "") or "").strip()
    suffix = f"Expected bundle missing after successful subprocess exit: {bundle_path}"
    entry["stderr"] = f"{stderr}\n{suffix}".strip()


def _update_alias(package_root: Path, manifest_path: Path) -> None:
    alias_path = package_root / "frontend" / "assets" / "generated" / "world_asset_sets" / "current_world_pixel_set.json"
    alias_path.write_bytes(manifest_path.read_bytes())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--scenario-dir", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--agent-id", action="append", dest="agent_ids", default=[])
    parser.add_argument("--update-current-alias", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = Path(args.config).resolve()
    scenario_dir = Path(args.scenario_dir).resolve()
    package_root = _locate_package_root(config_path)
    manifest_path = _manifest_path(package_root, args.revision)
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Revision manifest not found: {manifest_path}")

    base_config = _read_json(config_path)
    manifest = _read_json(manifest_path)
    retry_agent_ids = args.agent_ids or _load_failed_agent_ids(manifest)
    if not retry_agent_ids:
        print(json.dumps({"status": "ok", "message": "No failed agents to retry."}, indent=2))
        return

    retry_config = _build_retry_config(base_config)
    retry_config_path = manifest_path.parent / "world_config_ai_studio_retry.json"
    _write_json(retry_config_path, retry_config)

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{package_root}:{env.get('PYTHONPATH', '')}".rstrip(":")
    generate_script = package_root / "asset_pipeline" / "generate_agent_assets.py"
    agent_index = {entry["agent_id"]: entry for entry in manifest.get("agents", [])}

    ok = 0
    failed = 0
    for agent_id in retry_agent_ids:
        cmd = [
            sys.executable,
            str(generate_script),
            "--config",
            str(retry_config_path),
            "--scenario-dir",
            str(scenario_dir),
            "--agent-id",
            agent_id,
            "--revision",
            args.revision,
            "--invoke-remote",
        ]
        result = subprocess.run(cmd, cwd=str(package_root), env=env, capture_output=True, text=True, check=False)
        entry = agent_index.setdefault(agent_id, {"agent_id": agent_id})
        entry["returncode"] = result.returncode
        entry["stdout"] = result.stdout[-4000:]
        entry["stderr"] = result.stderr[-4000:]
        bundle_path = _asset_bundle_path(package_root, agent_id, args.revision)
        if result.returncode == 0 and bundle_path.is_file():
            ok += 1
        elif result.returncode == 0:
            _mark_missing_bundle_failure(entry, bundle_path)
            failed += 1
        else:
            failed += 1

    manifest["agents"] = sorted(agent_index.values(), key=lambda item: item["agent_id"])
    manifest["retry_backend"] = "ai_studio"
    manifest["retry_config_path"] = str(retry_config_path)
    _update_manifest_assets(package_root, manifest, args.revision)
    _write_json(manifest_path, manifest)
    if args.update_current_alias:
        _update_alias(package_root, manifest_path)

    print(
        json.dumps(
            {
                "status": "ok",
                "revision": args.revision,
                "retried": len(retry_agent_ids),
                "retry_ok": ok,
                "retry_failed": failed,
                "manifest": str(manifest_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
