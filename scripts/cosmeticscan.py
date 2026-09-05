"""Which other species can a cosmetic item break?

The fault needs two things on the same species: an unguarded cosmetic variation (one whose
aspects contain a cosmetic_item-* and nothing else, so it applies to every form), and an
alternate form whose geometry uses a LARGER UV space than the base model the layer was drawn
for. Report the pairs.
"""
import zipfile, json, os

MODS = "$COBBLEMON_DIR/mods"
res, geos = {}, {}
for f in sorted(os.listdir(MODS)):
    if not f.endswith(".jar"):
        continue
    z = zipfile.ZipFile(os.path.join(MODS, f))
    for n in z.namelist():
        if not n.endswith(".json"):
            continue
        if "/models/" in n:
            try:
                d = json.loads(z.read(n).decode("utf-8-sig"))
                desc = (d.get("minecraft:geometry") or [{}])[0].get("description", {})
                geos[n.rsplit("/", 1)[-1][:-5]] = (desc.get("texture_width"),
                                                   desc.get("texture_height"))
            except Exception:
                pass
        elif "/resolvers/" in n:
            try:
                res.setdefault(n, json.loads(z.read(n).decode("utf-8-sig")))
            except Exception:
                pass

per = {}
for n, d in res.items():
    sp = str(d.get("species", "")).split(":")[-1].lower()
    if not sp:
        continue
    e = per.setdefault(sp, {"cosmetic": [], "models": {}})
    for v in d.get("variations", []):
        asp = {str(a).lower() for a in (v.get("aspects") or [])}
        cos = {a for a in asp if a.startswith("cosmetic_item-")}
        if cos and asp == cos:
            e["cosmetic"].append(sorted(cos))
        m = str(v.get("model", "")).split(":")[-1]
        if m:
            e["models"][tuple(sorted(asp)) or ("base",)] = m

hits = []
for sp, e in sorted(per.items()):
    if not e["cosmetic"]:
        continue
    sizes = {}
    for asp, m in e["models"].items():
        g = geos.get(m)
        if g and g[0]:
            sizes[asp] = g
    if len(set(sizes.values())) > 1:
        hits.append((sp, e["cosmetic"], sizes))

print("species with an UNGUARDED cosmetic layer AND mixed model resolutions:")
print()
if not hits:
    print("  none besides those listed below")
for sp, cos, sizes in hits:
    print("  %s" % sp)
    print("     cosmetics: %s" % ", ".join("+".join(c) for c in cos))
    for asp, g in sorted(sizes.items(), key=lambda kv: str(kv[0])):
        label = "base" if asp == ("base",) else "+".join(asp)
        print("     %-38s %sx%s" % (label, g[0], g[1]))
    print()

total = sum(1 for e in per.values() if e["cosmetic"])
print("(%d species have an unguarded cosmetic variation in total; %d of them have a form at a "
      "different resolution)" % (total, len(hits)))
