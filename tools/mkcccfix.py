#!/usr/bin/env python3
"""Rebuild CCCwLegendSpawns without the Blastoise Gigantamax half-override.

Mega Showdown 1.9.3 shipped its Blastoise gmax resolver as `3_blastoise_gigantamax.json`, and
this pack overrode that exact path - so the pack's own model, poser, animation and texture all
won together as a consistent set. 1.9.5 renamed the mod's file to `3_blastoise_gmax.json`.
The pack's file is no longer an override but an ADDITIONAL resolver, and since `gigantamax`
sorts before `gmax` the mod's loads last and wins the model slot. The pack still wins the
TEXTURE, because both write the same path.

The result is the mod's 112-bone `geometry.blastoise` painted with a texture drawn for the
pack's 59-bone `geometry.gmax_blastoise`. Different UV layouts, so every part samples the
wrong region - Blastoise renders shell-brown from head to foot.

Note this is not about resolution. A 256 texture on a 512 UV space is fine on its own;
Bedrock scales the image to the declared space, which is how HD packs work. The fault is the
model and texture coming from different SOURCES, having been authored against different
geometry.

Fix: drop the pack's entire Blastoise gmax set so all of it comes from the jar. Everything
else in the pack is left exactly as it is.
"""
import zipfile, os, sys, hashlib

SRC = sys.argv[1] if len(sys.argv) > 1 else "X:/claude-tmp/scratch/nested/resourcepacks/CCCwLegendSpawns_2.1.zip"
OUT = sys.argv[2] if len(sys.argv) > 2 else "X:/cobblemon-ops/client/pending/CCCwLegendSpawns_2.1.zip"

# The pack's Blastoise gmax set. All were authored as a unit against the pack's own geometry;
# keeping any of them alongside the mod's model reintroduces the mismatch.
DROP = {
    "assets/cobblemon/bedrock/pokemon/resolvers/0009_blastoise/3_blastoise_gigantamax.json",
    "assets/cobblemon/bedrock/pokemon/models/0009_blastoise/blastoise_gigantamax.geo.json",
    "assets/cobblemon/bedrock/pokemon/posers/0009_blastoise/blastoisegmax.json",
    "assets/cobblemon/bedrock/pokemon/animations/0009_blastoise/blastoisegmax.animation.json",
    "assets/cobblemon/textures/pokemon/0009_blastoise/blastoise_gigantamax.png",
    "assets/cobblemon/textures/pokemon/0009_blastoise/blastoise_gigantamax_shiny.png",
    "assets/cobblemon/textures/pokemon/0009_blastoise/blastoise_gigantamax_emissive.png",

    # Latios BASE form, same shape of fault. The jar's 0_latios_base.json (which the pack does
    # not override) asks for poser cobblemon:latios, model latios2.geo and texture latios.png.
    # The pack replaces the first three and not the texture, so the pack's geometry gets the
    # jar's skin. Dropping its three puts the whole base form back on the jar.
    # This matters because a Latios can be redeemed from a card even though none is currently
    # in anyone's party or PC.
    "assets/cobblemon/bedrock/pokemon/models/0381_latios/latios2.geo.json",
    "assets/cobblemon/bedrock/pokemon/posers/0381_latios/latios.json",
    "assets/cobblemon/bedrock/pokemon/animations/0381_latios/latios2.animation.json",
}

# NOT dropped, deliberately: the nine Pikachu splits. Every one needs `region-bias-alola` or a
# cosplay form, whose textures come from Mega Showdown's built-in regionbias resourcepack while
# the pack supplies the geometry. Removing the pack's Pikachu geometry would repair those but
# strand the cosplay textures the pack ships alongside them, trading nine niche splits for a
# different set. Plain gmax Pikachu is unaffected: the pack supplies BOTH halves there.

zin = zipfile.ZipFile(SRC)
present = set(zin.namelist())
missing = DROP - present
if missing:
    print("WARNING: expected to drop these but they are not in the pack:")
    for m in sorted(missing):
        print("   %s" % m)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
dropped, kept = [], 0
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zout:
    for n in zin.namelist():
        if n.endswith("/"):
            continue
        if n in DROP:
            dropped.append(n)
            continue
        zout.writestr(n, zin.read(n))
        kept += 1

print("wrote %s" % OUT)
print("  kept    %d entries" % kept)
print("  dropped %d:" % len(dropped))
for d in sorted(dropped):
    print("     %s" % d.split("0009_blastoise/")[-1])
print("  size    %.1f MB" % (os.path.getsize(OUT) / 1048576))
print("  sha256  %s" % hashlib.sha256(open(OUT, "rb").read()).hexdigest()[:16])
z = zipfile.ZipFile(OUT)
print("  zip integrity: %s" % ("OK" if z.testzip() is None else "BAD"))
print("  pack.mcmeta preserved: %s" % ("pack.mcmeta" in z.namelist()))
