#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${HOME}/.config/agora_ui_runtime.env"
PYTHON_BIN="${PYTHON_BIN:-python3}"
REVISION="${1:-guild_replaceable_full_20260506_01}"
shift || true

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

if [[ -z "${AGORA_AISTUDIO_API_KEY:-}" ]]; then
  echo "AGORA_AISTUDIO_API_KEY is not set after sourcing ${ENV_FILE}" >&2
  exit 2
fi

exec "${PYTHON_BIN}" "${ROOT_DIR}/asset_pipeline/retry_failed_guild_assets.py" \
  --config "${ROOT_DIR}/sample_json/world_config.json" \
  --scenario-dir "${ROOT_DIR}/sample_json/scenario" \
  --revision "${REVISION}" \
  --update-current-alias \
  "$@"
