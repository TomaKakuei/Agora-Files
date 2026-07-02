#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY_BIN="${PY_BIN:-python3}"
SITE_PACKAGES=$("${PY_BIN}" -c 'import site; print(site.getsitepackages()[0])')
export AGORA_FLUX_MODEL="${AGORA_FLUX_MODEL:-YuCollection/FLUX.1-schnell-Diffusers}"
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION="${PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION:-python}"

CUDA_LIB_PATHS=(
  "${SITE_PACKAGES}/nvidia/nvjitlink/lib"
  "${SITE_PACKAGES}/nvidia/cusparse/lib"
  "${SITE_PACKAGES}/nvidia/cublas/lib"
  "${SITE_PACKAGES}/nvidia/cuda_runtime/lib"
  "${SITE_PACKAGES}/nvidia/cudnn/lib"
)

for lib_path in "${CUDA_LIB_PATHS[@]}"; do
  if [[ -d "${lib_path}" ]]; then
    export LD_LIBRARY_PATH="${lib_path}:${LD_LIBRARY_PATH:-}"
  fi
done

export PYTHONPATH="${ROOT_DIR}:${PYTHONPATH:-}"
exec "${PY_BIN}" -m agora_ui.flux_asset_service --bind 127.0.0.1 --port 8135 "$@"
