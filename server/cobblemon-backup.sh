#!/bin/bash
: "${COBBLEMON_DIR:=/srv/cobblemon}"
set -e
TIMESTAMP=$(date +%Y%m%d)
BACKUP_DIR=$BACKUP_DIR
CB=$COBBLEMON_DIR
RETAIN_DAYS=3          # lowered from 7: world grows to ~43GB at radius 15000
MIN_FREE_GB=50         # refuse to back up if this little space remains
mkdir -p "$BACKUP_DIR"

FREE=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
if [ "$FREE" -lt "$MIN_FREE_GB" ]; then
  echo "[$(date)] ABORT: only ${FREE}GB free (< ${MIN_FREE_GB}GB floor). Backup skipped."
  exit 1
fi

RUNNING=0
if systemctl is-active --quiet cobblemon; then
  RUNNING=1
  # 2026-08-15: save-on MUST run no matter how this script exits.
  # Before this trap existed, `set -e` plus a non-zero tar exit ("file changed as
  # we read it", which is NORMAL on a live world) aborted the script right after
  # tar and never re-enabled saving. Auto-save stayed off for 34 hours and the
  # world silently stopped persisting terrain. The trap is the real fix; the
  # tar-tolerance below just stops the abort happening in the first place.
  trap '[ "$RUNNING" = "1" ] && "$CB/rcon.py" save-on >/dev/null 2>&1 || true' EXIT
  "$CB/rcon.py" save-off       >/dev/null 2>&1 || RUNNING=0
  "$CB/rcon.py" save-all flush >/dev/null 2>&1 || true
  sleep 5
fi

# tar exit 1 == warnings only (files changed while being read); that is expected
# against a live world and is NOT a failure. Only exit >= 2 is a real error.
set +e
nice -n 19 ionice -c3 tar --warning=no-file-changed -czf "$BACKUP_DIR/cobblemon-$TIMESTAMP.tar.gz" \
  -C "$CB" $(cd "$CB" && ls -d world* config server.properties whitelist.json ops.json 2>/dev/null)
TAR_RC=$?
set -e

# Re-enable saving immediately rather than waiting for the EXIT trap, so the
# world is only unsaved for the duration of tar itself.
[ "$RUNNING" = "1" ] && "$CB/rcon.py" save-on >/dev/null 2>&1 || true

if [ "$TAR_RC" -ge 2 ]; then
  echo "[$(date)] ERROR: tar exited $TAR_RC - archive may be incomplete, keeping it for inspection."
  exit 1
fi

find "$BACKUP_DIR" -name "cobblemon-*.tar.gz" -mtime +$RETAIN_DAYS -delete

echo "[$(date)] Cobblemon backup complete (tar rc=$TAR_RC): $BACKUP_DIR/cobblemon-$TIMESTAMP.tar.gz ($(du -h "$BACKUP_DIR/cobblemon-$TIMESTAMP.tar.gz" | cut -f1)) | free: $(df -BG --output=avail / | tail -1)"
