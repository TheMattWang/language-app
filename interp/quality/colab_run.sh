#!/bin/sh
# One model per Colab session; partial results are pulled down on every poll
# so a session dying at the ceiling loses at most one stage.
#   interp/quality/colab_run.sh Qwen/Qwen3-4B-Instruct-2507 [T4]
set -u
MODEL="$1"; GPU="${2:-T4}"
SESSION="q-$(echo "$MODEL" | tr '/.' '--' | tr 'A-Z' 'a-z' | cut -c1-30)"
HERE="$(cd "$(dirname "$0")" && pwd)"; OUT="$HERE/colab_out"; mkdir -p "$OUT"
FILE="$(echo "$MODEL" | sed 's|/|__|').json"
q() { grep -v "new version\|update\|silence"; }

colab new -s "$SESSION" --gpu "$GPU" 2>&1 | q
colab upload -s "$SESSION" "$HERE/colab_quality.py" /content/colab_quality.py 2>&1 | q
printf 'import subprocess\nsubprocess.Popen("nohup python /content/colab_quality.py %s > /content/run.out 2>&1 &", shell=True)\n' "$MODEL" \
  | colab exec -s "$SESSION" 2>&1 | q

for i in $(seq 1 60); do
  sleep 120
  colab download -s "$SESSION" "/content/out/$FILE" "$OUT/$FILE" >/dev/null 2>&1
  colab download -s "$SESSION" /content/out/log.txt "$OUT/${FILE%.json}.log" >/dev/null 2>&1
  tail -2 "$OUT/${FILE%.json}.log" 2>/dev/null
  if grep -qE "DONE|FAILED|NaN act" "$OUT/${FILE%.json}.log" 2>/dev/null; then break; fi
  if ! colab status -s "$SESSION" >/dev/null 2>&1; then echo "SESSION LOST"; exit 1; fi
done
colab stop -s "$SESSION" 2>&1 | q
