#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
export NO_PROXY="*" no_proxy="*"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
PYTHON=/mnt/shopai-data-new/cad-research/environments/paddleocr/bin/python
[[ -x "$PYTHON" ]] || { echo "ERROR: ShopAI offline PaddleOCR venv missing" >&2; exit 2; }
[[ -f "$HERE/new_drawing.jpeg" ]] || { echo "ERROR: image missing" >&2; exit 2; }
(cd "$HERE" && "$PYTHON" -m unittest -q test_blind)
"$PYTHON" "$HERE/blind_test.py" "$@"
