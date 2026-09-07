#!/usr/bin/env bash
# Install niftycards and restart, rolling back automatically if the server does not come up.
#
# The mixin config is "required": true, so a failed injection stops the server booting rather
# than silently running without the fix. Correct failure mode, wrong one to leave unattended.
set -u
CB="${COBBLEMON_DIR:-/srv/cobblemon}"
JAR="$CB/mods/niftycards-1.0.0.jar"

# Ask the server whether it is up; do not read the log for it. logs/latest.log IS rotated on
# restart, so counting a marker across the restart compares two different files, and grepping
# it before the rotation finds the PREVIOUS boot. Both mistakes were made here. RCON answering
# is unambiguous.
boot_ok() {
    for _ in $(seq 1 60); do
        if python3 "$CB/rcon.py" list >/dev/null 2>&1; then
            grep -qiE 'Mixin apply failed|InjectionError' "$CB/logs/latest.log" && return 1
            return 0
        fi
        sleep 3
    done
    return 1
}

stop_server() {
    sudo systemctl stop cobblemon
    for _ in $(seq 1 30); do
        systemctl is-active --quiet cobblemon || return 0
        sleep 2
    done
}

cd "$CB" || exit 1
python3 rcon.py "say [Server] Quick restart to add a fix - back in under a minute." >/dev/null 2>&1
sleep 4
stop_server

cp /tmp/niftycards-1.0.0.jar "$JAR"
chown deploy:deploy "$JAR"
echo "installed: $(stat -c%s "$JAR") bytes"

sudo systemctl start cobblemon
if boot_ok; then
    echo "BOOT OK"
    grep -E 'Done \(' logs/latest.log | tail -1
    echo "mixin errors: $(grep -ciE 'Mixin apply failed|InjectionError' logs/latest.log)"
    grep -c niftycards logs/latest.log | sed 's/^/niftycards log mentions: /'
else
    echo "BOOT FAILED - rolling back"
    grep -iE 'mixin apply failed|injectionerror|caused by' logs/latest.log | tail -10
    stop_server
    rm -f "$JAR"
    sudo systemctl start cobblemon
    boot_ok && echo "ROLLED BACK - server is up without niftycards" \
             || echo "ROLLED BACK BUT SERVER DID NOT COME UP - needs a human"
fi
