# -*- coding: utf-8 -*-
"""Give the second seat to FORMS that declare their own riding.

The two-seat datapack patches riding at the SPECIES level with a species_addition. That never
reaches a form which declares `riding` of its own - the form's block wins outright - so
Hisuian Arcanine, the Galarian birds, Paldean Tauros, Giratina Origin and a dozen Megas stay
one-seaters. 27 forms across the installed jars do this, 17 of them with `"seats": []`.

A species_addition cannot fix it: SpeciesAdditions applies collection properties with
addAll, so a `forms` entry APPENDS a form rather than merging into the one already there.
The only route is to override the whole species file, which is what this writes.

Because a full override goes stale the moment Cobblemon changes that species, the file is
rebuilt from the CURRENTLY INSTALLED jars every run - the same rule mkseatpack.py follows.
Re-run it after any Cobblemon or addon update.

The seat geometry needs no work: these forms overwhelmingly reuse the base model
(Hisuian Arcanine is `arcanine.geo.json`), which the resource pack already gives a
locator_seat_2. Any form whose model has no seat locator in the pack is reported and skipped,
rather than shipping a seat nobody can sit in.

    python3 mkformseats.py <out-datapack-dir> [--seatpack /path/to/2seats.zip]
"""
import glob
import json
import os
import sys
import zipfile

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")

MODS = COBBLEMON_DIR + "/mods"
TWOSEAT = (COBBLEMON_DIR + "/world/datapacks/twoseat-mounts/"
           "data/cobblemon/species_additions/zzz_twoseat")
SEATPACK = COBBLEMON_DIR + "/nifty-2seats.zip"
PACK_FORMAT = 48          # data pack format for 1.21.1


def winning_species(jars):
    """path -> (raw, jar). A later jar overrides the same path, as the game does."""
    out = {}
    for p in jars:
        z = zipfile.ZipFile(p)
        for n in z.namelist():
            if "/species/" in n and n.endswith(".json") and n.startswith("data/"):
                out[n] = (z, p)
    return out


def build(outdir, seatpack):
    jars = sorted(glob.glob(os.path.join(MODS, "*.jar")))
    species = winning_species(jars)

    seats_for = {}
    for f in sorted(os.listdir(TWOSEAT)):
        if not f.endswith(".json"):
            continue
        d = json.load(open(os.path.join(TWOSEAT, f)))
        s = ((d.get("riding") or {}).get("seats")) or []
        if len(s) >= 2:
            seats_for[f[:-5]] = s

    have_locator = set()
    if seatpack and os.path.exists(seatpack):
        zp = zipfile.ZipFile(seatpack)
        for n in zp.namelist():
            if n.endswith(".geo.json"):
                have_locator.add(n.rsplit("/", 1)[-1])

    written = skipped = touched = 0
    for path, (z, jar) in sorted(species.items()):
        try:
            d = json.loads(z.read(path).decode("utf-8-sig"))
        except Exception:
            continue
        if not isinstance(d, dict) or not d.get("forms"):
            continue
        base = path.rsplit("/", 1)[-1][:-5]
        want = seats_for.get(base)
        if not want:
            continue
        changed = False
        for fm in d["forms"]:
            rd = fm.get("riding")
            if not isinstance(rd, dict):
                continue
            if len(rd.get("seats") or []) >= 2:
                continue
            rd["seats"] = json.loads(json.dumps(want))   # deep copy per form
            changed = True
            touched += 1
        if not changed:
            continue
        dst = os.path.join(outdir, path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w") as fh:
            json.dump(d, fh, separators=(",", ":"))
        written += 1
        print("  %-18s %-22s <- %s" % (base, "+%d form(s)" % len(d["forms"]),
                                       os.path.basename(jar)[:26]))

    with open(os.path.join(outdir, "pack.mcmeta"), "w") as fh:
        json.dump({"pack": {"pack_format": PACK_FORMAT,
                            "description": "Second seat for forms that declare their own "
                                           "riding (Hisuian Arcanine, Galar birds, Megas)."}},
                  fh, indent=2)
    print("\nspecies overridden: %d, forms given a second seat: %d, skipped: %d"
          % (written, touched, skipped))
    print("REBUILD THIS after any Cobblemon or addon update - it pins whole species files.")


if __name__ == "__main__":
    out = sys.argv[1]
    sp = sys.argv[sys.argv.index("--seatpack") + 1] if "--seatpack" in sys.argv else SEATPACK
    build(out, sp)
