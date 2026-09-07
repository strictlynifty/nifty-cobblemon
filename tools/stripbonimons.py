# -*- coding: utf-8 -*-
"""Keep only the species BoniMons actually adds; drop the ones it needlessly replaces.

BoniMons ships models for 16 species, but Cobblemon already models 10 of them properly
(arboliva, brambleghast, bramblin, clobbopus, dolliv, furfrou, grapploct, sandaconda,
silicobra, smoliv). For those it substitutes its own, lower-quality mesh - which is why
Clobbopus and Bramblin look wrong in game.

It also overwrites those species' data files, changing hitbox and baseScale.

We installed BoniMons for the six Cobblemon lacks. Strip it to those six: Clobbopus and
friends fall back to Cobblemon's own models and data, and Okidogi, Fezandipiti, Bombirdier,
Gouging Fire, Sandy Shocks and Cobalion still arrive.
"""
import zipfile, json, os, re, shutil

SRC = "X:/claude-tmp/scratch/delta/mods/bonimons-1-wrapped.jar"
TMP = "X:/claude-tmp/scratch/bonimons-stripped.jar"

# species Cobblemon already models - let its own assets and data win
DROP = {"arboliva", "brambleghast", "bramblin", "clobbopus", "dolliv",
        "furfrou", "grapploct", "sandaconda", "silicobra", "smoliv"}


def species_of(path):
    """Which species does this entry belong to, if any?"""
    for pat in (r"/bedrock/models/([a-z0-9_]+)/",
                r"/bedrock/animations/([a-z0-9_]+)/",
                r"/textures/pokemon/([a-z0-9_]+)/",
                r"/sounds/pokemon/([a-z0-9_]+)/",
                r"/bedrock/posers/([a-z0-9_]+)\.json$",
                r"/bedrock/species/\d+_([a-z0-9_]+)_base\.json$",
                r"/bedrock/species/([a-z0-9_]+)\.json$",
                r"/spawn_pool_world/([a-z0-9_]+)\.json$",
                r"/species/[a-z0-9]+/([a-z0-9_]+)\.json$"):
        m = re.search(pat, path)
        if m:
            # Cobblemon numbers its asset folders (0852_clobbopus); BoniMons uses both
            # layouts. Strip the dex number or the name never matches the drop list -
            # which is how its REPLACEMENT TEXTURES survived the first pass and kept
            # rendering over Cobblemon's mesh.
            return re.sub(r"^\d{3,4}_", "", m.group(1))
    return None


zi = zipfile.ZipFile(SRC)
zo = zipfile.ZipFile(TMP, "w", zipfile.ZIP_DEFLATED, compresslevel=6)
kept = dropped = 0
dropped_species = set()
for info in zi.infolist():
    sp = species_of(info.filename)
    if sp in DROP:
        dropped += 1
        dropped_species.add(sp)
        continue
    zo.writestr(info.filename, zi.read(info.filename), info.compress_type)
    kept += 1
zo.close()
zi.close()

print("dropped %d files covering %d species: %s"
      % (dropped, len(dropped_species), ", ".join(sorted(dropped_species))))
print("kept    %d files" % kept)

z = zipfile.ZipFile(TMP)
left = sorted({m.group(1) for n in z.namelist()
               if (m := re.search(r"/bedrock/models/([a-z0-9_]+)/", n))})
print()
print("species still supplied: %s" % ", ".join(left))
print("integrity: %s" % (z.testzip() or "OK"))
z.close()
shutil.move(TMP, SRC)
print("swapped into the delta")
