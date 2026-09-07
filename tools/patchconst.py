# -*- coding: utf-8 -*-
"""Replace a UTF8 string constant inside a .class file, length-safe.

    python3 patchconst.py <in.class> <out.class> <old-substring> <new-substring>

Class files reference constants by POOL INDEX, never by byte offset, so a UTF8
entry can be replaced with a different-length string as long as its 2-byte
length prefix is rewritten. Everything after it shifts harmlessly.

Written to fix LinguaChat: Google killed the `client=gtx` parameter its Google
provider hardcodes, while `client=dict-chrome-ex` still returns the identical
JSON shape.
"""
import struct, sys

src, dst, old, new = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
raw = bytearray(open(src, 'rb').read())
assert raw[:4] == b'\xca\xfe\xba\xbe', 'not a class file'

count = struct.unpack_from('>H', raw, 8)[0]
out = bytearray(raw[:10])
p = 10
i = 1
hits = 0
while i < count:
    tag = raw[p]
    if tag == 1:
        ln = struct.unpack_from('>H', raw, p + 1)[0]
        s = raw[p + 3:p + 3 + ln].decode('utf8', 'surrogatepass')
        if old in s:
            s2 = s.replace(old, new)
            b2 = s2.encode('utf8', 'surrogatepass')
            out += bytes([1]) + struct.pack('>H', len(b2)) + b2
            print('  [%d] %s\n   -> %s' % (i, s, s2))
            hits += 1
        else:
            out += raw[p:p + 3 + ln]
        p += 3 + ln
    else:
        sz = {7: 2, 8: 2, 16: 2, 19: 2, 20: 2, 9: 4, 10: 4, 11: 4, 12: 4,
              3: 4, 4: 4, 5: 8, 6: 8, 15: 3, 17: 4, 18: 4}[tag]
        out += raw[p:p + 1 + sz]
        p += 1 + sz
        if tag in (5, 6):
            i += 1
    i += 1
out += raw[p:]

if not hits:
    print('no constant contained %r - nothing written' % old)
    sys.exit(1)
open(dst, 'wb').write(bytes(out))
print('patched %d constant(s); %d -> %d bytes' % (hits, len(raw), len(out)))
