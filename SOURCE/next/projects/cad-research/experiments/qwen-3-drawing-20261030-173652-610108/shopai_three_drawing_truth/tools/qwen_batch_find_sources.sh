#!/usr/bin/env bash
# READ ONLY: finds potential best-performing historic Python pipeline files.
# Usage: on VirusLoaderMax, ssh -T shopai@10.42.0.10 'bash -s' < qwen_batch_find_sources.sh
set -Eeuo pipefail
ROOT='/mnt/shopai-data-new/cad-research'
[[ -d "$ROOT" ]] || { echo "Missing $ROOT" >&2; exit 1; }
echo '=== Read-only search for previously successful pipeline ==='
for term in 'legacy_lab.py' 'selector_v2.py' 'autotune_v5.py' 'run_shopai.sh' 'trace_v63.py'; do
    echo "--- $term"
    find "$ROOT" -maxdepth 9 -type f -name "$term" \
      -not -path '*/site-packages/*' -not -path '*/node_modules/*' \
      -not -path '*/experiments/qwen-3-drawing-*/shopai_three_drawing_truth/*' \
      -printf '%T+ %s %p\n' | sort -r | sed -n '1,12p'
done
printf '\n=== Likely working baseline directory ===\n'
for d in "$ROOT/benchmarks/blind-drawing-v1" "$ROOT/python_outline_good/current_v5"; do
 if [[ -d "$d" ]]; then
   find "$d" -maxdepth 2 -type f \( -name '*.py' -o -name '*.sh' -o -name '*README*' \) \
     -printf '%T+ %s %p\n' | sort -r | sed -n '1,40p'
 else
   echo "NOT FOUND: $d"
 fi
done
echo 'Read only: no original or experimental file changed.'
