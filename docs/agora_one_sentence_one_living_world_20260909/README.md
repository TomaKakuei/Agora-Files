# Agora: One Sentence, One Living World

This is the 2026-09-09 paper release. It contains the versioned paper, its 11
figures in both PDF and PNG formats, the source code and frozen inputs used to
render every figure, and matched English and Chinese human-evaluation forms.

## Contents

- `agora_one_sentence_one_living_world_20260909.pdf`: compiled paper
- `agora_one_sentence_one_living_world_20260909.tex`: paper source
- `figures/`: publication figures in vector PDF and raster PNG formats
- `figure_sources/`: Matplotlib source, frozen metrics, and selected visual
  inputs needed to reproduce all 11 publication figures
- `human_evaluation/`: self-contained English and Chinese questionnaire PDFs,
  LaTeX sources, administration method, and response template

## Build

Run XeLaTeX twice from this directory:

```bash
xelatex -interaction=nonstopmode -halt-on-error agora_one_sentence_one_living_world_20260909.tex
xelatex -interaction=nonstopmode -halt-on-error agora_one_sentence_one_living_world_20260909.tex
```

To rebuild the figures first:

```bash
python figure_sources/reproduce_and_verify.py
```

The regenerated files are written to `reproduced_figures/`. See
`figure_sources/README.md` for the figure-to-function map.

Build either questionnaire from `human_evaluation/` with XeLaTeX. Each PDF
contains all evidence needed by a rater; no Agora runtime is required.
