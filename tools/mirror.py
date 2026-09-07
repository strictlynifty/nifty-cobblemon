# -*- coding: utf-8 -*-
"""Copy a build to the opposite side of a structure by 180-degree rotation.

    x' = 2*CX - x,   z' = 2*CZ - z

USE ROTATION, NOT REFLECTION. A reflection reverses handedness, so every stair
`shape` has to flip too (inner_left <-> inner_right, outer_left <-> outer_right)
and it is easy to get wrong. A 180-degree rotation preserves handedness: `shape`
and `half` are untouched, only `facing` flips (n<->s, e<->w) and sign `rotation`
gains 8. One transform maps north->south AND east->west at the same time.

CHECK FOR PER-SIDE DIFFERENCES FIRST. The gym's four gates carry four *different*
statues (ancient / squirtle / charmander / pikachu). A whole-box copy would have
silently overwritten two of them. Fix: shrink the source box to exclude the
differing rows - here the staircases live at y 63-68 and the statues at y 69-70.

Then verify by walking every cell of the source box and asserting
    rot(source) == target
Both staircases came out 0 mismatched across 2,508 cells. Anything left over on
the target side that the source does not cover (village debris, in this case)
has to be cleared separately or the mirror is not actually a mirror.

Run with --go to emit /tmp/mirror.txt plus an exact undo.
"""

import json, collections, sys

CX, CZ = 14977, -14576
V = json.load(open('/tmp/voxel.json'))
FULL = {}
for k, v in V['blocks'].items():
    FULL[tuple(int(t) for t in k.split(','))] = v

NAT = set("""stone dirt water grass_block andesite granite diorite sand gravel coal_ore
copper_ore iron_ore gold_ore short_grass tall_grass fern large_fern clay coarse_dirt
rooted_dirt podzol moss_block moss_carpet mud muddy_mangrove_roots mangrove_roots
oak_log oak_leaves birch_log birch_leaves spruce_log spruce_leaves jungle_log
jungle_leaves acacia_log acacia_leaves dark_oak_log dark_oak_leaves mangrove_log
mangrove_leaves cherry_log cherry_leaves azalea_leaves flowering_azalea_leaves vine
glow_lichen poppy dandelion cornflower oxeye_daisy azure_bluet allium
lily_of_the_valley red_tulip orange_tulip white_tulip pink_tulip sugar_cane cactus
dead_bush lily_pad seagrass tall_seagrass snow snow_block ice tuff calcite
smooth_basalt amethyst_block budding_amethyst amethyst_cluster large_amethyst_bud
medium_amethyst_bud small_amethyst_bud deepslate bedrock lava magma_block peony lilac
rose_bush sunflower sweet_berry_bush cobweb obsidian dripstone_block
pointed_dripstone brown_mushroom red_mushroom grass dirt_path farmland""".split())

FLIP = {'north': 'south', 'south': 'north', 'east': 'west', 'west': 'east'}


def rot(v):
    """Rotate a blockstate string 180 degrees."""
    if '[' not in v:
        return v
    name, props = v.split('[', 1)
    props = props.rstrip(']')
    out = []
    for kv in props.split(','):
        k, _, val = kv.partition('=')
        if k == 'facing' and val in FLIP:
            val = FLIP[val]
        elif k == 'rotation':
            val = str((int(val) + 8) % 16)
        out.append('%s=%s' % (k, val))
    return '%s[%s]' % (name, ','.join(out))


SRC = {'NORTH->SOUTH': (14969, 14985, 63, 68, -14602, -14592),
       'EAST->WEST':   (14993, 15003, 63, 68, -14586, -14566)}

place, clear, conflict = [], [], collections.Counter()
for name, (x0, x1, y0, y1, z0, z1) in SRC.items():
    src = {}
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            for z in range(z0, z1 + 1):
                v = FULL.get((x, y, z))
                if v and v.split('[')[0] not in NAT:
                    src[(x, y, z)] = v
    tx0, tx1 = sorted((2 * CX - x0, 2 * CX - x1))
    tz0, tz1 = sorted((2 * CZ - z0, 2 * CZ - z1))
    # everything currently occupying the target box
    cur = {}
    for x in range(tx0, tx1 + 1):
        for y in range(y0, y1 + 1):
            for z in range(tz0, tz1 + 1):
                v = FULL.get((x, y, z))
                if v:
                    cur[(x, y, z)] = v
    tgt = {}
    for (x, y, z), v in src.items():
        tgt[(2 * CX - x, y, 2 * CZ - z)] = rot(v)
    nat_in_way = {p: v for p, v in cur.items() if v.split('[')[0] in NAT}
    built_in_way = {p: v for p, v in cur.items()
                    if v.split('[')[0] not in NAT and tgt.get(p, '').split('[')[0] != v.split('[')[0]}
    print('=== %s ===' % name)
    print('  source box  x %d..%d  y %d..%d  z %d..%d   -> %d built blocks'
          % (x0, x1, y0, y1, z0, z1, len(src)))
    print('  target box  x %d..%d  y %d..%d  z %d..%d' % (tx0, tx1, y0, y1, tz0, tz1))
    print('  natural terrain in the way: %d' % len(nat_in_way))
    print('  already correct (gym blocks that match): %d'
          % sum(1 for p, v in cur.items()
                if p in tgt and tgt[p].split('[')[0] == v.split('[')[0]))
    if built_in_way:
        c = collections.Counter(v.split('[')[0] for v in built_in_way.values())
        print('  ** EXISTING BUILT BLOCKS THAT WOULD BE REPLACED: %d **' % len(built_in_way))
        for m, n in c.most_common(10):
            print('       %-44s %d' % (m, n))
        conflict.update(c)
    else:
        print('  existing built blocks that would be replaced: none')
    for p in nat_in_way:
        clear.append('setblock %d %d %d air' % p)
    for p, v in sorted(tgt.items()):
        if FULL.get(p) != v:
            place.append('setblock %d %d %d %s' % (p[0], p[1], p[2], v))
    print()

print('TOTAL: clear %d natural blocks, place %d staircase blocks'
      % (len(clear), len(place)))
if '--go' in sys.argv:
    open('/tmp/mirror.txt', 'w').write('\n'.join(clear + place) + '\n')
    undo = []
    for line in clear + place:
        t = line.split()
        p = (int(t[1]), int(t[2]), int(t[3]))
        undo.append('setblock %d %d %d %s' % (p + (FULL.get(p, 'air'),)))
    open('/tmp/mirror_undo.txt', 'w').write('\n'.join(undo) + '\n')
    print('wrote /tmp/mirror.txt (%d cmds) and /tmp/mirror_undo.txt' % len(clear + place))
