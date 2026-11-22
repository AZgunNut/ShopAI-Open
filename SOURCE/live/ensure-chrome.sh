#!/usr/bin/env bash

# Start and verify the authenticated ShopAI Chrome session.
# Exit 0 when ready; exit 1 after the readiness timer expires.

WAIT_SECONDS="${1:-60}"
CHROME_USE="$HOME/.local/bin/chrome-use"

if [ ! -x "$CHROME_USE" ]; then
    CHROME_USE="$(
        command -v chrome-use 2>/dev/null || true
    )"
fi

if [ -z "$CHROME_USE" ]; then
    echo "ERROR: chrome-use not found."
    exit 1
fi

DEADLINE=$(( SECONDS + WAIT_SECONDS ))
LAUNCH_ATTEMPTED=0

echo "Checking ShopAI Chrome..."

while [ "$SECONDS" -lt "$DEADLINE" ]
do
    REMAINING=$(( DEADLINE - SECONDS ))
    PROBE_TIMEOUT=5

    if [ "$REMAINING" -lt "$PROBE_TIMEOUT" ]; then
        PROBE_TIMEOUT="$REMAINING"
    fi

    TABS="$(
        timeout "$PROBE_TIMEOUT" \
            "$CHROME_USE" \
            --session shopai \
            tabs \
            2>/dev/null ||
        true
    )"

    if [ -n "$TABS" ]; then
        REMAINING=$(( DEADLINE - SECONDS ))

        if [ "$REMAINING" -le 0 ]; then
            break
        fi

        AUTH_TIMEOUT=10

        if [ "$REMAINING" -lt "$AUTH_TIMEOUT" ]; then
            AUTH_TIMEOUT="$REMAINING"
        fi

        AUTH_JSON="$(
            timeout "$AUTH_TIMEOUT" \
                "$CHROME_USE" \
                --session shopai \
                site chatgpt/me --json \
                2>/dev/null
        )" || AUTH_JSON=""

        if printf '%s' "$AUTH_JSON" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    r = d.get("data", {}).get("result", {})
    ok = (
        d.get("success") is True
        and r.get("signed_in") is True
        and r.get("token_available") is True
    )
except Exception:
    ok = False
raise SystemExit(0 if ok else 1)
'
        then
            echo "ShopAI Chrome: ONLINE + AUTHENTICATED"
            exit 0
        fi

        echo "ShopAI Chrome: browser online, ChatGPT authentication not ready."

    elif [ "$LAUNCH_ATTEMPTED" -eq 0 ]; then
        LAUNCH_ATTEMPTED=1

        echo "No live ShopAI Chrome found."
        echo "Removing stale Chrome control session..."

        STALE_CHROME_USE_PIDS="$(
            pgrep -f "^$CHROME_USE$" \
                2>/dev/null ||
            true
        )"

        if [ -n "$STALE_CHROME_USE_PIDS" ]; then
            kill -9 $STALE_CHROME_USE_PIDS \
                2>/dev/null ||
            true

            sleep 2
        fi

        echo "Starting authenticated ShopAI Chrome..."

        REMAINING=$(( DEADLINE - SECONDS ))

        if [ "$REMAINING" -le 0 ]; then
            break
        fi

        LAUNCH_TIMEOUT=30

        if [ "$REMAINING" -lt "$LAUNCH_TIMEOUT" ]; then
            LAUNCH_TIMEOUT="$REMAINING"
        fi

        timeout "$LAUNCH_TIMEOUT" \
            "$CHROME_USE" \
            --session shopai \
            --profile Default \
            --launch \
            open https://chatgpt.com/ \
            >/dev/null 2>&1 ||
        true
    fi

    REMAINING=$(( DEADLINE - SECONDS ))

    if [ "$REMAINING" -gt 0 ]; then
        echo \
            "Waiting for ShopAI Chrome..." \
            "${REMAINING}s remaining"

        if [ "$REMAINING" -gt 2 ]; then
            sleep 2
        else
            sleep "$REMAINING"
        fi
    fi
done

echo \
    "ERROR: ShopAI Chrome was not ready within" \
    "${WAIT_SECONDS} seconds."

exit 1
