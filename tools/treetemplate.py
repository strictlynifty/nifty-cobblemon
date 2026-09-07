"""Find the trunk position inside legendarymonuments:dyna_tree.nbt.

DynaTreeSaplingBlock stamps this template at a fixed 10/10 offset from the 5x5
formation centre. Whether that lands the trunk on the centre depends on where the
trunk actually sits inside the template, which is what this measures.
"""
import os
import struct, gzip, zipfile, glob, collections

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")


def rd(b, p, t):
    if t == 1: return b[p] - (256 if b[p] > 127 else 0), p + 1
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
        return list(b[p:p + n]), p + n
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
    raise ValueError(t)


z = zipfile.ZipFile(glob.glob(COBBLEMON_DIR + '/mods/legendarymonuments-*.jar')[0])
raw = z.read('data/legendarymonuments/structure/dyna_tree.nbt')
try:
    raw = gzip.decompress(raw)
except Exception:
    pass
p = 0
t = raw[p]; p += 1
l = struct.unpack_from('>H', raw, p)[0]; p += 2 + l
d, _ = rd(raw, p, t)

size = d.get('size')
pal = d.get('palette') or []
blocks = d.get('blocks') or []
print('template size (x,y,z):', size)
print('palette entries:', len(pal), ' block entries:', len(blocks))

names = [str((e or {}).get('Name', '')) for e in pal]
log_states = {i for i, n in enumerate(names) if 'log' in n or 'wood' in n}
print('log/wood palette indices:', {i: names[i] for i in log_states})

by_y = collections.defaultdict(list)
for b in blocks:
    if b.get('state') in log_states:
        x, y, zz = b['pos']
        by_y[y].append((x, zz))

if not by_y:
    print('NO LOG BLOCKS FOUND - listing most common palette names instead')
    cnt = collections.Counter(names[b['state']] for b in blocks if b.get('state') is not None)
    for n, c in cnt.most_common(12):
        print('   %-52s %d' % (n, c))
else:
    ymin = min(by_y)
    base = by_y[ymin]
    xs = [c[0] for c in base]
    zs = [c[1] for c in base]
    print()
    print('lowest log layer y=%d  (%d blocks)' % (ymin, len(base)))
    print('   x range %d..%d   z range %d..%d' % (min(xs), max(xs), min(zs), max(zs)))
    cx = (min(xs) + max(xs)) / 2.0
    cz = (min(zs) + max(zs)) / 2.0
    print('   TRUNK CENTRE inside template: x=%.1f  z=%.1f' % (cx, cz))
    print()
    print('template geometric centre: x=%.1f z=%.1f' % ((size[0] - 1) / 2.0, (size[2] - 1) / 2.0))
    print()
    print('code stamps template at formationCentre -/+ (10,0,10).')
    print('  if placed at centre-(10,10): trunk lands at centre + (%.1f, %.1f)' % (cx - 10, cz - 10))
    print('  if placed at centre+(10,10): trunk lands at centre + (%.1f, %.1f)' % (cx + 10, cz + 10))
