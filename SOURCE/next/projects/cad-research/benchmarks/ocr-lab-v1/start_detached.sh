#!/usr/bin/env bash
# Start a long-lived campaign independent of SSH session.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$HERE/experiments"
# Store a PID. The run uses its own flock to prevent two workers writing at once.
PIDFILE="$HERE/experiments/worker.pid"
if [[ -f "$PIDFILE" ]]; then
  previous="$(cat "$PIDFILE")"
  if [[ "$previous" =~ ^[0-9]+$ ]] && kill -0 "$previous" 2>/dev/null; then
    if [[ -r "/proc/$previous/cmdline" ]] && tr '\0' ' ' < "/proc/$previous/cmdline" | grep -qF "$HERE"; then
      echo "ERROR: an OCR Lab worker is already running (PID=$previous)" >&2
      exit 1
    fi
  fi
fi
LOG="$HERE/experiments/worker.log"
nohup "$HERE/run_shopai.sh" "$@" >> "$LOG" 2>&1 < /dev/null &
PID=$!
printf '%s\n' "$PID" > "$PIDFILE"
sleep 2
if ! kill -0 "$PID" 2>/dev/null; then
  echo "ERROR: worker stopped immediately. See $LOG" >&2
  tail -35 "$LOG" || true
  exit 1
fi
echo "STARTED_PID=$PID"
echo "LOG=$LOG"
echo "DATABASE=$HERE/experiments/lab.sqlite3"
echo "STATUS_COMMAND=bash $HERE/status.sh"
