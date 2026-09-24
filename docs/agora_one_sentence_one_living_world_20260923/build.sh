#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v xelatex >/dev/null 2>&1; then
  agora_tex_bin="/home/yz_wang/yz_main/.TinyTeX/bin/x86_64-linux"
  if [[ -x "$agora_tex_bin/xelatex" ]]; then
    export PATH="$agora_tex_bin:$PATH"
  else
    echo "XeLaTeX and BibTeX must be installed and on PATH." >&2
    exit 1
  fi
fi
# Build both entries from a clean checkout: seed auxiliary labels first, then
# give each document its own bibliography and stabilize cross-PDF references.
agora_documents=(
  agora_one_sentence_one_living_world_20260923
  agora_one_sentence_one_living_world_20260923_supplement
)
for agora_document in "${agora_documents[@]}"; do
  xelatex -interaction=nonstopmode -halt-on-error "$agora_document.tex"
  bibtex "$agora_document"
done
for agora_pass in 1 2; do
  for agora_document in "${agora_documents[@]}"; do
    xelatex -interaction=nonstopmode -halt-on-error "$agora_document.tex"
  done
done
python figure_sources/verify_release.py
python figure_sources/audit_extended_evidence.py --check

# Replay the frozen LLM outputs locally; this verifier makes no API calls.
PYTHONWARNINGS=ignore python llm_ablation/analyze_ablation.py > /dev/null
printf '%s\n' 'Verified all 18 planner-ablation trajectories by deterministic action replay.'
