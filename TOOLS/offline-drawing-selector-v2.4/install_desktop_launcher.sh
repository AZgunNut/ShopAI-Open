#!/usr/bin/env bash
# User-scoped desktop launcher for ShopAI offline drawing selector v2.4.
# Run from the directory containing this file and assets/.
set -Eeuo pipefail
SRC="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$HOME/ShopAI-ROI-Tool"
APP="$ROOT/app/roi_native_v2_4.py"
LAUNCH="$ROOT/START_NATIVE_V2_4.sh"
ICON="$ROOT/assets/shopai-roi-selector.svg"
MENU="${XDG_DATA_HOME:-$HOME/.local/share}/applications/shopai-roi-selector.desktop"
if [[ ! -r "$APP" || ! -x "$LAUNCH" ]]; then
  echo "ERROR: v2.4 application is not installed. No changes made." >&2
  exit 1
fi
mkdir -p "$ROOT/assets" "$(dirname -- "$MENU")" "$ROOT/03_LOGS"
if [[ ! -f "$SRC/assets/shopai-roi-selector.svg" ]]; then
  echo "ERROR: Source icon missing. No changes made." >&2
  exit 1
fi
cp -n "$SRC/assets/shopai-roi-selector.svg" "$ICON"
if ! cmp -s "$SRC/assets/shopai-roi-selector.svg" "$ICON"; then
  cp -p "$ICON" "$ROOT/03_LOGS/shopai-roi-selector.svg.backup.$(date -u +%Y%m%dT%H%M%SZ).$$"
  cp "$SRC/assets/shopai-roi-selector.svg" "$ICON"
fi
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
cat > "$TMP" <<DESKTOP
[Desktop Entry]
Type=Application
Version=1.0
Name=ShopAI Drawing Selector
Comment=Offline engineering drawing ROI selection
Exec=/usr/bin/env bash "$LAUNCH"
Icon=$ICON
Terminal=true
Categories=Graphics;Utility;
StartupNotify=true
DESKTOP
if [[ -f "$MENU" ]] && ! cmp -s "$TMP" "$MENU"; then
  cp -p "$MENU" "$ROOT/03_LOGS/shopai-roi-selector.desktop.backup.$(date -u +%Y%m%dT%H%M%SZ).$$"
fi
install -m 755 "$TMP" "$MENU"
DESKTOP_DIR=""
if command -v xdg-user-dir >/dev/null 2>&1; then DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || true)"; fi
if [[ -z "$DESKTOP_DIR" && -d "$HOME/Desktop" ]]; then DESKTOP_DIR="$HOME/Desktop"; fi
if [[ -n "$DESKTOP_DIR" && "$DESKTOP_DIR" != "$HOME" && -d "$DESKTOP_DIR" ]]; then
  TARGET="$DESKTOP_DIR/ShopAI Drawing Selector.desktop"
  if [[ -f "$TARGET" ]] && ! cmp -s "$MENU" "$TARGET"; then
    cp -p "$TARGET" "$ROOT/03_LOGS/ShopAI-Drawing-Selector.desktop.backup.$(date -u +%Y%m%dT%H%M%SZ).$$"
  fi
  cp "$MENU" "$TARGET"; chmod +x "$TARGET"
  if command -v gio >/dev/null 2>&1; then gio set "$TARGET" metadata::trusted true >/dev/null 2>&1 || true; fi
fi
echo "Installed ShopAI Drawing Selector desktop icon: $MENU"
echo "No ShopAI services, original images or READY outputs changed."
