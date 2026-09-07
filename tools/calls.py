"""Dump the method calls a given class makes, in bytecode order, per method.

Used to confirm mechanics I would otherwise be inferring from field names - e.g.
whether TrainerSpawnerBlockEntity.addTrainerIdsFromItem actually consults
TrainerMobData.getSignatureItem.
"""
import struct, zipfile, sys

jar, cls = sys.argv[1], sys.argv[2]
only = sys.argv[3] if len(sys.argv) > 3 else None
raw = zipfile.ZipFile(jar).read(cls)

n = struct.unpack_from('>H', raw, 8)[0]
p = 10
pool = {}
i = 1
while i < n:
    tag = raw[p]; p += 1
    if tag == 1:
        l = struct.unpack_from('>H', raw, p)[0]; p += 2
        pool[i] = ('utf8', raw[p:p + l].decode('utf8', 'replace')); p += l
    elif tag in (7, 8, 16, 19, 20):
        pool[i] = ('ref', struct.unpack_from('>H', raw, p)[0]); p += 2
    elif tag in (9, 10, 11, 12):
        a, b = struct.unpack_from('>HH', raw, p); p += 4; pool[i] = ('pair', (a, b))
    elif tag in (3, 4):
        pool[i] = ('n', 0); p += 4
    elif tag in (5, 6):
        pool[i] = ('n', 0); p += 8; i += 1
    elif tag == 15:
        p += 3
    elif tag in (17, 18):
        p += 4
    else:
        raise ValueError(tag)
    i += 1


def utf(x):
    e = pool.get(x)
    return e[1] if e and e[0] == 'utf8' else None


def cname(ci):
    e = pool.get(ci)
    return utf(e[1]) if e and e[0] == 'ref' else None


def skip_attrs(p):
    c = struct.unpack_from('>H', raw, p)[0]; p += 2
    out = []
    for _ in range(c):
        ni = struct.unpack_from('>H', raw, p)[0]; p += 2
        ln = struct.unpack_from('>I', raw, p)[0]; p += 4
        out.append((ni, raw[p:p + ln])); p += ln
    return out, p


OPLEN = {}
for o in list(range(0x15, 0x19)) + list(range(0x36, 0x3a)) + [0x10, 0xbc, 0xa9]:
    OPLEN[o] = 1
for o in ([0x11, 0x12 + 1, 0x14, 0xb2, 0xb3, 0xb4, 0xb5, 0xb6, 0xb7, 0xb8, 0xbb, 0xbd,
           0xc0, 0xc1] + list(range(0x99, 0xa8))):
    OPLEN[o] = 2
OPLEN[0x12] = 1
OPLEN[0x84] = 2
OPLEN[0xc5] = 3
for o in (0xb9, 0xba, 0xc8, 0xc9):
    OPLEN[o] = 4

p += 6
ic = struct.unpack_from('>H', raw, p)[0]; p += 2 + 2 * ic
fc = struct.unpack_from('>H', raw, p)[0]; p += 2
for _ in range(fc):
    p += 6
    _, p = skip_attrs(p)
mc = struct.unpack_from('>H', raw, p)[0]; p += 2
for _ in range(mc):
    p += 2
    ni = struct.unpack_from('>H', raw, p)[0]; p += 2
    p += 2
    attrs, p = skip_attrs(p)
    mname = utf(ni)
    if only and only not in (mname or ''):
        continue
    for an, body in attrs:
        if utf(an) != 'Code':
            continue
        clen = struct.unpack_from('>I', body, 4)[0]
        code = body[8:8 + clen]
        seq = []
        k = 0
        while k < len(code):
            op = code[k]
            if op in (0xb6, 0xb7, 0xb8, 0xb9, 0xb2, 0xb4):
                e = pool.get(struct.unpack_from('>H', code, k + 1)[0])
                if e and e[0] == 'pair':
                    ci, nti = e[1]
                    nt = pool.get(nti)
                    seq.append('%s.%s' % ((cname(ci) or '?').split('/')[-1],
                                          utf(nt[1][0]) if nt else '?'))
                k += 1 + OPLEN.get(op, 2)
            elif op in (0xaa, 0xab):
                k += 1
                while k % 4:
                    k += 1
                if op == 0xaa:
                    lo, hi = struct.unpack_from('>ii', code, k + 4)
                    k += 12 + 4 * (hi - lo + 1)
                else:
                    np = struct.unpack_from('>i', code, k + 4)[0]
                    k += 8 + 8 * np
            else:
                k += 1 + OPLEN.get(op, 0)
        if seq:
            print('=== %s' % mname)
            for s in seq:
                print('    %s' % s)
            print()
