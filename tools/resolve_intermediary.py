# -*- coding: utf-8 -*-
"""Resolve intermediary Items field names (class_1802.field_NNNNN) to real item ids.

The Items <clinit> registers each item by string id and immediately putstatic's it into
its field, so walking the clinit in order recovers the mapping exactly - no guessing
from memory, which is how you end up telling someone to carry the wrong thing.
"""
import re

WANT = ["field_47315", "field_8687", "field_28354", "field_8056",
        "field_8288", "field_42688", "field_8711", "field_16998", "field_28659"]

src = open("/tmp/items.txt", encoding="utf-8", errors="replace").read()
clinit = src[src.index("=== <clinit>"):]

# pair each string constant with the next putstatic field_NNNNN after it
pairs = []
last_str = None
for m in re.finditer(r'ldc(?:_w)?\s+"([a-z0-9_./]+)"|putstatic\s+class_1802\.(field_\d+)', clinit):
    if m.group(1) is not None:
        last_str = m.group(1)
    elif last_str is not None:
        pairs.append((m.group(2), last_str))

table = {}
for fld, sid in pairs:
    table.setdefault(fld, sid)

print("resolved %d fields from <clinit>" % len(table))
print()
# sanity-check against something we can verify independently
for probe, expect in (("field_8687", "diamond"),):
    got = table.get(probe)
    print("  sanity: %s -> %s   (expected %s)  %s"
          % (probe, got, expect, "OK" if got == expect else "*** MISMATCH ***"))
print()
for f in WANT:
    print("  %-14s -> %s" % (f, table.get(f, "UNRESOLVED")))
