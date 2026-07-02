
import json
import unittest
from pathlib import Path
from typing import Optional

from agora_ui.boundary_schemas import (
    AssetBundleSpec,
    AssetEventSpec,
    BootstrapAgentsSpec,
    FinalManifestSpec,
    ImageJobSpec,
    PromptBundleSpec,
    ReplayBundleSpec,
    RuntimePolicyRegistrySpec,
    RuntimePolicySpec,
    RuntimeSnapshotSpec,
    RuntimeStoreSummarySpec,
    RunConfigSpec,
    StoryPayloadSpec,
    TimelineRecordSpec,
    VideoJobSpec,
)
from agora_ui.adjudicator_schemas import AgentRuntimeProfileSpec
from agora_ui.scenario_schemas import ScenarioMapGridSpec, ScenarioManifestSpec


ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def _load_first_jsonl_row(path: Path) -> dict:
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line:
            return json.loads(line)
    raise ValueError(f'no JSONL rows in {path}')


def _first_existing(patterns: list[str]) -> Optional[Path]:
    for pattern in patterns:
        match = next(ROOT.glob(pattern), None)
        if match is not None and match.is_file():
            return match
    return None


def _sample_prompt_bundle() -> dict:
    path = _first_existing(['frontend/assets/generated/*/*/prompt_bundle.json'])
    if path is not None:
        try:
            return _load_json(path)
        except Exception:
            pass
    return {
        'agent_id': 'demo_agent',
        'display_name': 'Demo Agent',
        'world_id': 'demo_world',
        'world_name': 'Demo World',
        'room_id': 'demo_room',
        'room_name': 'Demo Room',
        'room_visual': {},
        'core_values': ['curiosity'],
        'personality_tags': ['steady'],
        'framework_version': 'demo_v1',
        'sheet_layout': {'columns': 4, 'rows': 4},
        'processing': {'target_frame_width': 32, 'target_frame_height': 32},
        'alignment_policy': {},
        'concept_prompt': 'Describe a demo character.',
        'sprite_prompt': 'Build a demo sprite sheet.',
        'negative_prompt': 'text, watermark',
    }


def _sample_video_job() -> dict:
    path = _first_existing(['output/replay_runs/*/video_prompt_jobs.jsonl'])
    if path is None:
        return {
            'job_id': 'job_1',
            'status': 'ok',
            'round_index': 1,
            'actor_id': 'actor_a',
            'target_id': 'target_b',
            'prompts_jsonl_path': '/tmp/prompts.jsonl',
            'config_path': '/tmp/config.yaml',
            'command_log_path': '/tmp/longlive.log',
            'video_path': '/tmp/video.mp4',
            'snapshot_path': '',
            'num_output_frames': 81,
            'total_rgb_frames': 321,
            'switch_frame_indices': [41],
            'output_video_fps': 16.05,
            'gpu_selection': {'selected': True},
            'actor_prompt': 'actor',
            'target_continuation_prompt': 'target',
            'prompt_source': 'vertex_api',
            'safety_notes': '',
            'shared_action_core': {},
            'prompt_schedule_seconds': [0, 10],
        }
    return _load_first_jsonl_row(path)


def _sample_image_job() -> dict:
    path = _first_existing(['output/replay_runs/*/image_jobs.jsonl'])
    if path is None:
        return {
            'job_id': 'job_2',
            'status': 'ok',
            'round_index': 1,
            'actor_id': 'actor_a',
            'target_id': 'target_b',
            'prompt': 'Generate an item.',
            'prompt_source': 'vertex_api',
            'artifact_label': 'Item',
            'safety_notes': '',
            'job_dir': '/tmp/job',
            'image_path': '/tmp/image.png',
            'image_mime_type': 'image/png',
            'operation': 'create',
        }
    return _load_json(path)


class OutputSchemasTest(unittest.TestCase):
    def test_bootstrap_agents_sample(self) -> None:
        payload = _load_json(ROOT / 'frontend/bootstrap_agents.json')
        model = BootstrapAgentsSpec.model_validate(payload)
        self.assertEqual(model.agent_count, len(model.agents))

    def test_bootstrap_agent_runtime_profile_sample(self) -> None:
        payload = _load_json(ROOT / 'frontend/bootstrap_agents.json')
        model = AgentRuntimeProfileSpec.model_validate(payload['agents'][0])
        self.assertEqual(model.agent_id, payload['agents'][0]['agent_id'])

    def test_bootstrap_agents_rejects_count_mismatch(self) -> None:
        payload = _load_json(ROOT / 'frontend/bootstrap_agents.json')
        payload['agent_count'] = int(payload['agent_count']) + 1
        with self.assertRaises(Exception):
            BootstrapAgentsSpec.model_validate(payload)

    def test_asset_event_sample(self) -> None:
        payload = _load_json(ROOT / 'frontend/assets/generated/events/latest.json')
        if not {'id', 'display_name', 'atlas_url', 'json_url', 'revision', 'default_animation', 'generated_at'}.issubset(payload):
            payload = {
                'event': 'new_asset_ready',
                'id': 'demo_agent',
                'display_name': 'Demo Agent',
                'atlas_url': './assets/generated/demo_agent/demo.png',
                'json_url': './assets/generated/demo_agent/demo.json',
                'revision': 'demo_rev',
                'world_id': 'demo_world',
                'world_name': 'Demo World',
                'world_revision': 'demo_rev',
                'default_animation': 'idle_down',
                'animations': {},
                'generated_at': '2026-05-13T00:00:00+00:00',
            }
        model = AssetEventSpec.model_validate(payload)
        self.assertEqual(model.id, payload['id'])

    def test_asset_event_rejects_missing_field(self) -> None:
        payload = _load_json(ROOT / 'frontend/assets/generated/events/latest.json')
        payload.pop('event', None)
        with self.assertRaises(Exception):
            AssetEventSpec.model_validate(payload)

    def test_scenario_manifest_sample(self) -> None:
        payload = _load_json(ROOT / 'sample_json/scenario/manifest.json')
        model = ScenarioManifestSpec.model_validate(payload)
        self.assertEqual(model.scenario_meta.world_id, payload['scenario_meta']['world_id'])

    def test_scenario_manifest_accepts_creator_fields(self) -> None:
        payload = {
            'scenario_meta': {
                'world_id': 'panjiayuan',
                'world_name': 'Panjiayuan',
                'version': '1.0',
                'description': 'Market world',
                'simulation_objective': 'Keep negotiation live.',
                'player_entry_points': ['Enter through a bargaining dispute.'],
                'creator_conflict_hooks': ['A disputed provenance rumor splits the market.'],
            },
            'engine_config': {
                'world_mode': 'LLM_Wrap',
                'adjudicator_api': {'provider': 'Local'},
                'agent_default_api': {'provider': 'Local', 'temperature': 0.8},
                'simulation_params': {'max_timesteps': 1, 'parallel_execution': True, 'tick_rate_ms': 0, 'concurrency_limit': 10},
            },
            'asset_bindings': {
                'world_rules_path': './world_rules.json',
                'map_grid_path': './map_grid.json',
                'active_agents': ['./Agents/agent_001.json'],
                'relationship_tensor_path': '',
                'localized_visual_state_path': '',
                'intents_path': './agent_intents.json',
                'intent_batches_path': '',
                'prompt_path': '',
            },
        }
        model = ScenarioManifestSpec.model_validate(payload)
        self.assertEqual(model.scenario_meta.player_entry_points[0], 'Enter through a bargaining dispute.')

    def test_scenario_map_grid_sample(self) -> None:
        payload = _load_json(ROOT / 'sample_json/scenario/map_grid.json')
        model = ScenarioMapGridSpec.model_validate(payload)
        self.assertGreater(len(model.rooms), 0)

    def test_scenario_map_grid_accepts_room_metadata(self) -> None:
        payload = {
            'grid_shape': {'x': 8, 'y': 8, 'z': 1},
            'map_visual': {},
            'rooms': [
                {
                    'room_id': 'market_square',
                    'name': 'Market Square',
                    'x': 1,
                    'y': 1,
                    'z': 0,
                    'width_tiles': 4,
                    'height_tiles': 3,
                    'visual': {'biome': 'interior'},
                    'metadata': {
                        'purpose': 'Trading and appraisal hub',
                        'activity_tags': ['bargain', 'appraise'],
                        'player_entry_hook': 'Market Square',
                    },
                }
            ],
            'initial_positions': {},
            'initial_room_ids': {},
        }
        model = ScenarioMapGridSpec.model_validate(payload)
        self.assertEqual(model.rooms[0].metadata['purpose'], 'Trading and appraisal hub')

    def test_prompt_bundle_sample_or_synthetic(self) -> None:
        payload = _sample_prompt_bundle()
        model = PromptBundleSpec.model_validate(payload)
        self.assertEqual(model.agent_id, payload['agent_id'])

    def test_video_job_sample(self) -> None:
        payload = _sample_video_job()
        model = VideoJobSpec.model_validate(payload)
        self.assertEqual(model.job_id, payload['job_id'])

    def test_image_job_sample(self) -> None:
        payload = _sample_image_job()
        model = ImageJobSpec.model_validate(payload)
        self.assertEqual(model.job_id, payload['job_id'])

    def test_run_config_synthetic(self) -> None:
        payload = {
            'run_id': 'run_1',
            'created_at': '2026-05-13T00:00:00+00:00',
            'config_path': '/tmp/world.json',
            'scenario_dir': '/tmp/scenario',
            'scenario_files': {'scenario': '/tmp/scenario/manifest.json'},
            'agent_profile_cache_dir': '',
            'reused_agent_profile_cache': '',
            'rounds': 10,
            'activation_probability': 0.25,
            'seed': 42,
            'agent_profile_source': 'vertex_api',
            'disable_longlive': False,
            'disable_image_generation': False,
            'max_images_per_round': 2,
            'image_generation': {},
            'inventory_generation': {},
            'extra_world_functions': {},
            'always_activate_agent_ids': ['a1'],
            'force_cinematic_agent_ids': [],
            'story_filename': 'story.json',
            'run_name': 'demo',
            'vertex_api': None,
            'vertex_image_sdk': None,
            'resume': {'source_run_dir': '', 'completed_round': 0, 'start_round': 1, 'in_place': False},
            'compiled_orchestration_path': '/tmp/compiled.json',
        }
        model = RunConfigSpec.model_validate(payload)
        self.assertEqual(model.run_id, 'run_1')

    def test_runtime_policy_registry_synthetic(self) -> None:
        payload = {
            'policies': {
                'activation_policy': {
                    'policy_id': 'activation_v1',
                    'enabled': True,
                    'config': {'threshold': 0.25},
                    'notes': 'demo',
                },
                'finalization_policy': {
                    'policy_id': 'finalize_v1',
                    'enabled': False,
                    'config': {},
                },
            }
        }
        model = RuntimePolicyRegistrySpec.model_validate(payload)
        self.assertEqual(model.policies['activation_policy'].policy_id, 'activation_v1')

    def test_runtime_policy_rejects_missing_id(self) -> None:
        with self.assertRaises(Exception):
            RuntimePolicySpec.model_validate({'enabled': True, 'config': {}})

    def test_runtime_snapshot_synthetic(self) -> None:
        payload = {
            'run_id': 'run_1',
            'compiled_orchestration': {'mode': 'json_declared_runtime'},
            'component_state': {'trace': {'transitions': []}},
            'event_bus': {'events': []},
            'store_summary': {
                'rounds': 10,
                'resume_start_round': 1,
                'route_counts': {'move': 1},
                'longlive_counts': {},
                'image_counts': {},
            },
        }
        model = RuntimeSnapshotSpec.model_validate(payload)
        self.assertEqual(model.store_summary.rounds, 10)

    def test_runtime_store_summary_rejects_bad_counts(self) -> None:
        with self.assertRaises(Exception):
            RuntimeStoreSummarySpec.model_validate({
                'rounds': 10,
                'resume_start_round': 1,
                'route_counts': {'move': 'bad'},
                'longlive_counts': {},
                'image_counts': {},
            })

    def test_story_payload_synthetic(self) -> None:
        payload = {
            'run_id': 'run_1',
            'scenario_meta': {'world_id': 'demo', 'world_name': 'Demo', 'description': 'Demo'},
            'resumed_from': {'source_run_dir': '', 'completed_round': 0, 'start_round': 1, 'in_place': False},
            'round_summaries': [
                {
                    'round_index': 1,
                    'activated_agent_count': 1,
                    'intent_count': 1,
                    'story_event_count': 1,
                    'video_job_count': 0,
                    'image_job_count': 0,
                    'action_success_count': 1,
                    'action_result_count': 1,
                    'routes': {'move': 1},
                }
            ],
            'stories': [],
            'route_counts': {'move': 1},
            'longlive_counts': {},
            'image_counts': {},
            'extra_world_events': [],
            'target_legality': {},
            'orchestration': {},
        }
        model = StoryPayloadSpec.model_validate(payload)
        self.assertEqual(model.run_id, 'run_1')

    def test_final_manifest_synthetic(self) -> None:
        payload = {
            'run_id': 'run_1',
            'status': 'ok',
            'scenario_dir': '/tmp/scenario',
            'rounds': 10,
            'resumed_from': {'source_run_dir': '', 'completed_round': 0, 'start_round': 1, 'in_place': False},
            'activation_probability': 0.25,
            'agent_count': 1,
            'files': {'timeline': '/tmp/timeline.jsonl'},
            'route_counts': {'move': 1},
            'longlive_counts': {},
            'image_counts': {},
            'extra_world_event_count': 0,
            'target_legality': {},
            'orchestration_mode': 'json_declared_runtime',
        }
        model = FinalManifestSpec.model_validate(payload)
        self.assertEqual(model.status, 'ok')

    def test_timeline_record_synthetic(self) -> None:
        payload = {
            'round_index': 1,
            'summary': {
                'round_index': 1,
                'activated_agent_count': 1,
                'intent_count': 1,
                'story_event_count': 1,
                'video_job_count': 0,
                'image_job_count': 0,
                'action_success_count': 1,
                'action_result_count': 1,
                'routes': {'move': 1},
            },
            'stories': [],
            'video_jobs': [],
            'image_jobs': [],
            'extra_world_events': [],
            'action_results': [],
        }
        model = TimelineRecordSpec.model_validate(payload)
        self.assertEqual(model.round_index, 1)

    def test_macro_bundle_synthetic(self) -> None:
        payload = {
            'generated_at': '2026-05-13T00:00:00+00:00',
            'world': {
                'world_id': 'demo_world',
                'world_name': 'Demo World',
                'description': 'A demo world.',
                'simulation_objective': 'Validate schema.',
                'domain_label': 'gallery',
                'image_options': {'generate_character_portraits': True, 'item_image_mode': 'off'},
            },
            'run': {
                'run_id': 'run_1',
                'run_dir': '/tmp/run_1',
                'status': 'complete',
                'created_at': '2026-05-13T00:00:00+00:00',
                'rounds_target': 1,
                'rounds_completed': 1,
                'activation_probability': 0.25,
                'agent_count': 1,
                'route_counts': {'move': 1},
                'longlive_counts': {},
                'image_counts': {},
            },
            'map': {
                'grid_shape': {'x': 1, 'y': 1, 'z': 1},
                'map_visual': {},
                'bounds': {'min_x': 0, 'max_x': 0, 'min_y': 0, 'max_y': 0},
                'capacity_per_coordinate': 1,
                'rooms': [
                    {
                        'room_id': 'room_a',
                        'name': 'Room A',
                        'x': 0,
                        'y': 0,
                        'z': 0,
                        'width_tiles': 1,
                        'height_tiles': 1,
                        'footprint_area': 1,
                        'capacity_estimate': 1,
                        'occupancy_density': 0.0,
                        'pressure_band': 'clear',
                        'image_url': '',
                    }
                ],
            },
            'agents': [
                {
                    'agent_id': 'agent_a',
                    'display_name': 'Agent A',
                    'room_id': 'room_a',
                    'coordinates': {'x': 0, 'y': 0, 'z': 0},
                    'main_character': True,
                    'role_name': 'Hero',
                    'activity_directive': '',
                    'appearance_prompt': '',
                    'room_visual': {},
                    'agent_number': 101,
                    'image_url': '',
                }
            ],
            'relationship_graph': {'nodes': [], 'edges': []},
            'frames': [
                {
                    'frame_index': 0,
                    'round_index': 0,
                    'label': 'Initial',
                    'summary': {
                        'round_index': 0,
                        'activated_agent_count': 0,
                        'intent_count': 0,
                        'story_event_count': 0,
                        'video_job_count': 0,
                        'image_job_count': 0,
                        'action_success_count': 0,
                        'action_result_count': 0,
                        'routes': {},
                    },
                    'rooms': [],
                    'agents': [],
                    'relationship_edges': [],
                    'social_groups': [],
                    'stories': [],
                    'longlive_jobs': [],
                    'image_jobs': [],
                    'extra_world_events': [],
                    'action_results': [],
                }
            ],
        }
        model = ReplayBundleSpec.model_validate(payload)
        self.assertEqual(model.run.run_id, 'run_1')

    def test_macro_bundle_rejects_missing_world(self) -> None:
        payload = {
            'generated_at': '2026-05-13T00:00:00+00:00',
            'run': {'run_id': 'run_1', 'run_dir': '/tmp', 'status': 'complete', 'rounds_target': 1, 'rounds_completed': 1, 'activation_probability': 0.25, 'agent_count': 1, 'route_counts': {}, 'longlive_counts': {}, 'image_counts': {}},
            'map': {'grid_shape': {'x': 1, 'y': 1, 'z': 1}, 'map_visual': {}, 'bounds': {'min_x': 0, 'max_x': 0, 'min_y': 0, 'max_y': 0}, 'capacity_per_coordinate': 1, 'rooms': []},
            'agents': [],
            'relationship_graph': {},
            'frames': [],
        }
        with self.assertRaises(Exception):
            ReplayBundleSpec.model_validate(payload)


if __name__ == '__main__':
    unittest.main()
