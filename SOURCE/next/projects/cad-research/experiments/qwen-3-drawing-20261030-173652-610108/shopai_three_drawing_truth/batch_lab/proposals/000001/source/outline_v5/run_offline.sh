#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${SHOPAI_PYTHON:-/mnt/shopai-data-new/cad-research/environments/common/bin/python}"
[[ -x "$PY" ]] || { echo "ERROR: offline Python not installed: $PY" >&2; exit 1; }
IMAGE="${1:-$HERE/25-1.jpg}"
TRIALS="${2:-5000}"
[[ -f "$IMAGE" ]] || { echo "Missing image: $IMAGE" >&2; exit 1; }
[[ "$TRIALS" =~ ^[0-9]+$ ]] || { echo "Trials must be integer" >&2; exit 1; }
OUT="$HERE/results/$(date +%Y%m%d-%H%M%S)-$(basename "$IMAGE" | tr -cd 'A-Za-z0-9._-')"
mkdir -p "$OUT"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
"$PY" "$HERE/autotune.py" --image "$IMAGE" --out "$OUT" --trials "$TRIALS" \
  --registry "$HERE/model_registry.json" | tee "$OUT/run.log"
printf '%s\n' "$OUT" > "$HERE/latest-run.txt"
echo "READY: $OUT/report.html"
