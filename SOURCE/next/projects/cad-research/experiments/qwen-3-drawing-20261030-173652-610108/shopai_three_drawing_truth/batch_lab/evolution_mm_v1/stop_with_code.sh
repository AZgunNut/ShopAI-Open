#!/usr/bin/env bash
set -Eeuo pipefail
R="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$R/STOP_CODE" ]] || { echo 'STOP: missing secret stop code'; exit 2; }
[[ "${1:-}" == "$(cat "$R/STOP_CODE")" ]] || { echo 'STOP: incorrect 24-character code'; exit 3; }
touch -- "$R/TERMINATE"
echo 'TERMINATE sentinel created for evolution_mm_v1; owned subprocesses will stop.'
