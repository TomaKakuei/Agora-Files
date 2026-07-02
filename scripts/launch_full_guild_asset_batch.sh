#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${HOME}/.config/agora_ui_runtime.env"
PYTHON_BIN="${PYTHON_BIN:-python3}"
REVISION="${1:-guild_replaceable_full_$(date -u +%Y%m%d_%H%M%S)}"
shift || true

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

exec "${PYTHON_BIN}" "${ROOT_DIR}/asset_pipeline/generate_world_asset_set.py" \
  --config "${ROOT_DIR}/sample_json/world_config.json" \
  --scenario-dir "${ROOT_DIR}/sample_json/scenario" \
  --revision "${REVISION}" \
  --all-active-agents \
  --update-current-alias \
  "$@"
