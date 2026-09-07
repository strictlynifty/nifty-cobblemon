# -*- coding: utf-8 -*-
"""Build a resource pack that repairs the Mega models Journey Mounts overwrites.

Journey Mounts and Mega Showdown both ship files at identical asset paths - for example
assets/cobblemon/bedrock/pokemon/models/0115_kangaskhan/kangaskhan_mega.geo.json. Journey
Mounts' copies are stale: different bone and cube counts, and in several cases a different
declared texture size (Manectric 128x128 vs 256x256, Altaria the same). Only Mega Showdown
ships the megaXXX.png textures, so Journey Mounts' geometry has no texture that fits it.

Whichever mod wins the path decides what you see, and in game Journey Mounts is winning: the
model renders with scattered UVs and missing faces. Rendering both pairings side by side makes
it unambiguous.

A resource pack outranks every mod's own assets, so re-supplying Mega Showdown's version of
each contested path pins the correct model. Only paths present in BOTH of those two mods are
copied - Journey Mounts also overrides ~315 base Cobblemon models on purpose, to add riding,
and those are left alone.

    python tools/mkmegafix.py <jar dir> <out.zip>
"""
import glob
import json
import os
import sys
import zipfile

PACK_FORMAT = 34          # 1.21.1


def build(jardir, out):
    jars = sorted(glob.glob(os.path.join(jardir, "*.jar")))
    jm = next((j for j in jars if "journey" in os.path.basename(j).lower()), None)
    msd = next((j for j in jars if "mega_showdown" in os.path.basename(j).lower()), None)
    if not jm or not msd:
        raise SystemExit("need both the journey-mounts and mega_showdown jars in %s" % jardir)

    zj, zm = zipfile.ZipFile(jm), zipfile.ZipFile(msd)
    contested = sorted(set(zj.namelist()) & set(zm.namelist()))
    contested = [n for n in contested if n.startswith("assets/") and not n.endswith("/")]

    def mesh(z, n):
        g = json.loads(z.read(n).decode("utf-8-sig"))["minecraft:geometry"][0]
        d = g["description"]
        return (d.get("texture_width"), d.get("texture_height"), len(g["bones"]),
                sum(len(b.get("cubes") or []) for b in g["bones"]))

    def stale(n):
        """Is Journey Mounts' copy an older MESH, rather than a ride re-rig?

        A re-rig keeps every cube and adds a bone to hang the seat off - Appletun is
        24 bones/36 cubes in Mega Showdown and 25/36 in Journey Mounts. Overriding those
        would strip the ride point and fix nothing, so they are left alone. A stale copy
        has a different cube count, a different declared texture size, or FEWER bones.
        """
        if not n.endswith(".geo.json"):
            return False
        try:
            a, b = mesh(zj, n), mesh(zm, n)
        except Exception:
            return False
        return a[:2] != b[:2] or a[3] != b[3] or a[2] < b[2]

    take = [n for n in contested if stale(n)]

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("pack.mcmeta", json.dumps({
            "pack": {
                "pack_format": PACK_FORMAT,
                "description": "Restores Mega Showdown's mega models where Journey Mounts "
                               "ships an older copy at the same path."
            }
        }, indent=2))
        for n in take:
            z.writestr(n, zm.read(n))

    kinds = {}
    for n in take:
        k = ("model" if n.endswith(".geo.json") else
             "animation" if n.endswith(".animation.json") else
             "texture" if n.endswith(".png") else
             "poser" if "/posers/" in n else "other")
        kinds[k] = kinds.get(k, 0) + 1
    print("contested paths: %d, differing: %d" % (len(contested), len(take)))
    print("by kind: %s" % kinds)
    print("species covered: %d"
          % len({n.split("/")[-2] for n in take if n.endswith(".geo.json")}))
    print("wrote %s (%.0f KB)" % (out, os.path.getsize(out) / 1024.0))
    for n in take[:40]:
        print("   %s" % n.split("/")[-1])


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
