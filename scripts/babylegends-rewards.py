#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Grant a God Pack Ticket for registering every Baby Legends species in the Pokedex.

28 species ship in baby-legends-cobblemon-2.4.jar, all under the `cobblemon:` namespace
(the mod does not use a namespace of its own). Progress is read from the player's own
Pokedex save, world/pokedex/<xx>/<uuid>.nbt:

    speciesRecords["cobblemon:<species>"].formRecords[<form>].knowledge  ->  ENCOUNTERED | CAUGHT

ENCOUNTERED is enough. That is deliberate: it makes the reward reachable by scanning
someone else's Pokemon, so the four of us can help each other finish it, which is the point.

Deliberately a SEPARATE script from arcphone-rewards.py rather than folded into it -- that
one is live and working, and a bug in a merged version would take both rewards down.

Items can only reach an ONLINE player, so a ticket earned while offline stays pending and is
granted on the next pass. State is only written after the /give is confirmed, which is what
makes that safe.

Usage:
    babylegends-rewards.py            grant anything owed to online players
    babylegends-rewards.py --status   print everyone's progress, grant nothing
    babylegends-rewards.py --dry-run  say what it would grant, grant nothing
"""
import glob, gzip, io, json, os, re, struct, subprocess, sys, time

BASE = os.environ.get("COBBLEMON_DIR", BASE)
sys.path.insert(0, BASE)
from rewardutil import deliver

STATE = os.path.join(BASE, "babylegends-rewards-state.json")
USERCACHE = os.path.join(BASE, "usercache.json")
LOG = os.path.join(BASE, "logs/babylegends-rewards.log")
POKEDEX = os.path.join(BASE, "world/pokedex/*/*.nbt")

GOD_TICKET = "cobblemon-cards:god_pack_ticket"
KNOWN = ("ENCOUNTERED", "CAUGHT")

# the 28 species in baby-legends-cobblemon-2.4.jar, verified from its data/cobblemon/species/
BABIES = ["articoo", "beta", "courpup", "creslume", "delcalf", "foreroar", "fulguroar",
          "giragrub", "haidon", "kaidon", "karfoal", "latot", "myu", "myutu", "neonite",
          "ohho", "raygul", "regiclay", "rotisikree", "saladune", "statchic", "temga",
          "vertrice", "volcaroar", "xerfawn", "yangram", "yivpip", "zerpint"]

DRY = "--dry-run" in sys.argv
STATUS = "--status" in sys.argv


def log(msg):
    line = "%s %s" % (time.strftime("%F %T"), msg)
    if not STATUS:
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
    print(line)


def rcon(cmd):
    return subprocess.run(["python3", "rcon.py", cmd], cwd=BASE,
                          capture_output=True, text=True, timeout=30).stdout.strip()


def read_nbt(path):
    raw = open(path, "rb").read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    f = io.BytesIO(raw)

    def u1(): return f.read(1)[0]
    def i4(): return struct.unpack(">i", f.read(4))[0]
    def st(): return f.read(struct.unpack(">H", f.read(2))[0]).decode("utf-8", "replace")

    def payload(t):
        if t == 1: return struct.unpack(">b", f.read(1))[0]
        if t == 2: return struct.unpack(">h", f.read(2))[0]
        if t == 3: return i4()
        if t == 4: return struct.unpack(">q", f.read(8))[0]
        if t == 5: return struct.unpack(">f", f.read(4))[0]
        if t == 6: return struct.unpack(">d", f.read(8))[0]
        if t == 7: return f.read(i4())
        if t == 8: return st()
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
        if t == 11: return [i4() for _ in range(i4())]
        if t == 12: return [struct.unpack(">q", f.read(8))[0] for _ in range(i4())]
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


def registered(dex):
    """Which baby legends this Pokedex has at ENCOUNTERED or better."""
    sr = dex.get("speciesRecords") or {}
    out = []
    for b in BABIES:
        rec = sr.get("cobblemon:" + b)
        if not rec:
            continue
        forms = (rec.get("formRecords") or {}).values()
        if any(fr.get("knowledge") in KNOWN for fr in forms):
            out.append(b)
    return out


def main():
    names = {e.get("uuid"): e.get("name") for e in load_json(USERCACHE, [])}
    state = load_json(STATE, {})

    online = set()
    if not STATUS:
        m = re.search(r"online:\s*(.*)$", rcon("list"))
        if m and m.group(1).strip():
            online = {x.strip() for x in m.group(1).split(",") if x.strip()}

    changed = False
    for path in sorted(glob.glob(POKEDEX)):
        uuid = os.path.basename(path)[:-4]
        name = names.get(uuid, uuid[:8])
        try:
            have = registered(read_nbt(path))
        except Exception as ex:
            log("could not read pokedex for %s (%s) - skipping" % (name, ex))
            continue

        st = state.setdefault(uuid, {"name": name, "god": False})
        st["name"] = name

        if STATUS:
            missing = [b for b in BABIES if b not in have]
            print("  %-16s %2d/%d registered | ticket=%s" % (name, len(have), len(BABIES), st["god"]))
            if missing:
                print("       missing: %s" % ", ".join(missing))
            continue

        if st["god"] or len(have) < len(BABIES):
            continue
        if name not in online:
            log("%s has all %d baby legends - PENDING (offline)" % (name, len(BABIES)))
            continue
        if deliver(rcon, log, name, GOD_TICKET, "God Pack Ticket",
                   "registering all %d Baby Legendaries" % len(BABIES),
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
