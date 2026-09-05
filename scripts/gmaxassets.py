"""Re-check the two suspect species against the UNION of every mod's assets.

A resolver in Mega Showdown may legitimately reference a poser/model/texture shipped by base
Cobblemon. Judging one jar in isolation would wrongly call those broken.
"""
import zipfile, json, os, glob

MODS = "$COBBLEMON_DIR/mods"
posers, geos, files = set(), set(), set()
resolvers = []

for jar in sorted(glob.glob(os.path.join(MODS, "*.jar"))):
    try:
        z = zipfile.ZipFile(jar)
    except Exception:
        continue
    for n in z.namelist():
        files.add(n)
        if n.endswith(".json") and "/posers/" in n:
            posers.add(n.rsplit("/", 1)[-1][:-5])
        if n.endswith(".json") and "/models/" in n:
            geos.add(n.rsplit("/", 1)[-1][:-5])
        if n.endswith(".json") and "/resolvers/" in n:
            resolvers.append((jar, n, z))

print("scanned %d jars: %d posers, %d geos, %d files, %d resolvers"
      % (len(glob.glob(os.path.join(MODS, "*.jar"))), len(posers), len(geos),
         len(files), len(resolvers)))

res = {}
for jar, n, z in resolvers:
    try:
        d = json.loads(z.read(n).decode("utf-8-sig"))
    except Exception:
        continue
    sp = str(d.get("species", "")).split(":")[-1].lower()
    if not sp:
        continue
    for v in d.get("variations", []):
        asp = {str(a).lower() for a in (v.get("aspects") or [])}
        if "gmax" not in asp or "shiny" in asp:
            continue
        poser = str(v.get("poser", "")).split(":")[-1]
        model = str(v.get("model", "")).split(":")[-1]
        tex = str(v.get("texture", ""))
        tp = "assets/%s/%s" % tuple(tex.split(":", 1)) if ":" in tex else ""
        res[sp] = (poser, model, tp, os.path.basename(jar))

good, bad = [], []
for sp, (poser, model, tp, jar) in sorted(res.items()):
    miss = []
    if poser and poser not in posers: miss.append("poser:" + poser)
    if model and model not in geos:   miss.append("model:" + model)
    if tp and tp not in files:        miss.append("texture")
    (bad if miss else good).append((sp, miss, poser, model, tp))

print()
print("RENDERABLE (%d): %s" % (len(good), " ".join(s for s, _, _, _, _ in good)))
if bad:
    print()
    print("STILL MISSING across all %d jars:" % len(glob.glob(os.path.join(MODS, "*.jar"))))
    for sp, miss, poser, model, tp in bad:
        print("   ! %-11s %s" % (sp, ", ".join(miss)))
        if "texture" in miss:
            print("       wanted: %s" % tp)
