"""Build a basename -> owning-mod map so the wiki can badge every item.

The wiki's NAMES map is keyed on bare basenames with no namespace, which is exactly
why Lunar Wing / Lunar Feather got mislabelled. This scans every mod's lang file for
item./block. keys, records which namespaces define each basename, and flags the
collisions explicitly instead of silently picking one.

Badges chosen for glance-legibility rather than initials, since ML/LM misread easily:
    Legendary Monuments -> a classical building (it is the structures mod)
    Myths & Legends     -> a scroll (it is the key-item/lore mod)
"""
import zipfile, glob, json, collections, os

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")

BADGE = {
    'legendarymonuments': ('\U0001F3DB️', 'Legendary Monuments'),
    'mythsandlegends': ('\U0001F4DC', 'Myths &amp; Legends'),
}

owners = collections.defaultdict(set)
display = {}
for jp in sorted(glob.glob(COBBLEMON_DIR + '/mods/*.jar')):
    try:
        z = zipfile.ZipFile(jp)
    except Exception:
        continue
    for n in z.namelist():
        if not n.endswith('/lang/en_us.json') or not n.startswith('assets/'):
            continue
        ns = n.split('/')[1]
        try:
            lang = json.loads(z.read(n).decode('utf-8-sig'))
        except Exception:
            continue
        for k, v in lang.items():
            parts = k.split('.')
            if len(parts) < 3 or parts[0] not in ('item', 'block'):
                continue
            if parts[1] != ns:
                continue
            base = parts[2]
            if len(parts) > 3:           # skip .description / .tooltip subkeys
                continue
            owners[base].add(ns)
            display.setdefault((ns, base), v)

tracked = {b: sorted(s) for b, s in owners.items()
           if s & set(BADGE)}
collisions = {b: s for b, s in tracked.items() if len(s) > 1}

out = {}
for base, nss in tracked.items():
    mine = [ns for ns in nss if ns in BADGE]
    out[base] = {
        'mods': mine,
        'collision': len(nss) > 1,
        'others': [ns for ns in nss if ns not in BADGE],
    }

json.dump(out, open('/tmp/modsrc.json', 'w'))
print('items/blocks owned by M&L or LM : %d' % len(tracked))
print('  Legendary Monuments only      : %d'
      % sum(1 for v in out.values() if v['mods'] == ['legendarymonuments'] and not v['collision']))
print('  Myths & Legends only          : %d'
      % sum(1 for v in out.values() if v['mods'] == ['mythsandlegends'] and not v['collision']))
print()
print('NAME COLLISIONS (same basename in more than one mod) : %d' % len(collisions))
for b, nss in sorted(collisions.items()):
    labels = ' / '.join('%s=%s' % (ns, display.get((ns, b), '?')) for ns in nss)
    print('   %-28s %s' % (b, labels))
