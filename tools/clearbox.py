# -*- coding: utf-8 -*-
"""Clear a box, with a full restore file. Reads the region files directly.

Two modes:
  built-only  -> `fill <box> air replace <material>` per non-natural material.
                 Removes a structure but leaves the landscape intact.
  everything  -> a single `fill <box> air`. Two commands cleared both Petalwake
                 houses (5,897 + 1,978 blocks) instantly.

ALWAYS write the restore file first. It captures full block states, but container
CONTENTS cannot be restored - check with blockentities.py and tell the owner what
is inside before you delete anything.
"""
import struct, zlib, gzip, sys, os, collections

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")

REG = COBBLEMON_DIR + '/world/region'
NAT = set("""stone dirt water grass_block andesite granite diorite sand gravel coal_ore
copper_ore iron_ore gold_ore lapis_ore redstone_ore diamond_ore emerald_ore deepslate
deepslate_coal_ore deepslate_copper_ore deepslate_iron_ore deepslate_gold_ore
deepslate_lapis_ore deepslate_redstone_ore deepslate_diamond_ore deepslate_emerald_ore
short_grass tall_grass fern large_fern clay coarse_dirt rooted_dirt podzol moss_block
moss_carpet mud muddy_mangrove_roots mangrove_roots oak_log oak_leaves birch_log
birch_leaves spruce_log spruce_leaves jungle_log jungle_leaves acacia_log acacia_leaves
dark_oak_log dark_oak_leaves mangrove_log mangrove_leaves cherry_log cherry_leaves
azalea_leaves flowering_azalea_leaves vine glow_lichen cobblemon:apricorn_leaves
cobblemon:apricorn_log poppy dandelion cornflower oxeye_daisy azure_bluet allium
lily_of_the_valley red_tulip orange_tulip white_tulip pink_tulip blue_orchid
sugar_cane cactus dead_bush lily_pad seagrass tall_seagrass kelp kelp_plant snow
snow_block ice packed_ice tuff calcite smooth_basalt amethyst_block budding_amethyst
amethyst_cluster large_amethyst_bud medium_amethyst_bud small_amethyst_bud
pointed_dripstone dripstone_block bedrock lava magma_block sunflower lilac rose_bush
peony sweet_berry_bush cobweb obsidian bubble_column brown_mushroom red_mushroom
cobblemon:sun_stone_ore cobblemon:thunder_stone_ore cobblemon:water_stone_ore
cobblemon:fire_stone_ore cobblemon:leaf_stone_ore cobblemon:moon_stone_ore
cobblemon:dawn_stone_ore cobblemon:dusk_stone_ore cobblemon:shiny_stone_ore
cobblemon:ice_stone_ore""".split())


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


def scan(X0, X1, Y0, Y1, Z0, Z1):
    out = {}
    for cx in range(X0 >> 4, (X1 >> 4) + 1):
        for cz in range(Z0 >> 4, (Z1 >> 4) + 1):
            c = chunk(cx, cz)
            if not c:
                continue
            for sec in c.get('sections') or []:
                sy = sec.get('Y')
                if sy is None or sy * 16 > Y1 or sy * 16 + 15 < Y0:
                    continue
                bs = sec.get('block_states') or {}
                pal = bs.get('palette') or []
                if not pal:
                    continue
                data = bs.get('data')
                nm = [str(p.get('Name', '')).replace('minecraft:', '') for p in pal]
                pr = [p.get('Properties') or {} for p in pal]
                if data is None:
                    if nm[0] == 'air':
                        continue
                    idxs = [0] * 4096
                else:
                    bits = max(4, (len(pal) - 1).bit_length())
                    per, mask, idxs = 64 // bits, (1 << bits) - 1, []
                    for lw in data:
                        lw &= (1 << 64) - 1
                        for k in range(per):
                            if len(idxs) >= 4096:
                                break
                            idxs.append((lw >> (k * bits)) & mask)
                        if len(idxs) >= 4096:
                            break
                for i, pi in enumerate(idxs):
                    n = nm[pi]
                    if n in ('air', 'cave_air', 'void_air'):
                        continue
                    y = sy * 16 + (i >> 8)
                    z = cz * 16 + ((i >> 4) & 15)
                    x = cx * 16 + (i & 15)
                    if X0 <= x <= X1 and Y0 <= y <= Y1 and Z0 <= z <= Z1:
                        out[(x, y, z)] = (n, pr[pi])
    return out


BOXES = [('east', 14998, 15022, 63, 92, -14575, -14555),
         ('west', 14934, 14947, 69, 87, -14583, -14560)]
fills, restore, total = [], [], 0
for name, x0, x1, y0, y1, z0, z1 in BOXES:
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)
    z0, z1 = min(z0, z1), max(z0, z1)
    blocks = scan(x0, x1, y0, y1, z0, z1)
    mats = collections.Counter()
    for (x, y, z), (n, p) in blocks.items():
        if n in NAT:
            continue
        mats[n] += 1
        total += 1
        st = ''
        if p:
            st = '[' + ','.join('%s=%s' % kv for kv in sorted(p.items())) + ']'
        restore.append('setblock %d %d %d %s%s' % (x, y, z, n, st))
    box = '%d %d %d %d %d %d' % (x0, y0, z0, x1, y1, z1)
    for m in sorted(mats):
        fills.append('fill %s air replace %s' % (box, m))
    print('%s box: %d built blocks, %d materials, volume %d'
          % (name, sum(mats.values()), len(mats), (x1 - x0 + 1) * (y1 - y0 + 1) * (z1 - z0 + 1)))

open('/tmp/demo_fills.txt', 'w').write('\n'.join(fills) + '\n')
open('/tmp/demo_restore.txt', 'w').write('\n'.join(restore) + '\n')
print('total %d blocks to remove | %d fill commands | %d restore setblocks'
      % (total, len(fills), len(restore)))
