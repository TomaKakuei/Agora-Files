# Benchmark Integrity Audit

## Uniform retry rule

All models use the same prompt, schema, local validator, layer-specific retry
budgets, and scoring weights. The generation and runtime layers permit up to
three transport attempts per call; the already-frozen community runner permits
two. Every model within a layer receives the same budget, and every attempt
must retain the requested model. If transport failures exhaust the budget, the case is marked
`infrastructure_inconclusive` and is rerun unchanged after service recovery.
It is not converted into a model-quality zero.

A completed model response that violates the shared schema or semantic
contract may use the same localized repair path available to every model. The
generated-world layer permits three semantic attempts per node; community and
runtime plans receive one attempt and are scored as returned. Each successful
generation repair multiplies that case's generated-world score by 0.98.
Exhausting the three generation attempts without a compilable world scores zero.
First-pass pass rate and semantic repair count remain visible alongside the
adjusted score.

The machine-readable policy is `retry_policy_v1.json`. It was specified after
the current world-generation calls had started, so applying it to those calls
is a uniform retrospective sensitivity analysis, not a preregistered result.
It is prospective for the community and runtime calls that follow. The next
hidden generation suite must commit the policy, prompts, adapters, validators,
and weights before its first target-model call.

## Gemini substitution audit

The 15 confirmatory world trials contain 176 structured-call telemetry rows.
Every row records `status=ok`; all 173 contract-relevant calls ended with
`STOP`, while three post-compilation prose summaries from Gemini 2.5 Flash
ended with `MAX_TOKENS`. Every recorded model identifier equals the requested
Gemini model. Searches across generation, community, and corrected runtime
evidence find no `gemini-2.5-pro` response and no `VERTEX_FALLBACK` event.

The client did contain an older branch that would substitute Gemini 2.5 Pro
after a Gemini 3.1 HTTP 503. That branch did not execute in the reported
confirmatory evidence, but it violated the benchmark's intended model identity
rule and has now been removed.

Successful Gemini worlds used no deterministic inventory fallback and no
compiler-critique content repair. Localized generation repairs were:

| Model | Compiled worlds | First-pass worlds | Semantic repairs |
|---|---:|---:|---:|
| Gemini 3.7 Flash | 3/3 | 3/3 | 0 |
| Gemini 2.5 Flash | 3/3 | 2/3 | 2 |
| Gemini 3.1 Flash Lite | 3/3 | 2/3 | 1 |
| Gemini 3.1 Pro Preview | 3/3 | 0/3 | 4 |
| Gemini 3.5 Flash Lite | 1/3 | 1/3 | 0 in the successful artifact |

The Gemini 3.1 Pro repairs were content violations rather than router errors:
unsupported relationship types `evade`, `investigate`, and `bribe`, followed
by one unresolved relationship target. They are therefore subject to the same
2% semantic-repair multiplier as any other model.

## GPT extension audit

The GPT generation extension used the same three sentences, schemas,
specialist decomposition, validators, compiler, temperature, agent count, and
semantic-repair ceiling. Every successful response is attributed to the
requested GPT model; no generation trial records a transport failure or model
substitution.

| Model | Compiled worlds | First-pass worlds | Semantic repairs |
|---|---:|---:|---:|
| GPT-5.6 Sol | 3/3 | 1/3 | 2 |
| GPT-5.6 Terra | 1/3 | 0/3 | 1 in the successful artifact; 6 across two exhausted planners |
| GPT-5.6 Luna | 0/3 | 0/3 | 9 exhausted relationship attempts |

Sol's two repairs both correct an exact role-count violation. Terra's two failed
worlds omit required planner structure on each of three semantic attempts.
Luna's three worlds exhaust the relationship stage on invalid references or
types. These are model-content outcomes under the common contract and remain
zeros. No model-specific parser, alternate schema, or relaxed relationship rule
was introduced.

The initial GPT community run was executed without external name resolution.
Its empty responses and zero token counts identify a transport failure rather
than model output. It is preserved as
`community_results_gpt_invalid_transport.json` and excluded. The same prompts,
models, decoding parameters, scorer, and two-attempt transport policy were then
run after network recovery. All nine valid scenario calls succeeded on their
first attempt and are stored in `community_results_gpt.json`.

## Runtime correction

The earlier Gemini 3.1 Pro runtime score of 31.36 came from a harness defect:
human interventions were issued while the human occupied an empty room, making
all local uptake checks impossible. The shared harness was corrected to move
the human into an occupied room before each intervention, then every Gemini
model was rerun for three independent 24-round trajectories. Gemini 3.1 Pro
scored 91.59 with population standard deviation 2.02. The formal generation
telemetry does not support attributing its earlier low result to timeout or
router failure.

The corrected runtime protocol was then applied without change to the GPT
extension. GPT-5.6 Sol scores 97.54 with population standard deviation 0.39
across three 24-round trajectories. GPT-5.6 Terra scores 96.15 with population
standard deviation 0.43 in its only compiled first-prompt world. GPT-5.6 Luna
has no runtime score because it produced no compiled world; the harness did not
construct a surrogate world for it.

## Asset evidence

The visual extension uses the same FLUX2 model and quality rules. GPT-5.6 Sol's
first world references 20 semantic map components; all 20 are generated and all
three representative directional character sheets pass. GPT-5.6 Terra
references 14 components; all 14 are generated and two of three representative
characters pass. The third remains rejected after three attempts because its
silhouette aspect exceeds the common threshold. The threshold was not changed,
and no manual or generic replacement enters the score.

The component generator previously enforced a fixed 12-job ceiling even when a
compiled world referenced more components. The reported asset runs derive the
requested job count from the compiled semantic graph with a shared hard maximum
of 64. This common capacity correction was applied before both Sol and Terra
visual evaluation.

## Remaining evidence limits

The hidden prompt file predates the first Gemini call by seconds and its SHA-256
digest is recorded, but the suite and scoring code were ignored by the
repository and were not committed before execution. The existing report must
therefore avoid an immutable preregistration claim. The failed-generation
result format also discarded semantic retry events even though they appeared
in the console; the exception now carries those events into future result
artifacts. Current failed GPT cases retain their zero outcome, and their repair
counts are reconstructed only in the supplementary audit rather than silently
altering original evidence.
