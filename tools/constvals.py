"""Print every static-final field and its ConstantValue for a class.

cpstr.py only dumps UTF8 strings, so int constants like
GIANT_TREE_TEMPLATE_X_OFFSET are invisible to it. The value lives in the field's
ConstantValue attribute, pointing at a CONSTANT_Integer in the pool.
"""
import struct, zipfile, sys

jar, cls = sys.argv[1], sys.argv[2]
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
    elif tag == 3:
        pool[i] = ('int', struct.unpack_from('>i', raw, p)[0]); p += 4
    elif tag == 4:
        pool[i] = ('float', struct.unpack_from('>f', raw, p)[0]); p += 4
    elif tag == 5:
        pool[i] = ('long', struct.unpack_from('>q', raw, p)[0]); p += 8; i += 1
    elif tag == 6:
        pool[i] = ('double', struct.unpack_from('>d', raw, p)[0]); p += 8; i += 1
    elif tag in (7, 8, 16, 19, 20):
        pool[i] = ('ref', struct.unpack_from('>H', raw, p)[0]); p += 2
    elif tag == 15:
        p += 3
    elif tag in (9, 10, 11, 12, 17, 18):
        p += 4
    else:
        raise ValueError('tag %d' % tag)
    i += 1


def utf(i):
    e = pool.get(i)
    return e[1] if e and e[0] == 'utf8' else None


p += 6
ic = struct.unpack_from('>H', raw, p)[0]; p += 2 + 2 * ic
fc = struct.unpack_from('>H', raw, p)[0]; p += 2
print('%-40s %-10s %s' % ('FIELD', 'TYPE', 'CONSTANT VALUE'))
for _ in range(fc):
    p += 2
    ni = struct.unpack_from('>H', raw, p)[0]; p += 2
    di = struct.unpack_from('>H', raw, p)[0]; p += 2
    ac = struct.unpack_from('>H', raw, p)[0]; p += 2
    val = None
    for _ in range(ac):
        an = struct.unpack_from('>H', raw, p)[0]; p += 2
        ln = struct.unpack_from('>I', raw, p)[0]; p += 4
        body = raw[p:p + ln]; p += ln
        if utf(an) == 'ConstantValue':
            e = pool.get(struct.unpack_from('>H', body, 0)[0])
            val = e[1] if e else None
    if val is not None:
        print('%-40s %-10s %s' % (utf(ni), utf(di), val))
