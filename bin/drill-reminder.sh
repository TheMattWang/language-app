#!/bin/bash
# Daily nudge for the Spanish drill.
#
#   bin/drill-reminder.sh                 # notify only if something is due
#   bin/drill-reminder.sh --always        # notify even when nothing is due
#   bin/drill-reminder.sh --imessage +15551234567
#
# Designed to be run by launchd once a day. It never opens the app or starts a
# session by itself -- a reminder you did not ask for that also seizes your
# screen is a reminder you will uninstall. See RUNBOOK below for install.
set -u

cd "$(dirname "$0")/.." || exit 0

PY="$(command -v python3)"
[ -x "$PY" ] || exit 0

ALWAYS=0
IMESSAGE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --always) ALWAYS=1 ;;
    --imessage) shift; IMESSAGE="${1:-}" ;;
    *) ;;
  esac
  shift
done

# Ask the tool what today looks like. Any failure here is silent by design:
# a broken reminder must never produce a scary dialog at 09:00.
PLAN="$("$PY" - <<'PYEOF' 2>/dev/null
from datetime import datetime, timezone
try:
    from drill import store
    conn = store.connect()
    q = store.daily_queue(conn, datetime.now(timezone.utc))
    reviews = len(q.items) - q.new_introduced
    print(f"{len(q.items)}|{reviews}|{q.new_introduced}|{q.backlog}")
    conn.close()
except Exception:
    pass
PYEOF
)"

[ -n "$PLAN" ] || exit 0

TOTAL="${PLAN%%|*}"
REST="${PLAN#*|}"
REVIEWS="${REST%%|*}"
REST="${REST#*|}"
NEW="${REST%%|*}"

if [ "$TOTAL" -eq 0 ] && [ "$ALWAYS" -eq 0 ]; then
  exit 0
fi

DAYS_LEFT=$(( ( $(date -j -f "%Y-%m-%d" "2026-10-03" "+%s" 2>/dev/null || echo 0) - $(date "+%s") ) / 86400 ))

if [ "$TOTAL" -eq 0 ]; then
  BODY="Nada pendiente hoy. ${DAYS_LEFT} días para España."
else
  BODY="${TOTAL} tarjetas: ${REVIEWS} repaso + ${NEW} nuevas. ${DAYS_LEFT} días para España."
fi

# Escape double quotes for AppleScript.
SAFE_BODY="${BODY//\"/\\\"}"

/usr/bin/osascript -e "display notification \"${SAFE_BODY}\" with title \"Drill — español\"" 2>/dev/null

if [ -n "$IMESSAGE" ]; then
  /usr/bin/osascript <<OSAEOF 2>/dev/null
tell application "Messages"
  set targetService to 1st service whose service type = iMessage
  set targetBuddy to buddy "${IMESSAGE}" of targetService
  send "${SAFE_BODY}" to targetBuddy
end tell
OSAEOF
fi

exit 0
