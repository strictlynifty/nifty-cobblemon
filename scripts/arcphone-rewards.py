#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Grant Cobblemon Cards rewards for Legendary Monuments quest progress.

  - complete every TRACKABLE quest in a generation -> that generation's booster pack
  - complete all 60 trackable quests           -> one God Pack Ticket, ever

"Trackable" excludes the 37 work-in-progress quests, because the mod itself excludes
them: QuestCatalog.trackableCount() and completedCount() both `continue` on
workInProgress. Those are the question-mark entries in the Arc Phone UI. Counting them
would make every generation impossible and the ticket unreachable.

Quest progress is read from the server's own SavedData rather than any command, so this
works whether or not the player is online. Items can only be handed to an ONLINE player,
so a reward earned while offline stays pending and is granted on their next check - the
state file is only written after the /give is confirmed, which is what makes that safe.

Usage:
    arcphone-rewards.py            grant anything owed to online players
    arcphone-rewards.py --status   print everyone's progress, grant nothing
    arcphone-rewards.py --dry-run  say what it would grant, grant nothing
"""
import gzip, io, json, os, re, subprocess, struct, sys, time

BASE = os.environ.get("COBBLEMON_DIR", BASE)
sys.path.insert(0, BASE)
from rewardutil import deliver
CATALOG = os.path.join(BASE, "arcphone-questcat.json")
STATE = os.path.join(BASE, "arcphone-rewards-state.json")
QUESTDAT = os.path.join(BASE, "world/data/legendarymonuments_quest_rewards.dat")
USERCACHE = os.path.join(BASE, "usercache.json")
LOG = os.path.join(BASE, "logs/arcphone-rewards.log")

GEN_PACK = "cobblemon-cards:booster_pack_gen%d"
GOD_TICKET = "cobblemon-cards:god_pack_ticket"

DRY = "--dry-run" in sys.argv
STATUS = "--status" in sys.argv


def log(msg):
    line = "%s %s" % (time.strftime("%F %T"), msg)
    if not STATUS:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    print(line)


def rcon(cmd):
    return subprocess.run(["python3", "rcon.py", cmd], cwd=BASE,
                          capture_output=True, text=True, timeout=30).stdout.strip()


# ---- minimal NBT reader (the .dat is uncompressed or gzipped named-tag NBT) ----
def read_nbt(path):
    raw = open(path, "rb").read()
    try:
        raw = gzip.decompress(raw)
    except Exception:
        pass
    f = io.BytesIO(raw)

    def u1():
        return f.read(1)[0]

    def u2():
        return struct.unpack(">H", f.read(2))[0]

    def i4():
        return struct.unpack(">i", f.read(4))[0]

    def st():
        return f.read(u2()).decode("utf-8", "replace")

    def payload(t):
        if t == 1:
            return struct.unpack(">b", f.read(1))[0]
        if t == 2:
            return struct.unpack(">h", f.read(2))[0]
        if t == 3:
            return i4()
        if t == 4:
            return struct.unpack(">q", f.read(8))[0]
        if t == 5:
            return struct.unpack(">f", f.read(4))[0]
        if t == 6:
            return struct.unpack(">d", f.read(8))[0]
        if t == 7:
            return f.read(i4())
        if t == 8:
            return st()
        if t == 9:
            it = u1()
            return [payload(it) for _ in range(i4())]
        if t == 10:
            d = {}
            while True:
                tt = u1()
                if tt == 0:
                    return d
                k = st()
                d[k] = payload(tt)
        if t == 11:
            return [i4() for _ in range(i4())]
        if t == 12:
            return [struct.unpack(">q", f.read(8))[0] for _ in range(i4())]
        raise ValueError("nbt tag %d" % t)

    t = u1()
    st()
    return payload(t)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def main():
    cat = load_json(CATALOG, None)
    if not cat:
        log("ERROR: no quest catalog at %s" % CATALOG)
        return 1

    # generation -> set of trackable quest ids
    need = {}
    for e in cat:
        if not e["wip"]:
            need.setdefault(e["gen"], set()).add(e["id"])
    total_trackable = sum(len(v) for v in need.values())

    names = {}
    for e in load_json(USERCACHE, []):
        names[e.get("uuid")] = e.get("name")

    try:
        dat = read_nbt(QUESTDAT)
    except Exception as ex:
        log("could not read quest data (%s) - skipping this pass" % ex)
        return 0
    done = (dat.get("data") or {}).get("completedPlayers") or {}

    state = load_json(STATE, {})
    online = set()
    if not STATUS:
        out = rcon("list")
        m = re.search(r"online:\s*(.*)$", out)
        if m and m.group(1).strip():
            online = {x.strip() for x in m.group(1).split(",") if x.strip()}

    changed = False
    for uuid, lst in done.items():
        got = set(lst)
        name = names.get(uuid, uuid[:8])
        st = state.setdefault(uuid, {"name": name, "gens": [], "god": False})
        st["name"] = name
        have_total = sum(1 for q in got if any(e["id"] == q and not e["wip"] for e in cat))

        if STATUS:
            bits = []
            for g in sorted(need):
                bits.append("g%d %d/%d%s" % (g, len(need[g] & got), len(need[g]),
                                             "*" if g in st["gens"] else ""))
            print("  %-16s %2d/%d trackable | %s | god=%s"
                  % (name, have_total, total_trackable, "  ".join(bits), st["god"]))
            continue

        # generation packs
        for g in sorted(need):
            if g in st["gens"] or not need[g].issubset(got):
                continue
            if name not in online:
                log("%s completed gen %d - PENDING (offline)" % (name, g))
                continue
            if deliver(rcon, log, name, GEN_PACK % g,
                       "Generation %d Booster Pack" % g,
                       "completing every Generation %d Arc Phone quest" % g,
                       "gold", DRY):
                st["gens"].append(g)
                changed = True

        # the ticket
        if not st["god"] and have_total >= total_trackable:
            if name not in online:
                log("%s hit 100%% - PENDING (offline)" % name)
            elif deliver(rcon, log, name, GOD_TICKET, "God Pack Ticket",
                         "completing every Arc Phone legendary quest",
                         "light_purple", DRY):
                st["god"] = True
                changed = True

    if changed and not DRY:
        tmp = STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1)
        os.replace(tmp, STATE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
