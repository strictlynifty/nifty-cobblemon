"""Find every Cobblemon berry tree actually present in the generated Overworld.

Berry blocks are ordinary blocks, so they live in each chunk section's
block_states.palette - no block entity involved. We only need chunk coordinates to
send someone to the right 16x16, so we read the palette and skip decoding the packed
indices entirely.

NOTE the lesson from the bell scan: the needle MUST be tested against the
DECOMPRESSED chunk. Region payloads are zlib-compressed, so testing the raw .mca
bytes silently matches nothing and reports a confident zero.
"""
import os
import struct, zlib, gzip, glob, collections, json, math

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")

REF = (-18, -142)   # roughly where the players are standing
OUT = open('/tmp/berryscan.out', 'w')


def say(s):
    print(s)
    OUT.write(s + '\n')
    OUT.flush()


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


found = collections.defaultdict(list)      # berry -> [(chunkX, chunkZ)]
chunks_read = 0
regions = sorted(glob.glob(COBBLEMON_DIR + '/world/region/*.mca'))
for f in regions:
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
            if ln < 1 or sec * 4096 + 4 + ln > len(raw):
                continue
            comp = raw[sec * 4096 + 4]
            data = raw[sec * 4096 + 5: sec * 4096 + 4 + ln]
            ch = zlib.decompress(data) if comp == 2 else gzip.decompress(data)
        except Exception:
            continue
        chunks_read += 1
        if b'_berry' not in ch:                 # decompressed, not raw
            continue
        try:
            d = parse(ch)
        except Exception:
            continue
        cx, cz = d.get('xPos'), d.get('zPos')
        if cx is None:
            continue
        names = set()
        for s in (d.get('sections') or []):
            bs = s.get('block_states') or {}
            for pal in (bs.get('palette') or []):
                nm = str((pal or {}).get('Name', ''))
                if nm.startswith('cobblemon:') and nm.endswith('_berry'):
                    names.add(nm.split(':')[1].replace('_berry', ''))
        for nm in names:
            found[nm].append((cx, cz))

say('chunks read: %d   region files: %d' % (chunks_read, len(regions)))
say('distinct berry species found in world: %d' % len(found))
say('')
say('%-12s %8s   nearest chunk to (%d, %d)' % ('BERRY', 'CHUNKS', REF[0], REF[1]))
rows = []
for b, cs in found.items():
    best = min(cs, key=lambda c: (c[0] * 16 + 8 - REF[0]) ** 2 + (c[1] * 16 + 8 - REF[1]) ** 2)
    bx, bz = best[0] * 16 + 8, best[1] * 16 + 8
    dist = int(math.hypot(bx - REF[0], bz - REF[1]))
    rows.append((dist, b, len(cs), bx, bz))
for dist, b, n, bx, bz in sorted(rows):
    say('%-12s %8d   %6d %6d   (%d blocks away)' % (b, n, bx, bz, dist))

json.dump({b: cs for b, cs in found.items()}, open('/tmp/berryscan.json', 'w'))
say('')
say('wrote /tmp/berryscan.json')
OUT.close()
