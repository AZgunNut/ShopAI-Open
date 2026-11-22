#!/usr/bin/env bash
set -Eeuo pipefail
export PYTHONUNBUFFERED=1
URL='http://127.0.0.1:19097'
while true;do
  if python3 - "$URL" <<'PY'
import json,sys,urllib.request
try:
  with urllib.request.urlopen(sys.argv[1]+'/v1/models',timeout=4) as r: obj=json.load(r)
  a=[str(m.get('id','')) for m in obj.get('data',[])]
  assert len(a)==1 and 'qwen3-coder-30b-a3b' in a[0].lower()
except Exception:raise SystemExit(1)
PY
  then break;fi
  if [[ '1' == 1 ]];then
    OWNER_PID="$(cat '/mnt/shopai-data-new/cad-research/experiments/qwen-3-drawing-20261030-173652-610108/shopai_three_drawing_truth/batch_lab/services/qwen3coder/owned_pid')"
    if ! kill -0 "$OWNER_PID" 2>/dev/null;then
      echo 'STOP: owned model service exited';tail -45 '/mnt/shopai-data-new/cad-research/experiments/qwen-3-drawing-20261030-173652-610108/shopai_three_drawing_truth/batch_lab/services/qwen3coder/server.log';exit 5
    fi
  fi
  if [[ -f '/mnt/shopai-data-new/cad-research/experiments/qwen-3-drawing-20261030-173652-610108/shopai_three_drawing_truth/batch_lab/TERMINATE' ]];then echo 'TERMINATE while waiting for model';exit 6;fi
  sleep 5
done
cd '/mnt/shopai-data-new/cad-research/experiments/qwen-3-drawing-20261030-173652-610108/shopai_three_drawing_truth'
exec python3 -u tools/qwen_scored_loop.py --server-url "$URL" --batch '200'
