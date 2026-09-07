#!/usr/bin/env python3
"""Client resource pack of Gigantamax fixes. Supersedes nifty-halo-tuning.zip.

Mega Showdown ships animation clips for its Gigantamax models that the posers never
reference, so the models play their idle while walking, flying or sleeping. Three species are
affected; the other 29 cover every clip they have.

  blastoise    ships ground_walk, ground_run, water_idle, water_swim, surfacewater_idle,
               surfacewater_swim and sleep, and its poser defines exactly two poses. With no
               WALK pose it plays ground_idle while moving, which reads as walking diagonally.
               ground_run is the shell spin.
  corviknight  has four poses and ALL FOUR play ground_idle - including `fly` and `walking` -
               while air_fly and ground_walk go unused and there is no sleep pose at all.
  cinderace    its poser's animation expressions are written `bedrock(cinderacegmax, x)`
               rather than `q.bedrock('cinderacegmax', 'x')`. That looks like a genuine
               upstream typo, but it is NOT touched here: it is unverified in game, and
               rewriting someone's expressions on a guess is how the last round went wrong.

Structure is copied from Cobblemon's OWN base posers for the same species, not invented:
sprinting is a second WALK pose carrying a `q.is_sprinting` condition, because PoseType has no
RUN value. Ride-specific clips (ride_ground_run and friends) do not exist for these gmax
models, so a ridden Pokemon falls through to the same walk/run poses - which is what is wanted
here anyway.

Every clip referenced below is checked against the animation file before being written; a pose
whose clip is missing is skipped and reported rather than emitted.
"""
import zipfile, json, os, sys, hashlib

JAR = sys.argv[1] if len(sys.argv) > 1 else "X:/claude-tmp/scratch/blast/msd195.jar"
OUT = sys.argv[2] if len(sys.argv) > 2 else "X:/cobblemon-ops/client/pending/nifty-gmax-fixes.zip"

GMAX = """alcremie appletun blastoise butterfree centiskorch charizard cinderace coalossal
copperajah corviknight drednaw duraludon eevee flapple garbodor gengar grimmsnarl hatterene
inteleon kingler lapras machamp melmetal meowth orbeetle pikachu rillaboom sandaconda snorlax
toxtricity urshifu venusaur""".split()

# poser -> list of (pose name, poseTypes, condition or None, clip)
# Modelled on Cobblemon's base posers for the same species.
WANTED = {
    "blastoisegmax": [
        ("walk",                ["WALK"],           "!q.is_sprinting", "ground_walk"),
        ("run",                 ["WALK"],           "q.is_sprinting",  "ground_run"),
        ("surfacewater-float",  ["STAND", "FLOAT"], None,              "surfacewater_idle"),
        # !q.is_ridden matches Cobblemon's own base Blastoise poser. Without it this and the
        # plain `swim` pose both claim SWIM unconditionally, which is ambiguous - base avoids
        # exactly that by conditioning the surface variant.
        ("surfacewater-swim",   ["WALK", "SWIM"],   "!q.is_ridden",    "surfacewater_swim"),
        ("float",               ["FLOAT"],          None,              "water_idle"),
        ("swim",                ["SWIM"],           None,              "water_swim"),
        ("sleep",               ["SLEEP"],          None,              "sleep"),
    ],
    # These three REPLACE existing poses that all play ground_idle.
    "corviknight_gmax": [
        ("walking",             ["WALK"],           "!q.is_sprinting", "ground_walk"),
        ("fly",                 ["FLY", "SWIM"],    None,              "air_fly"),
        ("sleep",               ["SLEEP"],          None,              "sleep"),
    ],
}
# Poses we deliberately overwrite because the shipped version points at the wrong clip.
REPLACE = {"corviknight_gmax": {"walking", "fly"}}

z = zipfile.ZipFile(JAR)


def find(base, kind):
    for n in z.namelist():
        if n.endswith("/" + base) and kind in n:
            return n
    return None


def load(base, kind):
    n = find(base, kind)
    return (json.loads(z.read(n).decode("utf-8-sig")), n) if n else (None, None)


def build(poser):
    d, path = load(poser + ".json", "/posers/")
    ad, _ = load(poser + ".animation.json", "/animations/")
    if d is None or ad is None:
        print("   %-20s SKIP - poser or animation file not found" % poser)
        return None, None
    clips = {k.split(".")[-1] for k in (ad.get("animations") or {})}
    quirk = "q.bedrock_quirk('%s', 'blink')" % poser if "blink" in clips else None
    covered = {t for p in (d.get("poses") or {}).values() for t in (p.get("poseTypes") or [])}
    replaceable = REPLACE.get(poser, set())

    added, skipped = [], []
    for name, types, cond, clip in WANTED[poser]:
        if clip not in clips:
            skipped.append("%s (no %s clip)" % (name, clip))
            continue
        existing = name in (d.get("poses") or {})
        if existing and name not in replaceable:
            skipped.append("%s (already defined)" % name)
            continue
        # Do not claim a poseType that is already served, unless we are deliberately
        # replacing that pose or the new one is distinguished by a condition.
        if not existing and cond is None and any(t in covered for t in types):
            skipped.append("%s (%s already covered)" % (name, "/".join(types)))
            continue
        pose = {"poseTypes": types,
                "animations": ["q.look('head')", "q.bedrock('%s', '%s')" % (poser, clip)]}
        if cond:
            pose["condition"] = cond
        if quirk:
            pose["quirks"] = [quirk]
        d.setdefault("poses", {})[name] = pose
        added.append("%s->%s" % (name, clip))

    print("   %-20s root=%-16s added: %s" % (poser, d.get("rootBone"), ", ".join(added) or "none"))
    for s in skipped:
        print("        skipped %s" % s)
    return path, d


os.makedirs(os.path.dirname(OUT), exist_ok=True)
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as out:
    out.writestr("pack.mcmeta", json.dumps({
        # 34 = RESOURCE pack format for 1.21.1. 48 is the datapack number, and using it makes
        # the game reject the pack as "made for a different version" - silently doing nothing.
        "pack": {"pack_format": 34,
                 "description": "strictlynifty - Gigantamax fixes"}}, indent=1))

    print("posers:")
    for poser in WANTED:
        path, patched = build(poser)
        if path:
            out.writestr(path, json.dumps(patched, indent=1))

    print("halo sizers:")
    existing = {}
    for n in z.namelist():
        if "/msd_sizer/" in n and n.endswith(".json"):
            d = json.loads(z.read(n).decode("utf-8-sig"))
            existing[str(d.get("pokemon", "")).lower()] = d
    kept = 0
    for sp in GMAX:
        body = existing.get(sp) or {
            "pokemon": sp,
            "_comment": "UNTUNED - identity transform, adjust and reload with F3+T",
            "size_config": {"Gmax": {"msd:dmax": {"scale": [1.0, 1.0, 1.0],
                                                  "translate": [0.0, 0.0, 0.0],
                                                  "rotation": [0.0, 0.0, 0.0]}}}}
        out.writestr("assets/mega_showdown/msd_sizer/%s_clouds.json" % sp,
                     json.dumps(body, indent=1))
        kept += sp in existing
    print("   %d files, %d carrying the mod's own values" % (len(GMAX), kept))

print()
print("wrote %s (%.0f KB)  sha256 %s"
      % (OUT, os.path.getsize(OUT) / 1024,
         hashlib.sha256(open(OUT, "rb").read()).hexdigest()[:16]))
zz = zipfile.ZipFile(OUT)
print("  integrity %s, %d entries" % ("OK" if zz.testzip() is None else "BAD", len(zz.namelist())))
