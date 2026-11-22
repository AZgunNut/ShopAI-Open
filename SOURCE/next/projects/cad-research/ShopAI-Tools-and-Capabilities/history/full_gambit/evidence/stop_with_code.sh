#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
R=/mnt/shopai-data-new/cad-research/experiments/qwen-3-drawing-20261030-173652-610108/shopai_three_drawing_truth/batch_lab/ocr_outline_eight_v1/results/full_gambit_20261108T191855Z_740546_12852
[[ "${1:-}" == "$(cat "$R/STOP_CODE")" ]] || { echo BAD_CODE; exit 2; }
touch "$R/TERMINATE"
echo TERMINATE_SENTINEL_CREATED
