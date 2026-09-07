# -*- coding: utf-8 -*-
"""Back-fill nifty:series/* advancement criteria for battle-series wins earned before the
datapack existed.

Needed because rctmod:defeat_count criteria pinned to `trainer_ids` only evaluate at the
moment that exact trainer is defeated -- see gen-series-rewards.py. Without this, a player who
had already beaten three Sinnoh leaders would have to beat four MORE to hit the first
milestone.

Ground truth is world/data/rctmod.trainers.*.mem.dat (data.defeats[trainerId][uuid] = count),
the same store DefeatCountTriggerInstance reads.

`/advancement grant` only works on ONLINE players ("No player was found" otherwise), so this
runs on cron and catches each player the next time they log in. A player is marked done in
the state file once their grants succeed, and is never touched again.

SAFETY: refuses to grant a set of criteria that would COMPLETE an advancement, because
completing one pays out a booster pack. Anything that would complete is logged and skipped,
so a payout is always a deliberate, separate decision.

Usage:  python3 catchup-series-rewards.py [--apply] [--status]
"""
import glob, json, os, subprocess, sys, time

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")

BASE = COBBLEMON_DIR
STATE = os.path.join(BASE, "series-catchup-state.json")
LOG = os.path.join(BASE, "logs", "series-catchup.log")
sys.path.insert(0, "/tmp")
sys.path.insert(0, BASE)
from nbt2 import load

APPLY = "--apply" in sys.argv
STATUS = "--status" in sys.argv

SERIES = {
    "radicalred": ["leader_brock_019e", "leader_misty_019f", "leader_lt_surge_01a0",
                   "leader_erika_01a1", "leader_koga_01a2", "leader_sabrina_01a4",
                   "leader_blaine_01a3", "leader_clair_004a"],
    "bdsp":       ["gym_leader_roark_0395", "gym_leader_gardenia_03d6", "gym_leader_maylene_03d8",
                   "gym_leader_wake_03d7", "gym_leader_fantina_03d9", "gym_leader_byron_0399",
                   "gym_leader_candice_03da", "gym_leader_volkner_03db"],
    "unbound":    ["leader_mirskle_05aa", "leader_vega_05ab", "leader_alice_05ac",
                   "leader_mel_05ad", "leader_galavan_05af", "leader_big_mo_05b0",
                   "leader_tessy_05b1", "leader_benjamin_05b2"],
}
CHAMPS = {
    "radicalred": ["champion_terry_01b6", "champion_terry_01b7", "champion_terry_01b8"],
    "bdsp":       ["champion_cynthia_03a5"],
    "unbound":    ["champion_jax_05b7"],
}
COMPLETES_AT = {"_4": 4, "_8": 8}   # never grant this many criteria


def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def rcon(cmd):
    return subprocess.run(["python3", os.path.join(BASE, "rcon.py"), cmd],
                          capture_output=True, text=True).stdout.strip()


def read_defeats():
    out = {}
    for p in glob.glob(os.path.join(BASE, "world/data/rctmod.trainers.*.mem.dat")):
        if p.endswith("ver.dat"):
            continue
        try:
            data = (load(p).get("data") or {}).get("defeats", {})
        except Exception as e:
            log("WARN could not read %s: %s" % (os.path.basename(p), e))
            continue
        for tid, players in data.items():
            for uid, c in players.items():
                if c > 0:
                    out.setdefault(uid, set()).add(tid)
    return out


def plan_for(beaten):
    """-> (list of (advancement, criterion), list of warnings)"""
    grants, warns = [], []
    for sid, leaders in SERIES.items():
        idx = [i for i, t in enumerate(leaders) if t in beaten]
        for suffix, complete_at in COMPLETES_AT.items():
            adv = "nifty:series/%s%s" % (sid, suffix)
            if len(idx) >= complete_at:
                warns.append("SKIP %s: %d criteria would COMPLETE it and pay out a pack"
                             % (adv, len(idx)))
                continue
            grants += [(adv, "leader_%d" % i) for i in idx]
        if any(t in beaten for t in CHAMPS[sid]):
            warns.append("SKIP nifty:series/%s_champ: champion already beaten; single criterion, "
                         "granting it would pay out" % sid)
    return grants, warns


def main():
    state = {}
    if os.path.exists(STATE):
        state = json.load(open(STATE, encoding="utf-8"))
    names = {e["uuid"]: e["name"]
             for e in json.load(open(os.path.join(BASE, "usercache.json"), encoding="utf-8"))}
    defeats = read_defeats()

    if STATUS:
        for uid, beaten in defeats.items():
            g, w = plan_for(beaten)
            print("%-16s %-9s %d criteria to back-fill%s"
                  % (names.get(uid, uid[:8]),
                     "DONE" if state.get(uid) else "pending", len(g),
                     "  [%d warning(s)]" % len(w) if w else ""))
        return

    todo = {u: b for u, b in defeats.items() if not state.get(u)}
    if not todo:
        return                                   # everyone caught up; cheapest possible exit

    online = rcon("list")
    online_names = set()
    if ":" in online:
        online_names = {n.strip() for n in online.split(":", 1)[1].split(",") if n.strip()}
    if not online_names:
        return

    for uid, beaten in todo.items():
        who = names.get(uid)
        if who not in online_names:
            continue
        grants, warns = plan_for(beaten)
        for wmsg in warns:
            log("%s: %s" % (who, wmsg))
        ok = True
        for adv, crit in grants:
            res = rcon("advancement grant %s only %s %s" % (who, adv, crit))
            if "Granted" not in res and "as they already have it" not in res:
                log("%s: FAILED %s %s -> %s" % (who, adv, crit, res))
                ok = False
        if ok:
            state[uid] = {"name": who, "granted": len(grants), "at": time.strftime("%Y-%m-%d %H:%M:%S")}
            with open(STATE, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            log("%s: back-filled %d criteria, marked done" % (who, len(grants)))


if APPLY or STATUS:
    main()
else:
    print("Refusing to run without --apply (or --status). This issues live grants.")
