#!/usr/bin/env bash
: "${COBBLEMON_DIR:=/srv/cobblemon}"
# Wait until the server is empty, then restart it. NEVER kicks anyone.
#
#   restart-when-empty.sh "<reason>" [max_wait_hours]
#
# Config that is only parsed at startup - datapacks, mod jars, server.properties -
# needs a restart to apply, and a restart mid-session is rude. This polls RCON and
# acts on the first quiet moment, then verifies the server actually came back.
cd $COBBLEMON_DIR || exit 1

REASON="${1:-pending changes}"
MAX_WAIT=$(( ${2:-24} * 3600 ))
SLUG=$(printf '%s' "$REASON" | tr -c '[:alnum:]' '-' | tr -s '-' | sed 's/^-//;s/-$//' | cut -c1-40)
LOG="$COBBLEMON_DIR/logs/restart-${SLUG:-pending}.log"
EMPTY_NEEDED=3             # ~3 consecutive minutes empty, so a relog does not trigger it
INTERVAL=60

say(){ printf '%s %s\n' "$(date '+%F %T')" "$1" >>"$LOG"; }
players(){ python3 rcon.py "list" 2>/dev/null | grep -oP 'There are \K[0-9]+'; }

say "watcher started (pid $$); waiting for an empty server to apply: $REASON"
say "will give up after $(( MAX_WAIT / 3600 ))h"
start=$(date +%s); empty=0
while :; do
  now=$(date +%s)
  if (( now - start > MAX_WAIT )); then
    say "GAVE UP after $(( MAX_WAIT / 3600 ))h - server never emptied. Changes are staged; restart manually to apply."
    exit 0
  fi
  n=$(players)
  if [[ -z "$n" ]]; then
    say "rcon unreachable (server down?) - will re-check"
    sleep "$INTERVAL"; continue
  fi
  if (( n == 0 )); then
    empty=$(( empty + 1 ))
    say "empty ($empty/$EMPTY_NEEDED)"
  else
    (( empty > 0 )) && say "player rejoined - resetting counter"
    empty=0
  fi

  if (( empty >= EMPTY_NEEDED )); then
    say "server empty - flushing world before restart"
    python3 rcon.py "save-all flush" >/dev/null 2>&1
    sleep 5
    say "restarting cobblemon.service"
    if sudo -n /usr/bin/systemctl restart cobblemon; then
      sleep 45
      for i in $(seq 1 20); do
        if python3 rcon.py "list" >/dev/null 2>&1; then
          say "server back up - applied: $REASON"
          exit 0
        fi
        sleep 15
      done
      say "WARNING: restarted but rcon did not answer in time - check manually"
      exit 1
    else
      say "ERROR: systemctl restart failed"
      exit 1
    fi
  fi
  sleep "$INTERVAL"
done
