#!/usr/bin/env python3
"""Scaffold a resource pack for tuning the Dynamax halo on every gmax species.

The halo ("dmax_clouds") is positioned by a data file, not by code:

    assets/mega_showdown/msd_sizer/<name>_clouds.json
    { "pokemon": "<name>",
      "size_config": { "Gmax": { "msd:dmax": {
          "scale": [x,y,z], "translate": [x,y,z], "rotation": [x,y,z] } } } }

Mega Showdown 1.9.5 ships only SEVEN of these for 32 gmax species, so 25 render the halo at
the default transform. Charizard has one, but it sets `scale` and no `translate` - every other
tuned species has a translate - which is the likeliest reason it sits wrong.

These live under assets/, so a resource pack overrides them and F3+T reloads them. Tuning is
therefore an edit-and-look loop with no restart.

Values are NOT invented here. Species the mod already tunes keep the mod's exact numbers;
the rest are seeded with the identity transform and marked, so what is guesswork is obvious
rather than hidden behind plausible-looking numbers.
"""
import zipfile, json, os, sys, hashlib

JAR = sys.argv[1] if len(sys.argv) > 1 else "X:/claude-tmp/scratch/blast/msd195.jar"
OUT = sys.argv[2] if len(sys.argv) > 2 else "X:/cobblemon-ops/client/pending/nifty-halo-tuning.zip"

GMAX = """alcremie appletun blastoise butterfree centiskorch charizard cinderace coalossal
copperajah corviknight drednaw duraludon eevee flapple garbodor gengar grimmsnarl hatterene
inteleon kingler lapras machamp melmetal meowth orbeetle pikachu rillaboom sandaconda snorlax
toxtricity urshifu venusaur""".split()

z = zipfile.ZipFile(JAR)
existing = {}
for n in z.namelist():
    if "/msd_sizer/" in n and n.endswith(".json"):
        d = json.loads(z.read(n).decode("utf-8-sig"))
        existing[str(d.get("pokemon", "")).lower()] = d

os.makedirs(os.path.dirname(OUT), exist_ok=True)
seeded, copied = [], []
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as out:
    out.writestr("pack.mcmeta", json.dumps({
        # 34 is the RESOURCE pack format for 1.21.1. 48 is the DATApack format - using it
        # here made the game refuse the pack as "made for a different version", which is why
        # editing these files appeared to do nothing.
        "pack": {"pack_format": 34,
                 "description": "strictlynifty - Gigantamax halo tuning"}}, indent=1))
    for sp in GMAX:
        if sp in existing:
            body = existing[sp]
            copied.append(sp)
        else:
            body = {"pokemon": sp,
                    "_comment": "UNTUNED - identity transform, adjust and reload with F3+T",
                    "size_config": {"Gmax": {"msd:dmax": {
                        "scale": [1.0, 1.0, 1.0],
                        "translate": [0.0, 0.0, 0.0],
                        "rotation": [0.0, 0.0, 0.0]}}}}
            seeded.append(sp)
        out.writestr("assets/mega_showdown/msd_sizer/%s_clouds.json" % sp,
                     json.dumps(body, indent=1))

print("wrote %s  (%.0f KB)" % (OUT, os.path.getsize(OUT) / 1024))
print("  carried the mod's own values for %d: %s" % (len(copied), ", ".join(copied)))
print("  seeded UNTUNED (identity) for %d: %s" % (len(seeded), ", ".join(seeded)))
print("  sha256 %s" % hashlib.sha256(open(OUT, "rb").read()).hexdigest()[:16])
print()
print("Edit a file, press F3+T in game, look. No restart, no server change.")
