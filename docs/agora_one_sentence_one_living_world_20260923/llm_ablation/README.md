# Supplementary planner input and action-space diagnostics

Completed 18 formal trajectories using Gemini 2.5 Flash in Clockwork Rain Conservatory and Tidal Embassy: Full, No event history, and Catalog only, with three stochastic repeats each. Each trajectory has 24 rounds, six planning calls, and 72 scheduled action slots. The human study is unchanged.

| Configuration | Success / 432 | Inventory or location changes | Inventory changes | Moves |
|---|---:|---:|---:|---:|
| Full | 349 | 196 | 14 | 182 |
| No event history | 352 | 177 | 24 | 153 |
| Catalog only | 375 | 193 | 0 | 193 |

These counters describe the implemented planner and available handlers. Inventory changes are impossible through this harness's catalog handlers, so zero in the closed condition is partly structural. The recorded results do not establish a benefit from supplied event history. Neither execution success nor movement measures useful task completion. Both aggregate and per-trajectory tables appear in the supplement; the main paper uses an explicitly identified trace to explain proposal validation, persistent effects, and subsequent observation. These diagnostics do not measure the mechanism's novelty or overall value.

## Evidence

- `protocol.json`: scope, randomized run order, settings, primary denominators, input/source hashes; frozen locally before formal calls, following an excluded technical pilot. No external preregistration is claimed.
- `inputs/`: two shared world definitions, initial states, and rules.
- `runtime_snapshot/`: the actual world materializer, coordinator, handlers, and support code used, copied from the existing implementation. No production code was changed for these ablations.
- `runs/`: every supplied prompt payload, response schema, returned plan, telemetry, event, and state; `trajectory.json` aggregates each run. A truncated response is retained through its failure telemetry; the malformed raw text itself is not archived by the legacy client.
- `pilot/`: three excluded eight-round technical runs (six planning calls).
- `summary.json` and `trajectory_results.csv`: complete descriptive results and paired differences.
- `generated/`: aggregate and per-trajectory tables, both included in the supplement; the aggregate filename `main_table.tex` is retained for reproducibility.

The formal study has 108 completed planning blocks and 109 API attempts, including one invalid-JSON/truncation retry. It records 1,821,701 input and 201,841 output tokens. All 220 failed actions leave recorded state unchanged. API repeat indices are not provider random seeds. This is a centralized four-round planner study; it does not complete the separate decentralized Tidal memory protocol.

## Verify without model calls

From the paper directory:

```bash
PYTHONWARNINGS=ignore python llm_ablation/test_ablation.py
PYTHONWARNINGS=ignore python llm_ablation/analyze_ablation.py
bash build.sh
```

The analyzer checks frozen hashes, reconstructs all prompt treatments, and re-executes the recorded actions and interventions through the frozen runtime. It verifies every state and event against the saved record before generating tables. Tests check treatment isolation and failure denominators. Runtime dependency versions are recorded in `environment.json`; the Python verifier uses Pydantic, Pillow, requests, and google-auth through the archived implementation.

`run_ablation.py run` is the model-calling command, separate from verification. It resumes completed blocks and validates source hashes. Credentials are read from the named environment file and are never written into artifacts. Completed runs are reused. A new model-calling study requires a new directory/version and a newly frozen protocol; do not overwrite the original evidence.
