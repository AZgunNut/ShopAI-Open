#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$HOME/ShopAI-ROI-Tool"
FILE="$ROOT/app/roi_native_v2_4.py"
LOGDIR="$ROOT/03_LOGS"
mkdir -p "$LOGDIR"
if [[ ! -r "$FILE" ]]; then echo "ERROR: Missing $FILE" >&2; exit 1; fi
# Close ONLY this user's verified ShopAI ROI selector Python processes,
# never unrelated Python, AI/model services or other applications.
/usr/bin/python3 - <<'PY_KILL'
import os, pathlib, signal, time
prefix=str(pathlib.Path.home()/'ShopAI-ROI-Tool'/'app')+'/'
possible={'roi_native_v2.py','roi_native_v2_1.py','roi_native_v2_2.py','roi_native_v2_3.py','roi_native_v2_4.py'}
owned=[]
for d in pathlib.Path('/proc').iterdir():
    if not d.name.isdigit() or int(d.name)==os.getpid():
        continue
    try:
        if d.stat().st_uid!=os.getuid():
            continue
        parts=(d/'cmdline').read_bytes().split(b'\0')
        items=[os.fsdecode(x) for x in parts if x]
        if not items or 'python' not in pathlib.Path(items[0]).name.lower():
            continue
        if not any(x==prefix+name for x in items[1:] for name in possible):
            continue
        owned.append(int(d.name))
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        continue
for pid in owned:
    print('Stopping prior ShopAI ROI selector PID:',pid,flush=True)
    try: os.kill(pid,signal.SIGTERM)
    except ProcessLookupError: pass
end=time.monotonic()+3
while time.monotonic()<end:
    live=[]
    for pid in owned:
        try:
            content=(pathlib.Path('/proc')/str(pid)/'stat').read_text()
            if content.split(') ',1)[1][:1]!='Z': live.append(pid)
        except FileNotFoundError: pass
    if not live: break
    time.sleep(.1)
else:
    raise SystemExit('Older selector did not stop; close it manually; no forced kill sent.')
PY_KILL
/usr/bin/python3 - <<'PY_GTK'
try:
    import gi
    gi.require_version('Gtk','3.0')
    gi.require_version('GdkPixbuf','2.0')
    from gi.repository import Gtk, GdkPixbuf
    print('GTK_RUNTIME_OK',Gtk.MAJOR_VERSION,Gtk.MINOR_VERSION)
except Exception as e:
    raise SystemExit('ERROR: GTK unavailable in system Python: '+str(e)+'; no package installation attempted.')
PY_GTK
LOG="$LOGDIR/roi_native_v2_4_$(date -u +%Y%m%dT%H%M%SZ).log"
echo "Launching ShopAI ROI v2.4 — logs $LOG"
echo 'Window title: ShopAI — Offline Drawing ROI Selector v2.4'
echo 'Double-click a file on left; picture displays on right; drag a green box; Save.'
cd "$ROOT"
/usr/bin/python3 -u "$FILE" 2>&1 | tee -a "$LOG"
