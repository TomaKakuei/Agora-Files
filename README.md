# agora_2.0

`agora_2.0` is the runnable integration repository for the Agora stack.

It keeps the end-to-end product working:

- JSON world authoring
- SQLite runtime bundles
- FastAPI serving
- Macro UI and Pixel UI
- live multiplayer runtime
- package export and pull by access code
- deployment, regression, and load testing

The most important contract is simple:

- JSON is the authoring surface.
- `world_package.db` is the runtime bundle.
- In live mode, the selected world's DB remains the source of truth.

## Repository Role

Use this repository when you need the system to actually run.

`agora_2.0` owns:

- real simulation launches
- package export and package pull
- `PIXEL READ` package readiness gating
- FastAPI APIs under `/api/*`
- Macro UI under `/macro`
- Pixel UI under `/pixel`
- live sessions backed by `agora_ui/live_world.py`
- WebSocket movement and state-delta fanout
- deployment with systemd and Cloudflare Tunnel

If you want the lean core view instead, use the sibling repository `agora-C`.

## Runtime Contract

The current runtime flow is:

1. Author a world in JSON, or use the Universal Generative World Pipeline to synthesize it dynamically.
2. Materialize or export it into `world_package.db`.
3. Load the DB package for launch, replay, or live serving.
4. Materialize temporary JSON workspace files only as needed for tools that still consume them.

Important implications:

- `world_config.json` and `scenario/*` remain the editable source layer.
- `output/*/world_package.db` is the launchable artifact.
- package export assigns a 16-character `access_code`.
- a later session can pull the same package back by `access_code`.
- the Pixel UI world selector only lists packages that pass `PIXEL READ`.

## One Sentence To World Flow

Agora 2.0's current creator path turns a compact user brief into a live Pixel world through two asynchronous worker phases and one publish phase.

The frontend and API entry points are:

- `world_creator_ui/index.html`
  Browser creator surface.
- `POST /api/world-builder/drafts`
  Creates a draft from `world_name`, `genre`, `player_count_target`, `agent_count_target`, `focus`, `seed`, and `brief`.
- `GET /api/world-builder/drafts/{draft_id}`
  Polls generation status and current revision metadata.
- `POST /api/world-builder/drafts/{draft_id}/revise`
  Creates a new revision from feedback against the current draft context.
- `POST /api/world-builder/drafts/{draft_id}/art`
  Starts the art, package, and QA worker for the current revision.
- `GET /api/world-builder/drafts/{draft_id}/art/status`
  Polls art worker status, command logs, readiness reports, startup reports, and QA summaries.
- `POST /api/world-builder/drafts/{draft_id}/publish`
  Exports the revision-local `world_package.db` as a public package and returns a new 16-character `access_code`.

Generation is intentionally detached from the request path:

1. `create_draft()` writes `output/world_creator_drafts/{draft_id}/draft_manifest.json`.
2. It creates revision `r001` with an immediate placeholder `status.json`.
3. It queues `python -m agora_ui.world_builder generate-worker` through `systemd-run --user`.
4. The API returns immediately so the UI can poll instead of blocking the server.
5. `run_generation_worker()` calls `_generate_revision()`, updates the manifest, and records a complete revision.

Each ready revision stores the generated chain under:

```text
output/world_creator_drafts/{draft_id}/revisions/{revision_id}/
  input_brief.txt
  user_feedback.txt
  builder_spec.json
  planner.json
  rooms_spec.json
  items_spec.json
  agents_spec.json
  pixel_frontend_spec.json
  compiler_report.json
  compiler_critique.json
  world_config.json
  scenario/
  world_summary.md
  world_package.db
  status.json
```

The generator itself is staged:

1. `agora_ui.world_builder.generation` calls Gemini through `VertexJsonClient`.
2. It builds a `builder_spec` with world seed, rooms, item catalog, main characters, hooks, visual direction, and gameplay loops.
3. `_normalize_builder_spec()` clamps and repairs the spec, enforces valid room visuals, removes anonymous regular-role generation, and keeps protagonist-led worlds valid.
4. `agora_ui.world_pipeline.build_world_pipeline()` resolves registry-backed kits and policies into planner, rooms, items, agents, and Pixel frontend specs.
5. `_build_world_config_from_spec()` compiles those artifacts into the executable `world_config.json`.
6. `_validation_workspace()` materializes scenario files, finalizes agent payloads, packages a temporary DB, and performs compile/startup validation.
7. `_critique_compiled_world_config()` can repair the compiled config once before the revision is committed.
8. `_generate_summary()` writes a human-readable world summary for review.

The art worker is also detached:

1. `launch_art_worker()` queues `python -m agora_ui.world_builder art-worker` through `systemd-run --user`.
2. `_prepare_art_runtime()` creates a revision-local runtime workspace with `run_inputs/world_config.json` and `run_inputs/scenario/`.
3. `run_art_pipeline()` executes:
   - `python -m macro_ui.build_macro_ui --run-dir ... --no-agent-images --no-generate-images`
   - `asset_pipeline/generate_world_asset_set.py --all-active-agents --max-workers 1 --update-current-alias --reuse-latest-raw-sheet`
   - `asset_pipeline/build_live_ready_feed.py --target-ready-count min(30, runtime.agent_count) --all-active-agents --preferred-revision {draft_id}_{revision_id}`
4. `_repack_revision_package_with_current_assets()` copies only revision-matching generated assets into an isolated workspace and repacks `world_package.db`.
5. `assess_pixel_readiness_from_root()` must pass `PIXEL READ`; if it fails once, the live-ready feed is retried once.
6. `_startup_validation_for_package_db()` verifies backend package startup.
7. `_pixel_launch_validation_for_package_db()` copies the package into `output/package_exports/{access_code}/`, stamps `validation_probe=1`, launches the real Pixel UI in headless Firefox, then clears the probe only on success.
8. `_run_gemini_map_qa()` verifies both the stitched map image and browser screenshot.
9. Only after all gates pass does the manifest move to `publish_ready`.

Publishing never rebuilds from raw config. `publish_draft()` exports the revision-local package DB through `export_world_package_from_db()`, writes `output/package_exports/{access_code}/world_package.db`, materializes fast static assets, writes `package_meta.json`, reruns startup and Pixel launch validation, and marks the draft `published`.

The generated world is used through:

- `GET /api/pixel/worlds`
  Returns public, latest-by-seed, `PIXEL READ` worlds only.
- `GET /api/pixel/worlds/{access_code}`
  Returns the package-backed world detail payload and frontend asset URLs.
- `/pixel/index.html?pixel_world={access_code}` or `/pixel/index.html?access_code={access_code}&mode=live`
  Boots the Phaser Pixel UI against the selected package.
- `POST /api/pixel/worlds/{access_code}/live/sessions`
  Claims a controllable live session.
- `GET /api/pixel/worlds/{access_code}/live/state?session_id=...`
  Reads DB-backed world state snapshots and fallback deltas.
- `POST /api/pixel/worlds/{access_code}/live/actions`
  Submits high-value actions such as messages, item use, trade, movement requests, and target-aware interactions.
- `WS /api/pixel/worlds/{access_code}/live/ws/{session_id}`
  Streams realtime movement input and authoritative deltas.

Catalog visibility is strict:

- `validation_probe` must be absent or false.
- `pixel_read` must be true, or `pixel_read_report` must recompute cleanly.
- `startup_ok=false` hides the package.
- only `world_creator_publish`, `macro_ui_export`, `world_creator_art_pipeline`, or `_autonomous` world IDs are public.
- duplicate seeds are deduplicated server-side; only the latest package for a seed is returned.
- request-time access to an older seed revision returns `404` because the Pixel API enforces latest-by-template access.

Operational environment:

- Main runtime Python defaults to `/home/yz_wang/.conda/envs/new_py310/bin/python` through the launch scripts or `AGORA_RUNTIME_PYTHON`.
- Creator workers load `~/.config/agora_ui_runtime.env`; current required keys include `AGORA_AISTUDIO_API_KEY` and `AGORA_VERTEX_API_KEY`.
- The Macro/Pixel host is served by `macro_ui/serve_macro_ui.py` at `/macro`, `/creator`, `/pixel`, and `/api/*`.
- FLUX asset generation must be started through `scripts/launch_flux_asset_service.sh` so CUDA library paths are set correctly.
- `PIXEL READ` assets are served from the materialized static package path under `output/package_exports/{access_code}/materialized/` for fast map and atlas bootstrap.

## Key Paths

- `agora_ui/`
  Core Python package, including simulation, orchestration, package helpers, and live runtime.
- `agora_ui/package_db.py`
  DB package detection, export, import, materialization, and `PIXEL READ` helpers.
- `agora_ui/live_world.py`
  `PixelLiveStore`, the live DB-backed runtime and session authority.
- `agora_ui/runtime/`
  JSON-declared orchestration engine used by the offline simulation runner.
- `macro_ui/serve_macro_ui.py`
  FastAPI app serving `/macro`, `/pixel`, `/api/*`, package APIs, and live APIs.
- `frontend/`
  Phaser Pixel UI and surrounding HTML/CSS shell.
- `asset_pipeline/`
  Offline asset preparation and atlas packaging pipeline.
- `deploy/`
  systemd and Cloudflare Tunnel deployment assets.

## Quick Start

From `/home/yz_wang/yz_main/agora_2.0`:

```bash
export AGORA_VERTEX_API_KEY="your_api_key"
./launch_interaction_new_py310.sh \
  --config sample_json/world_package.db \
  --scenario-dir sample_json/scenario
```

Equivalent module form:

```bash
PYTHONPATH=. \
python -m agora_ui.run_interaction_simulation \
  --config sample_json/world_package.db \
  --scenario-dir sample_json/scenario
```

Useful variations:

```bash
./launch_interaction_new_py310.sh --config sample_json/world_package.db --rounds 3
./launch_interaction_new_py310.sh --config sample_json/world_package.db --resume-run-dir output/<run_group>/<run_id>
./launch_interaction_new_py310.sh --config sample_json/world_package.db --reuse-agent-profile-cache output/<run_group>/<run_id>/agent_profile_api_cache
```

## Web Product Surface

This repository serves one host with parallel experiences:

- `/macro`
  Main control surface for world configuration, package export, replay, and operational tooling.
- `/pixel`
  Phaser world view with live movement, target selection, trade, inventory, and dialogue controls.
- `/api/*`
  Shared API surface for packages, pixel world discovery, sessions, live state, actions, and WebSocket realtime.

The two UIs are meant to point at the same package-backed world, not separate copies.

## Live Runtime

Live mode is DB-backed and session-based.

Current high-frequency movement architecture:

- FastAPI WebSocket endpoint:
  `/api/pixel/worlds/{access_code}/live/ws/{session_id}`
- server tick loop in `serve_macro_ui.py`
- hot spatial state overlay in `PixelLiveStore`
- write-behind spatial flush back into SQLite
- delta broadcasts instead of full-state broadcasts for movement

Current defaults:

- `20` ticks per second
- `50ms` server tick interval
- `1s` spatial flush interval
- SQLite `WAL` mode for the runtime package

This preserves the DB contract while removing synchronous per-step writes from the hot path.

High-value actions such as inventory settlement, trade fulfillment, or task completion still remain DB-backed state changes, not frontend-owned state.

## Frontend Live Model

The Pixel UI is no longer HTTP-poll-only.

Current frontend behavior:

- boot world data through REST
- create live session through REST
- connect realtime movement over WebSocket
- use client-side prediction for the local agent
- reconcile against authoritative deltas from the server
- interpolate remote agents instead of teleporting them
- keep REST `/live/state` as a slower fallback and completeness channel

This is why the movement path can be low-latency without giving up DB-backed authority.

## Universal Generative World Pipeline

Worlds can now be synthesized dynamically via the `agora_ui.world_builder` and `agora_ui.world_pipeline` modules. This allows for fully autonomous world creation from a single natural language prompt.

- **Dynamic Item Catalog**: Instead of relying on static templates, the pipeline synthesizes a custom `item_catalog` tailored to the world's specific theme (e.g., generating jade and bronze artifacts for a "Panjiayuan Antique Market").
- **Self-Healing Co-presence**: The pipeline automatically merges dynamically generated items with mandatory frontend affordance items (e.g., `tea_flask`, `gold_coin`), ensuring the resulting world always passes frontend and Pixel UI validation.
- **Role-Aware Inventory**: Agent generation leverages localized naming conventions and scales inventory capacity based on their economic role (supporting up to 30 unique item types and 50 quantity per item).
- **Custom Visual Overrides**: The generator dynamically assigns room visuals, including `floor_tile`, `wall_tile`, `palette`, and `decor`, bypassing generic defaults.
- **Vertex API Pacing**: All backend generative calls are paced with an automatic 1.2s delay to prevent `429 Too Many Requests` errors when utilizing the Vertex API.

## Authoring Contract

Worlds are still authored around:

```text
my_world/
  world_config.json
  scenario/
    manifest.json
    world_rules.json
    map_grid.json
    agent_intents.json
    Agents/
      <agent_id>.json
```

`world_config.json` remains the main authoring contract. Important top-level sections include:

- `scenario_meta`
- `runtime`
- `runner`
- `orchestration`
- `human_interaction`
- `output`
- `vertex_api`
- `image_generation`
- `space`
- `economy`
- `world_rules`
- `agent_generation`
- `actions`
- `longlive`
- `pixel_asset_pipeline`
- `report`
- `inventory_generation`
- `main_characters`
- `extra_world_functions`
- `world_progress`

The rule is still the same:

- theme and world behavior belong in JSON
- Python and JavaScript execute those declared contracts

## Asset Responsibility Split

Do not mix up the runtime product and the asset backend.

- Gemini remains the primary runtime interaction and simulation media engine.
- FLUX-oriented local tooling is for heavier offline pixel asset work.

`agora_2.0` may host both sides operationally, but they are still separate responsibilities.

## Documentation Map

- [ARCHITECTURE.md](/home/yz_wang/yz_main/agora_2.0/ARCHITECTURE.md)
  Runnable architecture and layer boundaries.
- [README For LLM.md](/home/yz_wang/yz_main/agora_2.0/README%20For%20LLM.md)
  High-level implementation contract for future work.
- [SYNC_WITH_AGORA_C.md](/home/yz_wang/yz_main/agora_2.0/SYNC_WITH_AGORA_C.md)
  Sync boundary and repo split policy.
- [MemoryFrontEnd.md](/home/yz_wang/yz_main/agora_2.0/MemoryFrontEnd.md)
  Current Pixel UI live-state and interaction contract.
- [deploy/CLOUDFLARE_TUNNEL.md](/home/yz_wang/yz_main/agora_2.0/deploy/CLOUDFLARE_TUNNEL.md)
  Public deployment notes.

## Repo Split

Keep the split intentional:

- `agora-C`
  lean core repo, minimal samples, shared runtime contracts, reference architecture
- `agora_2.0`
  runnable integration repo, live serving, deployment, heavy validation, and operational UI behavior

Shared runtime ideas should stay aligned.
Operational wiring does not need to be identical.
