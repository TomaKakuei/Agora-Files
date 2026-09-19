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
agora_paper_name="agora_one_sentence_one_living_world_20260919"
xelatex -interaction=nonstopmode -halt-on-error "$agora_paper_name.tex"
bibtex "$agora_paper_name"
xelatex -interaction=nonstopmode -halt-on-error "$agora_paper_name.tex"
xelatex -interaction=nonstopmode -halt-on-error "$agora_paper_name.tex"
python figure_sources/verify_release.py

python figure_sources/audit_extended_evidence.py --check
