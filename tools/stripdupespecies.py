# -*- coding: utf-8 -*-
"""Strip a Cobblemon addon down to the species Cobblemon does not already model.

Addons like BoniMons and Monkeymons advertise themselves as adding missing Pokemon, but
each also ships its own, lower-quality mesh for species Cobblemon already models properly.
Those meshes - and, worse, the TEXTURES that go with them - override Cobblemon's own, which
is why Clobbopus and Bramblin rendered as scrambled geometry in game.

Cobblemon numbers its asset folders (0852_clobbopus); the addons use both layouts, sometimes
in the SAME jar. Comparing the raw folder names therefore reports "no overlap" when in fact
every one of them collides. Normalise the dex number off both sides before comparing, or
this whole check silently passes and ships the bug.

Usage: stripdupespecies.py <cobblemon.jar> <addon.jar> [addon.jar ...]
The addon jars are rewritten in place. Re-running on an already-stripped jar is a no-op.
"""
import zipfile, os, re, shutil, sys

# every path layout that binds a file to one species; the numbered prefix is optional
# because addons mix "clobbopus/" and "0852_clobbopus/" in the same archive
PATTERNS = (r"/bedrock/pokemon/models/([a-z0-9_]+)/",
            r"/bedrock/models/([a-z0-9_]+)/",
            r"/bedrock/animations/([a-z0-9_]+)/",
            r"/textures/pokemon/([a-z0-9_]+)/",
            r"/sounds/pokemon/([a-z0-9_]+)/",
            r"/bedrock/posers/([a-z0-9_]+)\.json$",
            r"/bedrock/species/(?:\d+_)?([a-z0-9_]+?)(?:_base)?\.json$",
            r"/spawn_pool_world/([a-z0-9_]+)\.json$",
            r"/species/[a-z0-9]+/([a-z0-9_]+)\.json$")


def species_of(path):
    for pat in PATTERNS:
        m = re.search(pat, path)
        if m:
            return re.sub(r"^\d{3,4}_", "", m.group(1))
    return None


def modelled(jar):
    """Species this jar supplies a MESH for - the thing that actually collides."""
    z = zipfile.ZipFile(jar)
    out = {s for n in z.namelist()
           for s in [species_of(n)]
           if s and re.search(r"/bedrock/(pokemon/)?models/", n)}
    z.close()
    return out


def strip(addon, drop):
    tmp = addon + ".tmp"
    zi = zipfile.ZipFile(addon)
    zo = zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6)
    kept = dropped = 0
    for info in zi.infolist():
        if species_of(info.filename) in drop:
            dropped += 1
            continue
        zo.writestr(info.filename, zi.read(info.filename), info.compress_type)
        kept += 1
    zo.close()
    zi.close()
    z = zipfile.ZipFile(tmp)
    bad = z.testzip()
    left = sorted(modelled(tmp))
    z.close()
    if bad:
        os.remove(tmp)
        raise SystemExit("corrupt output for %s: %s" % (addon, bad))
    shutil.move(tmp, addon)
    return kept, dropped, left


cob, addons = sys.argv[1], sys.argv[2:]
own = modelled(cob)
print("Cobblemon models %d species" % len(own))
for a in addons:
    sup = modelled(a)
    drop = sup & own
    print()
    print(os.path.basename(a))
    if not drop:
        print("  nothing to strip - all %d species are genuinely new" % len(sup))
        continue
    print("  duplicates Cobblemon : %s" % ", ".join(sorted(drop)))
    kept, dropped, left = strip(a, drop)
    print("  dropped %d files, kept %d" % (dropped, kept))
    print("  now supplies         : %s" % ", ".join(left))
    z = zipfile.ZipFile(a)
    leak = [n for n in z.namelist() if species_of(n) in drop]
    z.close()
    print("  leftover for dropped : %s" % (leak or "none"))
