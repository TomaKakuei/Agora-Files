#!/usr/bin/env python3
"""Repair a guild asset revision by migrating misplaced retry outputs and rebuilding its manifest."""

from __future__ import annotations

import argparse
import json
import shutil
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


def _manifest_path(package_root: Path, revision: str) -> Path:
    return package_root / "frontend" / "assets" / "generated" / "world_asset_sets" / revision / "world_asset_set_manifest.json"


def _asset_dir(package_root: Path, agent_id: str, revision: str) -> Path:
    return package_root / "frontend" / "assets" / "generated" / agent_id / revision


def _asset_bundle_path(package_root: Path, agent_id: str, revision: str) -> Path:
    return _asset_dir(package_root, agent_id, revision) / "asset_bundle.json"


def _nested_generated_root(package_root: Path, revision: str) -> Path:
    return package_root / "frontend" / "assets" / "generated" / "world_asset_sets" / revision / "frontend" / "assets" / "generated"


def _migrate_nested_outputs(package_root: Path, revision: str) -> int:
    nested_root = _nested_generated_root(package_root, revision)
    if not nested_root.is_dir():
        return 0
    moved_dirs = 0
    for agent_dir in nested_root.iterdir():
        if not agent_dir.is_dir():
            continue
        nested_revision_dir = agent_dir / revision
        if not nested_revision_dir.is_dir():
            continue
        target_dir = _asset_dir(package_root, agent_dir.name, revision)
        target_dir.mkdir(parents=True, exist_ok=True)
        for source_file in nested_revision_dir.iterdir():
            target_file = target_dir / source_file.name
            if target_file.exists():
                target_file.unlink()
            shutil.move(str(source_file), str(target_file))
        moved_dirs += 1
    shutil.rmtree(nested_root, ignore_errors=True)
    return moved_dirs


def _rebuild_manifest(package_root: Path, manifest: dict[str, Any], revision: str) -> dict[str, Any]:
    rebuilt_assets: list[dict[str, Any]] = []
    for entry in manifest.get("agents", []):
        agent_id = str(entry.get("agent_id", "")).strip()
        if not agent_id:
            continue
        bundle_path = _asset_bundle_path(package_root, agent_id, revision)
        if bundle_path.is_file():
            bundle = _read_json(bundle_path)
            entry["asset_bundle_path"] = str(bundle_path)
            entry["asset_bundle"] = bundle
            entry["returncode"] = 0
            event = bundle.get("event")
            if isinstance(event, dict):
                rebuilt_assets.append(event)
        else:
            entry.pop("asset_bundle_path", None)
            entry.pop("asset_bundle", None)
            if entry.get("returncode") == 0:
                entry["returncode"] = 1
                entry["stderr"] = (
                    (entry.get("stderr") or "") + "\n[repair] Missing asset_bundle.json at expected frontend path."
                ).strip()
    manifest["agents"] = sorted(manifest.get("agents", []), key=lambda item: item.get("agent_id", ""))
    manifest["assets"] = rebuilt_assets
    quality_summaries = [
        entry.get("asset_bundle", {}).get("quality_summary", {})
        for entry in manifest.get("agents", [])
        if isinstance(entry.get("asset_bundle", {}), dict)
        and isinstance(entry.get("asset_bundle", {}).get("quality_summary", {}), dict)
    ]
    existing_quality = manifest.get("quality_summary", {}) if isinstance(manifest.get("quality_summary", {}), dict) else {}
    manifest["quality_summary"] = {
        "agent_count": len(manifest.get("agents", [])),
        "passing_agents": sum(1 for summary in quality_summaries if summary.get("pass") is True),
        "failing_agents": sum(1 for summary in quality_summaries if summary.get("pass") is False),
        "remote_agent_ids": list(existing_quality.get("remote_agent_ids", [])) if isinstance(existing_quality.get("remote_agent_ids", []), list) else [],
        "reuse_latest_raw_sheet": bool(existing_quality.get("reuse_latest_raw_sheet", False)),
        "max_workers": int(existing_quality.get("max_workers", 1) or 1),
    }
    return manifest


def _update_alias(package_root: Path, manifest_path: Path) -> None:
    alias_path = package_root / "frontend" / "assets" / "generated" / "world_asset_sets" / "current_world_pixel_set.json"
    alias_path.write_bytes(manifest_path.read_bytes())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--update-current-alias", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = Path(args.config).resolve()
    package_root = _locate_package_root(config_path)
    manifest_path = _manifest_path(package_root, args.revision)
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Revision manifest not found: {manifest_path}")
    manifest = _read_json(manifest_path)
    moved_dirs = _migrate_nested_outputs(package_root, args.revision)
    manifest = _rebuild_manifest(package_root, manifest, args.revision)
    _write_json(manifest_path, manifest)
    if args.update_current_alias:
        _update_alias(package_root, manifest_path)
    ok = sum(1 for entry in manifest.get("agents", []) if entry.get("returncode") == 0)
    fail = sum(1 for entry in manifest.get("agents", []) if entry.get("returncode") not in (0, None))
    print(json.dumps({"status": "ok", "revision": args.revision, "moved_dirs": moved_dirs, "ok": ok, "fail": fail}, indent=2))


if __name__ == "__main__":
    main()
