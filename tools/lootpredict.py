# -*- coding: utf-8 -*-
"""Predict what a brushable block will give, from its stored LootTableSeed.

    python3 lootpredict.py X0 X1 Y0 Y1 Z0 Z1 <loot_table_substring>

Works ONLY for a loot table that is a single pool, `rolls: 1`, `bonus_rolls: 0`,
no functions and no conditions on the pool or any entry. Then the sole random
call is `nextInt(totalWeight)` and the result is fully determined by the seed
Minecraft already wrote into the block entity. `archaeology/trail_ruins_rare`
qualifies (12 entries, weight 1 each).

Verify before trusting: brush one predicted block and check it matches. If the
table has any function (enchantments, counts, damage) the RNG advances further
and this is wrong.

Java LegacyRandomSource == java.util.Random:
  seed  = (s ^ 0x5DEECE66D) & (2^48-1)
  next  : seed = (seed*0x5DEECE66D + 0xB) & (2^48-1); return (int)(seed >>> (48-bits))
  nextInt(n), n not a power of two: retry while (bits - val + n-1) overflows int
"""
import sys, json, zipfile

MASK = (1 << 48) - 1
MUL = 0x5DEECE66D
ADD = 0xB


def s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


class JRandom(object):
    def __init__(self, seed):
        self.s = (seed ^ MUL) & MASK

    def next(self, bits):
        self.s = (self.s * MUL + ADD) & MASK
        return s32(self.s >> (48 - bits))

    def next_int(self, bound):
        if bound & -bound == bound:                 # power of two
            return (bound * self.next(31)) >> 31
        while True:
            bits = self.next(31)
            val = bits % bound
            if s32(bits - val + (bound - 1)) >= 0:
                return val


def entries_for(table_id, jar):
    """Return [(name, weight)] in JSON order, or None if the table is unsafe."""
    path = 'data/%s/loot_table/%s.json' % tuple(table_id.split(':', 1)) \
        if ':' in table_id else None
    d = json.loads(zipfile.ZipFile(jar).read(path).decode('utf-8-sig'))
    pools = d.get('pools') or []
    if len(pools) != 1:
        return None
    p = pools[0]
    if p.get('rolls') != 1.0 or p.get('bonus_rolls', 0.0) != 0.0:
        return None
    if p.get('functions') or p.get('conditions'):
        return None
    out = []
    for e in p['entries']:
        if e.get('functions') or e.get('conditions'):
            return None
        out.append((e['name'], e.get('weight', 1)))
    return out


def predict(seed, entries):
    total = sum(w for _, w in entries)
    if len(entries) == 1:
        return entries[0][0]
    k = JRandom(seed).next_int(total)
    for name, w in entries:
        k -= w
        if k < 0:
            return name
    return entries[-1][0]


if __name__ == '__main__':
    print(__doc__)
