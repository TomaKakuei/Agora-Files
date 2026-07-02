# Agora-C Synchronization Guide

Last updated: 2026-05-23

This file records the intended synchronization boundary between:

- `agora-C`
- `agora_2.0`

It is written from the runnable repo perspective.

## Current Position

The two repositories are related, but they are not supposed to be identical.

- `agora-C` is the lean core repository.
- `agora_2.0` is the runnable integration repository.

They must share the same core runtime contract while allowing operational divergence.

## Shared Contract That Must Stay Aligned

These ideas should stay synchronized:

- JSON is the authoring surface
- `world_package.db` is the runtime bundle
- package export and pull semantics
- `world_config.json` top-level contract
- orchestration semantics
- adjudication semantics
- package DB helper behavior
- high-level live runtime contract

If one repository changes one of these, update or document the other in the same session.

## Runnable-Only Areas That Can Diverge

These are expected to remain primarily `agora_2.0` responsibilities:

- FastAPI app and routing
- live WebSocket manager
- package-serving APIs
- `PIXEL READ` world-catalog behavior
- Macro UI and Pixel UI operational wiring
- systemd and Cloudflare deployment
- Firefox headless regression harness
- live load tests
- heavier asset and validation workflows

These should not be copied into `agora-C` unless they become true core contracts.

## Lean-Core Areas That Belong In `agora-C`

`agora-C` should continue to emphasize:

- small reference samples
- shared schemas
- orchestration defaults and design
- minimal package examples
- core tests that do not depend on runnable deployment wiring
- documentation of the repo split and runtime contract

It should not become a second heavy artifact or operations repo.

## Current Live Runtime Sync Point

As of 2026-05-23, the important live-runtime truth is:

- DB-backed live sessions remain authoritative
- high-frequency movement uses WebSocket, not REST polling
- `PixelLiveStore` maintains hot in-memory spatial state
- hot movement state flushes back into SQLite
- frontend prediction exists, but the package DB remains authoritative

That architectural direction should be reflected conceptually in both repositories, even if only `agora_2.0` carries the full operational implementation.

## Documentation Sync Applied In This Session

The following maintained docs were refreshed to the current DB-first architecture:

- `agora_2.0/README.md`
- `agora_2.0/README For LLM.md`
- `agora_2.0/ARCHITECTURE.md`
- `agora_2.0/MemoryFrontEnd.md`
- `agora_2.0/deploy/CLOUDFLARE_TUNNEL.md`
- `agora-C/README.md`
- `agora-C/README For LLM.md`
- `agora-C/ARCHITECTURE.md`

The goal was to remove stale assumptions such as:

- JSON-only runtime wording
- old local path examples
- HTTP-poll-only live movement wording
- unclear repo-role boundaries

## Shared Files To Watch Closely

These files are especially likely to drift in meaningful ways:

- `agora_ui/package_db.py`
- `agora_ui/run_interaction_simulation.py`
- `agora_ui/run_universal_adjudicator.py`
- `agora_ui/runtime/defaults.py`
- `agora_ui/runtime/operations.py`
- top-level README files

Review them intentionally, not only by checksum.

## Practical Sync Rule

When a change lands in `agora_2.0`, classify it before porting:

1. Shared core contract
   Sync into `agora-C`.
2. Runnable integration detail
   Keep in `agora_2.0`, but document it if it affects how others understand the system.
3. Temporary experiment
   Either finish it and document it, or remove it before it becomes accidental drift.

## Non-Goals

Do not sync these blindly:

- deployment units
- generated artifacts
- package export history
- browser harness output
- heavy UI layout details
- local operational scripts

The goal is contract alignment, not duplication for its own sake.
