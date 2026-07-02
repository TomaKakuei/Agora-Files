from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agora_ui import world_builder
from agora_ui.package_db import materialize_world_package
from agora_ui.package_db import pack_world_package
from agora_ui.package_db import read_structured_world_definition
from agora_ui.run_interaction_simulation import materialize_scenario
from agora_ui.world_definition import sync_world_definition_into_config
from agora_ui.world_pipeline import build_world_pipeline
from macro_ui import build_macro_ui


ROOT = Path(__file__).resolve().parents[1]


class WorldDefinitionTest(unittest.TestCase):
    def test_panjiayuan_sync_replaces_legacy_currency_and_catalog(self) -> None:
        config = build_macro_ui.generalized_world_config_template(ROOT)
        config["scenario_meta"]["world_id"] = "panjiayuan"
        config["scenario_meta"]["world_name"] = "Panjiayuan"
        config["scenario_meta"]["description"] = "A realistic antique market full of appraisal disputes."
        config = sync_world_definition_into_config(config)

        self.assertEqual(config["economy"]["currency_item_id"], "cny_cash")
        self.assertEqual(config["economy"]["currency_code"], "CNY")
        self.assertEqual(config["economy"]["currency_symbol"], "¥")
        self.assertTrue(all(item_id != "gold" for item_id in config["inventory_generation"]["allowed_item_ids"]))
        self.assertIn("appraisal_slip", config["inventory_generation"]["allowed_item_ids"])
        self.assertIn("buyer_card", config["inventory_generation"]["allowed_item_ids"])
        self.assertEqual(config["property_library"]["item_catalog"][0]["item_id"], "cny_cash")

    def test_pack_world_package_writes_structured_world_definition_tables(self) -> None:
        config = build_macro_ui.generalized_world_config_template(ROOT)
        config["scenario_meta"]["world_id"] = "panjiayuan"
        config["scenario_meta"]["world_name"] = "Panjiayuan"
        config["scenario_meta"]["description"] = "A realistic antique market full of appraisal disputes."
        config = sync_world_definition_into_config(config)

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_inputs = root / "run_inputs"
            run_inputs.mkdir(parents=True, exist_ok=True)
            config_path = run_inputs / "world_config.json"
            config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            scenario_dir = run_inputs / "scenario"
            materialize_scenario(config, scenario_dir)
            package_db = root / "world_package.db"
            pack_world_package(root, package_db, package_name="Panjiayuan")
            structured = read_structured_world_definition(package_db)
            self.assertEqual(structured["world_definition"]["world_id"], "panjiayuan")
            self.assertEqual(structured["world_definition"]["currency_code"], "CNY")
            self.assertTrue(any(item["item_id"] == "appraisal_slip" for item in structured["item_catalog"]))
            self.assertIn("resolved_component_library", structured["pixel_kits"])
            self.assertIn("pov_local_modules", structured["frontend_affordances"])
            self.assertIn("image_generation", structured["asset_prompt_kits"])
            self.assertIn("compiler_report", structured["validation_reports"])
            self.assertTrue(structured["specialist_artifacts"])

            package = materialize_world_package(package_db, output_dir=root / "materialized")
            materialized = json.loads(package.config_path.read_text(encoding="utf-8"))
            self.assertEqual(materialized["economy"]["currency_item_id"], "cny_cash")
            self.assertIn("world_definition", materialized)



    def test_world_builder_panjiayuan_avoids_legacy_guild_outputs(self) -> None:
        builder_spec = {
            "world_id": "panjiayuan",
            "world_name": "Panjiayuan",
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
            "genre": "realistic antique market",
            "premise": "A dense antique market of stalls, appraisers, rumors, and provenance disputes.",
            "simulation_objective": "Support bargaining, appraisal, provenance, and rumor-driven discovery.",
            "visual_style": "weathered market realism",
            "agent_count_target": 12,
            "rooms": [
                {"name": "Main Market Square", "biome": "urban market", "purpose": "open bargaining", "decor_tags": ["stalls", "tables"]},
                {"name": "Appraiser Lane", "biome": "quiet lane", "purpose": "close inspection", "decor_tags": ["lamps", "cases"]},
            ],
            "role_groups": [
                {"role_name": "Stall Owner", "count": 6, "core_values": ["profit", "reputation"], "activity": "sell goods and bargain", "starting_items": ["consignment note", "packing cloth"]},
                {"role_name": "Appraiser", "count": 6, "core_values": ["authenticity", "judgment"], "activity": "inspect and verify", "starting_items": ["appraisal slip", "loupe"]},
            ],
            "main_characters": [
                {"display_name": "Master Wei", "role_name": "Senior Appraiser", "activity": "verify disputed antiques"},
                {"display_name": "Sister Lin", "role_name": "Broker", "activity": "connect buyers and sellers"},
            ],
            "gameplay_loops": [
                {"label": "Bargaining", "summary": "Stalls negotiate prices.", "roles": ["Stall Owner", "Appraiser"], "rooms": ["Main Market Square"], "pressure": "price pressure"},
            ],
            "player_entry_points": ["Enter through a noisy bargaining dispute."],
            "conflict_hooks": ["A forged provenance slip splits the market."],
            "social_rules": ["Trust changes with repeated fair dealing."],
            "item_themes": ["appraisal slip", "consignment note", "loupe", "jade pendant"],
            "custom_actions": ["Inspect", "Broker", "Appraise"],
        }
        request = {"brief": "Panjiayuan market", "seed": 42}
        config = world_builder._build_world_config_from_spec(ROOT, builder_spec, request)  # noqa: SLF001
        dumped = json.dumps(config, ensure_ascii=False)

        self.assertEqual(config["economy"]["currency_item_id"], "cny_cash")
        self.assertEqual(config["runner"]["agent_id_prefix"], "agent")
        self.assertTrue(all(not str(item.get("agent_id", "")).startswith("guild_main_") for item in config["main_characters"]))
        self.assertNotIn("gold", dumped)
        self.assertNotIn("healing_potion", dumped)
        self.assertNotIn("mana_crystal", dumped)
        self.assertNotIn("signed_commission", dumped)

    def test_pipeline_builds_third_world_without_panjiayuan_name_hack(self) -> None:
        builder_spec = {
            "world_id": "clockharbor",
            "world_name": "Clockharbor Exchange",
            "world_seed": {
                "seed_version": "world_seed_v2",
                "preset_id": "coastal_trade_city",
                "profile_id": "coastal_trade_city",
                "locale": "en",
                "tone": "coastal logistics society",
                "visual_direction": "weathered harbor realism",
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
            "genre": "coastal logistics society",
            "premise": "A port city where dock crews, brokers, and inspectors negotiate cargo windows and route risk.",
            "simulation_objective": "Support routing, inspections, cargo trade, and harbor scheduling pressure.",
            "visual_style": "weathered harbor realism",
            "agent_count_target": 10,
            "rooms": [
                {"name": "North Quay", "biome": "harbor edge", "purpose": "cargo handoff", "decor_tags": ["crates", "ropes"]},
                {"name": "Signal Loft", "biome": "upper dock", "purpose": "route planning", "decor_tags": ["flags", "charts"]},
                {"name": "Ledger House", "biome": "stone office", "purpose": "contracts and manifests", "decor_tags": ["desks", "ledgers"]},
            ],
            "role_groups": [
                {"role_name": "Dock Broker", "count": 4, "core_values": ["timing", "margin"], "activity": "broker cargo routes"},
                {"role_name": "Harbor Inspector", "count": 3, "core_values": ["compliance", "clarity"], "activity": "inspect contracts and cargo"},
                {"role_name": "Signal Pilot", "count": 3, "core_values": ["timing", "safety"], "activity": "navigate route windows"},
            ],
            "main_characters": [
                {"display_name": "Mara Voss", "role_name": "Route Broker", "activity": "balance competing departures"},
            ],
            "gameplay_loops": [
                {"label": "Cargo Window", "summary": "Crews compete for the next safe departure slot.", "roles": ["Dock Broker", "Signal Pilot"], "rooms": ["North Quay"], "pressure": "departure timing"},
            ],
            "player_entry_points": ["Arrive as a disputed shipment misses its tide window."],
            "conflict_hooks": ["A forged dock contract threatens a cargo line."],
            "social_rules": ["Repeated reliability changes who gets priority on the next route."],
            "custom_actions": ["Inspect", "Broker", "Route"],
        }
        request = {"brief": "A harbor city of route bargaining and cargo pressure.", "seed": 7}

        pipeline = build_world_pipeline(builder_spec, request)
        self.assertEqual(pipeline["planner"]["world_definition_seed"]["profile_id"], "coastal_trade_city")
        self.assertEqual(pipeline["compiler_report"]["status"], "ok")

        config = world_builder._build_world_config_from_spec(ROOT, builder_spec, request, pipeline_artifacts=pipeline)  # noqa: SLF001
        dumped = json.dumps(config, ensure_ascii=False)

        self.assertEqual(config["economy"]["currency_item_id"], "harbor_chit")
        self.assertIn("route_ledger", dumped)
        self.assertIn("dock_contract", dumped)
        self.assertNotIn("gold", dumped)
        self.assertNotIn("panjiayuan", dumped.lower())
        self.assertNotIn("grounded_market", dumped)
        self.assertTrue(config["world_definition"]["pixel_kits"]["resolved_component_library"]["props"])


if __name__ == "__main__":
    unittest.main()
