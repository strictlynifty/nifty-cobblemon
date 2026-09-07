# -*- coding: utf-8 -*-
"""Which aspects actually change a Pokemon's 3-D model?

Run on the server, from the mods directory:

    cd "$COBBLEMON_DIR/mods" && python3 aspectmodels.py

Writes /tmp/aspects_strict.json:  token -> {model: [...], poser: [...], tex: [...], mods: [...]}

Method: every resolver's `aspects: []` variation gives the species' base `model`
and `poser`. A variation is attributed to a token only when its aspect set minus
`shiny` is exactly that one token. Then:

  model differs from base  -> real model change (different mesh)
  poser differs, model not -> animation-only change
  neither                  -> texture repaint

THE TRAP: attributing a multi-aspect variation's model to every token in it.
Resolver files for megas contain a ["mega","shiny"] variation carrying the mega
mesh, so a loose scan reports `shiny` as changing the model on 63 species. It
does not. `female` survives strict matching at 82 species -- those really are
separate meshes.
"""
import zipfile, json, glob, collections, os, sys

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")

OUT = '/tmp/aspects_strict.json'

sp = collections.defaultdict(lambda: {'base': None, 'basep': None, 'vars': []})
for jp in sorted(glob.glob('*.jar')):
    try:
        z = zipfile.ZipFile(jp)
    except Exception:
        continue
    mod = os.path.basename(jp).split('-')[0].lower()
    for n in z.namelist():
        if '/bedrock/pokemon/resolvers/' not in n or not n.endswith('.json'):
            continue
        try:
            d = json.loads(z.read(n).decode('utf-8-sig'))
        except Exception:
            continue
        s = str(d.get('species', '')).split(':')[-1]
        if not s:
            continue
        for v in d.get('variations', []):
            a = frozenset(v.get('aspects') or [])
            sp[s]['vars'].append((a, v.get('model'), v.get('poser'), mod))
            if not a:
                if v.get('model'):
                    sp[s]['base'] = v.get('model')
                if v.get('poser'):
                    sp[s]['basep'] = v.get('poser')

tok = collections.defaultdict(lambda: {'model': set(), 'poser': set(),
                                       'tex': set(), 'mods': set()})
for s, info in sp.items():
    base, basep = info['base'], info['basep']
    for (a, m, p, mod) in info['vars']:
        core = a - {'shiny'}
        if len(core) != 1:
            continue
        e = tok[next(iter(core))]
        e['mods'].add(mod)
        if m and base and m != base:
            e['model'].add(s)
        elif p and basep and p != basep:
            e['poser'].add(s)
        else:
            e['tex'].add(s)

res = {k: {kk: sorted(vv) for kk, vv in v.items()} for k, v in tok.items()}
json.dump(res, open(OUT, 'w'))

mc = sorted(((len(v['model']), k) for k, v in res.items() if v['model']), reverse=True)
print('%d aspect tokens, %d change the model, %d change only the poser'
      % (len(res), len(mc), sum(1 for v in res.values() if v['poser'] and not v['model'])))
print('wrote ' + OUT)
if '-v' in sys.argv:
    for c, k in mc:
        print('  %-34s %3d | %s' % (k, c, ', '.join(res[k]['model'])[:110]))
