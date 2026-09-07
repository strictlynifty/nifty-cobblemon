# -*- coding: utf-8 -*-
"""Render Cobblemon's Bedrock models to PNG, so the wiki can show real pictures.

Cobblemon ships no 2D sprite for any Pokemon - the party screen renders the 3D model live.
The model and its textures ARE in the jar, so render them offline rather than showing UV
atlases, which are unreadable flat.

Three pieces:
  resolve()  species + aspects -> model, base texture, and texture LAYERS. This is how
             shiny, regional forms and Alcremie's decorations are all expressed: a variation
             whose `aspects` are satisfied contributes a texture or an extra layer over the
             same geometry. Later variations override earlier ones, so apply in file order.
  faces()    geometry -> model-space quads with UVs. Bedrock box UV only (no Pokemon model
             uses per-face UV), plus inflate, mirror, and bone and cube rotation.
  render()   z-buffered scanline rasteriser, cutout alpha, Lambert shading. Pure Python:
             numpy is not installed and installing it would land on the full C: drive.

Layers are sampled during the SAME rasterisation pass rather than re-rendered, so a
decoration composites exactly over the body with no depth fighting.

Usage:
  python tools/mcrender.py <jar> <species> [aspect,aspect] [-o out.png] [--size N]
                           [--yaw D] [--pitch P] [--list-aspects]
"""
import io
import json
import math
import re
import sys
import zipfile

from PIL import Image


# ---------------------------------------------------------------- resolver

class Pack(object):
    """Several mod jars as one lookup, the way the game stacks them.

    Mega and Gmax forms are not in the Cobblemon jar - they come from Mega Showdown, and
    other addons ship their own species. A later jar's file wins for the same path, and a
    species' resolver files are combined across every jar rather than one jar's set being
    picked. Quacks like ZipFile so everything downstream is unchanged.
    """

    def __init__(self, jars):
        self.zips = [j if isinstance(j, zipfile.ZipFile) else zipfile.ZipFile(j)
                     for j in jars]
        self._where = {}
        for z in self.zips:                 # later jars overwrite earlier ones
            for n in z.namelist():
                self._where[n] = z

    def namelist(self):
        return list(self._where)

    def read(self, name):
        z = self._where.get(name)
        if z is None:
            raise KeyError("There is no item named %r in the pack" % name)
        return z.read(name)



# Building these per render meant re-reading and re-parsing every resolver and every
# animation file in the jar - about 2000 JSON documents - for each of ~2000 renders. Index
# once per jar instead; it takes a batch run from hours to minutes.
_INDEX = {}


def index(z):
    key = id(z)
    if key in _INDEX:
        return _INDEX[key]
    base = "assets/cobblemon/bedrock/pokemon/"
    res, anims, posers = {}, {}, {}
    for n in sorted(z.namelist()):
        if not n.endswith(".json"):
            continue
        if "/pokemon/resolvers/" in n:
            try:
                r = json.loads(z.read(n).decode("utf-8-sig"))
            except Exception:
                continue
            sp = str(r.get("species", "")).split(":")[-1]
            if sp:
                # resolvers carry their own `order`; low order first, so a high-order file
                # from an addon (Mega Showdown) layers over the base one
                res.setdefault(sp, []).append((int(r.get("order") or 0), n, r))
        elif n.startswith(base + "animations/"):
            try:
                anims.update((json.loads(z.read(n).decode("utf-8-sig"))
                              .get("animations") or {}))
            except Exception:
                pass
        elif n.startswith(base + "posers/"):
            posers[n.rsplit("/", 1)[-1][:-5]] = n
    geos = {}
    for n in z.namelist():
        if n.endswith(".geo.json") and "/pokemon/models/" in n:
            geos[n.rsplit("/", 1)[-1][:-9]] = n
    for sp in res:
        res[sp] = [r for _o, _n, r in sorted(res[sp], key=lambda t: (t[0], t[1]))]
    _INDEX[key] = (res, anims, posers, geos)
    return _INDEX[key]



def _res_path(ref):
    """cobblemon:textures/pokemon/x.png -> assets/cobblemon/textures/pokemon/x.png"""
    ns, _, rest = ref.partition(":")
    return "assets/%s/%s" % (ns or "cobblemon", rest)


def _model_path(z, ref):
    want = ref.split(":")[-1]
    if want.endswith(".geo"):
        want = want[:-4]
    n = index(z)[3].get(want)
    if not n:
        raise KeyError("no geo for %r" % ref)
    return n


def resolve(z, species, aspects):
    """Pick model / texture / layers for a species under a set of aspects."""
    aspects = set(aspects or [])
    # Accumulate across every resolver file for the species, in order. A species can be split
    # over several: a base file with model+texture and a second holding only the female
    # texture. Treating each file independently and keeping the one that named a model threw
    # the second file's texture away, so every `female` sprite failed on a missing texture.
    cur = {}
    for r in index(z)[0].get(species, []):
        for v in r.get("variations", []):
            if not set(v.get("aspects") or []) <= aspects:
                continue
            for k in ("model", "texture", "poser"):
                if v.get(k):
                    cur[k] = v[k]
            if "layers" in v:
                # A matching variation REPLACES the layer set rather than adding to it.
                # That is what stops all seven decorations stacking on one Alcremie.
                cur["layers"] = v["layers"]
    if not cur.get("model") or not cur.get("texture"):
        raise KeyError("no usable variation for %s %s" % (species, sorted(aspects)))
    return cur


def pose_for(z, species, poser_ref=None):
    """The resting transforms of the pose the party screen shows.

    Rendering the bind pose alone is wrong for a lot of Pokemon: Bulbasaur's Vine Whip bones
    lie flat out to x=+-34 until an animation tucks them in, so it renders with two green
    spears through it. The poser names a pose whose poseTypes include PROFILE, that pose
    names a bedrock animation, and the animation's first frame is what puts every bone where
    the GUI shows it.

    MoLang expressions are not evaluated - they are all of the form math.sin(q.anim_time*...),
    the idle breathing, which is 0 at rest (1 for scale). That is exactly the resting pose.
    """
    _res, anims, posers, _geo = index(z)
    want = (poser_ref or species).split(":")[-1]
    pf = posers.get(want)
    if not pf:
        return {}
    try:
        p = json.loads(z.read(pf).decode("utf-8-sig"))
    except Exception:
        return {}
    poses = p.get("poses") or {}
    pick = None
    for key in ("PROFILE", "STAND", "NONE"):
        pick = next((v for v in poses.values() if key in (v.get("poseTypes") or [])), None)
        if pick:
            break
    if not pick and poses:
        pick = list(poses.values())[0]
    if not pick:
        return {}
    names = []
    for a in (pick.get("animations") or []):
        m = re.findall(r"bedrock\w*\(\s*'([^']+)'\s*,\s*'([^']+)'", str(a))
        names += ["animation.%s.%s" % (g, h) for g, h in m]
    def first(val, dflt):
        if isinstance(val, dict):                      # keyframed: take the earliest
            if not val:
                return dflt
            k = sorted(val, key=lambda s: float(s) if _num(s) else 0.0)[0]
            val = val[k]
            if isinstance(val, dict):
                val = val.get("pre") or val.get("post") or dflt
        if not isinstance(val, list):
            return dflt
        return [float(c) if isinstance(c, (int, float)) else d
                for c, d in zip(val, dflt)]

    out = {}
    for nm in names:
        for bone, ch in ((anims.get(nm) or {}).get("bones") or {}).items():
            cur = out.setdefault(bone, {"position": [0.0] * 3,
                                        "rotation": [0.0] * 3,
                                        "scale": [1.0] * 3})
            for key, dflt in (("position", [0.0] * 3), ("rotation", [0.0] * 3),
                              ("scale", [1.0] * 3)):
                if key in ch:
                    cur[key] = first(ch[key], dflt)
    return out


def _num(s):
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def list_aspects(z, species):
    out = set()
    for r in index(z)[0].get(species, []):
        for v in r.get("variations", []):
            for a in (v.get("aspects") or []):
                out.add(a)
    return sorted(out)


# ---------------------------------------------------------------- math

def rot(axis, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    if axis == 0:
        return ((1, 0, 0), (0, c, -s), (0, s, c))
    if axis == 1:
        return ((c, 0, s), (0, 1, 0), (-s, 0, c))
    return ((c, -s, 0), (s, c, 0), (0, 0, 1))


def mm(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
                 for i in range(3))


def mv(m, v):
    return tuple(sum(m[i][k] * v[k] for k in range(3)) for i in range(3))


def euler(r):
    """Bedrock rotation -> a right-handed matrix: order Z, Y, X, with Y and Z NEGATED.

    Bedrock's Y/Z sense is opposite to the right-handed convention used here. Pokemon with
    one or two rotated bones look almost right either way - Pikachu did - so the giveaway is
    a deep chain, where the error compounds: Alcremie's head swirl (base -> mid -> bend ->
    tip) flings pieces clear of the model under every other convention.
    """
    return mm(rot(2, -r[2]), mm(rot(1, -r[1]), rot(0, r[0])))


# ---------------------------------------------------------------- geometry

# Bedrock box-UV net. Vertex index bits: 1 = +x, 2 = +y, 4 = +z.
FACES = [
    ('up',    lambda w, h, d: (d, 0),           lambda w, h, d: (w, d),
     (2, 3, 7, 6), (0, 1, 0)),
    ('down',  lambda w, h, d: (d + w, 0),       lambda w, h, d: (w, d),
     (4, 5, 1, 0), (0, -1, 0)),
    ('east',  lambda w, h, d: (0, d),           lambda w, h, d: (d, h),
     (5, 7, 3, 1), (1, 0, 0)),
    ('north', lambda w, h, d: (d, d),           lambda w, h, d: (w, h),
     (4, 5, 7, 6), (0, 0, -1)),
    ('west',  lambda w, h, d: (d + w, d),       lambda w, h, d: (d, h),
     (0, 2, 6, 4), (-1, 0, 0)),
    ('south', lambda w, h, d: (d + w + d, d),   lambda w, h, d: (w, h),
     (1, 3, 2, 0), (0, 0, 1)),
]


def faces(geo, pose=None):
    """Flatten a geometry into model-space quads with normalised UVs.

    `pose` (from pose_for) is applied on top of the bind pose: animation rotation ADDS to the
    bone's own rotation, scale is about the pivot, position is a plain offset.
    """
    desc = geo.get("description") or {}
    tw = float(desc.get("texture_width") or 64)
    th = float(desc.get("texture_height") or 64)
    bones = {b["name"]: b for b in geo.get("bones", [])}
    cache = {}
    pose = pose or {}

    def bone_tf(name, seen=()):
        """(rotation, translation) taking bone-local coords into model space."""
        if name in cache:
            return cache[name]
        b = bones.get(name)
        ident = (((1, 0, 0), (0, 1, 0), (0, 0, 1)), (0.0, 0.0, 0.0))
        if b is None or name in seen:
            return ident
        piv = b.get("pivot") or [0, 0, 0]
        br = list(b.get("rotation") or [0, 0, 0])
        ap = (pose or {}).get(b["name"]) or {}
        ar = ap.get("rotation") or [0, 0, 0]
        sc = ap.get("scale") or [1, 1, 1]
        off = ap.get("position") or [0, 0, 0]
        r = euler([br[i] + ar[i] for i in range(3)])
        r = tuple(tuple(r[i][j] * sc[j] for j in range(3)) for i in range(3))
        rp = mv(r, piv)
        t = tuple(piv[i] - rp[i] + off[i] for i in range(3))
        if b.get("parent"):
            pr, pt = bone_tf(b["parent"], seen + (name,))
            t = tuple(mv(pr, t)[i] + pt[i] for i in range(3))
            r = mm(pr, r)
        cache[name] = (r, t)
        return r, t

    out = []
    for b in geo.get("bones", []):
        r, t = bone_tf(b["name"])
        for c in (b.get("cubes") or []):
            o = c.get("origin") or [0, 0, 0]
            s = c.get("size") or [0, 0, 0]
            inf = float(c.get("inflate") or 0)
            x0, y0, z0 = (o[0] - inf, o[1] - inf, o[2] - inf)
            w, h, d = (s[0] + 2 * inf, s[1] + 2 * inf, s[2] + 2 * inf)
            corners = [(x0 + (w if i & 1 else 0),
                        y0 + (h if i & 2 else 0),
                        z0 + (d if i & 4 else 0)) for i in range(8)]
            cr = None
            if c.get("rotation"):
                cr = euler(c["rotation"])
                cp = c.get("pivot") or [0, 0, 0]
                corners = [tuple(mv(cr, tuple(p[k] - cp[k] for k in range(3)))[k] + cp[k]
                                 for k in range(3)) for p in corners]
            corners = [tuple(mv(r, p)[k] + t[k] for k in range(3)) for p in corners]

            uv = c.get("uv") or [0, 0]
            mirror = bool(c.get("mirror"))
            uw, uh, ud = s[0], s[1], s[2]      # UV uses the UNINFLATED size
            for key, off, span, idx, nrm in FACES:
                ox, oy = off(uw, uh, ud)
                sw, sh = span(uw, uh, ud)
                u0, v0 = uv[0] + ox, uv[1] + oy
                quad = [corners[i] for i in idx]
                uvs = [(u0, v0), (u0 + sw, v0), (u0 + sw, v0 + sh), (u0, v0 + sh)]
                if key in ('up', 'down'):
                    uvs = [uvs[3], uvs[2], uvs[1], uvs[0]]
                if mirror:
                    uvs = [(2 * u0 + sw - u, v) for u, v in uvs]
                n = mv(r, mv(cr, nrm)) if cr is not None else mv(r, nrm)
                out.append((quad, [(u / tw, v / th) for u, v in uvs], n))
    return out


# ---------------------------------------------------------------- raster

def render(quads, textures, size=256, yaw=30.0, pitch=12.0, ss=2, bg=(0, 0, 0, 0)):
    """Orthographic, z-buffered, cutout alpha. textures = [base, layer, ...] as RGBA."""
    w = h = size * ss
    cam = mm(rot(0, pitch), rot(1, yaw))
    pts = [mv(cam, p) for q, _, _ in quads for p in q]
    if not pts:
        raise ValueError("nothing to draw")
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    ext = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    sc = (w * 0.88) / ext

    def project(p):
        v = mv(cam, p)
        return ((v[0] - cx) * sc + w / 2.0, h / 2.0 - (v[1] - cy) * sc, v[2])

    px = [t.load() for t in textures]
    dims = [t.size for t in textures]
    buf = [bg] * (w * h)
    zbuf = [1e30] * (w * h)
    # Minecraft shades by which way a face points, not by a light source. Lambert made
    # everything muddy - Vulpix came out brown instead of orange. These are the game's own
    # per-direction factors, so a render reads the way the model does in-game.
    SHADE = {'+y': 1.0, '-y': 0.62, '+z': 0.88, '-z': 0.88, '+x': 0.76, '-x': 0.76}

    for quad, uvs, nrm in quads:
        ax = max(range(3), key=lambda i: abs(nrm[i]))
        shade = SHADE['%s%s' % ('+' if nrm[ax] >= 0 else '-', 'xyz'[ax])]
        p = [project(v) for v in quad]
        for a, b, c in ((0, 1, 2), (0, 2, 3)):
            tri = (p[a], p[b], p[c])
            tuv = (uvs[a], uvs[b], uvs[c])
            x0 = max(0, int(min(t[0] for t in tri)))
            x1 = min(w - 1, int(max(t[0] for t in tri)) + 1)
            y0 = max(0, int(min(t[1] for t in tri)))
            y1 = min(h - 1, int(max(t[1] for t in tri)) + 1)
            if x1 < x0 or y1 < y0:
                continue
            (ax, ay, az), (bx, by, bz), (ex, ey, ez) = tri
            det = (by - ey) * (ax - ex) + (ex - bx) * (ay - ey)
            if abs(det) < 1e-9:
                continue
            for y in range(y0, y1 + 1):
                yc = y + 0.5
                row = y * w
                for x in range(x0, x1 + 1):
                    xc = x + 0.5
                    w0 = ((by - ey) * (xc - ex) + (ex - bx) * (yc - ey)) / det
                    if w0 < 0.0 or w0 > 1.0:
                        continue
                    w1 = ((ey - ay) * (xc - ex) + (ax - ex) * (yc - ey)) / det
                    if w1 < 0.0 or w0 + w1 > 1.0:
                        continue
                    w2 = 1.0 - w0 - w1
                    z = w0 * az + w1 * bz + w2 * ez
                    i = row + x
                    if z >= zbuf[i]:
                        continue
                    u = w0 * tuv[0][0] + w1 * tuv[1][0] + w2 * tuv[2][0]
                    v = w0 * tuv[0][1] + w1 * tuv[1][1] + w2 * tuv[2][1]
                    r = g = bb = al = 0.0
                    for k in range(len(px)):
                        twk, thk = dims[k]
                        sx = min(twk - 1, max(0, int(u * twk)))
                        sy = min(thk - 1, max(0, int(v * thk)))
                        pr, pg, pb, pa = px[k][sx, sy]
                        if not pa:
                            continue
                        a2 = pa / 255.0
                        r = pr * a2 + r * (1 - a2)
                        g = pg * a2 + g * (1 - a2)
                        bb = pb * a2 + bb * (1 - a2)
                        al = a2 + al * (1 - a2)
                    if al < 0.5:
                        continue
                    zbuf[i] = z
                    buf[i] = (int(r * shade), int(g * shade), int(bb * shade), 255)

    im = Image.new("RGBA", (w, h))
    im.putdata(buf)
    return im.resize((size, size), Image.LANCZOS)


def draw(jar, species, aspects=(), size=256, yaw=30.0, pitch=12.0, ss=2):
    if isinstance(jar, (list, tuple)):
        jar = Pack(jar)
    z = jar if hasattr(jar, "namelist") else zipfile.ZipFile(jar)
    r = resolve(z, species, aspects)
    geo = json.loads(z.read(_model_path(z, r["model"])).decode("utf-8-sig"))
    quads = faces(geo["minecraft:geometry"][0], pose_for(z, species, r.get("poser")))
    refs = [r["texture"]] + [l["texture"] for l in (r.get("layers") or [])]
    # An animated layer - Charizard's tail flame, Rotom's arcs - gives {"frames":[...]}
    # instead of a path. Take the first frame; a still image needs exactly one.
    refs = [t["frames"][0] if isinstance(t, dict) else t for t in refs]
    texs = [Image.open(io.BytesIO(z.read(_res_path(t)))).convert("RGBA") for t in refs]
    return render(quads, texs, size=size, yaw=yaw, pitch=pitch, ss=ss), r, len(quads)


if __name__ == "__main__":
    jar, species = sys.argv[1], sys.argv[2]
    rest = sys.argv[3:]
    if "--list-aspects" in rest:
        print("\n".join(list_aspects(zipfile.ZipFile(jar), species)))
        raise SystemExit
    asp = [a for a in (rest[0].split(",")
                       if rest and not rest[0].startswith("-") else []) if a]

    def opt(name, d, cast=float):
        return cast(rest[rest.index(name) + 1]) if name in rest else d

    out = rest[rest.index("-o") + 1] if "-o" in rest else "render.png"
    im, meta, nq = draw(jar, species, asp, size=opt("--size", 256, int),
                        yaw=opt("--yaw", 30.0), pitch=opt("--pitch", 12.0))
    im.save(out)
    print("%s %s -> %s  (%d quads, %d layers)"
          % (species, asp or "[]", out, nq, len(meta.get("layers") or [])))
