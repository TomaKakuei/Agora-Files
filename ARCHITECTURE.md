# agora_2.0 Architecture

This document describes the runnable architecture in `agora_2.0`.

## Role

`agora_2.0` is the executable integration repository.

It is responsible for making the stack work end to end:

- authoring import
- package export and pull
- simulation launch
- Macro UI and Pixel UI serving
- live multiplayer sessions
- deployment and validation

## Architecture Overview

The system is organized around one central rule:

- JSON declares the world.
- SQLite packages the world.
- the runtime executes against the package.

## Layer 1: Authoring

Worlds can be authored via two primary paths:

1. **Manual JSON Authoring**:
- `world_config.json`
- `scenario/manifest.json`
- `scenario/world_rules.json`
- `scenario/map_grid.json`
- `scenario/agent_intents.json`
- `scenario/Agents/*.json`

2. **Universal Generative World Pipeline**:
- A natural language prompt is passed to `agora_ui.world_builder`.
- The pipeline synthesizes a custom `item_catalog`, agent profiles with localized naming, scaled role-aware inventories, and custom room visuals.
- It leverages "self-healing co-presence" to merge mandatory affordance items seamlessly into the generated layout, ensuring frontend compatibility.
- Vertex API calls are dynamically paced with a `1.2s` delay to prevent rate-limiting.

Regardless of the path, the resulting configuration resolves to the same JSON-first semantic contract. Theme, world behavior, routes, economy, social rules, and human interaction settings belong here.

## Layer 2: Runtime Bundle

The runtime bundle is `world_package.db`.

Properties:

- DB packages can be exported from config
- packages can be restored by `access_code`
- packages can be materialized back into workspace files when needed
- **Validation Gates**: Pixel world discovery only exposes packages that pass several strict gates:
  1. `PIXEL READ` (Asset compilation success)
  2. Headless Firefox Regression (Validating the world starts in a real browser)
  3. Gemini Map Visual QA (Multimodal verification of the stitched map and browser screenshot)
- **Validation Probe**: Worlds undergoing or failing validation receive a `validation_probe` meta tag to remain hidden from catalogs. The backend deduplicates packages by seed and only promotes the latest successful package.

Important implementation helpers live in [package_db.py](file:///home/yz_wang/yz_main/agora_2.0/agora_ui/package_db.py).

## Layer 3: Simulation Core

The shared core sits under `agora_ui/`.

Important modules:

- interaction runner
- universal adjudicator
- package DB helpers
- JSON-declared orchestration runtime
- report building
- provider compatibility adapters

This layer is the closest conceptual overlap with `agora-C`.

## Layer 4: Web Serving

FastAPI in [serve_macro_ui.py](/home/yz_wang/yz_main/agora_2.0/macro_ui/serve_macro_ui.py:1) serves:

- `/macro`
- `/pixel`
- `/api/packages/*`
- `/api/pixel/worlds/*`
- live session APIs
- live WebSocket endpoint

This is the operational boundary where package-backed data becomes a runnable web product.

## Layer 5: Live Runtime

Live state is managed by `PixelLiveStore` in [live_world.py](/home/yz_wang/yz_main/agora_2.0/agora_ui/live_world.py:1).

Current design:

- the selected package DB is the persisted source of truth
- active session spatial state is mirrored into in-memory hot state
- movement input enters through WebSocket
- a server tick loop processes buffered inputs
- movement deltas are broadcast to connected clients
- hot spatial state flushes back into SQLite on a short interval

Current defaults in code:

- tick interval: `50ms`
- flush interval: `1s`
- max buffered movement inputs per session: `12`
- max movement inputs processed per tick: `1`
- SQLite journal mode: `WAL`

This design is the compromise that keeps SQLite as the runtime bundle while removing per-step synchronous write pressure from the hot path.

## Layer 6: Frontend Runtime

The Pixel frontend is implemented in:

- [main.js](/home/yz_wang/yz_main/agora_2.0/frontend/src/main.js:1)
- [WorldScene.js](/home/yz_wang/yz_main/agora_2.0/frontend/src/WorldScene.js:1)
- [AgentManager.js](/home/yz_wang/yz_main/agora_2.0/frontend/src/AgentManager.js:1)

Current frontend live model:

- REST for bootstrapping and heavier operations
- WebSocket for realtime movement and deltas
- local client-side prediction for the controller agent
- authoritative reconciliation from server `state_delta`
- interpolation for remote agents
- slower REST snapshot fallback for completeness

The frontend is deliberately split into:

- predicted local visual state
- authoritative world state

That prevents the UI from becoming the true owner of runtime state.

## Layer 7: Asset And Pixel Presentation

Pixel presentation depends on:

- package-backed map files
- package-backed agent data
- atlas event feeds
- Phaser scene rendering

Asset generation remains a separate subsystem:

- Gemini remains the runtime interaction/media engine
- FLUX-oriented tooling remains an offline asset-production backend

`agora_2.0` may integrate both operationally, but they should not be confused architecturally.

## API Shape

The important runtime API families are:

- package export and retrieval
- pixel world catalog
- live session create/release
- live state snapshot
- live action submission
- live WebSocket realtime channel

The important realtime endpoint is:

- `/api/pixel/worlds/{access_code}/live/ws/{session_id}`

## Synchronization Boundary With `agora-C`

Keep these ideas aligned across both repositories:

- package DB contract
- JSON authoring contract
- orchestration semantics
- adjudication assumptions
- high-level runtime state model

Allow these areas to stay runnable-only in `agora_2.0`:

- FastAPI serving specifics
- systemd and Cloudflare deployment
- Pixel UI layout details
- headless browser harnesses
- load tests
- operational WebSocket manager implementation

## Practical Rule

When editing this repository, ask:

1. Is this a shared contract?
2. Is this an operational integration detail?
3. If it is shared, has `agora-C` been updated or at least documented?

That rule matters more than keeping the repositories visually identical.
