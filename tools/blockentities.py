# -*- coding: utf-8 -*-
"""List block entities (and their inventories) inside a box."""
import struct, zlib, gzip, sys, os, json, collections

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")

X0, X1, Y0, Y1, Z0, Z1 = (int(a) for a in sys.argv[1:7])
X0, X1 = min(X0, X1), max(X0, X1)
Y0, Y1 = min(Y0, Y1), max(Y0, Y1)
Z0, Z1 = min(Z0, Z1), max(Z0, Z1)
REG = COBBLEMON_DIR + '/world/region'


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
    raise ValueError(t)


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
    d = gzip.decompress(d) if comp == 1 else zlib.decompress(d)
    l = struct.unpack_from('>H', d, 1)[0]
    return rd(d, 3 + l, 10)[0]


def items(be):
    out = []
    for key in ('Items', 'items'):
        for it in (be.get(key) or []):
            if isinstance(it, dict):
                out.append('%s x%s' % (str(it.get('id', '?')).replace('minecraft:', ''),
                                       it.get('count', it.get('Count', 1))))
    return out


rows, empty = [], collections.Counter()
for cx in range(X0 >> 4, (X1 >> 4) + 1):
    for cz in range(Z0 >> 4, (Z1 >> 4) + 1):
        c = chunk(cx, cz)
        if not c:
            continue
        for be in c.get('block_entities') or []:
            x, y, z = be.get('x'), be.get('y'), be.get('z')
            if x is None or not (X0 <= x <= X1 and Y0 <= y <= Y1 and Z0 <= z <= Z1):
                continue
            i = items(be)
            kind = str(be.get('id', '?')).replace('minecraft:', '')
            if i:
                rows.append((kind, x, y, z, i))
            else:
                empty[kind] += 1

print('box x %d..%d  y %d..%d  z %d..%d' % (X0, X1, Y0, Y1, Z0, Z1))
if rows:
    print('CONTAINERS WITH ITEMS: %d' % len(rows))
    for kind, x, y, z, i in sorted(rows, key=lambda r: -len(r[4])):
        print('  %-22s %d %d %d   %d stacks: %s'
              % (kind, x, y, z, len(i), ', '.join(i[:14]) + (' ...' if len(i) > 14 else '')))
else:
    print('CONTAINERS WITH ITEMS: none')
print('empty / non-inventory block entities: %s' % (dict(empty) or 'none'))
