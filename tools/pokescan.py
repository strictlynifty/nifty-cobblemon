# -*- coding: utf-8 -*-
"""List Pokemon entities of one species in a box, with their choice-feature values.

Written for the Alcremie gallery: spawn all 63 decoration/cream combinations, let the
players kill the ones they want, then diff this scan against the full set to find out which
they picked. Reading the saved entity chunks rather than asking with a selector means the
answer does not depend on which entity happened to be nearest at the moment of the query.

Aspects like decoration/cream live in Pokemon.Features as
    {"cobblemon:feature_id": "cream", cream: "rainbow_swirl"}
NOT in FormId - FormId is derived and collapses "rainbow_swirl" to "rainbowswirl", losing
the distinction the feature actually carries. Read the feature.

Usage: python3 pokescan.py <species> <x0> <x1> <z0> <z1> [world]
"""
import struct, zlib, gzip, sys, os, json

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")

SPECIES = sys.argv[1]
X0, X1, Z0, Z1 = (int(a) for a in sys.argv[2:6])
WORLD = sys.argv[6] if len(sys.argv) > 6 else COBBLEMON_DIR + "/world"
REG = os.path.join(WORLD, "entities")


def rd(b, p, t):
    if t == 1: return struct.unpack_from('>b', b, p)[0], p + 1
    if t == 2: return struct.unpack_from('>h', b, p)[0], p + 2
    if t == 3: return struct.unpack_from('>i', b, p)[0], p + 4
    if t == 4: return struct.unpack_from('>q', b, p)[0], p + 8
    if t == 5: return struct.unpack_from('>f', b, p)[0], p + 4
    if t == 6: return struct.unpack_from('>d', b, p)[0], p + 8
    if t == 8:
        l = struct.unpack_from('>H', b, p)[0]; p += 2
        return b[p:p + l].decode('utf8', 'replace'), p + l
    if t == 7:
        n = struct.unpack_from('>i', b, p)[0]; p += 4
        return b[p:p + n], p + n
    if t == 11:
        n = struct.unpack_from('>i', b, p)[0]; p += 4
        return list(struct.unpack_from('>%di' % n, b, p)), p + 4 * n
    if t == 12:
        n = struct.unpack_from('>i', b, p)[0]; p += 4
        return list(struct.unpack_from('>%dq' % n, b, p)), p + 8 * n
    if t == 9:
        it = b[p]; p += 1
        n = struct.unpack_from('>i', b, p)[0]; p += 4
        o = []
        for _ in range(n):
            v, p = rd(b, p, it); o.append(v)
        return o, p
    if t == 10:
        o = {}
        while True:
            tt = b[p]; p += 1
            if tt == 0: return o, p
            l = struct.unpack_from('>H', b, p)[0]; p += 2
            nm = b[p:p + l].decode('utf8', 'replace'); p += l
            v, p = rd(b, p, tt); o[nm] = v
    raise ValueError('nbt tag %d' % t)


def parse(raw):
    l = struct.unpack_from('>H', raw, 1)[0]
    return rd(raw, 3 + l, 10)[0]


def chunk(cx, cz):
    fp = os.path.join(REG, 'r.%d.%d.mca' % (cx >> 5, cz >> 5))
    if not os.path.exists(fp):
        return None
    with open(fp, 'rb') as f:
        f.seek(((cx & 31) + (cz & 31) * 32) * 4)
        e = f.read(4)
        pos = (e[0] << 16 | e[1] << 8 | e[2]) * 4096
        if pos == 0:
            return None
        f.seek(pos)
        ln = struct.unpack('>i', f.read(4))[0]
        comp = f.read(1)[0]
        d = f.read(ln - 1)
    return parse(gzip.decompress(d) if comp == 1 else zlib.decompress(d))


def feats(p):
    out = {}
    for f in (p.get('Features') or []):
        fid = f.get('cobblemon:feature_id')
        if fid in f:
            out[fid] = f[fid]
    return out


found = []
for cx in range(X0 >> 4, (X1 >> 4) + 1):
    for cz in range(Z0 >> 4, (Z1 >> 4) + 1):
        c = chunk(cx, cz)
        if not c:
            continue
        for e in (c.get('Entities') or []):
            p = e.get('Pokemon')
            if not p:
                continue
            sp = str(p.get('Species', '')).split(':')[-1]
            if SPECIES != '*' and sp != SPECIES:
                continue
            pos = e.get('Pos') or [0, 0, 0]
            if not (X0 <= pos[0] <= X1 and Z0 <= pos[2] <= Z1):
                continue
            nick = p.get('Nickname')
            if isinstance(nick, dict):
                nick = nick.get('translate') or nick.get('text')
            found.append(dict(species=sp, nick=nick, feats=feats(p), level=p.get('Level'),
                              shiny=bool(p.get('Shiny')), form=p.get('FormId'),
                              pos=[round(v, 1) for v in pos]))
print(json.dumps(found, indent=1, sort_keys=True))
print("TOTAL %d" % len(found), file=sys.stderr)
