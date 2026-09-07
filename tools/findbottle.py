# -*- coding: utf-8 -*-
"""Find every prison_bottle / prism_bottle in the world - containers and entities.

Two Prison Bottles exist (mega_showdown and mythsandlegends) and only the M&L one does
anything, so which copy is sitting in a chest is a real question.

Strategy: decompress each chunk and substring-test before parsing any NBT. The parse is
the expensive part; the test is a memchr.
"""
import struct, zlib, gzip, os, sys, glob, time, json

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")

NEEDLES = (b"prison_bottle", b"prism_bottle")


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
        out = []
        for _ in range(n):
            v, p = rd(b, p, it); out.append(v)
        return out, p
    if t == 10:
        out = {}
        while True:
            tt = b[p]; p += 1
            if tt == 0: return out, p
            l = struct.unpack_from('>H', b, p)[0]; p += 2
            nm = b[p:p + l].decode('utf8', 'replace'); p += l
            v, p = rd(b, p, tt); out[nm] = v
    raise ValueError(t)


def parse(raw):
    p = 0
    t = raw[p]; p += 1
    l = struct.unpack_from('>H', raw, p)[0]; p += 2 + l
    v, _ = rd(raw, p, t)
    return v


def walk(node, hits, ctx):
    """Collect any item stack whose id matches, with whatever container it sits in."""
    if isinstance(node, dict):
        nid = node.get("id")
        if isinstance(nid, str) and any(n.decode() in nid for n in NEEDLES):
            hits.append((nid, node.get("count", node.get("Count", 1)), dict(ctx)))
        newctx = dict(ctx)
        if isinstance(nid, str) and ":" in nid and "block_entity" not in nid:
            newctx.setdefault("holder", nid)
        for k in ("x", "y", "z"):
            if k in node and isinstance(node[k], int):
                newctx[k] = node[k]
        for v in node.values():
            walk(v, hits, newctx)
    elif isinstance(node, list):
        for v in node:
            walk(v, hits, ctx)


def scan_region(path, hits):
    try:
        d = open(path, "rb").read()
    except Exception:
        return 0
    if len(d) < 8192:          # empty or truncated region file
        return 0
    n = 0
    for i in range(1024):
        off = struct.unpack_from(">I", d, i * 4)[0]
        if not off:
            continue
        sec = off >> 8
        if sec * 4096 + 5 > len(d):
            continue
        ln = struct.unpack_from(">I", d, sec * 4096)[0]
        comp = d[sec * 4096 + 4]
        raw = d[sec * 4096 + 5: sec * 4096 + 4 + ln]
        try:
            raw = zlib.decompress(raw) if comp == 2 else (gzip.decompress(raw) if comp == 1 else raw)
        except Exception:
            continue
        n += 1
        if not any(x in raw for x in NEEDLES):
            continue
        try:
            nbt = parse(raw)
        except Exception:
            continue
        got = []
        walk(nbt, got, {"region": os.path.basename(path)})
        for g in got:
            hits.append(g)
    return n


if __name__ == "__main__":
    roots = sys.argv[1:] or [COBBLEMON_DIR + "/world/region"]
    files = []
    for r in roots:
        files += sorted(glob.glob(os.path.join(r, "*.mca")))
    t0 = time.time()
    hits, chunks = [], 0
    for k, f in enumerate(files):
        chunks += scan_region(f, hits)
        if k and k % 200 == 0:
            el = time.time() - t0
            print("  %d/%d regions, %d chunks, %d hits, %.0fs elapsed, ~%.0fs left"
                  % (k, len(files), chunks, len(hits), el, el / k * (len(files) - k)),
                  flush=True)
    print("DONE %d regions, %d chunks, %.0fs" % (len(files), chunks, time.time() - t0))
    seen = set()
    for nid, cnt, ctx in hits:
        key = (nid, ctx.get("x"), ctx.get("y"), ctx.get("z"))
        if key in seen:
            continue
        seen.add(key)
        print("  %-34s x%-3s at %s %s %s   holder=%s  (%s)"
              % (nid, cnt, ctx.get("x"), ctx.get("y"), ctx.get("z"),
                 ctx.get("holder", "?"), ctx.get("region")))
    print("total distinct: %d" % len(seen))
