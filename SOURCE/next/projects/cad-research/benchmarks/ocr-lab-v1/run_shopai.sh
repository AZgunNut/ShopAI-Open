#!/usr/bin/env bash
# Load the existing offline PaddleOCR CPU model once and evaluate many trials.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE=/mnt/shopai-data-new/cad-research
PY="${SHOPAI_PADDLE_PYTHON:-$BASE/environments/paddleocr/bin/python}"
[[ -x "$PY" ]] || { echo "ERROR: offline PaddleOCR Python missing: $PY" >&2; exit 1; }
TRIALS="${1:-2000}"
HOURS="${2:-72}"
IMAGE="${3:-$HERE/25-1.jpg}"
VARIANT="${4:-server}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
export NO_PROXY='*' no_proxy='*'
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
# Never permit accidental use of another OCR model download path.
exec "$PY" -u "$HERE/lab.py" run \
  --workdir "$HERE/experiments" \
  --image "$IMAGE" --models-root "${SHOPAI_OCR_MODELS:-$BASE/ocr-next}" \
  --variant "$VARIANT" --trials "$TRIALS" --max-hours "$HOURS" \
  --mem-floor-gb "${SHOPAI_OCR_MEM_FLOOR_GB:-8}"
