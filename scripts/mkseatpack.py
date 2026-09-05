#!/usr/bin/env python3
"""Regenerate the 2-seat resource pack against the CURRENTLY INSTALLED jars.

Why this exists: the pack overrides model geometry, so every model it ships is pinned to
whatever the jars looked like when it was built. When a mod later fixes a model, the client
keeps rendering our stale copy - and if the mod also updated that model's TEXTURE, the UVs no
longer correspond and the Pokemon is painted from the wrong region of the sheet. That is not
hypothetical: Mega Showdown 1.9.5 shipped a new blastoise_mega geometry AND texture, and 26
of our overrides went stale in one update.

Method: for each geometry the pack overrides, take the CURRENT version from the jars and
transplant our locator_seat_2 bone(s) into it. Upstream fixes come through; our seat data is
preserved exactly.

Bones are validated against the loader's hard requirements, because a violation throws
IllegalArgumentException and the model silently vanishes on the client:
  - the parent bone must exist
  - it must appear EARLIER in the array (the loader does a single forward pass)
  - it must have a pivot (dereferenced with no null check)
A model that cannot satisfy those with the new geometry keeps our old copy and is reported,
rather than shipping something that breaks.

Run on the server, where every jar is present:
    python3 mkseatpack.py /path/to/cobblemon-2seats-resourcepack.zip [-o out.zip]
"""
import zipfile, json, sys, os, io, collections

MODS = "$COBBLEMON_DIR/mods"
SEAT_PREFIX = "locator_seat_2"


def load_jar_models():
    """archive path -> raw bytes, for every model json in every installed jar."""
    out = {}
    for f in sorted(os.listdir(MODS)):
        if not f.endswith(".jar"):
            continue
        try:
            z = zipfile.ZipFile(os.path.join(MODS, f))
        except Exception:
            continue
        for n in z.namelist():
            if n.endswith(".json") and "/models/" in n and n not in out:
                out[n] = z.read(n)
    return out


def geometry(raw):
    d = json.loads(raw.decode("utf-8-sig"))
    return d, (d.get("minecraft:geometry") or [])


def validate(bones):
    """Return a list of problems with the seat bones in this bone array."""
    problems = []
    seen = {}
    allnames = {b.get("name") for b in bones}
    for idx, b in enumerate(bones):
        nm = b.get("name")
        if nm:
            seen[nm] = idx
        if not str(nm or "").startswith(SEAT_PREFIX):
            continue
        par = b.get("parent")
        if par is None:
            continue
        if par not in allnames:
            problems.append("parent %r missing" % par)
        elif par not in seen:
            problems.append("parent %r appears after child" % par)
        elif not bones[seen[par]].get("pivot"):
            problems.append("parent %r has no pivot" % par)
    return problems


def main():
    src = sys.argv[1]
    out = "-o" in sys.argv and sys.argv[sys.argv.index("-o") + 1] or \
          os.path.join(os.path.dirname(src) or ".", "cobblemon-2seats-resourcepack-NEW.zip")

    jars = load_jar_models()
    zin = zipfile.ZipFile(src)
    stats = collections.Counter()
    refreshed, kept_stale, unfixable, upstreamed, passthru = [], [], [], [], 0

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in zin.namelist():
            if n.endswith("/"):
                continue
            raw = zin.read(n)

            if not n.endswith(".json") or "/models/" not in n:
                zout.writestr(n, raw)
                passthru += 1
                continue

            cur = jars.get(n)
            if cur is None:
                # Not shipped by any jar (base Cobblemon mon we carry ourselves).
                zout.writestr(n, raw)
                stats["not in any jar"] += 1
                continue

            try:
                ours, gours = geometry(raw)
                theirs, gtheirs = geometry(cur)
            except Exception:
                zout.writestr(n, raw)
                stats["unparseable"] += 1
                continue

            # collect our seat bones, per geometry index
            seats = {}
            for i, g in enumerate(gours):
                seats[i] = [b for b in (g.get("bones") or [])
                            if str(b.get("name") or "").startswith(SEAT_PREFIX)]

            if not any(seats.values()):
                zout.writestr(n, cur)      # nothing of ours to preserve - just take theirs
                stats["refreshed (no seat bone)"] += 1
                continue

            # if the current geometry already equals ours-minus-seats, nothing changed
            def strip(g):
                return [b for b in (g.get("bones") or [])
                        if not str(b.get("name") or "").startswith(SEAT_PREFIX)]

            same = (len(gours) == len(gtheirs) and
                    all(strip(a) == (b.get("bones") or []) and
                        a.get("description") == b.get("description")
                        for a, b in zip(gours, gtheirs)))
            if same:
                zout.writestr(n, raw)
                stats["already current"] += 1
                continue

            # If the jar's own geometry now carries a seat bone, upstream has done the job
            # and our override is obsolete for that model - take theirs untouched. Appending
            # ours on top would produce TWO bones with the same name, which is how steelix
            # and magnezone ended up with duplicates on the first pass.
            if any(str(b.get("name") or "").startswith(SEAT_PREFIX)
                   for g in gtheirs for b in (g.get("bones") or [])):
                zout.writestr(n, cur)
                stats["upstream now has a seat"] += 1
                upstreamed.append(os.path.basename(n))
                continue

            # transplant
            merged = json.loads(cur.decode("utf-8-sig"))
            gm = merged.get("minecraft:geometry") or []
            problems = []
            for i, g in enumerate(gm):
                if i not in seats or not seats[i]:
                    continue
                bones = list(g.get("bones") or [])
                bones.extend(seats[i])
                p = validate(bones)
                if p:
                    problems.extend(p)
                else:
                    g["bones"] = bones

            if problems:
                zout.writestr(n, raw)      # keep the stale-but-working copy
                unfixable.append((os.path.basename(n), problems[0]))
                stats["KEPT STALE (would break)"] += 1
            else:
                zout.writestr(n, json.dumps(merged, indent=1).encode("utf-8"))
                refreshed.append(os.path.basename(n))
                stats["REFRESHED"] += 1

    print("wrote %s" % out)
    print("  passthrough (non-model) entries: %d" % passthru)
    for k, v in sorted(stats.items()):
        print("  %-28s %d" % (k, v))
    if refreshed:
        print()
        print("refreshed from the current jars (%d):" % len(refreshed))
        for r in sorted(refreshed):
            print("   %s" % r)
    if upstreamed:
        print()
        print("upstream now ships its own seat - our override dropped (%d): %s"
              % (len(upstreamed), ", ".join(sorted(upstreamed))))
    if unfixable:
        print()
        print("KEPT STALE because the new geometry cannot take our seat bone (%d):" % len(unfixable))
        for f, why in unfixable:
            print("   %-32s %s" % (f, why))


if __name__ == "__main__":
    main()
