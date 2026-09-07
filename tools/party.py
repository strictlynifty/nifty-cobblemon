"""Current party state. SlotCount also starts with 'Slot' - filter on the value being a
Pokemon, not on the key name."""
import os
import sys, glob, json

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")
sys.path.insert(0, COBBLEMON_DIR)
from nbt2 import load
BASE = COBBLEMON_DIR
uuid = {e["name"]: e["uuid"] for e in json.load(open(BASE + "/usercache.json"))}[os.environ.get("MC_PLAYER", "Player")]
for p in glob.glob("%s/world/pokemon/playerpartystore/*/%s.dat" % (BASE, uuid)):
    d = load(p)
    slots = {}
    for k, v in d.items():
        ks = str(k)
        if ks.startswith("Slot") and ks[4:].isdigit() and isinstance(v, dict) and v.get("Species"):
            slots[int(ks[4:])] = v
    for i in sorted(slots):
        m = slots[i]
        print("  party slot %d (Slot%d)  %-13s FormId=%-8s GmaxFactor=%s Shiny=%s"
              % (i + 1, i, str(m.get("Species")).split(":")[-1], m.get("FormId"),
                 m.get("GmaxFactor"), m.get("Shiny")))
