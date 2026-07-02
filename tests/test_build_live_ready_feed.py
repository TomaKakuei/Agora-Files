from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from asset_pipeline import build_live_ready_feed


class BuildLiveReadyFeedTest(unittest.TestCase):
    def test_canonicalize_revision_manifest_rewrites_manifest_and_aliases(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            generated_root = repo_root / "frontend" / "assets" / "generated"
            revision = "creator_demo_r001"
            manifest_dir = generated_root / "world_asset_sets" / revision
            manifest_dir.mkdir(parents=True, exist_ok=True)
            original_manifest = {
                "revision": revision,
                "world_revision": revision,
                "world_id": "demo_world",
                "world_name": "Demo World",
                "agents": [
                    {
                        "agent_id": "agent_001",
                        "publishable": True,
                        "returncode": 0,
                        "asset_bundle": {
                            "event": {
                                "atlas_url": f"./assets/generated/agent_001/{revision}/agent_atlas.png",
                                "json_url": f"./assets/generated/agent_001/{revision}/agent_atlas.json",
                            }
                        },
                    },
                    {
                        "agent_id": "agent_002",
                        "publishable": False,
                        "returncode": 1,
                        "asset_bundle": {
                            "event": {
                                "atlas_url": f"./assets/generated/agent_002/{revision}/agent_atlas.png",
                                "json_url": f"./assets/generated/agent_002/{revision}/agent_atlas.json",
                            }
                        },
                    },
                ],
                "assets": [
                    {
                        "id": "agent_001",
                        "atlas_url": f"./assets/generated/agent_001/{revision}/agent_atlas.png",
                        "json_url": f"./assets/generated/agent_001/{revision}/agent_atlas.json",
                        "world_id": "demo_world",
                        "world_revision": revision,
                    }
                ],
                "failed_agent_ids": ["agent_002"],
                "status": "partial",
            }
            (manifest_dir / "world_asset_set_manifest.json").write_text(
                json.dumps(original_manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            ready_assets = [
                {
                    "event": "new_asset_ready",
                    "id": "agent_001",
                    "display_name": "Agent One",
                    "atlas_url": f"./assets/generated/agent_001/{revision}/agent_atlas.png",
                    "json_url": f"./assets/generated/agent_001/{revision}/agent_atlas.json",
                    "revision": revision,
                    "world_id": "demo_world",
                    "world_name": "Demo World",
                    "world_revision": revision,
                    "default_animation": "idle_down",
                    "animations": {},
                    "generated_at": "2026-05-29T00:00:00+00:00",
                },
                {
                    "event": "new_asset_ready",
                    "id": "agent_002",
                    "display_name": "Agent Two",
                    "atlas_url": "./assets/generated/agent_002/live_ready_proc_01/agent_atlas.png",
                    "json_url": "./assets/generated/agent_002/live_ready_proc_01/agent_atlas.json",
                    "revision": "live_ready_proc_01",
                    "world_id": "demo_world",
                    "world_name": "Demo World",
                    "world_revision": revision,
                    "default_animation": "idle_down",
                    "animations": {},
                    "generated_at": "2026-05-29T00:00:01+00:00",
                },
            ]

            manifest = build_live_ready_feed._canonicalize_revision_manifest(
                repo_root,
                revision=revision,
                assets=ready_assets,
                target_ready_count=2,
                generated_results=[{"agent_id": "agent_002", "revision": "live_ready_proc_01"}],
                missing_agent_ids=[],
                world_id="demo_world",
                world_revision=revision,
            )

            self.assertIsNotNone(manifest)
            assert manifest is not None
            self.assertEqual(manifest["status"], "ok")
            self.assertEqual(manifest["failed_agent_ids"], [])
            self.assertEqual(manifest["ready_count"], 2)
            self.assertEqual([entry["id"] for entry in manifest["assets"]], ["agent_001", "agent_002"])
            self.assertEqual(manifest["agents"][1]["atlas_url"], "./assets/generated/agent_002/live_ready_proc_01/agent_atlas.png")
            self.assertNotIn("asset_bundle", manifest["agents"][1])

            manifest_payload = json.loads((manifest_dir / "world_asset_set_manifest.json").read_text(encoding="utf-8"))
            alias_payload = json.loads((generated_root / "world_asset_sets" / "current_world_pixel_set.json").read_text(encoding="utf-8"))
            compat_payload = json.loads((generated_root / "guild_asset_sets" / revision / "guild_asset_set_manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest_payload["status"], "ok")
            self.assertEqual(alias_payload["assets"][1]["id"], "agent_002")
            self.assertEqual(compat_payload["ready_count"], 2)
            self.assertEqual(manifest_payload["agents"][1]["resolved_revision"], "live_ready_proc_01")


if __name__ == "__main__":
    unittest.main()
