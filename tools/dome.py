# -*- coding: utf-8 -*-
"""Generate a watertight voxel dome over an existing circular wall.

    python3 dome.py --compare                 # silhouettes for several rises
    python3 dome.py --emit 15 > /dev/null     # writes /tmp/dome_fills.txt + _undo.txt

Then place with:  python3 rconbatch.py /tmp/dome_fills.txt

Assumes /tmp/voxel.json from voxel.py so it can collision-check first.

WHY IT WORKS: Minecraft circle generators use  dx^2 + dz^2 <= R^2  with a
half-block R (R=18.5 for a 37-diameter circle). Use the SAME rule in 3-D and the
dome's base course lands on the existing wall block-for-block.

Sphere is pinned so its surface passes through radius RB at the top FACE of the
wall (walltop + 0.5), which makes the join flush:

    d  = (RB^2 - H^2) / (2H)        drop from wall top down to the sphere centre
    Rs = d + H                      sphere radius for a rise of H

TWO TRAPS, both hit while building the Poke Ball gym:

1. A radius-band shell (r-1 <= dist <= r) leaks. Use the neighbour rule instead:
   keep a block if it is in the solid AND any of its 4 lateral neighbours is not,
   OR it is not covered by the layer above. That is watertight by construction.

2. Even a correct shell springs INBOARD of the wall at the diagonal positions,
   because layer 0 of the sphere is already slightly smaller than the equator.
   That leaves an uneven ledge. Fix by force-adding the full wall-line ring to
   the first course (--emit does this).

Verify with a flood fill, and only treat the SIDES and TOP of the test box as
escapes - the floor is legitimately open, and counting it reports a false leak.
"""
import json, collections, sys

CX, CZ = 14977, -14576     # arena centre
RB = 18.5                  # base radius (37-diameter circle)
WALLTOP = 75               # last course of the straight wall
SPRING = WALLTOP + 1
GLASS = 'chipped:clear_leaded_glass'


def build(H):
    d = (RB * RB - H * H) / (2.0 * H)
    Rs = d + H
    yc = (WALLTOP + 0.5) - d
    solid, y = {}, SPRING
    while True:
        q = Rs * Rs - (y + 0.5 - yc) ** 2
        if q < 0:
            break
        s = set((dx, dz) for dx in range(-20, 21) for dz in range(-20, 21)
                if dx * dx + dz * dz <= q)
        if not s:
            break
        solid[y] = s
        y += 1
    while solid and len(solid[max(solid)]) < 5:      # drop the apex spike
        del solid[max(solid)]
    dome = {}
    for y in sorted(solid):
        cur, up = solid[y], solid.get(y + 1, set())
        s = set(p for p in cur
                if (p[0] + 1, p[1]) not in cur or (p[0] - 1, p[1]) not in cur
                or (p[0], p[1] + 1) not in cur or (p[0], p[1] - 1) not in cur
                or p not in up)
        if s:
            dome[y] = s
    return dome, solid, Rs, yc


def wall_ring():
    return set((dx, dz) for dx in range(-19, 20) for dz in range(-19, 20)
               if dx * dx + dz * dz <= RB * RB
               and not all((dx + a) ** 2 + (dz + b) ** 2 <= RB * RB
                           for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1))))


def compare(rises):
    for H in rises:
        dome, solid, Rs, yc = build(H)
        ys = sorted(dome)
        ws = [max(p[0] for p in solid[y]) - min(p[0] for p in solid[y]) + 1 for y in ys]
        print('H=%-5s apex y=%-3d %2d courses %5d blocks  step-in %s'
              % (H, ys[-1], len(ys), sum(len(v) for v in dome.values()),
                 ' '.join(str(a - b) for a, b in zip([37] + ws[:-1], ws))))
        for y in reversed(ys):
            row = [' '] * 39
            for dx in range(-19, 20):
                if (dx, 0) in dome[y]:
                    row[dx + 19] = '#'
            print('   %4d |%s|' % (y, ''.join(row)))
        print()


def emit(H):
    dome, _, _, _ = build(H)
    dome[SPRING] = dome.get(SPRING, set()) | wall_ring()      # flush spring line
    try:
        occ = set(tuple(int(t) for t in k.split(','))
                  for k in json.load(open('/tmp/voxel.json'))['blocks'])
    except IOError:
        occ = set()
    fills, undo, n, clash = [], [], 0, 0
    for y in sorted(dome):
        rows = collections.defaultdict(list)
        for dx, dz in dome[y]:
            rows[CZ + dz].append(CX + dx)
        for z in sorted(rows):
            xs = sorted(rows[z])
            run = [xs[0]]
            for x in xs[1:] + [None]:
                if x == run[-1] + 1:
                    run.append(x)
                else:
                    fills.append('fill %d %d %d %d %d %d %s'
                                 % (run[0], y, z, run[-1], y, z, GLASS))
                    undo.append('fill %d %d %d %d %d %d air'
                                % (run[0], y, z, run[-1], y, z))
                    if x is not None:
                        run = [x]
            n += len(xs)
            clash += sum(1 for x in xs if (x, y, z) in occ)
    open('/tmp/dome_fills.txt', 'w').write(chr(10).join(fills) + chr(10))
    open('/tmp/dome_undo.txt', 'w').write(chr(10).join(reversed(undo)) + chr(10))
    print('H=%s  y=%d..%d  %d blocks  %d fills  %d already occupied'
          % (H, min(dome), max(dome), n, len(fills), clash))


if __name__ == '__main__':
    if '--emit' in sys.argv:
        emit(float(sys.argv[sys.argv.index('--emit') + 1]))
    else:
        compare([18.5, 15, 13, 11, 9])
