#!/usr/bin/env bash
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON="${PYTHON:-/home/yz_wang/.conda/envs/new_py310/bin/python}"
XELATEX="${XELATEX:-/home/yz_wang/.conda/envs/new_py310/bin/xelatex}"

cd "$ROOT"
"$PYTHON" make_figures.py
mkdir -p build
"$XELATEX" -interaction=nonstopmode -halt-on-error -output-directory=build report.tex
"$XELATEX" -interaction=nonstopmode -halt-on-error -output-directory=build report.tex
cp build/report.pdf agora_comprehensive_world_evaluation_20260826.pdf
printf 'Built %s\n' "$ROOT/agora_comprehensive_world_evaluation_20260826.pdf"
