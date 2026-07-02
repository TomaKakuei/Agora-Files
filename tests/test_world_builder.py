from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi import HTTPException

from agora_ui import package_db
from agora_ui.flex_api import first_json_value_from_text
from agora_ui.flex_api import FlexExecuteResponse
from agora_ui.flex_providers import GeminiAIStudioProvider
from agora_ui import world_builder
from agora_ui.run_interaction_simulation import materialize_scenario
from macro_ui import build_macro_ui
from macro_ui import serve_macro_ui


ROOT = Path(__file__).resolve().parents[1]


def _prepare_creator_root(temp_root: Path) -> None:
    shutil.copytree(ROOT / "sample_json", temp_root / "sample_json")
    generated_root = temp_root / "frontend" / "assets" / "generated"
    events_root = generated_root / "events"
    agent_root = generated_root / "creator_demo_agent" / "creator_demo_revision"
    asset_set_root = generated_root / "guild_asset_sets"
    agent_root.mkdir(parents=True, exist_ok=True)
    events_root.mkdir(parents=True, exist_ok=True)
    asset_set_root.mkdir(parents=True, exist_ok=True)
    (generated_root / "maps").mkdir(parents=True, exist_ok=True)
    (generated_root / "maps" / "creator_map.png").write_bytes(b"PNG")
    (agent_root / "agent_atlas.png").write_bytes(b"PNG")
    (agent_root / "agent_atlas.json").write_text(json.dumps({"frames": {"idle_down_0.png": {}}}), encoding="utf-8")
    latest_payload = {
        "event": "new_asset_ready",
        "id": "creator_demo_agent",
        "display_name": "Creator Demo Agent",
        "atlas_url": "./assets/generated/creator_demo_agent/creator_demo_revision/agent_atlas.png",
        "json_url": "./assets/generated/creator_demo_agent/creator_demo_revision/agent_atlas.json",
        "revision": "creator_demo_revision",
        "world_id": "creator_demo_world",
        "world_name": "Creator Demo World",
        "world_revision": "creator_demo_revision",
        "default_animation": "idle_down",
        "animations": {},
        "generated_at": "2026-05-26T00:00:00+00:00",
    }
    bootstrap_payload = {
        "generated_at": "2026-05-26T00:00:00+00:00",
        "world_id": "creator_demo_world",
        "world_revision": "creator_demo_revision",
        "assets": [latest_payload],
    }
    asset_manifest = {
        "revision": "creator_demo_revision",
        "world_revision": "creator_demo_revision",
        "world_id": "creator_demo_world",
        "world_name": "Creator Demo World",
        "map_asset_url": "./assets/generated/maps/creator_map.png",
        "assets": [latest_payload],
    }
    (events_root / "latest.json").write_text(json.dumps(latest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (events_root / "bootstrap_assets.json").write_text(json.dumps(bootstrap_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (asset_set_root / "current_guild_pixel_set.json").write_text(json.dumps(asset_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    world_asset_set_root = generated_root / "world_asset_sets"
    world_asset_set_root.mkdir(parents=True, exist_ok=True)
    (world_asset_set_root / "current_world_pixel_set.json").write_text(json.dumps(asset_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (temp_root / "output").mkdir(parents=True, exist_ok=True)


class _CreatorProvider:
    def __init__(self) -> None:
        self.json_calls = 0
        self.temperature = 0.2
        self.max_output_tokens = 4096
        self.thinking_level = "high"

    def execute(self, request):  # noqa: ANN001
        if request.task_type == "json":
            self.json_calls += 1
            return FlexExecuteResponse(
                provider="fake",
                model="gemini-3.1-pro",
                output_text="",
                output_json={
                    "world_name": "Clockharbor Exchange",
                    "world_id": "clockharbor_exchange",
                    "world_seed": {
                        "seed_version": "world_seed_v2",
                        "preset_id": "coastal_trade_city",
                        "profile_id": "coastal_trade_city",
                        "locale": "en",
                        "tone": "tidal trade city with ritual astronomy",
                        "visual_direction": "weathered brass harbor pixel world",
                        "currency_code": "HBR",
                        "currency_symbol": "hc",
                        "currency_minor_unit": "mark",
                        "currency_name": "harbor chit",
                        "domain_label": "harbor logistics, route bargaining, civic trade pressure",
                        "starting_wallet_minor": {"min": 2400, "max": 11000},
                        "kit_refs": {
                            "pixel_component_kit_id": "coastal_trade_city_v1",
                            "frontend_affordance_id": "coastal_trade_city_v1",
                            "asset_prompt_kit_id": "coastal_trade_city_v1",
                        },
                        "policy_refs": {
                            "economy_policy_id": "harbor_chit_v1",
                            "item_collection_id": "harbor_trade_items_v1",
                            "inventory_layer_policy_id": "split_four_layer_v1",
                            "role_item_policy_id": "coastal_trade_city_v1",
                            "property_policy_id": "coastal_trade_city_v1",
                            "knowledge_policy_id": "coastal_trade_city_v1",
                            "inventory_layers": ["wallet", "inventory", "property_library", "knowledge_assets"],
                        },
                    },
                    "genre": "tidal trade city with ritual astronomy",
                    "premise": "A harbor city where logistics guilds, shrine keepers, and tide pilots bargain over routes, omens, and civic survival.",
                    "simulation_objective": "Support a social-economy world with discovery and faction pressure.",
                    "agent_count_target": 36,
                    "player_count_target": 4,
                    "economy_focus": "negotiated trade routes and civic supply",
                    "exploration_focus": "hidden passages, rumors, and route intelligence",
                    "conflict_tone": "pressured but cooperative",
                    "visual_style": "weathered brass harbor pixel world",
                    "rooms": [
                        {"name": "Tide Market", "biome": "coastal bazaar", "purpose": "trade and rumor exchange", "decor_tags": ["crates", "lanterns"]},
                        {"name": "Signal Tower", "biome": "high lookout", "purpose": "navigation and warning", "decor_tags": ["flags", "maps"]},
                        {"name": "Guild Quay", "biome": "working docks", "purpose": "loading, repair, and contracts", "decor_tags": ["winches", "cargo"]},
                    ],
                    "role_groups": [
                        {"role_name": "Dock Broker", "count": 12, "core_values": ["trust", "timing"], "activity": "match cargo, labor, and opportunity"},
                        {"role_name": "Route Pilot", "count": 12, "core_values": ["precision", "nerve"], "activity": "guide people and goods through risky channels"},
                        {"role_name": "Shrine Archivist", "count": 12, "core_values": ["memory", "ritual"], "activity": "interpret signs and preserve agreements"},
                    ],
                    "main_characters": [
                        {"display_name": "Nara Voss", "role_name": "Harbor Broker", "activity": "keeps the city supplied while balancing rival demands"},
                        {"display_name": "Iven Kest", "role_name": "Tide Pilot", "activity": "opens new routes and brings danger back with him"},
                        {"display_name": "Suri Vale", "role_name": "Shrine Archivist", "activity": "turns omens into leverage and decisions"},
                    ],
                    "social_rules": [
                        "Trade should create obligations and future leverage.",
                        "Rumors and route information should spread through repeated contact.",
                    ],
                    "item_themes": ["contracts", "signal codes", "repair parts", "maps"],
                },
                meta={},
            )
        return FlexExecuteResponse(
            provider="fake",
            model="gemini-3.1-pro",
            output_text=(
                "Clockharbor Exchange is a tidal city built around bargaining, route pressure, and civic interdependence.\n\n"
                "The world runs on dock contracts, ritual observatories, and trade corridors that can shift with weather and politics.\n\n"
                "Players arrive in a space where agents negotiate supply, trust, and information every round."
            ),
            output_json=None,
            meta={},
        )

    def generate_json(self, *, system_instruction: str, prompt: str, schema: dict[str, Any], stage: str = "") -> dict[str, Any] | list[Any]:
        class DummyRequest:
            task_type = "json"
        res = self.execute(DummyRequest())
        return res.output_json

    def generate_text(self, *, system_instruction: str, prompt: str, stage: str = "") -> str:
        class DummyRequest:
            task_type = "text"
        res = self.execute(DummyRequest())
        return res.output_text


class _RepairingCreatorProvider(_CreatorProvider):
    def execute(self, request):  # noqa: ANN001
        if request.task_type == "json" and self.json_calls == 0:
            self.json_calls += 1
            return FlexExecuteResponse(
                provider="fake",
                model="gemini-3.1-pro",
                output_text="[]",
                output_json=[],
                meta={},
            )
        return super().execute(request)


class _CritiquingCreatorProvider(_CreatorProvider):
    def execute(self, request):  # noqa: ANN001
        if request.task_type == "json" and self.json_calls == 1:
            self.json_calls += 1
            return FlexExecuteResponse(
                provider="fake",
                model="gemini-3.1-pro",
                output_text="",
                output_json={
                    "should_repair": True,
                    "diagnosis": [
                        "Player onboarding can be more explicit.",
                        "The main harbor tension needs one more concrete loop and action hook.",
                    ],
                    "custom_actions": ["Debate"],
                    "player_entry_points": [
                        "Arrive during a customs dispute and learn the harbor through competing explanations."
                    ],
                    "conflict_hooks": [
                        "A customs inspection wave makes ordinary trade feel politically risky."
                    ],
                    "social_rules": [
                        "Inspection pressure should force trade, routing, and information choices into the open."
                    ],
                    "loop_reinforcements": [
                        {
                            "label": "Inspection Loop",
                            "summary": "Agents respond to customs checks by rerouting cargo, negotiating permits, and trading information.",
                            "roles": ["Dock Broker", "Route Pilot", "Shrine Archivist"],
                            "rooms": ["Tide Market", "Guild Quay", "Signal Tower"],
                            "pressure": "inspection delays and selective enforcement",
                        }
                    ],
                    "role_adjustments": [
                        {
                            "role_name": "Dock Broker",
                            "home_base": "Tide Market",
                            "activity_hint": "Argue through customs bottlenecks instead of treating trade as frictionless.",
                            "starting_items": ["contracts"],
                        }
                    ],
                },
                meta={},
            )
        return super().execute(request)


class _AlwaysFailCreatorProvider:
    def __init__(self) -> None:
        self.temperature = 0.2
        self.max_output_tokens = 4096
        self.thinking_level = "high"

    def execute(self, request):  # noqa: ANN001
        raise RuntimeError("Gemini API key is required")

    def generate_json(self, *, system_instruction: str, prompt: str, schema: dict[str, Any], stage: str = "") -> dict[str, Any] | list[Any]:
        raise RuntimeError("Gemini API key is required")

    def generate_text(self, *, system_instruction: str, prompt: str, stage: str = "") -> str:
        raise RuntimeError("Gemini API key is required")


class _WrappedJsonProvider:
    def __init__(self, payload) -> None:  # noqa: ANN001
        self.payload = payload
        self.temperature = 0.2
        self.max_output_tokens = 4096
        self.thinking_level = "high"

    def execute(self, request):  # noqa: ANN001
        return FlexExecuteResponse(
            provider="fake",
            model="gemini-2.5-flash",
            output_text="",
            output_json=self.payload,
            meta={},
        )

    def generate_json(self, *, system_instruction: str, prompt: str, schema: dict[str, Any], stage: str = "") -> dict[str, Any] | list[Any]:
        class DummyRequest:
            task_type = "json"
        res = self.execute(DummyRequest())
        return res.output_json

    def generate_text(self, *, system_instruction: str, prompt: str, stage: str = "") -> str:
        class DummyRequest:
            task_type = "text"
        res = self.execute(DummyRequest())
        return res.output_text


class _RetryingJsonProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.temperature = 0.2
        self.max_output_tokens = 4096
        self.thinking_level = "high"

    def execute(self, request):  # noqa: ANN001
        self.calls += 1
        if self.calls == 1:
            return FlexExecuteResponse(
                provider="fake",
                model="gemini-2.5-flash",
                output_text='{"world_name":"Panjiayuan","rooms":[{"name":"Main Market Square"}],"main_characters":[{"display_name":"Old Master Li","arc_',
                output_json=[{"name": "Main Market Square"}, {"name": "Appraisal Alley"}],
                meta={},
            )
        return FlexExecuteResponse(
            provider="fake",
            model="gemini-2.5-flash",
            output_text='{"world_name":"Panjiayuan","world_id":"panjiayuan","world_seed":{"seed_version":"world_seed_v2","preset_id":"grounded_antique_market","profile_id":"grounded_antique_market"},"rooms":[{"name":"Main Market Square"}]}',
            output_json={
                "world_name": "Panjiayuan",
                "world_id": "panjiayuan",
                "world_seed": {
                    "seed_version": "world_seed_v2",
                    "preset_id": "grounded_antique_market",
                    "profile_id": "grounded_antique_market",
                    "locale": "zh-CN",
                    "tone": "grounded antique market",
                    "visual_direction": "weathered market realism",
                    "currency_code": "CNY",
                    "currency_symbol": "¥",
                    "currency_minor_unit": "fen",
                    "currency_name": "renminbi",
                    "domain_label": "antique market bargaining, appraisal disputes, rumor trade",
                    "starting_wallet_minor": {"min": 3000, "max": 14000},
                    "kit_refs": {
                        "pixel_component_kit_id": "grounded_antique_market_v1",
                        "frontend_affordance_id": "grounded_antique_market_v1",
                        "asset_prompt_kit_id": "grounded_antique_market_v1",
                    },
                    "policy_refs": {
                        "economy_policy_id": "cny_market_v1",
                        "item_collection_id": "antique_market_items_v1",
                        "inventory_layer_policy_id": "split_four_layer_v1",
                        "role_item_policy_id": "grounded_antique_market_v1",
                        "property_policy_id": "grounded_antique_market_v1",
                        "knowledge_policy_id": "grounded_antique_market_v1",
                        "inventory_layers": ["wallet", "inventory", "property_library", "knowledge_assets"],
                    },
                },
                "rooms": [{"name": "Main Market Square"}],
            },
            meta={},
        )

    def generate_json(self, *, system_instruction: str, prompt: str, schema: dict[str, Any], stage: str = "") -> dict[str, Any] | list[Any]:
        class DummyRequest:
            task_type = "json"
        res = self.execute(DummyRequest())
        if isinstance(res.output_json, list):
            res = self.execute(DummyRequest())
        return res.output_json

    def generate_text(self, *, system_instruction: str, prompt: str, stage: str = "") -> str:
        class DummyRequest:
            task_type = "text"
        res = self.execute(DummyRequest())
        return res.output_text


class WorldBuilderApiTest(unittest.TestCase):
    def test_load_creator_runtime_env_reads_env_file(self) -> None:
        with TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "agora_ui_runtime.env"
            env_path.write_text("AGORA_VERTEX_API_KEY=test-vertex-key\nAGORA_AISTUDIO_API_KEY=test-aistudio-key\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True), patch.object(world_builder, "GLOBAL_CREATOR_ENV_PATHS", (env_path,)):
                env = world_builder._load_creator_runtime_env()
        self.assertEqual(env["AGORA_VERTEX_API_KEY"], "test-vertex-key")
        self.assertEqual(env["AGORA_AISTUDIO_API_KEY"], "test-aistudio-key")

    def test_gemini_provider_accepts_aistudio_env_key(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AGORA_AISTUDIO_API_KEY": "AIza-demo-key",
                "AGORA_GEMINI_API_KEY": "",
                "GEMINI_API_KEY": "",
                "GOOGLE_API_KEY": "",
            },
            clear=False,
        ):
            provider = GeminiAIStudioProvider.from_env()
            self.assertEqual(provider.api_key, "AIza-demo-key")

    def test_execute_json_prompt_unwraps_singleton_object_wrappers(self) -> None:
        direct = world_builder._execute_json_prompt(
            provider=_WrappedJsonProvider([{"world_name": "Panjiayuan"}]),
            system_instruction="Return JSON.",
            prompt="Test",
            response_schema={"type": "object"},
        )
        nested = world_builder._execute_json_prompt(
            provider=_WrappedJsonProvider({"builder_spec": {"world_name": "Panjiayuan"}}),
            system_instruction="Return JSON.",
            prompt="Test",
            response_schema={"type": "object"},
        )
        self.assertEqual(direct["world_name"], "Panjiayuan")
        self.assertEqual(nested["world_name"], "Panjiayuan")

    def test_first_json_value_from_text_prefers_top_level_object_over_nested_array(self) -> None:
        text = """
        {
          "world_name": "Panjiayuan",
          "rooms": [
            {"name": "Grand Bazaar Hall"},
            {"name": "Jade Alley"}
          ],
          "role_groups": [
            {"role_name": "Vendor"}
          ]
        }
        """
        parsed = first_json_value_from_text(text)
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed["world_name"], "Panjiayuan")

    def test_execute_json_prompt_retries_truncated_object_text(self) -> None:
        provider = _RetryingJsonProvider()
        payload = world_builder._execute_json_prompt(
            provider=provider,
            system_instruction="Return JSON only.",
            prompt="Test prompt",
            response_schema={"type": "object"},
        )
        self.assertEqual(payload["world_name"], "Panjiayuan")
        self.assertEqual(provider.calls, 2)

    def test_compiler_strengthens_loops_routes_and_role_directives(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            _prepare_creator_root(temp_root)
            request = {
                "world_name": "Clockharbor Exchange",
                "genre": "tidal trade city",
                "player_count_target": 4,
                "agent_count_target": 36,
                "focus": "economy, exploration, and faction tension",
                "seed": 42627,
                "brief": "A harbor city where route brokers, tide pilots, and shrine archivists create a living economy under customs pressure.",
            }
            builder_spec = world_builder._normalize_builder_spec(
                {
                    "world_name": "Clockharbor Exchange",
                    "world_id": "clockharbor_exchange",
                    "world_seed": {
                        "seed_version": "world_seed_v2",
                        "preset_id": "coastal_trade_city",
                        "profile_id": "coastal_trade_city",
                        "locale": "en",
                        "tone": "tidal trade city with ritual astronomy",
                        "visual_direction": "weathered brass harbor pixel world",
                        "currency_code": "HBR",
                        "currency_symbol": "hc",
                        "currency_minor_unit": "mark",
                        "currency_name": "harbor chit",
                        "domain_label": "harbor logistics, route bargaining, civic trade pressure",
                        "starting_wallet_minor": {"min": 2400, "max": 11000},
                        "kit_refs": {
                            "pixel_component_kit_id": "coastal_trade_city_v1",
                            "frontend_affordance_id": "coastal_trade_city_v1",
                            "asset_prompt_kit_id": "coastal_trade_city_v1",
                        },
                        "policy_refs": {
                            "economy_policy_id": "harbor_chit_v1",
                            "item_collection_id": "harbor_trade_items_v1",
                            "inventory_layer_policy_id": "split_four_layer_v1",
                            "role_item_policy_id": "coastal_trade_city_v1",
                            "property_policy_id": "coastal_trade_city_v1",
                            "knowledge_policy_id": "coastal_trade_city_v1",
                            "inventory_layers": ["wallet", "inventory", "property_library", "knowledge_assets"],
                        },
                    },
                    "genre": "tidal trade city with ritual astronomy",
                    "premise": "A harbor city where logistics guilds, shrine keepers, and tide pilots bargain over routes, omens, and civic survival.",
                    "simulation_objective": "Support a social-economy world with discovery and faction pressure.",
                    "agent_count_target": 36,
                    "player_count_target": 4,
                    "economy_focus": "negotiated trade routes and civic supply",
                    "exploration_focus": "hidden passages, rumors, and route intelligence",
                    "conflict_tone": "pressured but cooperative",
                    "visual_style": "weathered brass harbor pixel world",
                    "rooms": [
                        {"name": "Tide Market", "biome": "coastal bazaar", "purpose": "trade and rumor exchange", "decor_tags": ["crates", "lanterns"]},
                        {"name": "Signal Tower", "biome": "high lookout", "purpose": "navigation and warning", "decor_tags": ["flags", "maps"]},
                        {"name": "Guild Quay", "biome": "working docks", "purpose": "loading, repair, and contracts", "decor_tags": ["winches", "cargo"]},
                    ],
                    "role_groups": [
                        {"role_name": "Dock Broker", "count": 12, "core_values": ["trust", "timing"], "activity": "match cargo, labor, and opportunity", "home_base": "Tide Market", "starting_items": ["contracts", "rations"]},
                        {"role_name": "Route Pilot", "count": 12, "core_values": ["precision", "nerve"], "activity": "guide people and goods through risky channels", "home_base": "Signal Tower", "starting_items": ["maps"]},
                        {"role_name": "Shrine Archivist", "count": 12, "core_values": ["memory", "ritual"], "activity": "interpret signs and preserve agreements", "home_base": "Guild Quay", "starting_items": ["signal codes", "ritual crystal"]},
                    ],
                    "main_characters": [
                        {"display_name": "Nara Voss", "role_name": "Harbor Broker", "activity": "keeps the city supplied while balancing rival demands", "home_base": "Tide Market"},
                        {"display_name": "Iven Kest", "role_name": "Tide Pilot", "activity": "opens new routes and brings danger back with him", "home_base": "Signal Tower"},
                        {"display_name": "Suri Vale", "role_name": "Shrine Archivist", "activity": "turns omens into leverage and decisions", "home_base": "Guild Quay"},
                    ],
                    "social_rules": [
                        "Trade should create obligations and future leverage.",
                        "Rumors and route information should spread through repeated contact.",
                    ],
                    "item_themes": ["contracts", "signal codes", "repair parts", "maps"],
                },
                request,
            )
            config = world_builder._build_world_config_from_spec(temp_root, builder_spec, request)
            self.assertGreaterEqual(len(config["world_progress"]["gameplay_loops"]), 3)
            self.assertGreaterEqual(len(config["scenario_meta"]["player_entry_points"]), 3)
            self.assertTrue(any(route.get("actor_role_ids") for route in config["actions"]["ordinary_routes"] if isinstance(route, dict)))
            self.assertIn("CinematicInteraction", config["actions"]["allowed_custom_actions"])
            self.assertTrue(config["extra_world_functions"]["enabled"])
            self.assertGreaterEqual(len(config["extra_world_functions"]["functions"]), 3)
            self.assertTrue(
                any(
                    "player" in str(function.get("purpose", "")).lower() or "newcomer" in str(function.get("purpose", "")).lower()
                    for function in config["extra_world_functions"]["functions"]
                )
            )
            self.assertTrue(all(str(group.get("home_room_id", "")).strip() for group in config["agent_generation"]["role_groups"]))
            self.assertTrue(all(str(group.get("activity_directive", "")).strip() for group in config["agent_generation"]["role_groups"]))
            scenario_dir = temp_root / "compiled_scenario"
            materialize_scenario(config, scenario_dir)
            first_agent = json.loads(next((scenario_dir / "Agents").glob("*.json")).read_text(encoding="utf-8"))
            self.assertTrue(str(first_agent["public_state"].get("activity_directive", "")).strip())
            self.assertTrue(str(first_agent["public_state"].get("home_room_id", "")).strip())

    def test_compiler_emits_world_neutral_ids_and_market_inventory(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            _prepare_creator_root(temp_root)
            request = {
                "world_name": "Panjiayuan",
                "genre": "antique market district",
                "player_count_target": 4,
                "agent_count_target": 30,
                "focus": "economy, appraisal, and rumor",
                "seed": 42627,
                "brief": "A dense antiques market full of bargaining, appraisal, and rumor-driven treasure hunting.",
            }
            builder_spec = world_builder._normalize_builder_spec(
                {
                    "world_name": "Panjiayuan",
                    "world_id": "panjiayuan",
                    "world_seed": {
                        "seed_version": "world_seed_v2",
                        "preset_id": "grounded_antique_market",
                        "profile_id": "grounded_antique_market",
                        "locale": "zh-CN",
                        "tone": "antique market district",
                        "visual_direction": "crowded market pixel world",
                        "currency_code": "CNY",
                        "currency_symbol": "¥",
                        "currency_minor_unit": "fen",
                        "currency_name": "renminbi",
                        "domain_label": "antique market bargaining, appraisal disputes, rumor trade",
                        "starting_wallet_minor": {"min": 3000, "max": 14000},
                        "kit_refs": {
                            "pixel_component_kit_id": "grounded_antique_market_v1",
                            "frontend_affordance_id": "grounded_antique_market_v1",
                            "asset_prompt_kit_id": "grounded_antique_market_v1",
                        },
                        "policy_refs": {
                            "economy_policy_id": "cny_market_v1",
                            "item_collection_id": "antique_market_items_v1",
                            "inventory_layer_policy_id": "split_four_layer_v1",
                            "role_item_policy_id": "grounded_antique_market_v1",
                            "property_policy_id": "grounded_antique_market_v1",
                            "knowledge_policy_id": "grounded_antique_market_v1",
                            "inventory_layers": ["wallet", "inventory", "property_library", "knowledge_assets"],
                        },
                    },
                    "genre": "antique market district",
                    "premise": "Dealers, scouts, and appraisers bargain over provenance and hidden value.",
                    "simulation_objective": "Keep a market world legible and negotiable.",
                    "agent_count_target": 30,
                    "player_count_target": 4,
                    "economy_focus": "bargaining and appraisal",
                    "exploration_focus": "rumor trails and hidden stock",
                    "conflict_tone": "tense but social",
                    "visual_style": "crowded market pixel world",
                    "rooms": [
                        {"name": "Main Market Square", "biome": "open bazaar", "purpose": "trade and appraisal", "decor_tags": ["stalls", "lanterns"], "activity_tags": ["bargain", "appraise"]},
                        {"name": "Appraiser's Alley", "biome": "covered lane", "purpose": "authentication and rumor exchange", "decor_tags": ["ledgers", "scrolls"], "activity_tags": ["verify", "whisper"]},
                        {"name": "Warehouse Court", "biome": "storage yard", "purpose": "sorting stock and securing deliveries", "decor_tags": ["crates", "carts"], "activity_tags": ["sort", "haul"]},
                    ],
                    "role_groups": [
                        {"role_name": "Antique Broker", "count": 10, "core_values": ["credibility", "timing"], "activity": "broker deals and compare provenance", "home_base": "Main Market Square", "starting_items": ["contracts", "permits"]},
                        {"role_name": "Appraiser", "count": 10, "core_values": ["memory", "discernment"], "activity": "verify authenticity and advise buyers", "home_base": "Appraiser's Alley", "starting_items": ["records", "maps"]},
                        {"role_name": "Runner", "count": 10, "core_values": ["speed", "discretion"], "activity": "move goods and rumors between stalls", "home_base": "Warehouse Court", "starting_items": ["route notes", "rations"]},
                    ],
                    "main_characters": [
                        {"display_name": "Old Master Li", "role_name": "Broker", "activity": "keeps the market balanced while chasing a valuable rumor", "home_base": "Main Market Square"},
                    ],
                    "social_rules": ["A deal should create new leverage."],
                    "item_themes": ["contracts", "maps", "permits"],
                },
                request,
            )
            config = world_builder._build_world_config_from_spec(temp_root, builder_spec, request)
            self.assertEqual(config["runner"]["agent_id_prefix"], "agent")
            self.assertEqual(config["agent_generation"]["agent_id_prefix"], "agent")
            self.assertEqual(config["pixel_asset_pipeline"]["frontend"]["asset_set_manifest_path"], "./assets/generated/world_asset_sets/current_world_pixel_set.json")
            self.assertNotEqual(config["human_interaction"]["default_room_id"], "guild_hall")
            self.assertTrue(all(not str(room.get("room_id", "")).startswith("guild") for room in config["space"]["rooms"]))
            self.assertTrue(all(not str(entry.get("agent_id", "")).startswith("guild_main") for entry in config["main_characters"]))
            broker_group = next(group for group in config["agent_generation"]["role_groups"] if str(group.get("role_name")) == "Antique Broker")
            broker_items = [str(item.get("item_id", "")) for item in broker_group.get("inventory", []) if isinstance(item, dict)]
            self.assertIn("consignment_note", broker_items)
            self.assertNotIn("gold", broker_items)
            self.assertTrue(any(str(room.get("metadata", {}).get("room_archetype", "")).strip() for room in config["space"]["rooms"]))

    def test_create_draft_and_download_package(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            _prepare_creator_root(temp_root)
            provider = _CreatorProvider()
            with (
                patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root),
                patch.object(world_builder, "_world_creator_provider", return_value=provider),
            ):
                draft = serve_macro_ui.api_world_builder_create_draft(
                    serve_macro_ui.WorldBuilderDraftCreateRequest(
                        world_name="Clockharbor Exchange",
                        genre="tidal trade city",
                        player_count_target=4,
                        agent_count_target=36,
                        focus="economy and exploration",
                        seed=42627,
                        brief="A harbor city where route brokers, tide pilots, and shrine archivists create a living economy.",
                    )
                )
                self.assertEqual(draft["status"], world_builder.STATUS_DRAFT_READY)
                self.assertTrue(draft["world_summary_markdown"])
                self.assertTrue(draft["current_revision_data"]["package_validation"]["materialize_ok"])
                self.assertTrue(draft["current_revision_data"]["startup_validation"]["startup_ok"])
                self.assertIn("compiler_critique", draft["current_revision_data"])
                self.assertIn("compiled_preview", draft["current_revision_data"])
                self.assertIn("event_functions", draft["current_revision_data"]["compiled_preview"])
                package_response = serve_macro_ui.api_world_builder_draft_package(draft["draft_id"])
                self.assertTrue(str(package_response.path).endswith(".db"))
                self.assertTrue(Path(package_response.path).is_file())
                catalog = serve_macro_ui.api_pixel_worlds()
                self.assertEqual(catalog["worlds"], [])

    def test_revise_draft_creates_new_revision(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            _prepare_creator_root(temp_root)
            provider = _CreatorProvider()
            with (
                patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root),
                patch.object(world_builder, "_world_creator_provider", return_value=provider),
            ):
                draft = serve_macro_ui.api_world_builder_create_draft(
                    serve_macro_ui.WorldBuilderDraftCreateRequest(
                        world_name="Clockharbor Exchange",
                        genre="tidal trade city",
                        player_count_target=4,
                        agent_count_target=36,
                        focus="economy",
                        seed=42627,
                        brief="A harbor city where route brokers, tide pilots, and shrine archivists create a living economy.",
                    )
                )
                revised = serve_macro_ui.api_world_builder_revise_draft(
                    draft["draft_id"],
                    serve_macro_ui.WorldBuilderDraftReviseRequest(
                        feedback="Make the world less stable, add a customs checkpoint vibe, and increase faction suspicion."
                    ),
                )
                self.assertEqual(revised["current_revision"], "r002")
                self.assertEqual(len(revised["history"]), 2)
                self.assertEqual(revised["status"], world_builder.STATUS_DRAFT_READY)

    def test_world_name_must_be_unique_across_drafts(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            _prepare_creator_root(temp_root)
            provider = _CreatorProvider()
            with (
                patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root),
                patch.object(world_builder, "_world_creator_provider", return_value=provider),
            ):
                serve_macro_ui.api_world_builder_create_draft(
                    serve_macro_ui.WorldBuilderDraftCreateRequest(
                        world_name="Clockharbor Exchange",
                        genre="tidal trade city",
                        player_count_target=4,
                        agent_count_target=36,
                        focus="economy",
                        seed=42627,
                        brief="A harbor city where route brokers, tide pilots, and shrine archivists create a living economy.",
                    )
                )
                with self.assertRaises(HTTPException) as exc:
                    serve_macro_ui.api_world_builder_create_draft(
                        serve_macro_ui.WorldBuilderDraftCreateRequest(
                            world_name="Clockharbor Exchange",
                            genre="different draft attempt",
                            player_count_target=4,
                            agent_count_target=36,
                            focus="story",
                            seed=42627,
                            brief="Try to create the same world again.",
                        )
                    )
                self.assertEqual(exc.exception.status_code, 400)
                self.assertIn("already in use", str(exc.exception.detail))

    def test_resolve_draft_by_world_name_and_world_id(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            _prepare_creator_root(temp_root)
            provider = _CreatorProvider()
            with (
                patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root),
                patch.object(world_builder, "_world_creator_provider", return_value=provider),
            ):
                draft = serve_macro_ui.api_world_builder_create_draft(
                    serve_macro_ui.WorldBuilderDraftCreateRequest(
                        world_name="Clockharbor Exchange",
                        genre="tidal trade city",
                        player_count_target=4,
                        agent_count_target=36,
                        focus="economy",
                        seed=42627,
                        brief="A harbor city where route brokers, tide pilots, and shrine archivists create a living economy.",
                    )
                )
                resolved_by_name = serve_macro_ui.api_world_builder_resolve(identifier="Clockharbor Exchange")
                resolved_by_id = serve_macro_ui.api_world_builder_resolve(identifier="clockharbor_exchange")
                self.assertEqual(resolved_by_name["matched_by"], "world_name")
                self.assertEqual(resolved_by_id["matched_by"], "world_id")
                self.assertEqual(resolved_by_name["draft"]["draft_id"], draft["draft_id"])
                self.assertEqual(resolved_by_id["draft"]["draft_id"], draft["draft_id"])

    def test_create_draft_repair_path_recovers_from_bad_first_json(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            _prepare_creator_root(temp_root)
            provider = _RepairingCreatorProvider()
            with (
                patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root),
                patch.object(world_builder, "_world_creator_provider", return_value=provider),
            ):
                draft = serve_macro_ui.api_world_builder_create_draft(
                    serve_macro_ui.WorldBuilderDraftCreateRequest(
                        world_name="Repair World",
                        genre="repairable world",
                        player_count_target=3,
                        agent_count_target=30,
                        focus="story",
                        seed=42627,
                        brief="Create a repairable world.",
                    )
                )
                self.assertEqual(draft["status"], world_builder.STATUS_DRAFT_READY)
                self.assertGreaterEqual(provider.json_calls, 2)

    def test_revise_failed_draft_reuses_original_input_brief(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            _prepare_creator_root(temp_root)
            with (
                patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root),
                patch.object(world_builder, "_world_creator_provider", return_value=_AlwaysFailCreatorProvider()),
            ):
                draft = serve_macro_ui.api_world_builder_create_draft(
                    serve_macro_ui.WorldBuilderDraftCreateRequest(
                        world_name="Panjiayuan",
                        genre="market world",
                        player_count_target=4,
                        agent_count_target=30,
                        focus="economy",
                        seed=42627,
                        brief="A tense antiques market full of bargaining, counterfeit goods, and rumor-driven treasure hunting.",
                    )
                )
                self.assertEqual(draft["status"], world_builder.STATUS_DRAFT_FAILED)

            captured: dict[str, object] = {}

            def _fake_generate_revision(*, package_root, draft_id, revision_id, request, prior_context, feedback):  # noqa: ANN001
                captured["request"] = dict(request)
                return {
                    "draft_id": draft_id,
                    "revision_id": revision_id,
                    "created_at": "2026-05-26T00:00:00+00:00",
                    "status": world_builder.STATUS_DRAFT_READY,
                    "world_name": "Panjiayuan",
                    "world_id": "panjiayuan",
                    "summary_path": "",
                    "package_path": "",
                    "world_config_path": "",
                    "scenario_dir": "",
                    "structured_summary": world_builder.WorldBuilderStructuredSummarySpec().model_dump(),
                    "compiler_critique": {},
                    "compiled_preview": {},
                    "package_validation": {},
                    "world_summary_markdown": "",
                    "error": "",
                }

            with (
                patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root),
                patch.object(world_builder, "_generate_revision", side_effect=_fake_generate_revision),
            ):
                revised = serve_macro_ui.api_world_builder_revise_draft(
                    draft["draft_id"],
                    serve_macro_ui.WorldBuilderDraftReviseRequest(
                        feedback="Retry with the same setting, but keep the bargaining dynamic clear."
                    ),
                )
                self.assertEqual(revised["current_revision"], "r002")
                self.assertEqual(
                    captured["request"]["brief"],
                    "A tense antiques market full of bargaining, counterfeit goods, and rumor-driven treasure hunting.",
                )

    def test_compiler_critique_auto_repairs_world_config(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            _prepare_creator_root(temp_root)
            provider = _CritiquingCreatorProvider()
            with (
                patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root),
                patch.object(world_builder, "_world_creator_provider", return_value=provider),
            ):
                draft = serve_macro_ui.api_world_builder_create_draft(
                    serve_macro_ui.WorldBuilderDraftCreateRequest(
                        world_name="Clockharbor Exchange",
                        genre="tidal trade city",
                        player_count_target=4,
                        agent_count_target=36,
                        focus="economy and faction tension",
                        seed=42627,
                        brief="A harbor city where route brokers, tide pilots, and shrine archivists create a living economy.",
                    )
                )
                config_path = world_builder._revision_world_config_path(temp_root, draft["draft_id"], draft["current_revision"])
                critique_path = world_builder._revision_compiler_critique_path(temp_root, draft["draft_id"], draft["current_revision"])
                config = json.loads(config_path.read_text(encoding="utf-8"))
                critique = json.loads(critique_path.read_text(encoding="utf-8"))
                self.assertTrue(critique["should_repair"])
                self.assertIn("Debate", config["actions"]["allowed_custom_actions"])
                self.assertTrue(
                    any(
                        "customs dispute" in str(entry).lower()
                        for entry in config["scenario_meta"]["player_entry_points"]
                    )
                )
                self.assertTrue(
                    any(
                        str(loop.get("label", "")) == "Inspection Loop"
                        for loop in config["world_progress"]["gameplay_loops"]
                    )
                )
                self.assertTrue(
                    any(
                        "customs dispute" in str(function.get("event_policy", "")).lower()
                        or "customs" in str(function.get("event_policy", "")).lower()
                        for function in config["extra_world_functions"]["functions"]
                    )
                )
                self.assertTrue(draft["current_revision_data"]["package_validation"]["compiler_critique_applied"])

    def test_art_pipeline_and_publish_make_world_public(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            _prepare_creator_root(temp_root)
            provider = _CreatorProvider()
            with (
                patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root),
                patch.object(world_builder, "_world_creator_provider", return_value=provider),
                patch.object(world_builder, "_run_worker_command", return_value={"command": ["fake"], "returncode": 0, "stdout": "", "stderr": ""}),
                patch.object(
                    world_builder,
                    "_repack_revision_package_with_current_assets",
                    return_value={"package_db": temp_root / "world_package.db", "pixel_report": {"pixel_read": True, "details": []}, "asset_count": 1},
                ),
                patch.object(world_builder, "validate_pixel_ui_launch", return_value={
                    "startup_ok": True,
                    "stage": "ok",
                    "expected_access_code": "launch_test_access",
                    "selected_access_code": "launch_test_access",
                    "startup_status_text": "Pixel UI ready",
                    "session_endpoint": "/api/pixel/worlds/launch_test_access/live/sessions",
                    "screenshot_path": "/tmp/pixel.png",
                    "error": "",
                }),
                patch.object(build_macro_ui, "validate_pixel_ui_launch", return_value={
                    "startup_ok": True,
                    "stage": "ok",
                    "expected_access_code": "publish_test_access",
                    "selected_access_code": "publish_test_access",
                    "startup_status_text": "Pixel UI ready",
                    "session_endpoint": "/api/pixel/worlds/publish_test_access/live/sessions",
                    "screenshot_path": "/tmp/pixel.png",
                    "error": "",
                }),
            ):
                draft = serve_macro_ui.api_world_builder_create_draft(
                    serve_macro_ui.WorldBuilderDraftCreateRequest(
                        world_name="Clockharbor Exchange",
                        genre="tidal trade city",
                        player_count_target=4,
                        agent_count_target=36,
                        focus="economy",
                        seed=42627,
                        brief="A harbor city where route brokers, tide pilots, and shrine archivists create a living economy.",
                    )
                )
                draft_id = str(draft["draft_id"])
                revision_id = str(draft["current_revision"])
                art_payload = world_builder.run_art_pipeline(temp_root, draft_id, revision_id)
                self.assertEqual(art_payload["status"], world_builder.STATUS_PUBLISH_READY)
                self.assertTrue(art_payload["startup_validation"]["startup_ok"])
                self.assertTrue(art_payload["pixel_launch_validation"]["startup_ok"])
                published = serve_macro_ui.api_world_builder_publish(draft_id)
                self.assertEqual(published["publish"]["status"], world_builder.STATUS_PUBLISHED)
                self.assertTrue(published["publish"]["startup_validation"]["startup_ok"])
                self.assertTrue(published["publish"]["pixel_launch_validation"]["startup_ok"])
                access_code = str(published["published_access_code"])
                self.assertTrue(access_code)

    def test_art_pipeline_fails_when_pixel_launch_validation_fails(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            _prepare_creator_root(temp_root)
            provider = _CreatorProvider()
            with (
                patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root),
                patch.object(world_builder, "_world_creator_provider", return_value=provider),
                patch.object(world_builder, "_run_worker_command", return_value={"command": ["fake"], "returncode": 0, "stdout": "", "stderr": ""}),
                patch.object(
                    world_builder,
                    "_repack_revision_package_with_current_assets",
                    return_value={"package_db": temp_root / "world_package.db", "pixel_report": {"pixel_read": True, "details": []}, "asset_count": 1},
                ),
                patch.object(world_builder, "validate_pixel_ui_launch", return_value={
                    "startup_ok": False,
                    "stage": "pixel_launch",
                    "expected_access_code": "launch_test_access",
                    "selected_access_code": "wrong_access",
                    "startup_status_text": "Startup failed",
                    "session_endpoint": "",
                    "screenshot_path": "/tmp/pixel.png",
                    "error": "headless failure",
                }),
            ):
                draft = serve_macro_ui.api_world_builder_create_draft(
                    serve_macro_ui.WorldBuilderDraftCreateRequest(
                        world_name="Clockharbor Exchange",
                        genre="tidal trade city",
                        player_count_target=4,
                        agent_count_target=36,
                        focus="economy",
                        seed=42627,
                        brief="A harbor city where route brokers, tide pilots, and shrine archivists create a living economy.",
                    )
                )
                art_payload = world_builder.run_art_pipeline(temp_root, draft["draft_id"], draft["current_revision"])
                self.assertEqual(art_payload["status"], world_builder.STATUS_ART_FAILED)
                self.assertFalse(art_payload["startup_validation"]["startup_ok"])
                self.assertEqual(art_payload["pixel_launch_validation"]["stage"], "pixel_launch")

    def test_publish_does_not_update_manifest_when_pixel_launch_validation_fails(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            _prepare_creator_root(temp_root)
            provider = _CreatorProvider()
            with (
                patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root),
                patch.object(world_builder, "_world_creator_provider", return_value=provider),
                patch.object(world_builder, "_run_worker_command", return_value={"command": ["fake"], "returncode": 0, "stdout": "", "stderr": ""}),
                patch.object(
                    world_builder,
                    "_repack_revision_package_with_current_assets",
                    return_value={"package_db": temp_root / "world_package.db", "pixel_report": {"pixel_read": True, "details": []}, "asset_count": 1},
                ),
                patch.object(world_builder, "validate_pixel_ui_launch", return_value={
                    "startup_ok": True,
                    "stage": "ok",
                    "expected_access_code": "launch_test_access",
                    "selected_access_code": "launch_test_access",
                    "startup_status_text": "Pixel UI ready",
                    "session_endpoint": "/api/pixel/worlds/launch_test_access/live/sessions",
                    "screenshot_path": "/tmp/pixel.png",
                    "error": "",
                }),
            ):
                draft = serve_macro_ui.api_world_builder_create_draft(
                    serve_macro_ui.WorldBuilderDraftCreateRequest(
                        world_name="Clockharbor Exchange",
                        genre="tidal trade city",
                        player_count_target=4,
                        agent_count_target=36,
                        focus="economy",
                        seed=42627,
                        brief="A harbor city where route brokers, tide pilots, and shrine archivists create a living economy.",
                    )
                )
                print("DEBUG DRAFT:", json.dumps(draft, indent=2))
                world_builder.run_art_pipeline(temp_root, draft["draft_id"], draft["current_revision"])

            with (
                patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root),
                patch.object(build_macro_ui, "validate_pixel_ui_launch", return_value={
                    "startup_ok": False,
                    "stage": "pixel_launch",
                    "expected_access_code": "publish_test_access",
                    "selected_access_code": "wrong_access",
                    "startup_status_text": "Startup failed",
                    "session_endpoint": "",
                    "screenshot_path": "/tmp/pixel.png",
                    "error": "headless failure",
                }),
            ):
                with self.assertRaises(HTTPException) as exc:
                    serve_macro_ui.api_world_builder_publish(draft["draft_id"])
                self.assertEqual(exc.exception.status_code, 500)
                manifest = world_builder._load_manifest(temp_root, draft["draft_id"])
                self.assertEqual(str(manifest.get("status", "")), world_builder.STATUS_PUBLISH_READY)
                self.assertEqual(str(manifest.get("published_access_code", "")), "")

    def test_create_draft_fails_when_startup_validation_fails(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            _prepare_creator_root(temp_root)
            provider = _CreatorProvider()
            with (
                patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root),
                patch.object(world_builder, "_world_creator_provider", return_value=provider),
                patch.object(world_builder, "_startup_validation_for_package_db", return_value={"startup_ok": False, "error": "boom"}),
            ):
                draft = serve_macro_ui.api_world_builder_create_draft(
                    serve_macro_ui.WorldBuilderDraftCreateRequest(
                        world_name="Clockharbor Exchange",
                        genre="tidal trade city",
                        player_count_target=4,
                        agent_count_target=36,
                        focus="economy",
                        seed=42627,
                        brief="A harbor city where route brokers, tide pilots, and shrine archivists create a living economy.",
                    )
                )
                self.assertEqual(draft["status"], world_builder.STATUS_DRAFT_FAILED)
                self.assertEqual(draft["current_revision_data"]["status"], world_builder.STATUS_DRAFT_FAILED)
                self.assertIn("startup validation failed", draft["current_revision_data"]["error"].lower())

    def test_art_pipeline_fails_after_retry_if_pixel_read_never_passes(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            _prepare_creator_root(temp_root)
            provider = _CreatorProvider()
            with (
                patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root),
                patch.object(world_builder, "_world_creator_provider", return_value=provider),
                patch.object(world_builder, "_run_worker_command", return_value={"command": ["fake"], "returncode": 0, "stdout": "", "stderr": ""}),
                patch.object(
                    world_builder,
                    "_repack_revision_package_with_current_assets",
                    return_value={
                        "package_db": temp_root / "world_package.db",
                        "pixel_report": {"pixel_read": False, "missing_resources": ["assets/generated/events/bootstrap_assets.json"]},
                        "asset_count": 0,
                    },
                ),
            ):
                draft = serve_macro_ui.api_world_builder_create_draft(
                    serve_macro_ui.WorldBuilderDraftCreateRequest(
                        world_name="Clockharbor Exchange",
                        genre="tidal trade city",
                        player_count_target=4,
                        agent_count_target=36,
                        focus="economy",
                        seed=42627,
                        brief="A harbor city where route brokers, tide pilots, and shrine archivists create a living economy.",
                    )
                )
                art_payload = world_builder.run_art_pipeline(temp_root, draft["draft_id"], draft["current_revision"])
                self.assertEqual(art_payload["status"], world_builder.STATUS_ART_FAILED)

    def test_isolated_revision_asset_workspace_uses_revision_specific_manifest_and_feeds(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            _prepare_creator_root(temp_root)
            draft_id = "creator_test_harbor"
            revision_id = "r001"
            revision_slug = f"{draft_id}_{revision_id}"
            revision_dir = world_builder._revision_dir(temp_root, draft_id, revision_id)
            scenario_dir = revision_dir / "scenario"
            scenario_dir.mkdir(parents=True, exist_ok=True)
            world_config = {
                "scenario_meta": {
                    "world_id": "clockharbor_exchange_autonomous",
                    "world_name": "Clockharbor Exchange",
                },
                "pixel_asset_pipeline": {
                    "frontend": {
                        "asset_set_manifest_path": "./assets/generated/world_asset_sets/current_world_pixel_set.json",
                        "bootstrap_feed_path": "./assets/generated/events/bootstrap_assets.json",
                        "event_feed_path": "./assets/generated/events/latest.json",
                        "map_asset_url": "./assets/generated/maps/creator_map.png",
                    }
                },
                "runtime": {"seed": 42627},
            }
            (revision_dir / "world_config.json").write_text(json.dumps(world_config, ensure_ascii=False, indent=2), encoding="utf-8")
            (scenario_dir / "manifest.json").write_text(
                json.dumps({"scenario_id": revision_slug, "asset_bindings": {"active_agents": []}}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (scenario_dir / "map_grid.json").write_text(json.dumps({"rooms": []}, ensure_ascii=False, indent=2), encoding="utf-8")

            generated_root = temp_root / "frontend" / "assets" / "generated"
            harbor_agent_dir = generated_root / "agent_001" / revision_slug
            harbor_agent_dir.mkdir(parents=True, exist_ok=True)
            (harbor_agent_dir / "agent_atlas.png").write_bytes(b"PNG")
            (harbor_agent_dir / "agent_atlas.json").write_text(json.dumps({"frames": {"idle_down_0.png": {}}}), encoding="utf-8")
            revision_asset = {
                "event": "new_asset_ready",
                "id": "agent_001",
                "display_name": "Harbor Broker",
                "atlas_url": f"./assets/generated/agent_001/{revision_slug}/agent_atlas.png",
                "json_url": f"./assets/generated/agent_001/{revision_slug}/agent_atlas.json",
                "revision": revision_slug,
                "world_id": "clockharbor_exchange_autonomous",
                "world_name": "Clockharbor Exchange",
                "world_revision": revision_slug,
                "default_animation": "idle_down",
                "animations": {},
                "generated_at": "2026-05-29T00:00:00+00:00",
            }
            pan_asset = {
                "event": "new_asset_ready",
                "id": "agent_004",
                "display_name": "Pan Dealer",
                "atlas_url": "./assets/generated/agent_004/pan_rev/agent_atlas.png",
                "json_url": "./assets/generated/agent_004/pan_rev/agent_atlas.json",
                "revision": "pan_rev",
                "world_id": "panjiayuan_autonomous_2026052802",
                "world_name": "Panjiayuan",
                "world_revision": "creator_pan_r001",
                "default_animation": "idle_down",
                "animations": {},
                "generated_at": "2026-05-29T00:00:00+00:00",
            }
            manifest_payload = {
                "revision": revision_slug,
                "world_revision": revision_slug,
                "world_id": "clockharbor_exchange_autonomous",
                "world_name": "Clockharbor Exchange",
                "map_asset_url": "./assets/generated/maps/creator_map.png",
                "assets": [revision_asset],
            }
            harbor_manifest_dir = generated_root / "world_asset_sets" / revision_slug
            harbor_manifest_dir.mkdir(parents=True, exist_ok=True)
            (harbor_manifest_dir / "world_asset_set_manifest.json").write_text(
                json.dumps(manifest_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (generated_root / "world_asset_sets" / "current_world_pixel_set.json").write_text(
                json.dumps(
                    {
                        "revision": "creator_pan_r001",
                        "world_revision": "creator_pan_r001",
                        "world_id": "panjiayuan_autonomous_2026052802",
                        "world_name": "Panjiayuan",
                        "assets": [pan_asset],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            events_root = generated_root / "events"
            events_root.mkdir(parents=True, exist_ok=True)
            (events_root / "bootstrap_assets.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-05-29T00:00:00+00:00",
                        "world_id": "panjiayuan_autonomous_2026052802",
                        "world_revision": "creator_pan_r001",
                        "assets": [pan_asset, revision_asset],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (events_root / "latest.json").write_text(json.dumps(pan_asset, ensure_ascii=False, indent=2), encoding="utf-8")

            isolated_root = temp_root / "isolated_workspace"
            _, filtered_assets, _ = world_builder._isolated_revision_asset_workspace(
                temp_root,
                draft_id,
                revision_id,
                target_root=isolated_root,
            )

            isolated_manifest = json.loads(
                (isolated_root / "assets" / "generated" / "world_asset_sets" / "current_world_pixel_set.json").read_text(encoding="utf-8")
            )
            isolated_bootstrap = json.loads(
                (isolated_root / "assets" / "generated" / "events" / "bootstrap_assets.json").read_text(encoding="utf-8")
            )
            isolated_latest = json.loads(
                (isolated_root / "assets" / "generated" / "events" / "latest.json").read_text(encoding="utf-8")
            )

            self.assertEqual(isolated_manifest["world_id"], "clockharbor_exchange_autonomous")
            self.assertEqual(isolated_manifest["world_revision"], revision_slug)
            self.assertEqual(len(filtered_assets), 1)
            self.assertEqual(len(isolated_bootstrap["assets"]), 1)
            self.assertEqual(isolated_bootstrap["assets"][0]["world_revision"], revision_slug)
            self.assertEqual(isolated_latest["world_revision"], revision_slug)


class WorldCreatorUiRouteTest(unittest.TestCase):
    def test_creator_route_loads(self) -> None:
        creator_mount = next(
            route
            for route in serve_macro_ui.app.routes
            if getattr(route, "path", "") == "/creator"
        )
        self.assertIsNotNone(creator_mount)
        index_path = ROOT / "world_creator_ui" / "index.html"
        self.assertTrue(index_path.is_file())
        self.assertIn("World Creator UI", index_path.read_text(encoding="utf-8"))

    def test_validate_pixel_ui_launch_uses_resolved_runtime_python(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            export_dir = temp_root / "output" / "package_exports" / "launch_test_access"
            export_dir.mkdir(parents=True, exist_ok=True)
            (export_dir / "world_package.db").write_bytes(b"sqlite")
            scripts_dir = temp_root / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            (scripts_dir / "headless_pixel_firefox_regression.py").write_text("# test harness\n", encoding="utf-8")
            completed = subprocess.CompletedProcess(
                args=["fake"],
                returncode=0,
                stdout=json.dumps({"result": {"status": "ok", "selected_access_code": "launch_test_access"}}),
                stderr="",
            )
            with (
                patch.object(package_db, "resolve_runtime_python", return_value="/tmp/custom-python"),
                patch.object(package_db.subprocess, "run", return_value=completed) as run_mock,
            ):
                report = package_db.validate_pixel_ui_launch(temp_root, "launch_test_access")
            self.assertTrue(report["startup_ok"])
            command = run_mock.call_args.args[0]
            env = run_mock.call_args.kwargs["env"]
            self.assertEqual(command[0], "/tmp/custom-python")
            self.assertEqual(env["AGORA_PIXEL_PYTHON"], "/tmp/custom-python")

    def test_run_art_pipeline_uses_resolved_runtime_python(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            _prepare_creator_root(temp_root)
            provider = _CreatorProvider()
            issued_commands: list[list[str]] = []

            def _capture_worker_command(command, **_kwargs):  # noqa: ANN001
                issued_commands.append(list(command))
                return {"command": list(command), "returncode": 0, "stdout": "", "stderr": ""}

            with (
                patch.object(serve_macro_ui, "MACRO_PACKAGE_ROOT", temp_root),
                patch.object(world_builder, "_world_creator_provider", return_value=provider),
                patch.object(world_builder, "resolve_runtime_python", return_value="/tmp/runtime-python"),
                patch.object(world_builder, "_run_worker_command", side_effect=_capture_worker_command),
                patch.object(
                    world_builder,
                    "_repack_revision_package_with_current_assets",
                    return_value={"package_db": temp_root / "world_package.db", "pixel_report": {"pixel_read": True, "details": []}, "asset_count": 1},
                ),
                patch.object(world_builder, "_startup_validation_for_package_db", return_value={"startup_ok": True, "stage": "ok"}),
                patch.object(world_builder, "validate_pixel_ui_launch", return_value={
                    "startup_ok": True,
                    "stage": "ok",
                    "expected_access_code": "launch_test_access",
                    "selected_access_code": "launch_test_access",
                    "startup_status_text": "Pixel UI ready",
                    "session_endpoint": "/api/pixel/worlds/launch_test_access/live/sessions",
                    "screenshot_path": "/tmp/pixel.png",
                    "error": "",
                }),
            ):
                draft = serve_macro_ui.api_world_builder_create_draft(
                    serve_macro_ui.WorldBuilderDraftCreateRequest(
                        world_name="Clockharbor Exchange",
                        genre="tidal trade city",
                        player_count_target=4,
                        agent_count_target=36,
                        focus="economy",
                        seed=42627,
                        brief="A harbor city where route brokers, tide pilots, and shrine archivists create a living economy.",
                    )
                )
                art_payload = world_builder.run_art_pipeline(temp_root, draft["draft_id"], draft["current_revision"])
            self.assertEqual(art_payload["status"], world_builder.STATUS_PUBLISH_READY)
            self.assertTrue(issued_commands)
            self.assertTrue(all(command and command[0] == "/tmp/runtime-python" for command in issued_commands))

    def test_headless_harness_uses_wallet_trade_probe_contract(self) -> None:
        html = serve_macro_ui._render_headless_pixel_harness(17, "testtoken", "1234567890abcdef")
        self.assertIn("actor_wallet_before_trade", html)
        self.assertIn("target_wallet_before_trade", html)
        self.assertNotIn("actor_gold_before_trade", html)
        self.assertNotIn("target_gold_before_trade", html)
        self.assertIn("quote_probe_item", html)
        self.assertIn('response_source || "") === "ai_studio"', html)
        self.assertIn('message_status || "") === "completed"', html)

    def test_pixel_world_catalog_keeps_only_latest_world_per_template(self) -> None:
        older = {
            "access_code": "1111111111111111",
            "created_at": "2026-05-28T00:00:00+00:00",
            "world_name": "Panjiayuan Autonomous",
            "world_id": "panjiayuan_autonomous_2026052802",
        }
        newer = {
            "access_code": "2222222222222222",
            "created_at": "2026-05-29T00:00:00+00:00",
            "world_name": "Panjiayuan Autonomous",
            "world_id": "panjiayuan_autonomous_2026052802",
        }
        other = {
            "access_code": "3333333333333333",
            "created_at": "2026-05-27T00:00:00+00:00",
            "world_name": "Clockharbor Exchange Autonomous",
            "world_id": "clockharbor_exchange_autonomous",
        }
        def fake_pixel_world_record(access_code: str):
            records = {entry["access_code"]: entry for entry in (older, newer, other)}
            return records.get(access_code)

        with (
            patch.object(serve_macro_ui, "_all_pixel_world_records", return_value=[newer, older, other]),
            patch.object(serve_macro_ui, "_pixel_world_record", side_effect=fake_pixel_world_record),
        ):
            catalog = serve_macro_ui.api_pixel_worlds()
            self.assertEqual([world["access_code"] for world in catalog["worlds"]], ["2222222222222222", "3333333333333333"])
            self.assertIsNotNone(serve_macro_ui._canonical_pixel_world_record("2222222222222222"))
            self.assertIsNone(serve_macro_ui._canonical_pixel_world_record("1111111111111111"))

    def test_validation_probe_bypasses_latest_template_gate_without_entering_public_catalog(self) -> None:
        probe = {
            "access_code": "aaaaaaaaaaaaaaaa",
            "created_at": "2026-05-30T00:00:00+00:00",
            "world_name": "Clockharbor Exchange Autonomous",
            "world_id": "clockharbor_exchange_autonomous",
            "validation_probe": True,
        }
        public_latest = {
            "access_code": "bbbbbbbbbbbbbbbb",
            "created_at": "2026-05-29T00:00:00+00:00",
            "world_name": "Clockharbor Exchange Autonomous",
            "world_id": "clockharbor_exchange_autonomous",
            "validation_probe": False,
        }
        non_public = {
            "access_code": "cccccccccccccccc",
            "created_at": "2026-05-28T00:00:00+00:00",
            "world_name": "Panjiayuan",
            "world_id": "panjiayuan",
            "validation_probe": False,
        }

        def fake_pixel_world_record(access_code: str):
            records = {
                probe["access_code"]: probe,
                public_latest["access_code"]: public_latest,
                non_public["access_code"]: non_public,
            }
            return records.get(access_code)

        with TemporaryDirectory() as tmp_dir:
            export_root = Path(tmp_dir)
            (export_root / probe["access_code"]).mkdir(parents=True, exist_ok=True)
            (export_root / public_latest["access_code"]).mkdir(parents=True, exist_ok=True)
            (export_root / non_public["access_code"]).mkdir(parents=True, exist_ok=True)
            with (
                patch.object(serve_macro_ui, "_package_export_root", return_value=export_root),
                patch.object(serve_macro_ui, "_pixel_world_record", side_effect=fake_pixel_world_record),
            ):
                public_records = serve_macro_ui._all_pixel_world_records()
                self.assertEqual([record["access_code"] for record in public_records], [public_latest["access_code"]])
                self.assertEqual(
                    str(serve_macro_ui._canonical_pixel_world_record(probe["access_code"])["access_code"]),
                    probe["access_code"],
                )
                self.assertFalse(serve_macro_ui._pixel_world_is_public(non_public))
                self.assertEqual(
                    serve_macro_ui._require_latest_pixel_world_access_code(probe["access_code"]),
                    probe["access_code"],
                )

    def test_pixel_world_endpoint_rejects_non_latest_template_revision(self) -> None:
        older = {
            "access_code": "1111111111111111",
            "created_at": "2026-05-28T00:00:00+00:00",
            "world_name": "Panjiayuan Autonomous",
            "world_id": "panjiayuan_autonomous_2026052802",
        }
        newer = {
            "access_code": "2222222222222222",
            "created_at": "2026-05-29T00:00:00+00:00",
            "world_name": "Panjiayuan Autonomous",
            "world_id": "panjiayuan_autonomous_2026052802",
        }
        records = {
            older["access_code"]: older,
            newer["access_code"]: newer,
        }

        with (
            patch.object(serve_macro_ui, "_all_pixel_world_records", return_value=[newer, older]),
            patch.object(serve_macro_ui, "_pixel_world_record", side_effect=lambda access_code: records.get(access_code)),
            patch.object(
                serve_macro_ui,
                "read_world_package_metadata",
                return_value={"pixel_read": "true", "pixel_read_report": json.dumps({"pixel_read": True})},
            ),
            patch.object(serve_macro_ui, "_pixel_world_workspace", return_value=Path("/tmp/fake-world-workspace")),
            patch.object(
                serve_macro_ui,
                "load_world_config_from_access_code",
                return_value=(
                    {
                        "world_name": "Panjiayuan Autonomous",
                        "world_id": "panjiayuan_autonomous_2026052802",
                    },
                    {"created_at": newer["created_at"]},
                ),
            ),
            patch.object(serve_macro_ui, "assess_pixel_readiness_from_root", return_value={"pixel_read": True}),
            patch.object(
                serve_macro_ui,
                "_pixel_world_detail_payload",
                return_value={"access_code": newer["access_code"], "world_name": newer["world_name"]},
            ),
        ):
            with self.assertRaises(HTTPException) as older_exc:
                serve_macro_ui.api_pixel_world("1111111111111111")
            self.assertEqual(older_exc.exception.status_code, 404)

            latest_payload = serve_macro_ui.api_pixel_world("2222222222222222")
            self.assertEqual(latest_payload["access_code"], "2222222222222222")

    def test_load_world_config_reuses_existing_materialized_workspace(self) -> None:
        access_code = "abcdef1234567890"
        with TemporaryDirectory() as tmp_dir:
            package_root = Path(tmp_dir)
            export_dir = package_root / "output" / "package_exports" / access_code
            export_dir.mkdir(parents=True, exist_ok=True)
            (export_dir / "world_package.db").write_bytes(b"db")
            materialized_dir = export_dir / "materialized"
            run_inputs_dir = materialized_dir / "run_inputs"
            run_inputs_dir.mkdir(parents=True, exist_ok=True)
            (run_inputs_dir / "world_config.json").write_text(
                json.dumps(
                    {
                        "scenario_meta": {
                            "world_name": "Cached Pixel World",
                            "world_id": "cached_pixel_world",
                        },
                        "runtime": {
                            "seed": 77,
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            with (
                patch.object(build_macro_ui, "ensure_materialized_world_package", return_value=materialized_dir) as ensure_mock,
                patch.object(build_macro_ui, "materialize_world_package") as materialize_mock,
            ):
                config, metadata = build_macro_ui.load_world_config_from_access_code(
                    package_root,
                    access_code,
                    materialize_dir=materialized_dir,
                )

            ensure_mock.assert_called_once()
            materialize_mock.assert_not_called()
            self.assertEqual(config["scenario_meta"]["world_id"], "cached_pixel_world")
            self.assertEqual(metadata["access_code"], access_code)
