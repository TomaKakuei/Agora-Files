# Agora World Interaction Study

This directory separates the completed multiworld execution evidence,
historical pilot evidence, and the preregistered confirmatory experiment.

## Research question

When a typed world supplies space, roles, private state, persistent memory,
relationships, and actionable objects, do initially local events become
world-level social processes rather than disconnected dialogues?

## Confirmatory design

- World: `Tidal Embassy of Lost Languages`, 25 agents, 32 rounds.
- Seed event: only three agents initially know that a flood threatens the sole
  surviving peace treaty in the lower archive.
- Full condition: persistent episodic memory, relationship updates, spatial
  movement, items, and world rules.
- Memory ablation: identical profiles, model, temperature, activation schedule,
  and random seed; prior-round social memory is removed before each round.
- Seeds: `26080311`, `26080312`, `26080313` per condition.
- Primary outcome: fraction of initially uninformed agents whose recorded
  action or memory contains a seed-event fact by round 16.
- Secondary outcomes: time to first cross-room transmission, rescue-task
  participation, unique and repeated dyads, largest interaction component,
  route entropy, relationship change, item transfers, and rule violations.
- Qualitative evidence: a fixed, deterministic selection rule reports the
  earliest cross-room transmission, first coordinated rescue, largest trust
  reversal, and one failed coordination episode. No hand-picked examples.

Historical runs are analyzed only as pilot evidence. They must not be pooled
with the paired confirmatory runs.

## Current execution status

On 2026-08-03 the original Vertex project returned
`RESOURCE_PROJECT_INVALID`. The experiment was moved to AI Studio using a key
supplied out of band. A full-memory smoke run then completed one round with
eight real interactions. It is retained as end-to-end validation, not pooled
with the preregistered confirmatory runs.

The run selected Redaction Game six times, Rescue Treaty once, and Dialect Duel
once. Eleven participants appeared across eight dyads; the largest interaction
component contained six participants. The API key is not stored here.

## Completed multiworld study

On 2026-08-04, five held-out worlds were run for two rounds each through AI
Studio with activation probability `0.12`, fixed seeds `26080411` through
`26080415`, fixed compiled profiles, and image/video generation disabled. The
accepted runs are `multiworld_runs/mw3_*`; earlier `mw_*` attempts are excluded
because a shared mutable scenario directory caused cross-world contamination,
and `mw2_*` attempts made no model progress because sandbox DNS was unavailable.

The runtime now puts mutable scenario state under each run directory and aborts
when materialized agent IDs differ from the current config. All five accepted
runs pass this identity audit. Their aggregate evidence is:

- 53 logged interaction events and 37 within-world unique dyads;
- 10 coordinator-approved open proposals and 9 compiled world-specific actions;
- 13 AI actions targeting the live human interactor;
- 87.5% success across 61 adjudicated action results.

Per-world metrics, routes, relationship deltas, and identity checks are in
`multiworld_metrics.json`. Raw evidence remains in each accepted run's
`story.jsonl`, `timeline.jsonl`, intent batches, and timestep snapshots. The API
key is not stored in configs, logs, or this directory.

## Pilot analysis

Run:

```bash
python -m scripts.agora_social_dynamics_analysis \
  /path/to/story.json --output docs/world_interaction_experiment_20260803/pilot_metrics.json
```

The analyzer uses only logged state: no LLM judge and no subjective coding.
