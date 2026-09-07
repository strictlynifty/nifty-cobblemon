# -*- coding: utf-8 -*-
"""Build the series walkthroughs for the Trainers page.

What a player actually needs at the gym is two things: the ORDER, and the SIGNATURE
ITEM to load into the Trainer Spawner. Both are in rctmod's mob files - `requiredDefeats`
gives the dependency graph, `signatureItem` gives the spawner item - and neither has ever
been on the wiki.

Writes /tmp/wiki_trainers.json.
"""
import zipfile, json, collections, re, os

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")

JAR = COBBLEMON_DIR + "/mods/rctmod-fabric-1.21.1-0.18.1-beta.jar"
z = zipfile.ZipFile(JAR)

mobs = {}
for n in z.namelist():
    if "/mobs/trainers/" not in n or not n.endswith(".json"):
        continue
    if n.endswith("default.json") or "/groups/" in n:
        continue
    tid = n.split("/")[-1][:-5]
    try:
        mobs[tid] = json.loads(z.read(n).decode("utf-8-sig"))
    except Exception:
        pass

# display names come from the trainer definitions
names = {}
levels = {}
types = {}
for n in z.namelist():
    if "/trainers/" in n and n.endswith(".json") and "/mobs/" not in n:
        tid = n.split("/")[-1][:-5]
        try:
            d = json.loads(z.read(n).decode("utf-8-sig"))
            names[tid] = d.get("name") or tid
            # Highest level on the team. Spawner-summoned trainers ignore the level cap, so
            # this is what a player needs in order to nerf their party to a fair fight - and
            # it was previously only findable by Ctrl-F'ing further down the page.
            lv = [p.get("level") for p in (d.get("team") or []) if p.get("level")]
            if lv:
                levels[tid] = max(lv)
        except Exception:
            pass

print("mob entries: %d, trainer definitions: %d" % (len(mobs), len(names)))


# ---- which trainers a gym structure actually places -------------------------------
# Read from the structure NBT rather than assumed from the file name, so a gym is only listed
# as an option if it really contains that trainer. The ids are gzipped inside the .nbt; scan the
# decompressed bytes and keep whatever matches a real trainer id.
import gzip

RGS_JAR = COBBLEMON_DIR + "/mods/RadicalGymsStructures-RGS.jar"
GYM_LABEL = {
    "pewter_gym":     "a Pewter Gym (Rock)",
    "cerulean_gym":   "a Cerulean Gym (Water)",
    "vermilion_gym":  "a Vermilion Gym (Electric)",
    "celadon_gym":    "a Celadon Gym (Grass)",
    "saffron_gym":    "a Saffron Gym (Psychic)",
    "fuchsia_gym":    "a Fuchsia Gym (Poison)",
    "cinnabar_gym":   "a Cinnabar Gym (Fire), in the Nether",
    "blackthorn_gym": "a Blackthorn Gym (Dragon), in the End",
    "kanto_league":   "the Kanto League, in the End",
}
gyms = {}
if os.path.exists(RGS_JAR):
    gz = zipfile.ZipFile(RGS_JAR)
    for n in gz.namelist():
        key = n.split("/")[-1][:-4] if n.endswith(".nbt") else None
        if key not in GYM_LABEL:
            continue
        raw = gz.read(n)
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
        for tid in set(re.findall(rb"[a-z][a-z_]*_[0-9a-f]{4}", raw)):
            tid = tid.decode()
            if tid in mobs:  # block names like stripped_acac fit the pattern too
                gyms[tid] = GYM_LABEL[key]
print("gym structures place %d trainers" % len(gyms))

by_series = collections.defaultdict(dict)
for tid, m in mobs.items():
    for s in (m.get("series") or []):
        by_series[s][tid] = m

print("series found:", {k: len(v) for k, v in by_series.items()})


def pretty(tid):
    base = names.get(tid) or re.sub(r"_[0-9a-f]{4}$", "", tid).replace("_", " ").title()
    return base


def order(series_map):
    """Topological order by requiredDefeats; ties broken by how many gate on you."""
    deps = {}
    for tid, m in series_map.items():
        need = set()
        for grp in (m.get("requiredDefeats") or []):
            if isinstance(grp, list):
                need |= {g for g in grp if g in series_map}
            elif grp in series_map:
                need.add(grp)
        deps[tid] = need
    out, done = [], set()
    guard = 0
    while len(done) < len(series_map) and guard < 5000:
        guard += 1
        ready = sorted([t for t in series_map if t not in done and deps[t] <= done])
        if not ready:                       # cycle or external dep - take the rest
            ready = sorted(t for t in series_map if t not in done)
        for t in ready:
            out.append(t)
            done.add(t)
    return out


TYPE_LABEL = {"leader": "Gym Leader", "e4": "Elite Four", "champion": "Champion",
              "rival": "Rival", "team_rocket": "Team Rocket", "normal": "Trainer",
              "boss": "Boss", "title_defense": "Title Defense",
              "team_galactic": "Team Galactic", "team_aqua": "Team Aqua",
              "team_magma": "Team Magma", "team": "Team", "elite_four": "Elite Four"}

result = {}
for series, smap in by_series.items():
    rows = []
    for tid in order(smap):
        m = smap[tid]
        rows.append({
            "id": tid,
            "n": pretty(tid),
            "t": TYPE_LABEL.get(m.get("type", "normal"), str(m.get("type", "")).title()),
            "item": m.get("signatureItem"),
            "req": [g for grp in (m.get("requiredDefeats") or [])
                    for g in (grp if isinstance(grp, list) else [grp])],
            "opt": bool(m.get("optional", True)),
            "maxDef": m.get("maxTrainerDefeats"),
            "lvl": levels.get(tid),
            "gym": gyms.get(tid),
        })
    # Collapse repeat encounters: RCT ships one mob file per encounter, so Cedric
    # appears 12 times and Rival Wayne 6. A player needs "beat this one N times",
    # not twelve identical rows.
    merged = []
    for r in rows:
        if merged and merged[-1]["n"] == r["n"] and merged[-1]["t"] == r["t"]                 and merged[-1]["item"] == r["item"]:
            merged[-1]["count"] += 1
            # later encounters with the same trainer are higher level - keep the span
            if r.get("gym") and not merged[-1].get("gym"):
                merged[-1]["gym"] = r["gym"]
            if r.get("lvl"):
                prev = merged[-1].get("lvl")
                merged[-1]["lvl"] = max(prev, r["lvl"]) if prev else r["lvl"]
                lo = merged[-1].get("lvlLo") or prev or r["lvl"]
                merged[-1]["lvlLo"] = min(lo, r["lvl"])
            continue
        r["count"] = 1
        merged.append(r)
    result[series] = merged

json.dump(result, open("/tmp/wiki_trainers.json", "w"), separators=(",", ":"))
print("wrote /tmp/wiki_trainers.json")
print()
for s, rows in result.items():
    withitem = [r for r in rows if r["item"]]
    req = [r for r in rows if not r["opt"]]
    print("== %-12s %3d trainers, %3d required, %3d with a signature item"
          % (s, len(rows), len(req), len(withitem)))
    for r in rows[:8]:
        print("    %-26s %-14s x%-2d %s" % (r["n"], r["t"], r["count"], r["item"] or "-"))
