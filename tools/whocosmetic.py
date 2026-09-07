"""Who currently has a cosmetic item on a species that can break because of it?

Seven species pair an unguarded cosmetic layer with an alternate form at a different UV
resolution. The layer only misrenders while that alternate form is active, so a mega one is
harmless until mega-evolved - but a gmax one shows the moment the form is on.
"""
import os
import sys, glob, json, re, collections

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")
sys.path.insert(0, "/tmp"); sys.path.insert(0, COBBLEMON_DIR)
from nbt2 import load

BASE = COBBLEMON_DIR
RISK = {"blastoise": "gmax 512 vs base 256   (SHOWS NOW if gmax)",
        "dragonite": "mega 512 vs base 256x128",
        "delphox":   "mega 256x256 vs base 256x128",
        "hawlucha":  "mega 128x128 vs base 128x64",
        "pikachu":   "gmax 256 vs base 128x64  (SHOWS NOW if gmax)",
        "raichu":    "mega_x 256 vs base 128x64",
        "sceptile":  "mega 198x128 vs base 128x64"}

names = {e["uuid"]: e["name"] for e in json.load(open(BASE + "/usercache.json"))}
found = []

def walk(o, who, store):
    if isinstance(o, dict):
        sp = o.get("Species")
        if isinstance(sp, str):
            b = re.sub(r"[^a-z0-9]", "", sp.split(":")[-1].lower())
            ci = o.get("CosmeticItem")
            if b in RISK and isinstance(ci, dict) and ci.get("id"):
                found.append((who, store, b, str(ci.get("id")), str(o.get("FormId"))))
        for v in o.values():
            walk(v, who, store)
    elif isinstance(o, list):
        for v in o:
            walk(v, who, store)

for uuid, who in names.items():
    for store, lbl in (("playerpartystore", "party"), ("pcstore", "PC")):
        for p in glob.glob("%s/world/pokemon/%s/*/%s.dat" % (BASE, store, uuid)):
            try:
                walk(load(p), who, lbl)
            except Exception:
                pass

if not found:
    print("Nobody is carrying a cosmetic on an at-risk species.")
else:
    print("Cosmetic items on species that can misrender:")
    print()
    for who, store, sp, item, form in sorted(found):
        flag = "  <-- ACTIVE NOW" if form in ("gmax",) else ""
        print("  %-16s %-5s %-11s %-28s FormId=%-8s%s"
              % (who, store, sp, item.split(":")[-1], form, flag))
        print("       %s" % RISK[sp])
