#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY_BIN="/home/yz_wang/.conda/envs/new_py310/bin/python"

if [[ ! -x "${PY_BIN}" ]]; then
  echo "new_py310 python not found at: ${PY_BIN}" >&2
  exit 2
fi

export MKL_SERVICE_FORCE_INTEL=1
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH:-}"

exec "${PY_BIN}" "${SCRIPT_DIR}/macro_ui/build_macro_ui.py" "$@"
