#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$HERE/lab.py" status --workdir "$HERE/experiments"
echo '--- MOST RECENT MESSAGES ---'
if [[ -f "$HERE/experiments/worker.log" ]]; then
  tail -15 "$HERE/experiments/worker.log"
fi
