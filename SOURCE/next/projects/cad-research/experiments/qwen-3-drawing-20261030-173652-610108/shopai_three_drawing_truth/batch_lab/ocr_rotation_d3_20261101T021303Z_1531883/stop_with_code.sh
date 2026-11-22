#!/usr/bin/env bash
set -Eeuo pipefail
R=/mnt/shopai-data-new/cad-research/experiments/qwen-3-drawing-20261030-173652-610108/shopai_three_drawing_truth/batch_lab/ocr_rotation_d3_20261101T021303Z_1531883
[[ "${1:-}" == "$(cat "$R/kill_code.txt")" ]] || { echo "INVALID CODE"; exit 2; }
(umask 077; touch "$R/TERMINATE")
echo "Requested safe stop; only this run will stop its owned processes."
