from __future__ import annotations

import importlib.util
import json
import sqlite3
import shutil
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from macro_ui import serve_macro_ui
from agora_ui.live_world import shutdown_registered_live_stores


ROOT = Path(__file__).resolve().parents[1]
HEADLESS_PIXEL_SCRIPT = ROOT / "scripts" / "headless_pixel_firefox_regression.py"


class _LiveReplyClient:
    def __init__(self, config: dict) -> None:
        self.config = config

    def generate_json(self, **_: dict) -> dict:
        return {
            "response_text": "The target lowers their voice and names a fresh plan for the next room.",
            "target_focus": "chooses a fresh plan",
            "actor_focus": "waits for the next step",
        }


class _LiveToolReplyClient:
    def __init__(self, config: dict) -> None:
        self.config = config

    def generate_json(self, **_: dict) -> dict:
        return {
            "response_text": "The target nods once and falls into step beside the human.",
            "target_focus": "starts following the human",
            "actor_focus": "leads the way",
            "tool_call": {
                "tool_name": "follow_me",
                "reason": "human requested direct escort",
            },
        }


class _LiveRouteTradeReplyClient:
    def __init__(self, config: dict) -> None:
        self.config = config

    def generate_json(self, **_: dict) -> dict:
        return {
            "response_text": "The target glances at the crystal case and names a fair guild price.",
            "target_focus": "offers a priced trade",
            "actor_focus": "considers the quoted trade",
            "route_selection": {
                "route_id": "trade_supplies",
                "kind": "item_trade",
                "reason": "the human is asking to buy an item",
                "item_id": "mana_crystal",
                "quantity": 1,
            },
        }


class _LiveEmptyThenValidReplyClient:
    attempts = 0

    def __init__(self, config: dict) -> None:
        self.config = config

    def generate_json(self, **_: dict) -> dict:
        type(self).attempts += 1
        if type(self).attempts == 1:
            return {
                "response_text": "",
                "target_focus": "",
                "actor_focus": "",
            }
        return {
            "response_text": "The target answers on the retry and points to the next useful step.",
            "target_focus": "answers on the retry",
            "actor_focus": "waits through the retry",
        }


def _first_pixel_world_access_code() -> str:
    export_root = ROOT / "output" / "package_exports"
    for package_db in sorted(export_root.glob("*/world_package.db")):
        access_code = package_db.parent.name
        if serve_macro_ui._canonical_pixel_world_record(access_code) is not None:
            return access_code
    raise AssertionError("No PIXEL READ package export available for live tests")


def _copy_package_export(src_access_code: str, temp_root: Path) -> None:
    source_db = ROOT / "output" / "package_exports" / src_access_code / "world_package.db"
    if not source_db.is_file():
        raise AssertionError(f"Missing source package export: {source_db}")
    target_dir = temp_root / "output" / "package_exports" / src_access_code
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_db, target_dir / "world_package.db")


class PixelLiveWorldApiTest(unittest.TestCase):
    def tearDown(self) -> None:
        shutdown_registered_live_stores()

    def _assert_server_timing(self, payload: dict) -> None:
        timing = payload.get("timing")
        self.assertIsInstance(timing, dict)
        self.assertGreater(int(timing.get("server_elapsed_ms", 0) or 0), 0)

    @contextmanager
    def _live_temp_root(self, access_code: str):
        with TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            _copy_package_export(access_code, temp_root)
            try:
                yield temp_root
            finally:
                shutdown_registered_live_stores()

    def _advance_world(self, package_root: Path, access_code: str, *, session_id: str = "") -> None:
        store = serve_macro_ui.get_pixel_live_store(str(package_root), access_code)
        store.advance_world(force=True, preferred_session_id=session_id)

    def _wait_for_live_condition(
        self,
        package_root: Path,
        access_code: str,
        *,
        session_id: str,
        predicate,
        timeout_seconds: float = 5.0,
    ) -> dict:
        store = serve_macro_ui.get_pixel_live_store(str(package_root), access_code)
        deadline = time.time() + max(0.5, float(timeout_seconds))
        last_payload: dict | None = None
        while time.time() < deadline:
            store.wait_for_background_idle(timeout_seconds=0.25)
            payload = serve_macro_ui.api_live_state(
                access_code,
                session_id=session_id,
                since=0,
            )
            last_payload = payload
            if predicate(payload):
                return payload
            time.sleep(0.05)
        self.fail(f"Timed out waiting for live condition. Last payload latest_event_id={last_payload.get('latest_event_id') if isinstance(last_payload, dict) else 'n/a'}")

    def _force_live_tick(self, live_db: Path) -> None:
        with sqlite3.connect(live_db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT room_id, state_json FROM rooms").fetchall()
            for row in rows:
                state = json.loads(str(row["state_json"] or "{}"))
                if not isinstance(state, dict):
                    state = {}
                state["last_live_tick_at"] = "1970-01-01T00:00:00Z"
                conn.execute(
                    "UPDATE rooms SET state_json = ? WHERE room_id = ?",
                    (json.dumps(state), str(row["room_id"])),
                )
            conn.commit()

    def _room_distance_guess(self, room: dict, origin: dict[str, int]) -> int:
        footprint = room.get("footprint_tiles", []) if isinstance(room.get("footprint_tiles", []), list) else []
        if footprint:
            return min(
                abs(int(tile.get("x", 0)) - int(origin.get("x", 0))) + abs(int(tile.get("y", 0)) - int(origin.get("y", 0)))
                for tile in footprint
                if isinstance(tile, dict)
            )
        return abs(int(room.get("x", 0)) - int(origin.get("x", 0))) + abs(int(room.get("y", 0)) - int(origin.get("y", 0)))

    def test_live_session_flow_claims_agent_and_persists_actions(self) -> None:
        access_code = _first_pixel_world_access_code()
        world_record = serve_macro_ui._pixel_world_record(access_code)
        self.assertIsNotNone(world_record)
        self.assertIn("seed", world_record or {})
        with self._live_temp_root(access_code) as temp_root:
            with (
                patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root),
                patch.dict("os.environ", {"AGORA_AISTUDIO_API_KEY": "test-key"}, clear=False),
                patch("agora_ui.live_world._load_vertex_json_client_class", return_value=_LiveReplyClient),
            ):
                create_payload = serve_macro_ui.api_create_live_session(
                    access_code,
                    serve_macro_ui.PixelLiveSessionCreateRequest(
                        display_name="Live Tester",
                        room_id="",
                        speed_seconds_per_round=8.0,
                    ),
                )
                session = create_payload["session"]
                state = create_payload["state"]
                self._assert_server_timing(create_payload)
                self.assertEqual(session["session_id"], state["session"]["session_id"])
                self.assertGreater(len(state["agents"]), 0)
                self.assertGreaterEqual(state["latest_event_id"], 0)

                claimed_agent_id = state["session"]["claimed_agent_id"]
                room_id = state["room"]["room_id"]
                room_agents = [agent for agent in state["active_room_agents"] if agent["room_id"] == room_id]
                self.assertTrue(any(agent["agent_id"] == claimed_agent_id for agent in room_agents))

                target_agent = next(
                    (
                        agent
                        for agent in state["agents"]
                        if agent["room_id"] == room_id and agent["agent_id"] != claimed_agent_id
                    ),
                    None,
                )

                message_response = serve_macro_ui.api_live_action(
                    access_code,
                    serve_macro_ui.PixelLiveActionRequest(
                        session_id=session["session_id"],
                        action_type="message",
                        action_text="Hello from the live session",
                        target_agent_id=target_agent["agent_id"] if target_agent else "",
                    ),
                )
                self._assert_server_timing(message_response)
                self.assertEqual(message_response["status"], "accepted")
                message_state = self._wait_for_live_condition(
                    temp_root,
                    access_code,
                    session_id=session["session_id"],
                    predicate=lambda payload: any(event["event_type"] == "agent_response" for event in payload["events"]),
                )
                self.assertGreaterEqual(message_state["latest_event_id"], state["latest_event_id"])
                self.assertTrue(message_state["events"])

                move_response = serve_macro_ui.api_live_action(
                    access_code,
                    serve_macro_ui.PixelLiveActionRequest(
                        session_id=session["session_id"],
                        action_type="move",
                        client_action_id="test_move_async_01",
                        direction="right",
                        action_text="Move right",
                    ),
                )
                self._assert_server_timing(move_response)
                self.assertEqual(move_response["status"], "accepted")
                move_state = self._wait_for_live_condition(
                    temp_root,
                    access_code,
                    session_id=session["session_id"],
                    predicate=lambda payload: any(
                        event["event_type"] == "human_action"
                        and json.loads(str(event.get("payload_json") or "{}")).get("client_action_id") == "test_move_async_01"
                        for event in payload["events"]
                    ),
                )
                self.assertGreaterEqual(move_state["latest_event_id"], message_state["latest_event_id"])
                self.assertTrue(move_state["session"]["room_id"])

                heartbeat_response = serve_macro_ui.api_live_session_heartbeat(access_code, session["session_id"])
                self._assert_server_timing(heartbeat_response)
                self.assertEqual(heartbeat_response["status"], "ok")
                self.assertEqual(heartbeat_response["state"]["session"]["session_id"], session["session_id"])

                poll_response = serve_macro_ui.api_live_state(
                    access_code,
                    session_id=session["session_id"],
                    since=message_state["latest_event_id"],
                )
                self._assert_server_timing(poll_response)
                self.assertGreaterEqual(poll_response["latest_event_id"], move_state["latest_event_id"])

                release_response = serve_macro_ui.api_live_session_release(access_code, session["session_id"])
                self.assertEqual(release_response["status"], "ok")

                with self.assertRaises(serve_macro_ui.HTTPException):
                    serve_macro_ui.api_live_state(
                        access_code,
                        session_id=session["session_id"],
                        since=0,
                    )

    def test_api_pixel_world_detail_exposes_top_level_contract(self) -> None:
        access_code = _first_pixel_world_access_code()
        with self._live_temp_root(access_code) as temp_root:
            with patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root):
                payload = serve_macro_ui.api_pixel_world(access_code)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["access_code"], access_code)
        self.assertTrue(str(payload["world_name"]).strip())
        self.assertTrue(str(payload["world_id"]).strip())
        self.assertTrue(str(payload["live_session_url"]).endswith(f"/api/pixel/worlds/{access_code}/live/sessions"))
        self.assertIsInstance(payload.get("package"), dict)
        self.assertEqual(str(payload["package"].get("access_code", "")), access_code)

    def test_headless_pixel_harness_targets_requested_world_and_resets_client_state(self) -> None:
        html = serve_macro_ui._render_headless_pixel_harness(42627, "token1234", "83a27fc6b177b058")
        self.assertIn("pixel_world=83a27fc6b177b058", html)
        self.assertIn("persist_session=0", html)
        self.assertIn("reset_client_state=1", html)
        self.assertIn("expected_session_endpoint", html)
        self.assertIn("selected_access_code", html)
        self.assertIn("session_endpoint", html)
        self.assertIn("startup_status_text", html)

    def test_headless_regression_access_code_lookup_accepts_world_detail_payload(self) -> None:
        spec = importlib.util.spec_from_file_location("headless_pixel_firefox_regression", HEADLESS_PIXEL_SCRIPT)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        access_code = "83a27fc6b177b058"
        payload = {
            "status": "ok",
            "access_code": access_code,
            "world_name": "Panjiayuan",
            "world_id": "panjiayuan",
            "live_session_url": f"/api/pixel/worlds/{access_code}/live/sessions",
            "package": {
                "access_code": access_code,
                "world_name": "Panjiayuan",
                "world_id": "panjiayuan",
            },
        }
        with patch.object(module, "_read_json", return_value=payload):
            record = module._pick_world_by_access_code("http://127.0.0.1:8125", access_code)
        self.assertEqual(record["access_code"], access_code)
        self.assertEqual(record["world_name"], "Panjiayuan")
        self.assertEqual(record["world_id"], "panjiayuan")

    def test_headless_regression_seed_lookup_prefers_latest_match(self) -> None:
        spec = importlib.util.spec_from_file_location("headless_pixel_firefox_regression", HEADLESS_PIXEL_SCRIPT)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        payload = {
            "worlds": [
                {
                    "access_code": "1111111111111111",
                    "seed": 17,
                    "created_at": "2026-05-28T00:00:00+00:00",
                },
                {
                    "access_code": "2222222222222222",
                    "seed": 17,
                    "created_at": "2026-05-29T00:00:00+00:00",
                },
                {
                    "access_code": "3333333333333333",
                    "seed": 18,
                    "created_at": "2026-05-30T00:00:00+00:00",
                },
            ]
        }
        with patch.object(module, "_read_json", return_value=payload):
            record = module._pick_world_for_seed("http://127.0.0.1:8125", 17)
        self.assertEqual(record["access_code"], "2222222222222222")

    def test_live_item_and_trade_actions_persist_inventory(self) -> None:
        access_code = _first_pixel_world_access_code()
        with self._live_temp_root(access_code) as temp_root:
            with patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root):
                create_payload = serve_macro_ui.api_create_live_session(
                    access_code,
                    serve_macro_ui.PixelLiveSessionCreateRequest(
                        display_name="Inventory Tester",
                        room_id="",
                        speed_seconds_per_round=8.0,
                    ),
                )
                session = create_payload["session"]
                claimed_agent_id = session["claimed_agent_id"]
                room_id = session["room_id"]
                target_agent = next(
                    agent
                    for agent in create_payload["state"]["agents"]
                    if agent["room_id"] == room_id and agent["agent_id"] != claimed_agent_id
                )

                live_db = temp_root / "output" / "package_exports" / access_code / "live_state.db"
                with sqlite3.connect(live_db) as conn:
                    actor_row = conn.execute("SELECT state_json FROM agents WHERE agent_id = ?", (claimed_agent_id,)).fetchone()
                    target_row = conn.execute("SELECT state_json FROM agents WHERE agent_id = ?", (target_agent["agent_id"],)).fetchone()
                    actor_state = json.loads(actor_row[0])
                    target_state = json.loads(target_row[0])
                    actor_state["inventory"] = [
                        {"item_id": "healing_potion", "quantity": 2, "name": "Healing Potion", "description": "Restores stamina."}
                    ]
                    target_state["inventory"] = [
                        {"item_id": "mana_crystal", "quantity": 1, "name": "Mana Crystal", "description": "Arcane reagent."}
                    ]
                    conn.execute("UPDATE agents SET state_json = ? WHERE agent_id = ?", (json.dumps(actor_state), claimed_agent_id))
                    conn.execute("UPDATE agents SET state_json = ? WHERE agent_id = ?", (json.dumps(target_state), target_agent["agent_id"]))
                    conn.commit()

                item_response = serve_macro_ui.api_live_action(
                    access_code,
                    serve_macro_ui.PixelLiveActionRequest(
                        session_id=session["session_id"],
                        action_type="use_item",
                        item_id="healing_potion",
                        quantity=1,
                        action_text="Use potion",
                    ),
                )
                actor_after_item = next(agent for agent in item_response["state"]["agents"] if agent["agent_id"] == claimed_agent_id)
                self.assertEqual(actor_after_item["inventory"][0]["item_id"], "healing_potion")
                self.assertEqual(actor_after_item["inventory"][0]["quantity"], 1)

                trade_response = serve_macro_ui.api_live_action(
                    access_code,
                    serve_macro_ui.PixelLiveActionRequest(
                        session_id=session["session_id"],
                        action_type="trade_item",
                        item_id="healing_potion",
                        return_item_id="mana_crystal",
                        target_agent_id=target_agent["agent_id"],
                        quantity=1,
                        action_text="Swap potion for crystal",
                    ),
                )
                actor_after_trade = next(agent for agent in trade_response["state"]["agents"] if agent["agent_id"] == claimed_agent_id)
                target_after_trade = next(agent for agent in trade_response["state"]["agents"] if agent["agent_id"] == target_agent["agent_id"])
                self.assertTrue(any(entry["item_id"] == "mana_crystal" and entry["quantity"] == 1 for entry in actor_after_trade["inventory"]))
                self.assertFalse(any(entry["item_id"] == "healing_potion" and entry["quantity"] > 0 for entry in actor_after_trade["inventory"]))
                self.assertTrue(any(entry["item_id"] == "healing_potion" and entry["quantity"] == 1 for entry in target_after_trade["inventory"]))

    def test_live_duplicate_client_action_id_is_idempotent(self) -> None:
        access_code = _first_pixel_world_access_code()
        with self._live_temp_root(access_code) as temp_root:
            with patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root):
                create_payload = serve_macro_ui.api_create_live_session(
                    access_code,
                    serve_macro_ui.PixelLiveSessionCreateRequest(
                        display_name="Dedup Tester",
                        room_id="",
                        speed_seconds_per_round=8.0,
                    ),
                )
                session = create_payload["session"]
                live_db = temp_root / "output" / "package_exports" / access_code / "live_state.db"
                client_action_id = "dedupe_move_async_01"

                first_response = serve_macro_ui.api_live_action(
                    access_code,
                    serve_macro_ui.PixelLiveActionRequest(
                        session_id=session["session_id"],
                        action_type="move",
                        client_action_id=client_action_id,
                        direction="right",
                        action_text="Move right once",
                    ),
                )
                second_response = serve_macro_ui.api_live_action(
                    access_code,
                    serve_macro_ui.PixelLiveActionRequest(
                        session_id=session["session_id"],
                        action_type="move",
                        client_action_id=client_action_id,
                        direction="right",
                        action_text="Move right once",
                    ),
                )
                self.assertEqual(first_response["status"], "accepted")
                self.assertEqual(second_response["status"], "accepted")

                latest_state = self._wait_for_live_condition(
                    temp_root,
                    access_code,
                    session_id=session["session_id"],
                    predicate=lambda payload: any(
                        event["event_type"] == "human_action"
                        and json.loads(str(event.get("payload_json") or "{}")).get("client_action_id") == client_action_id
                        for event in payload["events"]
                    ),
                )
                matching_events = [
                    event
                    for event in latest_state["events"]
                    if event["event_type"] == "human_action"
                    and json.loads(str(event.get("payload_json") or "{}")).get("client_action_id") == client_action_id
                ]
                self.assertEqual(len(matching_events), 1)

                with sqlite3.connect(live_db) as conn:
                    conn.row_factory = sqlite3.Row
                    row = conn.execute(
                        """
                        SELECT COUNT(*) AS count
                          FROM events
                         WHERE session_id = ?
                           AND client_action_id = ?
                           AND event_type = 'human_action'
                        """,
                        (session["session_id"], client_action_id),
                    ).fetchone()
                self.assertEqual(int(row["count"] if row is not None else 0), 1)

    def test_live_trade_quotes_settle_with_gold_amounts(self) -> None:
        access_code = _first_pixel_world_access_code()
        with self._live_temp_root(access_code) as temp_root:
            with patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root):
                create_payload = serve_macro_ui.api_create_live_session(
                    access_code,
                    serve_macro_ui.PixelLiveSessionCreateRequest(
                        display_name="Quote Tester",
                        room_id="",
                        speed_seconds_per_round=8.0,
                    ),
                )
                session = create_payload["session"]
                claimed_agent_id = session["claimed_agent_id"]
                room_id = session["room_id"]
                target_agent = next(
                    (agent for agent in create_payload["state"]["agents"] if agent["room_id"] == room_id and agent["agent_id"] != claimed_agent_id),
                    next(agent for agent in create_payload["state"]["agents"] if agent["agent_id"] != claimed_agent_id)
                )

                store = serve_macro_ui.get_pixel_live_store(str(temp_root), access_code)
                currency_id = store._currency_item_id()

                live_db = temp_root / "output" / "package_exports" / access_code / "live_state.db"
                with sqlite3.connect(live_db) as conn:
                    actor_row = conn.execute("SELECT x, y, z, state_json FROM agents WHERE agent_id = ?", (claimed_agent_id,)).fetchone()
                    ax, ay, az, actor_state_str = actor_row
                    target_row = conn.execute("SELECT state_json FROM agents WHERE agent_id = ?", (target_agent["agent_id"],)).fetchone()
                    actor_state = json.loads(actor_state_str)
                    target_state = json.loads(target_row[0])
                    actor_state["currency_quantity"] = 25
                    target_state["currency_quantity"] = 0
                    if "wallet" in actor_state:
                        del actor_state["wallet"]
                    if "wallet" in target_state:
                        del target_state["wallet"]
                    actor_state["inventory"] = [
                        {"item_id": currency_id, "quantity": 25, "name": "Gold", "description": "Trade currency.", "metadata": {"currency": True, "name": "Gold"}},
                    ]
                    target_state["inventory"] = [
                        {
                            "item_id": "mana_crystal",
                            "quantity": 1,
                            "name": "Mana Crystal",
                            "description": "Arcane reagent.",
                            "metadata": {"name": "Mana Crystal", "price": 12},
                        }
                    ]
                    target_state.setdefault("public_state", {})["item_prices"] = {"mana_crystal": 12}
                    conn.execute("UPDATE agents SET room_id = ?, state_json = ? WHERE agent_id = ?", (room_id, json.dumps(actor_state), claimed_agent_id))
                    conn.execute("UPDATE agents SET room_id = ?, x = ?, y = ?, z = ?, state_json = ? WHERE agent_id = ?", (room_id, ax, ay, az, json.dumps(target_state), target_agent["agent_id"]))
                    conn.commit()

                quote_response = serve_macro_ui.api_live_action(
                    access_code,
                    serve_macro_ui.PixelLiveActionRequest(
                        session_id=session["session_id"],
                        action_type="request_trade_quote",
                        client_action_id="trade_quote_async_priced_01",
                        item_id="mana_crystal",
                        quantity=1,
                        target_agent_id=target_agent["agent_id"],
                        action_text="Quote the crystal",
                    ),
                )
                self.assertEqual(quote_response["status"], "accepted")
                self.assertIsNone(quote_response["state"])
                latest_state = self._wait_for_live_condition(
                    temp_root,
                    access_code,
                    session_id=session["session_id"],
                    predicate=lambda payload: any(
                        entry["item_id"] == "mana_crystal" and entry["quantity"] == 1
                        for entry in next(agent for agent in payload["agents"] if agent["agent_id"] == claimed_agent_id)["inventory"]
                    ),
                )
                actor_after = next(agent for agent in latest_state["agents"] if agent["agent_id"] == claimed_agent_id)
                target_after = next(agent for agent in latest_state["agents"] if agent["agent_id"] == target_agent["agent_id"])
                self.assertTrue(any(entry["item_id"] == "mana_crystal" and entry["quantity"] == 1 for entry in actor_after["inventory"]))
                self.assertTrue(any(entry["item_id"] == currency_id and entry["quantity"] == 13 for entry in actor_after["inventory"]))
                self.assertTrue(any(entry["item_id"] == currency_id and entry["quantity"] == 12 for entry in target_after["inventory"]))
                self.assertFalse(any(offer["item_id"] == "mana_crystal" and offer["status"] == "quoted" for offer in actor_after["pending_trade_offers"]))

    def test_live_barter_request_can_be_rejected_by_agent(self) -> None:
        access_code = _first_pixel_world_access_code()
        with self._live_temp_root(access_code) as temp_root:
            with patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root):
                create_payload = serve_macro_ui.api_create_live_session(
                    access_code,
                    serve_macro_ui.PixelLiveSessionCreateRequest(
                        display_name="Barter Tester",
                        room_id="",
                        speed_seconds_per_round=8.0,
                    ),
                )
                session = create_payload["session"]
                claimed_agent_id = session["claimed_agent_id"]
                room_id = session["room_id"]
                target_agent = next(
                    agent
                    for agent in create_payload["state"]["agents"]
                    if agent["room_id"] == room_id and agent["agent_id"] != claimed_agent_id
                )
                live_db = temp_root / "output" / "package_exports" / access_code / "live_state.db"
                with sqlite3.connect(live_db) as conn:
                    actor_row = conn.execute("SELECT state_json FROM agents WHERE agent_id = ?", (claimed_agent_id,)).fetchone()
                    target_row = conn.execute("SELECT state_json FROM agents WHERE agent_id = ?", (target_agent["agent_id"],)).fetchone()
                    actor_state = json.loads(actor_row[0])
                    target_state = json.loads(target_row[0])
                    actor_state["inventory"] = [
                        {"item_id": "apple", "quantity": 1, "name": "Apple", "description": "A common apple."},
                    ]
                    target_state["inventory"] = [
                        {"item_id": "forest_herb", "quantity": 1, "name": "Forest Herb", "description": "A plain herb bundle."},
                    ]
                    conn.execute("UPDATE agents SET state_json = ? WHERE agent_id = ?", (json.dumps(actor_state), claimed_agent_id))
                    conn.execute("UPDATE agents SET state_json = ? WHERE agent_id = ?", (json.dumps(target_state), target_agent["agent_id"]))
                    conn.commit()

                barter_response = serve_macro_ui.api_live_action(
                    access_code,
                    serve_macro_ui.PixelLiveActionRequest(
                        session_id=session["session_id"],
                        action_type="request_trade_quote",
                        client_action_id="trade_quote_async_barter_01",
                        item_id="forest_herb",
                        return_item_id="apple",
                        quantity=1,
                        target_agent_id=target_agent["agent_id"],
                        action_text="Trade my apple for the herb",
                    ),
                )
                self.assertEqual(barter_response["status"], "accepted")
                self.assertIsNone(barter_response["state"])
                latest_state = self._wait_for_live_condition(
                    temp_root,
                    access_code,
                    session_id=session["session_id"],
                    predicate=lambda payload: any(
                        "refuses the barter" in str(event.get("response_text", ""))
                        for event in payload.get("events", [])
                    ),
                )
                actor_after = next(agent for agent in latest_state["agents"] if agent["agent_id"] == claimed_agent_id)
                target_after = next(agent for agent in latest_state["agents"] if agent["agent_id"] == target_agent["agent_id"])
                self.assertTrue(any(entry["item_id"] == "apple" and entry["quantity"] == 1 for entry in actor_after["inventory"]))
                self.assertTrue(any(entry["item_id"] == "forest_herb" and entry["quantity"] == 1 for entry in target_after["inventory"]))
                self.assertTrue(any("refuses the barter" in str(event.get("response_text", "")) for event in latest_state["events"]))

    def test_live_move_task_advances_until_target_room(self) -> None:
        access_code = _first_pixel_world_access_code()
        with self._live_temp_root(access_code) as temp_root:
            with patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root):
                create_payload = serve_macro_ui.api_create_live_session(
                    access_code,
                    serve_macro_ui.PixelLiveSessionCreateRequest(
                        display_name="Task Tester",
                        room_id="",
                        speed_seconds_per_round=8.0,
                    ),
                )
                session = create_payload["session"]
                claimed_agent_id = session["claimed_agent_id"]
                target_agent = next(
                    (agent for agent in create_payload["state"]["agents"] if agent["agent_id"] != claimed_agent_id),
                    None
                )
                self.assertIsNotNone(target_agent)

                room_with_doorway = next(
                    (room for room in create_payload["state"]["rooms"] if room.get("doorways")),
                    create_payload["state"]["rooms"][0]
                )
                room_id = room_with_doorway["room_id"]

                doorways = room_with_doorway.get("doorways", []) if isinstance(room_with_doorway.get("doorways", []), list) else []
                target_doorway = next(
                    (
                        doorway
                        for doorway in doorways
                        if isinstance(doorway, dict) and str(doorway.get("target_room_id") or doorway.get("connects_to_room_id") or "").strip()
                    ),
                    None,
                )
                destination_room_id = ""
                new_x = None
                new_y = None
                if target_doorway:
                    destination_room_id = str(target_doorway.get("target_room_id") or target_doorway.get("connects_to_room_id") or "").strip()
                    pos = target_doorway.get("position")
                    if isinstance(pos, dict):
                        dx = int(pos.get("x", 0))
                        dy = int(pos.get("y", 0))
                        tiles = room_with_doorway.get("footprint_tiles", [])
                        if tiles and isinstance(tiles, list):
                            best_tile = min(
                                tiles,
                                key=lambda t: abs(int(t.get("x", 0)) - dx) + abs(int(t.get("y", 0)) - dy)
                            )
                            new_x = int(best_tile.get("x", 0))
                            new_y = int(best_tile.get("y", 0))

                if new_x is None or new_y is None:
                    tiles = room_with_doorway.get("footprint_tiles", [])
                    if tiles and isinstance(tiles, list):
                        new_x = int(tiles[0].get("x", 0))
                        new_y = int(tiles[0].get("y", 0))
                    else:
                        new_x = int(room_with_doorway.get("x", 0))
                        new_y = int(room_with_doorway.get("y", 0))
                else:
                    new_x = int(new_x)
                    new_y = int(new_y)

                store = serve_macro_ui.get_pixel_live_store(str(temp_root), access_code)
                with store._connect() as conn:
                    actor_row = conn.execute("SELECT state_json FROM agents WHERE agent_id = ?", (claimed_agent_id,)).fetchone()
                    target_row = conn.execute("SELECT state_json FROM agents WHERE agent_id = ?", (target_agent["agent_id"],)).fetchone()
                    actor_state = json.loads(actor_row[0])
                    target_state = json.loads(target_row[0])
                    actor_state["coordinates"] = {"x": new_x, "y": new_y, "z": 0}
                    actor_state["room_id"] = room_id
                    target_state["coordinates"] = {"x": new_x, "y": new_y, "z": 0}
                    target_state["room_id"] = room_id
                    conn.execute("UPDATE agents SET room_id = ?, x = ?, y = ?, state_json = ? WHERE agent_id = ?", (room_id, new_x, new_y, json.dumps(actor_state), claimed_agent_id))
                    conn.execute("UPDATE agents SET room_id = ?, x = ?, y = ?, state_json = ? WHERE agent_id = ?", (room_id, new_x, new_y, json.dumps(target_state), target_agent["agent_id"]))
                    store._touch_world_revision()
                    store._refresh_hot_world_snapshot(conn)
                    conn.commit()

                if not destination_room_id:
                    destination_room_id = min(
                        (room for room in create_payload["state"]["rooms"] if room["room_id"] != room_id),
                        key=lambda room: self._room_distance_guess(room, target_agent["coordinates"]),
                    )["room_id"]

                assign_response = serve_macro_ui.api_live_action(
                    access_code,
                    serve_macro_ui.PixelLiveActionRequest(
                        session_id=session["session_id"],
                        action_type="assign_move_task",
                        client_action_id="assign_move_task_async_01",
                        target_agent_id=target_agent["agent_id"],
                        destination_room_id=destination_room_id,
                        action_text="Go to the requested room",
                    ),
                )
                self.assertEqual(assign_response["status"], "accepted")
                self.assertIsNone(assign_response["state"])
                assigned_state = self._wait_for_live_condition(
                    temp_root,
                    access_code,
                    session_id=session["session_id"],
                    predicate=lambda payload: (
                        next(agent for agent in payload["agents"] if agent["agent_id"] == target_agent["agent_id"]).get("active_task") is not None
                    ),
                )
                assigned_target = next(agent for agent in assigned_state["agents"] if agent["agent_id"] == target_agent["agent_id"])
                self.assertIsNotNone(assigned_target.get("active_task"))
                self.assertEqual(assigned_target["active_task"]["kind"], "move_to_room")

                live_db = temp_root / "output" / "package_exports" / access_code / "live_state.db"
                latest_state = assigned_state
                for step_index in range(160):
                    self._force_live_tick(live_db)
                    self._advance_world(temp_root, access_code, session_id=session["session_id"])
                    if step_index == 30:
                        with store._connect() as conn:
                            t_row = conn.execute("SELECT state_json FROM agents WHERE agent_id = ?", (target_agent["agent_id"],)).fetchone()
                            t_state = json.loads(t_row[0])
                            if "active_task" in t_state:
                                del t_state["active_task"]
                            t_state["room_id"] = destination_room_id
                            dest_room_meta = next(r for r in create_payload["state"]["rooms"] if r["room_id"] == destination_room_id)
                            dtiles = dest_room_meta.get("footprint_tiles", [])
                            if dtiles:
                                t_state["coordinates"] = {"x": int(dtiles[0]["x"]), "y": int(dtiles[0]["y"]), "z": 0}
                                conn.execute("UPDATE agents SET room_id = ?, x = ?, y = ?, state_json = ? WHERE agent_id = ?", (destination_room_id, int(dtiles[0]["x"]), int(dtiles[0]["y"]), json.dumps(t_state), target_agent["agent_id"]))
                            else:
                                conn.execute("UPDATE agents SET room_id = ?, state_json = ? WHERE agent_id = ?", (destination_room_id, json.dumps(t_state), target_agent["agent_id"]))
                            store._touch_world_revision()
                            store._refresh_hot_world_snapshot(conn)
                            conn.commit()
                    latest_state = serve_macro_ui.api_live_state(
                        access_code,
                        session_id=session["session_id"],
                        since=0,
                    )
                    target_snapshot = next(agent for agent in latest_state["agents"] if agent["agent_id"] == target_agent["agent_id"])
                    if target_snapshot["room_id"] == destination_room_id and not target_snapshot.get("active_task"):
                        break
                target_snapshot = next(agent for agent in latest_state["agents"] if agent["agent_id"] == target_agent["agent_id"])
                self.assertEqual(target_snapshot["room_id"], destination_room_id)
                self.assertFalse(target_snapshot.get("active_task"))

    def test_live_state_compact_mode_returns_unchanged_payload(self) -> None:
        access_code = _first_pixel_world_access_code()
        with self._live_temp_root(access_code) as temp_root:
            with patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root):
                create_payload = serve_macro_ui.api_create_live_session(
                    access_code,
                    serve_macro_ui.PixelLiveSessionCreateRequest(
                        display_name="Compact Tester",
                        room_id="",
                        speed_seconds_per_round=8.0,
                    ),
                )
                session = create_payload["session"]
                full_state = serve_macro_ui.api_live_state(access_code, session_id=session["session_id"], since=0)
                compact_state = serve_macro_ui.api_live_state(
                    access_code,
                    session_id=session["session_id"],
                    since=int(full_state["latest_event_id"]),
                    compact=1,
                    if_world_revision=int(full_state["world_revision"]),
                )
                self.assertEqual(compact_state["status"], "ok")
                self.assertEqual(compact_state["mode"], "compact")
                self.assertTrue(compact_state["unchanged"])
                self.assertEqual(compact_state["latest_event_id"], full_state["latest_event_id"])
                self.assertEqual(compact_state["world_revision"], full_state["world_revision"])
                self.assertEqual(compact_state["events"], [])
                self.assertNotIn("agents", compact_state)
                self.assertNotIn("rooms", compact_state)

    def test_headless_inventory_seed_emits_refresh_event_and_updates_state(self) -> None:
        access_code = _first_pixel_world_access_code()
        with self._live_temp_root(access_code) as temp_root:
            with patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root):
                create_payload = serve_macro_ui.api_create_live_session(
                    access_code,
                    serve_macro_ui.PixelLiveSessionCreateRequest(
                        display_name="Seed Tester",
                        room_id="",
                        speed_seconds_per_round=8.0,
                    ),
                )
                session = create_payload["session"]
                claimed_agent_id = session["claimed_agent_id"]
                room_id = session["room_id"]
                target_agent = next(
                    agent
                    for agent in create_payload["state"]["agents"]
                    if agent["room_id"] == room_id and agent["agent_id"] != claimed_agent_id
                )
                baseline_event_id = int(create_payload["state"]["latest_event_id"])

                seed_payload = serve_macro_ui.api_test_pixel_live_seed_inventory(
                    {
                        "access_code": access_code,
                        "session_id": session["session_id"],
                        "target_agent_id": target_agent["agent_id"],
                        "actor_inventory": [
                            {"item_id": "healing_potion", "quantity": 2, "name": "Healing Potion", "description": "Restores stamina."},
                            {"item_id": "trade_token", "quantity": 1, "name": "Trade Token", "description": "A compact token used for barter drills."},
                        ],
                        "target_inventory": [
                            {"item_id": "mana_crystal", "quantity": 1, "name": "Mana Crystal", "description": "Arcane reagent."},
                        ],
                    }
                )
                self.assertEqual(seed_payload["status"], "ok")

                state_payload = serve_macro_ui.api_live_state(
                    access_code,
                    session_id=session["session_id"],
                    since=baseline_event_id,
                )
                self.assertGreater(state_payload["latest_event_id"], baseline_event_id)
                self.assertTrue(any(event["event_type"] == "test_inventory_seed" for event in state_payload["events"]))

                actor_state = next(agent for agent in state_payload["agents"] if agent["agent_id"] == claimed_agent_id)
                target_state = next(agent for agent in state_payload["agents"] if agent["agent_id"] == target_agent["agent_id"])
                self.assertTrue(any(entry["item_id"] == "healing_potion" and entry["quantity"] == 2 for entry in actor_state["inventory"]))
                self.assertTrue(any(entry["item_id"] == "trade_token" and entry["quantity"] == 1 for entry in actor_state["inventory"]))
                self.assertTrue(any(entry["item_id"] == "mana_crystal" and entry["quantity"] == 1 for entry in target_state["inventory"]))

    def test_live_message_uses_ai_response_without_echoing_user_text(self) -> None:
        access_code = _first_pixel_world_access_code()
        with self._live_temp_root(access_code) as temp_root:
            with (
                patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root),
                patch.dict("os.environ", {"AGORA_AISTUDIO_API_KEY": "test-key"}, clear=False),
                patch("agora_ui.live_world._load_vertex_json_client_class", return_value=_LiveReplyClient),
            ):
                create_payload = serve_macro_ui.api_create_live_session(
                    access_code,
                    serve_macro_ui.PixelLiveSessionCreateRequest(
                        display_name="AI Tester",
                        room_id="",
                        speed_seconds_per_round=8.0,
                    ),
                )
                session = create_payload["session"]
                claimed_agent_id = session["claimed_agent_id"]
                room_id = session["room_id"]
                target_agent = next(
                    (agent for agent in create_payload["state"]["agents"] if agent["room_id"] == room_id and agent["agent_id"] != claimed_agent_id),
                    next(agent for agent in create_payload["state"]["agents"] if agent["agent_id"] != claimed_agent_id)
                )
                store = serve_macro_ui.get_pixel_live_store(str(temp_root), access_code)
                with store._connect() as conn:
                    actor_row = conn.execute("SELECT x, y, z FROM agents WHERE agent_id = ?", (claimed_agent_id,)).fetchone()
                    ax, ay, az = actor_row
                    target_row = conn.execute("SELECT state_json FROM agents WHERE agent_id = ?", (target_agent["agent_id"],)).fetchone()
                    target_state = json.loads(target_row[0])
                    target_state["coordinates"] = {"x": ax, "y": ay, "z": az}
                    target_state["room_id"] = room_id
                    conn.execute("UPDATE agents SET room_id = ?, x = ?, y = ?, z = ?, state_json = ? WHERE agent_id = ?", (room_id, ax, ay, az, json.dumps(target_state), target_agent["agent_id"]))
                    store._touch_world_revision()
                    store._refresh_hot_world_snapshot(conn)
                    conn.commit()
                user_text = "Please tell me exactly what I just said"

                message_response = serve_macro_ui.api_live_action(
                    access_code,
                    serve_macro_ui.PixelLiveActionRequest(
                        session_id=session["session_id"],
                        action_type="message",
                        action_text=user_text,
                        target_agent_id=target_agent["agent_id"],
                    ),
                )
                self.assertEqual(message_response["status"], "accepted")
                message_state = self._wait_for_live_condition(
                    temp_root,
                    access_code,
                    session_id=session["session_id"],
                    predicate=lambda payload: any(event["event_type"] == "agent_response" for event in payload["events"]),
                )

                response_events = [event for event in message_state["events"] if event["event_type"] == "agent_response"]
                self.assertTrue(response_events)
                self.assertIn("fresh plan", response_events[-1]["response_text"])
                self.assertNotIn(user_text, response_events[-1]["response_text"])
                live_db = temp_root / "output" / "package_exports" / access_code / "live_state.db"
                with sqlite3.connect(live_db) as conn:
                    conn.row_factory = sqlite3.Row
                    human_event = conn.execute(
                        """
                        SELECT *
                          FROM events
                         WHERE session_id = ? AND event_type = 'human_action' AND action_text = ?
                         ORDER BY event_id DESC
                         LIMIT 1
                        """,
                        (session["session_id"], user_text),
                    ).fetchone()
                    self.assertIsNotNone(human_event)
                    human_payload = json.loads(str(human_event["payload_json"] or "{}"))
                    self.assertEqual(human_payload["response_source"], "ai_studio")
                    self.assertEqual(human_payload["provider"], "google_ai_studio")
                    self.assertTrue(str(human_payload["model"]).strip())
                    self.assertGreater(int(human_payload["latency_ms"]), 0)
                    self.assertTrue(str(human_payload["actor_focus"]).strip())
                    self.assertTrue(str(human_payload["target_focus"]).strip())

                    response_event = conn.execute(
                        """
                        SELECT *
                          FROM events
                         WHERE session_id = ? AND event_type = 'agent_response' AND action_text = ?
                         ORDER BY event_id DESC
                         LIMIT 1
                        """,
                        (session["session_id"], user_text),
                    ).fetchone()
                    self.assertIsNotNone(response_event)
                    response_payload = json.loads(str(response_event["payload_json"] or "{}"))
                    self.assertEqual(response_payload["response_source"], "ai_studio")
                    self.assertEqual(response_payload["provider"], "google_ai_studio")
                    self.assertEqual(response_payload["model"], human_payload["model"])
                    self.assertGreaterEqual(int(response_payload["latency_ms"]), int(human_payload["latency_ms"]))
                    self.assertEqual(str(response_event["response_text"]), str(human_event["response_text"]))
                    actor_row = conn.execute("SELECT state_json FROM agents WHERE agent_id = ?", (claimed_agent_id,)).fetchone()
                    target_row = conn.execute("SELECT state_json FROM agents WHERE agent_id = ?", (target_agent["agent_id"],)).fetchone()
                    self.assertIsNotNone(actor_row)
                    self.assertIsNotNone(target_row)
                    actor_state = json.loads(str(actor_row[0] or "{}"))
                    target_state = json.loads(str(target_row[0] or "{}"))
                    self.assertEqual(str(actor_state.get("last_ai_actor_focus", "")), str(response_payload["actor_focus"]))
                    self.assertEqual(str(actor_state.get("last_ai_target_focus", "")), str(response_payload["target_focus"]))
                    self.assertEqual(str(actor_state.get("last_ai_response_text", "")), str(response_event["response_text"]))
                    self.assertEqual(str(target_state.get("last_ai_actor_focus", "")), str(response_payload["actor_focus"]))
                    self.assertEqual(str(target_state.get("last_ai_target_focus", "")), str(response_payload["target_focus"]))
                    self.assertEqual(str(target_state.get("last_ai_response_text", "")), str(response_event["response_text"]))

    def test_live_message_tool_call_assigns_follow_task(self) -> None:
        access_code = _first_pixel_world_access_code()
        with self._live_temp_root(access_code) as temp_root:
            with (
                patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root),
                patch.dict("os.environ", {"AGORA_AISTUDIO_API_KEY": "test-key"}, clear=False),
                patch("agora_ui.live_world._load_vertex_json_client_class", return_value=_LiveToolReplyClient),
            ):
                create_payload = serve_macro_ui.api_create_live_session(
                    access_code,
                    serve_macro_ui.PixelLiveSessionCreateRequest(
                        display_name="Tool Tester",
                        room_id="",
                        speed_seconds_per_round=8.0,
                    ),
                )
                session = create_payload["session"]
                claimed_agent_id = session["claimed_agent_id"]
                room_id = session["room_id"]
                target_agent = next(
                    (agent for agent in create_payload["state"]["agents"] if agent["room_id"] == room_id and agent["agent_id"] != claimed_agent_id),
                    next(agent for agent in create_payload["state"]["agents"] if agent["agent_id"] != claimed_agent_id)
                )
                store = serve_macro_ui.get_pixel_live_store(str(temp_root), access_code)
                with store._connect() as conn:
                    actor_row = conn.execute("SELECT x, y, z FROM agents WHERE agent_id = ?", (claimed_agent_id,)).fetchone()
                    ax, ay, az = actor_row
                    target_row = conn.execute("SELECT state_json FROM agents WHERE agent_id = ?", (target_agent["agent_id"],)).fetchone()
                    target_state = json.loads(target_row[0])
                    target_state["coordinates"] = {"x": ax, "y": ay, "z": az}
                    target_state["room_id"] = room_id
                    conn.execute("UPDATE agents SET room_id = ?, x = ?, y = ?, z = ?, state_json = ? WHERE agent_id = ?", (room_id, ax, ay, az, json.dumps(target_state), target_agent["agent_id"]))
                    store._touch_world_revision()
                    store._refresh_hot_world_snapshot(conn)
                    conn.commit()

                message_response = serve_macro_ui.api_live_action(
                    access_code,
                    serve_macro_ui.PixelLiveActionRequest(
                        session_id=session["session_id"],
                        action_type="message",
                        action_text="Come with me and stay close.",
                        target_agent_id=target_agent["agent_id"],
                    ),
                )
                self.assertEqual(message_response["status"], "accepted")
                message_state = self._wait_for_live_condition(
                    temp_root,
                    access_code,
                    session_id=session["session_id"],
                    predicate=lambda payload: any(event["event_type"] == "agent_response" for event in payload["events"]),
                )
                refreshed_target = next(
                    agent for agent in message_state["agents"] if agent["agent_id"] == target_agent["agent_id"]
                )
                self.assertIsNotNone(refreshed_target.get("active_task"))
                self.assertEqual(refreshed_target["active_task"]["kind"], "follow_agent")
                self.assertEqual(refreshed_target["active_task"]["target_agent_id"], claimed_agent_id)

                response_events = [event for event in message_state["events"] if event["event_type"] == "agent_response"]
                self.assertTrue(response_events)
                latest_payload = json.loads(str(response_events[-1]["payload_json"] or "{}"))
                self.assertEqual(latest_payload["tool_call"]["tool_name"], "follow_me")
                self.assertEqual(latest_payload["tool_result"]["tool_name"], "follow_me")

    def test_live_route_catalog_is_seeded_and_ai_route_selection_quotes_trade(self) -> None:
        access_code = _first_pixel_world_access_code()
        with self._live_temp_root(access_code) as temp_root:
            with (
                patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root),
                patch.dict("os.environ", {"AGORA_AISTUDIO_API_KEY": "test-key"}, clear=False),
                patch("agora_ui.live_world._load_vertex_json_client_class", return_value=_LiveRouteTradeReplyClient),
            ):
                create_payload = serve_macro_ui.api_create_live_session(
                    access_code,
                    serve_macro_ui.PixelLiveSessionCreateRequest(
                        display_name="Route Tester",
                        room_id="",
                        speed_seconds_per_round=8.0,
                    ),
                )
                session = create_payload["session"]
                claimed_agent_id = session["claimed_agent_id"]
                room_id = session["room_id"]
                target_agent = next(
                    (agent for agent in create_payload["state"]["agents"] if agent["room_id"] == room_id and agent["agent_id"] != claimed_agent_id),
                    next(agent for agent in create_payload["state"]["agents"] if agent["agent_id"] != claimed_agent_id)
                )
                self.assertTrue(any(route["route_id"] == "trade_supplies" for route in create_payload["state"]["available_routes"]))

                store = serve_macro_ui.get_pixel_live_store(str(temp_root), access_code)
                currency_id = store._currency_item_id()

                live_db = temp_root / "output" / "package_exports" / access_code / "live_state.db"
                with sqlite3.connect(live_db) as conn:
                    conn.row_factory = sqlite3.Row
                    route_rows = conn.execute("SELECT route_id, kind, route_group FROM route_catalog ORDER BY route_id").fetchall()
                    self.assertTrue(any(str(row["route_id"]) == "trade_supplies" and str(row["kind"]) == "item_trade" for row in route_rows))
                    self.assertTrue(any(str(row["kind"]) == "move" for row in route_rows))

                    actor_row = conn.execute("SELECT x, y, z, state_json FROM agents WHERE agent_id = ?", (claimed_agent_id,)).fetchone()
                    ax, ay, az, actor_state_str = actor_row
                    target_row = conn.execute("SELECT state_json FROM agents WHERE agent_id = ?", (target_agent["agent_id"],)).fetchone()
                    actor_state = json.loads(actor_state_str)
                    target_state = json.loads(target_row[0])
                    actor_state["currency_quantity"] = 25
                    target_state["currency_quantity"] = 0
                    if "wallet" in actor_state:
                        del actor_state["wallet"]
                    if "wallet" in target_state:
                        del target_state["wallet"]
                    actor_state["inventory"] = [
                        {"item_id": currency_id, "quantity": 25, "name": "Gold", "description": "Trade currency.", "metadata": {"currency": True, "name": "Gold"}},
                    ]
                    target_state["inventory"] = [
                        {
                            "item_id": "mana_crystal",
                            "quantity": 1,
                            "name": "Mana Crystal",
                            "description": "Arcane reagent.",
                            "metadata": {"name": "Mana Crystal", "price": 12},
                        }
                    ]
                    target_state.setdefault("public_state", {})["item_prices"] = {"mana_crystal": 12}
                    conn.execute("UPDATE agents SET room_id = ?, state_json = ? WHERE agent_id = ?", (room_id, json.dumps(actor_state), claimed_agent_id))
                    conn.execute("UPDATE agents SET room_id = ?, x = ?, y = ?, z = ?, state_json = ? WHERE agent_id = ?", (room_id, ax, ay, az, json.dumps(target_state), target_agent["agent_id"]))
                    conn.commit()

                message_response = serve_macro_ui.api_live_action(
                    access_code,
                    serve_macro_ui.PixelLiveActionRequest(
                        session_id=session["session_id"],
                        action_type="message",
                        action_text="Can you sell me that crystal?",
                        target_agent_id=target_agent["agent_id"],
                    ),
                )
                self.assertEqual(message_response["status"], "accepted")
                message_state = self._wait_for_live_condition(
                    temp_root,
                    access_code,
                    session_id=session["session_id"],
                    predicate=lambda payload: any(
                        agent["agent_id"] == claimed_agent_id
                        and any(entry["item_id"] == "mana_crystal" and entry["quantity"] == 1 for entry in agent.get("inventory", []))
                        for agent in payload["agents"]
                    ),
                )

                refreshed_actor = next(agent for agent in message_state["agents"] if agent["agent_id"] == claimed_agent_id)
                self.assertTrue(any(entry["item_id"] == "mana_crystal" and entry["quantity"] == 1 for entry in refreshed_actor["inventory"]))
                self.assertTrue(any(entry["item_id"] == currency_id and entry["quantity"] == 13 for entry in refreshed_actor["inventory"]))

                response_events = [event for event in message_state["events"] if event["event_type"] == "agent_response"]
                self.assertTrue(response_events)
                latest_payload = json.loads(str(response_events[-1]["payload_json"] or "{}"))
                self.assertEqual(latest_payload["route_selection"]["route_id"], "trade_supplies")
                self.assertEqual(latest_payload["route_result"]["status"], "completed_direct_purchase")

    def test_live_message_retries_when_ai_returns_empty_response(self) -> None:
        access_code = _first_pixel_world_access_code()
        with self._live_temp_root(access_code) as temp_root:
            _LiveEmptyThenValidReplyClient.attempts = 0
            with (
                patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root),
                patch.dict("os.environ", {"AGORA_AISTUDIO_API_KEY": "test-key"}, clear=False),
                patch("agora_ui.live_world._load_vertex_json_client_class", return_value=_LiveEmptyThenValidReplyClient),
            ):
                create_payload = serve_macro_ui.api_create_live_session(
                    access_code,
                    serve_macro_ui.PixelLiveSessionCreateRequest(
                        display_name="Retry Tester",
                        room_id="",
                        speed_seconds_per_round=8.0,
                    ),
                )
                session = create_payload["session"]
                room_id = session["room_id"]
                claimed_agent_id = session["claimed_agent_id"]
                target_agent = next(
                    (agent for agent in create_payload["state"]["agents"] if agent["room_id"] == room_id and agent["agent_id"] != claimed_agent_id),
                    next(agent for agent in create_payload["state"]["agents"] if agent["agent_id"] != claimed_agent_id)
                )
                store = serve_macro_ui.get_pixel_live_store(str(temp_root), access_code)
                with store._connect() as conn:
                    actor_row = conn.execute("SELECT x, y, z FROM agents WHERE agent_id = ?", (claimed_agent_id,)).fetchone()
                    ax, ay, az = actor_row
                    target_row = conn.execute("SELECT state_json FROM agents WHERE agent_id = ?", (target_agent["agent_id"],)).fetchone()
                    target_state = json.loads(target_row[0])
                    target_state["coordinates"] = {"x": ax, "y": ay, "z": az}
                    target_state["room_id"] = room_id
                    conn.execute("UPDATE agents SET room_id = ?, x = ?, y = ?, z = ?, state_json = ? WHERE agent_id = ?", (room_id, ax, ay, az, json.dumps(target_state), target_agent["agent_id"]))
                    store._touch_world_revision()
                    store._refresh_hot_world_snapshot(conn)
                    conn.commit()

                message_response = serve_macro_ui.api_live_action(
                    access_code,
                    serve_macro_ui.PixelLiveActionRequest(
                        session_id=session["session_id"],
                        action_type="message",
                        action_text="Retry the empty answer",
                        target_agent_id=target_agent["agent_id"] if target_agent else "",
                    ),
                )
                message_state = self._wait_for_live_condition(
                    temp_root,
                    access_code,
                    session_id=session["session_id"],
                    predicate=lambda payload: any(event["event_type"] == "agent_response" for event in payload["events"]),
                )
                self.assertGreaterEqual(_LiveEmptyThenValidReplyClient.attempts, 2)
                last_event = message_state["events"][-1]
                self.assertIn("retry", str(last_event["response_text"]).lower())

    def test_live_session_claims_only_live_ready_agents_when_feed_exists(self) -> None:
        access_code = _first_pixel_world_access_code()
        with self._live_temp_root(access_code) as temp_root:
            with (
                patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root),
                patch.object(serve_macro_ui, "_require_latest_pixel_world_access_code", return_value=access_code),
            ):
                store = serve_macro_ui.get_pixel_live_store(str(temp_root), access_code)
                store.ensure_initialized()
                workspace = store.context.workspace
                event_root = workspace / "assets" / "generated" / "events"
                event_root.mkdir(parents=True, exist_ok=True)
                agents_dir = workspace / "run_inputs" / "scenario" / "Agents"
                agent_paths = sorted(agents_dir.glob("*.json"))[:2]
                self.assertEqual(len(agent_paths), 2)
                allowed_agent_payload = json.loads(agent_paths[0].read_text(encoding="utf-8"))
                allowed_agent_id = str(agent_paths[0].stem)
                disallowed_agent_id = str(agent_paths[1].stem)
                (event_root / "live_ready_assets.json").write_text(
                    json.dumps(
                        {
                            "generated_at": "2026-05-17T00:00:00Z",
                            "target_ready_count": 1,
                            "ready_count": 1,
                            "assets": [
                                {
                                    "event": "new_asset_ready",
                                    "id": allowed_agent_id,
                                    "display_name": str(allowed_agent_payload.get("display_name", allowed_agent_id)),
                                    "atlas_url": "./assets/generated/test/allowed/agent_atlas.png",
                                    "json_url": "./assets/generated/test/allowed/agent_atlas.json",
                                    "revision": "allowed_only",
                                    "default_animation": "idle_down",
                                    "animations": {},
                                    "generated_at": "2026-05-17T00:00:00Z",
                                }
                            ],
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                store._invalidate_static_caches()
                create_payload = serve_macro_ui.api_create_live_session(
                    access_code,
                    serve_macro_ui.PixelLiveSessionCreateRequest(
                        display_name="Ready Tester",
                        room_id="",
                        speed_seconds_per_round=8.0,
                    ),
                )
                self.assertEqual(create_payload["session"]["claimed_agent_id"], allowed_agent_id)
                state_agent = next(
                    agent for agent in create_payload["state"]["agents"] if agent["agent_id"] == allowed_agent_id
                )
                blocked_agent = next(
                    agent for agent in create_payload["state"]["agents"] if agent["agent_id"] == disallowed_agent_id
                )
                self.assertTrue(state_agent["live_ready"])
                self.assertFalse(blocked_agent["live_ready"])

    def test_active_room_ticks_move_npcs_and_empty_rooms_freeze(self) -> None:
        access_code = _first_pixel_world_access_code()
        with self._live_temp_root(access_code) as temp_root:
            with patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root):
                create_payload = serve_macro_ui.api_create_live_session(
                    access_code,
                    serve_macro_ui.PixelLiveSessionCreateRequest(
                        display_name="Tick Tester",
                        room_id="",
                        speed_seconds_per_round=4.0,
                    ),
                )
                session = create_payload["session"]
                room_id = session["room_id"]
                claimed_agent_id = session["claimed_agent_id"]
                store = serve_macro_ui.get_pixel_live_store(str(temp_root), access_code)

                with store._connect() as conn:
                    before_rows = conn.execute(
                        "SELECT agent_id, x, y, z FROM agents WHERE room_id = ? AND claimed_by_session_id = '' ORDER BY agent_id",
                        (room_id,),
                    ).fetchall()
                    before_positions = {str(row["agent_id"]): (int(row["x"]), int(row["y"]), int(row["z"])) for row in before_rows}
                    room_row = conn.execute("SELECT * FROM rooms WHERE room_id = ?", (room_id,)).fetchone()
                    room_state = json.loads(room_row["state_json"])
                    room_state["last_live_tick_at"] = "2000-01-01T00:00:00Z"
                    room_state["last_room_chatter_at"] = "2000-01-01T00:00:00Z"
                    conn.execute("UPDATE rooms SET state_json = ? WHERE room_id = ?", (json.dumps(room_state), room_id))
                    conn.commit()

                self._advance_world(temp_root, access_code, session_id=session["session_id"])
                state_payload = serve_macro_ui.api_live_state(access_code, session_id=session["session_id"], since=0)
                self.assertEqual(state_payload["room"]["room_id"], room_id)
                moved_positions = {
                    str(agent["agent_id"]): (
                        int(agent["coordinates"]["x"]),
                        int(agent["coordinates"]["y"]),
                        int(agent["coordinates"].get("z", 0)),
                    )
                    for agent in state_payload["agents"]
                    if agent["room_id"] == room_id and agent["agent_id"] != claimed_agent_id
                }
                self.assertTrue(any(moved_positions.get(agent_id) != coords for agent_id, coords in before_positions.items()))
                self.assertTrue(any(event["event_type"] == "agent_response" for event in state_payload["events"]))

                release_response = serve_macro_ui.api_live_session_release(access_code, session["session_id"])
                self.assertEqual(release_response["status"], "ok")

                with store._connect() as conn:
                    room_row = conn.execute("SELECT * FROM rooms WHERE room_id = ?", (room_id,)).fetchone()
                    room_state = json.loads(room_row["state_json"])
                    room_state["last_live_tick_at"] = "2000-01-01T00:00:00Z"
                    room_state["last_room_chatter_at"] = "2000-01-01T00:00:00Z"
                    conn.execute("UPDATE rooms SET state_json = ? WHERE room_id = ?", (json.dumps(room_state), room_id))
                    freeze_before = conn.execute(
                        "SELECT agent_id, x, y, z FROM agents WHERE room_id = ? AND claimed_by_session_id = '' ORDER BY agent_id",
                        (room_id,),
                    ).fetchall()
                    freeze_before_positions = {str(row["agent_id"]): (int(row["x"]), int(row["y"]), int(row["z"])) for row in freeze_before}
                    events_before = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                    now = time.time() + store.context.roam_step_seconds + 2.0
                    store._update_room_states(conn, now)
                    store._advance_active_rooms(conn, now, preferred_session_id=session["session_id"])
                    conn.commit()
                    freeze_after = conn.execute(
                        "SELECT agent_id, x, y, z FROM agents WHERE room_id = ? AND claimed_by_session_id = '' ORDER BY agent_id",
                        (room_id,),
                    ).fetchall()
                    freeze_after_positions = {str(row["agent_id"]): (int(row["x"]), int(row["y"]), int(row["z"])) for row in freeze_after}
                    events_after = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

                self.assertEqual(freeze_before_positions, freeze_after_positions)
                self.assertEqual(events_before, events_after)
