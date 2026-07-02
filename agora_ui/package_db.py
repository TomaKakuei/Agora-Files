from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from .world_definition import extract_structured_world_definition
from .world_definition import sync_world_definition_into_config
from .package_schemas import *
from .package_schemas import _create_structured_definition_tables, _write_structured_world_definition, _resolve_existing_config_path, _resolve_existing_scenario_dir, _read_json_if_exists



PACKAGE_KIND = "agora_world_package"
PACKAGE_VERSION = 1
PIXEL_READ_META_KEY = "pixel_read"
PIXEL_READ_REPORT_META_KEY = "pixel_read_report"
MATERIALIZED_STAMP_FILENAME = ".agora_materialized_stamp.json"
DEFAULT_RUNTIME_PY_BIN = Path(sys.executable)


@dataclass
class MaterializedWorldPackage:
    package_path: Path
    root_dir: Path
    config_path: Path
    scenario_dir: Path
    _tempdir: tempfile.TemporaryDirectory[str]

    def cleanup(self) -> None:
        self._tempdir.cleanup()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_meta(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return str(row[0]) if row is not None else ""


def read_world_package_metadata(path: Path | str) -> dict[str, str]:
    candidate = Path(path)
    if not candidate.is_file():
        raise FileNotFoundError(f"package not found: {candidate}")
    with sqlite3.connect(candidate) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT key, value FROM meta ORDER BY key").fetchall()
    return {str(row["key"]): str(row["value"]) for row in rows}


def package_contains_paths(path: Path | str, required_paths: Iterable[str]) -> bool:
    candidate = Path(path)
    if not candidate.is_file():
        return False
    required = [str(entry or "").strip() for entry in required_paths if str(entry or "").strip()]
    if not required:
        return True
    with sqlite3.connect(candidate) as conn:
        conn.row_factory = sqlite3.Row
        present = {
            str(row["path"]): True
            for row in conn.execute(
                f"SELECT path FROM files WHERE path IN ({','.join('?' for _ in required)})",
                tuple(required),
            ).fetchall()
        }
    return all(present.get(path, False) for path in required)


def _package_db_materialize_stamp(package_db: Path) -> dict[str, str]:
    stat = package_db.stat()
    return {
        "package_db": str(package_db.resolve()),
        "mtime_ns": str(int(stat.st_mtime_ns)),
        "size": str(int(stat.st_size)),
    }


def _normalize_python_candidate(candidate: str | Path) -> str:
    raw = str(candidate or "").strip()
    if not raw:
        return ""
    expanded = Path(raw).expanduser()
    if expanded.is_file():
        return str(expanded.resolve())
    resolved = shutil.which(raw)
    return str(Path(resolved).resolve()) if resolved else ""


@lru_cache(maxsize=64)
def _python_supports_modules(python_bin: str, modules: tuple[str, ...]) -> bool:
    executable = _normalize_python_candidate(python_bin)
    if not executable:
        return False
    required = tuple(str(module).strip() for module in modules if str(module).strip())
    if not required:
        return True
    probe_lines = ["import importlib"] + [f"importlib.import_module({module!r})" for module in required]
    try:
        result = subprocess.run(
            [executable, "-c", "; ".join(probe_lines)],
            capture_output=True,
            text=True,
            timeout=15.0,
            check=False,
        )
    except Exception:
        return False
    return int(result.returncode) == 0


def resolve_runtime_python(
    preferred: str | Path = "",
    *,
    required_modules: Iterable[str] = (),
) -> str:
    modules = tuple(str(module).strip() for module in required_modules if str(module).strip())
    candidates: list[str] = []
    seen: set[str] = set()
    for entry in (
        preferred,
        os.environ.get("AGORA_RUNTIME_PYTHON", ""),
        os.environ.get("AGORA_PYTHON_BIN", ""),
        DEFAULT_RUNTIME_PY_BIN,
        sys.executable,
        "python3",
        "python",
    ):
        executable = _normalize_python_candidate(entry)
        if not executable or executable in seen:
            continue
        seen.add(executable)
        candidates.append(executable)
    for executable in candidates:
        if _python_supports_modules(executable, modules):
            return executable
    fallback = _normalize_python_candidate(sys.executable)
    if fallback:
        return fallback
    if candidates:
        return candidates[0]
    return str(Path(sys.executable))


def ensure_materialized_world_package(package_db: Path | str, *, output_dir: Path | str) -> Path:
    package_path = Path(package_db).resolve()
    target_root = Path(output_dir).resolve()
    stamp_path = target_root / MATERIALIZED_STAMP_FILENAME
    expected_stamp = _package_db_materialize_stamp(package_path)
    current_stamp: dict[str, Any] = {}
    if stamp_path.is_file():
        try:
            current_stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
        except Exception:
            current_stamp = {}
    if (
        current_stamp == expected_stamp
        and _resolve_existing_config_path(target_root) is not None
        and _resolve_existing_scenario_dir(target_root) is not None
    ):
        return target_root
    shutil.rmtree(target_root, ignore_errors=True)
    target_root.mkdir(parents=True, exist_ok=True)
    materialize_world_package(package_path, output_dir=target_root)
    stamp_path.write_text(json.dumps(expected_stamp, ensure_ascii=False, indent=2), encoding="utf-8")
    return target_root


def is_world_package_db(path: Path | str) -> bool:
    candidate = Path(path)
    if not candidate.is_file():
        return False
    if candidate.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
        return False
    try:
        with sqlite3.connect(candidate) as conn:
            conn.row_factory = sqlite3.Row
            kind = _read_meta(conn, "package_kind")
            version = _read_meta(conn, "package_version")
            return kind == PACKAGE_KIND and version == str(PACKAGE_VERSION)
    except Exception:
        return False


def is_world_package_pixel_read(path: Path | str) -> bool:
    try:
        meta = read_world_package_metadata(path)
    except Exception:
        return False
    value = str(meta.get(PIXEL_READ_META_KEY, "")).strip().lower()
    if value in {"1", "true", "yes", "ok"}:
        return True
    if value in {"0", "false", "no"}:
        return False
    return False


def _local_resource_path(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith(("http://", "https://", "data:", "blob:", "file://")):
        return ""
    parsed = urllib.parse.urlsplit(text)
    if parsed.scheme and parsed.netloc:
        return ""
    path = parsed.path or text
    if path.startswith("../") or "/../" in path:
        return ""
    while path.startswith("./"):
        path = path[2:]
    return path.lstrip("/")


def _resolve_relative_path(root: Path, value: str) -> Path | None:
    rel = _local_resource_path(value)
    if not rel:
        return None
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _candidate_resource_strings(*payloads: Any) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        if not isinstance(value, str):
            return
        normalized = value.strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        values.append(normalized)

    def walk(payload: Any) -> None:
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key in {"asset_set_manifest_path", "bootstrap_feed_path", "event_feed_path", "map_asset_url", "atlas_url", "json_url"}:
                    add(value)
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(payload, list):
            for item in payload:
                walk(item)

    for payload in payloads:
        walk(payload)
    return values








def _expected_asset_provenance(
    *,
    config: dict[str, Any],
    scenario_manifest: dict[str, Any] | None,
    asset_manifest: dict[str, Any] | None,
) -> tuple[str, str]:
    scenario_meta = scenario_manifest.get("scenario_meta", {}) if isinstance(scenario_manifest, dict) else {}
    config_meta = config.get("scenario_meta", {}) if isinstance(config.get("scenario_meta", {}), dict) else {}
    world_id = str(scenario_meta.get("world_id") or config_meta.get("world_id") or "").strip()
    world_revision = ""
    if isinstance(asset_manifest, dict):
        world_revision = str(asset_manifest.get("world_revision") or asset_manifest.get("revision") or "").strip()
    return world_id, world_revision


def _check_asset_event_provenance(
    payload: dict[str, Any],
    *,
    expected_world_id: str,
    expected_world_revision: str,
    label: str,
    details: list[str],
) -> bool:
    asset_world_id = str(payload.get("world_id", "")).strip()
    asset_world_revision = str(payload.get("world_revision") or payload.get("revision") or "").strip()
    okay = True
    if expected_world_id and asset_world_id != expected_world_id:
        details.append(f"{label}: world_id mismatch expected={expected_world_id} got={asset_world_id or 'missing'}")
        okay = False
    if expected_world_revision and asset_world_revision != expected_world_revision:
        details.append(f"{label}: world_revision mismatch expected={expected_world_revision} got={asset_world_revision or 'missing'}")
        okay = False
    return okay


def assess_pixel_readiness_from_root(root: Path | str) -> dict[str, Any]:
    source_root = Path(root).resolve()
    config_path = _resolve_existing_config_path(source_root)
    scenario_dir = _resolve_existing_scenario_dir(source_root)
    checked: list[str] = []
    missing: list[str] = []
    details: list[str] = []

    if config_path is None:
        missing.append("world_config.json")
        return {
            "pixel_read": False,
            "source_root": str(source_root),
            "checked_resources": checked,
            "missing_resources": missing,
            "details": details,
        }

    checked.append(str(config_path.relative_to(source_root)))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    scenario_manifest_payload = None
    if scenario_dir is None:
        missing.extend(["scenario/map_grid.json", "scenario/manifest.json"])
    else:
        for rel_name in ("map_grid.json", "manifest.json"):
            scenario_path = scenario_dir / rel_name
            rel = scenario_path.relative_to(source_root)
            checked.append(str(rel))
            if not scenario_path.is_file():
                missing.append(str(rel))
            elif rel_name == "manifest.json":
                scenario_manifest_payload = json.loads(scenario_path.read_text(encoding="utf-8"))

    frontend = dict(config.get("pixel_asset_pipeline", {}).get("frontend", {}))
    manifest_path = frontend.get("asset_set_manifest_path", "")
    bootstrap_path = frontend.get("bootstrap_feed_path", "")
    event_path = frontend.get("event_feed_path", "")
    map_asset_path = frontend.get("map_asset_url", "")

    manifest_payload = None
    bootstrap_payload = None
    latest_payload = None

    for label, candidate in (
        ("asset_set_manifest_path", manifest_path),
        ("bootstrap_feed_path", bootstrap_path),
        ("event_feed_path", event_path),
        ("map_asset_url", map_asset_path),
    ):
        resolved = _resolve_relative_path(source_root, str(candidate))
        if resolved is None:
            if str(candidate).strip():
                missing.append(str(candidate))
            continue
        rel = resolved.relative_to(source_root)
        checked.append(str(rel))
        if not resolved.is_file():
            missing.append(str(rel))
            continue
        if label == "asset_set_manifest_path":
            manifest_payload = json.loads(resolved.read_text(encoding="utf-8"))
        elif label == "bootstrap_feed_path":
            bootstrap_payload = json.loads(resolved.read_text(encoding="utf-8"))
        elif label == "event_feed_path":
            latest_payload = json.loads(resolved.read_text(encoding="utf-8"))

    for candidate in _candidate_resource_strings(manifest_payload, bootstrap_payload, latest_payload):
        resolved = _resolve_relative_path(source_root, candidate)
        if resolved is None:
            continue
        rel = resolved.relative_to(source_root)
        checked.append(str(rel))
        if not resolved.is_file():
            missing.append(str(rel))

    expected_world_id, expected_world_revision = _expected_asset_provenance(
        config=config,
        scenario_manifest=scenario_manifest_payload,
        asset_manifest=manifest_payload,
    )
    provenance_ok = True
    ready_asset_count = 0
    if isinstance(manifest_payload, dict):
        provenance_ok = _check_asset_event_provenance(
            manifest_payload,
            expected_world_id=expected_world_id,
            expected_world_revision=expected_world_revision,
            label="asset_set_manifest",
            details=details,
        ) and provenance_ok
    asset_groups: list[tuple[str, list[dict[str, Any]]]] = []
    if isinstance(manifest_payload, dict) and isinstance(manifest_payload.get("assets", []), list):
        asset_groups.append(("asset_set_manifest.assets", [entry for entry in manifest_payload.get("assets", []) if isinstance(entry, dict)]))
    if isinstance(bootstrap_payload, dict) and isinstance(bootstrap_payload.get("assets", []), list):
        asset_groups.append(("bootstrap_feed.assets", [entry for entry in bootstrap_payload.get("assets", []) if isinstance(entry, dict)]))
    if isinstance(latest_payload, dict) and latest_payload:
        asset_groups.append(("event_feed.latest", [latest_payload]))
    for label, assets in asset_groups:
        for index, asset in enumerate(assets, start=1):
            if _check_asset_event_provenance(
                asset,
                expected_world_id=expected_world_id,
                expected_world_revision=expected_world_revision,
                label=f"{label}[{index}]",
                details=details,
            ):
                ready_asset_count += 1
            else:
                provenance_ok = False
    coverage_ok = ready_asset_count > 0
    if not coverage_ok:
        details.append("no provenance-valid ready assets were found")

    pixel_read = not missing and provenance_ok and coverage_ok
    return {
        "pixel_read": pixel_read,
        "source_root": str(source_root),
        "checked_resources": checked,
        "missing_resources": missing,
        "details": details,
        "expected_world_id": expected_world_id,
        "expected_world_revision": expected_world_revision,
    }


def _iter_source_files(source_root: Path, *, skip_paths: set[Path] | None = None) -> Iterable[Path]:
    skip = {path.resolve() for path in (skip_paths or set())}
    for path in sorted(source_root.rglob("*")):
        if not path.is_file():
            continue
        if path.resolve() in skip:
            continue
        if "__pycache__" in path.parts:
            continue
        if path.suffix.lower() == ".pyc":
            continue
        if path.name in {".DS_Store"}:
            continue
        yield path


def pack_world_package(
    source_root: Path | str,
    output_db: Path | str,
    *,
    package_name: str = "",
    source_label: str = "",
    extra_meta: dict[str, Any] | None = None,
) -> Path:
    source_root = Path(source_root).resolve()
    output_db = Path(output_db).resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"source root not found: {source_root}")
    output_db.parent.mkdir(parents=True, exist_ok=True)
    if output_db.exists():
        output_db.unlink()

    temp_handle = tempfile.NamedTemporaryFile(suffix=".db", dir=str(source_root.parent), delete=False)
    temp_path = Path(temp_handle.name)
    temp_handle.close()
    try:
        with sqlite3.connect(temp_path) as conn:
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY,
                    size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    content BLOB NOT NULL
                )
                """
            )
            _create_structured_definition_tables(conn)
            conn.execute("DELETE FROM meta")
            conn.execute("DELETE FROM files")
            meta = {
                "package_kind": PACKAGE_KIND,
                "package_version": str(PACKAGE_VERSION),
                "created_at": _now_iso(),
                "source_root": str(source_root),
                "package_name": package_name or source_root.name,
                "source_label": source_label or source_root.name,
            }
            if extra_meta:
                for key, value in extra_meta.items():
                    if value is None:
                        continue
                    if isinstance(value, bool):
                        meta[str(key)] = "true" if value else "false"
                    else:
                        meta[str(key)] = str(value)
            conn.executemany(
                "INSERT INTO meta(key, value) VALUES(?, ?)",
                list(meta.items()),
            )
            rows: list[tuple[str, int, str, bytes]] = []
            skip_paths = {output_db} if output_db.is_relative_to(source_root) else set()
            for file_path in _iter_source_files(source_root, skip_paths=skip_paths):
                relative_path = file_path.relative_to(source_root).as_posix()
                payload = file_path.read_bytes()
                rows.append(
                    (
                        relative_path,
                        len(payload),
                        hashlib.sha256(payload).hexdigest(),
                        payload,
                    )
                )
            conn.executemany(
                "INSERT INTO files(path, size, sha256, content) VALUES(?, ?, ?, ?)",
                rows,
            )
            _write_structured_world_definition(conn, source_root=source_root)
            conn.commit()
        os.replace(temp_path, output_db)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return output_db


def materialize_world_package(
    package_db: Path | str,
    *,
    output_dir: Path | str | None = None,
) -> MaterializedWorldPackage:
    package_db = Path(package_db).resolve()
    if not is_world_package_db(package_db):
        raise ValueError(f"not a world package db: {package_db}")

    tempdir = tempfile.TemporaryDirectory(prefix="agora_world_package_")
    root_dir = Path(output_dir).resolve() if output_dir is not None else Path(tempdir.name)
    root_dir.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(package_db) as conn:
        conn.row_factory = sqlite3.Row
        for row in conn.execute("SELECT path, content FROM files ORDER BY path"):
            relative_path = str(row["path"])
            target_path = root_dir / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(bytes(row["content"]))
        structured = read_structured_world_definition(package_db)
        if structured:
            world_definition_path = root_dir / "world_definition.json"
            world_definition_path.write_text(json.dumps(structured, ensure_ascii=False, indent=2), encoding="utf-8")

    config_path = root_dir / "world_config.json"
    scenario_dir = root_dir / "scenario"
    if not config_path.is_file() and (root_dir / "run_inputs" / "world_config.json").is_file():
        config_path = root_dir / "run_inputs" / "world_config.json"
    if not scenario_dir.is_dir() and (root_dir / "run_inputs" / "scenario").is_dir():
        scenario_dir = root_dir / "run_inputs" / "scenario"
    if config_path.is_file():
        try:
            config = sync_world_definition_into_config(json.loads(config_path.read_text(encoding="utf-8")))
            config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    return MaterializedWorldPackage(
        package_path=package_db,
        root_dir=root_dir,
        config_path=config_path,
        scenario_dir=scenario_dir,
        _tempdir=tempdir,
    )


def validate_world_package_startup(
    package_root: Path | str,
    access_code: str,
    *,
    display_name: str = "Startup Smoke Test",
    room_id: str = "",
    speed_seconds_per_round: float = 6.0,
) -> dict[str, Any]:
    package_root = Path(package_root).resolve()
    normalized = str(access_code or "").strip()
    export_dir = (package_root / "output" / "package_exports" / normalized).resolve()
    package_db = export_dir / "world_package.db"
    report: dict[str, Any] = {
        "startup_ok": False,
        "package_root": str(package_root),
        "access_code": normalized,
        "export_dir": str(export_dir),
        "package_db": str(package_db),
        "stage": "init",
        "session_id": "",
        "world_name": "",
        "world_id": "",
        "agent_count": 0,
        "live_ready_count": 0,
        "world_revision": 0,
        "error": "",
    }
    if not normalized:
        report["stage"] = "access_code"
        report["error"] = "access_code is required"
        return report
    if not package_db.is_file():
        report["stage"] = "package_db"
        report["error"] = f"package not found: {normalized}"
        return report

    live_state_path = export_dir / "live_state.db"
    live_snapshot_path = export_dir / "live_snapshot.json"
    live_snapshot_meta_path = export_dir / "live_snapshot.meta.json"
    for path in (live_state_path, live_snapshot_path, live_snapshot_meta_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass

    session_id = ""
    try:
        from .live_world import get_pixel_live_store, load_pixel_world_context

        context = load_pixel_world_context(str(package_root), normalized)
        report["stage"] = "context"
        report["world_name"] = str(context.config.get("scenario_meta", {}).get("world_name", ""))
        report["world_id"] = str(context.config.get("scenario_meta", {}).get("world_id", ""))
        store = get_pixel_live_store(str(package_root), normalized)
        report["stage"] = "snapshot"
        store.ensure_initialized()
        with store._connect() as conn:  # noqa: SLF001
            snapshot = store._build_hot_world_snapshot(conn)  # noqa: SLF001
        report["agent_count"] = int(len(snapshot.get("agents", [])) if isinstance(snapshot.get("agents", []), list) else 0)
        report["live_ready_count"] = int(snapshot.get("live_ready_count", 0) or 0)
        report["world_revision"] = int(snapshot.get("world_revision", 0) or 0)
        report["world_name"] = str(snapshot.get("world_name", report["world_name"]))
        report["world_id"] = str(snapshot.get("world_id", report["world_id"]))
        report["startup_ok"] = True
        report["stage"] = "ok"
        return report
    except Exception as exc:
        report["error"] = str(exc)
        return report


def _last_json_object(text: str) -> dict[str, Any]:
    source = str(text or "")
    if not source:
        return {}
    decoder = json.JSONDecoder()
    last_payload: dict[str, Any] = {}
    last_end = -1
    for index, char in enumerate(source):
        if char != "{":
            continue
        try:
            payload, end = decoder.raw_decode(source[index:])
        except Exception:
            continue
        absolute_end = index + int(end)
        if isinstance(payload, dict) and absolute_end >= last_end:
            last_payload = payload
            last_end = absolute_end
    return last_payload


def validate_pixel_ui_launch(
    package_root: Path | str,
    access_code: str,
    *,
    seed: int = 42627,
    port: int = 8125,
    timeout_seconds: float = 300.0,
    firefox_binary: str = "",
    python_executable: str = "",
) -> dict[str, Any]:
    package_root = Path(package_root).resolve()
    normalized = str(access_code or "").strip()
    export_dir = (package_root / "output" / "package_exports" / normalized).resolve()
    package_db = export_dir / "world_package.db"
    report: dict[str, Any] = {
        "startup_ok": False,
        "package_root": str(package_root),
        "access_code": normalized,
        "expected_access_code": normalized,
        "selected_access_code": "",
        "package_db": str(package_db),
        "stage": "init",
        "startup_status_text": "",
        "session_endpoint": "",
        "screenshot_path": "",
        "returncode": 0,
        "command": [],
        "error": "",
    }
    if not normalized:
        report["stage"] = "access_code"
        report["error"] = "access_code is required"
        return report
    if not package_db.is_file():
        report["stage"] = "package_db"
        report["error"] = f"package not found: {normalized}"
        return report

    script_path = package_root / "scripts" / "headless_pixel_firefox_regression.py"
    if not script_path.is_file():
        report["stage"] = "script"
        report["error"] = f"headless regression script not found: {script_path}"
        return report

    py_bin = resolve_runtime_python(
        python_executable,
        required_modules=("uvicorn",),
    )
    command = [
        py_bin,
        str(script_path),
        "--seed",
        str(max(1, int(seed or 42627))),
        "--port",
        str(max(1, int(port or 8125))),
        "--access-code",
        normalized,
    ]
    report["command"] = list(command)

    env = dict(os.environ)
    env["AGORA_PIXEL_PYTHON"] = py_bin
    env["AGORA_MACRO_PACKAGE_ROOT"] = str(package_root)
    if str(firefox_binary or "").strip():
        env["FIREFOX_BINARY"] = str(firefox_binary).strip()

    try:
        result = subprocess.run(
            command,
            cwd=str(package_root),
            capture_output=True,
            text=True,
            timeout=max(30.0, float(timeout_seconds)),
            env=env,
            check=False,
        )
    except FileNotFoundError as exc:
        report["stage"] = "subprocess"
        report["error"] = str(exc)
        return report
    except subprocess.TimeoutExpired as exc:
        report["stage"] = "timeout"
        report["error"] = str(exc)
        return report
    except Exception as exc:
        report["stage"] = "subprocess"
        report["error"] = str(exc)
        return report

    report["returncode"] = int(result.returncode)
    print("STDOUT: ", result.stdout)
    print("STDERR: ", result.stderr)
    payload = _last_json_object(result.stdout) or _last_json_object(result.stderr)
    result_payload = payload.get("result", {}) if isinstance(payload.get("result", {}), dict) else {}
    selected_access_code = str(
        result_payload.get("selected_access_code")
        or payload.get("selected_access_code")
        or result_payload.get("access_code")
        or payload.get("access_code")
        or ""
    ).strip()
    report["selected_access_code"] = selected_access_code
    report["startup_status_text"] = str(
        result_payload.get("startup_status_text")
        or payload.get("startup_status_text")
        or payload.get("ready_text")
        or payload.get("message")
        or ""
    ).strip()
    report["session_endpoint"] = str(
        result_payload.get("session_endpoint")
        or payload.get("session_endpoint")
        or ""
    ).strip()
    report["screenshot_path"] = str(payload.get("screenshot", "")).strip()

    if int(result.returncode) == 0:
        report["startup_ok"] = True
        report["stage"] = "ok"
        report["error"] = ""
        return report

    report["stage"] = str(payload.get("stage", "")).strip() or "pixel_launch"
    report["error"] = str(payload.get("message", "") or payload.get("error", "") or result.stderr or result.stdout).strip()
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pack or unpack an Agora world package SQLite DB.")
    sub = parser.add_subparsers(dest="command", required=True)

    pack = sub.add_parser("pack", help="Pack a source directory into a world-package DB.")
    pack.add_argument("--source-root", type=Path, required=True)
    pack.add_argument("--output-db", type=Path, required=True)
    pack.add_argument("--package-name", type=str, default="")
    pack.add_argument("--source-label", type=str, default="")

    extract = sub.add_parser("extract", help="Extract a world-package DB to a directory.")
    extract.add_argument("--package-db", type=Path, required=True)
    extract.add_argument("--output-dir", type=Path, required=True)

    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.command == "pack":
        pack_world_package(
            args.source_root,
            args.output_db,
            package_name=str(args.package_name),
            source_label=str(args.source_label),
        )
        print(json.dumps({"status": "ok", "package_db": str(Path(args.output_db).resolve())}, indent=2))
        return
    package = materialize_world_package(args.package_db, output_dir=args.output_dir)
    print(
        json.dumps(
            {
                "status": "ok",
                "package_db": str(package.package_path),
                "output_dir": str(package.root_dir),
                "config_path": str(package.config_path),
                "scenario_dir": str(package.scenario_dir),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
