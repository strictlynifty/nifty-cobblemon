#!/usr/bin/env bash
: "${COBBLEMON_DIR:=/srv/cobblemon}"
cd $COBBLEMON_DIR
# HEAP: 4G, set 2026-09-01. History: 1536M -> 2G on 2026-08-10 (OutOfMemoryError under
# the expanded 30-jar mod set), then to 5G at some point without this note being updated
# and against the warning it carried. 5G was too much and it showed:
#
#   * java RSS 5.94G of a 7.7G box, because AlwaysPreTouch commits the whole heap up front
#   * only 256M free, and 186M of the JVM itself paged out to swap (/proc/<pid>/status)
#   * TPS a flat 20.0, but tick times min 11 / median 16 / 95%ile 32.7 / max 243.8 ms -
#     stutter rather than sustained lag, which is what paging + GC looks like
#
# Measured with the server STOPPED, as this comment has always asked: the rest of the box
# (the other services) uses ~450M, leaving ~7.0G
# available. Spark put the live set - G1 Old Gen occupancy right after a collection - at
# 2.3G, with 366M non-heap.
#
# So 4G gives the live set ~1.7G of headroom and leaves roughly 2.5G for page cache, which
# a 33G world wants for chunk I/O. That cache pressure is what was buying swap at 5G.
#
# Before changing this again: stop the server, run `free -h`, and check the live set with
# `spark health --memory` (read it out of logs/latest.log - spark does not answer on rcon).
# Do not size the heap from total RAM; size it from the live set plus room for cache.
exec java -Xms4G -Xmx4G \
  -XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200 -XX:+UnlockExperimentalVMOptions \
  -XX:+DisableExplicitGC -XX:+AlwaysPreTouch -XX:G1NewSizePercent=30 -XX:G1MaxNewSizePercent=40 \
  -XX:G1HeapRegionSize=8M -XX:G1ReservePercent=20 -XX:G1HeapWastePercent=5 -XX:G1MixedGCCountTarget=4 \
  -XX:InitiatingHeapOccupancyPercent=15 -XX:G1MixedGCLiveThresholdPercent=90 \
  -XX:G1RSetUpdatingPauseTimePercent=5 -XX:SurvivorRatio=32 -XX:+PerfDisableSharedMem \
  -XX:MaxTenuringThreshold=1 \
  -jar fabric-server-launch.jar nogui
