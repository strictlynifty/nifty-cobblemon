#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Let players show their Gigantamax form outside battle - but only if they earned it.

Mega Evolution already works outside battle (outSideMega puts a Mega Evolve button on the
interaction wheel). Gigantamax has no such path: the mod gates it behind a battle AND a
Power Spot, so a G-max form can only ever be seen mid-fight at the gym.

The MODEL, though, is driven purely by the `gmax` aspect - the resolvers carry no battle or
Power Spot condition. So the form can be shown anywhere. What must NOT be lost is that it is
earned: this only applies to a Pokemon whose GmaxFactor is 1, i.e. one that has actually
been fed a Max Soup, exactly as a Mega needs its stone held.

MECHANISM, all established by testing on 1.9.5 (see COBBLEMON-GOTCHAS.md):
  apply   pokeedit <slot> form=gmax             works
  revert  pokeedit <slot> form=normal           works, PER POKEMON, GmaxFactor untouched
  revert  msd hard_reset                        also works but resets the player's WHOLE
                                                party+PC and CLEARS GmaxFactor - avoid
  no-op   pokeedit dynamax_form=none / =normal  silently does nothing
  no-op   pokeedit unaspect=gmax / gmax=false   silently does nothing
`pokeedit` prints "Edited <player>'s <mon>." for every input, valid or not, so its output
proves nothing - always read the saved NBT back. Read it MORE THAN ONCE: a single read after
a fixed delay caught a stale file and made a working revert look like a no-op.

Reverting no longer costs the player their megas, so the toggle is genuinely two-way.

Usage:
    gmaxdisplay.py --status            show every player's eligible Pokemon
    gmaxdisplay.py --apply <player> <slot>
    gmaxdisplay.py --reset <player> [slot]   (omit slot = whole party)
"""
import subprocess, sys, os, glob, json, time

BASE = os.environ.get("COBBLEMON_DIR", BASE)
sys.path.insert(0, "/tmp")
sys.path.insert(0, BASE)
LOG = os.path.join(BASE, "logs", "gmaxdisplay.log")

# Species whose gmax form can actually RENDER on Mega Showdown 1.9.5.
#
# Derived from the jars by tools/gmaxassets.py, not from the changelog: a form renders only
# if its resolver names a poser, a geometry AND a texture that all exist. Two traps make a
# naive scan under-report, and both bit the 1.9.3 pass:
#   - assets may live in a DIFFERENT jar (alcremie's poser and model come from base
#     Cobblemon, not from Mega Showdown)
#   - or under a built-in resourcepack path (resourcepacks/regionbiasmsd/assets/...), not
#     the top-level assets/
# Re-run tools/gmaxassets.py after any Mega Showdown update rather than editing this by hand.
# 1.9.5 added 8 to the 24 that 1.9.3 had: appletun centiskorch flapple grimmsnarl hatterene
# inteleon kingler lapras
HAVE_MODEL = set("""alcremie appletun blastoise butterfree centiskorch charizard cinderace
coalossal copperajah corviknight drednaw duraludon eevee flapple garbodor gengar grimmsnarl
hatterene inteleon kingler lapras machamp melmetal meowth orbeetle pikachu rillaboom
sandaconda snorlax toxtricity urshifu venusaur""".split())


def rcon(cmd):
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


def names():
    return {e["uuid"]: e["name"]
            for e in json.load(open(os.path.join(BASE, "usercache.json")))}


def party(uuid, fresh=True):
    """Slot -> mon dict. An ONLINE player's .dat is their LAST SAVE, so force one first."""
    if fresh:
        rcon("save-all")
        time.sleep(3)
    from nbt2 import load
    for p in glob.glob("%s/world/pokemon/playerpartystore/*/%s.dat" % (BASE, uuid)):
        try:
            d = load(p)
        except Exception:
            continue
        return {int(str(k)[4:]): v for k, v in d.items()
                if str(k).startswith("Slot") and isinstance(v, dict) and v.get("Species")}
    return {}


def bare(m):
    return str(m.get("Species", "")).split(":")[-1].lower()


def eligible(m):
    """(ok, why-not). Earned = fed a Max Soup; showable = a model exists."""
    if bare(m) not in HAVE_MODEL:
        return False, "%s has no Gigantamax model in this pack" % bare(m).title()
    if not m.get("GmaxFactor"):
        return False, "%s has never been fed a Max Soup" % bare(m).title()
    return True, ""


def main():
    nm = names()
    args = sys.argv[1:]

    if "--status" in args or not args:
        # An online player's .dat is their last save. Force one, once, before reading any of
        # them - otherwise the report describes a state that may be hours old.
        rcon("save-all flush")
        time.sleep(4)
        for uuid, who in sorted(nm.items(), key=lambda kv: kv[1]):
            pk = party(uuid, fresh=False)
            if not pk:
                continue
            print("  %s" % who)
            for slot in sorted(pk):
                m = pk[slot]
                ok, why = eligible(m)
                mark = "CAN SHOW" if ok else "-"
                print("     slot %d  %-14s lvl %-4s gmaxfactor=%s  %-9s %s"
                      % (slot + 1, bare(m), m.get("Level"), m.get("GmaxFactor"), mark,
                         "" if ok else why))
        return 0

    if "--reset" in args:
        # Per-slot revert. hard_reset is NOT used: it also wipes megas across the whole
        # party and PC, and clears GmaxFactor, which throws away the Max Soup the player
        # actually spent. form=normal leaves the entitlement intact.
        i = args.index("--reset")
        who = args[i + 1]
        uuid = next((u for u, n in nm.items() if n == who), None)
        if not uuid:
            log("unknown player %s" % who)
            return 1
        want = int(args[i + 2]) if len(args) > i + 2 and args[i + 2].isdigit() else None
        pk = party(uuid)
        done = []
        for slot in sorted(pk):
            if want is not None and slot + 1 != want:
                continue
            if str(pk[slot].get("FormId")) != "gmax":
                continue
            rcon("execute as %s run pokeedit %d form=normal" % (who, slot + 1))
            done.append(slot + 1)
        if not done:
            log("%s had nothing in gmax form" % who)
            return 0
        again = party(uuid)
        stuck = [s for s in done if str((again.get(s - 1) or {}).get("FormId")) == "gmax"]
        if stuck:
            log("REVERT INCOMPLETE %s slots %s still gmax" % (who, stuck))
            return 1
        rcon('tellraw %s {"text":"Gigantamax display turned off.","color":"yellow"}' % who)
        log("REVERTED %s slots %s" % (who, done))
        return 0

    if "--apply" in args:
        i = args.index("--apply")
        who, slot = args[i + 1], int(args[i + 2])
        uuid = next((u for u, n in nm.items() if n == who), None)
        if not uuid:
            log("unknown player %s" % who)
            return 1
        pk = party(uuid)
        m = pk.get(slot - 1)
        if not m:
            log("%s has nothing in party slot %d" % (who, slot))
            return 1
        ok, why = eligible(m)
        if not ok:
            rcon('tellraw %s {"text":"Cannot show that form - %s","color":"red"}' % (who, why))
            log("REFUSED %s slot %d: %s" % (who, slot, why))
            return 1
        # pokeedit's output is meaningless - read the NBT back. Two separate things can go
        # wrong, so retry BOTH: the command itself can be dropped (rcon timeout, the player
        # changing dimension mid-edit), and the save is asynchronous so a read can beat the
        # write to disk. Re-issuing the command on each round covers the first; sampling more
        # than once per round covers the second. Reading only once after a fixed delay is how
        # a working revert got recorded as a no-op during testing.
        again = {}
        for attempt in range(3):
            rcon("execute as %s run pokeedit %d form=gmax" % (who, slot))
            for _ in range(3):
                time.sleep(2)
                again = party(uuid).get(slot - 1) or {}
                if str(again.get("FormId")) == "gmax":
                    break
            if str(again.get("FormId")) == "gmax":
                break
            log("apply attempt %d did not take for %s slot %d - retrying"
                % (attempt + 1, who, slot))
        if str(again.get("FormId")) == "gmax":
            rcon('tellraw %s {"text":"Gigantamax form applied to your %s.","color":"light_purple"}'
                 % (who, bare(m).title()))
            log("APPLIED %s slot %d -> %s" % (who, slot, bare(m)))
            return 0
        log("APPLY FAILED %s slot %d (FormId=%s)" % (who, slot, again.get("FormId")))
        return 1

    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
