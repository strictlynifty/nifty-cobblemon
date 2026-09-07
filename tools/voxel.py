# -*- coding: utf-8 -*-
"""Read a real cuboid of blocks out of the saved region files.

Unlike berryscan.py this decodes the packed block_states.data, so it gives
actual per-coordinate blocks, not just "this chunk contains X".

Usage:  python3 voxel.py X0 X1 Y0 Y1 Z0 Z1  [world_dir]
Writes /tmp/voxel.json  ->  {"box": [...], "blocks": {"x,y,z": "name", ...}}

Chunk format notes (1.21.1):
  sections[].block_states.palette = [{Name, Properties}]
  sections[].block_states.data    = long[] , bits = max(4, ceil(log2(len(palette))))
  Values never span two longs (post-1.16). Index order = y*256 + z*16 + x.
  A section with a 1-entry palette has NO data array - the whole section is that block.
"""
import struct, zlib, gzip, sys, os, json, math, collections

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")

X0, X1, Y0, Y1, Z0, Z1 = (int(a) for a in sys.argv[1:7])
WORLD = sys.argv[7] if len(sys.argv) > 7 else COBBLEMON_DIR + '/world'
REG = os.path.join(WORLD, 'region')


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


blocks = {}
census = collections.Counter()
missing = []
for cx in range(X0 >> 4, (X1 >> 4) + 1):
    for cz in range(Z0 >> 4, (Z1 >> 4) + 1):
        c = chunk(cx, cz)
        if c is None:
            missing.append((cx, cz)); continue
        for sec in c.get('sections') or []:
            sy = sec.get('Y')
            if sy is None:
                continue
            base = sy * 16
            if base > Y1 or base + 15 < Y0:
                continue
            bs = sec.get('block_states') or {}
            pal = bs.get('palette') or []
            if not pal:
                continue
            data = bs.get('data')
            nm = [str(p.get('Name', '')).replace('minecraft:', '') for p in pal]
            props = [p.get('Properties') or {} for p in pal]
            if data is None:
                if nm[0] == 'air':
                    continue
                idxs = [0] * 4096
            else:
                bits = max(4, (len(pal) - 1).bit_length())
                per = 64 // bits
                mask = (1 << bits) - 1
                idxs = []
                for lw in data:
                    lw &= (1 << 64) - 1
                    for k in range(per):
                        if len(idxs) >= 4096:
                            break
                        idxs.append((lw >> (k * bits)) & mask)
                    if len(idxs) >= 4096:
                        break
            for i, pi in enumerate(idxs):
                n = nm[pi]
                if n == 'air' or n == 'cave_air' or n == 'void_air':
                    continue
                y = base + (i >> 8)
                if y < Y0 or y > Y1:
                    continue
                z = cz * 16 + ((i >> 4) & 15)
                x = cx * 16 + (i & 15)
                if x < X0 or x > X1 or z < Z0 or z > Z1:
                    continue
                pr = props[pi]
                lbl = n
                if pr:
                    keep = {k: v for k, v in pr.items()
                            if k in ('facing', 'half', 'shape', 'axis', 'type', 'open')}
                    if keep:
                        lbl = n + '[' + ','.join('%s=%s' % kv for kv in sorted(keep.items())) + ']'
                blocks['%d,%d,%d' % (x, y, z)] = lbl
                census[n] += 1

json.dump({'box': [X0, X1, Y0, Y1, Z0, Z1], 'blocks': blocks},
          open('/tmp/voxel.json', 'w'))
print('box x%d..%d y%d..%d z%d..%d -> %d non-air blocks'
      % (X0, X1, Y0, Y1, Z0, Z1, len(blocks)))
if missing:
    print('MISSING CHUNKS (ungenerated): %d  %s' % (len(missing), missing[:8]))
print('top materials:')
for n, c in census.most_common(30):
    print('  %-34s %d' % (n, c))
