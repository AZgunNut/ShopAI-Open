#!/usr/bin/env bash
set -Eeuo pipefail
[[ $# -eq 2 ]] || { echo 'Usage: run.sh INPUT.json OUTPUT_DIR' >&2; exit 2; }
TOOL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_PY="/mnt/shopai-data-new/ShopAI-Next/projects/cad-research/environments/cadquery-2.8.0-isolated-v1/bin/python"
[[ -x "$ENV_PY" ]] || { echo 'Cloned CadQuery Python missing' >&2; exit 3; }
export PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PIP_NO_INDEX=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
unset PYTHONPATH PYTHONHOME
exec "$ENV_PY" -B "$TOOL_DIR/create_parametric.py" "$1" "$2"
