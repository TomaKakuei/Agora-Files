#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
for agora_tool in xelatex bibtex; do
  if ! command -v "$agora_tool" >/dev/null 2>&1; then
    echo "$agora_tool is required; install TeX Live or MiKTeX and add its binaries to PATH." >&2
    exit 1
  fi
done
agora_documents=(
  agora_one_sentence_one_living_world_20260923
  agora_one_sentence_one_living_world_20260923_supplement
)
# Seed both documents' labels and build their separate bibliographies.
for agora_document in "${agora_documents[@]}"; do
  xelatex -interaction=nonstopmode -halt-on-error "$agora_document.tex"
  bibtex "$agora_document"
done
# Resolve links between the main paper and the supplement.
for agora_pass in 1 2; do
  for agora_document in "${agora_documents[@]}"; do
    xelatex -interaction=nonstopmode -halt-on-error "$agora_document.tex"
  done
done
