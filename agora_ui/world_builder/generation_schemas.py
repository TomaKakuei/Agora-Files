from __future__ import annotations
import json
import time
import traceback
from typing import Any
from agora_ui.vertex_json_client import VertexJsonClient

def _builder_spec_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "world_name",
            "world_id",
            "world_seed",
            "genre",
            "premise",
            "agent_count_target",
            "player_count_target",
            "economy_focus",
            "exploration_focus",
            "rooms",
            "role_groups",
            "main_characters",
            "social_rules",
            "item_themes",
            "visual_style",
            "item_catalog",
        ],
        "properties": {
            "world_name": {"type": "string"},
            "world_id": {"type": "string"},
            "world_seed": {
                "type": "object",
                "required": [
                    "seed_version",
                    "preset_id",
                    "profile_id",
                    "locale",
                    "tone",
                    "visual_direction",
                    "currency_code",
                    "currency_symbol",
                    "currency_minor_unit",
                    "domain_label",
                    "kit_refs",
                ],
                "properties": {
                    "seed_version": {"type": "string", "enum": ["world_seed_v2"]},
                    "preset_id": {"type": "string", "enum": sorted(WORLD_PROFILE_LIBRARY.keys())},
                    "profile_id": {"type": "string", "enum": sorted(WORLD_PROFILE_LIBRARY.keys())},
                    "locale": {"type": "string"},
                    "tone": {"type": "string"},
                    "visual_direction": {"type": "string"},
                    "currency_code": {"type": "string"},
                    "currency_symbol": {"type": "string"},
                    "currency_minor_unit": {"type": "string"},
                    "currency_name": {"type": "string"},
                    "domain_label": {"type": "string"},
                    "starting_wallet_minor": {
                        "type": "object",
                        "properties": {
                            "min": {"type": "integer"},
                            "max": {"type": "integer"},
                        },
                    },
                    "kit_refs": {
                        "type": "object",
                        "required": [
                            "pixel_component_kit_id",
                            "frontend_affordance_id",
                            "asset_prompt_kit_id",
                        ],
                        "properties": {
                            "pixel_component_kit_id": {"type": "string", "enum": sorted(COMPONENT_KIT_REGISTRY.keys())},
                            "frontend_affordance_id": {"type": "string", "enum": sorted(FRONTEND_AFFORDANCE_REGISTRY.keys())},
                            "asset_prompt_kit_id": {"type": "string", "enum": sorted(ASSET_PROMPT_KIT_REGISTRY.keys())},
                        },
                    },
                    "policy_refs": {
                        "type": "object",
                        "required": [
                            "economy_policy_id",
                            "item_collection_id",
                            "inventory_layer_policy_id",
                            "role_item_policy_id",
                            "property_policy_id",
                            "knowledge_policy_id",
                        ],
                        "properties": {
                            "economy_policy_id": {"type": "string", "enum": sorted(ECONOMY_POLICY_REGISTRY.keys())},
                            "item_collection_id": {"type": "string", "enum": sorted(ITEM_COLLECTION_REGISTRY.keys())},
                            "inventory_layer_policy_id": {"type": "string", "enum": sorted(INVENTORY_LAYER_POLICY_REGISTRY.keys())},
                            "role_item_policy_id": {"type": "string", "enum": sorted(ROLE_ITEM_POLICY_REGISTRY.keys())},
                            "property_policy_id": {"type": "string", "enum": sorted(PROPERTY_POLICY_REGISTRY.keys())},
                            "knowledge_policy_id": {"type": "string", "enum": sorted(KNOWLEDGE_POLICY_REGISTRY.keys())},
                            "inventory_layers": {"type": "array", "items": {"type": "string", "enum": ["wallet", "inventory", "property_library", "knowledge_assets"]}},
                        },
                    },
                },
            },
            "genre": {"type": "string"},
            "premise": {"type": "string"},
            "simulation_objective": {"type": "string"},
            "agent_count_target": {"type": "integer"},
            "player_count_target": {"type": "integer"},
            "economy_focus": {"type": "string"},
            "exploration_focus": {"type": "string"},
            "conflict_tone": {"type": "string"},
            "visual_style": {"type": "string"},
            "rooms": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "biome", "purpose", "decor_tags", "archetype", "ambient_palette", "width_tiles", "height_tiles"],
                    "properties": {
                        "name": {"type": "string"},
                        "biome": {"type": "string"},
                        "purpose": {"type": "string"},
                        "decor_tags": {"type": "array", "items": {"type": "string"}},
                        "activity_tags": {"type": "array", "items": {"type": "string"}},
                        "flux_floor_prompt": {"type": "string"},
                        "room_scene_prompt": {"type": "string"},
                        "floor_tile": {
                            "type": "string",
                            "enum": ["bamboo_planks", "red_brick", "jade_tile", "stone_checker", "yard_pavers", "library_planks", "wood_planks", "stone_slabs", "forge_slate", "clean_tile", "dorm_planks", "war_room_inlay"]
                        },
                        "wall_tile": {
                            "type": "string",
                            "enum": ["red_pillar_wall", "bamboo_wall", "courtyard_brick_wall", "quiet_lane_wall", "stall_canvas_wall", "wood_beam_wall", "storage_wall", "forge_wall", "healer_wall", "dorm_wall", "war_room_wall", "library_shelf_wall", "glass_case_wall", "tavern_wall", "yard_fence"]
                        },
                        "ambient_palette": {
                            "type": "string",
                            "enum": ["warm_lantern", "soft_mint", "focused_blue", "clear_day", "dusty_brown", "ember_orange", "low_lantern"]
                        },
                        "archetype": {
                            "type": "string",
                            "enum": ["market_exchange", "checkpoint", "logistics_yard", "lookout", "workshop", "archive_ritual", "rest_social", "training", "council", "commons"]
                        },
                        "width_tiles": {"type": "integer", "description": "The width of the room in tiles. For large markets with many agents, use large numbers (e.g. 30-60)."},
                        "height_tiles": {"type": "integer", "description": "The height of the room in tiles. For large markets with many agents, use large numbers (e.g. 30-60)."},
                    },
                },
            },
            "role_groups": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "role_name",
                        "count",
                        "core_values",
                        "activity",
                        "starting_item_ids",
                        "property_templates",
                        "knowledge_templates"
                    ],
                    "properties": {
                        "role_name": {"type": "string"},
                        "count": {"type": "integer"},
                        "core_values": {"type": "array", "items": {"type": "string"}},
                        "activity": {"type": "string"},
                        "home_base": {"type": "string"},
                        "starting_items": {"type": "array", "items": {"type": "string"}},
                        "starting_item_ids": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "property_templates": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["asset_name", "asset_type", "description", "story_use"],
                                "properties": {
                                    "asset_name": {"type": "string"},
                                    "asset_type": {"type": "string"},
                                    "description": {"type": "string"},
                                    "story_use": {"type": "string"}
                                }
                            }
                        },
                        "knowledge_templates": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["knowledge_id", "topic", "summary", "confidence"],
                                "properties": {
                                    "knowledge_id": {"type": "string"},
                                    "topic": {"type": "string"},
                                    "summary": {"type": "string"},
                                    "confidence": {"type": "integer"}
                                }
                            }
                        }
                    },
                },
            },
            "main_characters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["display_name", "role_name", "activity"],
                    "properties": {
                        "display_name": {"type": "string"},
                        "role_name": {"type": "string"},
                        "activity": {"type": "string"},
                        "home_base": {"type": "string"},
                        "arc_goal": {"type": "string"},
                        "starting_item_ids": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "property_templates": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["asset_name", "asset_type", "description", "story_use"],
                                "properties": {
                                    "asset_name": {"type": "string"},
                                    "asset_type": {"type": "string"},
                                    "description": {"type": "string"},
                                    "story_use": {"type": "string"}
                                }
                            }
                        },
                        "knowledge_templates": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["knowledge_id", "topic", "summary", "confidence"],
                                "properties": {
                                    "knowledge_id": {"type": "string"},
                                    "topic": {"type": "string"},
                                    "summary": {"type": "string"},
                                    "confidence": {"type": "integer"}
                                }
                            }
                        }
                    },
                },
            },
            "social_rules": {"type": "array", "items": {"type": "string"}},
            "item_themes": {"type": "array", "items": {"type": "string"}},
            "custom_actions": {"type": "array", "items": {"type": "string"}},
            "player_entry_points": {"type": "array", "items": {"type": "string"}},
            "conflict_hooks": {"type": "array", "items": {"type": "string"}},
            "gameplay_loops": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["label", "summary"],
                    "properties": {
                        "label": {"type": "string"},
                        "summary": {"type": "string"},
                        "roles": {"type": "array", "items": {"type": "string"}},
                        "rooms": {"type": "array", "items": {"type": "string"}},
                        "pressure": {"type": "string"},
                    },
                },
            },
            "item_catalog": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["item_id", "name", "price", "mass", "description", "image_prompt"],
                    "properties": {
                        "item_id": {"type": "string"},
                        "name": {"type": "string"},
                        "price": {"type": "integer"},
                        "mass": {"type": "number"},
                        "description": {"type": "string"},
                        "image_prompt": {"type": "string"},
                        "category": {"type": "string"},
                    },
                },
            },
        },
    }


def _world_config_critique_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["should_repair", "diagnosis"],
        "properties": {
            "should_repair": {"type": "boolean"},
            "diagnosis": {"type": "array", "items": {"type": "string"}},
            "custom_actions": {"type": "array", "items": {"type": "string"}},
            "player_entry_points": {"type": "array", "items": {"type": "string"}},
            "conflict_hooks": {"type": "array", "items": {"type": "string"}},
            "social_rules": {"type": "array", "items": {"type": "string"}},
            "loop_reinforcements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["label", "summary"],
                    "properties": {
                        "label": {"type": "string"},
                        "summary": {"type": "string"},
                        "roles": {"type": "array", "items": {"type": "string"}},
                        "rooms": {"type": "array", "items": {"type": "string"}},
                        "pressure": {"type": "string"},
                    },
                },
            },
            "room_adjustments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["room_name"],
                    "properties": {
                        "room_name": {"type": "string"},
                        "purpose_hint": {"type": "string"},
                        "activity_tags": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "role_adjustments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["role_name"],
                    "properties": {
                        "role_name": {"type": "string"},
                        "home_base": {"type": "string"},
                        "activity_hint": {"type": "string"},
                        "starting_items": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "main_character_adjustments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["display_name"],
                    "properties": {
                        "display_name": {"type": "string"},
                        "home_base": {"type": "string"},
                        "activity_hint": {"type": "string"},
                        "arc_goal": {"type": "string"},
                    },
                },
            },
        },
    }
