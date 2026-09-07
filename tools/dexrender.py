# -*- coding: utf-8 -*-
"""Render the whole Pokedex to sprite atlases for the wiki.

Renders every species, its shiny, and its regional/gender forms with tools/mcrender.py, then
packs the lot into a handful of atlas sheets plus a JSON manifest. Atlases rather than a file
per sprite: ~2000 loose PNGs is a bad thing to put in a git repo and a worse thing to fetch
over HTTP, and embedding them in mc-wiki.html would take the page past 20 MB.

Two stages so a long run is resumable - a crash or a stop only loses the sprite in flight:

    python tools/dexrender.py render <jar> [--jobs N] [--size N] [--limit N]
    python tools/dexrender.py pack   <outdir> [--size N] [--per-sheet N]

`render` writes one PNG per sprite under the work directory and skips any that already
exist. `pack` builds the sheets and manifest from whatever is there.
"""
import io
import json
import multiprocessing
import os
import sys
import time

WORK = os.environ.get("DEXWORK", "X:/claude-tmp/dexpng")

# Every aspect gets a sprite - patterns, cosmetics, region bias, mega, gmax - each on its
# own and again shiny. What keeps that from exploding is deduping on APPEARANCE: an aspect
# that resolves to the same model, texture and layers as one already rendered is skipped, so
# the ~3800 candidates collapse to the ~3700 that actually look different. Mega and Gmax live
# in Mega Showdown rather than the Cobblemon jar, hence the whole-pack lookup.


def _mr():
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location("mr", os.path.join(here, "mcrender.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def key_of(species, aspects):
    return "|".join([species] + sorted(aspects))


def jars_in(path):
    import glob
    import os as _os
    if _os.path.isdir(path):
        return sorted(glob.glob(_os.path.join(path, "*.jar")))
    return [path]


def jobs_for(path):
    """(species, aspects) for every distinct appearance across the whole mod pack."""
    mr = _mr()
    pk = mr.Pack(jars_in(path))
    res = mr.index(pk)[0]
    out = []
    for sp in sorted(res):
        asp = [a for a in mr.list_aspects(pk, sp) if a != "shiny"]
        cands = [[], ["shiny"]] + [[a] for a in asp] + [[a, "shiny"] for a in asp]
        seen = set()
        for c in cands:
            try:
                r = mr.resolve(pk, sp, set(c))
            except Exception:
                continue           # an aspect naming a texture that does not exist
            sig = (str(r.get("model")), str(r.get("texture")),
                   str([l.get("texture") for l in (r.get("layers") or [])]))
            if sig in seen:
                continue           # this aspect does not change how it looks
            seen.add(sig)
            out.append((sp, c))
    return out


_Z = None
_MR = None


def _init(jar):
    global _Z, _MR
    _MR = _mr()
    _Z = _MR.Pack(jars_in(jar))
    _MR.index(_Z)          # pay the indexing cost once per worker, not once per sprite


def _one(job):
    sp, aspects, size = job
    k = key_of(sp, aspects)
    path = os.path.join(WORK, k.replace("|", "__") + ".png")
    if os.path.exists(path):
        return (k, "skip")
    try:
        im, _, _ = _MR.draw(_Z, sp, aspects, size=size, ss=2)
        bb = im.getbbox()
        if bb:
            im = im.crop(bb)
        from PIL import Image
        alpha = im.getchannel("A")
        q = im.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=255)
        pal = (q.getpalette() or [])
        q.putpalette(pal + [0] * (768 - len(pal)))
        q.paste(255, mask=alpha.point(lambda a: 255 if a < 128 else 0))
        buf = io.BytesIO()
        q.save(buf, "PNG", optimize=True, transparency=255)
        with open(path, "wb") as f:
            f.write(buf.getvalue())
        return (k, "ok")
    except Exception as e:
        return (k, "FAIL %s" % e)


def cmd_render(jar, njobs, size, limit):
    os.makedirs(WORK, exist_ok=True)
    js = jobs_for(jar)
    if limit:
        js = js[:limit]
    todo = [(sp, a, size) for sp, a in js]
    print("sprites to render: %d   workers: %d   size: %d" % (len(todo), njobs, size))
    t0 = time.time()
    done = fail = skip = 0
    fails = []
    with multiprocessing.Pool(njobs, initializer=_init, initargs=(jar,)) as pool:
        for i, (k, st) in enumerate(pool.imap_unordered(_one, todo, chunksize=4), 1):
            if st == "ok":
                done += 1
            elif st == "skip":
                skip += 1
            else:
                fail += 1
                fails.append((k, st))
            if i % 100 == 0 or i == len(todo):
                el = time.time() - t0
                rate = i / el if el else 0
                print("  %5d/%d  ok=%d skip=%d fail=%d  %.1f/s  eta %.0fs"
                      % (i, len(todo), done, skip, fail, rate,
                         (len(todo) - i) / rate if rate else 0), flush=True)
    print("rendered %d, skipped %d, failed %d in %.0fs" % (done, skip, fail, time.time() - t0))
    for k, st in fails[:25]:
        print("   FAIL %-40s %s" % (k, st[:80]))


def cmd_pack(outdir, tile, per_sheet):
    from PIL import Image
    os.makedirs(outdir, exist_ok=True)
    files = sorted(f for f in os.listdir(WORK) if f.endswith(".png"))
    cols = int(per_sheet ** 0.5)
    rows = (per_sheet + cols - 1) // cols
    sheets, manifest = [], {}
    sheet = None
    for i, f in enumerate(files):
        slot = i % per_sheet
        if slot == 0:
            sheet = Image.new("RGBA", (cols * tile, rows * tile), (0, 0, 0, 0))
            sheets.append(sheet)
        im = Image.open(os.path.join(WORK, f)).convert("RGBA")
        im.thumbnail((tile, tile), Image.LANCZOS)
        cx = (slot % cols) * tile + (tile - im.width) // 2
        cy = (slot // cols) * tile + (tile - im.height)      # sit on the cell floor
        sheet.alpha_composite(im, (cx, cy))
        manifest[f[:-4].replace("__", "|")] = [len(sheets) - 1, slot % cols, slot // cols]
    total = 0
    for i, sh in enumerate(sheets):
        p = os.path.join(outdir, "dex%02d.png" % i)
        alpha = sh.getchannel("A")
        q = sh.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=255)
        pal = (q.getpalette() or [])
        q.putpalette(pal + [0] * (768 - len(pal)))
        q.paste(255, mask=alpha.point(lambda a: 255 if a < 128 else 0))
        q.save(p, "PNG", optimize=True, transparency=255)
        total += os.path.getsize(p)
    meta = {"tile": tile, "cols": cols, "rows": rows,
            "sheets": ["dex%02d.png" % i for i in range(len(sheets))], "map": manifest}
    with open(os.path.join(outdir, "dex.json"), "w") as f:
        json.dump(meta, f, separators=(",", ":"), sort_keys=True)
    print("packed %d sprites into %d sheets, %.1f MB total"
          % (len(manifest), len(sheets), total / 1048576.0))
    print("manifest: %s" % os.path.join(outdir, "dex.json"))


if __name__ == "__main__":
    a = sys.argv[1:]

    def opt(name, d, cast=int):
        return cast(a[a.index(name) + 1]) if name in a else d

    if a and a[0] == "render":
        cmd_render(a[1], opt("--jobs", max(1, (os.cpu_count() or 4) - 2)),
                   opt("--size", 112), opt("--limit", 0))
    elif a and a[0] == "pack":
        cmd_pack(a[1], opt("--size", 96), opt("--per-sheet", 100))
    else:
        print(__doc__)
