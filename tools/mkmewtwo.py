# -*- coding: utf-8 -*-
"""Make Mewtwo fly like a bird instead of a jet.
Cobblemon does not make Mewtwo rideable at all ("behaviour": null); Journey Mounts adds
the riding and picks cobblemon:air/jet. JetBehaviour has no roll correction and no
damping - three roll fields against BirdBehaviour is twenty - so Mewtwo never levels
itself out. Every other flyer here (Zapdos, Lugia, Honchkrow) is air/bird.
Journey Mounts ships a COMPLETE species file, so the override has to be complete too.
Copy theirs verbatim and change only riding.behaviours.AIR, modelled on Zapdos: key,
rideSounds and stats, with the jet-tuned speed/gravity/jumpVector dropped because the
bird controller handles those itself.
"""
import zipfile, json, os, shutil

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")

SRC = COBBLEMON_DIR + "/mods/cobblemon-journey-mounts-1.7.2.jar"
PATH = "data/cobblemon/species/generation1/mewtwo.json"
OUT = COBBLEMON_DIR + "/world/datapacks/mewtwo-bird-ride"

z = zipfile.ZipFile(SRC)
d = json.loads(z.read(PATH).decode("utf-8-sig"))
z.close()

air = d["riding"]["behaviours"]["AIR"]
before = dict(air)
new_air = {"key": "cobblemon:air/bird"}
if "rideSounds" in air:
    new_air["rideSounds"] = air["rideSounds"]
new_air["stats"] = air["stats"]
d["riding"]["behaviours"]["AIR"] = new_air

shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(os.path.join(OUT, os.path.dirname(PATH)), exist_ok=True)
with open(os.path.join(OUT, PATH), "w", encoding="utf-8") as f:
    json.dump(d, f, indent=2)
with open(os.path.join(OUT, "pack.mcmeta"), "w", encoding="utf-8") as f:
    json.dump({"pack": {"pack_format": 48,
                        "supported_formats": {"min_inclusive": 34, "max_inclusive": 48},
                        "description": "Mewtwo flies with the bird controller, not the jet"}},
              f, indent=2)

print("AIR before:", sorted(before.keys()))
print("   key    :", before.get("key"))
print("AIR after :", sorted(new_air.keys()))
print("   key    :", new_air.get("key"))
print("   dropped:", sorted(set(before) - set(new_air)))
print()
print("LAND untouched:", d["riding"]["behaviours"]["LAND"]["key"])
print("top-level keys carried over:", len(d))
print("stats preserved:", new_air["stats"] == before["stats"])
print()
print("written to", OUT)
