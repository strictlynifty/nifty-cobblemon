#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Let players toggle their own Gigantamax display, with no client download.

Mega Showdown gates the G-max form behind a battle AND a Power Spot, so a form the player
earned with a Max Soup is only ever visible for a few turns. gmaxdisplay.py can show it
anywhere, but only an admin can run it - which makes the feature useless day to day.

This closes that gap with a vanilla `trigger` objective. `/trigger` is the one scoreboard
command an unprivileged player may run, so it needs no permissions, no mod and no resource
pack: nothing reaches the client at all.

    /trigger gmax set 3      toggle party slot 3

Why a daemon and not a datapack function: the gate is `GmaxFactor`, which lives in the party
store NBT rather than on an entity, and no mcfunction can read it. Doing the work here also
keeps the eligibility rules in exactly one place - gmaxdisplay.py - instead of restating them
in a form that cannot enforce them.

Run from cron every minute, matching stackguard:
    * * * * * cd $COBBLEMON_DIR && /usr/bin/python3 gmaxwatch.py --loop >/dev/null 2>&1

The poll is deliberately cheap: reading a scoreboard is one small rcon call, and the
expensive part (save-all plus an NBT read) only happens when someone has actually asked for
something.
"""
import subprocess, sys, os, time, re

BASE = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")
sys.path.insert(0, BASE)
import gmaxdisplay as G                      # single source of truth for the rules

OBJ = "gmax"
INTERVAL = 3.0
LOOP_FOR = 55.0                              # cron relaunches us every minute
REENABLE_EVERY = 0.0                         # re-arm on EVERY poll. A trigger disarms itself
                                             # on use and a player who just joined has never
                                             # had it armed, so at 20s several uses in a row
                                             # hit "you cannot trigger this yet". One rcon
                                             # call per online player per poll is cheap for a
                                             # 5-slot server.
LOG = os.path.join(BASE, "logs", "gmaxwatch.log")
LOCK = os.path.join(BASE, "gmaxwatch.lock")


def rcon(cmd):
    try:
        return subprocess.run(["python3", "rcon.py", cmd], cwd=BASE,
                              capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return ""


def log(msg):
    line = "%s %s" % (time.strftime("%F %T"), msg)
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def online():
    out = rcon("list")
    if ":" not in out:
        return []
    return [p.strip() for p in out.split(":", 1)[1].split(",") if p.strip()]


def score(player):
    m = re.search(r"has (-?\d+)", rcon("scoreboard players get %s %s" % (player, OBJ)))
    return int(m.group(1)) if m else 0


def tell(player, text, color="yellow"):
    rcon('tellraw %s {"text":"%s","color":"%s"}' % (player, text.replace('"', "'"), color))


def clear(player):
    rcon("scoreboard players set %s %s 0" % (player, OBJ))
    rcon("scoreboard players enable %s %s" % (player, OBJ))


def gmax_shown(mon):
    """Is this Pokemon actually displaying its Gigantamax form?

    Read the dynamax_form FEATURE, not FormId. FormId can say "normal" while the model is
    still gmax - checking it is what made every earlier revert report a false success.
    """
    for f in (mon.get("Features") or []):
        if str(f.get("cobblemon:feature_id")) == "dynamax_form":
            return str(f.get("dynamax_form")) == "gmax"
    return False


def toggle(player, slot):
    """Apply or revert one party slot, enforcing exactly gmaxdisplay's rules."""
    uuid = next((u for u, n in G.names().items() if n == player), None)
    if not uuid:
        # Silent here would be indistinguishable from "worked": the tellraw goes nowhere if
        # the name is not a real player, so the log is the only trace.
        tell(player, "Could not find your save data - tell an admin.", "red")
        log("NO SAVE DATA for %r (slot %d)" % (player, slot))
        return

    mon = G.party(uuid).get(slot - 1)          # G.party forces a save first
    if not mon:
        tell(player, "Nothing in party slot %d." % slot, "red")
        return
    name = G.bare(mon).title()

    if gmax_shown(mon):
        # `pokeedit form=normal` does NOT do this. The model follows the `gmax` aspect, which
        # comes from the dynamax_form species feature; form=normal changes FormId, a different
        # field, and nothing visible happens. dynamax_form is a choice feature whose default
        # "none" is not among its choices, so pokeedit rejects it while printing "Edited ...".
        # niftygmaxserver makes Mega Showdown's own per-Pokemon revert call instead.
        out = rcon("niftygmax revert %s %d" % (player, slot))
        # Trust the command, not the NBT. Cobblemon's party store persists on its own
        # schedule - a `.dat` read can lag a successful revert by nearly a minute, which made
        # three separate tests look like failures.
        if "Reverted" in out:
            tell(player, "%s is back to its normal form." % name)
            log("REVERT %s slot %d (%s)" % (player, slot, name))
        elif "not showing" in out:
            tell(player, "%s was not showing a Gigantamax form." % name)
            log("REVERT no-op %s slot %d (%s)" % (player, slot, name))
        else:
            tell(player, "Could not change %s back - tell an admin." % name, "red")
            log("REVERT FAILED %s slot %d (%s): %s" % (player, slot, name, out[:120]))
        return

    ok, why = G.eligible(mon)
    if not ok:
        tell(player, why + ".", "red")
        log("REFUSED %s slot %d: %s" % (player, slot, why))
        return

    # Retry the command, not just the read: a dropped rcon call and a form that will not take
    # look identical from one sample.
    after = {}
    for _ in range(2):
        rcon("execute as %s run pokeedit %d form=gmax" % (player, slot))
        for _ in range(3):
            time.sleep(1.5)
            after = G.party(uuid).get(slot - 1) or {}
            if gmax_shown(after):
                break
        if gmax_shown(after):
            break
    if gmax_shown(after):
        tell(player, "%s is showing its Gigantamax form. Recall and resummon it if the "
                      "model has not changed yet." % name, "light_purple")
        log("APPLY %s slot %d (%s)" % (player, slot, name))
    else:
        tell(player, "Could not change %s - tell an admin." % name, "red")
        log("APPLY FAILED %s slot %d (%s)" % (player, slot, name))


def take_lock():
    """One copy at a time. cron relaunches every minute and the loop runs 55s, so an
    overlap at the boundary is normal; a stale lock from a killed run is not."""
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except OSError:
        try:
            os.kill(int(open(LOCK).read().strip() or 0), 0)
            return False                       # another copy is alive and owns it
        except (OSError, ValueError):
            try:
                os.unlink(LOCK)
                fd = os.open(LOCK, os.O_CREAT | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return True
            except OSError:
                return False


def main():
    once = "--once" in sys.argv
    if not once and not take_lock():
        return 0
    try:
        rcon('scoreboard objectives add %s trigger [{"text":"Gmax","color":"light_purple"}]'
             % OBJ)
        end = time.time() + (0 if once else LOOP_FOR)
        last_enable = 0.0
        first = True
        while first or time.time() < end:
            first = False
            try:
                players = online()
                if time.time() - last_enable > REENABLE_EVERY:
                    for p in players:
                        rcon("scoreboard players enable %s %s" % (p, OBJ))
                    last_enable = time.time()
                for p in players:
                    v = score(p)
                    if v == 0:
                        continue
                    clear(p)                   # clear FIRST so a slow toggle cannot re-fire
                    if 1 <= v <= 6:
                        toggle(p, v)
                    else:
                        tell(p, "Use a party slot from 1 to 6, e.g. /trigger gmax set 3.",
                             "red")
            except Exception as e:
                log("loop error: %r" % e)
            if once:
                break
            time.sleep(INTERVAL)
    finally:
        if not once:
            try:
                os.unlink(LOCK)
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
