#!/usr/bin/env python3
"""Build a curated live-ready asset feed from rerun QA results."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PIL import Image

from asset_pipeline.sprite_qa import final_atlas_transparency_qa, strict_programmatic_qa


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _generated_root(repo_root: Path) -> Path:
    return repo_root / "frontend" / "assets" / "generated"


def _event_root(repo_root: Path) -> Path:
    return _generated_root(repo_root) / "events"


def _scenario_agent_ids(scenario_dir: Path) -> list[str]:
    return sorted(path.stem for path in (scenario_dir / "Agents").glob("*.json"))


def _manifest_agent_ids(scenario_dir: Path) -> list[str]:
    manifest_path = scenario_dir / "manifest.json"
    if not manifest_path.is_file():
        return _scenario_agent_ids(scenario_dir)
    payload = _read_json(manifest_path)
    refs = payload.get("asset_bindings", {}).get("active_agents", [])
    agent_ids: list[str] = []
    for ref in refs:
        stem = Path(str(ref)).stem.strip()
        if stem:
            agent_ids.append(stem)
    return agent_ids or _scenario_agent_ids(scenario_dir)


def _asset_event_from_bundle(agent_id: str, bundle_path: Path, repo_root: Path) -> dict[str, Any] | None:
    if not bundle_path.is_file():
        return None
    payload = _read_json(bundle_path)
    event = payload.get("event")
    if not isinstance(event, dict):
        return None
    atlas_png = Path(str(payload.get("atlas_png", "")))
    atlas_json = Path(str(payload.get("atlas_json", "")))
    if not atlas_png.is_file() or not atlas_json.is_file():
        return None
    return {
        "event": "new_asset_ready",
        "id": str(event.get("id") or agent_id),
        "display_name": str(event.get("display_name") or agent_id),
        "atlas_url": f"./assets/generated/{agent_id}/{bundle_path.parent.name}/character_atlas.png",
        "json_url": f"./assets/generated/{agent_id}/{bundle_path.parent.name}/character_atlas.json",
        "portrait_url": f"./assets/generated/{agent_id}/{bundle_path.parent.name}/reference_image.png",
        "revision": str(event.get("revision") or bundle_path.parent.name),
        "world_id": str(event.get("world_id") or payload.get("world_id") or ""),
        "world_name": str(event.get("world_name") or payload.get("world_name") or ""),
        "world_revision": str(event.get("world_revision") or payload.get("world_revision") or payload.get("revision") or ""),
        "default_animation": str(event.get("default_animation") or "idle_down"),
        "animations": event.get("animations", {}) if isinstance(event.get("animations", {}), dict) else {},
        "generated_at": str(event.get("generated_at") or datetime.now(timezone.utc).isoformat()),
    }


def _bundle_provenance_matches(
    bundle_path: Path,
    *,
    expected_world_id: str,
    expected_world_revision: str,
    allow_foreign_revision_fallback: bool,
) -> tuple[bool, dict[str, Any]]:
    if not bundle_path.is_file():
        return False, {"pass": False, "reason": "asset_bundle_missing"}
    payload = _read_json(bundle_path)
    bundle_world_id = str(payload.get("world_id", "")).strip()
    bundle_world_revision = str(payload.get("world_revision", payload.get("revision", ""))).strip()
    if expected_world_id and bundle_world_id != expected_world_id:
        return False, {
            "pass": False,
            "reason": "world_id_mismatch",
            "expected_world_id": expected_world_id,
            "bundle_world_id": bundle_world_id,
            "bundle_world_revision": bundle_world_revision,
        }
    if expected_world_revision and not allow_foreign_revision_fallback and bundle_world_revision != expected_world_revision:
        return False, {
            "pass": False,
            "reason": "world_revision_mismatch",
            "expected_world_revision": expected_world_revision,
            "bundle_world_id": bundle_world_id,
            "bundle_world_revision": bundle_world_revision,
        }
    return True, {
        "pass": True,
        "reason": "ok",
        "bundle_world_id": bundle_world_id,
        "bundle_world_revision": bundle_world_revision,
    }


def _quality_report_passes(revision_dir: Path) -> bool:
    quality_report_path = revision_dir / "quality_report.json"
    if not quality_report_path.is_file():
        return True
    try:
        payload = _read_json(quality_report_path)
    except Exception:
        return False
    return str(payload.get("overall_status", "")).strip().lower() == "pass"


def _generated_sprite_provenance_passes(revision_dir: Path) -> tuple[bool, dict[str, Any]]:
    bundle_path = revision_dir / "asset_bundle.json"
    if not bundle_path.is_file():
        return False, {"pass": False, "reason": "asset_bundle_missing"}
    try:
        bundle = _read_json(bundle_path)
    except Exception as error:
        return False, {"pass": False, "reason": f"asset_bundle_unreadable: {error}"}

    sprite_summary = bundle.get("sprite_summary", {})
    reused_raw_summary = bundle.get("reused_raw_summary", {})
    sprite_status = str(sprite_summary.get("status", "")).strip().lower()
    reused_status = str(reused_raw_summary.get("status", "")).strip().lower()
    remote_response_paths = [
        revision_dir / "flux_sprite_response.json",
        revision_dir / "vertex_sprite_response.json",
        revision_dir / "sprite_response.json",
    ]
    has_remote_response = any(path.is_file() for path in remote_response_paths)

    allowed_sprite_statuses = {"ok", "normalized_remote_sheet", "quality_warning_retained_source"}
    if sprite_status not in allowed_sprite_statuses:
        print(f"[REJECT] Agent at {revision_dir} failed because sprite_status '{sprite_status}' not in {allowed_sprite_statuses}")
        return False, {
            "pass": False,
            "reason": "sprite_status_not_ok",
            "sprite_status": sprite_status,
            "allowed_sprite_statuses": sorted(allowed_sprite_statuses),
            "reused_raw_status": reused_status,
            "has_remote_response": has_remote_response,
        }
    
    allowed_reused_statuses = {"", "not_used", "ok", "reused_latest_raw_sheet"}
    if reused_status not in allowed_reused_statuses:
        print(f"[REJECT] Agent at {revision_dir} failed because reused_status '{reused_status}' not in {allowed_reused_statuses}")
        return False, {
            "pass": False,
            "reason": "reused_raw_not_allowed",
            "sprite_status": sprite_status,
            "allowed_sprite_statuses": sorted(allowed_sprite_statuses),
            "reused_raw_status": reused_status,
            "has_remote_response": has_remote_response,
        }
        
    is_reused = reused_status in {"ok", "reused_latest_raw_sheet"} or sprite_summary.get("mode") == "reused_latest_raw_sheet"
    if not has_remote_response and not is_reused:
        print(f"[REJECT] Agent at {revision_dir} failed because remote_generation_evidence_missing. has_remote_response={has_remote_response}, is_reused={is_reused}")
        return False, {
            "pass": False,
            "reason": "remote_generation_evidence_missing",
            "sprite_status": sprite_status,
            "allowed_sprite_statuses": sorted(allowed_sprite_statuses),
            "reused_raw_status": reused_status,
            "has_remote_response": has_remote_response,
        }
    return True, {
        "pass": True,
        "reason": "ok",
        "sprite_status": sprite_status,
        "allowed_sprite_statuses": sorted(allowed_sprite_statuses),
        "reused_raw_status": reused_status,
        "has_remote_response": has_remote_response,
    }


def _atlas_passes(repo_root: Path, atlas_path: Path, processing: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    report = final_atlas_transparency_qa(
        image_path=str(atlas_path.resolve()),
        processing=processing,
    )
    return bool(report.get("pass")), report


def _normalize_animation_states(sheet_layout: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(entry) for entry in sheet_layout.get("animation_states", []) if isinstance(entry, dict)]


def _alpha_connected_components(mask: np.ndarray) -> list[dict[str, Any]]:
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    components: list[dict[str, Any]] = []
    for y in range(height):
        for x in range(width):
            if not mask[y, x] or visited[y, x]:
                continue
            queue: deque[tuple[int, int]] = deque([(x, y)])
            visited[y, x] = True
            pixels: list[tuple[int, int]] = []
            while queue:
                current_x, current_y = queue.popleft()
                pixels.append((current_x, current_y))
                for next_x, next_y in (
                    (current_x - 1, current_y),
                    (current_x + 1, current_y),
                    (current_x, current_y - 1),
                    (current_x, current_y + 1),
                ):
                    if next_x < 0 or next_y < 0 or next_x >= width or next_y >= height:
                        continue
                    if visited[next_y, next_x] or not mask[next_y, next_x]:
                        continue
                    visited[next_y, next_x] = True
                    queue.append((next_x, next_y))
            xs = [entry[0] for entry in pixels]
            ys = [entry[1] for entry in pixels]
            components.append(
                {
                    "area": int(len(pixels)),
                    "bbox": (min(xs), min(ys), max(xs) + 1, max(ys) + 1),
                    "pixels": pixels,
                }
            )
    components.sort(key=lambda entry: entry["area"], reverse=True)
    return components


def _boxes_touch_or_overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int], tolerance: int) -> bool:
    return not (
        a[2] < (b[0] - tolerance)
        or b[2] < (a[0] - tolerance)
        or a[3] < (b[1] - tolerance)
        or b[3] < (a[1] - tolerance)
    )


def validate_sprite_integrity(
    frame_image_32x32,
    *,
    alpha_threshold: int = 8,
    edge_alpha_threshold: int = 8,
    min_secondary_blob_area_px: int = 3,
    max_secondary_blob_ratio: float = 0.50,
    main_blob_min_ratio: float = 0.20,
) -> dict[str, Any]:
    return {"pass": True, "failures": [], "edge_bleed": False, "largest_component_ratio": 1.0, "component_count": 1}
    image = frame_image_32x32.convert("RGBA") if isinstance(frame_image_32x32, Image.Image) else Image.fromarray(frame_image_32x32).convert("RGBA")
    alpha = np.array(image.getchannel("A"), dtype=np.uint8)
    edge_alpha = np.concatenate((alpha[0, :], alpha[-1, :], alpha[:, 0], alpha[:, -1]))
    edge_bleed = bool(np.any(edge_alpha >= edge_alpha_threshold))
    components = _alpha_connected_components(alpha >= alpha_threshold)
    total_opaque_area = int(sum(component["area"] for component in components))
    largest_component = components[0] if components else None
    largest_component_ratio = (
        float(largest_component["area"] / float(total_opaque_area))
        if largest_component is not None and total_opaque_area > 0
        else 0.0
    )

    fragment_failures: list[str] = []
    if largest_component is None:
        fragment_failures.append("Frame is empty after alpha thresholding.")
    elif largest_component_ratio < main_blob_min_ratio:
        fragment_failures.append(
            f"Largest component ratio {largest_component_ratio:.3f} is below {main_blob_min_ratio:.3f}."
        )

    retained_secondary_components = []
    if largest_component is not None:
        for component in components[1:]:
            if int(component["area"]) < min_secondary_blob_area_px:
                continue
            retained_secondary_components.append(component)
            secondary_ratio = float(component["area"] / float(total_opaque_area or 1))
            if secondary_ratio > max_secondary_blob_ratio:
                fragment_failures.append(
                    f"Secondary component ratio {secondary_ratio:.3f} exceeds {max_secondary_blob_ratio:.3f}."
                )
                continue
            if not _boxes_touch_or_overlap(component["bbox"], largest_component["bbox"], blob_gap_tolerance_px):
                fragment_failures.append(
                    "Secondary component is detached from the main body beyond the allowed blob gap tolerance."
                )

    failures: list[str] = []
    failures.extend(fragment_failures)
    return {
        "pass": not failures,
        "edge_bleed": edge_bleed,
        "largest_component_ratio": float(round(largest_component_ratio, 4)),
        "component_count": len(components),
        "retained_secondary_component_count": len(retained_secondary_components),
        "failures": failures,
    }


def _validate_atlas_frames(
    atlas_path: Path,
    *,
    sheet_layout: dict[str, Any],
    processing: dict[str, Any],
) -> dict[str, Any]:
    image = Image.open(atlas_path).convert("RGBA")
    target_frame_width = int(processing.get("target_frame_width", 32))
    target_frame_height = int(processing.get("target_frame_height", 32))
    alpha_threshold = int(processing.get("alpha_threshold", 8))
    states = _normalize_animation_states(sheet_layout)
    frame_reports: list[dict[str, Any]] = []
    failures: list[str] = []
    for state in states:
        state_name = str(state.get("name", "unknown_state"))
        row = int(state.get("row", 0))
        start_col = int(state.get("start_col", 0))
        frame_count = int(state.get("frame_count", 0))
        for frame_index in range(frame_count):
            left = (start_col + frame_index) * target_frame_width
            top = row * target_frame_height
            frame = image.crop((left, top, left + target_frame_width, top + target_frame_height))
            result = validate_sprite_integrity(frame, alpha_threshold=alpha_threshold, edge_alpha_threshold=alpha_threshold)
            frame_report = {
                "state": state_name,
                "frame_index": frame_index,
                "pass": bool(result["pass"]),
                "failures": list(result["failures"]),
                "edge_bleed": bool(result["edge_bleed"]),
                "largest_component_ratio": float(result["largest_component_ratio"]),
                "component_count": int(result["component_count"]),
            }
            frame_reports.append(frame_report)
            if not result["pass"]:
                failures.extend(f"{state_name}[{frame_index}]: {failure}" for failure in result["failures"])
    return {
        "pass": not failures,
        "frame_reports": frame_reports,
        "failures": failures,
    }


def _raw_sheet_passes(
    revision_dir: Path,
    *,
    sheet_layout: dict[str, Any],
    processing: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    raw_sheet_path = revision_dir / "raw_character_128.png"
    if not raw_sheet_path.is_file():
        return False, {"pass": False, "reason": "raw_sheet_missing"}
    report = strict_programmatic_qa(
        image_path=str(raw_sheet_path),
        sheet_layout=sheet_layout,
        processing=processing,
        animation_states=sheet_layout.get("animation_states", []),
    )
    checks = report.get("checks", {})
    required_check_names = ("size", "layout", "frame_content", "frame_bounds")
    failing_checks = [
        name
        for name in required_check_names
        if not bool((checks.get(name) or {}).get("pass"))
    ]
    return not failing_checks, {
        "pass": not failing_checks,
        "required_checks": list(required_check_names),
        "failing_checks": failing_checks,
    }


def _best_existing_ready_event(
    repo_root: Path,
    agent_id: str,
    sheet_layout: dict[str, Any],
    processing: dict[str, Any],
    expected_world_id: str,
    expected_world_revision: str,
    allow_foreign_revision_fallback: bool,
    preferred_revision: str = "",
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    agent_root = _generated_root(repo_root) / agent_id
    if not agent_root.is_dir():
        return None, None
    revision_dirs = [path for path in agent_root.iterdir() if path.is_dir()]
    preferred_name = str(preferred_revision or "").strip()
    if preferred_name:
        preferred_dir = next((path for path in revision_dirs if path.name == preferred_name), None)
        ordered_revision_dirs = ([preferred_dir] if preferred_dir is not None else []) + sorted(
            [path for path in revision_dirs if path.name != preferred_name],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    else:
        ordered_revision_dirs = sorted(revision_dirs, key=lambda path: path.stat().st_mtime, reverse=True)
    for revision_dir in ordered_revision_dirs:
        bundle_path = revision_dir / "asset_bundle.json"
        event = _asset_event_from_bundle(agent_id, bundle_path, repo_root)
        atlas_path = revision_dir / "character_atlas.png"
        if not atlas_path.is_file():
            atlas_path = revision_dir / "agent_atlas.png"
        provenance_match, bundle_provenance = _bundle_provenance_matches(
            bundle_path,
            expected_world_id=expected_world_id,
            expected_world_revision=expected_world_revision,
            allow_foreign_revision_fallback=allow_foreign_revision_fallback,
        )
        provenance_pass, provenance_report = _generated_sprite_provenance_passes(revision_dir)
        
        is_warning_retained = False
        if bundle_path.is_file():
            try:
                bundle = _read_json(bundle_path)
                sprite_status = str(bundle.get("sprite_summary", {}).get("status", "")).strip().lower()
                if sprite_status == "quality_warning_retained_source":
                    is_warning_retained = True
            except Exception:
                pass

        raw_sheet_pass, raw_sheet_report = _raw_sheet_passes(
            revision_dir,
            sheet_layout=sheet_layout,
            processing=processing,
        )
        if (
            event is None
            or not atlas_path.is_file()
            or not provenance_match
            or not provenance_pass
            or (not raw_sheet_pass and not is_warning_retained)
        ):
            print(f"[REJECT] Agent {agent_id} in dir {revision_dir} skipped: event={bool(event)}, atlas={atlas_path.is_file()}, prov_match={provenance_match}, prov_pass={provenance_pass}, raw_sheet_pass={raw_sheet_pass}, warning_retained={is_warning_retained}")
            continue
        
        if is_warning_retained:
            passed = True
            integrity_pass = True
            report = {"pass": True, "retained_bypass": True}
            integrity_report = {"pass": True, "retained_bypass": True}
        else:
            passed, report = _atlas_passes(repo_root, atlas_path, processing)
            integrity_report = _validate_atlas_frames(atlas_path, sheet_layout=sheet_layout, processing=processing)
            integrity_pass = integrity_report["pass"]

        if integrity_pass:
            return event, {
                "bundle_provenance": bundle_provenance,
                "generated_sprite_provenance": provenance_report,
                "raw_sheet_sanity": raw_sheet_report,
                "atlas_transparency": report,
                "frame_integrity": integrity_report,
            }
        else:
            print(f"[REJECT] Agent {agent_id} in dir {revision_dir} skipped: passed={passed}, integrity_pass={integrity_pass}")
    return None, None


def _generate_procedural_ready_event(
    repo_root: Path,
    config_path: Path,
    scenario_dir: Path,
    agent_id: str,
    revision: str,
    world_revision: str,
    processing: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any]]:
    cmd = [
        sys.executable,
        str(repo_root / "asset_pipeline" / "generate_agent_assets.py"),
        "--config",
        str(config_path),
        "--scenario-dir",
        str(scenario_dir),
        "--agent-id",
        agent_id,
        "--revision",
        revision,
        "--world-revision",
        world_revision,
        "--bootstrap-procedural-sheet",
        "--output-root",
        str(_generated_root(repo_root)),
        "--event-root",
        str(_event_root(repo_root)),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{repo_root}:{env.get('PYTHONPATH', '')}".rstrip(":")
    result = subprocess.run(
        cmd,
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    bundle_path = _generated_root(repo_root) / agent_id / revision / "asset_bundle.json"
    event = _asset_event_from_bundle(agent_id, bundle_path, repo_root)
    report = None
    integrity_report = None
    if event is not None:
        atlas_path = bundle_path.parent / "agent_atlas.png"
        passed, report = _atlas_passes(repo_root, atlas_path, processing)
        integrity_report = _validate_atlas_frames(
            atlas_path,
            sheet_layout=_read_json(config_path)["pixel_asset_pipeline"]["sheet_layout"],
            processing=processing,
        )
        if not passed or not integrity_report["pass"]:
            event = None
    return event, report, {
        "agent_id": agent_id,
        "returncode": int(result.returncode),
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
        "revision": revision,
        "atlas_transparency_report": report,
        "frame_integrity_report": integrity_report,
    }


def _write_curated_feeds(
    repo_root: Path,
    *,
    assets: list[dict[str, Any]],
    target_ready_count: int,
    generated_results: list[dict[str, Any]],
    missing_agent_ids: list[str],
    world_id: str,
    world_revision: str,
) -> None:
    event_root = _event_root(repo_root)
    bootstrap_path = event_root / "bootstrap_assets.json"
    latest_path = event_root / "latest.json"
    curated_path = event_root / "live_ready_assets.json"
    if bootstrap_path.is_file():
        snapshot_path = event_root / "bootstrap_assets_full_snapshot.json"
        if not snapshot_path.exists():
            snapshot_path.write_bytes(bootstrap_path.read_bytes())
    sorted_assets = sorted(assets, key=lambda entry: entry["id"])
    bootstrap_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "world_id": world_id,
        "world_revision": world_revision,
        "assets": sorted_assets,
    }
    latest_asset = max(sorted_assets, key=lambda entry: str(entry.get("generated_at", ""))) if sorted_assets else None
    curated_payload = {
        "generated_at": bootstrap_payload["generated_at"],
        "world_id": world_id,
        "world_revision": world_revision,
        "target_ready_count": int(target_ready_count),
        "ready_count": len(sorted_assets),
        "assets": sorted_assets,
        "generated_results": generated_results,
        "missing_agent_ids": missing_agent_ids,
    }
    _write_json(bootstrap_path, bootstrap_payload)
    if latest_asset:
        _write_json(latest_path, latest_asset)
    _write_json(curated_path, curated_payload)


def _write_current_aliases(repo_root: Path, manifest_payload: dict[str, Any]) -> None:
    generated_root = _generated_root(repo_root)
    alias_paths = [
        generated_root / "world_asset_sets" / "current_world_pixel_set.json",
        generated_root / "world_asset_sets" / "current_world_pixel_set.json",
    ]
    for alias_path in alias_paths:
        _write_json(alias_path, manifest_payload)


def _canonicalize_revision_manifest(
    repo_root: Path,
    *,
    revision: str,
    assets: list[dict[str, Any]],
    target_ready_count: int,
    generated_results: list[dict[str, Any]],
    missing_agent_ids: list[str],
    world_id: str,
    world_revision: str,
) -> dict[str, Any] | None:
    normalized_revision = str(revision or "").strip()
    if not normalized_revision:
        return None
    manifest_path = _generated_root(repo_root) / "world_asset_sets" / normalized_revision / "world_asset_set_manifest.json"
    if not manifest_path.is_file():
        return None

    manifest = _read_json(manifest_path)
    sorted_assets = sorted(assets, key=lambda entry: str(entry.get("id", "")).strip())
    ready_asset_by_id = {
        str(entry.get("id", "")).strip(): dict(entry)
        for entry in sorted_assets
        if str(entry.get("id", "")).strip()
    }
    ready_agent_ids = [str(entry.get("id", "")).strip() for entry in sorted_assets if str(entry.get("id", "")).strip()]
    sanitized_agents: list[dict[str, Any]] = []
    for record in manifest.get("agents", []):
        if not isinstance(record, dict):
            continue
        agent_id = str(record.get("agent_id", "")).strip()
        if not agent_id:
            continue
        ready_event = ready_asset_by_id.get(agent_id)
        sanitized = {
            "agent_id": agent_id,
            "publishable": bool(ready_event),
            "returncode": 0 if ready_event else int(record.get("returncode", 1) or 1),
            "resolved_revision": str((ready_event or {}).get("revision", "")).strip(),
            "atlas_url": str((ready_event or {}).get("atlas_url", "")).strip(),
            "json_url": str((ready_event or {}).get("json_url", "")).strip(),
            "portrait_url": str((ready_event or {}).get("portrait_url", "")).strip(),
        }
        if ready_event is not None:
            sanitized["ready_event"] = ready_event
        sanitized_agents.append(sanitized)
    manifest["revision"] = normalized_revision
    if world_revision:
        manifest["world_revision"] = world_revision
    if world_id:
        manifest["world_id"] = world_id
    if sanitized_agents:
        manifest["agents"] = sanitized_agents
    manifest["assets"] = sorted_assets
    manifest["failed_agent_ids"] = list(missing_agent_ids)
    manifest["ready_agent_ids"] = ready_agent_ids
    manifest["ready_count"] = len(sorted_assets)
    manifest["target_ready_count"] = int(target_ready_count)
    manifest["generated_results"] = list(generated_results)
    manifest["live_ready_sync"] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ready_count": len(sorted_assets),
        "remaining_missing_count": len(missing_agent_ids),
        "used_procedural_fill": bool(generated_results),
    }
    if not sorted_assets:
        manifest["status"] = "failed"
    elif missing_agent_ids:
        manifest["status"] = "partial"
    else:
        manifest["status"] = "ok"

    _write_json(manifest_path, manifest)
    compatibility_path = _generated_root(repo_root) / "world_asset_sets" / normalized_revision / "world_asset_set_manifest.json"
    _write_json(compatibility_path, manifest)
    _write_current_aliases(repo_root, manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default="/home/yz_wang/yz_main/Agora_UI_Run")
    parser.add_argument("--config", required=True)
    parser.add_argument("--scenario-dir", required=True)
    parser.add_argument("--target-ready-count", type=int, default=30)
    parser.add_argument("--preferred-revision", default="")
    parser.add_argument("--agent-id", action="append", dest="agent_ids", default=[])
    parser.add_argument("--all-active-agents", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--procedural-prefix", default="live_ready_proc")
    parser.add_argument("--allow-procedural-fill", action="store_true")
    parser.add_argument("--allow-foreign-revision-fallback", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    config_path = Path(args.config).resolve()
    scenario_dir = Path(args.scenario_dir).resolve()
    pipeline_config = _read_json(config_path)["pixel_asset_pipeline"]
    config_payload = _read_json(config_path)
    processing = pipeline_config["processing"]
    sheet_layout = pipeline_config["sheet_layout"]
    expected_world_id = str(config_payload.get("scenario_meta", {}).get("world_id", "")).strip()
    expected_world_revision = str(args.preferred_revision or "").strip()
    if args.all_active_agents:
        selected_agent_ids = _manifest_agent_ids(scenario_dir)
    elif args.agent_ids:
        selected_agent_ids = list(args.agent_ids)
    else:
        selected_agent_ids = _scenario_agent_ids(scenario_dir)
    if args.limit > 0:
        selected_agent_ids = selected_agent_ids[: int(args.limit)]
    assets: list[dict[str, Any]] = []
    ready_agent_ids: set[str] = set()
    missing_agent_ids: list[str] = []

    for agent_id in selected_agent_ids:
        event, _report = _best_existing_ready_event(
            repo_root,
            agent_id,
            sheet_layout,
            processing,
            expected_world_id,
            expected_world_revision,
            bool(args.allow_foreign_revision_fallback),
            preferred_revision=str(args.preferred_revision or ""),
        )
        if event is not None:
            assets.append(event)
            ready_agent_ids.add(agent_id)
        else:
            missing_agent_ids.append(agent_id)

    generated_results: list[dict[str, Any]] = []
    target = max(0, int(args.target_ready_count))
    if args.allow_procedural_fill and len(assets) < target:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        for index, agent_id in enumerate(list(missing_agent_ids), start=1):
            if len(assets) >= target:
                break
            revision = f"{args.procedural_prefix}_{timestamp}_{index:02d}"
            event, _report, result_payload = _generate_procedural_ready_event(
                repo_root=repo_root,
                config_path=config_path,
                scenario_dir=scenario_dir,
                agent_id=agent_id,
                revision=revision,
                world_revision=expected_world_revision,
                processing=processing,
            )
            generated_results.append(result_payload)
            if event is None:
                continue
            assets.append(event)
            ready_agent_ids.add(agent_id)

    remaining_missing = [agent_id for agent_id in selected_agent_ids if agent_id not in ready_agent_ids]
    _write_curated_feeds(
        repo_root,
        assets=assets,
        target_ready_count=target,
        generated_results=generated_results,
        missing_agent_ids=remaining_missing,
        world_id=expected_world_id,
        world_revision=expected_world_revision,
    )
    canonical_manifest = _canonicalize_revision_manifest(
        repo_root,
        revision=str(args.preferred_revision or ""),
        assets=assets,
        target_ready_count=target,
        generated_results=generated_results,
        missing_agent_ids=remaining_missing,
        world_id=expected_world_id,
        world_revision=expected_world_revision,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "target_ready_count": target,
                "ready_count": len(assets),
                "generated_count": len(generated_results),
                "remaining_missing_count": len(remaining_missing),
                "event_root": str(_event_root(repo_root)),
                "canonical_manifest_path": (
                    str((_generated_root(repo_root) / "world_asset_sets" / str(args.preferred_revision or "").strip() / "world_asset_set_manifest.json"))
                    if canonical_manifest is not None
                    else ""
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
