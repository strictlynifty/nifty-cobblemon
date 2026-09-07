"""Resolve intermediary field_NNNN names to real Minecraft item ids.

class_1802 (Items) registers each item in <clinit> as roughly
    putstatic field_XXXX  <- method_7989("registry_name", ...)
so walking the Code attribute and pairing each ldc String with the NEXT putstatic
recovers field -> item id.
"""
import os
import struct, zipfile, json, sys

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")

TARGETS = set(sys.argv[1:]) if len(sys.argv) > 1 else set()


def parse_pool(raw):
    n = struct.unpack_from('>H', raw, 8)[0]
    p = 10
    pool = {}
    i = 1
    while i < n:
        tag = raw[p]; p += 1
        if tag == 1:
            l = struct.unpack_from('>H', raw, p)[0]; p += 2
            pool[i] = ('utf8', raw[p:p + l].decode('utf8', 'replace')); p += l
        elif tag == 7:
            pool[i] = ('class', struct.unpack_from('>H', raw, p)[0]); p += 2
        elif tag == 8:
            pool[i] = ('string', struct.unpack_from('>H', raw, p)[0]); p += 2
        elif tag in (9, 10, 11):
            a, b = struct.unpack_from('>HH', raw, p); p += 4; pool[i] = ('ref', (a, b))
        elif tag == 12:
            a, b = struct.unpack_from('>HH', raw, p); p += 4; pool[i] = ('nat', (a, b))
        elif tag in (3, 4):
            pool[i] = ('num', 0); p += 4
        elif tag in (5, 6):
            pool[i] = ('num8', 0); p += 8; i += 1
        elif tag == 15:
            p += 3
        elif tag == 16:
            p += 2
        elif tag in (17, 18):
            p += 4
        elif tag in (19, 20):
            p += 2
        else:
            raise ValueError(tag)
        i += 1
    return pool, p


def utf(pool, i):
    e = pool.get(i)
    return e[1] if e and e[0] == 'utf8' else None


def skip_attrs(raw, p):
    cnt = struct.unpack_from('>H', raw, p)[0]; p += 2
    out = []
    for _ in range(cnt):
        ni = struct.unpack_from('>H', raw, p)[0]; p += 2
        ln = struct.unpack_from('>I', raw, p)[0]; p += 4
        out.append((ni, raw[p:p + ln])); p += ln
    return out, p


OPLEN = {}
for o in list(range(0x15, 0x19)) + list(range(0x36, 0x3a)) + [0x10, 0xbc, 0xa9]:
    OPLEN[o] = 1
for o in ([0x11, 0x13, 0x14, 0xb2, 0xb3, 0xb4, 0xb5, 0xb6, 0xb7, 0xb8, 0xbb, 0xbd, 0xc0, 0xc1]
          + list(range(0x99, 0xa8))):
    OPLEN[o] = 2
OPLEN[0x84] = 2
OPLEN[0xc5] = 3
for o in (0xb9, 0xba, 0xc8, 0xc9):
    OPLEN[o] = 4

z = zipfile.ZipFile(COBBLEMON_DIR + '/.fabric/remappedJars/'
                    'minecraft-1.21.1-0.19.3/server-intermediary.jar')
name = [n for n in z.namelist() if n.endswith('net/minecraft/class_1802.class')
        or n == 'net/minecraft/class_1802.class']
raw = z.read(name[0])
pool, p = parse_pool(raw)
p += 6
ic = struct.unpack_from('>H', raw, p)[0]; p += 2 + 2 * ic
fc = struct.unpack_from('>H', raw, p)[0]; p += 2
for _ in range(fc):
    p += 6
    _, p = skip_attrs(raw, p)
mc = struct.unpack_from('>H', raw, p)[0]; p += 2
mapping = {}
for _ in range(mc):
    p += 2
    ni = struct.unpack_from('>H', raw, p)[0]; p += 2
    p += 2
    attrs, p = skip_attrs(raw, p)
    if utf(pool, ni) != '<clinit>':
        continue
    for an, body in attrs:
        if utf(pool, an) != 'Code':
            continue
        clen = struct.unpack_from('>I', body, 4)[0]
        code = body[8:8 + clen]
        i = 0
        pending = None
        while i < len(code):
            op = code[i]
            if op == 0x12:
                e = pool.get(code[i + 1]); i += 2
                if e and e[0] == 'string':
                    pending = utf(pool, e[1])
            elif op in (0x13, 0x14):
                e = pool.get(struct.unpack_from('>H', code, i + 1)[0]); i += 3
                if e and e[0] == 'string':
                    pending = utf(pool, e[1])
            elif op == 0xb3:                     # putstatic
                e = pool.get(struct.unpack_from('>H', code, i + 1)[0]); i += 3
                if e and e[0] == 'ref':
                    nt = pool.get(e[1][1])
                    fn = utf(pool, nt[1][0]) if nt else None
                    if fn and pending:
                        mapping[fn] = pending
            elif op in (0xaa, 0xab):
                i += 1
                while i % 4:
                    i += 1
                if op == 0xaa:
                    lo, hi = struct.unpack_from('>ii', code, i + 4)
                    i += 12 + 4 * (hi - lo + 1)
                else:
                    np = struct.unpack_from('>i', code, i + 4)[0]
                    i += 8 + 8 * np
            else:
                i += 1 + OPLEN.get(op, 0)

print('resolved %d item fields' % len(mapping))
json.dump(mapping, open('/tmp/itemmap.json', 'w'))
if TARGETS:
    print()
    for t in sorted(TARGETS):
        print('  %-16s -> %s' % (t, mapping.get(t, '*** NOT RESOLVED ***')))
