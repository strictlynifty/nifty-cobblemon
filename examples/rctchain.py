"""The full radicalred progression: every required trainer and what gates it.

Each trainer file carries `requiredDefeats`, a list of alternative prerequisite groups. Walk
every trainer in the series, build the graph, and sort it into tiers - tier 0 needs nothing,
tier N needs something from tier N-1. That is the order they must be spawned and beaten in.
"""
import zipfile, json, os, collections

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")

MODS = COBBLEMON_DIR + "/mods"
trainers = {}
for f in sorted(os.listdir(MODS)):
    if not f.endswith(".jar"):
        continue
    try:
        z = zipfile.ZipFile(os.path.join(MODS, f))
    except Exception:
        continue
    for n in z.namelist():
        if "/mobs/trainers/" not in n or not n.endswith(".json"):
            continue
        try:
            d = json.loads(z.read(n).decode("utf-8-sig"))
        except Exception:
            continue
        if "radicalred" not in (d.get("series") or []):
            continue
        tid = n.split("/")[-1].replace(".json", "")
        trainers[tid] = d

print("radicalred trainers found: %d" % len(trainers))
print()

# requiredDefeats is a list of OR-groups; each group is a list of trainer ids (AND within it)
def prereqs(d):
    out = set()
    for grp in (d.get("requiredDefeats") or []):
        if isinstance(grp, list):
            out |= {str(x) for x in grp}
        else:
            out.add(str(grp))
    return out

tier = {}
remaining = dict(trainers)
level = 0
while remaining and level < 30:
    ready = [t for t, d in remaining.items()
             if all(p in tier or p not in trainers for p in prereqs(d))]
    if not ready:
        break
    for t in ready:
        tier[t] = level
        remaining.pop(t)
    level += 1

byt = collections.defaultdict(list)
for t, lv in tier.items():
    byt[lv].append(t)

for lv in sorted(byt):
    mons = sorted(byt[lv])
    leaders = [m for m in mons if m.startswith("leader")]
    bosses = [m for m in mons if m.startswith("boss")]
    others = [m for m in mons if not m.startswith(("leader", "boss"))]
    print("TIER %d  (%d trainers)" % (lv, len(mons)))
    if leaders: print("   LEADERS: %s" % ", ".join(leaders))
    if bosses:  print("   BOSSES : %s" % ", ".join(bosses))
    if others:  print("   others : %s%s" % (", ".join(others[:10]), " ..." if len(others) > 10 else ""))
if remaining:
    print()
    print("unresolved (cyclic or external prereqs): %d" % len(remaining))
    for t in sorted(remaining)[:10]:
        print("   %-26s needs %s" % (t, sorted(prereqs(remaining[t]))[:4]))
