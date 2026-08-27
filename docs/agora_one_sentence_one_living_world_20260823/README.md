# Agora: One Sentence, One Living World

This release contains the latest 14-page paper, its 11 figures in both PDF and
PNG formats, and the source code plus frozen inputs used to render every figure.

## Contents

- `agora_one_sentence_one_living_world.pdf`: compiled paper
- `agora_one_sentence_one_living_world.tex`: self-contained paper source
- `figures/`: publication figures in vector PDF and raster PNG formats
- `figure_sources/`: Matplotlib source, frozen metrics, and selected visual
  inputs needed to reproduce all 11 publication figures

## Build

Run XeLaTeX twice from this directory:

```bash
xelatex -interaction=nonstopmode -halt-on-error agora_one_sentence_one_living_world.tex
xelatex -interaction=nonstopmode -halt-on-error agora_one_sentence_one_living_world.tex
```

To rebuild the figures first:

```bash
python figure_sources/reproduce_and_verify.py
```

The regenerated files are written to `reproduced_figures/`. See
`figure_sources/README.md` for the figure-to-function map.
