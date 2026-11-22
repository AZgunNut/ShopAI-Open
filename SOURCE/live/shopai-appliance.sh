#!/bin/bash

ROOT="$HOME/ShopAI"
VENV="$ROOT/venv"
EXTRA="/media/shopai/Extra Space"

clear
echo "========================================"
echo "          ShopAI Starting"
echo "========================================"
echo

# ---------------------------------------------------------
# 1. Make sure required ShopAI folders exist
# ---------------------------------------------------------

mkdir -p \
    "$ROOT/logs" \
    "$ROOT/work" \
    "$ROOT/checkpoints" \
    "$ROOT/local-memory"

echo "Local storage: READY"

# ---------------------------------------------------------
# 2. Verify critical ShopAI files
# ---------------------------------------------------------

MISSING=0

for FILE in \
    "$ROOT/chatgpt_browser.py" \
    "$ROOT/shopai_agent.py" \
    "$ROOT/start-bridge.sh" \
    "$ROOT/bridge/shopai_bridge.py"
do
    if [ ! -f "$FILE" ]; then
        echo "MISSING: $FILE"
        MISSING=1
    fi
done

if [ "$MISSING" -ne 0 ]; then
    echo
    echo "ERROR: Critical ShopAI files are missing."
    read -p "Press Enter to close..."
    exit 1
fi

echo "Core files: READY"

# ---------------------------------------------------------
# 3. Check Extra Space
# ---------------------------------------------------------

# Extra Space is managed by systemd automount.
# Touching the directory triggers the mount when available.
if timeout 10 ls "$EXTRA" >/dev/null 2>&1 &&
   mountpoint -q "$EXTRA"
then
    echo "Extra Space: READY"
else
    echo "WARNING: Extra Space unavailable."
    echo "Continuing on local 249-GB Linux storage."
fi

# ---------------------------------------------------------
# 4. Ensure ShopAI bridge is running
# ---------------------------------------------------------

BRIDGE_URL="http://127.0.0.1:8765/health"
BRIDGE_LOG="$ROOT/logs/bridge.log"

mkdir -p "$ROOT/logs"

if curl -fsS --max-time 2 "$BRIDGE_URL" >/dev/null 2>&1
then
    echo "Bridge: ONLINE"
else
    echo "Bridge: STARTING"

    # Prevent duplicate bridge processes if something is
    # starting but has not opened the port yet.
    if ! pgrep -f "$ROOT/bridge/shopai_bridge.py" >/dev/null 2>&1
    then
        nohup "$ROOT/start-bridge.sh" \
            >>"$BRIDGE_LOG" 2>&1 &
    fi

    BRIDGE_READY=0

    # Poll for up to 20 seconds instead of using a blind delay.
    for _ in $(seq 1 40)
    do
        if curl -fsS --max-time 2 \
            "$BRIDGE_URL" >/dev/null 2>&1
        then
            BRIDGE_READY=1
            break
        fi

        sleep 0.5
    done

    if [ "$BRIDGE_READY" -eq 1 ]
    then
        echo "Bridge: ONLINE"
    else
        echo "Bridge: FAILED TO START"
        echo
        echo "Last bridge log entries:"
        tail -20 "$BRIDGE_LOG" 2>/dev/null || true
        echo
        read -p "Press Enter to close..."
        exit 1
    fi
fi

# ---------------------------------------------------------
# 6. Verify Python environment
# ---------------------------------------------------------

if [ ! -f "$VENV/bin/activate" ]; then
    echo "Python environment: MISSING"
    echo
    read -p "Press Enter to close..."
    exit 1
fi

source "$VENV/bin/activate"

echo "Python environment: READY"

echo
echo "========================================"
echo "             ShopAI Online"
echo "========================================"
echo

# ---------------------------------------------------------
# 7. Start ShopAI
# ---------------------------------------------------------

# Chrome is prepared after AI selection. Local Qwen therefore
# remains available even when Chrome or Internet access is down.

python "$ROOT/shopai_agent.py"
SHOPAI_STATUS=$?

echo

if [ "$SHOPAI_STATUS" -eq 0 ]; then
    echo "ShopAI closed normally."
else
    echo "ShopAI stopped with error status $SHOPAI_STATUS."
fi

read -p "Press Enter to close..."
exit "$SHOPAI_STATUS"
