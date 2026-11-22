#!/bin/bash

ROOT="$HOME/ShopAI"
VENV="$ROOT/venv"

cd "$ROOT" || exit 1

clear
echo "========================================"
echo "          ShopAI Starting"
echo "========================================"
echo

# Start bridge if it is not already running
if ! python3 - <<'PY' >/dev/null 2>&1
import urllib.request
urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=1)
PY
then
    echo "Starting ShopAI bridge..."
    "$ROOT/start-bridge.sh" >> "$ROOT/logs/bridge-console.log" 2>&1 &
    BRIDGE_PID=$!

    # Wait up to 10 seconds for bridge
    for i in {1..20}; do
        if python3 - <<'PY' >/dev/null 2>&1
import urllib.request
urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=1)
PY
        then
            break
        fi
        sleep 0.5
    done
fi

# Verify bridge
if python3 - <<'PY' >/dev/null 2>&1
import urllib.request
urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=2)
PY
then
    echo "Bridge: ONLINE"
else
    echo "Bridge: FAILED TO START"
    echo
    read -p "Press Enter to close..."
    exit 1
fi

# Activate ShopAI Python environment
source "$VENV/bin/activate"

echo "OpenAI agent: READY"
echo
echo "========================================"
echo "             ShopAI Online"
echo "========================================"
echo

# Run agent and keep terminal available if it exits
python "$ROOT/shopai_agent.py"

echo
echo "ShopAI agent stopped."
read -p "Press Enter to close..."
