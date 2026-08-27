# Figure Sources

The paper's diagrams and evidence figures were rendered with Matplotlib rather
than TikZ. This directory contains the two source programs and a frozen,
minimal input snapshot. No network call, model API, or Agora runtime is needed.

## Rebuild

From the paper directory:

```bash
python figure_sources/reproduce_and_verify.py
```

The command rebuilds all figures and verifies that all 11 regenerated PNGs are
byte-identical to the publication copies. The two rendering programs can also
be run separately and accept `--output-root`. By default they write PDF and PNG
files to `reproduced_figures/`. Required Python packages are listed in
`requirements.txt`.

## Figure Map

| Paper file | Source function | Program |
|---|---|---|
| `generation_overview` | `architecture_figure` | `make_generation_figures.py` |
| `generated_worlds` | `world_strip_figure` | `make_generation_figures.py` |
| `world_quality_results` | `results_figure` | `make_generation_figures.py` |
| `multiworld_interactions` | `multiworld_dashboard` | `make_social_figures.py` |
| `pilot_social_dynamics` | `pilot_dynamics` | `make_social_figures.py` |
| `situated_action_cycle` | `coordinator_loop` | `make_social_figures.py` |
| `clockwork_social_episode` | `clockwork_episode` | `make_social_figures.py` |
| `memory_intervention_design` | `experiment_design` | `make_social_figures.py` |
| `tidal_embassy_visual_elements` | `tidal_artifact_gallery` | `make_social_figures.py` |
| `localized_visual_refinement` | `tidal_repair_trace` | `make_social_figures.py` |
| `embodied_character_interaction` | `tidal_runtime_capture` | `make_social_figures.py` |

## Frozen Inputs

- `input_snapshot/docs/benchmark_20260724/`: paired world-generation results
- `input_snapshot/docs/world_interaction_experiment_20260803/`: interaction
  and social-dynamics metrics
- `input_snapshot/frontend/assets/generated/`: the exact maps, characters,
  rooms, repair attempts, and prop used in the composite figures
- `input_snapshot/runtime_captures/`: the two Firefox player-view captures

The snapshot intentionally contains only files read by the figure programs.
Minor byte-level differences in PDFs can occur across Matplotlib versions, but
the plotted values, layout, labels, and raster inputs are frozen here.
