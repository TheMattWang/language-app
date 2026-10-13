#!/bin/sh
# One model per Colab session; partial results are pulled down on every poll
# so a session dying at the ceiling loses at most one stage.
#   interp/quality/colab_run.sh Qwen/Qwen3-4B-Instruct-2507 [GPU] [SCRIPT]
# SCRIPT defaults to colab_quality.py; any other script may `import colab_quality`.
set -u
MODEL="$1"; GPU="${2:-T4}"; SCRIPT="${3:-colab_quality.py}"
PREFIX=""; [ "$SCRIPT" != colab_quality.py ] && PREFIX="${SCRIPT%.py}__"
SESSION="q-$(echo "$PREFIX$MODEL" | tr '/.' '--' | tr 'A-Z' 'a-z' | cut -c1-30)"
HERE="$(cd "$(dirname "$0")" && pwd)"; OUT="$HERE/colab_out"; mkdir -p "$OUT"
FILE="$PREFIX$(echo "$MODEL" | sed 's|/|__|').json"
q() { grep -v "new version\|update\|silence"; }
# A dead session can leave `colab download` hanging forever; cap each call.
dl() { colab download -s "$SESSION" "$1" "$2" >/dev/null 2>&1 & p=$!
       ( sleep 90; kill $p 2>/dev/null ) 2>/dev/null & w=$!
       wait $p 2>/dev/null; { kill $w; wait $w; } 2>/dev/null; }

if ! colab new -s "$SESSION" --gpu "$GPU" 2>&1 | q | tee /dev/stderr | grep -q "READY"; then
  echo "NO $GPU AVAILABLE (session not created)"; exit 2
fi
colab upload -s "$SESSION" "$HERE/colab_quality.py" /content/colab_quality.py 2>&1 | q
# resume: hand a dead session's partial result to the new one
[ -f "$OUT/$FILE" ] && colab upload -s "$SESSION" "$OUT/$FILE" "/content/out/$FILE" 2>&1 | q
[ "$SCRIPT" != colab_quality.py ] && colab upload -s "$SESSION" "$HERE/$SCRIPT" "/content/$SCRIPT" 2>&1 | q
printf 'import subprocess\nsubprocess.Popen("cd /content && nohup python /content/%s %s > /content/run.out 2>&1 &", shell=True)\n' "$SCRIPT" "$MODEL" \
  | colab exec -s "$SESSION" 2>&1 | q

for i in $(seq 1 60); do
  sleep 120
  dl "/content/out/$FILE" "$OUT/$FILE"
  dl /content/out/log.txt "$OUT/${FILE%.json}.log"
  tail -2 "$OUT/${FILE%.json}.log" 2>/dev/null
  if grep -qE "DONE|FAILED|NaN act" "$OUT/${FILE%.json}.log" 2>/dev/null; then break; fi
  # `colab status` succeeds even for a vanished session; the server list doesn't
  if ! colab sessions 2>/dev/null | grep -q "$SESSION"; then echo "SESSION LOST"; colab sessions 2>&1 | q; exit 1; fi
done
colab stop -s "$SESSION" 2>&1 | q
