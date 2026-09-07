# -*- coding: utf-8 -*-
"""Union of N solid spheres, emitted as `fill ... replace air`.

Built for the Gloom bloom on the gym: four r=14 spheres, centres 14 out on the gate axes, red concrete.
Edit the constants, run on the server, then rconbatch.py /tmp/bloom_fills.txt.

`replace air` is the key: the shape is laid through whatever is already there
WITHOUT destroying it. That preserved the glass dome, so the arena still has a
glass ceiling from the inside.

BUT `replace air` also leaves every non-air block embedded, which puts dents in a
shape you meant to be solid. Always run a second pass: rescan, find non-air cells
inside the volume that are not the thing you deliberately kept, convert those, and
append their original ids to the undo file. 88 blocks of hillside needed this.

Scale: 2,601 fills / 85,181 blocks went through batched RCON in 0.56 s. `/fill` is
capped at 32768 blocks per command; per-row fills never come close.
"""

import json, collections, math, sys

CX, CZ = 14977, -14576
D = 14
RP = 14.0
YC = 90
BLOCK = 'red_concrete'
OUTLINE = 18.5

V = json.load(open('/tmp/voxel.json'))
occ = {}
for k, v in V['blocks'].items():
    x, y, z = (int(t) for t in k.split(','))
    occ[(x, y, z)] = v.split('[')[0]

cs = [(CX + D, CZ), (CX - D, CZ), (CX, CZ + D), (CX, CZ - D)]
pts = set()
r = int(math.ceil(RP))
for (sx, sz) in cs:
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            for dz in range(-r, r + 1):
                if dx * dx + dy * dy + dz * dz <= RP * RP:
                    pts.add((sx + dx, YC + dy, sz + dz))

embedded = collections.Counter(occ[p] for p in pts if p in occ)
new = [p for p in pts if p not in occ]

fills, undo = [], []
bylayer = collections.defaultdict(lambda: collections.defaultdict(list))
for (x, y, z) in pts:
    bylayer[y][z].append(x)
for y in sorted(bylayer):
    for z in sorted(bylayer[y]):
        xs = sorted(bylayer[y][z])
        run = [xs[0]]
        for x in xs[1:] + [None]:
            if x == run[-1] + 1:
                run.append(x)
            else:
                fills.append('fill %d %d %d %d %d %d %s replace air'
                             % (run[0], y, z, run[-1], y, z, BLOCK))
                undo.append('fill %d %d %d %d %d %d air replace %s'
                            % (run[0], y, z, run[-1], y, z, BLOCK))
                if x is not None:
                    run = [x]

open('/tmp/bloom_fills.txt', 'w').write('\n'.join(fills) + '\n')
open('/tmp/bloom_undo.txt', 'w').write('\n'.join(reversed(undo)) + '\n')

xs = [p[0] for p in pts]; ys = [p[1] for p in pts]; zs = [p[2] for p in pts]
print('bloom: D=%d Rp=%g Yc=%d  centres %s' % (D, RP, YC, cs))
print('  %d sphere blocks, %d currently air (will be placed), %d already occupied'
      % (len(pts), len(new), len(pts) - len(new)))
print('  span x %d..%d  z %d..%d  y %d..%d' % (min(xs), max(xs), min(zs), max(zs), min(ys), max(ys)))
print('  overhang past the %.1f outline: %.1f blocks (%.0f%% of a radius)'
      % (OUTLINE, D + RP - OUTLINE, 100 * (D + RP - OUTLINE) / RP))
print('  %d fill commands' % len(fills))
print('  blocks left embedded (preserved, not overwritten):')
for m, c in embedded.most_common(12):
    print('     %-40s %d' % (m, c))
