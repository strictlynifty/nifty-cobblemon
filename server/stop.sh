#!/usr/bin/env bash
: "${COBBLEMON_DIR:=/srv/cobblemon}"
cd $COBBLEMON_DIR
./rcon.py stop >/dev/null 2>&1 || exit 0
for _ in $(seq 1 60); do
  pgrep -u deploy -f fabric-server-launch.jar >/dev/null || exit 0
  sleep 1
done
