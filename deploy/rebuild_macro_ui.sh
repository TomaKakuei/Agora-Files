#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUN_DIR_DEFAULT="${ROOT_DIR}/output/debug_run/20260426_213617_035143"

if [[ -z "${AGORA_VERTEX_API_KEY:-}" ]]; then
  echo "AGORA_VERTEX_API_KEY is not set." >&2
  exit 2
fi

"${ROOT_DIR}/launch_macro_ui_new_py310.sh" \
  --run-dir "${1:-${RUN_DIR_DEFAULT}}" \
  --max-agent-images 8
