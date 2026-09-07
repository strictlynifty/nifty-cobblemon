#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Clamp dropped item stacks that are too big for the world save to survive.

Minecraft's ItemStack save codec rejects any count outside [1;99]. On 2026-08-29 a dropped
stack of 108 Lapis Lazuli crashed the server TWICE - ServerLevel.save threw, the server
shut down, the watchdog force-killed it. Both stacks were 108, both in the owner's Titan
Hammer tunnel, both above lapis's own 64 max stack, so the hammer is merging the drops from
its multi-block break past the legal limit. Legendary Monuments ships no config for it.

Detection must happen IN MEMORY: the oversized stack is precisely the thing that cannot be
written, so it never reaches the region files.

A 2-minute cron LOST THE RACE once, which is why this polls rather than running per-minute.
cron starts it once a minute; it loops for just under a minute and exits, so cron also acts
as the restart-if-it-died watchdog and two copies never overlap for long.

Selectors cannot compare NBT numerically but CAN compare scores, hence the scoreboard.

2026-09-01, two changes after this turned out to be writing ~49,000 of the ~50,000 lines in
latest.log:

  * It used to shell out to `python3 rcon.py` PER COMMAND, so every command paid a Python
    interpreter start AND a fresh TCP connection - and vanilla logs two lines for every
    RCON connect/disconnect. That was ~36 processes and ~72 log lines a minute, forever.
    One socket is now held open for the whole loop: 2 log lines per cron run instead.
  * INTERVAL 3s -> 15s. The players now know to pick lapis up while Titan-hammering with
    Fortune, so this is a backstop rather than the primary defence. 15s still leaves a wide
    margin against an autosave (5 min) and is 5x less work.

Usage:
    stackguard.py --loop        poll for ~55s, clamping anything oversized  (cron)
    stackguard.py               one pass, report only
    stackguard.py --fix         one pass, clamp
"""
import socket, struct, subprocess, sys, os, time

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")

BASE = COBBLEMON_DIR
OBJ = "stackguard"
LOG = os.path.join(BASE, "logs", "stackguard.log")
THRESHOLD = 65          # report/clamp at or above this; the fatal limit is 100
CLAMP_TO = 64           # legal for every vanilla stack
INTERVAL = 15.0         # seconds between passes in --loop mode
LOOP_FOR = 55.0         # exit before the next cron tick

HOST, PORT = "127.0.0.1", 25575

LOOP = "--loop" in sys.argv
FIX = LOOP or "--fix" in sys.argv


class Rcon(object):
    """One connection, held open for the whole run.

    Deliberately the same wire format as rcon.py - single request, single response packet.
    Every command this script sends returns a small body, so the multi-packet case that
    matters for big queries does not arise here. See COBBLEMON-GOTCHAS.md 82: a response
    near 4096 bytes is truncated, not short, so keep asking for numbers and small structs.
    """

    def __init__(self):
        self.s = None

    def connect(self):
        pw = open(os.path.join(BASE, ".rconpw")).read().strip()
        s = socket.create_connection((HOST, PORT), timeout=15)
        s.sendall(self._pkt(1, 3, pw))
        rid, _, _ = self._recv(s)
        if rid == -1:
            s.close()
            raise RuntimeError("RCON auth failed")
        self.s = s

    @staticmethod
    def _pkt(rid, typ, body):
        data = struct.pack("<ii", rid, typ) + body.encode("utf8") + b"\x00\x00"
        return struct.pack("<i", len(data)) + data

    @staticmethod
    def _recv(s):
        head = b""
        while len(head) < 4:
            c = s.recv(4 - len(head))
            if not c:
                raise IOError("rcon closed")
            head += c
        ln = struct.unpack("<i", head)[0]
        buf = b""
        while len(buf) < ln:
            c = s.recv(ln - len(buf))
            if not c:
                raise IOError("rcon closed")
            buf += c
        rid, typ = struct.unpack("<ii", buf[:8])
        return rid, typ, buf[8:-2].decode("utf8", "replace")

    def cmd(self, c):
        self.s.sendall(self._pkt(2, 2, c))
        return self._recv(self.s)[2].strip()

    def close(self):
        if self.s:
            try:
                self.s.close()
            except OSError:
                pass
            self.s = None


_RC = Rcon()


def rcon(cmd):
    """Send one command. Falls back to the subprocess path if the socket is unavailable,
    so a change here can never leave the guard silently doing nothing."""
    if _RC.s is not None:
        try:
            return _RC.cmd(cmd)
        except (IOError, OSError, struct.error):
            _RC.close()          # server restarting: fall through, cron retries next minute
    try:
        return subprocess.run(["python3", "rcon.py", cmd], cwd=BASE,
                              capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return ""


def log(msg):
    line = "%s %s" % (time.strftime("%F %T"), msg)
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def sweep():
    """One pass. Returns how many oversized stacks were seen."""
    rcon("execute as @e[type=item] store result score @s %s run data get entity @s Item.count"
         % OBJ)
    one = "@e[type=item,scores={%s=%d..},limit=1]" % (OBJ, THRESHOLD)
    found = 0
    for _ in range(30):
        item = rcon("data get entity %s Item" % one)
        if "entity data" not in item:
            break
        desc = item.split("data: ", 1)[-1][:80]
        pos = rcon("data get entity %s Pos" % one)
        where = pos.split("data: ", 1)[-1][:56] if "entity data" in pos else "?"
        found += 1
        if FIX:
            rcon("data modify entity %s Item.count set value %d" % (one, CLAMP_TO))
            log("CLAMPED %d: %s at %s" % (CLAMP_TO, desc, where))
        else:
            log("OVERSIZED: %s at %s" % (desc, where))
        # clear the score either way so the next iteration moves on
        rcon("scoreboard players set %s %s 0" % (one, OBJ))
    return found


def main():
    # Two copies running at once interleave their RCON responses - during testing that
    # produced a log line reading "6Tuff has the following entity data: 3Tuff has the
    # following..." and could clamp the wrong entity. cron fires this every minute and the
    # loop runs for 55s, so overlap is expected at the boundary; take a lock and exit.
    lock = os.path.join(BASE, "stackguard.lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        try:
            pid = int(open(lock).read().strip() or 0)
            os.kill(pid, 0)          # still alive -> another copy owns it
            return 0
        except (ValueError, ProcessLookupError, PermissionError, OSError):
            os.unlink(lock)          # stale lock from a killed run
            fd = os.open(lock, os.O_CREAT | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
    try:
        return _run()
    finally:
        _RC.close()
        try:
            os.unlink(lock)
        except OSError:
            pass


def _run():
    try:
        _RC.connect()
    except (IOError, OSError, RuntimeError):
        pass                         # rcon() falls back to the subprocess path
    rcon("scoreboard objectives add %s dummy" % OBJ)
    if not LOOP:
        sweep()
        return 0
    end = time.time() + LOOP_FOR
    total = 0
    while time.time() < end:
        total += sweep()
        time.sleep(INTERVAL)
    if total:
        log("loop finished: %d clamped this minute" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
