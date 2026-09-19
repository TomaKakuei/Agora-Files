from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _first(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _status_flag(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "ok", "1"}:
            return True
        if lowered in {"false", "no", "failed", "0"}:
            return False
    return None


def _package_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for meta_path in sorted((root / "output" / "package_exports").glob("*/package_meta.json")):
        meta = _read_json(meta_path)
        if not meta:
            continue
        rows.append(
            {
                "access_code": _first(meta.get("access_code"), meta_path.parent.name),
                "package_name": _first(meta.get("package_name"), meta.get("world_name")),
                "world_id": _first(meta.get("world_id")),
                "source_label": _first(meta.get("source_label")),
                "pixel_read": _status_flag(meta.get("pixel_read")),
                "startup_ok": _status_flag(meta.get("startup_ok")),
                "created_at": _first(meta.get("created_at")),
                "draft_id": _first(meta.get("world_creator_draft_id"), meta.get("extra_meta", {}).get("world_creator_draft_id")),
                "revision_id": _first(meta.get("world_creator_revision"), meta.get("extra_meta", {}).get("world_creator_revision")),
                "path": str(meta_path),
            }
        )
    return rows


def _load_test_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for summary_path in sorted((root / "export_artifact" / "live_load_tests").glob("*/summary.json")):
        summary = _read_json(summary_path)
        if not summary:
            continue
        metrics = summary.get("metrics", {})
        rows.append(
            {
                "artifact_dir": _first(summary.get("artifact_dir"), summary_path.parent.name),
                "status": _first(summary.get("status")),
                "world_name": _first(summary.get("world_name")),
                "access_code": _first(summary.get("access_code")),
                "transport": _first(summary.get("transport")),
                "users_requested": summary.get("users_requested"),
                "users_created": summary.get("users_created"),
                "backend_stress_signal": summary.get("backend_stress_signal"),
                "create_session_p50_ms": metrics.get("create_session", {}).get("client_latency_ms", {}).get("p50"),
                "live_state_p50_ms": metrics.get("live_state", {}).get("client_latency_ms", {}).get("p50"),
                "live_action_p50_ms": metrics.get("live_action", {}).get("client_latency_ms", {}).get("p50"),
                "ws_connect_p50_ms": metrics.get("ws_connect", {}).get("client_latency_ms", {}).get("p50"),
                "ws_move_delta_p50_ms": metrics.get("ws_move_delta", {}).get("client_latency_ms", {}).get("p50"),
                "path": str(summary_path),
            }
        )
    return rows


def _draft_rows(root: Path, packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    package_by_draft = {
        (row.get("draft_id"), row.get("revision_id")): row
        for row in packages
        if row.get("draft_id") and row.get("revision_id")
    }
    rows: list[dict[str, Any]] = []
    for manifest_path in sorted((root / "output" / "world_creator_drafts").glob("*/draft_manifest.json")):
        manifest = _read_json(manifest_path)
        if not manifest:
            continue
        draft_id = _first(manifest.get("draft_id"), manifest_path.parent.name)
        revision_id = _first(manifest.get("current_revision"), "r001")
        revision_dir = manifest_path.parent / "revisions" / revision_id
        status = _read_json(revision_dir / "status.json")
        art_status = _read_json(revision_dir / "art_status.json")
        world_config_exists = (revision_dir / "world_config.json").is_file()
        package_db_exists = (revision_dir / "world_package.db").is_file()
        scenario_exists = (revision_dir / "scenario" / "manifest.json").is_file()
        package = package_by_draft.get((draft_id, revision_id), {})
        art_ok = str(manifest.get("art_status", "")).strip() == "publish_ready" or str(art_status.get("status", "")).strip() == "publish_ready"
        published = str(manifest.get("publish_status", "")).strip() == "published"
        publish_ready = str(manifest.get("status", "")).strip() == "publish_ready" or art_ok or published
        complete = bool(
            (published or publish_ready)
            and art_ok
            and (package_db_exists or package)
            and (package.get("pixel_read") is True or art_status.get("qa_summary", {}).get("pixel_read") is True)
            and (package.get("startup_ok") is True or art_status.get("backend_startup_validation", {}).get("startup_ok") is True)
        )
        missing: list[str] = []
        if not world_config_exists:
            missing.append("world_config")
        if not scenario_exists:
            missing.append("scenario")
        if not package_db_exists and not package:
            missing.append("package_db_or_export")
        if not art_ok:
            missing.append("art_publish_ready")
        if not published:
            missing.append("published_access_code")
        rows.append(
            {
                "draft_id": draft_id,
                "revision_id": revision_id,
                "world_name": _first(manifest.get("world_name"), status.get("world_name")),
                "manifest_status": _first(manifest.get("status")),
                "art_status": _first(manifest.get("art_status"), art_status.get("status")),
                "publish_status": _first(manifest.get("publish_status")),
                "published_access_code": _first(manifest.get("published_access_code"), package.get("access_code")),
                "world_config_exists": world_config_exists,
                "scenario_exists": scenario_exists,
                "package_db_exists": package_db_exists,
                "art_status_file_exists": (revision_dir / "art_status.json").is_file(),
                "art_pixel_read": art_status.get("qa_summary", {}).get("pixel_read"),
                "art_backend_startup_ok": art_status.get("backend_startup_validation", {}).get("startup_ok"),
                "art_pixel_launch_ok": art_status.get("pixel_launch_validation", {}).get("startup_ok"),
                "art_expected_access_code": _first(art_status.get("pixel_launch_validation", {}).get("expected_access_code")),
                "export_access_code": _first(package.get("access_code")),
                "export_pixel_read": package.get("pixel_read"),
                "export_startup_ok": package.get("startup_ok"),
                "complete_for_benchmark": complete,
                "missing_for_full_completion": missing,
                "recommended_next_action": _next_action(manifest, status, art_status, world_config_exists, package_db_exists, published),
                "manifest_path": str(manifest_path),
                "revision_dir": str(revision_dir),
            }
        )
    return rows


def _next_action(
    manifest: dict[str, Any],
    status: dict[str, Any],
    art_status: dict[str, Any],
    world_config_exists: bool,
    package_db_exists: bool,
    published: bool,
) -> str:
    if not world_config_exists:
        return "rerun_generation_worker"
    if art_status.get("status") == "art_failed":
        return "rerun_art_worker_or_debug_pixel_launch"
    if not art_status:
        return "run_art_worker"
    if str(art_status.get("status", "")).strip() == "publish_ready" and not published:
        return "publish_or_mark_package_ready"
    if package_db_exists and not published:
        return "publish"
    if published:
        return "runtime_evaluation"
    if status.get("status") == "draft_generating":
        return "inspect_generation_worker"
    return "inspect"


def _write_markdown(path: Path, manifest: dict[str, Any]) -> None:
    lines: list[str] = []
    summary = manifest["summary"]
    lines.append("# Agora 10-World Benchmark Manifest")
    lines.append("")
    lines.append(f"Generated: `{manifest['generated_at']}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    for key, value in summary.items():
        lines.append(f"- `{key}`: {value}")
    lines.append("")
    lines.append("## Current Creator Drafts")
    lines.append("")
    lines.append("| World | Draft | Status | Art | Publish | Complete | Next | Missing |")
    lines.append("| --- | --- | --- | --- | --- | ---: | --- | --- |")
    for row in manifest["drafts"]:
        missing = ", ".join(row["missing_for_full_completion"]) or "-"
        complete = "Y" if row["complete_for_benchmark"] else "N"
        lines.append(
            "| "
            + " | ".join(
                [
                    row["world_name"],
                    row["draft_id"],
                    row["manifest_status"],
                    row["art_status"],
                    row["publish_status"],
                    complete,
                    row["recommended_next_action"],
                    missing,
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## Valid Package Exports")
    lines.append("")
    lines.append("| Package | Access Code | Source | Pixel Read | Startup | Draft |")
    lines.append("| --- | --- | --- | ---: | ---: | --- |")
    for row in manifest["packages"]:
        lines.append(
            f"| {row['package_name']} | `{row['access_code']}` | {row['source_label']} | {row['pixel_read']} | {row['startup_ok']} | {row['draft_id']} |"
        )
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Agora 10-world benchmark status.")
    parser.add_argument("--repo-root", default=".", help="Agora 2.0 repository root")
    parser.add_argument("--out-dir", default="docs/benchmark_20260724", help="Output directory")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    out_dir = (root / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    packages = _package_rows(root)
    drafts = _draft_rows(root, packages)
    load_tests = _load_test_rows(root)
    summary = {
        "draft_count": len(drafts),
        "complete_or_package_ready_drafts": sum(1 for row in drafts if row["complete_for_benchmark"]),
        "published_current_drafts": sum(1 for row in drafts if row["publish_status"] == "published"),
        "valid_package_exports": sum(1 for row in packages if row["pixel_read"] is True and row["startup_ok"] is True),
        "load_test_summaries": len(load_tests),
        "needs_generation": sum(1 for row in drafts if row["recommended_next_action"] == "rerun_generation_worker"),
        "needs_art_or_art_repair": sum(1 for row in drafts if row["recommended_next_action"] in {"run_art_worker", "rerun_art_worker_or_debug_pixel_launch"}),
        "needs_publish": sum(1 for row in drafts if row["recommended_next_action"] in {"publish", "publish_or_mark_package_ready"}),
    }
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(root),
        "summary": summary,
        "drafts": drafts,
        "packages": packages,
        "load_tests": load_tests,
    }
    json_path = out_dir / "benchmark_manifest.json"
    md_path = out_dir / "benchmark_manifest.md"
    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_markdown(md_path, manifest)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
