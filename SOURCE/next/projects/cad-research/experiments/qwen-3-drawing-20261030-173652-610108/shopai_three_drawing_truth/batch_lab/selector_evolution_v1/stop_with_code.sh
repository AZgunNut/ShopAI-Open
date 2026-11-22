#!/usr/bin/env bash
set -Eeuo pipefail
R='/mnt/shopai-data-new/cad-research/experiments/qwen-3-drawing-20261030-173652-610108/shopai_three_drawing_truth/batch_lab/selector_evolution_v1'
[[ "${1:-}" == "$(cat "$R/kill_code.txt")" ]] || { echo 'STOP CODE INVALID'; exit 2; }
(umask 077; touch "$R/TERMINATE")
echo 'TERMINATE sent to selector evolution. Original Qwen server is untouched.'
