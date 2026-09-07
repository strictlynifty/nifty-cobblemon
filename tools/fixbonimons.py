# -*- coding: utf-8 -*-
"""Give BoniMons' models unique geometry identifiers.

10 of its 16 .geo.json files declare "identifier": "geometry.unknown" - the Blockbench
default the author never renamed. Cobblemon registers geometry by that identifier, so all
ten collide and whichever loads last renders for every one of them. That is why Clobbopus
and Bramblin come out as the wrong mesh.

Species files reference the model by FILE PATH ("cobblemon:clobbopus.geo") and posers do
not mention the identifier at all, so renaming it is safe and self-contained.
"""
import zipfile, json, os, re, shutil

SRC = "X:/claude-tmp/scratch/delta/mods/bonimons-1-wrapped.jar"
TMP = "X:/claude-tmp/scratch/bonimons-fixed.jar"

zi = zipfile.ZipFile(SRC)
zo = zipfile.ZipFile(TMP, "w", zipfile.ZIP_DEFLATED, compresslevel=6)
fixed = []
for info in zi.infolist():
    data = zi.read(info.filename)
    if info.filename.endswith(".geo.json"):
        try:
            d = json.loads(data.decode("utf-8-sig"))
        except Exception:
            d = None
        if d and d.get("minecraft:geometry"):
            base = os.path.basename(info.filename)[:-9]          # strip ".geo.json"
            slug = re.sub(r"[^a-z0-9_]", "_", base.lower())
            changed = False
            for g in d["minecraft:geometry"]:
                desc = g.get("description") or {}
                if desc.get("identifier") in (None, "", "geometry.unknown"):
                    desc["identifier"] = "geometry." + slug
                    g["description"] = desc
                    changed = True
            if changed:
                data = json.dumps(d, separators=(",", ":")).encode("utf-8")
                fixed.append(base)
    zo.writestr(info.filename, data, info.compress_type)
zo.close()
zi.close()

print("renamed geometry.unknown on %d models:" % len(fixed))
print("   " + ", ".join(sorted(fixed)))

# prove no identifier collides any more
z = zipfile.ZipFile(TMP)
seen = {}
for n in z.namelist():
    if not n.endswith(".geo.json"):
        continue
    d = json.loads(z.read(n).decode("utf-8-sig"))
    for g in d.get("minecraft:geometry", []):
        i = g.get("description", {}).get("identifier")
        seen.setdefault(i, []).append(os.path.basename(n))
dupes = {k: v for k, v in seen.items() if len(v) > 1}
print()
print("distinct identifiers now: %d over %d models" % (len(seen), sum(len(v) for v in seen.values())))
print("collisions remaining    : %s" % (dupes or "none"))
print("integrity               : %s" % (z.testzip() or "OK"))
z.close()
shutil.move(TMP, SRC)
print("swapped into the delta")
