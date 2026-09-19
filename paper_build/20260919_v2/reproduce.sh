#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python verify_bundle.py
cd paper
bash build.sh
python figure_sources/reproduce_and_verify.py
