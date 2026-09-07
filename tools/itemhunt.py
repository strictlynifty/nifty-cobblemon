"""Find every copy of given item ids ANYWHERE: player inventories (online or not),
ender chests, every container block entity in every dimension, and items nested
inside shulker boxes in any of those.

Usage: itemhunt.py <item_id> [<item_id> ...]

Nesting matters here - a bottle inside a shulker box inside a chest is three levels
deep, so the walk has to recurse rather than just read the top-level Items list.
"""
import struct, zlib, gzip, glob, os, sys, json, collections

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")

WANT = set(sys.argv[1:])
if not WANT:
    print('usage: itemhunt.py <item_id> ...')
    raise SystemExit(1)


def rd(b, p, t):
    if t == 1: return b[p], p + 1
    if t == 2: return struct.unpack_from('>h', b, p)[0], p + 2
    if t == 3: return struct.unpack_from('>i', b, p)[0], p + 4
    if t == 4: return struct.unpack_from('>q', b, p)[0], p + 8
    if t == 5: return struct.unpack_from('>f', b, p)[0], p + 4
    if t == 6: return struct.unpack_from('>d', b, p)[0], p + 8
    if t == 8:
        l = struct.unpack_from('>H', b, p)[0]; p += 2
        return b[p:p + l].decode('utf8', 'replace'), p + l
    if t == 7:
        n = struct.unpack_from('>i', b, p)[0]; return None, p + 4 + n
    if t == 11:
        n = struct.unpack_from('>i', b, p)[0]; return None, p + 4 + 4 * n
    if t == 12:
        n = struct.unpack_from('>i', b, p)[0]; return None, p + 4 + 8 * n
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


def parse(raw):
    p = 0
    t = raw[p]; p += 1
    l = struct.unpack_from('>H', raw, p)[0]; p += 2 + l
    return rd(raw, p, t)[0]


hits = []


def walk(o, where):
    """recurse through any NBT looking for item stacks, including nested shulkers"""
    if isinstance(o, dict):
        iid = o.get('id')
        if isinstance(iid, str) and iid in WANT:
            cnt = o.get('count', o.get('Count', 1))
            hits.append((where, iid, cnt))
        for v in o.values():
            walk(v, where)
    elif isinstance(o, list):
        for v in o:
            walk(v, where)


# ---- players (works whether online or not) ----
names = {}
try:
    for e in json.load(open(COBBLEMON_DIR + '/usercache.json')):
        names[e['uuid']] = e['name']
except Exception:
    pass
for f in sorted(glob.glob(COBBLEMON_DIR + '/world/playerdata/*.dat')):
    u = os.path.basename(f)[:-4]
    try:
        d = parse(gzip.open(f, 'rb').read())
    except Exception:
        continue
    walk(d, 'PLAYER %s' % names.get(u, u[:8]))

# ---- containers in every dimension ----
DIMS = [('Overworld', COBBLEMON_DIR + '/world/region'),
        ('Nether', COBBLEMON_DIR + '/world/DIM-1/region'),
        ('The End', COBBLEMON_DIR + '/world/DIM1/region')]
needles = [w.encode() for w in WANT]
for dim, path in DIMS:
    for f in sorted(glob.glob(path + '/*.mca')):
        try:
            raw = open(f, 'rb').read()
        except Exception:
            continue
        if len(raw) < 8192:
            continue
        hdr = raw[:4096]
        for i in range(1024):
            off = struct.unpack_from('>I', hdr, i * 4)[0]
            sec = off >> 8
            if sec == 0 or (sec + 1) * 4096 > len(raw):
                continue
            try:
                ln = struct.unpack_from('>I', raw, sec * 4096)[0]
                comp = raw[sec * 4096 + 4]
                data = raw[sec * 4096 + 5: sec * 4096 + 4 + ln]
                ch = zlib.decompress(data) if comp == 2 else gzip.decompress(data)
            except Exception:
                continue
            if not any(nd in ch for nd in needles):     # decompressed, not raw
                continue
            try:
                d = parse(ch)
            except Exception:
                continue
            for be in (d.get('block_entities') or []):
                walk(be, '%s container @ %s %s %s'
                     % (dim, be.get('x'), be.get('y'), be.get('z')))

# ---- entities (item frames, dropped items, minecart chests) ----
for dim, path in [('Overworld', COBBLEMON_DIR + '/world/entities'),
                  ('Nether', COBBLEMON_DIR + '/world/DIM-1/entities'),
                  ('The End', COBBLEMON_DIR + '/world/DIM1/entities')]:
    for f in sorted(glob.glob(path + '/*.mca')):
        try:
            raw = open(f, 'rb').read()
        except Exception:
            continue
        if len(raw) < 8192:
            continue
        hdr = raw[:4096]
        for i in range(1024):
            off = struct.unpack_from('>I', hdr, i * 4)[0]
            sec = off >> 8
            if sec == 0 or (sec + 1) * 4096 > len(raw):
                continue
            try:
                ln = struct.unpack_from('>I', raw, sec * 4096)[0]
                comp = raw[sec * 4096 + 4]
                data = raw[sec * 4096 + 5: sec * 4096 + 4 + ln]
                ch = zlib.decompress(data) if comp == 2 else gzip.decompress(data)
            except Exception:
                continue
            if not any(nd in ch for nd in needles):
                continue
            try:
                d = parse(ch)
            except Exception:
                continue
            for e in (d.get('Entities') or []):
                pos = e.get('Pos') or [0, 0, 0]
                walk(e, '%s entity %s @ %d %d %d'
                     % (dim, str(e.get('id', '')).split(':')[-1],
                        pos[0], pos[1], pos[2]))

print('SEARCHED FOR: %s' % ', '.join(sorted(WANT)))
print()
if not hits:
    print('*** NOT FOUND ANYWHERE *** (players, ender chests, containers, entities,')
    print('    including items nested inside shulker boxes)')
else:
    agg = collections.Counter()
    for where, iid, cnt in hits:
        agg[(where, iid)] += cnt
    for (where, iid), cnt in sorted(agg.items()):
        print('  %-58s %-44s x%d' % (where, iid.split(':')[-1], cnt))
    print()
    print('total stacks found: %d' % len(hits))
