from __future__ import annotations

import unittest

from scripts.pixel_live_load_test import build_mixed_action
from scripts.pixel_live_load_test import _build_metrics
from scripts.pixel_live_load_test import RequestResult
from scripts.pixel_live_load_test import SessionRuntime
from scripts.pixel_live_load_test import choose_world_record
from scripts.pixel_live_load_test import compare_metric_summaries
from scripts.pixel_live_load_test import percentile
from scripts.pixel_live_load_test import summarize_records


class PixelLiveLoadTestHelpers(unittest.TestCase):
    def test_choose_world_record_prefers_access_code_then_seed_then_first(self) -> None:
        worlds = [
            {"access_code": "aaaaaaaaaaaaaaaa", "seed": 101, "world_name": "First"},
            {"access_code": "bbbbbbbbbbbbbbbb", "seed": 202, "world_name": "Second"},
        ]

        by_access_code = choose_world_record(worlds, access_code="bbbbbbbbbbbbbbbb", seed=101)
        self.assertEqual(by_access_code["world_name"], "Second")

        by_seed = choose_world_record(worlds, seed=101)
        self.assertEqual(by_seed["world_name"], "First")

        first_world = choose_world_record(worlds)
        self.assertEqual(first_world["access_code"], "aaaaaaaaaaaaaaaa")

    def test_build_mixed_action_uses_expected_mix_and_fallbacks(self) -> None:
        state = {
            "session": {
                "session_id": "session-1",
                "claimed_agent_id": "hero",
            },
            "room": {
                "room_id": "guild_hall",
                "doorways": [{"target_room_id": "forge"}],
            },
            "active_room_agents": [
                {"agent_id": "hero", "inventory": []},
                {"agent_id": "merchant", "inventory": [{"item_id": "mana_crystal", "quantity": 1}]},
            ],
        }

        message_action = build_mixed_action(state, step_index=0)
        self.assertEqual(message_action["action_type"], "message")
        self.assertEqual(message_action["target_agent_id"], "merchant")

        move_action = build_mixed_action(state, step_index=7)
        self.assertEqual(move_action["action_type"], "move")
        self.assertIn(move_action["direction"], {"up", "down", "left", "right"})

        special_action = build_mixed_action(state, step_index=9)
        self.assertEqual(special_action["action_type"], "request_trade_quote")
        self.assertEqual(special_action["item_id"], "mana_crystal")

        solo_state = {
            "session": {
                "session_id": "session-2",
                "claimed_agent_id": "solo",
            },
            "room": {
                "room_id": "empty_room",
                "doorways": [],
            },
            "active_room_agents": [{"agent_id": "solo", "inventory": []}],
        }
        fallback_action = build_mixed_action(solo_state, step_index=9)
        self.assertEqual(fallback_action["action_type"], "move")

    def test_summarize_records_and_compare_metric_summaries(self) -> None:
        records = [
            {
                "ok": True,
                "client_latency_ms": 100.0,
                "server_elapsed_ms": 80.0,
                "response_bytes": 512,
                "ai_reply_latency_ms": 0,
                "status_code": 200,
                "latest_event_advanced": True,
            },
            {
                "ok": True,
                "client_latency_ms": 300.0,
                "server_elapsed_ms": 250.0,
                "response_bytes": 256,
                "ai_reply_latency_ms": 180,
                "status_code": 200,
                "latest_event_advanced": False,
            },
            {
                "ok": False,
                "client_latency_ms": 1200.0,
                "server_elapsed_ms": None,
                "response_bytes": 0,
                "ai_reply_latency_ms": None,
                "status_code": 500,
                "latest_event_advanced": None,
            },
        ]

        summary = summarize_records(records)
        self.assertEqual(summary["count"], 3)
        self.assertEqual(summary["ok_count"], 2)
        self.assertAlmostEqual(summary["error_rate"], 1 / 3, places=6)
        self.assertAlmostEqual(summary["client_latency_ms"]["p50"], 200.0, places=3)
        self.assertGreaterEqual(summary["client_latency_ms"]["p95"], 290.0)
        self.assertEqual(summary["status_codes"]["200"], 2)
        self.assertEqual(summary["status_codes"]["500"], 1)
        self.assertAlmostEqual(summary["latest_event_advance_rate"], 0.5, places=6)

        baseline = {
            "client_latency_ms": {"p50": 150.0, "p95": 275.0, "p99": 295.0, "max": 300.0},
            "server_elapsed_ms": {"p50": 90.0, "p95": 225.0, "p99": 245.0, "max": 250.0},
            "error_rate": 0.1,
        }
        comparison = compare_metric_summaries(summary, baseline)
        self.assertAlmostEqual(comparison["client_latency_ms"]["p50"], 50.0, places=3)
        self.assertAlmostEqual(comparison["server_elapsed_ms"]["max"], 0.0, places=3)
        self.assertAlmostEqual(comparison["error_rate"], summary["error_rate"] - 0.1, places=6)

    def test_percentile_interpolates_between_neighbors(self) -> None:
        values = [100.0, 200.0, 300.0, 400.0]
        self.assertAlmostEqual(percentile(values, 0.5), 250.0, places=6)
        self.assertAlmostEqual(percentile(values, 0.95), 385.0, places=6)

    def test_build_metrics_splits_move_from_interaction(self) -> None:
        records = [
            {"endpoint": "live_action", "action_type": "message", "ok": True, "client_latency_ms": 100.0, "server_elapsed_ms": 80.0, "response_bytes": 10, "ai_reply_latency_ms": None, "status_code": 200, "latest_event_advanced": False},
            {"endpoint": "live_action", "action_type": "move", "ok": True, "client_latency_ms": 120.0, "server_elapsed_ms": 90.0, "response_bytes": 12, "ai_reply_latency_ms": None, "status_code": 200, "latest_event_advanced": False},
            {"endpoint": "live_action", "action_type": "request_trade_quote", "ok": False, "client_latency_ms": 300.0, "server_elapsed_ms": None, "response_bytes": 0, "ai_reply_latency_ms": None, "status_code": 500, "latest_event_advanced": None},
        ]

        metrics = _build_metrics(records)
        self.assertEqual(metrics["live_action"]["count"], 3)
        self.assertEqual(metrics["live_action_message"]["count"], 1)
        self.assertEqual(metrics["live_action_move"]["count"], 1)
        self.assertEqual(metrics["live_action_interaction"]["count"], 1)
        self.assertEqual(metrics["live_action_non_message"]["count"], 2)
        self.assertAlmostEqual(metrics["live_action_interaction"]["error_rate"], 1.0, places=6)

    def test_session_runtime_preserves_full_state_on_compact_unchanged_poll(self) -> None:
        runtime = SessionRuntime(
            user_index=0,
            access_code="world-1",
            session_id="session-1",
            display_name="User 01",
            session_payload={"session_id": "session-1"},
            state_payload={
                "status": "ok",
                "mode": "full",
                "unchanged": False,
                "latest_event_id": 12,
                "world_revision": 5,
                "poll_interval_ms": 1200,
                "room": {"room_id": "guild_hall"},
                "active_room_agents": [{"agent_id": "merchant"}],
                "events": [{"event_id": 12, "event_type": "room_chatter"}],
                "session": {"session_id": "session-1"},
            },
            created_result=RequestResult(
                endpoint="create_session",
                method="POST",
                url="http://localhost",
                ok=True,
                status_code=200,
                client_latency_ms=10.0,
                response_bytes=100,
                payload={},
            ),
        )

        runtime.apply_state(
            {
                "status": "ok",
                "mode": "compact",
                "unchanged": True,
                "latest_event_id": 12,
                "world_revision": 5,
                "poll_interval_ms": 900,
                "events": [],
                "session": {"session_id": "session-1"},
            }
        )

        latest_event_id, world_revision, _, state = runtime.snapshot()
        self.assertEqual(latest_event_id, 12)
        self.assertEqual(world_revision, 5)
        self.assertEqual(state["room"]["room_id"], "guild_hall")
        self.assertEqual(state["active_room_agents"][0]["agent_id"], "merchant")
        self.assertEqual(state["events"], [])
        self.assertEqual(state["mode"], "compact")
        self.assertTrue(state["unchanged"])
        self.assertEqual(state["poll_interval_ms"], 900)


if __name__ == "__main__":
    unittest.main()
