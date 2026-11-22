#!/usr/bin/env bash
set -Eeuo pipefail
R=/mnt/shopai-data-new/cad-research/experiments/qwen-3-drawing-20261030-173652-610108/shopai_three_drawing_truth/batch_lab/selector_evolution_v2
[[ "${1:-}" == "$(cat "$R/kill_code.txt")" ]] || { echo "INVALID STOP CODE"; exit 2; }
(umask 077; touch "$R/TERMINATE")
echo "TERMINATE requested for selector v2."
