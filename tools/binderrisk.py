"""How much of the wild spawns around each player does their binder rewrite?

The modifier fires for every wild Pokemon loading within 64 blocks, once per elemental type
the binder has _spawn cards for, and only when the Pokemon is not already that type. So the
per-spawn conversion chance is roughly 1 - product(1 - p_type) over the types that do not
match. A converted Pokemon is REBUILT by Species.create(level): shiny, IVs, nature and ability
are all discarded.
"""
import os
import sys, glob, json, collections

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")
sys.path.insert(0, COBBLEMON_DIR)
from nbt2 import load

BASE = COBBLEMON_DIR
names = {e["uuid"]: e["name"] for e in json.load(open(BASE + "/usercache.json"))}

def cards(o, out):
    if isinstance(o, dict):
        for k, v in o.items():
            if "card_data" in str(k) and isinstance(v, dict):
                out.append(dict(v))
            cards(v, out)
    elif isinstance(o, list):
        for v in o:
            cards(v, out)
    return out

for uuid, who in sorted(names.items(), key=lambda kv: kv[1]):
    for p in glob.glob("%s/world/playerdata/%s.dat" % (BASE, uuid)):
        try:
            cs = cards(load(p), [])
        except Exception:
            continue
        by = collections.defaultdict(float)
        n = collections.Counter()
        for c in cs:
            st = str(c.get("stat", ""))
            if not st.endswith("_spawn"):
                continue
            v = c.get("stat_value")
            if v is None:
                v = c.get("statValue")
            if v is None:
                continue
            by[st[:-6]] += float(v) * 10.0     # the log prints statValue * 10 as a percent
            n[st[:-6]] += 1
        if not by:
            continue
        # chance a given wild spawn is left ALONE by every type it is not already
        survive = 1.0
        for t, pct in by.items():
            survive *= (1.0 - pct / 100.0)
        print("=== %s ===" % who)
        for t, pct in sorted(by.items(), key=lambda kv: -kv[1])[:6]:
            print("   %-10s %5.3f%%  (%d card%s)" % (t, pct, n[t], "s" if n[t] > 1 else ""))
        if len(by) > 6:
            print("   ... and %d more types" % (len(by) - 6))
        print("   TOTAL types=%d   chance a wild spawn gets rewritten: ~%.2f%%"
              % (len(by), (1 - survive) * 100))
        print()
