from __future__ import annotations
import json
import sqlite3
import json
from pathlib import Path
from typing import Any
from .world_definition import extract_structured_world_definition, sync_world_definition_into_config

def _resolve_existing_config_path(root: Path) -> Path | None:
    candidates = [
        root / "world_config.json",
        root / "run_inputs" / "world_config.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None

def _resolve_existing_scenario_dir(root: Path) -> Path | None:
    candidates = [
        root / "scenario",
        root / "run_inputs" / "scenario",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None

def _read_json_if_exists(path: Path) -> Any:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))

def _create_structured_definition_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS world_definition (
            world_id TEXT PRIMARY KEY,
            world_name TEXT NOT NULL,
            locale TEXT NOT NULL,
            tone TEXT NOT NULL,
            visual_direction TEXT NOT NULL,
            currency_code TEXT NOT NULL,
            currency_symbol TEXT NOT NULL,
            currency_minor_unit TEXT NOT NULL,
            currency_item_id TEXT NOT NULL,
            source_revision TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS room_definitions (
            room_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            name TEXT NOT NULL,
            archetype TEXT NOT NULL,
            purpose TEXT NOT NULL,
            decor_tags_json TEXT NOT NULL,
            activity_tags_json TEXT NOT NULL,
            entry_hints_json TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS role_definitions (
            role_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            role_name TEXT NOT NULL,
            count INTEGER NOT NULL,
            home_room_policy TEXT NOT NULL,
            activity TEXT NOT NULL,
            core_values_json TEXT NOT NULL,
            appearance_policy TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS item_taxonomy (
            taxonomy_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            label TEXT NOT NULL,
            description TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS item_catalog (
            item_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            taxonomy_id TEXT NOT NULL,
            name TEXT NOT NULL,
            price_minor INTEGER NOT NULL,
            tradeable INTEGER NOT NULL,
            needs_image INTEGER NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS generation_policies (
            policy_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS prompt_policies (
            policy_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pixel_kits (
            kit_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS frontend_affordances (
            affordance_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS asset_prompt_kits (
            kit_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS validation_reports (
            report_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS specialist_artifacts (
            artifact_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )


def _write_structured_world_definition(
    conn: sqlite3.Connection,
    *,
    source_root: Path,
) -> None:
    config_path = _resolve_existing_config_path(source_root)
    if config_path is None:
        return
    scenario_dir = _resolve_existing_scenario_dir(source_root)
    scenario_manifest = _read_json_if_exists(scenario_dir / "manifest.json") if scenario_dir is not None else {}
    config = sync_world_definition_into_config(json.loads(config_path.read_text(encoding="utf-8")))
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    structured = extract_structured_world_definition(config, scenario_manifest=scenario_manifest if isinstance(scenario_manifest, dict) else {})
    world_meta = dict(structured.get("world_definition", {}))
    world_id = str(world_meta.get("world_id", "")).strip()
    if not world_id:
        return
    conn.execute("DELETE FROM world_definition")
    conn.execute("DELETE FROM room_definitions")
    conn.execute("DELETE FROM role_definitions")
    conn.execute("DELETE FROM item_taxonomy")
    conn.execute("DELETE FROM item_catalog")
    conn.execute("DELETE FROM generation_policies")
    conn.execute("DELETE FROM prompt_policies")
    conn.execute("DELETE FROM pixel_kits")
    conn.execute("DELETE FROM frontend_affordances")
    conn.execute("DELETE FROM asset_prompt_kits")
    conn.execute("DELETE FROM validation_reports")
    conn.execute("DELETE FROM specialist_artifacts")
    conn.execute(
        """
        INSERT INTO world_definition(
            world_id, world_name, locale, tone, visual_direction,
            currency_code, currency_symbol, currency_minor_unit, currency_item_id,
            source_revision, payload_json
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            world_id,
            str(world_meta.get("world_name", "")),
            str(world_meta.get("locale", "")),
            str(world_meta.get("tone", "")),
            str(world_meta.get("visual_direction", "")),
            str(world_meta.get("currency_code", "")),
            str(world_meta.get("currency_symbol", "")),
            str(world_meta.get("currency_minor_unit", "")),
            str(world_meta.get("currency_item_id", "")),
            str(world_meta.get("source_revision", "")),
            json.dumps(world_meta, ensure_ascii=False),
        ),
    )
    for room in structured.get("room_definitions", []):
        if not isinstance(room, dict):
            continue
        room_id = str(room.get("room_id", "")).strip()
        if not room_id:
            continue
        conn.execute(
            """
            INSERT INTO room_definitions(
                room_id, world_id, name, archetype, purpose,
                decor_tags_json, activity_tags_json, entry_hints_json, payload_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                room_id,
                world_id,
                str(room.get("name", "")),
                str(room.get("archetype", "")),
                str(room.get("purpose", "")),
                json.dumps(room.get("decor_tags", []), ensure_ascii=False),
                json.dumps(room.get("activity_tags", []), ensure_ascii=False),
                json.dumps(room.get("entry_hints", []), ensure_ascii=False),
                json.dumps(room, ensure_ascii=False),
            ),
        )
    for role in structured.get("role_definitions", []):
        if not isinstance(role, dict):
            continue
        role_id = str(role.get("role_id", "")).strip()
        if not role_id:
            continue
        conn.execute(
            """
            INSERT INTO role_definitions(
                role_id, world_id, role_name, count, home_room_policy,
                activity, core_values_json, appearance_policy, payload_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                role_id,
                world_id,
                str(role.get("role_name", "")),
                int(role.get("count", 0) or 0),
                str(role.get("home_room_policy", "")),
                str(role.get("activity", "")),
                json.dumps(role.get("core_values", []), ensure_ascii=False),
                str(role.get("appearance_policy", "")),
                json.dumps(role, ensure_ascii=False),
            ),
        )
    for item in structured.get("item_taxonomy", []):
        if not isinstance(item, dict):
            continue
        taxonomy_id = str(item.get("taxonomy_id", "")).strip()
        if not taxonomy_id:
            continue
        conn.execute(
            """
            INSERT INTO item_taxonomy(
                taxonomy_id, world_id, label, description, tags_json, payload_json
            ) VALUES(?, ?, ?, ?, ?, ?)
            """,
            (
                taxonomy_id,
                world_id,
                str(item.get("label", "")),
                str(item.get("description", "")),
                json.dumps(item.get("tags", []), ensure_ascii=False),
                json.dumps(item, ensure_ascii=False),
            ),
        )
    for item in structured.get("item_catalog", []):
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("item_id", "")).strip()
        if not item_id:
            continue
        conn.execute(
            """
            INSERT INTO item_catalog(
                item_id, world_id, taxonomy_id, name, price_minor, tradeable, needs_image, payload_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                world_id,
                str(item.get("taxonomy_id", "")),
                str(item.get("name", "")),
                int(item.get("price_minor", 0) or 0),
                1 if bool(item.get("tradeable", False)) else 0,
                1 if bool(item.get("needs_image", False)) else 0,
                json.dumps(item, ensure_ascii=False),
            ),
        )
    for policy_id, payload in dict(structured.get("generation_policies", {})).items():
        conn.execute(
            "INSERT INTO generation_policies(policy_id, world_id, payload_json) VALUES(?, ?, ?)",
            (str(policy_id), world_id, json.dumps(payload, ensure_ascii=False)),
        )
    for policy_id, payload in dict(structured.get("prompt_policies", {})).items():
        conn.execute(
            "INSERT INTO prompt_policies(policy_id, world_id, payload_json) VALUES(?, ?, ?)",
            (str(policy_id), world_id, json.dumps(payload, ensure_ascii=False)),
        )
    pixel_kit_payload = structured.get("pixel_kits", {})
    if isinstance(pixel_kit_payload, dict) and pixel_kit_payload:
        conn.execute(
            "INSERT INTO pixel_kits(kit_id, world_id, payload_json) VALUES(?, ?, ?)",
            (str(pixel_kit_payload.get("pixel_component_kit_id", "pixel_component_kit")), world_id, json.dumps(pixel_kit_payload, ensure_ascii=False)),
        )
    frontend_payload = structured.get("frontend_affordances", {})
    if isinstance(frontend_payload, dict) and frontend_payload:
        conn.execute(
            "INSERT INTO frontend_affordances(affordance_id, world_id, payload_json) VALUES(?, ?, ?)",
            (str(frontend_payload.get("frontend_affordance_id", "frontend_affordance")), world_id, json.dumps(frontend_payload, ensure_ascii=False)),
        )
    asset_prompt_payload = structured.get("asset_prompt_kits", {})
    if isinstance(asset_prompt_payload, dict) and asset_prompt_payload:
        conn.execute(
            "INSERT INTO asset_prompt_kits(kit_id, world_id, payload_json) VALUES(?, ?, ?)",
            (str(asset_prompt_payload.get("asset_prompt_kit_id", "asset_prompt_kit")), world_id, json.dumps(asset_prompt_payload, ensure_ascii=False)),
        )
    for report_id, payload in dict(structured.get("validation_reports", {})).items():
        conn.execute(
            "INSERT INTO validation_reports(report_id, world_id, payload_json) VALUES(?, ?, ?)",
            (str(report_id), world_id, json.dumps(payload, ensure_ascii=False)),
        )
    for artifact_id, payload in dict(structured.get("specialist_artifacts", {})).items():
        conn.execute(
            "INSERT INTO specialist_artifacts(artifact_id, world_id, payload_json) VALUES(?, ?, ?)",
            (str(artifact_id), world_id, json.dumps(payload, ensure_ascii=False)),
        )


def read_structured_world_definition(path: Path | str) -> dict[str, Any]:
    candidate = Path(path)
    if not candidate.is_file():
        raise FileNotFoundError(f"package not found: {candidate}")
    with sqlite3.connect(candidate) as conn:
        conn.row_factory = sqlite3.Row
        tables = {
            str(row["name"])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        if "world_definition" not in tables:
            return {}
        world_row = conn.execute("SELECT payload_json FROM world_definition LIMIT 1").fetchone()
        if world_row is None:
            return {}
        payload = {
            "world_definition": json.loads(str(world_row["payload_json"])),
            "room_definitions": [],
            "role_definitions": [],
            "item_taxonomy": [],
            "item_catalog": [],
            "generation_policies": {},
            "prompt_policies": {},
            "pixel_kits": {},
            "frontend_affordances": {},
            "asset_prompt_kits": {},
            "validation_reports": {},
            "specialist_artifacts": {},
        }
        for row in conn.execute("SELECT payload_json FROM room_definitions ORDER BY room_id"):
            payload["room_definitions"].append(json.loads(str(row["payload_json"])))
        for row in conn.execute("SELECT payload_json FROM role_definitions ORDER BY role_id"):
            payload["role_definitions"].append(json.loads(str(row["payload_json"])))
        for row in conn.execute("SELECT payload_json FROM item_taxonomy ORDER BY taxonomy_id"):
            payload["item_taxonomy"].append(json.loads(str(row["payload_json"])))
        for row in conn.execute("SELECT payload_json FROM item_catalog ORDER BY item_id"):
            payload["item_catalog"].append(json.loads(str(row["payload_json"])))
        for row in conn.execute("SELECT policy_id, payload_json FROM generation_policies ORDER BY policy_id"):
            payload["generation_policies"][str(row["policy_id"])] = json.loads(str(row["payload_json"]))
        for row in conn.execute("SELECT policy_id, payload_json FROM prompt_policies ORDER BY policy_id"):
            payload["prompt_policies"][str(row["policy_id"])] = json.loads(str(row["payload_json"]))
        pixel_kit_row = conn.execute("SELECT payload_json FROM pixel_kits LIMIT 1").fetchone()
        if pixel_kit_row is not None:
            payload["pixel_kits"] = json.loads(str(pixel_kit_row["payload_json"]))
        frontend_row = conn.execute("SELECT payload_json FROM frontend_affordances LIMIT 1").fetchone()
        if frontend_row is not None:
            payload["frontend_affordances"] = json.loads(str(frontend_row["payload_json"]))
        asset_prompt_row = conn.execute("SELECT payload_json FROM asset_prompt_kits LIMIT 1").fetchone()
        if asset_prompt_row is not None:
            payload["asset_prompt_kits"] = json.loads(str(asset_prompt_row["payload_json"]))
        for row in conn.execute("SELECT report_id, payload_json FROM validation_reports ORDER BY report_id"):
            payload["validation_reports"][str(row["report_id"])] = json.loads(str(row["payload_json"]))
        for row in conn.execute("SELECT artifact_id, payload_json FROM specialist_artifacts ORDER BY artifact_id"):
            payload["specialist_artifacts"][str(row["artifact_id"])] = json.loads(str(row["payload_json"]))
    return payload

