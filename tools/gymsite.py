# -*- coding: utf-8 -*-
"""Judge whether a generated structure is actually PLAYABLE where it landed.

`locate structure` will happily point at a gym that generated inside a hill or under a
lake - it reports placement, not usability. The Vermilion gym at 10048,-8672 is the proof:
locate found it, and it turned out buried in stone with 950 water blocks through it.

So read the saved chunks instead and answer the two questions that decide it:
  flooded - water inside the structure's own bounding box
  buried  - ground level OUTSIDE the box sitting above the box's floor

The bounding box comes from the chunk's own `structures.starts[<id>].BB`, not guessed from
which blocks look man-made; only the START chunk carries it, so scan a few chunks out.

Usage:  python3 gymsite.py <structure-id> <x> <z> [<x> <z> ...]
Chunks must already be generated - forceload the area first, then save-all flush.
"""
import struct, zlib, gzip, sys, os, json, collections

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")

WORLD = os.environ.get("MCWORLD", COBBLEMON_DIR + "/world")
REG = os.path.join(WORLD, "region")

def rd(b, p, t):
    if t == 1: return struct.unpack_from('>b', b, p)[0], p + 1   # TAG_Byte is SIGNED
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
    t = raw[0]
    assert t == 10, t
    l = struct.unpack_from('>H', raw, 1)[0]
    v, _ = rd(raw, 3 + l, 10)
    return v


def chunk(cx, cz):
    rx, rz = cx >> 5, cz >> 5
    fp = os.path.join(REG, 'r.%d.%d.mca' % (rx, rz))
    if not os.path.exists(fp):
        return None
    with open(fp, 'rb') as f:
        off = ((cx & 31) + (cz & 31) * 32) * 4
        f.seek(off)
        e = f.read(4)
        pos = (e[0] << 16 | e[1] << 8 | e[2]) * 4096
        if pos == 0:
            return None
        f.seek(pos)
        ln = struct.unpack('>i', f.read(4))[0]
        comp = f.read(1)[0]
        d = f.read(ln - 1)
    if comp == 1:
        d = gzip.decompress(d)
    elif comp == 2:
        d = zlib.decompress(d)
    return parse(d)




NATURAL = {"stone", "dirt", "andesite", "diorite", "granite", "gravel", "deepslate",
           "tuff", "sand", "sandstone", "clay", "grass_block", "coarse_dirt", "water",
           "terracotta", "red_sand", "red_sandstone"}


def blocks_in(x0, x1, y0, y1, z0, z1):
    """Decode real blocks in a cuboid. Air is omitted, as in voxel.py."""
    out = {}
    for cx in range(x0 >> 4, (x1 >> 4) + 1):
        for cz in range(z0 >> 4, (z1 >> 4) + 1):
            c = chunk(cx, cz)
            if c is None:
                continue
            for sec in c.get("sections") or []:
                sy = sec.get("Y")
                if sy is None or sy * 16 > y1 or sy * 16 + 15 < y0:
                    continue
                bs = sec.get("block_states") or {}
                pal = bs.get("palette") or []
                if not pal:
                    continue
                nm = [str(p.get("Name", "")).replace("minecraft:", "") for p in pal]
                data = bs.get("data")
                if data is None:
                    if nm[0] == "air":
                        continue
                    idxs = [0] * 4096
                else:
                    bits = max(4, (len(pal) - 1).bit_length())
                    per = 64 // bits
                    mask = (1 << bits) - 1
                    idxs = []
                    for lo in data:
                        v = lo & 0xFFFFFFFFFFFFFFFF
                        for k in range(per):
                            if len(idxs) < 4096:
                                idxs.append((v >> (k * bits)) & mask)
                for i, pi in enumerate(idxs):
                    n = nm[pi]
                    if n == "air":
                        continue
                    by = sy * 16 + (i >> 8)
                    bz = cz * 16 + ((i >> 4) & 15)
                    bx = cx * 16 + (i & 15)
                    if x0 <= bx <= x1 and y0 <= by <= y1 and z0 <= bz <= z1:
                        out[(bx, by, bz)] = n
    return out


def find_bb(sid, x, z, span=3):
    """Only the START chunk carries the BB. Every chunk the structure touches instead carries
    a References entry: a long[] of packed ChunkPos naming that start chunk. Follow it rather
    than sweeping outward and hoping - a gym can start well outside a 3-chunk box."""
    short = sid.split(":")[-1]
    cx0, cz0 = x >> 4, z >> 4
    todo, seen = [], set()
    for dx in range(-span, span + 1):
        for dz in range(-span, span + 1):
            todo.append((cx0 + dx, cz0 + dz))
    while todo:
        cx, cz = todo.pop(0)
        if (cx, cz) in seen:
            continue
        seen.add((cx, cz))
        c = chunk(cx, cz)
        if not c:
            continue
        st = c.get("structures") or {}
        for k, v in (st.get("starts") or {}).items():
            # The start itself carries no BB - each jigsaw piece under Children does. One
            # piece for these gyms, but union them so a multi-piece structure still works.
            if k.split(":")[-1] != short or not isinstance(v, dict):
                continue
            bbs = [c["BB"] for c in (v.get("Children") or [])
                   if isinstance(c, dict) and c.get("BB")]
            if bbs:
                return [min(b[i] for b in bbs) for i in range(3)] +                        [max(b[i] for b in bbs) for i in range(3, 6)]
        for k, longs in (st.get("References") or {}).items():
            if k.split(":")[-1] != short:
                continue
            for lo in (longs or []):
                lo &= 0xFFFFFFFFFFFFFFFF
                rx = lo & 0xFFFFFFFF
                rz = (lo >> 32) & 0xFFFFFFFF
                if rx >= 0x80000000:
                    rx -= 0x100000000
                if rz >= 0x80000000:
                    rz -= 0x100000000
                if (rx, rz) not in seen:
                    todo.append((rx, rz))
    return None


def full(cx, cz):
    """`locate` writes proto-chunks: structure starts computed, no terrain. Those parse fine
    and answer "0 water, nothing around" - which reads as CLEAN and is really "not built yet".
    Only Status=minecraft:full chunks can be judged."""
    c = chunk(cx, cz)
    return bool(c) and str(c.get("Status", "")).split(":")[-1] == "full"


def report(sid, x, z):
    try:
        bb = find_bb(sid, x, z)
    except Exception as e:
        return dict(x=x, z=z, ok=False, why="read error: %s" % e)
    if not bb:
        cx, cz = x >> 4, z >> 4
        return dict(x=x, z=z, ok=False, why="not generated" if chunk(cx, cz) is None
                    else "no structure start found within 3 chunks")
    X0, Y0, Z0, X1, Y1, Z1 = bb
    pad = 6
    need = [(cx, cz)
            for cx in range((X0 - pad) >> 4, ((X1 + pad) >> 4) + 1)
            for cz in range((Z0 - pad) >> 4, ((Z1 + pad) >> 4) + 1)]
    nf = [p for p in need if not full(*p)]
    if nf:
        return dict(x=x, z=z, ok=False, bb=bb,
                    why="%d/%d chunks not generated - forceload first" % (len(nf), len(need)))
    inner = blocks_in(X0, X1, Y0, Y1, Z0, Z1)
    water = sum(1 for n in inner.values() if n == "water")

    # ground level just OUTSIDE the box, on all four sides. If that sits above the box floor
    # the structure is dug into a slope; well above the box top and it is fully swallowed.
    ring = blocks_in(X0 - pad, X1 + pad, Y0 - 4, Y1 + 40, Z0 - pad, Z1 + pad)
    cols = collections.defaultdict(int)
    for (bx, by, bz), n in ring.items():
        if X0 <= bx <= X1 and Z0 <= bz <= Z1:
            continue                      # inside the footprint - that is the building
        if n in NATURAL or n.endswith("_log") or n.endswith("_leaves"):
            cols[(bx, bz)] = max(cols[(bx, bz)], by)
    heights = sorted(cols.values())
    med = heights[len(heights) // 2] if heights else 0
    outside_water = sum(1 for (bx, by, bz), n in ring.items()
                        if n == "water" and not (X0 <= bx <= X1 and Z0 <= bz <= Z1))
    return dict(x=x, z=z, ok=True, bb=bb, floor=Y0, top=Y1, water=water,
                ground=med, buried=med - Y0, near_water=outside_water,
                size="%dx%dx%d" % (X1 - X0 + 1, Y1 - Y0 + 1, Z1 - Z0 + 1))


if __name__ == "__main__":
    sid = sys.argv[1]
    args = [int(a) for a in sys.argv[2:]]
    rows = [report(sid, args[i], args[i + 1]) for i in range(0, len(args), 2)]
    print("%-16s %-6s %-6s %-7s %-7s %-8s %s" %
          ("site", "floor", "top", "ground", "water", "nearby", "verdict"))
    for r in rows:
        if not r["ok"]:
            print("%-16s %s" % ("%d,%d" % (r["x"], r["z"]), r["why"]))
            continue
        bad = []
        if r["water"] > 20:
            bad.append("FLOODED (%d water inside)" % r["water"])
        if r["buried"] > 6:
            bad.append("BURIED (ground %d above floor)" % r["buried"])
        v = "  ".join(bad) if bad else "CLEAN"
        print("%-16s %-6d %-6d %-7d %-7d %-8d %s"
              % ("%d,%d" % (r["x"], r["z"]), r["floor"], r["top"], r["ground"],
                 r["water"], r["near_water"], v))
    print()
    print(json.dumps(rows))
