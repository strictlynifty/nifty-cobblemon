"""Trainer Spawner gym guide: which item summons which trainer, in battle order.

Mechanic verified from bytecode, not inferred: TrainerSpawnerBlockEntity
.addTrainerIdsFromItem resolves the held item's registry name, filters
TrainerManager.getAllData on TrainerMobData.getSignatureItem, and adds every match
to trainerIds. So the spawner summons whoever owns that signature item.

Collision check: 16 signature items map to more than one trainer, but all of those
are the SAME character at different story stages (Cedric x3, Rival Wayne x3...).
No Gym Leader shares a signature item, so one item = one leader.

The "or go to" column comes from the RGS structure NBTs themselves, so a gym is only offered
as an alternative if that structure really contains that leader. Kanto is the only series with
gym structures; the other two are spawner-only.
"""
import os
import json, html, zipfile, glob, collections

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")

D3P = '/tmp/wiki_data3.json'
z = zipfile.ZipFile(glob.glob(COBBLEMON_DIR + '/mods/rctmod-*.jar')[0])


def esc(s):
    return html.escape(str(s))


names, teams = {}, {}
for n in z.namelist():
    if n.startswith('data/rctmod/trainers/') and n.endswith('.json'):
        try:
            d = json.loads(z.read(n).decode('utf-8-sig'))
        except Exception:
            continue
        tid = n.split('/')[-1][:-5]
        names[tid] = d.get('name')
        teams[tid] = d.get('team') or []
mobs = {}
for n in z.namelist():
    if n.startswith('data/rctmod/mobs/trainers/single/') and n.endswith('.json'):
        mobs[n.split('/')[-1][:-5]] = json.loads(z.read(n).decode('utf-8-sig'))

# Which leaders a gym structure actually places. Scan the decompressed NBT for trainer ids and
# keep only those naming a real trainer - block names like stripped_acac fit the pattern too.
import gzip, re

GYM_LABEL = {
    "pewter_gym":     "a Pewter Gym (Rock)",
    "cerulean_gym":   "a Cerulean Gym (Water)",
    "vermilion_gym":  "a Vermilion Gym (Electric)",
    "celadon_gym":    "a Celadon Gym (Grass)",
    "saffron_gym":    "a Saffron Gym (Psychic)",
    "fuchsia_gym":    "a Fuchsia Gym (Poison)",
    "cinnabar_gym":   "a Cinnabar Gym (Fire), in the Nether",
    "blackthorn_gym": "a Blackthorn Gym (Dragon), in the End",
    "kanto_league":   "the Kanto League, in the End",
}
gyms = {}
for _p in glob.glob(COBBLEMON_DIR + '/mods/RadicalGymsStructures*.jar'):
    gz = zipfile.ZipFile(_p)
    for n in gz.namelist():
        key = n.split('/')[-1][:-4] if n.endswith('.nbt') else None
        if key not in GYM_LABEL:
            continue
        raw = gz.read(n)
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
        for t in set(re.findall(rb"[a-z][a-z_]*_[0-9a-f]{4}", raw)):
            if t.decode() in mobs:
                gyms[t.decode()] = GYM_LABEL[key]

sigcount = collections.Counter()
for tid, d in mobs.items():
    if d.get('signatureItem'):
        sigcount[d['signatureItem']] += 1


def deps(t):
    return [x for g in (mobs.get(t, {}).get('requiredDefeats') or []) for x in g]


def depth(t, seen=frozenset()):
    ds = [d for d in deps(t) if d in mobs and d not in seen]
    return 0 if not ds else 1 + max(depth(d, seen | {t}) for d in ds)


SERIES = [('bdsp', 'Brilliant Diamond / Shining Pearl', 'Sinnoh'),
          ('radicalred', 'Radical Red', 'Kanto'),
          ('unbound', 'Unbound', 'Borrious')]

blocks = ''
for key, title, region in SERIES:
    leaders = [t for t, d in mobs.items()
               if d.get('type') == 'leader' and key in (d.get('series') or [])]
    leaders.sort(key=lambda t: (depth(t), names.get(t, t)))
    rows = ''
    for i, tid in enumerate(leaders, 1):
        d = mobs[tid]
        sig = str(d.get('signatureItem') or '').split(':')[-1]
        lv = [p.get('level') for p in teams.get(tid, []) if p.get('level')]
        team = ', '.join('%s %s' % (str(p.get('species', '?')).replace('_', ' ').title(),
                                    p.get('level')) for p in teams.get(tid, []))
        uniq = sigcount.get(d.get('signatureItem'), 0)
        warn = '' if uniq <= 1 else ' <span style="color:#e8a33d">&#9888;&#65039;</span>'
        rows += ('<tr><td class="n">%d</td><td><b>%s</b></td>'
                 '<td><b>%s</b>%s</td><td class="n">%s</td><td class="sm">%s</td>'
                 '<td class="sm">%s</td></tr>'
                 % (i, esc(names.get(tid, tid)),
                    esc(sig.replace('_', ' ').title()), warn,
                    max(lv) if lv else '?', esc(team)[:90],
                    ('or go to <b>%s</b>' % esc(gyms[tid])) if tid in gyms
                    else '<span class="mut">spawner only</span>'))
    blocks += ('<h4 style="margin:16px 0 4px">%s <span class="mut">&mdash; %s</span></h4>'
               '<div class="tw"><table><thead><tr><th>#</th><th>Gym Leader</th>'
               '<th>Item to put in the spawner</th><th>Ace</th><th>Team</th>'
               '<th>Or go to</th></tr></thead><tbody>%s</tbody></table></div>'
               % (esc(title), esc(region), rows))

GYM = """<b>Build a gym: the Trainer Spawner summons a specific trainer on demand.</b>
<div class="card good" style="margin:8px 0"><b>This removes the hunting entirely.</b>
<div class="sm" style="margin-top:6px">Put a trainer's <b>signature item</b> into a Trainer Spawner
and that trainer becomes the one it spawns. No wandering biomes hoping the 0.25-weight lottery lands
&mdash; build eight rooms, drop eight items, and every leader is on tap for everyone.</div></div>
<div class="card" style="margin:8px 0"><b>Kanto has a second option.</b>
<div class="sm" style="margin-top:6px">Eight Kanto leaders also stand in a gym structure out in the world, and the Elite Four and Champion in the Kanto League. Beating them there counts the same as a spawner fight, and keeps the level cap on. The <b>Or go to</b> column says which structure holds each one.</div></div>
<p style="margin:8px 0 0"><b>Craft the Trainer Spawner:</b> stone bricks in the four corners,
stone brick slabs top-centre and bottom-centre, and <b>2 diamonds</b> either side of <b>1 redstone</b>
in the middle row (<code>BSB / DRD / BSB</code>).</p>
<p style="margin:8px 0 0">It also has <b>powered</b> and <b>inverted</b> redstone states and a
player-distance range, so you can wire a gym door to activate the leader only once a challenger
walks in.</p>

<div class="card warn" style="margin:10px 0"><b>Battle them in the listed order.</b>
<div class="sm" style="margin-top:6px">A leader will refuse to fight until their prerequisites are
beaten, so a spawner does not let you skip ahead &mdash; it only removes the <i>finding</i>. The #
column below is the dependency order. You also still need to be <b>on that series</b>, and each
leader can be beaten <b>once</b>.</div></div>

%s

<p style="margin:10px 0 0" class="muted sm">&#9888;&#65039; marks a signature item shared by more
than one trainer entry &mdash; always the same character at a different story stage, never a
different person. No two Gym Leaders share an item, so every row above is unambiguous.</p>
<p style="margin:8px 0 0" class="muted sm">Verified from the mod's own code: the spawner reads the
item's registry name and matches it against every trainer's <code>signatureItem</code>.</p>""" % blocks

D3 = json.load(open(D3P))
D3['notes']['gymspawner'] = GYM
json.dump(D3, open(D3P, 'w'))
tot = sum(1 for t, d in mobs.items() if d.get('type') == 'leader')
print('gym note built: %d leaders across %d series' % (tot, len(SERIES)))
print('signature items shared by >1 entry: %d' % sum(1 for v in sigcount.values() if v > 1))
