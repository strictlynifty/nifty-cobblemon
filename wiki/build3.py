import hashlib
import json, os, html, re, collections

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")

P = json.load(open('/tmp/wiki_parts.json'))     # dex payload + mounts/lm/mnl
D2 = json.load(open('/tmp/wiki_data2.json'))    # items/structures/bait/cuisine/mods
D3 = json.load(open('/tmp/wiki_data3.json'))    # guides/tex/furnies/chipped_fams

# Typos in the SOURCE data, corrected wherever an item id is resolved. "prism_bottle"
# does not exist in any jar; Hoopa's item is prison_bottle, and the typo is in both the
# guide data and the spawn conditions, so fixing it here catches every path.
_ITEM_TYPO = {'prism_bottle': 'mythsandlegends:prison_bottle'}


_BARE_TYPO = {k: v.split(':')[-1] for k, v in _ITEM_TYPO.items()}
_nfix = 0


def _fix_typos(node):
    """Rewrite the bad id wherever it appears in a guide - item, itemName, and the
    mnl.items list that feeds the key-item summary table."""
    global _nfix
    if isinstance(node, dict):
        return {k: _fix_typos(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_fix_typos(v) for v in node]
    if isinstance(node, str):
        if node in _BARE_TYPO:
            _nfix += 1
            return _BARE_TYPO[node]
        if node == 'Prism Bottle':
            _nfix += 1
            return 'Prison Bottle'
        # some sources are pre-baked HTML blobs (P['mnl'] is a 5 KB table) and the
        # payload is one big JSON string - an exact-match test never reaches inside
        # those, so substitute on a word boundary too
        if len(node) > 40:
            out = node
            for _bad, _good in list(_BARE_TYPO.items()) + [('Prism Bottle', 'Prison Bottle')]:
                if _bad in out:
                    new_out = re.sub(r'%s' % re.escape(_bad), _good, out)
                    if new_out != out:
                        _nfix += 1
                        out = new_out
            return out
    return node


P = _fix_typos(P)
D2 = _fix_typos(D2)
D3 = _fix_typos(D3)
if _nfix:
    print('source: corrected %d item typos across P/D2/D3' % _nfix)

# /tmp/wiki_data2.json predates every mod installed after it was generated, so its item
# list has no Cobblemon Cards in it at all - 52 items, a whole tab's worth of content,
# invisible on the Items page. Read them out of the mod's own lang file and splice them
# in; recipes and sources are looked up later by id, so they fill in for free.
#
# Deliberately Cards-only. A blanket sweep of every jar offers ~2,900 rows, but most are
# re-listings of items already present under other ids and it would need a dedupe pass
# that has not been designed yet. Widening this without that pass would silently double
# the page. See WIKI-STATE 'Still to do'.
import zipfile as _cz, glob as _cg
# the Cards page reads this config too, but that block runs much later in the file
try:
    _bchance = float(json.load(open(COBBLEMON_DIR + '/config/cobblemon-cards.json'))
                     .get('boosterChestSpawnChance', 2.0))
except Exception:
    _bchance = 2.0
_have = {str(_r.get('x')) for _r in D2['items'] if _r.get('x')}
_added_items = 0
for _jp in sorted(_cg.glob(COBBLEMON_DIR + '/mods/*.jar')):
    if 'cobblemon-cards' not in os.path.basename(_jp).lower():
        continue
    try:
        _z = _cz.ZipFile(_jp)
    except (IOError, OSError, _cz.BadZipFile):
        continue
    for _n in _z.namelist():
        if not re.match(r'assets/[a-z0-9_.-]+/lang/en_us\.json$', _n):
            continue
        try:
            _lang = json.loads(_z.read(_n).decode('utf-8-sig'))
        except Exception:
            continue
        for _k, _v in _lang.items():
            # the namespace must not contain dots: 'item.cobblemon-cards.card.normal'
            # is a format string, and a greedy namespace turns it into an item called
            # '%s Card' with the id 'normal'
            _m = re.match(r'^(?:item|block)\.([a-z0-9_-]+)\.([a-z0-9_]+)$', _k)
            if not _m:
                continue
            _x = '%s:%s' % (_m.group(1), _m.group(2))
            if _x in _have:
                continue
            _have.add(_x)
            # strip the section-sign colour codes the custom booster uses in its name
            _nm = re.sub(r'§.', '', str(_v)).strip()
            _row = {'i': _m.group(2), 'm': 'Cobblemon Cards', 'n': _nm, 'x': _x}
            if _m.group(2) == 'booster_pack':
                _row['s'] = ['Vanilla chest loot &mdash; %g%% per chest, villages '
                             'excluded. Modded structures never have one.' % _bchance]
            elif _m.group(2).startswith('booster_pack_'):
                _row['s'] = ['Does not generate &mdash; creative menu or an admin only']
            elif _m.group(2) == 'custom_booster_pack':
                _row['s'] = ['Made with the Custom Booster Creator (admin command)']
            D2['items'].append(_row)
            _added_items += 1
    _z.close()
if _added_items:
    print('items: spliced in %d Cobblemon Cards items the source list never had'
          % _added_items)

# A blanket sweep is still off the table, but one narrow slice of it is not: items that are
# MISSING BY ID while their display NAME is already taken by another mod. Those are exactly
# the rows a name collision hides, and they are the ones that mislead - the page listed one
# "Blue Orb", mythsandlegends' (which SUMMONS Kyogre), while mega_showdown's (which triggers
# Primal Reversion) was absent entirely. A reader following the page gets the wrong item.
# Adding only collided ids cannot double the page: it is bounded by the names already there.
# Match on the item's ID PATH, not its display name. Matching names recovered 2,121 rows and
# nearly doubled the page: plenty of mods re-declare a name that already exists without being
# a different item. Two mods shipping the SAME id under different namespaces is the real
# collision - mythsandlegends:blue_orb against mega_showdown:blue_orb - and it is rare.
# Source rows carry `i` and `m` only - the namespaced `x` is derived further down - so key
# the index on the bare id and compare MOD LABELS, not namespaces.
def _modkey(x):
    # 'mega_showdown', 'Mega Showdown' and 'MegaShowdown' are the same mod. Comparing the
    # raw strings made 920 label-spelling differences look like collisions.
    return re.sub(r'[^a-z0-9]', '', str(x).lower())


_byid = {}
for _r in D2['items']:
    _byid.setdefault(str(_r.get('i', '')), set()).add(_modkey(_r.get('m', '')))
_MODLABEL = {'mega_showdown': 'Mega Showdown', 'mythsandlegends': 'MythsAndLegends',
             'cobblemon': 'Cobblemon', 'legendarymonuments': 'Legendary Monuments',
             'rctmod': 'RCT', 'cobblefurnies': 'CobbleFurnies'}
_collided = 0
for _jp in sorted(_cg.glob(COBBLEMON_DIR + '/mods/*.jar')):
    try:
        _z = _cz.ZipFile(_jp)
    except (IOError, OSError, _cz.BadZipFile):
        continue
    for _n in _z.namelist():
        if not re.match(r'assets/[a-z0-9_.-]+/lang/en_us\.json$', _n):
            continue
        try:
            _lang = json.loads(_z.read(_n).decode('utf-8-sig'))
        except Exception:
            continue
        for _k, _v in _lang.items():
            _m = re.match(r'^(?:item|block)\.([a-z0-9_-]+)\.([a-z0-9_]+)$', _k)
            if not _m:
                continue
            _x = '%s:%s' % (_m.group(1), _m.group(2))
            if _x in _have:
                continue
            _nm = re.sub(r'§.', '', str(_v)).strip()
            _lbl = _MODLABEL.get(_m.group(1), _m.group(1))
            _owners = _byid.get(_m.group(2))
            if not _owners or _modkey(_m.group(1)) in _owners or _modkey(_lbl) in _owners:
                continue                     # not a collision - leave the sweep alone
            _have.add(_x)
            D2['items'].append({'i': _m.group(2), 'm': _lbl,
                                'n': _nm, 'x': _x})
            _collided += 1
    _z.close()
if _collided:
    print('items: recovered %d item(s) hidden by a name collision' % _collided)



try:
    _RX = json.load(open('/tmp/wiki_recipes.json'))
except Exception as _e:
    _RX = {}
    print('dex: recipe index missing (%s) - tutorials skipped' % _e)


_MODNAME = {'legendarymonuments': 'Legendary Monuments', 'mythsandlegends': 'Myths & Legends',
            'mega_showdown': 'Mega Showdown', 'cobblemon': 'Cobblemon',
            'minecraft': 'vanilla', 'cobblemon_additions': 'Cobblemon Additions'}


_MODEMOJI = {'legendarymonuments': '🏛️', 'mythsandlegends': '📜',
             'mega_showdown': '💠', 'cobblemon': '⚪', 'minecraft': '🟫',
             'cobblecuisine': '🍳', 'cobblenav': '🧭', 'chipped': '🧱'}
_MODCOLOR = {'legendarymonuments': '#c9a227', 'mythsandlegends': '#8b7bc4',
             'mega_showdown': '#c1543a', 'cobblemon': '#4a8f52', 'minecraft': '#767d92',
             'cobblecuisine': '#b06a28', 'cobblenav': '#3d7ea6', 'chipped': '#8a6f4b'}


def _mod_badge_html(ns):
    """Same badge the Pokedex renders, built server-side for the guides page."""
    if not ns or ns not in _MODNAME:
        return ''
    return ('<span class="mbadge" style="--mb:%s"><span class="mbe">%s</span>%s</span>'
            % (_MODCOLOR.get(ns, '#767d92'), _MODEMOJI.get(ns, '🧩'),
               esc(_MODNAME[ns])))


def _NSFIX(item):
    """Bare path -> namespaced id.

    35 item names in this pack are defined by two mods, so existence alone is not
    enough: resolving "griseous_orb" to the MythsAndLegends copy (no recipe) instead of
    the Mega Showdown one (craftable) loses the whole chain. Prefer a candidate that has
    a real source, then one that at least exists.
    """
    item = _ITEM_TYPO.get(str(item), str(item))
    if ':' in item:
        return item
    cands = (_RX.get('items') or {}).get(item) or []
    if isinstance(cands, str):
        cands = [cands]
    for c in cands:
        if (_RX.get('recipes') or {}).get(c):
            return c
    for c in cands:
        if ((_RX.get('trades') or {}).get(c) or (_RX.get('spawner') or {}).get(c)
                or (_RX.get('mnl_loot') or {}).get(c) or (_RX.get('loot') or {}).get(c)):
            return c
    return cands[0] if cands else item




def esc(s):
    return html.escape(str(s))


NAMES = D3.get('names') or {}


def nice(iid):
    return NAMES.get(iid) or str(iid).replace('_', ' ').title()


def ic(iid, label=None):
    """thumbnail placeholder filled by JS; title shows the full item name"""
    if not iid:
        return ''
    return '<span class="ic" data-i="%s" title="%s"></span>' % (esc(iid), esc(label or nice(iid)))


def _bare_name(b):
    """The old display name: namespace stripped, title-cased, 'Any ' for tags."""
    b = str(b)
    tag = b.startswith('#')
    b = b.lstrip('#')
    ns, _, name = b.partition(':')
    if not name:
        name = ns
    name = name.replace('is_', '').replace('has_', '')
    w = name.replace('/', ' ').replace('_', ' ').strip().title()
    return ('Any ' + w) if tag else w


# Biome ids whose plain name is ALSO a dimension name or a whole family. A player who
# reads "The End" flies to the End, lands on the outer islands and waits forever, because
# minecraft:the_end is the central island biome only. Same trap for "the Nether" when the
# entry actually demands one specific Nether biome. Keyed on the full id.
_END_NOTE = 'central island only, NOT End Highlands/Midlands/Barrens/Small End Islands'
# ALWAYS: the plain name IS a dimension name, so it misleads even mid-list. "The End"
# in any context reads as the End dimension.
DISAMBIG_ALWAYS = {'minecraft:the_end': 'The End (%s)' % _END_NOTE}

# SOLO: one specific Nether biome. Worth flagging when it stands alone, because "I tried
# the Nether" is the exact mistake players make - but stamping it on all five down a list
# of Nether biomes reads as noise, so lists get the bare name.
DISAMBIG_SOLO = dict(DISAMBIG_ALWAYS)
for _b in ('soul_sand_valley', 'nether_wastes', 'crimson_forest',
           'warped_forest', 'basalt_deltas'):
    DISAMBIG_SOLO['minecraft:' + _b] = ('%s (this Nether biome specifically)'
                                        % _b.replace('_', ' ').title())

# A weaker "Forest means exactly this biome, not any forest" note was tried and removed:
# those names are only mildly ambiguous, and the note re-fired inside family samples as
# "55 biomes incl. Badlands (exactly this biome, not any badlands), ...".

_BIO_OK_IDS = set(D3.get('bio_ok') or [])
_TAGS_RESOLVED = {k: v for k, v in (D3.get('tag_map') or {}).items() if v}
# tag_map keys carry namespaces; some sources drop them.
_TAGS_SHORT = {}
for _t, _v in _TAGS_RESOLVED.items():
    _TAGS_SHORT.setdefault(_t.lstrip('#').split(':')[-1], _v)

_MAX_LIST = 5   # beyond this, name the family and sample it


def _resolve(ref):
    """-> list of concrete installed biome ids, or [] if this ref can never match."""
    ref = str(ref)
    if ref.startswith('#'):
        body = ref.lstrip('#')
        hit = _TAGS_RESOLVED.get(ref) or _TAGS_RESOLVED.get('#' + body) \
            or _TAGS_SHORT.get(body.split(':')[-1])
        return [b for b in (hit or []) if b in _BIO_OK_IDS] if hit else []
    if ':' in ref:
        return [ref] if ref in _BIO_OK_IDS else []
    match = [b for b in _BIO_OK_IDS if b.split(':')[-1] == ref]
    return match


# The bare name `_resolve` is REBOUND further down to an item resolver. Anything below
# that point which called pretty_biome() would silently get item lookups back and drop
# every tag-based biome. Keep a stable handle so pretty_biome works from any call site.
_resolve_biome = _resolve


def _one(bid, solo=True):
    table = DISAMBIG_SOLO if solo else DISAMBIG_ALWAYS
    return table.get(bid) or _bare_name(bid)


def pretty_biome(b, solo=True):
    """Name a biome reference the way a player can act on it.

    solo=False means this name will sit in a list of sibling biomes, where the
    "one specific Nether biome" caveat is obvious from context and repeating it on
    every entry is just noise. The End keeps its caveat either way.

    Tags become the biomes they actually resolve to on THIS server rather than an
    internal category name - "Any Spooky" means nothing to a player, "Dark Forest or
    Plains of Death" is something they can walk to. Big families keep the family name
    but carry a sample so the label stays short.
    """
    got = _resolve_biome(b)
    if not got:
        # unresolvable tag: nothing on this server can satisfy it
        return '' if str(b).startswith('#') else _one(str(b), solo=solo)
    if len(got) == 1:
        return _one(got[0], solo=solo)
    if len(got) <= _MAX_LIST:
        names = [_one(g, solo=False) for g in sorted(got)]
        return ', '.join(names[:-1]) + ' or ' + names[-1]
    fam = _bare_name(b)
    # vanilla first - a sample of an overworld family should not open with mod biomes
    ordered = sorted(got, key=lambda g: (g.split(':')[0] != 'minecraft', g))
    sample = ', '.join(_bare_name(g) for g in ordered[:4])
    return '%s - %d biomes incl. %s' % (fam, len(got), sample)


# ---------------- recipe grid ----------------
# Recipe ingredients are often TAGS. "#cobblemon:pokedex_screen" was rendering as an
# item called "Pokedex Screen", which is not craftable and does not exist - it is a tag of
# five substitutes. Draw a real member instead and say it is a choice.
_TAG_PREF = {
    # redstone is the one to name here: it is what the owner actually uses, and it is the
    # cheapest of the five.
    '#cobblemon:pokedex_screen': 'minecraft:redstone',
}


def _tag_members(t):
    out = []
    for m in ((_RX.get('itemtags') or {}).get(t) or []):
        if m.startswith('#'):
            out.extend(_tag_members(m))          # tags nest
        else:
            out.append(m)
    return out


def _tag_pick(t):
    """A real item to draw for a tag, plus how many choices there are."""
    ms = _tag_members(t)
    if not ms:
        return None, 0
    pref = _TAG_PREF.get(t)
    if pref and pref in ms:
        return pref, len(ms)
    van = [m for m in ms if m.startswith('minecraft:')]
    return sorted(van or ms, key=lambda x: (len(x), x))[0], len(ms)


_BARETAG = None


def _bare_tag(name):
    """Guide chain data stores tags with the '#' stripped, so "pokedex_screen" arrives
    looking like an item. Map a bare path back to its tag when no real item owns it."""
    global _BARETAG
    if _BARETAG is None:
        _BARETAG = {}
        for t in (_RX.get('itemtags') or {}):
            _BARETAG.setdefault(t.split(':')[-1].split('/')[-1], t)
    if (_RX.get('items') or {}).get(name):
        return None                       # a real item of that name exists; leave it
    return _BARETAG.get(name)


def _cell_item(c):
    """(basename, tooltip) for one grid cell, resolving tags to something drawable."""
    if not c:
        return None, ''
    if ':' not in c and not c.startswith('#'):
        _t = _bare_tag(c)
        if _t:
            c = _t
    if c.startswith('#'):
        pick, n = _tag_pick(c)
        if pick:
            b = pick.split(':')[-1]
            return b, '%s - or any of the %d %s' % (nice(b), n, nice(c.split(':')[-1]))
        return None, ''
    return c.split(':')[-1], nice(c.split(':')[-1])


# Cobblemon does not craft everything at a bench. Sweets, medicines, aprijuice and mochi
# are COOKED in a Campfire Pot, and berry juices brewed in its own stand. Three separate
# renderers each had their own ad-hoc mapping, and only the item browser named the station -
# elsewhere "cobblemon:cooking_pot_shapeless" surfaced as "Shapeless" or "Potless", which
# reads as "make it in a crafting table". It cannot be, so the recipe looked broken and the
# item looked like a trainer drop.
RKIND = {
    'shaped': 'Shaped', 'shapeless': 'Shapeless', 'furni': 'Furniture bench',
    'pot': 'Campfire Pot', 'potless': 'Campfire Pot (shapeless)',
    'brewing': 'Brewing Stand', 'stonecutting': 'Stonecutter',
    'smelting': 'Furnace', 'blasting': 'Blast Furnace', 'smoking': 'Smoker',
    'campfire_cooking': 'Campfire',
}
# how the same thing reads as a provenance line rather than a station label
RSOURCE = {
    'pot': 'Cooked in a <b>Campfire Pot</b>',
    'potless': 'Cooked in a <b>Campfire Pot</b>',
    'brewing': 'Brewed in a <b>Cobblemon Brewing Stand</b>',
    'furni': 'Made at a <b>Furniture bench</b>',
    'stonecutting': 'Cut on a <b>Stonecutter</b>',
    'smelting': 'Smelted', 'blasting': 'Blasted', 'smoking': 'Smoked',
    'campfire_cooking': 'Cooked on a <b>Campfire</b>',
}


def rkind(k):
    return RKIND.get(k, str(k).replace('_', ' ').title())


def grid_html(r):
    if not r:
        return ''
    if r.get('kind') == 'shaped':
        cells = ''
        for row in r['grid']:
            for c in row:
                b = _cell_item(c)[0] if c else None
                cells += '<div class="cell">%s</div>' % (ic(b) if b else '')
        return '<div class="craft"><div class="grid3">%s</div></div>' % cells
    ings = r.get('ings') or []
    if not ings:
        return ''
    kind = r.get('kind', '')
    lbl = rkind(kind)
    return '<div class="craft"><div class="muted sm">%s</div>%s</div>' % (
        esc(lbl), ' '.join(ic(_cell_item(i)[0] or i) for i in ings))


# ---------------- guides ----------------
guides = D3['guides']

# The "7 Pokemon have no model" blob is stale. They have no model in Cobblemon 1.7.3 or
# any server mod - verified, Cobblemon ships 1,124 and none of the seven - but
# CCCwLegendSpawns_2.1 supplies all seven and is bundled into the client update pack
# everyone here installs. The pack is client-side ONLY, so its 221 spawn-pool files do
# not affect what spawns on this server.
D3['nomodel_html'] = (
    '<div class="card good"><b>The seven modelless Pok&eacute;mon are fixed, client-side.'
    '</b> Raikou, Suicune, Heatran, Cresselia, Virizion, Yveltal and Zeraora have no model '
    'in Cobblemon 1.7.3 or any server-side mod, so on a bare client they render as a green '
    'Substitute Doll. <b>CCCwLegendSpawns_2.1</b> ships proper models for all seven and is '
    'bundled into the client update pack, so they render correctly for everyone here. '
    'A new player who skips that pack sees dolls - the Pok&eacute;mon itself is fine either '
    'way, with its real stats, typing and IVs.<br><br>'
    'That pack also contains 221 spawn-pool files, but it is installed <b>client-side only'
    '</b>, so it does <b>not</b> change what spawns here. Server data governs spawns.</div>')



# ---- rename baked-in biome labels -------------------------------------------------
# mnl2 / spawnconds store DISPLAY strings ("The End", "Any Spooky"), not ids, so the
# improved naming has to be applied by inverting the old naming over the biome and tag
# universes. Deterministic, so the inversion is exact.
def _alias_names(b):
    """Every spelling upstream might have written for this ref.

    The old labels were produced by a different script whose exact transform is not
    recoverable, and it is inconsistent: it kept the '/' in nested tags
    (#cobblemon:nether/is_crimson -> "Any Nether/Crimson") and sometimes kept the
    has_ prefix (#cobblemon:has_block/mud -> "Any Has Block/Mud"). Guessing one
    spelling leaves labels silently unmatched, so enumerate the combinations.
    """
    b = str(b)
    tag = b.startswith('#')
    body = b.lstrip('#')
    ns, _, name = body.partition(':')
    if not name:
        name = ns
    out = set()
    for strip in (True, False):
        n = name
        if strip:
            n = n.replace('is_', '').replace('has_', '')
        for slash in (' ', '/'):
            w = n.replace('/', slash).replace('_', ' ').strip().title()
            w = re.sub(r'\s+', ' ', w)
            if w:
                out.add(('Any ' + w) if tag else w)
    return out


def _tail_name(b):
    """Upstream sometimes kept only the last path segment:
    #cobblemon:has_season/autumn was written plain "Any Autumn"."""
    b = str(b)
    tag = b.startswith('#')
    body = b.lstrip('#')
    ns, _, name = body.partition(':')
    if not name:
        name = ns
    seg = name.split('/')[-1].replace('is_', '').replace('has_', '')
    w = seg.replace('_', ' ').strip().title()
    return (('Any ' + w) if tag else w) if w else ''


_OLD2REF = {}
# exact spellings first, so a precise match always beats a short-form guess
for _b in sorted(_BIO_OK_IDS):
    for _a in _alias_names(_b):
        _OLD2REF.setdefault(_a, _b)
for _t in sorted(_TAGS_RESOLVED):
    for _a in _alias_names(_t):
        _OLD2REF.setdefault(_a, _t)
# then last-segment short forms, filling only the gaps the exact spellings left
for _t in sorted(_TAGS_RESOLVED):
    _a = _tail_name(_t)
    if _a:
        _OLD2REF.setdefault(_a, _t)

_relabelled = collections.Counter()


def _relabel(label, solo=True):
    ref = _OLD2REF.get(str(label))
    if ref is None:
        return str(label)
    new = pretty_biome(ref, solo=solo)
    if not new:
        return ''                      # can never match here - caller drops it
    if new != str(label):
        _relabelled[str(label)] += 1
    return new


def _relabel_list(seq):
    # a one-entry list IS the solo case; more than one and the entries sit beside
    # each other, so the per-biome caveat would repeat down the whole list
    seq = list(seq or [])
    solo = len(seq) == 1
    out = []
    for x in seq:
        n = _relabel(x, solo=solo)
        if n and n not in out:
            out.append(n)
    # A tag that expands to biomes already listed individually produces a redundant
    # combined entry - Meloetta rendered "Cherry Grove, Flower Forest, Meadow,
    # Sunflower Plains, Cherry Grove, Flower Forest, Meadow or Sunflower Plains".
    parts = {o for o in out if ',' not in o and ' or ' not in o}
    out = [o for o in out
           if (',' not in o and ' or ' not in o)
           or not set(re.split(r',\s*| or ', o)).issubset(parts)]
    return out


for _g in guides:
    for _e in (_g.get('mnl2') or []):
        if _e.get('biomes'):
            _before = len(_e['biomes'])
            _e['biomes'] = _relabel_list(_e['biomes'])
            _e['dropped'] = _e.get('dropped', 0) + (_before - len(_e['biomes']))
for _rows in (D3.get('spawnconds') or {}).values():
    for _r in _rows or []:
        if _r.get('bi'):
            _r['bi'] = _relabel_list(_r['bi'])
print('biomes: relabelled %d distinct labels, %d total occurrences'
      % (len(_relabelled), sum(_relabelled.values())))
for _k, _v in _relabelled.most_common(8):
    print('   %-26s x%-4d -> %s' % (_k, _v, pretty_biome(_OLD2REF[_k])[:72]))

# ---- sweep the pre-baked HTML blobs ----------------------------------------------
# myth_html / dossier / notes / craft_html and friends are HTML produced by EARLIER
# scripts, so their biome labels never pass through pretty_biome. Rewrite them here, at
# source, one blob at a time.
#
# Do NOT do this over the assembled page. That was the first attempt and it re-entered
# this module's own output: the renderer emits "Nether Wastes (this Nether biome
# specifically)" and the sweep then matched the bare prefix and appended the note a
# second time, and it stamped the solo qualifier onto every name in a list. Sweeping
# only the untouched blobs keeps renderer output off-limits by construction.
_SWEEP = {k: pretty_biome(v) for k, v in _OLD2REF.items()}
_SWEEP = {k: v for k, v in _SWEEP.items() if v and v != k}
# "#empty" is not a biome tag - it is the marker for a structure that is NOT placed by
# biome at all (the Hall of Origin sits in its own dimension). The old namer turned it
# into "Any Empty", which reads as a biome that does not exist.
_SWEEP['Any Empty'] = 'its own dimension (not placed by biome)'
# every known label is in the alternation, longest first, so "Dyna Plains" consumes
# itself before the inner "Plains" can match; unchanged labels map to themselves
_SWEEP_RE = re.compile(r'(?<!\w)(' + '|'.join(
    re.escape(k) for k in sorted(set(_OLD2REF) | set(_SWEEP), key=len, reverse=True))
    + r')(?! *(?:\(|- *\d+ +biomes))(?!\w)') if _SWEEP else None
_swept = collections.Counter()


def _sweep_text(txt):
    if not txt or _SWEEP_RE is None:
        return txt

    def _swap(m):
        lab = m.group(1)
        new = _SWEEP.get(lab)
        if new is None:
            return lab
        _swept[lab] += 1
        return new

    return _SWEEP_RE.sub(_swap, txt)


for _k in ('myth_html', 'urns_html', 'craft_html', 'research_html', 'pasture_html',
           'pasture_space_html', 'mulch_html', 'rides_html', 'nomodel_html',
           'seats_html', 'system'):
    if isinstance(D3.get(_k), str):
        D3[_k] = _sweep_text(D3[_k])
# Recursive, because the stale labels hide at every depth: guide prose ("That structure
# generates in: Any Nether"), spawncond anticonditions ("not in Any Floral, Any Spooky"),
# and dossier sub-dicts ({"ped": {"bio": "Any Nether"}}). A top-level-strings-only pass
# missed all three.
#
# SKIP is the important half. mnl2['biomes'] and spawnconds['bi'] are already relabelled
# above with list-awareness; sweeping them again would re-add the per-biome caveat that
# the list form deliberately drops.
_SWEEP_SKIP = {'mnl2', 'bi', 'biomes'}


def _sweep_deep(node, key=None):
    if key in _SWEEP_SKIP:
        return node
    if isinstance(node, str):
        return _sweep_text(node)
    if isinstance(node, list):
        return [_sweep_deep(v) for v in node]
    if isinstance(node, dict):
        return {k: _sweep_deep(v, k) for k, v in node.items()}
    return node


for _k in ('dossier', 'notes', 'spawnconds', 'jigsaw', 'trainers'):
    if _k in D3:
        D3[_k] = _sweep_deep(D3[_k])
guides[:] = [_sweep_deep(g) for g in guides]
D3['guides'] = guides
print('blob sweep: rewrote %d labels across %d occurrences'
      % (len(_swept), sum(_swept.values())))
gh = ''
for g in sorted(guides, key=lambda x: x['title']):
    tips = ''.join('<div class="tip">%s</div>' % esc(t) for t in g.get('tips', []))
    steps = []
    ch = g.get('chain')
    if ch:
        subs = ch.get('sub') or []
        if subs:
            for s in subs:
                steps.append('<div class="step"><b>Craft %s %s</b>%s</div>' % (
                    ic(s['item']), esc(s['name']), grid_html(s['r'].get('r'))))
        steps.append('<div class="step"><b>Craft %s %s</b>%s</div>' % (
            ic(g['item']), esc(g['itemName']), grid_html(ch.get('r'))))
    elif not ((g.get('mnl') or {}).get('src')):
        steps.append('<div class="step"><b>Obtain %s %s</b><div class="muted sm">'
                     'No crafting recipe - found in a structure, as loot, or given by a mechanic.</div></div>'
                     % (ic(g['item']), esc(g['itemName'])))
    for rel in g.get('related', []):
        if rel.get('r'):
            steps.append('<div class="step"><b>Craft %s %s</b>%s</div>'
                         % (ic(rel['i']), esc(rel['n']), grid_html(rel['r'])))
        elif rel.get('where'):
            w = rel['where']
            steps.append('<div class="step"><b>Find the %s inside the %s</b>'
                         '<div class="muted sm">That structure generates in: <b>%s</b>.</div>'
                         '<div class="muted sm">The pedestal is a block built into the structure - you interact with '
                         'it there, you do not craft or carry it.</div></div>'
                         % (esc(rel['n']), esc(w[0]), esc(w[1])))
        else:
            steps.append('<div class="step"><b>Obtain %s %s</b>'
                         '<div class="muted sm">No recipe - this is found in the world (structure loot, '
                         'a pedestal you interact with, or dropped by a mechanic).</div></div>'
                         % (ic(rel['i']), esc(rel['n'])))
    if g.get('structs'):
        for s in g['structs']:
            steps.append('<div class="step"><b>Find the %s</b><div class="muted sm">Generates in: %s</div></div>'
                         % (esc(s['id'].title()), esc(', '.join(s['b']))))
    m = g.get('mnl')
    if m:
        if m.get('src'):
            rows = ''.join('<tr><td>%s</td><td><b>%s%%</b></td></tr>' % (esc(s['t']), s['p']) for s in m['src'][:5])
            steps.append('<div class="step"><b>Find %s %s</b>'
                         '<div class="muted sm">It has no recipe - it only appears as chest loot. Best sources:</div>'
                         '<div class="tw"><table><thead><tr><th>Where</th><th>Chance per chest</th></tr></thead><tbody>%s</tbody></table></div>'
                         '<div class="muted sm">These odds are very low by design. The server owner can raise them in '
                         '<code>config/mythsandlegends/loot_tables_config.json</code>.</div></div>'
                         % (ic(m['key']), esc(nice(m['key'])), rows))
        if m.get('shared'):
            steps.append('<div class="step"><b>Note: this key item is shared</b>'
                         '<div class="muted sm">The same %s also works for <b>%s</b>. One bell covers all four - '
                         'there is no requirement to catch any of them first.</div></div>'
                         % (esc(nice(m['key'])), esc(m['shared'])))
        extra = ''
        if m.get('items'):
            try:
                need = ', '.join('%sx %s' % (i.get('count', 1), nice(str(i.get('id', '')).split(':')[-1])) for i in m['items'])
                extra = ('<div class="card bad" style="margin:8px 0 0"><b>This spawn costs you materials.</b>'
                         '<div class="sm">You must also be carrying <b>%s</b>. They are a hard requirement - with even one '
                         'short, it cannot spawn at all - and they are <b>destroyed</b> when it spawns, together with the '
                         '%s itself.</div></div>'
                         % (esc(need), esc(nice(m['key']))))
            except Exception:
                pass
        if not extra:
            extra = ('<div class="card warn" style="margin:8px 0 0"><b>The %s is consumed.</b>'
                     '<div class="sm">On this server it is destroyed the moment the spawn happens. Budget one per '
                     'attempt.</div></div>' % esc(nice(m['key'])))
        ents = g.get('mnl2')
        if ents:
            blocks = ''
            for e in ents:
                if not e.get('biomes'):
                    continue
                notes = ''.join('<div class="tip">%s</div>' % n for n in e.get('notes', []))
                blocks += ('<div class="alt" style="margin:8px 0 0"><b>Option: %s</b>'
                           '<div class="sm" style="margin:4px 0"><b>Biomes:</b> %s</div>'
                           '<div class="muted sm">You must be <b>%s</b>. Level %s.</div>%s</div>'
                           % (esc(', '.join(e['biomes'][:3]) + (' ...' if len(e['biomes']) > 3 else '')),
                              esc(', '.join(e['biomes'])), esc(e.get('ctx') or 'on the ground'),
                              esc(e.get('lvl') or '?'), notes))
            dropped = sum(e.get('dropped', 0) for e in ents)
            drop_note = ('<div class="muted sm">(%d biome entries in the mod files refer to biomes from mods '
                         'that are <b>not installed here</b> - they are hidden because they can never match.)</div>'
                         % dropped) if dropped else ''
            steps.append('<div class="step"><b>Hold %s %s and <u>right-click it</u></b>'
                         '<div class="muted sm">This is the reliable way. Right-clicking searches a '
                         '<b>100 x 50 x 100 area around you</b> and tries <b>400 times</b> to place it - so it '
                         'either works within a second or tells you why not. A plain right-click; '
                         '<b>sneaking does nothing</b>. There is <b>no cooldown and no use limit</b> on this '
                         'server, so you can retry as fast as you like.</div>'
                         '<div class="muted sm">Simply carrying it also works, but it is a <b>0.2%%</b> ultra-rare '
                         'roll you could wait hours for. Carrying is what makes it <i>possible</i>; '
                         'right-clicking is what makes it <i>happen</i>.</div>'
                         '<div class="tip" style="margin-top:6px"><b>Right-clicking does not skip a single '
                         'condition.</b> It builds a spawn zone around you and asks the game 400 times whether a '
                         'spawn is legal right there - biome, <b>time of day</b> and what you are standing on are '
                         'all still checked. It only removes the waiting, never the rules. If you see '
                         '<i>&quot;No Pok&eacute;mon matching ... conditions could be found for spawning&quot;</i>, '
                         'one of the rules below is not satisfied <b>right now</b>. The trap is time of day: a '
                         'night-only summon fails all 400 tries in daylight and starts working the moment the sun '
                         'goes down.</div></div>'
                         % (ic(m['key']), esc(nice(m['key']))))
            steps.append('<div class="step"><b>Be somewhere it can actually spawn</b>'
                         '<div class="muted sm">Each option below is a separate rule - you need to satisfy '
                         '<b>all</b> of one option, not a mix.</div>%s%s%s</div>' % (blocks, drop_note, extra))
        else:
            steps.append('<div class="step"><b>Carry %s %s in your inventory and go to one of these biomes</b>'
                         '<div class="muted sm"><b>%s</b></div>'
                         '<div class="muted sm">It does <b>not</b> have to be in your hand. Anywhere in your 36 main '
                         'inventory slots counts, <b>including inside a shulker box or bundle</b>. It does <b>not</b> '
                         'count in your off-hand or armour slots. After you move it, allow up to <b>3 minutes</b> '
                         'before it registers. Level %s, ultra-rare bucket (0.2%%), so expect to wait.</div>%s</div>'
                         % (ic(m['key']), esc(nice(m['key'])),
                            esc(', '.join(m['biomes'])), esc(m.get('lvl') or '?'), extra))
    alt = g.get('alt')
    altbox = ''
    if alt:
        lis = ''.join('<li>%s</li>' % s for s in alt['steps'])
        altbox = '<div class="alt"><b>%s</b><ol>%s</ol></div>' % (esc(alt['title']), lis)
    _gmod = _NSFIX(str(g.get('item') or '')).split(':')[0] if g.get('item') else ''
    _gbadge = _mod_badge_html(_gmod)
    gh += ('<div class="guide" data-title="%s" data-name="%s"><h3>%s%s</h3>%s'
           '<div class="steps">%s</div>%s</div>'
           % (esc(g["title"]), esc((g['title'] + ' ' + _MODNAME.get(_gmod, '')).lower()),
              esc(g['title']), _gbadge, tips, ''.join(steps), altbox))

# ---------------- furnies ----------------
def recipe_html(item_id, compact=False):
    """Render a recipe from the index: real 3x3 grid when shaped, chips otherwise.

    Both the furniture and cooking pages previously showed either an empty list or a
    line of raw text. The thumbnails and grid CSS already existed - they just were
    not used outside the Pokedex.
    """
    rid = _NSFIX(item_id)
    rows = (_RX.get('recipes') or {}).get(rid) or []
    if not rows:
        return ''
    r = rows[0]
    kind = rkind(r['kind'])
    out = '<div class="tcraft"><span class="tkind">%s</span>' % esc(kind)
    if r.get('grid'):
        cells = ''
        for row in r['grid']:
            for c in row:
                b, tip = _cell_item(c)
                cells += ('<div class="tcell">%s</div>'
                          % ('<span class="ic" data-i="%s" title="%s"></span>'
                             % (esc(b), esc(tip)) if b else ''))
        out += '<div class="tgrid">%s</div>' % cells
    for g in r['ings']:
        b, tip = _cell_item(g['i'])
        if b is None:
            b, tip = g['i'].split(':')[-1], nice(g['i'].split(':')[-1])
        label = nice(b)
        if str(g['i']).startswith('#'):
            _, _n = _tag_pick(g['i'])
            label = '%s <span class="muted">(or %d alternatives)</span>' % (nice(b), _n - 1)
        out += ('<span class="ting"><span class="ic icsm" data-i="%s" title="%s"></span>'
                '%s&times; %s</span>' % (esc(b), esc(tip), g['n'], label))
    return out + '</div>'


fh = '<div class="fgrid">'
for f in D3['furnies']:
    _fr = recipe_html(f['i']) or grid_html(f.get('r'))
    fh += '<div class="fcard" data-s="%s"><div class="fh">%s <b>%s</b></div>%s</div>' % (
        esc((f['n'] + ' ' + f['i']).lower()), ic(f['i']), esc(f['n']), _fr)
fh += '</div>'

# ---------------- chipped ----------------
fams = D3['chipped_fams']
_famcount = {k: v for k, v in fams}

# Which bench handles what. Chipped ships one chipped:workbench recipe per bench whose
# "ingredients" are the block tags it accepts - so the split is declared, not guessed.
BENCH_BLURB = {
    'mason_table': 'Stone and rock: cobblestone, andesite, deepslate, blackstone, calcite, basalt, prismarine, ancient debris.',
    'carpenters_table': 'Everything wooden - every plank type, and the log and stem families.',
    'glassblower': 'Glass and glass panes, including all sixteen stained colours.',
    'loom_table': 'Wool and carpet, all sixteen colours.',
    'alchemy_bench': 'Gem and mineral blocks: amethyst, diamond, emerald, gold, lapis, coal, crying obsidian, lodestone.',
    'botanist_workbench': 'Earth and growing things: dirt, clay, mud, leaves, ice, snow.',
    'tinkering_table': 'Metal, redstone and lighting: iron bars, lanterns, sea lanterns, redstone lamps.',
}
BENCH_ORDER = ['mason_table', 'carpenters_table', 'glassblower', 'loom_table',
               'alchemy_bench', 'botanist_workbench', 'tinkering_table']

_bench_tags = {}
try:
    import zipfile as _zf
    _cz = _zf.ZipFile(COBBLEMON_DIR + '/mods/chipped-fabric-1.21.1-4.0.2.jar')
    for _n in _cz.namelist():
        if '/recipe' not in _n or not _n.endswith('.json'):
            continue
        try:
            _d = json.loads(_cz.read(_n).decode('utf-8-sig'))
        except Exception:
            continue
        if _d.get('type') == 'chipped:workbench':
            _bench = _n.split('/')[-1][:-5]
            _bench_tags[_bench] = [str(t.get('tag', '')).split(':')[-1]
                                   for t in (_d.get('ingredients') or []) if t.get('tag')]
except Exception as _e:
    print('chipped: could not read the jar (%s)' % _e)

chh = ''
if _bench_tags:
    chh += ('<div class="card">Chipped does not add recipes you memorise &mdash; it adds '
            '<b>seven workbenches</b>. Put a block in one and it shows you every variant '
            'of that block, one click each. Which bench you need depends on the material.</div>')
    chh += '<div class="sgrid">'
    for _b in BENCH_ORDER:
        if _b not in _bench_tags:
            continue
        _tags = _bench_tags[_b]
        _var = sum(_famcount.get(t, 0) for t in _tags)
        chh += ('<div class="scard">%s<b>%s</b>'
                '<div class="muted sm">%s</div>'
                '<div class="bchips">%s</div>'
                '<div class="strack"><b>%d</b> base blocks accepted'
                '%s</div></div>'
                % (ic(_b), esc(_b.replace('_', ' ').title()),
                   esc(BENCH_BLURB.get(_b, '')),
                   ''.join('<span class="bchip b-other">%s</span>' % esc(nice(t))
                           for t in _tags[:10])
                   + ('<span class="bchip b-other">+%d more</span>' % (len(_tags) - 10)
                      if len(_tags) > 10 else ''),
                   len(_tags),
                   (', <b>%d</b> variants in total' % _var) if _var else ''))
    chh += '</div>'
    print('chipped: %d benches, %d families' % (len(_bench_tags), len(fams)))

chh += '<h3>Every family, and how many variants it has</h3>'
chh += ('<div class="sqrow"><input id="chipq" type="search" '
        'placeholder="Filter families - try &quot;stone&quot;, &quot;wool&quot;, &quot;glass&quot;">'
        '<span class="sqhint" id="chipcnt"></span></div>')
chh += '<div class="tw"><table><thead><tr><th>Base block family</th><th>Variants</th></tr></thead><tbody>'
for k, v in fams:
    chh += ('<tr data-s="%s"><td>%s %s</td><td><b>%d</b></td></tr>'
            % (esc(k.replace('_', ' ').lower()), ic(k), esc(k.replace('_', ' ').title()), v))
chh += '</tbody></table></div>' 

# ---------------- structures (pretty biomes) ----------------
# D2['structures'] is prebuilt and is not regenerated by this build, so a newly added
# structure mod is invisible on the Structures page. Discover them from the jars instead:
# every worldgen/structure/*.json that D2 has never heard of gets merged in, which means
# the next structure mod needs no code change at all.
import glob as _glob2
import zipfile as _zip2

_KNOWN = {s['id'] for s in D2['structures']}
# The prebuilt list uses display names ('Cobblemon'); jar paths give namespaces
# ('cobblemon', 'bca'). Without mapping them the page grows duplicate sections.
_MODNICE = {'rgs': 'Radical Gyms', 'cobblemon': 'Cobblemon',
            'bca': 'cobblemon-additions', 'mega_showdown': 'mega_showdown',
            'legendarymonuments': 'legendarymonuments',
            'rctmod': 'Radical Trainers', 'cobbreeding': 'Cobbreeding',
            'cobblefurnies': 'CobbleFurnies', 'rustlingspots': 'Rustling Spots'}
_nnew = 0
for _jp in sorted(_glob2.glob(COBBLEMON_DIR + '/mods/*.jar')):
    try:
        _z = _zip2.ZipFile(_jp)
    except (IOError, OSError, _zip2.BadZipFile):
        continue
    for _n in _z.namelist():
        _pt = _n.split('/')
        if (len(_pt) < 5 or _pt[0] != 'data' or _pt[2] != 'worldgen'
                or _pt[3] != 'structure' or not _n.endswith('.json')):
            continue
        _sid = '/'.join(_pt[4:])[:-5]
        if _sid in _KNOWN:
            continue
        try:
            _d = json.loads(_z.read(_n).decode('utf-8-sig'))
        except Exception:
            continue
        _b = _d.get('biomes')
        _blist = ([_b] if isinstance(_b, str) else list(_b or []))
        D2['structures'].append({
            'id': _sid, 'mod': _MODNICE.get(_pt[1], _pt[1]),
            'b': _blist, 'step': _d.get('step'), 'sp': None, 'sep': None})
        _KNOWN.add(_sid)
        _nnew += 1
    _z.close()
if _nnew:
    print('structures: %d discovered from jars that the prebuilt list did not have' % _nnew)

by_mod = collections.defaultdict(list)
for s in D2['structures']:
    by_mod[s['mod']].append(s)
icons = D2['icons']


def icon_for(sid):
    for k in (sid, sid + '_icon', sid.replace('_cave', ''), sid.replace('_temple', '')):
        if k in icons:
            return '<img class="ico" alt="" src="data:image/png;base64,%s">' % icons[k]
    return ''


NBT = {}
try:
    NBT = json.load(open('/tmp/struct_nbt.json'))
except Exception:
    pass

LAYER = {'surface_structures': 'on the surface', 'underground_structures': 'underground',
         'underground_decoration': 'underground', 'top_layer_modification': 'at the very top layer',
         'lakes': 'in lakes', 'raw_generation': 'as raw terrain'}


def describe(s):
    """honest, derived description of a structure"""
    bits = []
    n = NBT.get(s['id'])
    if n and n.get('size') and len(n['size']) == 3:
        w, h, d = n['size']
        scale = 'huge' if max(w, h, d) > 90 else ('large' if max(w, h, d) > 45 else
                 ('small' if max(w, h, d) < 18 else 'medium-sized'))
        bits.append('A %s structure, about %d x %d x %d blocks' % (scale, w, h, d))
    elif n:
        bits.append('A structure')
    else:
        bits.append('Assembled from multiple pieces, so its size varies')
    if n and n.get('top'):
        mats = ', '.join(t.replace('_', ' ') for t in n['top'][:4])
        bits.append('built mainly from %s' % mats)
    where = ', '.join(pretty_biome(x) for x in s['b'])
    layer = LAYER.get(s.get('step') or '', '')
    tail = 'Generates in %s' % where if where else 'Biome unknown'
    if layer:
        tail += ', %s' % layer
    bits2 = '. '.join([', '.join(bits), tail])
    if s.get('sp'):
        bits2 += '. Roughly one every %s blocks' % format(int(s['sp']) * 16, ',')
    return bits2 + '.'


# What the Arc Phone needs you to CARRY before it will locate each structure.
# Read out of LegendaryTrackingServerHandler.getRequiredItemFor - the switch pairs
# structure path to item in order. Confirmed by 14 unambiguous semantic matches
# (Ecruteak->Clear Bell, Snowpoint->Golem Scrap, Spear Pillar->Red Chain,
# Dyna Tree->Cherry Sapling, Amphitheater->Disc of the First Song, Liberty Island->
# Liberty Pass, the four shrines to their own Seals, ...).
ARC_TRACK = {
    'dragonspiraltower': 'Lightstone Shard', 'turnback_cave': 'Trial Key',
    'traditional_village': 'Clear Bell', 'heatran_cave': 'Magma Stone',
    'firescourge_shrine': 'Firescourge Seal', 'grasswither_shrine': 'Grasswither Seal',
    'groundblight_shrine': 'Groundblight Seal', 'icerend_shrine': 'Icerend Seal',
    'outskirt_stand': 'Emerald', 'southern_island': 'Axolotl Bucket',
    'lugia_temple': 'Vortex Stone', 'hoopa_pyramid': 'End Rod',
    'eternatus_cocoon': 'Galar Particle',
    'crown_shrine': 'Iceroot Carrot Seeds or Shaderoot Carrot Seeds',
    'throneroom_of_knightly_heroes': 'Totem of Undying', 'yveltal_cocoon': 'Soul Jar',
    'tree_of_life': 'Aurora Essence Jar', 'amphitheater': 'Disc of the First Song',
    'kyuremcave': 'Ideals Bottle', 'dyna_tree': 'Cherry Sapling',
    'giratina_island': 'Origin Ingot', 'final_island': 'Old Sea Map',
    'snowpoint_temple': 'Golem Scrap', 'spear_pillar': 'Red Chain',
    'lake_valor': 'Fermented Spider Eye', 'lake_acuity': 'Sweet Berries',
    'lake_verity': 'Glow Berries', 'liberty_island': 'Liberty Pass',
}

# colour a biome chip by the family a player actually thinks in
BIOME_CLASS = (
    ('nether', ('nether', 'crimson', 'warped', 'basalt', 'soul sand')),
    ('end', ('the end', 'end ', 'small end')),
    ('cold', ('snow', 'frozen', 'ice', 'glacial', 'taiga', 'grove', 'peak', 'tundra')),
    ('hot', ('desert', 'badlands', 'savanna', 'mesa')),
    ('wet', ('ocean', 'river', 'beach', 'swamp', 'shore', 'coast', 'reef')),
    ('lush', ('jungle', 'forest', 'flower', 'meadow', 'plains', 'grove', 'lush', 'cherry')),
    ('cave', ('cave', 'dripstone', 'deep dark', 'underground')),
)


def biome_chips(s):
    out = []
    for raw in s['b']:
        name = pretty_biome(raw)
        if not name:
            continue
        low = name.lower()
        cls = 'other'
        for c, keys in BIOME_CLASS:
            if any(k in low for k in keys):
                cls = c
                break
        out.append('<span class="bchip b-%s">%s</span>' % (cls, esc(name)))
    return ''.join(out)


# Some structures need something ON ARRIVAL that no generated field can express. The
# Amphitheater is the case that cost real play time: its card named the structure, the
# Pokemon and the tracking item, and never mentioned the four vanilla discs. The full
# walkthrough lives on the dex entry, but nobody searches the dex while standing in the
# building - they read the Structures card.
STRUCT_NOTE = {
    'amphitheater':
        'Bring <b>four vanilla music discs</b> &mdash; <b>Pigstep</b>, <b>5</b>, '
        '<b>Creator</b> and <b>Relic</b> &mdash; and put one in each ordinary jukebox, then '
        'right-click the Meloetta Jukebox holding the Disc of the First Song. Order and '
        'placement do not matter, but all four must be within <b>20 blocks</b>. '
        '<b>Watch out: &ldquo;Creator (Music Box)&rdquo; is a different item and does not '
        'count.</b> Creator comes from an <b>ominous vault</b>; the Music Box comes from '
        'corridor pots, so it is the one you pick up by accident.',
}


def arc_track_for(sid):
    for k, v in ARC_TRACK.items():
        if sid == k or sid.startswith(k):
            return v
    return None


# The Arc Phone is the thing that makes this page usable in game - it is what carries a
# tracking item and points you at a structure. It had its own entry on the guides page and
# nowhere else, so it moves here rather than into any one Pokedex entry: it is not tied to
# a species.
# The dex is not loaded yet at this point, so spell the awkward ones out.
_SPNAME = {'hooh': 'Ho-Oh', 'chienpao': 'Chien-Pao', 'chiyu': 'Chi-Yu',
           'wochien': 'Wo-Chien', 'tinglu': 'Ting-Lu', 'regieleki': 'Regieleki',
           'regidrago': 'Regidrago', 'glastrier': 'Glastrier',
           'spectrier': 'Spectrier'}

sh = ('<h3>The Arc Phone</h3>'
      '<div class="card">Every &ldquo;track with&rdquo; below means the <b>Arc Phone</b>. '
      'Hold the listed item and the phone points you at the nearest one. It also carries '
      'your PC, an ender chest, a heal button, the Pok&eacute;dex, quests and system '
      'upgrades &mdash; the upgrades are bought in-phone and widen what it can track.'
      '</div>')
_arc = recipe_html('legendarymonuments:arc_phone')
if _arc:
    sh += ('<div class="card"><b>Crafting it.</b> The centre-bottom slot takes a single '
           '<b>redstone dust</b>. Recipe browsers call that slot a &ldquo;Pok&eacute;dex '
           'Screen&rdquo;, which is <b>not an item and cannot be crafted</b> &mdash; it is '
           'a tag covering five substitutes (redstone, glowstone dust, blaze powder, glow '
           'ink sac or Bright Powder). Redstone is the cheapest, so that is what is drawn '
           'below.%s</div>' % _arc)

sh += ''
for mod in sorted(by_mod):
    rows = sorted(by_mod[mod], key=lambda x: x['id'])
    sh += '<h3>%s <span class="muted">(%d)</span></h3>' % (esc(mod), len(rows))
    sh += '<div class="sgrid">'
    for s in rows:
        _chips = biome_chips(s)
        _trk = arc_track_for(s['id'])
        _trkhtml = ('<div class="strack"><b>Arc Phone:</b> carry <b>%s</b> to track it</div>'
                    % esc(_trk)) if _trk else ''
        _note = STRUCT_NOTE.get(s['id'])
        _notehtml = ('<div class="card warn sm" style="margin:8px 0 0">%s</div>'
                     % _note) if _note else ''
        # Which Pokemon this structure is actually for. Nothing in the pack says it, and
        # "track the Throne Room of Knightly Heroes" is useless if you do not know that is
        # where Zacian and Zamazenta are.
        _mons = (_RX.get('structmons') or {}).get(s['id']) or []
        _monhtml = ''
        if _mons:
            _pretty = [_SPNAME.get(m) or nice(m) for m in _mons]
            _monhtml = ('<div class="smons"><b>Pok&eacute;mon:</b> %s</div>'
                        % esc(', '.join(sorted(_pretty))))
        _search = (s['id'] + ' ' + mod + ' ' +
                   ' '.join(pretty_biome(x) for x in s['b']) + ' ' + (_trk or '') + ' ' +
                   ' '.join(_mons)).lower()
        sh += ('<div class="scard" data-s="%s">%s<b>%s</b>'
               '<div class="muted sm">%s</div>%s%s</div>'
               % (esc(_search), icon_for(s['id']),
                  esc(s['id'].replace('_', ' ').title()), esc(describe(s)),
                  ('<div class="bchips">%s</div>' % _chips) if _chips else '',
                  _monhtml + _trkhtml + _notehtml))
    sh += '</div>'

# ---------------- bait with icons ----------------
EFF = {'shiny_reroll': 'Extra shiny roll', 'ha_chance': 'Hidden Ability chance',
       'rarity_bucket': 'Shifts rarity bucket', 'iv': 'Guaranteed IVs', 'ev': 'EV yield',
       'nature': 'Influences nature', 'typing': 'Attracts type', 'egg_group': 'Attracts egg group',
       'level_raise': 'Higher level', 'friendship': 'Starting friendship',
       'gender_chance': 'Gender bias', 'bite_time': 'Faster bite', 'pokemon_chance': 'Higher catch rate',
       'drops_reroll': 'Extra drops roll'}
STAR = {'shiny_reroll', 'ha_chance', 'rarity_bucket'}
bh = '<div class="tw"><table><thead><tr><th>Berry</th><th>Effect</th></tr></thead><tbody>'
for b in sorted(D2['bait'], key=lambda x: (not any(e['t'] in STAR for e in x['e']), x['i'])):
    eff = []
    for e in b['e']:
        lbl = EFF.get(e['t'], e['t'])
        ex = []
        if e.get('s'):
            ex.append(e['s'])
        if e.get('c') is not None and e['c'] != 1.0:
            ex.append('%d%%' % round(float(e['c']) * 100))
        cls = 'pill hot' if e['t'] in STAR else 'pill'
        eff.append('<span class="%s">%s%s</span>' % (cls, esc(lbl), (' ' + esc(' '.join(ex))) if ex else ''))
    bh += '<tr><td>%s <b>%s</b></td><td>%s</td></tr>' % (ic(b['i']), esc(b['i'].replace('_', ' ').title()), ' '.join(eff))
bh += '</tbody></table></div>'

# ---------------- cuisine with icons ----------------
cu = D2['cuisine'].get('items', [])
ch2 = '<div class="tw"><table><thead><tr><th>Item</th><th>What it does</th><th>Recipe</th></tr></thead><tbody>'
_nlegacy = 0
for it in cu:
    if '[LEGACY]' in str(it.get('n', '')):
        _nlegacy += 1
        continue
    tips = ' '.join(esc(t) for t in it['t']) or '<span class="muted">-</span>'
    rec = recipe_html(it['i'])
    if not rec:
        # fall back to parsing the stored "shapeless:: a + b + c" string
        parts = []
        for raw in it['r']:
            kind, _, body = str(raw).partition('::')
            chips = ''
            for tok in [x.strip() for x in body.split('+') if x.strip()]:
                b = tok.split(':')[-1]
                chips += ('<span class="ting"><span class="ic icsm" data-i="%s"></span>%s</span>'
                          % (esc(b), esc(nice(b))))
            if chips:
                parts.append('<div class="tcraft"><span class="tkind">%s</span>%s</div>'
                             % (esc(kind.strip().title() or 'Recipe'), chips))
        rec = ''.join(parts)
    rec = rec or '<span class="muted">-</span>'
    ch2 += ('<tr data-s="%s"><td>%s <b>%s</b></td><td>%s</td><td>%s</td></tr>'
            % (esc((it['n'] + ' ' + it['i']).lower()), ic(it['i']), esc(it['n']), tips, rec))
ch2 += '</tbody></table></div>'
print('cuisine: %d items rendered, %d legacy hidden' % (len(cu) - _nlegacy, _nlegacy))

# ---------------- trainer series walkthroughs ----------------
# What you need standing at the Trainer Spawner is the ORDER and the SIGNATURE ITEM.
# Both come from rctmod's mob files (requiredDefeats gives the dependency graph,
# signatureItem gives the spawner item); neither was ever on the wiki.
SERIES_LABEL = {'radicalred': 'Kanto', 'bdsp': 'Sinnoh', 'unbound': 'Unbound'}
SERIES_NOTE = {
    'radicalred': 'Radical Red - a Kanto run. Brock through the Elite Four.',
    'bdsp': 'Brilliant Diamond / Shining Pearl - the Sinnoh gyms, with Team Galactic between them.',
    'unbound': 'Pokemon Unbound - the longest of the three, with Team Shadow throughout.',
}
try:
    _TR = json.load(open('/tmp/wiki_trainers.json'))
except Exception as _e:
    _TR = {}
    print('trainers: walkthrough data missing (%s)' % _e)

th = ''
if _TR:
    th += '<div class="srow">'
    for _k in ('radicalred', 'bdsp', 'unbound'):
        if _k in _TR:
            th += ('<button class="sbtn%s" data-series="%s">%s</button>'
                   % (' on' if _k == 'radicalred' else '', _k, esc(SERIES_LABEL[_k])))
    th += '</div>'
    for _k in ('radicalred', 'bdsp', 'unbound'):
        rows = _TR.get(_k) or []
        th += ('<div class="spanel%s" data-series="%s">'
               % (' on' if _k == 'radicalred' else '', _k))
        th += '<div class="muted sm" style="margin:0 0 10px">%s</div>' % esc(SERIES_NOTE.get(_k, ''))
        th += ('<div class="tw"><table><thead><tr><th>#</th><th>Trainer</th><th>Type</th>'
               '<th>Highest Lv</th><th>Where to fight</th></tr></thead><tbody>')
        _n = 0
        for r in rows:
            if r.get('opt'):
                continue                     # optional side trainers are not the path
            _n += 1
            it = r.get('item')
            bare = it.split(':')[-1] if it else None
            cell = ('<span class="ic icsm" data-i="%s"></span><b>%s</b> in the spawner'
                    % (esc(bare), esc(nice(bare)))) if bare else                    '<span class="muted">spawns on its own</span>'
            # Eight of these also stand in a Kanto gym structure out in the world. Fighting them
            # there keeps the level cap on; the spawner ignores it. Give both, so the choice is
            # visible at the point of decision rather than in a separate list.
            if r.get('gym'):
                cell += ('<div class="muted sm" style="margin-top:3px">or go to %s</div>'
                         % esc(r['gym']))
            times = (' <span class="pill">beat %d times</span>' % r['count']) if r.get('count', 1) > 1 else ''
            # A spawner-summoned trainer IGNORES the level cap, so this is the number a player
            # needs before the fight - not something to hunt for further down the page.
            _hi, _lo = r.get('lvl'), r.get('lvlLo')
            if _hi and _lo and _lo != _hi:
                lvcell = '<b>%d</b><span class="muted">-%d</span>' % (_lo, _hi)
            elif _hi:
                lvcell = '<b>%d</b>' % _hi
            else:
                lvcell = '<span class="muted">-</span>'
            th += ('<tr><td class="muted">%d</td><td><b>%s</b>%s</td><td>%s</td>'
                   '<td class="nowrap">%s</td><td>%s</td></tr>'
                   % (_n, esc(r['n']), times, esc(r['t']), lvcell, cell))
        th += '</tbody></table></div></div>'
    print('trainers: %s' % ', '.join('%s %d steps' % (SERIES_LABEL[k],
          sum(1 for r in v if not r.get('opt'))) for k, v in _TR.items() if k in SERIES_LABEL))

# ---------------- mounts sub-tabs ----------------
mounts = collections.defaultdict(list)
LABEL = {'AIR': 'Flight', 'LAND': 'Ground', 'LIQUID': 'Water'}
PAYOBJ = _fix_typos(json.loads(P['payload']))   # payload is a JSON *string*, so the
                                               # load-time pass could not reach inside it
dex = PAYOBJ['dex']

# --- enrich the dex with what the Pokedex was silently omitting -------------
# 1. the materials an M&L key-item spawn destroys   2. the Legendary Monuments
# route (structure + pedestal), which the dex never mentioned at all.
def _norm(s):
    return re.sub(r'[^a-z]', '', str(s).lower())


# Guide titles are not bare species names ("Summon Heatran with a Magma Stone"),
# so match the LONGEST dex name the title starts with - longest-first keeps
# "Summon Mewtwo" from being claimed by Mew.
_dexnames = sorted({_norm(p.get('n')) for p in dex if p.get('n')}, key=len, reverse=True)


def _mon_of(title):
    # Match the species as a WHOLE WORD anywhere in the title first. Prefix-only matching
    # missed "Summon the Dragon of Truths Reshiram" and "Earn Calyrex", orphaning their
    # content on a standalone page with no dex entry to hold it. Word-exact, so "Mew"
    # never claims "Mewtwo".
    words = {re.sub(r'[^a-z0-9]', '', w.lower()) for w in re.split(r'[\s\-/]+', str(title))}
    for n in _dexnames:
        if n and n in words:
            return n
    gt = _norm(re.sub(r'^\s*summon\s+', '', title, flags=re.I))
    for n in _dexnames:
        if n and gt.startswith(n):
            return n
    return None


# Every one of these pedestals consumes an item. The page used to claim the opposite -
# "this route needs no key item and no biome luck" - for all of them, which sent people to
# the Burned Tower to stand in front of a pedestal that does nothing. Read out of each
# *PedestalBlockEntity class: the item it validates before spawning.
_PED_NEEDS = {
    'entei': 'Entei Treat', 'raikou': 'Raikou Treat', 'suicune': 'Suicune Treat',
    'latias': 'Latias Treat', 'latios': 'Latios Treat',
    'hooh': 'Rainbow Feather', 'heatran': 'Magma Stone',
    'dialga': 'Red Chain', 'palkia': 'Red Chain', 'giratina': 'Griseous Orb',
    'kyurem': 'Truth Bottle and an Ideals Bottle',
    'reshiram': 'Lightstone', 'zekrom': 'Darkstone',
    'zacian': 'Hero Sword and a Totem of Undying',
    'zamazenta': 'Hero Shield and a Totem of Undying',
    'hoopa': 'Prison Bottle and a Temple Key',
    'lugia': 'Lugia Key or a Vortex Stone',
    'mew': 'Old Sea Map or a Tuft of Mew Hair',
}

_req, _ped = {}, {}
for g in guides:
    mon = _mon_of(g['title'])
    if not mon:
        continue
    m = g.get('mnl') or {}
    if m.get('items'):
        try:
            _req[mon] = ', '.join('%sx %s' % (i.get('count', 1), nice(str(i.get('id', '')).split(':')[-1]))
                                  for i in m['items'])
        except Exception:
            pass
    # prefer the pedestal itself over other locked blocks in the same structure
    rels = [r for r in g.get('related', []) if r.get('where')]
    rels.sort(key=lambda r: 'pedestal' not in str(r.get('n', '')).lower())
    _need = _PED_NEEDS.get(mon)
    _art = 'an' if _need and _need[0].upper() in 'AEIOU' else 'a'
    _tail = ((' You must put %s <b>%s</b> in it &mdash; the pedestal alone does nothing.'
              % (_art, _need)) if _need
             else ' No key item is needed for this one.')
    if rels:
        r0 = rels[0]
        _ped[mon] = ('Find the <b>%s</b> inside the <b>%s</b> (generates in %s) and use it.%s'
                     % (esc(r0['n']), esc(r0['where'][0]), esc(r0['where'][1]), _tail))
    elif g.get('whereOwn'):
        w = g['whereOwn']
        _ped[mon] = ('Find the <b>%s</b> at the <b>%s</b> (generates in %s) and use it.%s'
                     % (esc(g.get('itemName') or 'pedestal'), esc(w[0]), esc(w[1]), _tail))

# Strip biomes that cannot exist here (Terralith/BYG/Wythers are not installed).
# Without this the Pokedex sends players hunting for biomes that do not generate.
# Replace the dex spawn rows with the full-condition extraction. The old rows carried
# biome + bucket only, which is why the Pokedex disagreed with what players saw in game
# (Greninja needs water nearby, Ogerpon needs a waning gibbous, etc).
_SC = D3.get('spawnconds') or {}
_FULL = set()          # mons whose biomes are already resolved - the filter below must skip them
if _SC:
    _sc = {re.sub(r'[^a-z0-9]', '', k.lower()): v for k, v in _SC.items()}
    _nrep = _nc = 0
    for p in dex:
        key = re.sub(r'[^a-z0-9]', '', str(p.get('n', '')).lower())
        rows = _sc.get(key)
        if rows:
            p['sp'] = rows
            _FULL.add(key)
            _nrep += 1
            _nc += sum(1 for r in rows if r.get('c'))
    print('dex: %d mons given full spawn conditions (%d rows with hidden gates)' % (_nrep, _nc))

# attach the per-mon dossier + search blob so the Pokedex answers everything in one place
_DOSS = {re.sub(r'[^a-z0-9]', '', k.lower()): v for k, v in (D3.get('dossier') or {}).items()}
_DEXQ = {re.sub(r'[^a-z0-9]', '', k.lower()): v for k, v in (D3.get('dexq') or {}).items()}
_nd = 0
for p in dex:
    key = re.sub(r'[^a-z0-9]', '', str(p.get('n', '')).lower())
    if key in _DOSS:
        p['dz'] = _DOSS[key]
        _nd += 1
    if key in _DEXQ:
        p['q'] = _DEXQ[key]
print('dex: %d dossiers attached, %d search blobs' % (_nd, len(_DEXQ)))

# ---- fold each guide + its RESOLVED recipe chain into the mon's dex entry ----------
# Guide chains name their ingredients but never resolved them ("sub" was always []), so
# "how do I get a Celestica Flute" lived on a different page from "Summon Arceus" and the
# only way to connect them was Ctrl-F. /tmp/wiki_recipes.json (wikiindex.py) is the join:
# item -> recipe / loot / villager trade / spawner reward. Resolve it here so one dex
# entry is the whole tutorial.


# Errors in the SOURCE guide data, corrected before they reach a dex entry. Giratina's
# guide claims antimatter_globe; GiratinaPedestalBlockEntity.<clinit> actually resolves
# mega_showdown:griseous_orb, and the antimatter globe is an Azure Flute part.
_GUIDE_ITEM_FIX = {'giratina': 'mega_showdown:griseous_orb'}

# The same error also lives in the dossier blob, which is a separate un-regenerable input,
# so fixing the guide item alone left the Pokedex still printing "The pedestal wants
# Antimatter Globe / Griseous Orb". Re-read from bytecode 2026-09-01:
# GiratinaPedestalBlockEntity.handleSpecialAction tests exactly ONE item, and at the end
# of a successful summon it CALLS getstatic ModItems.ANTIMATTER_GLOBE and prints "You've
# received an Antimatter Globe!". The globe is the reward, not a requirement - the wiki
# had it as a prerequisite, which is a wasted farming trip AND hides the Arceus chain.
_doss_gira = (D3.get('dossier') or {}).get('giratina')
if isinstance(_doss_gira, dict) and _doss_gira.get('needs'):
    _doss_gira['needs'] = ['Griseous Orb <span class="muted">(Mega Showdown&rsquo;s, not '
                           'Myths &amp; Legends&rsquo;)</span>']
    print('dex: corrected Giratina - the Antimatter Globe is the reward, not a requirement')

# Facts read out of the mod code that the guide data simply does not contain. Meloetta's
# guide knows the Disc of the First Song and its fragment recipe, but not the four OTHER
# discs the ritual needs, and its structs list is empty - so the wiki never said where
# the Amphitheater is or what to put in the jukeboxes.
_GUIDE_ITEM_FIX['hoopa'] = 'mythsandlegends:prison_bottle'   # source data says "prism_bottle"

_FOOTPRINT = [
    'These footprints are <b>Legendary Monuments</b>, not Myths &amp; Legends &mdash; a '
    'common mix-up, because the Swords of Justice <i>swords</i> (Sacred Sword, Iron Will '
    'Sword) really are Myths &amp; Legends items.',
    'Footprints generate on the ground as a world feature. <b>Collect 50 of the matching '
    'type</b> &mdash; progress is tracked per player and survives logout.',
    'On the 50th, <b>the Pok&eacute;mon spawns immediately, right where you are</b>. '
    'There is no altar, no key item and no biome requirement.',
    'Completing a set also grants the three <b>Curry of Justice</b> ingredients, which '
    'is how you get to Keldeo.',
]

_URN = [
    'Craft the urn (its grid is on this entry). You only need to <b>carry</b> it - '
    'it does not have to be held.',
    'Defeat wild Pok&eacute;mon of the matching type <b>within 32 blocks of you</b>. '
    'Kills by anyone in your group count toward your urn too.',
    'Chat tracks it: <i>"Your urn absorbs energy from X! Progress: n/50"</i>.',
    'At full, <b>right-click the urn anywhere</b> to summon the bird. The urn is '
    'consumed and you also receive its stone.',
    '<b>The Galarian trap:</b> turning an urn Galarian changes which type you must '
    'defeat, and it is never the one you would guess &mdash; a Galarian Urn of Storms '
    'still summons Zapdos but wants <b>Fighting</b>, not Electric. It also raises the '
    'requirement from 50 to <b>75</b>, and your progress resets.',
]
_NOT_OBTAINABLE = ('<b>Not obtainable on this server.</b> No spawn entry and no key '
                   'item exists for it in the installed files, so short of an operator '
                   'command there is no route. Listed here so nobody hunts for one.')

_BOX = (
    'The box has <b>no recipe and no loot table</b>. The <b>Entrepreneur</b> villager is '
    'the only source, and <b>only once you have levelled him up</b> &mdash; he stocks it '
    'at <b>level 2 (Apprentice)</b> for <b>32 emeralds + 32 relic coins</b>, 5 uses. Trade '
    'his cheap level-1 offers first to get him there.')


def _BEAST(name, colour):
    return [
        '<b>Two routes.</b> Myths &amp; Legends uses the <b>Clear Bell</b>.',
        '<b>Legendary Monuments:</b> the <b>%s Pedestal</b> in the <b>Burned Tower</b> '
        '(Dyna Plains). <b>The pedestal is not free</b> &mdash; it needs the '
        '<b>%s Treat</b> placed in it.' % (name, name),
        'The Treat is crafted from berries plus a <b>Pok&eacute;Treat Box</b> (grid below).',
        _BOX,
        '<b>Summoning it also gives you a %s feather.</b> Collect all three &mdash; red '
        'from Entei, blue from Suicune, yellow from Raikou &mdash; and they craft the '
        '<b>Rainbow Feather</b>, which summons <b>Ho-Oh</b> at the top of the Bell '
        'Tower.' % colour,
    ]


def _TREATONLY(name):
    return [
        '<b>The pedestal needs a %s Treat.</b> It does nothing on its own.' % name,
        'The Treat is crafted from berries plus a <b>Pok&eacute;Treat Box</b> (grid below).',
        _BOX,
    ]


def _KNIGHT(name, weapon, side):
    return [
        'The <b>Throneroom of Knightly Heroes</b> has a <b>dungeon underneath it</b>, and '
        'that is where the work is &mdash; a maze you fight through, not a chest you walk '
        'up to.',
        'The structure is split into a <b>blue side</b> and a <b>red side</b>. The '
        '<b>%s</b> is in a loot room on the <b>%s side</b>.' % (weapon, side),
        'The mod&rsquo;s own tooltip: <i>"Can be used with a totem of undying to summon '
        '%s"</i>. You need <b>both</b> &mdash; the %s <b>and a Totem of Undying</b>.'
        % (name, weapon),
        'Take them to the <b>top of the structure</b> and use the pedestal there.',
        '<b>Do not throw away what it drops.</b> Summoning %s gives you a <b>Rusted %s</b>, '
        'and that is a different item from the Hero one &mdash; give the Rusted %s to the '
        '%s you caught and it changes into its <b>Crowned</b> form. If you have already '
        'binned one, Mega Showdown&rsquo;s version is craftable: an iron %s, a netherite '
        'scrap and a fire charge.'
        % (name, weapon.split()[-1], weapon.split()[-1], name,
           weapon.split()[-1].lower()),
    ]


def _SHRINE(name, kind):
    return [
        '<b>There is no summon item for this one.</b> The Entrepreneur sells an '
        '<b>%s Seal</b>, and it is easy to assume that is the key &mdash; it is not. The '
        'seal is <b>only for the Arc Phone</b>: carry it and the phone points you at the '
        'nearest %s Shrine. It is never used on the shrine and is not consumed.' % (kind, kind),
        'The shrines are in the <b>Nether</b>. Around them are <b>%s Stakes</b> &mdash; '
        'coloured poles, one colour per shrine type.' % kind,
        '<b>Right-click stakes where they stand</b> to collect them &mdash; each one adds '
        '1 to a counter kept per player, the same way the Swords of Justice footprints '
        'work. The counter <b>keeps climbing past 8</b>, so you can bank them: 12 of 8 is '
        'a normal thing to see.',
        'With at least 8, <b>right-click the shrine with anything at all</b>, an empty hand '
        'included. %s spawns and <b>8 are spent</b> &mdash; the counter drops by 8 rather '
        'than resetting, so a stock of 16 is two summons.' % name,
        '<b>The shrine is destroyed when it is used</b>, along with everything within 10 '
        'blocks of it. One use per shrine, for everybody &mdash; go and find another. The '
        'stakes keep generating, so this is repeatable.',
        '%s also spawns on its own in freezing biomes, so a shrine is not the only way '
        '&mdash; it is just the reliable one.' % name if kind == 'Icerend' else
        '%s also has ordinary spawns, so a shrine is not the only way &mdash; it is just '
        'the reliable one.' % name,
    ]


_LAKE_TAIL = (
    'Keep the claw, fang and plume after you use them. All three together craft the '
    '<b>Red Chain</b>, which is what summons <b>Dialga and Palkia</b> at the Spear '
    'Pillar &mdash; see either of their entries.')

_SPEAR = [
    '<b>Two separate routes, from two different mods.</b>',
    '<b>Myths &amp; Legends:</b> the orb (Adamant for Dialga, Lustrous for Palkia), '
    'shown below.',
    '<b>Legendary Monuments:</b> the <b>Red Chain</b> &mdash; and one chain summons '
    '<b>both</b>. Its own tooltip reads <i>"Used to summon Palkia and Dialga at the '
    'Spear Pillar and to craft Ancient Origin Balls"</i>.',
    'The Red Chain is <b>crafted from the three lake guardian items</b>: <b>Uxie&rsquo;s '
    'Claw</b>, <b>Azelf&rsquo;s Fang</b> and <b>Mesprit&rsquo;s Plume</b> (grid below). '
    'So the lake trio comes first &mdash; catching them is the prerequisite.',
    'Take it to the <b>Spear Pillar</b> structure and use it there.',
    'If what you have is a <b>Fragmented Red Chain</b>, repair it with <b>Origin '
    'Ingots</b>, which come from the <b>Distortion World</b>: mine <b>Distortion Origin '
    'Ore</b>, smelt it to <b>Raw Origin</b>, smelt that to an <b>Origin Ingot</b>. One '
    'also turns up in the Turnback Cave vault at about 0.9%.',
]

_TUT_FIX = {
    'articuno': {'steps': _URN},

    # ---- Legendary Monuments routes the Pokedex did not carry at all --------------
    # Taken from the mods' own tooltips and recipes. The old guides page asserted an
    # invented source - "found in the world (structure loot, a pedestal you interact
    # with, or dropped by a mechanic)" - for 43 items it had no data for, including
    # Origin Glass, which is not obtainable at all.
    'dialga': {'items': ['legendarymonuments:red_chain',
                         'legendarymonuments:fragmented_red_chain',
                         'legendarymonuments:origin_ingot'],
               'steps': _SPEAR},
    'palkia': {'items': ['legendarymonuments:red_chain',
                         'legendarymonuments:fragmented_red_chain',
                         'legendarymonuments:origin_ingot'],
               'steps': _SPEAR},

    'uxie': {'items': ['legendarymonuments:proof_of_conquest_u'], 'steps': [
        '<b>Two routes.</b> Myths &amp; Legends uses <b>Uxie&rsquo;s Claw</b>, below.',
        '<b>Legendary Monuments:</b> a <b>Proof of Conquest (U)</b>. The item tooltip is '
        'literally <i>"Right-click to summon Uxie"</i> &mdash; no altar, no biome.',
        'The Proof is earned by completing the <b>Lake Guardian Trial</b>. It has no '
        'recipe and is not chest loot anywhere in the pack.',
        _LAKE_TAIL]},
    'mesprit': {'items': ['legendarymonuments:proof_of_conquest_m'], 'steps': [
        '<b>Two routes.</b> Myths &amp; Legends uses <b>Mesprit&rsquo;s Plume</b>, below.',
        '<b>Legendary Monuments:</b> a <b>Proof of Conquest (M)</b> &mdash; tooltip '
        '<i>"Right-click to summon Mesprit"</i>.',
        'Earned by completing the <b>Lake Guardian Trial</b>. No recipe, not chest loot.',
        _LAKE_TAIL]},
    'azelf': {'items': ['legendarymonuments:proof_of_conquest_a'], 'steps': [
        '<b>Two routes.</b> Myths &amp; Legends uses <b>Azelf&rsquo;s Fang</b>, below.',
        '<b>Legendary Monuments:</b> a <b>Proof of Conquest (A)</b> &mdash; tooltip '
        '<i>"Right-click to summon Azelf"</i>.',
        'Earned by completing the <b>Lake Guardian Trial</b>. No recipe, not chest loot.',
        _LAKE_TAIL]},

    # --- the Burned Tower chain: treats in, coloured feathers out, Ho-Oh at the end ----
    'hooh': {'items': ['legendarymonuments:rainbow_feather'], 'steps': [
        '<b>Two routes.</b> Myths &amp; Legends uses the <b>Rainbow Wing</b> with the '
        'Clear Bell.',
        '<b>Legendary Monuments:</b> the <b>Rainbow Feather</b> &mdash; <i>"A special '
        'feather that is said to bring eternal happiness to anyone who possesses it. Can '
        'be used to summon Ho-Oh"</i>.',
        'It is <b>crafted shapeless from the three coloured feathers</b>: <b>red</b>, '
        '<b>blue</b> and <b>yellow</b> (grid below).',
        '<b>Those feathers are what the legendary beasts give you.</b> Summon Entei for '
        'the red one, Suicune for the blue, Raikou for the yellow &mdash; see their '
        'entries. Ho-Oh is the end of that chain, not a separate hunt.',
        'Take the Rainbow Feather to the <b>top floor of the Bell Tower</b> (Dyna Plains) '
        'and use it on the pedestal there.']},

    'entei': {'items': ['legendarymonuments:entei_treat',
                        'legendarymonuments:poketreat_box'], 'steps': _BEAST('Entei', 'red')},
    'raikou': {'items': ['legendarymonuments:raikou_treat',
                         'legendarymonuments:poketreat_box'], 'steps': _BEAST('Raikou', 'yellow')},
    'suicune': {'items': ['legendarymonuments:suicune_treat',
                          'legendarymonuments:poketreat_box'], 'steps': _BEAST('Suicune', 'blue')},

    'latias': {'items': ['legendarymonuments:latias_treat',
                         'legendarymonuments:poketreat_box'], 'steps': _TREATONLY('Latias')},
    'latios': {'items': ['legendarymonuments:latios_treat',
                         'legendarymonuments:poketreat_box'], 'steps': _TREATONLY('Latios')},

    # --- Knightly Heroes: the weapon is deep in the dungeon, not in a chest outside ---
    'zacian': {'items': ['legendarymonuments:herosword'], 'steps': _KNIGHT(
        'Zacian', 'Hero Sword', 'blue')},
    'zamazenta': {'items': ['legendarymonuments:heroshield'], 'steps': _KNIGHT(
        'Zamazenta', 'Hero Shield', 'red')},

    'eternatus': {'items': ['legendarymonuments:galar_particle',
                            'legendarymonuments:galar_particle_block'], 'steps': [
        'Eternatus is asleep in an <b>Eternatus Cocoon</b>, and the cocoon does nothing '
        'until you feed it.',
        '<b>Finding it:</b> hold a <b>Galar Particle</b> and the <b>Arc Phone</b> points '
        'you at the nearest cocoon. That is what the particle is for outside the ritual.',
        '<b>Feeding it: 500 Galar Particles.</b> Right-click the cocoon and it takes every '
        'loose particle in your inventory, up to 500 total. <b>Progress is stored in the '
        'cocoon</b>, so you can do it over as many trips as you like &mdash; it tells you '
        '<i>"The cocoon is ready to break"</i> when it is full.',
        'Particles come from <b>Galar Particle Ore</b> and its deepslate version, about '
        '50% a block. Nine particles make a <b>Galar Particle Block</b> and one block '
        'unpacks back to nine, so 500 is roughly <b>56 blocks</b> &mdash; it is a mining '
        'job, not a lucky find.',
        '<b>Blocks do not count.</b> The cocoon only reads loose particles, so unpack any '
        'blocks before you feed it.']},

    # --- the four Nether shrines: no summon item exists ------------------------------
    'chienpao': {'items': ['legendarymonuments:icerend_seal'], 'steps': _SHRINE('Chien-Pao', 'Icerend')},
    'chiyu': {'items': ['legendarymonuments:firescourge_seal'], 'steps': _SHRINE('Chi-Yu', 'Firescourge')},
    'wochien': {'items': ['legendarymonuments:grasswither_seal'], 'steps': _SHRINE('Wo-Chien', 'Grasswither')},
    'tinglu': {'items': ['legendarymonuments:groundblight_seal'], 'steps': _SHRINE('Ting-Lu', 'Groundblight')},
    'zapdos': {'steps': _URN},
    'moltres': {'steps': _URN},

    # the three Mythicals that break the key-item pattern, per the Mythicals page
    'melmetal': {'steps': [
        '<b>Not summoned.</b> Evolve a <b>Meltan</b> after collecting '
        '<b>64 Meltan Candy</b>.']},
    'meltan': {'steps': [
        'One of the very few Mythicals that spawns with <b>no key item at all</b> '
        '&mdash; overworld biomes and beaches.',
        'Collect <b>64 Meltan Candy</b> to evolve it into Melmetal.']},
    'manaphy': {'steps': [
        _NOT_OBTAINABLE,
        'Cobbreeding ships a <b>Manaphy Egg</b> item, but nothing on this server seeds '
        'the first one.']},
    'phione': {'steps': [
        _NOT_OBTAINABLE,
        'Normally bred from Manaphy, which is itself unobtainable here.']},

    # the Loyal Three: no spawn pool, no key item, no evolution data in any installed jar
    'okidogi': {'steps': [_NOT_OBTAINABLE]},
    'munkidori': {'steps': [_NOT_OBTAINABLE]},
    'fezandipiti': {'steps': [_NOT_OBTAINABLE]},

    # obtained only by evolving something else - no spawn, no key item
    'silvally': {'steps': [
        '<b>Not summoned.</b> Evolve <b>Type: Null</b> &mdash; see its entry for how to '
        'get one.']},
    'urshifu': {'steps': [
        '<b>Not summoned.</b> Evolve <b>Kubfu</b> &mdash; see its entry for the route.']},
    'cosmoem': {'steps': [
        '<b>Not summoned.</b> Evolve <b>Cosmog</b>, which then becomes Solgaleo or '
        'Lunala depending on how you level it.']},

    # --- footprints: Legendary Monuments, NOT Myths & Legends -----------------------
    # FootprintTracker.FootprintType = COBALION / TERRAKION / VIRIZION / COSMIC_DUST,
    # threshold 50, and completion also grants the Curry of Justice ingredients.
    'cobalion': {'steps': _FOOTPRINT},
    'terrakion': {'steps': _FOOTPRINT},
    'virizion': {'steps': _FOOTPRINT},
    'cosmog': {'steps': [
        'Collect <b>50 Cosmic Dust</b>. It uses the same Legendary Monuments tracker as '
        'the Swords of Justice footprints &mdash; progress is per player, and on the '
        '50th piece <b>a Cosmog spawns on the spot</b> '
        '(<i>"A Cosmog has emerged from the void!"</i>).',
        'From there Cosmog evolves into Cosmoem, then Solgaleo or Lunala depending on '
        'how you level it.',
    ]},
    'keldeo': {'steps': [
        'Keldeo needs the <b>Curry of Justice</b>, and its three special ingredients '
        '&mdash; <b>Special Spices</b>, <b>Special Meat Chunks</b> and <b>Special Leafy '
        'Greens</b> &mdash; are granted by <b>completing a Swords of Justice footprint '
        'set</b> (50 Cobalion, Terrakion or Virizion footprints).',
        'So the route runs through the footprints, not through a chest: finish a set, '
        'take the ingredients, cook the curry.',
    ]},

    'zygarde': {'items': ['mega_showdown:zygarde_cube', 'mythsandlegends:zygarde_cube',
                          'mythsandlegends:zygarde_cell', 'mythsandlegends:zygarde_core',
                          'mega_showdown:zygarde_cell', 'mega_showdown:zygarde_core'],
                'steps': [
        '<b>Both sets of cells you have are usable &mdash; they feed different systems.</b>',
        '<b>Myths &amp; Legends (summons it):</b> put <b>95 Zygarde Cells + 5 Zygarde '
        'Cores</b> into the M&amp;L <b>Zygarde Cube</b> (it works as a bundle). A full '
        'cube is the key item for the Zygarde-100% spawn &mdash; level 70, in forest, '
        'jungle, mangrove swamp or cave biomes. M&amp;L cells drop from Ancient City at '
        '~19%, cores at ~3%.',
        '<b>Mega Showdown (changes its form):</b> a separate <b>Zygarde Cube</b> you '
        'craft &mdash; <b>4 black apricorns</b> in the corners, <b>4 green apricorns</b> on '
        'the edges and <b>1 netherite ingot</b> in the middle (grid below). It opens a GUI '
        'that takes <b>Mega Showdown</b> cells and cores and switches Zygarde between '
        '10%, 50% and Complete / Power Construct.',
        '<b>The two mods’ cells do not mix.</b> Each cube only accepts its own '
        'mod’s items, and the icons look almost identical &mdash; check the tooltip.',
    ]},

    # The Legendary Monuments route is the one that counts for Arc Phone progress, and it
    # is the most confusing thing on the server: the NPC's dialogue arrives as CLICKABLE
    # CHAT LINES with no indication that they are clickable, so it reads as a broken NPC.
    # The owner grew both carrots and summoned both steeds without ever being able to
    # start the quest, then found it by accident.
    'calyrex': {'items': ['legendarymonuments:iceroot_carrot_seeds',
                          'legendarymonuments:shaderoot_carrot_seeds'],
                'steps': [
        '<b>Two completely separate routes. Only one counts for the Arc Phone.</b>',
        '<b>Quick route (no quest):</b> carry the <b>Reins of Unity</b> and hunt in a <b>Flower Forest</b>. Calyrex is ultra-rare there at level 70. This gives you the Pok&eacute;mon but <b>no Arc Phone progress</b>.',
        '<b>Crown Shrine route (this is the one the Arc Phone wants).</b> Track a Crown Shrine with either carrot seed in the Arc Phone.',
        '<b>Talk to the Calyrex NPC FIRST, before you grow or use anything.</b> Its replies come through as <b>clickable lines in chat</b> &mdash; nothing marks them as buttons. Click <i>&quot;The King of Bountiful Harvests?&quot;</i>, then <i>&quot;How do I find them?&quot;</i>. That is what assigns the quest.',
        '<b>Get seeds from chests.</b> The Crown Shrine&rsquo;s own chest has both. <b>Regice</b> shrines carry Iceroot seeds, <b>Thalic</b> structures carry Shaderoot seeds. There is nothing buried in ice spikes &mdash; that is a myth.',
        '<b>Grow the carrot.</b> Iceroot seeds go in ordinary farmland <b>in a cold biome</b>. Shaderoot seeds will only grow in <b>Thalic Dirt</b>, not normal farmland.',
        '<b>Summon at the Steed Pedestal.</b> Iceroot Carrot calls <b>Glastrier</b>, Shaderoot Carrot calls <b>Spectrier</b>. Catch it.',
        '<b>Return carrying at least one related seed and click &quot;I accept&quot;.</b> Calyrex battles you himself. Beat him and he is yours &mdash; that is what fires the Arc Phone quest.',
        '<b>One steed per shrine.</b> Calyrex says it plainly: <i>&quot;Only one steed may answer my call.&quot;</i> To get the other horse, do it again at a different Crown Shrine.',
        '<b>If you already summoned before talking to him</b>, you are not stuck. The NPC picks its line from what you are <b>carrying</b>, so it keeps asking for seeds. Bring any related seed back and the conversation moves on.',
    ]},
    'genesect': {'items': ['mythsandlegends:genesect_drive'],
                 'steps': [
        '<b>Two routes, and only one is a key item.</b>',
        '<b>Passive spawn:</b> Genesect is in the ultra-rare pool for <b>dripstone '
        'caves</b> at weight 5.0 (about 9.8% of ultra-rare rolls there). This is what '
        'Pok&eacute; Snacks and the Pok&eacute;Nav are picking up &mdash; no item needed.',
        '<b>Key item:</b> carry a <b>Genesect Drive</b> (Myths &amp; Legends) and it can '
        'spawn at <b>level 70</b> in the <b>Deep Dark</b> or <b>any End biome</b> &mdash; '
        'note that is <i>not</i> dripstone. Drops from Ancient City chests at 0.63%.',
        '<b>Dome Fossil + Dubious Disk does NOT work here.</b> No such recipe exists in '
        'any installed mod; that is a different modpack. The Genesect Drive is the item '
        'this server actually uses.',
    ]},

    'hoopa': {'steps': [
        '<b>Legendary Monuments route:</b> find the <b>Hoopa Pyramid</b> and use a '
        '<b>Temple Key</b> on the <b>Hoopa Pedestal</b>. Hoopa spawns '
        '(<i>"A dimensional portal opens!"</i>) and the pedestal hands you a '
        '<b>Prison Bottle</b>.',
        '<b>Careful &mdash; that is the wrong bottle.</b> The pedestal gives Mega '
        'Showdown’s Prison Bottle, which nothing in any installed mod consumes. '
        'Turning Hoopa into its <b>Unbound</b> form needs the <b>Myths &amp; Legends</b> '
        'Prison Bottle instead. Two different items, same name.',
        '<b>Myths &amp; Legends route:</b> carry a <b>Hoopa Ring</b> in any End biome.',
        '<b>Broken in the mod, not on this server:</b> Myths &amp; Legends declares a '
        'second Hoopa route keyed to <code>mythsandlegends:pris&#109;_bottle</code>, but the '
        'item it actually ships is <code>prison_bottle</code>. No such item exists, so '
        '<b>that route can never fire</b> &mdash; carrying a Prison Bottle will do '
        'nothing. Nothing you can do about it short of a datapack override.',
    ]},

    'meloetta': {
        'st': [{'id': 'amphitheater', 'b': ['%s' % pretty_biome('#cobblemon:is_desert')]}],
        'steps': [
            'Craft the <b>Disc of the First Song</b> from <b>9 fragments</b> (fills the '
            'whole 3&times;3 grid). Fragments are common in Legendary Monuments chests.',
            'Find the <b>Amphitheater</b> - a desert surface structure, roughly every '
            '250 chunks. It contains one <b>Meloetta Jukebox</b> and <b>four ordinary '
            'jukeboxes</b>.',
            'Load the four ordinary jukeboxes with <b>Pigstep</b>, <b>5</b>, '
            '<b>Creator</b> and <b>Relic</b>. Careful: <b>Creator Music Box</b> is a '
            'different disc and does not count.',
            'Hold the Disc of the First Song and <b>right-click the Meloetta Jukebox</b>. '
            'It scans <b>&plusmn;20 blocks</b> for the four discs, so the jukeboxes must be '
            'nearby - you may place your own instead of using the ones in the structure.',
            'If it says <i>"The melodies seem incomplete"</i>, one of the four discs is '
            'missing or wrong. On success all five jukeboxes are emptied.',
        ],
    },
}

# Never expand vanilla. "Brick -> smelting -> Clay Ball -> Clay 50% per container" is
# true, useless, and exactly the wall of text this rewrite exists to remove. Players know
# where clay is; what they don't know is where a Celestica Flute is.
def _is_vanilla(item):
    return str(item).startswith('minecraft:')

            








def _label(item):
    """Display name, tagged with its mod when the bare name is ambiguous.

    35 item names in this pack are defined by two mods - griseous_orb, azure_flute,
    magma_stone, red_chain and friends exist in BOTH Myths & Legends and Legendary
    Monuments / Mega Showdown, and they are different items with different routes.
    Showing a bare "Griseous Orb" is how a player ends up at the pedestal holding the
    wrong one. Tag every ambiguous name, every time - not only when two copies happen
    to appear side by side.
    """
    bare = str(item).split(':')[-1]
    nm = nice(bare)
    cands = (_RX.get('items') or {}).get(bare) or []
    if isinstance(cands, str):
        cands = [cands]
    if len(cands) > 1:
        ns = str(item).split(':')[0]
        nm = '%s (%s)' % (nm, _MODNAME.get(ns, ns))
    return nm


def _sources(item):
    """Every way to get this item on THIS server, best route first."""
    out = []
    for t in (_RX.get('trades') or {}).get(item, []):
        out.append('Buy from the %s villager: %s (%d use%s per villager)'
                   % (t['villager'], t['costs'], t['maxUses'],
                      '' if t['maxUses'] == 1 else 's'))
    for s in (_RX.get('spawner') or {}).get(item, []):
        out.append('%s - %s%%%s' % (s['source'], s['pct'],
                                    ('. ' + s['note']) if s.get('note') else ''))
    seen_t = set()
    for r in ((_RX.get('mnl_loot') or {}).get(item, [])
              + (_RX.get('loot') or {}).get(item, [])):
        if r['table'] in seen_t:
            continue
        seen_t.add(r['table'])
        _tail = r['table'].split('/')[-1].split(':')[-1]
        if _tail == item.split(':')[-1]:
            continue                      # the item's own block drop - says nothing
        out.append('%s - %s%% per container' % (nice(_tail), r['pct']))
        if len(seen_t) >= 4:
            break
    return out


def _resolve(item, depth=0, seen=frozenset()):
    """Recipe tree for an item, with each ingredient resolved in turn."""
    if item in seen or depth > 2 or item.startswith('#'):
        return None
    node = {'i': item, 'b': str(item).split(':')[-1], 'nm': _label(item)}
    if ':' in str(item):
        node['m'] = str(item).split(':')[0]
    if _is_vanilla(item) and depth > 0:
        return node                       # named, never expanded
    src = _sources(item)
    if src:
        node['src'] = src
    rs = (_RX.get('recipes') or {}).get(item) or []
    if rs:
        r = rs[0]
        ings = []
        for ing in r['ings']:
            sub = None
            if depth < 2 and not _is_vanilla(ing['i']):
                sub = _resolve(ing['i'], depth + 1, seen | {item})
                if sub and not sub.get('r') and not sub.get('src'):
                    sub = None          # nothing to say about it - don't nest an empty node
            _b, _tip = _cell_item(ing['i'])
            _nm = nice(ing['i'].split(':')[-1])
            if str(ing['i']).startswith('#') and _b:
                _, _cnt = _tag_pick(ing['i'])
                _nm = '%s (or %d alternatives)' % (nice(_b), _cnt - 1)
            ings.append({'i': ing['i'], 'b': _b or ing['i'].split(':')[-1], 'nm': _nm,
                         'n': ing['n'], 'sub': sub})
        node['r'] = {'k': r['kind'], 'ings': ings}
        if r.get('grid'):
            # the LAYOUT is the information for a shaped recipe - a bare ingredient
            # list makes the reader go find the grid on another page
            node['r']['g'] = [[_cell_item(c)[0] for c in row] for row in r['grid']]
    return node


_byname = {re.sub(r'[^a-z0-9]', '', str(p.get('n', '')).lower()): p for p in dex}

# The typo also sits in the raw spawn-condition key ("carry prism_bottle") and in the
# guide item summary table, neither of which passes through _NSFIX. Correct them at
# source so no rendering path can show a nonexistent item.
# NOTE: deliberately NOT rewriting _s['k']. The spawn condition is the mod's own
# declaration; M&L's Hoopa pool asks for mythsandlegends:prism_bottle while the item it
# ships is prison_bottle, so that route cannot fire at all. Renaming it here would make
# the wiki promise a route the game will never satisfy. It is flagged on the entry
# instead - see _TUT_FIX['hoopa'].

if _nfix:
    print('dex: corrected %d source-data item typos' % _nfix)


def _walk_tut(t):
    """Every resolved item node in a tutorial, at any depth."""
    stack = [t.get('key')] + list(t.get('ki') or []) + list(t.get('it') or [])
    while stack:
        n = stack.pop()
        if not isinstance(n, dict):
            continue
        yield n
        for ing in ((n.get('r') or {}).get('ings') or []):
            if ing.get('sub'):
                stack.append(ing['sub'])


def _disambiguate(t):
    """35 item names in this pack exist in two mods. Giratina legitimately has BOTH
    Griseous Orbs on its entry - one force-spawns it, one feeds the pedestal - and two
    rows both reading "Griseous Orb" is worse than useless. Tag the mod when a display
    name repeats within one tutorial."""
    seen = collections.Counter()
    nodes = list(_walk_tut(t))
    for n in nodes:
        seen[n.get('nm')] += 1
    for n in nodes:
        if seen.get(n.get('nm'), 0) > 1 and n.get('i'):
            ns = str(n['i']).split(':')[0]
            n['nm'] = '%s (%s)' % (n['nm'], _MODNAME.get(ns, ns))


# ---- which items belong to which species ------------------------------------------
# A guide names ONE item, but a species' gear is usually spread wider: the Urn of Frost
# is Articuno's and is craftable, yet Articuno's guide item is the Tidal Bell, so the urn
# recipe only ever appeared on a separate page. Attribute items from several signals.
_ITEM2MON = collections.defaultdict(set)

# 1. key items, straight from the spawn conditions
for _ki_id, _mons in (_RX.get('keyfor') or {}).items():
    for _m in _mons:
        _ITEM2MON[_NSFIX(_ki_id)].add(re.sub(r'[^a-z0-9]', '', str(_m).lower()))

# 2. the item's own name contains a species as a whole token ("entei_treat",
#    "zacian_pedestal"). Token-exact, so "mew" never claims "mewtwo".

# ---------------------------------------------------------------------------------
# Legendary Monuments routes the Pokedex reduced to a single item name.
#
# The guide data carries only `itemName` + `item` per legendary, so the page said things
# like "the summon item is the Shadowy Cowl" for a route that actually needs a Thalic
# Well, a bucket, a cauldron and TWO items thrown on the ground. Every step below was read
# out of the mod: the block's own interaction method, its recipe json, or its en_us
# tooltip - never inferred from the item's name.
#
# The pedestal legendaries were already handled by _PED_NEEDS. These are the ones that use
# some other mechanism entirely: cauldrons, cocoons, jars, jukeboxes, statues, whistles.
# ---------------------------------------------------------------------------------

_DREAM = [
    '<b>Darkrai and Cresselia share one chain</b>, and it starts with a mob drop rather '
    'than a structure.',
    '<b>Dream String</b> drops from <b>defeating Pok&eacute;mon at night</b> &mdash; an '
    '<b>8% chance</b> per defeat (<i>"You found a Dream String in the darkness!"</i>). '
    'Its tooltip says it plainly: <i>"A string acquired by defeating pokemon at night, '
    'can be used to craft the dream catcher"</i>.',
    '<b>9 Dream String</b> fills the crafting grid and makes a <b>Dream Catcher</b>.',
    '<b>Sleep near the Dream Catcher.</b> It applies <b>Lucid Dreaming</b>, and waking up '
    'rolls an outcome: about <b>1 in 4</b> is a good dream and gives a <b>Lunar '
    'Feather</b>; the bad outcome is a nightmare, which gives a <b>Nightmare Essence</b> '
    'and leaves you with lingering effects.',
    '<b>5 Lunar Feathers</b> make a <b>Fullmoon Whistle</b>; <b>5 Nightmare Essences</b> '
    'make a <b>Newmoon Whistle</b>. Both are the same shape &mdash; a row of three over a '
    'row of two.',
    '<b>Right-click the whistle anywhere.</b> No altar, no structure, no biome. It is '
    'consumed and the Pok&eacute;mon appears in front of you at <b>level 50</b>, with a '
    '<b>2%</b> shiny roll.',
    '<span class="muted">The mod spells the item <b>&ldquo;Fulmoon Whistle&rdquo;</b> '
    'in game &mdash; one L. That is the mod&rsquo;s typo, not ours.</span>',
]


def _REGI(name, tablet):
    return [
        '<b>Two different tablets, and only one of them is a key.</b> Myths &amp; '
        'Legends has its own tablet item for this route. Legendary Monuments&rsquo; '
        '<b>%s</b> is something you <b>receive</b>, not something you spend.' % tablet,
        'Find the <b>%s Statue</b>. It does nothing when you use it &mdash; there is no '
        'item to hold and nothing to insert.' % name,
        '<b>It is a light puzzle.</b> The floor around the statue carries two kinds of '
        'light block that look alike: <b>correct</b> ones and <b>false</b> ones. '
        'Standing on a light toggles it.',
        '<b>The statue activates only when every correct light nearby is lit and every '
        'false light is unlit.</b> The check sweeps <b>10 blocks horizontally</b> and '
        '<b>3 blocks vertically</b> from the light you just stepped on, and a single lit '
        'false light anywhere in that box blocks it.',
        'When the condition is met the statue <b>breaks</b>, %s appears '
        '(<i>"%s has awakened!"</i>), and you are handed a <b>%s</b>.' % (name, name, tablet),
        '<b>Keep the tablet.</b> All five Regi tablets together craft the <b>Titan '
        'Key</b> &mdash; see <b>Regigigas</b>.',
    ]


_LM_ADD = {
    # ---- the one the owner asked about: a cauldron ritual, not a pedestal -------------
    'marshadow': {'items': ['legendarymonuments:shadow_ichor_bucket',
                            'legendarymonuments:shadowy_cowl',
                            'legendarymonuments:old_fighters_towel'], 'steps': [
        '<b>Two routes.</b> Myths &amp; Legends uses the <b>Marshadow Hood</b>. '
        'Legendary Monuments has no pedestal for Marshadow at all &mdash; it is a '
        'cauldron ritual, and the Shadowy Cowl on its own does nothing.',
        'Find a <b>Thalic Well</b>. <b>Fill a bucket</b> from the shadow ichor in the '
        'middle of it to get a <b>Shadow Ichor Bucket</b>.',
        'Place an ordinary <b>cauldron</b> and <b>use the Shadow Ichor Bucket on it</b>. '
        'The bucket is registered against the empty-cauldron interaction, so it fills '
        'exactly the way water or lava would.',
        '<b>Drop</b> &mdash; as in press Q, not right-click &mdash; a <b>Shadowy Cowl</b> '
        'and an <b>Old Fighters Towel</b> onto the cauldron. Both must be lying loose '
        'within the cauldron&rsquo;s own space: the block it sits in, plus about two and '
        'a half blocks above it.',
        'The check runs the moment an item touches the cauldron, so the items landing on '
        'it is the trigger. Both are consumed, <b>the cauldron is destroyed</b>, and '
        'Marshadow appears.',
        'The Shadow Ichor Bucket tooltip says it outright: <i>"A mysterious liquid that '
        'can be combined in a cauldron with the Shadowy Cowl and the Old Fighters '
        'Towel"</i>.',
        '<b>Both items come from the same chests</b> &mdash; <b>Thalic</b> structures, '
        'and the two <b>Sword/Shield temple</b> chests. Read one well, loot the camp and '
        'pyramid nearby, and you can leave with all three pieces.']},

    # ---- a pokeball on a shrine ------------------------------------------------------
    'celebi': {'items': ['legendarymonuments:gs_ball'], 'steps': [
        '<b>Find an Ilex Shrine</b> and <b>right-click it with a GS Ball</b>. That is the '
        'whole route &mdash; the shrine crumbles and Celebi emerges at <b>level 40</b>.',
        'Hold anything else and it tells you so: <i>"This ancient Ilex Shrine seems to be '
        'awaiting a special pokeball..."</i>',
        '<b>The GS Ball is crafted</b>, not found: <b>4 Yellow Apricorns</b> in a '
        'diamond around <b>1 Netherite Scrap</b>. The apricorns are the easy part; the '
        'scrap means a nether trip.',
        'The ball&rsquo;s own tooltip confirms the pairing &mdash; <i>"A special pokeball '
        'that summons Celebi when used on a Ilex Shrine"</i>.']},

    # ---- once per player, and the lock remembers -------------------------------------
    'victini': {'items': ['legendarymonuments:liberty_pass'], 'steps': [
        'Find <b>Liberty Island</b>. It contains a <b>Victini Lock</b>.',
        '<b>Right-click the lock holding a Liberty Pass.</b> Victini appears at '
        '<b>level 50</b> with a <b>2%</b> shiny roll.',
        '<b>The lock remembers you personally</b> &mdash; try again and it says <i>"This '
        'lock has already responded to your Liberty Pass."</i> But it is per player, not '
        'per lock, so <b>everyone on the server can use the same one</b>. Do not break it '
        'after your turn.',
        'Liberty Passes come from <b>Thalic chests</b>, and the mod also injects them '
        'into other loot tables.']},

    # ---- jar collection routes -------------------------------------------------------
    'xerneas': {'items': ['legendarymonuments:aurora_essence_jar',
                          'legendarymonuments:jar'], 'steps': [
        '<b>Craft empty Jars first</b> &mdash; <b>5 glass</b> each. You will need '
        '<b>16</b> of them, so bring 80 glass.',
        'At the <b>Tree of Life</b>, <b>Aurora Essence</b> grows as a block. '
        '<b>Right-click each one holding an empty Jar</b> to bottle it into an <b>Aurora '
        'Essence Jar</b>. Empty-handed it just says <i>"You need an empty jar to capture '
        'this aurora essence."</i>',
        '<b>Right-click the Aurora X Log with the jars.</b> It takes what you are '
        'carrying and reports <b>&ldquo;n/16 Aurora Essence Jars offered&rdquo;</b>. '
        '<b>Progress is stored in the log</b>, so this can take as many trips as you '
        'like.',
        'At 16 the log transforms &mdash; <i>"The aurora wood awakens."</i> '
        '<b>Right-click the activated log</b> and Xerneas answers.']},

    'yveltal': {'items': ['legendarymonuments:soul_jar',
                          'legendarymonuments:jar'], 'steps': [
        'Same shape as Xerneas, different jar. <b>Craft 16 empty Jars</b> &mdash; '
        '<b>5 glass</b> each.',
        'At the <b>Yveltal Cocoon</b>, <b>Restless Soul</b> blocks float around the '
        'structure. <b>Right-click each with an empty Jar</b> to get a <b>Soul Jar</b> '
        '(<i>"You need an empty jar to capture this soul."</i>).',
        '<b>Right-click the cocoon with the jars</b> &mdash; it reports <b>&ldquo;n/16 '
        'soul jars offered&rdquo;</b> and <b>stores the progress in the cocoon</b>.',
        'On the 16th the cocoon breaks: <i>"Yveltal has awakened, the harbinger of '
        'destruction!"</i>']},

    # ---- the dream chain -------------------------------------------------------------
    'darkrai': {'items': ['legendarymonuments:newmoon_whistle',
                          'legendarymonuments:nightmare_essence',
                          'legendarymonuments:dream_catcher',
                          'legendarymonuments:dream_string'], 'steps': _DREAM},
    'cresselia': {'items': ['legendarymonuments:fullmoon_whistle',
                            'legendarymonuments:lunar_feather',
                            'legendarymonuments:dream_catcher',
                            'legendarymonuments:dream_string'], 'steps': _DREAM},

    # ---- the five statues, then the sixth --------------------------------------------
    'regirock': {'items': ['legendarymonuments:regirock_tablet'],
                 'steps': _REGI('Regirock', 'Regirock Tablet')},
    'regice': {'items': ['legendarymonuments:regice_tablet'],
               'steps': _REGI('Regice', 'Regice Tablet')},
    'registeel': {'items': ['legendarymonuments:registeel_tablet'],
                  'steps': _REGI('Registeel', 'Registeel Tablet')},
    'regieleki': {'items': ['legendarymonuments:regieleki_tablet'],
                  'steps': _REGI('Regieleki', 'Regieleki Tablet')},
    'regidrago': {'items': ['legendarymonuments:regidrago_tablet'],
                  'steps': _REGI('Regidrago', 'Regidrago Tablet')},

    'regigigas': {'items': ['legendarymonuments:titan_key',
                            'legendarymonuments:titan_core',
                            'legendarymonuments:titan_hammer'], 'steps': [
        '<b>Regigigas is the end of the Regi chain, and it is the reason to do the other '
        'five.</b>',
        '<b>Summon all five Regis</b> &mdash; Regirock, Regice, Registeel, Regieleki and '
        'Regidrago &mdash; from their statues. Each hands you <b>its tablet</b> on the '
        'way out. See any of their entries for the light puzzle.',
        '<b>Craft the Titan Key from all five tablets.</b> Its tooltip is the whole '
        'answer: <i>"Unlocks the Regigigas Room at Snowpoint Temple"</i>.',
        'Use it on the <b>Regigigas Lock</b> at <b>Snowpoint Temple</b> to open the room.',
        'The Regigigas statue inside works like the other five, but instead of a tablet '
        'it gives you a <b>Titan Core</b>.',
        '<b>The Titan Core is what the whole chain is really for.</b> It makes the '
        '<b>Titan Hammer</b> (Titan Core + 2 netherite ingots + 2 breeze rods) &mdash; '
        'the wide-area mining tool &mdash; and the <b>Titan Pauldron</b>, which fuses the '
        'five elemental pauldrons into one.']},

    # ---- the bird trio pays out a stone each -----------------------------------------
    'lugia': {'items': ['legendarymonuments:vortex_stone',
                        'legendarymonuments:lugia_key'], 'steps': [
        '<b>Two ways in</b>, and the second is a reward for work you may already have '
        'done: a <b>Lugia Key</b>, or a <b>Vortex Stone</b>.',
        '<b>The Vortex Stone is the legendary birds&rsquo; payoff.</b> Summoning '
        '<b>Articuno</b>, <b>Zapdos</b> and <b>Moltres</b> from their urns gives you an '
        '<b>Arctic Stone</b>, a <b>Zap Stone</b> and a <b>Molten Stone</b> respectively '
        '&mdash; one per bird, handed over on the summon.',
        '<b>Combine the three</b> (shapeless, no pattern) into a <b>Vortex Stone</b>. '
        'Its tooltip: <i>"A stone infused with the torrential power of Articuno, Zapdos, '
        'and Moltres. Whoever possesses this stone has earned the right to challenge '
        'Lugia."</i>',
        'Take it to the <b>Lugia Temple</b> pedestal, out under a deep ocean. The '
        '<b>Lugia Lock</b> in the same structure is what the Lugia Key opens.',
        '<b>If you are hunting the birds anyway, do the urns first</b> &mdash; the stones '
        'cost nothing extra and there is no other source for them anywhere in the pack.']},
}

_LM_ADD['giratina'] = {'items': ['mega_showdown:griseous_orb',
                                 'legendarymonuments:antimatter_globe'], 'steps': [
    '<b>The pedestal wants ONE item, and it is not the one the item list used to '
    'suggest.</b> It tests a single stack against <b>Mega Showdown&rsquo;s Griseous '
    'Orb</b> &mdash; resolved by name, <code>mega_showdown:griseous_orb</code>. The '
    '<b>Myths &amp; Legends</b> orb of the same name is a different item and does '
    'nothing here.',
    '<b>You do not need an Antimatter Globe.</b> That was wrong on this page for a long '
    'time and it is the opposite of the truth &mdash; see the next step.',
    'Use the orb on the <b>Giratina Pedestal</b> (Turnback Cave / Distortion World). '
    'Giratina appears, with a <b>2%</b> shiny roll.',
    '<b>The pedestal is once per player</b> &mdash; <i>"This pedestal has already been '
    'used by you."</i> &mdash; so everyone can take their own Giratina from the same one. '
    'Leave it standing.',
    '<b>You are handed an Antimatter Globe on the way out</b> (<i>"You&rsquo;ve received an '
    'Antimatter Globe!"</i>). It is the <b>reward</b>, not the fee.',
    '<b>That globe is an Azure Flute ingredient</b>, and the Azure Flute is how you reach '
    'the <b>Hall of Origin</b> and <b>Arceus</b>. Giratina is a step on that chain, which '
    'is easy to miss when the globe looks like a prerequisite.',
    'Keeping the orb: it also switches Giratina between its <b>Altered</b> and '
    '<b>Origin</b> forms, so do not spend your only one if you want the other form.']}

# Read from AzureFluteTeleporter 2026-09-01. A pending correction note claimed the only
# exit was another flute and that players could strand themselves - that is WRONG, and it
# is why the warning was never published. tickServer teleports the owner out and consumes
# the flute the moment the encounter ends, so the dimension cannot trap anyone.
_LM_ADD['arceus'] = {'items': ['legendarymonuments:azure_flute'], 'steps': [
    '<b>The Azure Flute is a teleporter, not a tracker.</b> There is nothing to '
    '<code>/locate</code> &mdash; the Hall of Origin is its own dimension. '
    '<b>Right-click the flute anywhere</b> and you are in.',
    '<b>Bring nothing.</b> No pedestal, no vault, no chest, no second key item.',
    '<b>Arceus appears about 3 seconds after you arrive</b> (60 ticks), at '
    '<b>level 90</b>. It is an ordinary wild encounter &mdash; throw balls or battle it '
    'normally.',
    '<b>Do not leave while it is out.</b> If you go back to another dimension mid-fight '
    'the encounter is cancelled and <b>Arceus despawns</b>.',
    '<b>Falling into the void does not eject you</b> &mdash; you are put back at the '
    'centre of the Hall. It is safe to fall.',
    '<b>You cannot strand yourself.</b> When the encounter ends, the server sends you '
    'home on its own <b>and only then consumes the flute</b>. Using the flute again while '
    'inside is a manual exit and does the same thing.',
    '<b>Craft the flute</b> from the Space, Time and Antimatter Globes plus a Celestica '
    'Flute. The Antimatter Globe comes from summoning <b>Giratina</b> &mdash; see its '
    'entry &mdash; and the Celestica Flute from an <b>Entrepreneur</b> villager '
    '(64 diamonds + 64 relic coins, one per villager) or the Turnback Cave vault.',
    '<span class="muted">Namespaces matter here: this is '
    '<code>legendarymonuments:azure_flute</code>. Myths &amp; Legends ships a different '
    'item with the same name that spawns Arceus by biome instead.</span>']}

for _k, _v in _LM_ADD.items():
    if _k in _TUT_FIX:
        print('lm-routes: WARNING %s already had a walkthrough - not overwriting' % _k)
        continue
    _TUT_FIX[_k] = _v

# Meltan already had an entry, but it described only the wild spawn and the 64-candy
# evolution. The Meltan Box - a craftable, REUSABLE candy machine - was missing entirely,
# which matters because 64 candies is otherwise a very long grind.
_MELTAN_BOX = [
    '<b>There is also a Meltan Box, and it is the only renewable Meltan Candy source in '
    'the pack.</b>',
    '<b>Right-click the box with metal ingots</b> to charge it. They are worth different '
    'amounts: <b>copper 1</b>, <b>iron 2</b>, <b>gold 3</b>, <b>netherite 50</b>. It '
    'takes <b>50</b> and reports <b>&ldquo;n/50 metal value stored&rdquo;</b> as you go. '
    'Anything that is not one of those four is refused &mdash; <i>"This box only accepts '
    'metal ingots"</i>.',
    'At 50 it says <i>"The Meltan Box is ready to summon Meltan!"</i>. <b>Right-click it '
    'again</b> &mdash; the <b>first</b> time this releases <b>Meltan</b>.',
    '<b>Every fill after that gives a Meltan Candy instead</b> (<i>"The Meltan Box '
    'condensed a Meltan Candy."</i>), and the counter resets to zero each time. So each '
    'candy costs another 50 metal value &mdash; one netherite ingot, or 17 gold, or 25 '
    'iron.',
    '<b>That is the practical route to Melmetal</b>, since it needs <b>64</b> candies. '
    'The box is reusable forever; it is the ingots that are the grind.',
]
if 'meltan' in _TUT_FIX:
    _TUT_FIX['meltan'].setdefault('items', [])
    for _mi in ('legendarymonuments:meltan_box', 'legendarymonuments:meltan_candy'):
        if _mi not in _TUT_FIX['meltan']['items']:
            _TUT_FIX['meltan']['items'].append(_mi)
    _TUT_FIX['meltan']['steps'] = list(_TUT_FIX['meltan']['steps']) + _MELTAN_BOX

print('lm-routes: %d Legendary Monuments walkthroughs added, Meltan Box documented'
      % len(_LM_ADD))


for _bare, _fulls in (_RX.get('items') or {}).items():
    _toks = set(str(_bare).split('_'))
    for _t in _toks:
        if len(_t) >= 4 and _t in _byname:
            for _f in (_fulls if isinstance(_fulls, list) else [_fulls]):
                _ITEM2MON[_f].add(_t)

# 3. the urns table states its own mapping ("Urn of Frost | Articuno | Ice | 50"), and
#    frost->Articuno is not derivable from the name.
_urn_txt = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', D3.get('urns_html') or ''))
for _m in re.finditer(r'((?:Galarian )?Urn of (?:Frost|Storms|Embers))\s+([A-Za-z]+)', _urn_txt):
    _urn, _mon = _m.group(1), re.sub(r'[^a-z0-9]', '', _m.group(2).lower())
    if _mon in _byname:
        _uid = _NSFIX(_urn.lower().replace(' of ', '_of_').replace(' ', '_'))
        _ITEM2MON[_uid].add(_mon)

_MON2ITEM = collections.defaultdict(list)
for _i, _ms in _ITEM2MON.items():
    for _m in _ms:
        if _i not in _MON2ITEM[_m]:
            _MON2ITEM[_m].append(_i)
print('dex: %d items attributed to %d species' % (len(_ITEM2MON), len(_MON2ITEM)))
_ntut = _nchain = 0
for _g in guides:
    _mon = _mon_of(_g.get('title', ''))
    _p = _byname.get(_mon) if _mon else None
    if not _p:
        continue
    _tut = {'t': _g.get('title')}
    if _g.get('tips'):
        _tut['tips'] = _g['tips']
    if _g.get('structs'):
        _tut['st'] = _g['structs']
    if _g.get('related'):
        _tut['rel'] = _g['related']
    _it = _GUIDE_ITEM_FIX.get(_mon) or _g.get('item')
    if _it:
        # Guide items are bare paths. Resolve by EXISTENCE, not by "has a recipe" -
        # shrines, pedestals and legendary drops have no recipe and no loot table, and
        # the has-a-source test silently dropped 79 of 108 of them.
        _it = _NSFIX(_it)
        _tut['key'] = _resolve(_it)
        if _tut['key'] and _tut['key'].get('r'):
            _nchain += 1
    # key items named by the spawn conditions themselves
    _ki = []
    for _s in _p.get('sp', []) or []:
        _k = _s.get('k')
        if _k and _k not in _ki:
            _ki.append(_k)
    if _ki:
        # the summon item and the key item are usually the SAME item (Tidal Bell is both
        # what the guide names and what the spawn condition requires). Rendering it twice
        # with an identical source list is pure noise.
        _keyid = (_tut.get('key') or {}).get('i')
        _tut['ki'] = [x for x in (_resolve(_NSFIX(k)) for k in _ki)
                      if x and x.get('i') != _keyid]
        if not _tut['ki']:
            _tut.pop('ki')
        elif _tut.get('key') is None:
            pass
    # everything else attributed to this species - urns, treats, its own pedestal
    _extra = []
    _already = {(_tut.get('key') or {}).get('i')} | {x.get('i') for x in (_tut.get('ki') or [])}
    for _i in _MON2ITEM.get(_mon, []):
        if _i in _already:
            continue
        _n = _resolve(_i)
        if _n and '[LEGACY]' in str(_n.get('nm', '')):
            continue
        if _n and (_n.get('r') or _n.get('src')):
            _extra.append(_n)
    if _extra:
        _seen_nm, _dedup = set(), []
        for _n2 in _extra:
            _k2 = str(_n2.get('i') or _n2.get('nm'))
            if _k2 in _seen_nm:
                continue
            _seen_nm.add(_k2)
            _dedup.append(_n2)
        _tut['it'] = _dedup[:8]
    _fx = _TUT_FIX.get(_mon)
    if _fx:
        if _fx.get('steps'):
            _tut['steps'] = _fx['steps']
        if _fx.get('st'):
            _tut['st'] = (_tut.get('st') or []) + _fx['st']
        for _fi in (_fx.get('items') or []):
            _fn = _resolve(_NSFIX(_fi))
            if _fn:
                _tut.setdefault('it', []).append(_fn)
    # Dedupe last: _TUT_FIX items are appended after the guide's own, and the same item
    # arrives twice whenever a fix names something the guide already listed.
    if _tut.get('it'):
        # Seed the seen-set with the summon item itself. A _TUT_FIX list usually names
        # the species' own key item, which is already rendered above as tut['key'] with
        # the same source list - Genesect printed the Genesect Drive twice for exactly
        # this reason. 20 species carry such a list, so seed rather than special-case.
        _seen2 = {str((_tut.get('key') or {}).get('i') or '')}
        _seen2 |= {str(x.get('i') or x.get('nm')) for x in (_tut.get('ki') or [])}
        _seen2.discard('')
        _keep2 = []
        for _n3 in _tut['it']:
            _k3 = str(_n3.get('i') or _n3.get('nm'))
            if _k3 in _seen2:
                continue
            _seen2.add(_k3)
            _keep2.append(_n3)
        _tut['it'] = _keep2[:8]
        if not _tut['it']:
            _tut.pop('it')
    _disambiguate(_tut)
    _p['tut'] = _tut
    _ntut += 1

# _TUT_FIX species with neither a guide nor attributed gear - "you cannot get this
# here" is exactly the thing worth saying, and it had no home anywhere before
for _m2, _fx2 in _TUT_FIX.items():
    _p2 = _byname.get(_m2)
    if _p2 is None or _p2.get('tut'):
        continue
    _t2 = {}
    if _fx2.get('steps'):
        _t2['steps'] = _fx2['steps']
    if _fx2.get('st'):
        _t2['st'] = _fx2['st']
    for _fi2 in (_fx2.get('items') or []):
        _fn2 = _resolve(_NSFIX(_fi2))
        if _fn2:
            _t2.setdefault('it', []).append(_fn2)
    if _t2:
        _p2['tut'] = _t2
        _ntut += 1

# species with attributed gear but no guide of their own still deserve the entry
for _mon, _items in _MON2ITEM.items():
    _p = _byname.get(_mon)
    if not _p or _p.get('tut'):
        continue
    _rows = []
    for _i in _items:
        _n = _resolve(_i)
        if _n and '[LEGACY]' in str(_n.get('nm', '')):
            continue                    # disabled CobbleCuisine dishes - same filter
        if _n and (_n.get('r') or _n.get('src')):        # the guide path already applies
            _rows.append(_n)
    if _rows:
        _t = {'it': _rows[:8]}
        _disambiguate(_t)
        _p['tut'] = _t
        _ntut += 1
print('dex: %d mons given a full tutorial (%d with a resolved recipe chain)'
      % (_ntut, _nchain))

# ---- mark guides the Pokedex now covers -------------------------------------------
# Everything species-specific moved into the dex entry, but a handful of guides are
# cross-cutting prerequisites (Red Chain, Arc Phone, Origin Ingot) that no single
# species' chain reaches. Hiding the page wholesale would lose those, so mark what IS
# covered and let the page hide only that, with a toggle to show everything.
_reach = set()
for _p in dex:
    _t = _p.get('tut')
    if not _t:
        continue
    _stk = [_t.get('key')] + list(_t.get('ki') or []) + list(_t.get('it') or [])
    while _stk:
        _n = _stk.pop()
        if not isinstance(_n, dict):
            continue
        if _n.get('i'):
            _reach.add(str(_n['i']).split(':')[-1])
        for _g2 in ((_n.get('r') or {}).get('ings') or []):
            if _g2.get('i'):
                _reach.add(str(_g2['i']).split(':')[-1])
            if _g2.get('sub'):
                _stk.append(_g2['sub'])
        for _row in ((_n.get('r') or {}).get('g') or []):
            for _c in _row:
                if _c:
                    _reach.add(_c)

_covered_titles = set()
for _g3 in guides:
    _it3 = str(_g3.get('item') or '').split(':')[-1]
    if _mon_of(_g3.get('title', '')) or (_it3 and _it3 in _reach):
        _covered_titles.add(_g3.get('title'))
_ncov = 0
for _t3 in _covered_titles:
    _needle = '<div class="guide" data-title="%s"' % esc(_t3)
    if _needle in gh:
        gh = gh.replace(_needle, '<div class="guide covered" data-title="%s"' % esc(_t3))
        _ncov += 1
print('guides: %d of %d now covered by a Pokedex entry (hidden by default)'
      % (_ncov, len(guides)))

# evolution requirements - the single most looked-up thing, previously absent
_EVO = {re.sub(r'[^a-z0-9]', '', k.lower()): v for k, v in (D3.get('evo') or {}).items()}
_ne = 0
for p in dex:
    key = re.sub(r'[^a-z0-9]', '', str(p.get('n', '')).lower())
    e = _EVO.get(key)
    if e:
        p['ev'] = e
        _ne += 1
        bits = [str(p.get('q') or '')]
        if e.get('from'):
            bits.append(e['from'])
        for t in (e.get('to') or []):
            bits.append(t.get('to', ''))
            bits += [re.sub('<[^>]+>', '', x) for x in (t.get('req') or [])]
            bits.append(re.sub('<[^>]+>', '', t.get('how', '')))
        p['q'] = ' '.join(bits).lower()[:1400]
print('dex: %d mons given evolution requirements' % _ne)

_NOMODEL = {re.sub(r'[^a-z0-9]', '', x) for x in (D3.get('nomodel') or [])}
_nm = 0
for p in dex:
    if re.sub(r'[^a-z0-9]', '', str(p.get('n', '')).lower()) in _NOMODEL:
        p['nm'] = 1
        _nm += 1
print('dex: %d mons flagged as having no model' % _nm)

_OK = set(D3.get('bio_ok') or [])
_TAGMAP = {k: v for k, v in (D3.get('tag_map') or {}).items() if v}
# the dex payload drops namespaces ("#is_jungle", "badlands") while the source data
# keeps them ("#minecraft:is_jungle"), so match on the bare path as well.
_OK_SHORT = {b.split(':')[-1] for b in _OK}
_TAG_SHORT = {t.lstrip('#').split(':')[-1] for t in _TAGMAP}


def _reachable(b):
    b = str(b)
    if b.startswith('#'):
        body = b[1:]
        if ':' in body:
            return b in _TAGMAP
        return body in _TAG_SHORT
    if ':' in b:
        return b in _OK
    return b in _OK_SHORT


# "needs pumpkin nearby" reads like flavour. It is a hard gate with a very small radius,
# and the radius is a server config value nobody would think to look up: the block has to
# be within maxNearbyBlocksHorizontalRange of the spawn position, not of the player, and
# not of the general area. Put the real number in the condition so it cannot be misread.
_NB_H = _NB_V = None
try:
    _cbmain = json.load(open(COBBLEMON_DIR + '/config/cobblemon/main.json'))
    _NB_H = _cbmain.get('maxNearbyBlocksHorizontalRange')
    _NB_V = _cbmain.get('maxNearbyBlocksVerticalRange')
except Exception as _e:
    print('dex: could not read the nearby-block radius (%s)' % _e)

_nnb = 0
if _NB_H:
    _NBRE = re.compile(r'^needs (.+?) nearby$')
    for p in dex:
        for _s in p.get('sp', []) or []:
            _cs = _s.get('c') or []
            for _k, _c in enumerate(_cs):
                _m = _NBRE.match(str(_c))
                if not _m:
                    continue
                _cs[_k] = ('needs %s within %d blocks (and %d up/down)'
                           % (_m.group(1), _NB_H, _NB_V))
                _nnb += 1
    print('dex: %d nearby-block conditions given the real %d-block radius' % (_nnb, _NB_H))

# Sky light and light level are different numbers, and the difference decides whether
# you can safely torch a cave. 2,023 spawn entries use minSkyLight/maxSkyLight, which
# torches do not touch; only 14 use minLight/maxLight, which they do. Saying just
# "sky light 0-7" leaves a player guessing, and guessing wrong means hunting in the dark
# fighting mobs for no reason.
_LIGHT_TORCH = ' &mdash; torches are fine, only sky light counts'
_LIGHT_REAL = ' &mdash; <b>torches break this</b>'
_nlight = 0
for p in dex:
    for _s in p.get('sp', []) or []:
        _cs = _s.get('c') or []
        # If the same spawn also has a real light-level rule, do NOT tell the reader
        # torches are fine - they are not, and the two lines would contradict.
        _has_real = any(str(x).lower().startswith('light level') for x in _cs)
        for _k, _c in enumerate(_cs):
            _c = str(_c)
            low = _c.lower()
            if _LIGHT_TORCH in _c or _LIGHT_REAL in _c:
                continue
            if low.startswith('light level'):
                _cs[_k] = _c + _LIGHT_REAL
                _nlight += 1
            elif not _has_real and ('sky light' in low or low == 'must see the sky'):
                _cs[_k] = _c + _LIGHT_TORCH
                _nlight += 1
print('dex: %d light conditions labelled torch-safe or torch-breaking' % _nlight)
# Highlight the criteria a player has to ACT on. A spawn row's biome is the headline, but
# the rows that actually catch people out are the extra gates hiding in the condition list:
# Genesect needs an iron block within 4 blocks, and that read exactly like the ambient
# "on land" next to it. Bold only the gates you must seek out or set up - marking the
# positional/ambient ones too (on land, stand on natural ground, sky light) would put bold
# on nearly every row and highlight nothing.
_CRIT_RE = re.compile(
    r'^(?:needs .+?(?:nearby|within \d+ blocks.*)'
    r'|ONLY inside .+'
    r'|while (?:raining|thundering).*'
    r'|.*moon.*'
    r'|.*slime chunk.*'
    r'|height Y .+)$', re.I)
_CRIT_OPEN = '<b style="color:var(--warn)">'
_ncrit = _nrowcrit = 0
for p in dex:
    for _s in p.get('sp', []) or []:
        _cs = _s.get('c') or []
        _hit = False
        for _k, _c in enumerate(_cs):
            _c = str(_c)
            if _CRIT_OPEN in _c or not _CRIT_RE.match(_c.strip()):
                continue
            # the light pass may already have appended its own markup; keep that outside
            # the bold so the sentence does not end up bolded twice over
            _cs[_k] = _CRIT_OPEN + _c + '</b>'
            _ncrit += 1
            _hit = True
        if _hit:
            _nrowcrit += 1
print('dex: %d extra criteria highlighted across %d spawn rows' % (_ncrit, _nrowcrit))
# ---------------- regional forms ----------------
# The dex listed every spawn row for a species under one name, so Hisuian Voltorb's
# apricorn rule and base Voltorb's concrete rule sat side by side with nothing saying
# they are different Pokemon. Tauros was worse: three Paldean breeds rendered as three
# identical "Any Highlands" rows.
#
# The upstream spawncond prose is keyed by bare species name and cannot be split after
# the fact - base and regional rows share bucket, level and condition keys and differ
# only by biome, so matching prose back to jar rows is not reliable enough to trust.
# This reads the jars directly instead and emits a separate, authoritative block.
_REGIONAL = ('hisuian', 'galarian', 'alolan', 'paldean', 'valencian')
_RF_NAME = {'hisuian': 'Hisuian', 'galarian': 'Galarian', 'alolan': 'Alolan',
            'paldean': 'Paldean', 'valencian': 'Valencian'}
import zipfile as _rfz, glob as _rfg


def _rf_blocks(v):
    """Readable name for a block/tag list from neededNearbyBlocks / neededBaseBlocks."""
    out = []
    for b in (v if isinstance(v, list) else [v]):
        b = str(b).lstrip('#').split(':')[-1].replace('_', ' ')
        if b not in out:
            out.append(b)
    return ', '.join(out)


def _rf_cond(sp):
    """Compact, honest prose for one jar spawn entry's conditions."""
    c = sp.get('condition') or {}
    a = sp.get('anticondition') or {}
    out = []
    if c.get('neededNearbyBlocks'):
        if _NB_H:
            out.append('needs %s within %d blocks (and %d up/down)'
                       % (_rf_blocks(c['neededNearbyBlocks']), _NB_H, _NB_V))
        else:
            out.append('needs %s nearby' % _rf_blocks(c['neededNearbyBlocks']))
    if c.get('neededBaseBlocks'):
        out.append('stand on %s' % _rf_blocks(c['neededBaseBlocks']))
    if c.get('structures'):
        out.append('ONLY inside %s' % _rf_blocks(c['structures']))
    _lo, _hi = c.get('minSkyLight'), c.get('maxSkyLight')
    if _lo is not None or _hi is not None:
        out.append('sky light %s-%s' % (_lo if _lo is not None else 0,
                                        _hi if _hi is not None else 15))
    if c.get('canSeeSky') is True:
        out.append('must see the sky')
    elif c.get('canSeeSky') is False:
        out.append('must be under cover')
    if c.get('minY') is not None or c.get('maxY') is not None:
        out.append('height Y %s to %s' % (c.get('minY', '?'), c.get('maxY', '?')))
    if c.get('isRaining') is True:
        out.append('while raining')
    if c.get('isThundering') is True:
        out.append('while thundering')
    if c.get('moonPhase') is not None:
        out.append('moon phase %s' % c['moonPhase'])
    if c.get('isSlimeChunk') is True:
        out.append('in a slime chunk')
    if c.get('timeRange'):
        out.append('time: %s' % c['timeRange'])
    if a.get('biomes'):
        _anti = [x for x in (pretty_biome(b, solo=False) for b in a['biomes']) if x]
        if _anti:
            out.append('not in %s' % ', '.join(_anti))
    return out


_rf_pool = collections.defaultdict(lambda: collections.defaultdict(list))
_rf_bias = collections.defaultdict(set)
try:
    _rf_jars = sorted(_rfg.glob(COBBLEMON_DIR + '/mods/*.jar'))
except Exception:
    _rf_jars = []


def _rf_ingest(_spawns):
    for _sp in (_spawns or []):
        _pk = str(_sp.get('pokemon') or '').strip()
        if not _pk:
            continue
        _parts = _pk.split(' ')
        _base = _parts[0].lower()
        _form = None
        for _asp in _parts[1:]:
            if _asp in _REGIONAL:
                _form = _asp
            elif _asp.startswith('region_bias='):
                _rf_bias[_base].add(_asp.split('=', 1)[1])
        _rf_pool[_base][_form].append(_sp)


# Spawns added by a world datapack are just as real as the ones in the jars - the
# regional-form spawns this server adds (Hisuian Growlithe, Alolan Sandshrew, Hisuian
# Avalugg, Galarian Yamask) live there. Reading only the jars would leave them off the
# Pokedex while they spawn perfectly well in game.
_rf_dp = 0
for _dpf in sorted(_rfg.glob(COBBLEMON_DIR + '/world/datapacks/*/data/*/spawn_pool_world/*.json')):
    try:
        with open(_dpf, encoding='utf-8-sig') as _fh:
            _dpd = json.load(_fh)
    except Exception as _e:
        print('dex: could not read datapack spawn file %s (%s)' % (_dpf, _e))
        continue
    if _dpd.get('enabled') is False:
        continue
    _rf_ingest(_dpd.get('spawns'))
    _rf_dp += len(_dpd.get('spawns') or [])
if _rf_dp:
    print('dex: %d spawn entries read from world datapacks' % _rf_dp)
for _jp in _rf_jars:
    try:
        _z = _rfz.ZipFile(_jp)
    except Exception:
        continue
    for _n in sorted(_z.namelist()):
        if 'spawn_pool_world/' not in _n or not _n.endswith('.json'):
            continue
        try:
            _d = json.loads(_z.read(_n).decode('utf-8-sig'))
        except Exception:
            continue
        for _sp in (_d.get('spawns') or []):
            _pk = str(_sp.get('pokemon') or '').strip()
            if not _pk:
                continue
            _parts = _pk.split(' ')
            _base = _parts[0].lower()
            _form = None
            for _asp in _parts[1:]:
                if _asp in _REGIONAL:
                    _form = _asp
                elif _asp.startswith('region_bias='):
                    _rf_bias[_base].add(_asp.split('=', 1)[1])
            _rf_pool[_base][_form].append(_sp)

_nrf = 0
for p in dex:
    _key = re.sub(r'[^a-z0-9]', '', str(p.get('n', '')).lower())
    _forms = _rf_pool.get(_key)
    if not _forms or not any(f for f in _forms if f):
        continue
    _out = []
    # base form first, then regionals alphabetically, so the contrast reads top-down
    for _f in [None] + sorted(x for x in _forms if x):
        _rows = []
        _sigs = {}
        for _sp in _forms[_f]:
            _bi = [x for x in (pretty_biome(b, solo=False)
                               for b in ((_sp.get('condition') or {}).get('biomes') or [])) if x]
            if not _bi:
                continue          # every biome for this row is uninstalled here
            _cnd = [(_CRIT_OPEN + x + '</b>')
                    if _CRIT_RE.match(str(x).strip()) else x
                    for x in _rf_cond(_sp)]
            # Paldean Tauros ships three breeds (combat/blaze/aqua) that spawn in exactly
            # the same place, so listing them as rows printed the same line three times.
            # Collapse identical rows and name the variants instead.
            _var = [a for a in str(_sp.get('pokemon') or '').split(' ')[1:]
                    if a not in _REGIONAL and not a.startswith('region_bias=')]
            _sig = (str(_sp.get('bucket')), str(_sp.get('level')),
                    tuple(_bi), tuple(_cnd))
            if _sig in _sigs:
                for _v in _var:
                    if _v not in _sigs[_sig]['v']:
                        _sigs[_sig]['v'].append(_v)
                continue
            _row = {'b': _sp.get('bucket') or '?',
                    'l': str(_sp.get('level') or '?'),
                    'bi': _bi, 'c': _cnd, 'v': list(_var)}
            _sigs[_sig] = _row
            _rows.append(_row)
        for _row in _rows:
            if not _row['v']:
                _row.pop('v')
            else:
                # 'bull_breed=combat' reads best as 'combat', but 'wooper_heart=true'
                # reads as a bare 'true' - for boolean aspects the KEY is the label.
                _vv = []
                for _x in _row['v']:
                    _x = str(_x)
                    if '=' in _x:
                        _vk, _vval = _x.split('=', 1)
                        _vv.append(_vk.replace('_', ' ') if _vval in ('true', 'false')
                                   else _vval.replace('_', ' '))
                    else:
                        _vv.append(_x.replace('_', ' '))
                _row['v'] = _vv
        if _rows:
            _out.append({'f': _RF_NAME.get(_f, 'Base form' if _f is None else _f),
                         'rows': _rows})
    if len(_out) > 1 or (_out and _out[0]['f'] != 'Base form'):
        p['rf'] = _out
        _nrf += 1
print('dex: %d species given a per-form spawn breakdown' % _nrf)

_nbias = 0
for p in dex:
    _key = re.sub(r'[^a-z0-9]', '', str(p.get('n', '')).lower())
    _bias = _rf_bias.get(_key)
    if _bias:
        # region_bias is NOT a form of this Pokemon - it decides which regional form it
        # evolves INTO. Pikachu has no Alolan form, but a beach Pikachu gives Alolan Raichu.
        p['rb'] = sorted(_bias)
        _nbias += 1
print('dex: %d species carry a region_bias evolution note' % _nbias)
# The search box matches a flat lowercase blob (p['q']). Without these words, typing
# "alolan" found nothing at all even though 35 spawns use that aspect. Both spellings go
# in - people type the adjective (alolan) and the region (alola) about equally.
_RF_SEARCH = {'Hisuian': 'hisuian hisui', 'Galarian': 'galarian galar',
              'Alolan': 'alolan alola', 'Paldean': 'paldean paldea',
              'Valencian': 'valencian valencia'}
_nq = 0
for p in dex:
    _terms = []
    for _g in (p.get('rf') or []):
        _t = _RF_SEARCH.get(_g.get('f'))
        if _t:
            _terms.append(_t)
    for _b in (p.get('rb') or []):
        _terms.append('region bias %s' % str(_b).lower())
    if not _terms:
        continue
    if p.get('rf'):
        _terms.append('regional form')
    p['q'] = ((p.get('q') or '') + ' ' + ' '.join(_terms)).strip().lower()
    _nq += 1
print('dex: %d entries made searchable by regional form' % _nq)

# A regional form you can only EVOLVE into has no spawn row, so the block above skips it
# entirely - Hisuian Arcanine and Alolan Sandslash were invisible to a "hisuian" search
# even though both are now obtainable. Read the evolution tables and credit the target.
_rf_evo = collections.defaultdict(list)
for _jp in _rf_jars:
    try:
        _z = _rfz.ZipFile(_jp)
    except Exception:
        continue
    for _n in _z.namelist():
        if '/species/' not in _n or not _n.endswith('.json'):
            continue
        try:
            _d = json.loads(_z.read(_n).decode('utf-8-sig'))
        except Exception:
            continue
        _src = str(_d.get('name') or '')
        for _fname, _blk in [(None, _d)] + [(f.get('name'), f) for f in (_d.get('forms') or [])]:
            for _ev in (_blk.get('evolutions') or []):
                _res = str(_ev.get('result') or '').strip().split(' ')
                if len(_res) < 2:
                    continue
                _tform = next((a for a in _res[1:] if a in _REGIONAL), None)
                if not _tform:
                    continue
                _rq = str(_ev.get('requiredContext') or '')
                _rf_evo[re.sub(r'[^a-z0-9]', '', _res[0].lower())].append(
                    {'f': _RF_NAME.get(_tform, _tform), 'from': _src,
                     'item': nice(_rq.split(':')[-1]) if _rq else '',
                     'how': str(_ev.get('variant') or '').replace('_', ' ')})

_nevo = 0
for p in dex:
    _key = re.sub(r'[^a-z0-9]', '', str(p.get('n', '')).lower())
    _evs = _rf_evo.get(_key)
    if not _evs:
        continue
    _have = {g.get('f') for g in (p.get('rf') or [])}
    _new = [e for e in _evs if e['f'] not in _have]
    if not _new:
        continue
    _seen_e, _keep_e = set(), []
    for _e in _new:
        _k = (_e['f'], _e['from'])
        if _k in _seen_e:
            continue
        _seen_e.add(_k)
        _keep_e.append(_e)
    p['rfe'] = _keep_e
    _terms = [_RF_SEARCH.get(e['f'], '') for e in _keep_e]
    p['q'] = ((p.get('q') or '') + ' ' + ' '.join(_terms) + ' regional form').strip().lower()
    _nevo += 1
print('dex: %d evolution-only regional forms credited and made searchable' % _nevo)

# ---------------- cosmetic items ----------------
# Cobblemon renders a cosmetic on 25 species and documents it nowhere. On Pikachu the
# regional delicacies each produce one of Ash's caps.
#
# READ THE RIGHT FILE. `species_features/cosmetic_item.json` also lists choices, but it is
# a parallel definition and its list is INCOMPLETE - pewter_crunchies is missing from it.
# Trusting it made this build wrongly report Ash's signature Partner cap as unobtainable.
# `data/cobblemon/cosmetic_items/*.json` is the real assignment data: it names the species,
# the item, and the aspect, and its field is `consumedItem` - the item is consumed and the
# look is permanent, which is also why simply HOLDING the item does nothing.
_COS_DEF = collections.defaultdict(dict)        # species -> {item id: [aspects]}
_COS_LOOK = collections.defaultdict(dict)      # species -> {aspect: texture label}
for _jp in _rf_jars:
    try:
        _z = _rfz.ZipFile(_jp)
    except Exception:
        continue
    for _n in _z.namelist():
        if not _n.endswith('.json'):
            continue
        if '/cosmetic_items/' in _n:
            try:
                _cd = json.loads(_z.read(_n).decode('utf-8-sig'))
            except Exception:
                continue
            for _sp in (_cd.get('pokemon') or []):
                _spk = re.sub(r'[^a-z0-9]', '', str(_sp).lower())
                for _ci in (_cd.get('cosmeticItems') or []):
                    _item = str(_ci.get('consumedItem') or '')
                    if not _item:
                        continue
                    # dyes.json lists BOTH spellings of the same thing (color-white and
                    # colour-white). Keying by the consumed item collapses them, which is
                    # what a reader cares about anyway: one dye, one result.
                    _COS_DEF[_spk].setdefault(_item, [])
                    for _a in (_ci.get('aspects') or []):
                        if str(_a) not in _COS_DEF[_spk][_item]:
                            _COS_DEF[_spk][_item].append(str(_a))
        elif '/resolvers/' in _n and 'resourcepacks/' not in _n:
            # the jar bundles alternate-form resolvers under resourcepacks/; their texture
            # names describe that form, not the cosmetic, and they labelled a pair of
            # shears "Fluff Alola Bias Male"
            try:
                _cd = json.loads(_z.read(_n).decode('utf-8-sig'))
            except Exception:
                continue
            _spk = re.sub(r'[^a-z0-9]', '', str(_cd.get('species') or '').split(':')[-1].lower())
            for _v in (_cd.get('variations') or []):
                _asps = [a for a in (_v.get('aspects') or []) if a != 'male']
                # a variation keyed on exactly one aspect describes that aspect alone;
                # multi-aspect ones are gender/shiny combinations of the same look
                if len(_asps) != 1:
                    continue
                _tex = ''
                for _L in (_v.get('layers') or []):
                    _tex = str(_L.get('texture') or '').split('/')[-1].replace('.png', '')
                if not _tex:
                    _tex = str(_v.get('model') or '').split(':')[-1].replace('.geo', '')
                if _tex:
                    _COS_LOOK[_spk].setdefault(str(_asps[0]), _tex)

_ncos = 0
for p in dex:
    _key = re.sub(r'[^a-z0-9]', '', str(p.get('n', '')).lower())
    _defs = _COS_DEF.get(_key)
    if not _defs:
        continue
    _looks = _COS_LOOK.get(_key) or {}
    _rows = []
    for _item in sorted(_defs):
        _look = ''
        for _a in _defs[_item]:
            if _a in _looks:
                _look = _looks[_a]
                break
        _rows.append({'i': nice(_item.split(':')[-1]),
                      'l': nice(_look.replace(_key + '_', '')) if _look else ''})
    if _rows:
        p['cos'] = _rows
        p['q'] = ((p.get('q') or '') + ' cosmetic item hat cap accessory dye').strip().lower()
        _ncos += 1
_cosnoart = sum(1 for p in dex for r in (p.get('cos') or []) if not r['l'])
print('dex: %d species given a cosmetic-item block (%d entries with no distinct artwork)'
      % (_ncos, _cosnoart))

# ---------------- evolutions, rebuilt form-aware ----------------
# D3['evo'] is keyed by bare species name, so a form's evolution is invisible: Yamask's
# entry claimed one evolution (Cofagrigus) and never mentioned that GALARIAN Yamask
# becomes Runerigus, and Runerigus's entry never said where it comes from. 85 of the 742
# evolutions in the game live on a form block rather than the base species.
#
# Rebuilt from the species files so both ends of every branch are named, and so each of
# the 22 requirement variants renders in words rather than being silently dropped.
_EV_HOW = {'level_up': 'Level it up', 'item_interact': 'Use an item on it',
           'trade': 'Trade it'}


def _ev_form_label(fname, aspects):
    for _a in (aspects or []):
        if _a in _REGIONAL:
            return _RF_NAME[_a]
    return str(fname or '')


def _ev_result(res):
    parts = str(res).strip().split(' ')
    form = ''
    for _a in parts[1:]:
        if _a in _REGIONAL:
            form = _RF_NAME[_a]
    return nice(parts[0]), form


def _ev_req(r):
    """One requirement -> one readable clause. Every variant in the game is handled."""
    v = str(r.get('variant') or '')
    if v == 'level':
        # minLevel 0 means no level gate at all - 'reach level 0' reads like a bug, and
        # it lands on exactly the entry people look up (Galarian Yamask -> Runerigus).
        if not r.get('minLevel'):
            return 'any level'
        return 'reach <b>level %s</b>' % r.get('minLevel')
    if v == 'held_item':
        return 'hold <b>%s</b>' % nice(str(r.get('itemCondition') or '').split(':')[-1])
    if v == 'friendship':
        return 'friendship <b>%s+</b>' % r.get('amount')
    if v == 'time_range':
        return 'during <b>%s</b>' % str(r.get('range'))
    if v == 'weather':
        if r.get('isThundering'):
            return 'while <b>thundering</b>'
        if r.get('isRaining'):
            return 'while <b>raining</b>'
        return 'in <b>clear weather</b>'
    if v == 'moon_phase':
        return 'during a <b>%s</b>' % nice(str(r.get('moonPhase') or '').lower())
    if v == 'has_move':
        return 'know the move <b>%s</b>' % nice(str(r.get('move')))
    if v == 'has_move_type':
        return 'know any <b>%s</b>-type move' % nice(str(r.get('type')))
    if v == 'use_move':
        return 'use <b>%s</b> <b>%s</b> times' % (nice(str(r.get('move'))), r.get('amount'))
    if v == 'damage_taken':
        return 'take <b>%s</b> damage without fainting' % r.get('amount')
    if v == 'recoil':
        return 'take <b>%s</b> recoil damage' % r.get('amount')
    if v == 'battle_critical_hits':
        return 'land <b>%s</b> critical hits in one battle' % r.get('amount')
    if v == 'blocks_traveled':
        return 'walk <b>%s</b> blocks with it out' % r.get('amount')
    if v == 'defeat':
        return 'defeat <b>%s</b> %s' % (r.get('amount'),
                                        nice(str(r.get('target') or '').split(' ')[0]))
    if v == 'party_member':
        _t = nice(str(r.get('target') or '').split(' ')[0])
        if r.get('contains', True):
            return 'with <b>%s</b> in your party' % _t
        return 'with <b>no %s</b> in your party' % _t
    if v == 'advancement':
        _adv = str(r.get('requiredAdvancement') or '').split(':')[-1]
        return 'earn the advancement <b>%s</b>' % nice(_adv)
    if v == 'properties':
        _t = str(r.get('target') or '')
        if _t.startswith('gender='):
            return 'must be <b>%s</b>' % _t.split('=', 1)[1]
        return 'must be <b>%s</b>' % nice(_t.replace('=', ' '))
    if v == 'property_range':
        return '<b>%s</b> in range <b>%s</b>' % (nice(str(r.get('feature') or '')),
                                                 r.get('range'))
    if v == 'stat_compare':
        return '<b>%s</b> higher than <b>%s</b>' % (nice(str(r.get('highStat'))),
                                                    nice(str(r.get('lowStat'))))
    if v == 'stat_equal':
        return '<b>%s</b> equal to <b>%s</b>' % (nice(str(r.get('statOne'))),
                                                 nice(str(r.get('statTwo'))))
    if v == 'biome':
        _c = r.get('biomeCondition')
        _anti = r.get('biomeAnticondition')
        _ref = _c or _anti
        _nm = pretty_biome(_ref, solo=False)
        if not _nm:
            _nm = str(_ref).lstrip('#').split(':')[-1].replace('_', ' ')
        if _anti:
            return '<b>NOT</b> in %s' % _nm
        return 'in <b>%s</b>' % _nm
    if v == 'structure':
        _c = r.get('structureCondition')
        _anti = r.get('structureAnticondition')
        _nm = nice(str(_c or _anti).lstrip('#').split(':')[-1].replace('/', ' '))
        if _anti:
            return '<b>NOT</b> inside %s' % _nm
        return 'inside <b>%s</b>' % _nm
    return nice(v.replace('_', ' '))


_ev_to = collections.defaultdict(list)
_ev_from = collections.defaultdict(list)
for _jp in _rf_jars:
    try:
        _z = _rfz.ZipFile(_jp)
    except Exception:
        continue
    for _n in _z.namelist():
        if '/species/' not in _n or not _n.endswith('.json'):
            continue
        try:
            _sd = json.loads(_z.read(_n).decode('utf-8-sig'))
        except Exception:
            continue
        _src = str(_sd.get('name') or '')
        if not _src:
            continue
        _skey = re.sub(r'[^a-z0-9]', '', _src.lower())
        _blocks = [(None, _sd)] + [(f.get('name'), f) for f in (_sd.get('forms') or [])]
        for _fname, _blk in _blocks:
            _sform = ''
            if _fname:
                _sform = _ev_form_label(_fname, _blk.get('aspects'))
            for _ev in (_blk.get('evolutions') or []):
                _rn, _rform = _ev_result(_ev.get('result') or '')
                if not _rn:
                    continue
                _how = _EV_HOW.get(str(_ev.get('variant')), nice(str(_ev.get('variant') or '')))
                _ctx = str(_ev.get('requiredContext') or '')
                if _ctx:
                    _how = 'Use a <b>%s</b> on it' % nice(_ctx.split(':')[-1])
                _reqs = [_ev_req(r) for r in (_ev.get('requirements') or [])]
                _row = {'to': _rn, 'form': _rform, 'how': _how, 'req': _reqs,
                        'eat': bool(_ev.get('consumeHeldItem')), 'sform': _sform}
                if _row not in _ev_to[_skey]:
                    _ev_to[_skey].append(_row)
                _back = {'from': _src, 'form': _sform, 'how': _how, 'req': _reqs,
                         'tform': _rform}
                _rkey = re.sub(r'[^a-z0-9]', '', _rn.lower())
                if _back not in _ev_from[_rkey]:
                    _ev_from[_rkey].append(_back)

_nev2 = 0
_nform_ev = 0
for p in dex:
    _key = re.sub(r'[^a-z0-9]', '', str(p.get('n', '')).lower())
    _to = _ev_to.get(_key)
    _fr = _ev_from.get(_key)
    if not _to and not _fr:
        continue
    _e = {}
    if _to:
        _e['to'] = _to
        _nform_ev += sum(1 for r in _to if r.get('sform'))
    if _fr:
        _e['fr2'] = _fr
        _e['from'] = (p.get('ev') or {}).get('from') or _fr[0]['from']
    p['ev'] = _e
    _nev2 += 1
    _bits = [str(p.get('q') or '')]
    for _t in (_to or []):
        _bits += [_t['to'], _t.get('sform', ''), _t.get('form', '')]
        _bits += [re.sub('<[^>]+>', '', x) for x in _t['req']]
    for _f in (_fr or []):
        _bits += [_f['from'], _f.get('form', '')]
    p['q'] = ' '.join(x for x in _bits if x).lower()[:1800]
print('dex: %d mons given form-aware evolutions (%d branches are form-specific)'
      % (_nev2, _nform_ev))






# A spawn will not fire unless there is clear room for the Pokemon: ceil(hitbox *
# baseScale) blocks wide and tall. Small ones never notice; a Rayquaza in dense jungle
# will not appear at all until you cut a hole. Say so on the entries where it matters.
_SPACE = (_RX.get('space') or {})
_nspace = 0
for p in dex:
    _key = re.sub(r'[^a-z0-9]', '', str(p.get('n', '')).lower())
    _wh = _SPACE.get(_key)
    if not _wh:
        continue
    _w, _h = _wh
    if _w < 3 and _h < 4:
        continue                     # fits anywhere a player does; not worth the noise
    _txt = ('needs <b>%d&times;%d&times;%d</b> of clear space to appear' % (_w, _h, _w))
    for _s in p.get('sp', []) or []:
        _cs = _s.setdefault('c', [])
        if not any('clear space' in str(x) for x in _cs):
            _cs.append(_txt)
    _nspace += 1
print('dex: %d species told how much clear space they need' % _nspace)

# Form changes are invisible in game. An item in a chest can change a Pokemon's model and
# its battling, and nothing tells you which item or which Pokemon - so attach it to the
# entry, where somebody looking that Pokemon up will actually see it.
_GMAX_SET = {'alcremie', 'blastoise', 'butterfree', 'charizard', 'cinderace',
             'coalossal', 'copperajah', 'corviknight', 'drednaw', 'duraludon',
             'eevee', 'garbodor', 'gengar', 'machamp', 'melmetal', 'meowth',
             'orbeetle', 'pikachu', 'rillaboom', 'sandaconda', 'snorlax',
             'toxtricity', 'urshifu', 'venusaur'}
_MEGAS = _RX.get('megas') or {}
_BFORMS = _RX.get('battleforms') or {}
_INTER = _RX.get('interactions') or {}


def _pretty_form(f, mon):
    f = re.sub(r'^%s[_-]?' % re.escape(mon), '', str(f))
    return nice(f) if f else 'base form'


def _forms_html(mon, name):
    rows = []
    stone = _MEGAS.get(mon)
    if stone:
        _sid = _NSFIX(stone)
        _rec = recipe_html(_sid)
        rows.append('<div class="frow"><span class="fkey">mega</span>'
                    '<b>%s can Mega Evolve.</b> It has to <b>hold the %s</b>, and you have '
                    'to be wearing a <b>Mega Bracelet</b> <i>or</i> an <b>Omni Ring</b> &mdash; both '
                    'halves, or nothing happens. The Omni Ring covers Mega, Dynamax, '
                    'Tera and Z at once, so it is the one to aim for.'
                    '%s</div>' % (esc(name), esc(nice(stone)), _rec))
    bf = _BFORMS.get(mon) or []
    if bf:
        _extra = ('' if mon != 'greninja' else
                  ' The Ash form needs an <b>Ash Cap</b> &mdash; 5 red, 2 white and 1 green '
                  'wool, and easy to miss.')
        rows.append('<div class="frow"><span class="fkey">forms</span>'
                    'Has alternate forms: <b>%s</b>. Some switch on their own with the '
                    'weather or mid-battle; others need an accessory.%s</div>'
                    % (esc(', '.join(sorted({_pretty_form(f, mon) for f in bf}))), _extra))
    for it in (_INTER.get(mon) or []):
        _need = str(it.get('need') or '')
        _b, _tip = _cell_item(_need)
        _eff = []
        for e in it.get('eff') or []:
            if e.startswith('form:'):
                _eff.append('<b>changes its form</b>')
            else:
                _eff.append(esc(e))
        rows.append('<div class="frow"><span class="fkey">hold &amp; use</span>'
                    '%sRight-click it holding <b>%s</b> &mdash; %s.</div>'
                    % ('<span class="ic icsm" data-i="%s"></span>' % esc(_b) if _b else '',
                       esc(nice(_b or _need)), ', '.join(_eff)))
    if mon in _GMAX_SET:
        rows.append('<div class="frow"><span class="fkey">G-max</span>'
                    '<b>%s has a Gigantamax form</b> &mdash; one of only 24. Any '
                    'Pok&eacute;mon can Dynamax with the Band; only these 24 change '
                    'shape when they do.</div>' % esc(name))
    if not rows:
        return ''
    return ('<div class="forms"><h4>Forms and items</h4>%s'
            '<div class="frow muted sm">Mega stones, the Bracelet, the Dynamax Band, the '
            'Tera Orb and the Z-Ring are all craftable &mdash; see the Mechanics tab.</div>'
            '</div>' % ''.join(rows))


_nforms = 0
for p in dex:
    _k = re.sub(r'[^a-z0-9]', '', str(p.get('n', '')).lower())
    _h = _forms_html(_k, p.get('n', ''))
    if _h:
        p['fm'] = _h
        _nforms += 1
print('dex: %d entries given a forms-and-items block' % _nforms)

# Structure <-> species, both ways. The Arc Phone will happily track a "Throne Room of
# Knightly Heroes" without ever saying that is where Zacian and Zamazenta live, and the
# Structures page did not say either. Derived from the blocks inside each structure, so it
# does not depend on the guide text - which is what left Zamazenta with no route line while
# Zacian had one.
def _pretty_struct(sid):
    """Title-case a structure id without shouting the joining words."""
    small = {'of', 'the', 'and', 'in', 'on'}
    parts = str(sid).replace("_", " ").split()
    return " ".join(w if i and w in small else w.capitalize()
                    for i, w in enumerate(parts))


_STRUCTMONS = _RX.get('structmons') or {}
_MON2STRUCT = {}
for _st, _sps in _STRUCTMONS.items():
    for _sp in _sps:
        _MON2STRUCT.setdefault(_sp, [])
        if _st not in _MON2STRUCT[_sp]:
            _MON2STRUCT[_sp].append(_st)

# 24 species have a Gigantamax form. Dynamax is not per-species - the band works on
# anything - so only the G-max list is worth naming.
_GMAX = {'alcremie', 'blastoise', 'butterfree', 'charizard', 'cinderace', 'coalossal',
         'copperajah', 'corviknight', 'drednaw', 'duraludon', 'eevee', 'garbodor',
         'gengar', 'machamp', 'melmetal', 'meowth', 'orbeetle', 'pikachu', 'rillaboom',
         'sandaconda', 'snorlax', 'toxtricity', 'urshifu', 'venusaur'}

_nstruct = 0
for p in dex:
    _k = re.sub(r'[^a-z0-9]', '', str(p.get('n', '')).lower())
    _sts = _MON2STRUCT.get(_k) or []
    _eq = []
    if _sts:
        _bits = []
        for _st in _sts:
            # exact lookup misses 'traditional_village/ecruteak' and friends;
            # arc_track_for does the prefix match the structures page already relies on

            _track = arc_track_for(_st)
            _art = 'an' if _track and _track[0].upper() in 'AEIOU' else 'a'
            _bits.append('<b>%s</b>%s' % (esc(_pretty_struct(_st)),
                                          (' &mdash; track it by carrying %s <b>%s</b>'
                                           % (_art, esc(_track))) if _track else ''))
            _eq.append(nice(_st).lower())
            if _track:
                _eq.append(str(_track).lower())
        p['st2'] = 'Found in: ' + '; '.join(_bits) + '.'
        _nstruct += 1
    if _k in _MEGAS:
        _eq += ['mega', 'mega evolution', 'megaevolve', _MEGAS[_k]]
    if _k in _GMAX:
        _eq += ['gigantamax', 'gmax', 'dynamax']
    if _eq:
        p['q'] = ((p.get('q') or '') + ' ' + ' '.join(_eq)).lower()[:1800]
print('dex: %d entries told which structure they come from' % _nstruct)

# Fossil revival is a whole route the Pokedex never mentioned. The four Galar fossil
# Pokemon have no spawn pool anywhere, so their entries were completely blank.
_FOSSILS = _RX.get('fossils') or {}
_NATMATS = _RX.get('natmats') or {}

# Which species each fossil item feeds. The Galar four share a pool of four fossils and
# every one of them is used by exactly two Pokemon, so spending a Fossilized Drake is
# always a decision against something else. An entry that does not say so is a trap.
_FOSSIL_USERS = {}
for _sp, _fl in _FOSSILS.items():
    for _fi in _fl:
        _FOSSIL_USERS.setdefault(str(_fi), []).append(_sp)

_DEXNAME = {re.sub(r'[^a-z0-9]', '', str(p.get('n', '')).lower()): str(p.get('n', ''))
            for p in dex}

# "Put organic material in the tank" is useless without the arithmetic. But sorting by
# value picks Nether Stars and Dragon Eggs - true, and advice nobody should follow.
# Curate to things you can farm, with their own plural labels so the sentence reads.
_FILL = 128
_NATPREF = [('minecraft:hay_block', 'hay blocks'),
            ('cobblemon:hearty_grain_bale', 'hearty grain bales'),
            ('minecraft:bread', 'bread'),
            ('minecraft:bone_meal', 'bone meal'),
            ('#cobblemon:berries', 'berries')]
_natpick = [(_NATMATS[_k], _lbl) for _k, _lbl in _NATPREF if _k in _NATMATS][:4]
_natstr = ', or '.join('<b>%d</b> %s' % (-(-_FILL // _v), esc(_lbl))
                       for _v, _lbl in _natpick)

_nfos = 0
for p in dex:
    _k = re.sub(r'[^a-z0-9]', '', str(p.get('n', '')).lower())
    _f = _FOSSILS.get(_k)
    if not _f:
        continue
    _names = [nice(str(x).split(':')[-1]) for x in _f]

    # searchable by the fossil's own name - "dome", "claw fossil", "old amber" should all
    # land on the Pokemon they make, which is the whole reason to look a fossil up
    _fq = ' '.join([str(x).split(':')[-1].replace('_', ' ') for x in _f])
    p['q'] = ((p.get('q') or '') + ' ' + _fq
              + ' fossil fossils revive revived restoration fossil analyzer'
              + (' galar combination combo two fossils' if len(_f) > 1 else '')
              ).lower()[:1800]

    if len(_names) > 1:
        _first = ('<b>Revived from a fossil</b>, not caught &mdash; and it takes <b>two</b>: '
                  '<b>%s</b> and <b>%s</b>.' % (_names[0], _names[1]))
        _second = (
            'The Galar fossils pair a <b>head</b> with a <b>body</b>, and the halves name the '
            'Pok&eacute;mon. Head: <b>Fossilized Dino</b> makes <b>Arcto</b>-, '
            '<b>Fossilized Drake</b> makes <b>Draco</b>-. Body: <b>Fossilized Fish</b> makes '
            '-<b>vish</b>, <b>Fossilized Bird</b> makes -<b>zolt</b>.')
    else:
        _first = ('<b>Revived from a fossil</b>, not caught. You need %s <b>%s</b>.'
                  % ('an' if _names[0][0].upper() in 'AEIOU' else 'a', _names[0]))
        _second = ('Fossils are <b>brushed out of suspicious blocks</b> at prehistoric dig '
                   'sites. This one is yours alone &mdash; no other Pok&eacute;mon uses it.')

    _steps = [
        _first,
        _second,
        ('Build the machine: a <b>Fossil Analyzer</b> with a <b>Data Monitor</b> directly '
         '<b>on top of it</b>, and a <b>Restoration Tank</b> against any one of its four '
         'sides. The tank is two blocks tall and builds itself when you place it.'),
        ('Fill the tank with organic material until it reads full. It wants '
         '<b>%d units</b> &mdash; that is %s. Anything organic counts; richer food '
         'fills it faster.' % (_FILL, _natstr or 'a lot of food or plant matter')),
        ('Put the fossil%s in the analyzer and wait <b>12 minutes</b>. The machine is '
         '<b>locked to you</b> while it runs, so nobody else can take the result. This '
         'server allows <b>2 fossils</b> in at once, which is exactly what a pair needs.'
         % ('s' if len(_f) > 1 else '')),
    ]

    # the actual trap: every Galar fossil is used by two different Pokemon
    _shared = []
    for _fi in _f:
        _others = [_DEXNAME.get(x, x).title() for x in _FOSSIL_USERS.get(str(_fi), [])
                   if x != _k]
        if _others:
            _shared.append('<b>%s</b> is also the one for <b>%s</b>'
                           % (nice(str(_fi).split(':')[-1]), ', '.join(sorted(_others))))
    if _shared:
        _steps.append(
            '<b>Think before you spend it.</b> %s. A full set of all four Galar fossils makes '
            '<b>exactly two</b> Pok&eacute;mon, and choosing one pair decides the other: '
            'Arctovish leaves you Dracozolt, and Arctozolt leaves you Dracovish. There is no '
            'set of four that gives you three.' % '; '.join(_shared))

    _tut = p.get('tut') or {'t': 'Revive %s' % p.get('n', '')}
    _tut['steps'] = _steps
    _tut.setdefault('t', 'Revive %s' % p.get('n', ''))
    _it = _tut.setdefault('it', [])
    for _fi in list(_f) + ['cobblemon:fossil_analyzer', 'cobblemon:restoration_tank',
                           'cobblemon:monitor']:
        _node = _resolve(_NSFIX(str(_fi)))
        if _node and not any(x.get('i') == _node.get('i') for x in _it):
            _it.append(_node)
    _tut['it'] = _it[:8]
    p['tut'] = _tut
    _nfos += 1
print('dex: %d species given a fossil-revival route' % _nfos)
print('dex: %d fossil items made searchable' % len(_FOSSIL_USERS))

# Saying "we could not find a route" is worse than saying nothing; saying "there is no
# route" is the useful thing, and it is checkable: no spawn pool, no key item, no
# evolution, no fossil anywhere in the installed mods.
_nnone = 0
for p in dex:
    if p.get('tut') or (p.get('sp') or []) or p.get('ev'):
        continue
    p['tut'] = {'t': 'Not obtainable here', 'steps': [
        '<b>There is no way to get this one on this server.</b> No spawn pool, no key '
        'item, no evolution and no fossil route exists for it in any installed mod '
        '&mdash; checked across every jar.',
        'That is a gap in the mods, not in this page. It would take a datapack or a '
        'creative-mode spawn to have one.']}
    _nnone += 1
print('dex: %d species marked as having no route at all' % _nnone)

# Addon species that are not in the base 1025 - the Baby Legends pre-evolutions above
# all. Without this they exist in game and are entirely absent from the Pokedex, which is
# the one place anyone would look for them.
def _addon_biome(b):
    """Plain name for an addon spawn biome.

    pretty_biome() is built for the structures page and expects the prebuilt tag
    map; fed a raw id it returns nothing useful. These are simple enough to name
    directly: "#cobblemon:is_jungle" -> "Jungle".
    """
    b = str(b).lstrip("#").split(":")[-1]
    if b.startswith("is_"):
        b = b[3:]
    return b.replace("_", " ").title()


_CUSTOM = _RX.get('customspecies') or {}
_have = {re.sub(r'[^a-z0-9]', '', str(p.get('n', '')).lower()) for p in dex}
_SPAWNS_BY = collections.defaultdict(list)
for _sp in dex:
    pass
_nadd = 0
for _k, _c in sorted(_CUSTOM.items()):
    if _k in _have:
        continue
    _t = [x for x in (_c.get('t1'), _c.get('t2')) if x]
    _nm2 = str(_c.get('name') or '')
    if _nm2 == _nm2.lower():
        _nm2 = _nm2[:1].upper() + _nm2[1:]          # some addons ship lowercase names
    _sp2 = []
    for _r2 in (_c.get('spawns') or []):
        _sp2.append({'b': _r2.get('b'), 'l': _r2.get('l'),
                     'bi': [_addon_biome(x) for x in (_r2.get('bi') or [])] or ['any'],
                     'c': []})
    _entry = {
        'n': _nm2, 'd': 0, 't': _t, 'lb': [], 'dr': [], 'sp': _sp2, 'r': [],
        'st': [], 'q': ('%s addon %s' % (_nm2, _c.get('src', ''))).lower(),
    }
    _evo = _c.get('evo') or []
    if _evo:
        _entry['ev'] = {'to': [{'to': nice(e['to']), 'form': '',
                                'how': 'Evolve it',
                                'req': e.get('req') or []} for e in _evo]}
        _tgt = ', '.join(nice(e['to']) for e in _evo)
        _how = '; '.join('; '.join(e.get('req') or ['no stated requirement']) for e in _evo)
        _entry['tut'] = {'t': 'Raise %s' % _nm2, 'steps': [
            '<b>A pre-evolution added by an addon</b> (%s). It is not one of the original '
            '1025, so nothing else will tell you it exists.' % esc(_c.get('src', 'an addon')),
            '<b>It evolves into %s.</b> Requirement: <b>%s</b>.' % (esc(_tgt), esc(_how)),
            'That makes it a <b>second route</b> to that legendary &mdash; catch and raise '
            'this instead of hunting the ritual or the key item.']}
        _entry['q'] += ' ' + ' '.join(nice(e['to']).lower() for e in _evo) + ' baby pre-evolution'
    dex.append(_entry)
    # biomes here are already display names; the reachability filter below reads raw
    # ids, so without this it finds nothing recognisable and blanks every one.
    _FULL.add(_k)
    _nadd += 1
print('dex: %d addon species spliced in' % _nadd)

_nbio = 0
if _OK:
    for p in dex:
        if re.sub(r'[^a-z0-9]', '', str(p.get('n', '')).lower()) in _FULL:
            continue
        for s in p.get('sp', []):
            src = s.get('bi') or []
            keep = [b for b in src if _reachable(b)]
            if len(keep) != len(src):
                _nbio += len(src) - len(keep)
                s['bi'] = keep
    print('dex: removed %d unreachable biome entries' % _nbio)

# Some mons (Type: Null) have M&L spawns that never reached the dex payload, so the
# Pokedex showed them as having no spawns at all. Backfill from the guide data.
_spawnmap = {}
for g in guides:
    mon = _mon_of(g['title'])
    if mon and g.get('mnl2'):
        rows = []
        for e in g['mnl2']:
            if e.get('biomes'):
                rows.append({'b': e.get('bucket') or 'ultra-rare', 'l': e.get('lvl') or '?',
                             'bi': list(e['biomes']), 'k': e.get('key')})
        if rows:
            _spawnmap[mon] = rows
_nback = 0
for p in dex:
    if not p.get('sp'):
        rows = _spawnmap.get(_norm(p.get('n')))
        if rows:
            p['sp'] = rows
            _nback += 1
if _nback:
    print('dex: backfilled spawns for %d mons that showed none' % _nback)

_nreq = _nped = 0
for p in dex:
    mon = _norm(p.get('n'))
    if mon in _ped:
        p['pd'] = _ped[mon]
        _nped += 1
    if mon in _req:
        for s in p.get('sp', []):
            if s.get('k'):
                s['rq'] = _req[mon]
                _nreq += 1
print('dex enriched: %d spawn rows given a cost, %d mons given a 2nd route' % (_nreq, _nped))
for p in dex:
    for r in p.get('r', []):
        nums = [int(x) for x in re.findall(r'\d+', str(r.get('s') or ''))]
        mounts[r['t']].append((max(nums) if nums else -1, p['n'], r.get('s') or '?'))
mh = '<div class="subtabs">'
for i, g in enumerate(['Flight', 'Ground', 'Water']):
    mh += '<button class="%s" data-m="%s">%s (%d)</button>' % ('on' if i == 0 else '', g, g, len(mounts.get(g, [])))
if D3.get('seats_html'):
    mh += '<button data-m="Seats">Seats</button>'
mh += '</div>'
for i, g in enumerate(['Flight', 'Ground', 'Water']):
    rows = sorted(mounts.get(g, []), reverse=True)
    mh += '<div class="msec %s" id="m_%s"><div class="tw"><table><thead><tr><th>#</th><th>Pokémon</th><th>Riding speed</th></tr></thead><tbody>' % ('on' if i == 0 else '', g)
    for j, (hi, nm, sp) in enumerate(rows, 1):
        mh += '<tr><td class="muted">%d</td><td><b>%s</b></td><td>%s</td></tr>' % (j, esc(nm), esc(sp))
    mh += '</tbody></table></div></div>'
if D3.get('seats_html'):
    mh += '<div class="msec" id="m_Seats">%s</div>' % D3['seats_html']

# ---------------- self-host guide ----------------
# Purpose (owner's words): insurance for rehosting this manually, or by pointing an LLM
# at it. So: exact versions, the server/client split, and the order of operations.
import zipfile as _mz, glob as _mg, os as _mo

_srv = []
for _jp in sorted(_mg.glob(COBBLEMON_DIR + '/mods/*.jar')):
    _nm, _ver, _env = _mo.path.basename(_jp), '', 'both'
    try:
        _z = _mz.ZipFile(_jp)
        if 'fabric.mod.json' in _z.namelist():
            _d = json.loads(_z.read('fabric.mod.json').decode('utf-8-sig'))
            _nm = _d.get('name') or _nm
            _ver = _d.get('version', '')
            _env = {'*': 'both', 'client': 'client', 'server': 'server'}.get(
                _d.get('environment', '*'), 'both')
    except Exception:
        pass
    _srv.append((_nm, _ver, _env, _mo.path.basename(_jp)))

try:
    _cp = json.load(open('/tmp/wiki_clientpkg.json'))
except Exception:
    _cp = {'client_mods': [], 'resourcepacks': [], 'package': '', 'package_mb': 0}
_cset = set(_cp['client_mods'])
_sset = {f for _, _, _, f in _srv}

host = ''
host += ('<div class="card"><b>This section is the rehost instructions.</b> Everything '
         'below is read from the running server, so the versions are what is actually '
         'installed &mdash; not what a README once said. If you are rebuilding this '
         'server from nothing, or handing it to someone (or something) else to rebuild, '
         'this is the list.</div>')
_cv = (_cp.get('package_sha') or '')[:8]
_sv = (_cp.get('server_sha') or '')[:8]
host += ('<h3>Downloads</h3>'
         '<div class="tw"><table><thead><tr><th>Package</th><th>Size</th>'
         '<th>What it is</th></tr></thead><tbody>'
         '<tr><td><a href="/dl/cobblemon-client-package.zip?v=%s"><b>Client package</b></a>'
         '<div class="muted sm"><a href="/dl/cobblemon-client-package.zip.sha256">sha256</a>'
         ' &middot; <code>%s</code></div></td><td>%d&nbsp;MB</td>'
         '<td>What a player installs: <b>%d mods</b> and <b>%d resource packs</b>, with an '
         'installer that leaves your waypoints, map and settings alone. '
         '<b>Read the pack order below before you launch</b> &mdash; it also ships as '
         '<code>READ-ME-PACK-ORDER.txt</code> inside the zip.</td></tr>'
         % (_cv, _cv or 'n/a', _cp.get('package_mb', 0),
            len(_cp['client_mods']), len(_cp['resourcepacks'])))
if _cp.get('server_package'):
    host += ('<tr><td><a href="/dl/cobblemon-server-package.zip?v=%s"><b>Server package</b>'
             '</a><div class="muted sm">'
             '<a href="/dl/cobblemon-server-package.zip.sha256">sha256</a> &middot; '
             '<code>%s</code></div></td><td>%d&nbsp;MB</td>'
             '<td>The <b>%d server mods</b> and the tuned <code>config</code> folder. No '
             'world, no whitelist, no op list and no passwords &mdash; '
             '<code>server.properties</code> ships as an example with rcon off and the '
             'seed blank.</td></tr>'
             % (_sv, _sv or 'n/a', _cp.get('server_mb', 0), _cp.get('server_mods', 0)))
if _cp.get('update_package'):
    host += ('<tr><td><a href="/dl/%s?v=%s"><b>Update only</b></a>'
             '<div class="muted sm"><a href="/dl/%s.sha256">sha256</a> &middot; '
             '<code>%s</code></div></td><td>%d&nbsp;MB</td>'
             '<td><b>For players who already have the pack.</b> Just the <b>%d new mods</b> '
             'from the latest update. Drag the <code>mods</code> folder from it into '
             '<code>%%APPDATA%%\.minecraft</code> &mdash; no installer, nothing to enable, '
             'and nothing else is touched.</td></tr>'
             % (_cp['update_package'], (_cp.get('update_sha') or '')[:8],
                _cp['update_package'], (_cp.get('update_sha') or 'n/a')[:8],
                _cp.get('update_mb', 0), _cp.get('update_mods', 0)))
host += ('</tbody></table></div>'
         '<div class="card sm muted">Served as plain static files. The <code>?v=</code> on '
         'each link is the first eight characters of that package&rsquo;s sha256 &mdash; it '
         'changes when the contents change, so you are never handed a stale copy from a '
         'cache. Verify a download with <code>sha256sum cobblemon-client-package.zip</code>.'
         '</div>')

host += ('<h3>The base</h3><div class="tw"><table><tbody>'
         '<tr><td>Minecraft</td><td><b>1.21.1</b></td></tr>'
         '<tr><td>Loader</td><td><b>Fabric 0.19.3</b></td></tr>'
         '<tr><td>Java</td><td><b>21</b> (OpenJDK 21.0.11)</td></tr>'
         '<tr><td>Whitelist</td><td>on &mdash; max 5 players, online-mode on</td></tr>'
         '<tr><td>Distances</td><td>view 12, simulation 8</td></tr>'
         '</tbody></table></div>')

host += ('<h3>Order of operations</h3><ol class="tsteps">'
         '<li>Install <b>Java 21</b>. Nothing here runs on 17.</li>'
         '<li>Install the <b>Fabric server</b> for <b>Minecraft 1.21.1</b>, loader '
         '<b>0.19.3</b>. Mod versions are pinned to 1.21.1 &mdash; a different Minecraft '
         'version will not work.</li>'
         '<li>Drop all <b>%d</b> jars below into <code>mods/</code>. Versions matter: '
         'CobbleCuisine in particular must be the <b>alpha</b> build, because the stable '
         'one crashes on Cobblemon 1.7.</li>'
         '<li>Start once to generate configs, stop, then restore <code>config/</code> '
         '&mdash; especially <code>config/mythsandlegends/loot_tables_config.json</code>, '
         'which carries the tuned drop rates, and '
         '<code>config/cobblemon/spawning/best-spawner-config.json</code>.</li>'
         '<li>Restore <code>world/</code>, including <code>world/datapacks/</code> '
         '(ride-fix, strictlynifty-tweaks, twoseat-mounts) and '
         '<code>world/dimensions/</code>.</li>'
         '<li>Set the whitelist and start.</li>'
         '</ol>' % len(_srv))

host += ('<h3>Server mods &mdash; all %d</h3>'
         '<div class="sqrow"><input id="modq" type="search" '
         'placeholder="Filter mods"><span class="sqhint" id="modcnt"></span></div>'
         '<div class="tw"><table><thead><tr><th>Mod</th><th>Version</th>'
         '<th>Also needed on the client?</th></tr></thead><tbody>' % len(_srv))
for _nm, _ver, _env, _f in sorted(_srv, key=lambda r: r[0].lower()):
    if _env == 'server':
        _cl = '<span class="muted">server only</span>'
    elif _f in _cset:
        _cl = '<b>yes</b> &mdash; in the client package'
    else:
        _cl = '<span class="muted">no</span>'
    host += ('<tr data-s="%s"><td><b>%s</b><div class="muted sm"><code>%s</code></div></td>'
             '<td>%s</td><td>%s</td></tr>'
             % (esc((_nm + ' ' + _f).lower()), esc(_nm), esc(_f), esc(_ver or '-'), _cl))
host += '</tbody></table></div>'

_extra = sorted(_cset - _sset)
host += ('<h3>The client package</h3>'
         '<div class="card"><code>%s</code> &mdash; about %d MB. '
         '<b>%d mods</b> and <b>%d resource packs</b>. It is not a copy of the server '
         'list: it drops the server-only mods and adds a few the server does not need.'
         '</div>' % (esc(_cp.get('package', '')), _cp.get('package_mb', 0),
                     len(_cp['client_mods']), len(_cp['resourcepacks'])))
if _extra:
    host += ('<div class="tw"><table><thead><tr><th>Client-only addition</th>'
             '<th>Why</th></tr></thead><tbody>')
    WHY = {'xaerominimap': 'Minimap and waypoints. Purely client.',
           'linguachat': 'In-game chat translation. <b>Ship the patched jar</b> &mdash; the '
                         'stock one calls a Google endpoint that no longer answers.',
           'MoreCobblemonTweaks': 'Client-side quality-of-life tweaks.'}
    for _e in _extra:
        _k = next((k for k in WHY if k.lower() in _e.lower()), None)
        host += '<tr><td><code>%s</code></td><td>%s</td></tr>' % (esc(_e), WHY.get(_k, ''))
    host += '</tbody></table></div>'
host += ('<h3>Resource packs &mdash; the order is not optional</h3>'
         '<div class="card">These packs overwrite each other. <b>113 model files exist in '
         'more than one pack</b>, and all 113 differ, so whichever pack sits higher decides '
         'what you actually see. Get the order wrong and things break quietly: no error, '
         'the second seat just stops being drawn, or a mount throws your camera off its '
         'back.<br><br>'
         '<b>Higher in the list wins.</b> In game that is Options &rarr; Resource Packs, '
         'top of the <i>Selected</i> column. In <code>options.txt</code> it is the other '
         'way round &mdash; last in the line wins.</div>')

_PACKS = [
    ('cobblemon-2seats-resourcepack.zip', 'in the package', 1,
     'Draws the second rider on 329 mounts. <b>Must be top.</b> It shares 113 model files '
     'with CCC and has to win all of them, or the passenger seat vanishes on Charizard, '
     'Kyogre, Latios, Salamence, Aerodactyl and the legendary birds.'),
    ('CCC-seat-patch.zip', 'in the package', 2,
     'Adds a seat locator to <b>252 CCC forms that ship without one</b>. Without this you '
     'can mount Kubfu, Urshifu, Ogerpon, Galarian Zapdos, Hoopa, Meloetta or Calyrex and '
     'the Pok&eacute;mon runs off while your camera stays behind. Must sit above CCC.'),
    ('CCCwLegendSpawns_2.1.zip', 'in the package', 3,
     'The models for Raikou, Suicune, Heatran, Cresselia, Virizion, Yveltal and Zeraora, '
     'which Cobblemon 1.7.3 does not ship &mdash; without it those seven render as a green '
     'Substitute Doll. Goes at the bottom so the two packs above can correct it. '
     '<b>Client-side only</b>: it also carries spawn data, which does not affect this server.'),
]
host += '<div class="packstack">'
for _pn, _pw, _pi, _pd in _PACKS:
    host += ('<div class="prow"><div class="pnum">%d</div><div class="pbody">'
             '<code>%s</code> <span class="ptag">%s</span><div class="sm">%s</div>'
             '</div></div>' % (_pi, esc(_pn), esc(_pw), _pd))
host += ('<div class="prow pvan"><div class="pnum">&darr;</div><div class="pbody">'
         '<span class="sm">everything below is the built-in packs that ship with the mods, then '
         'vanilla. Leave them alone.</span></div></div>')
host += '</div>'

host += ('<div class="card"><b>All three are in the download.</b> The seat patch is '
         'generated from a copy of CCC, so it is version-locked to the '
         '<code>CCCwLegendSpawns_2.1</code> shipped beside it &mdash; the two travel '
         'together. If you ever swap CCC for a different build, regenerate the patch with '
         '<code>patch-ccc-seats.py</code> rather than keeping this one.</div>')

host += ('<div class="card"><b>Cosmetic packs are safe anywhere below the top entry.</b> '
         'The live client also runs <code>FreshAnimations_v1.10.4.zip</code> and the two '
         'emissive-ore packs. They touch different files and do not fight with the three '
         'above. If you add a pack that <i>does</i> re-model Pok&eacute;mon, it goes '
         '<i>below</i> the 2-seat pack.</div>')

host += ('<div class="card"><b>The exact line that works today.</b> This is lifted from a '
         'working client &mdash; remember it reads lowest-priority first, so it is the '
         'stack above written backwards. Paste it into <code>options.txt</code> with the '
         'game closed.<br><br><code class="wrapcode">resourcePacks:["vanilla","fabric",'
         '"cobbreeding:pasturefix","cobblemon:gyaradosjump","cobblemon:regionbiasforms",'
         '"continuity:glass_pane_culling_fix","continuity:default",'
         '"file/CCCwLegendSpawns_2.1.zip","file/FreshAnimations_v1.10.4.zip",'
         '"file/CCC-seat-patch.zip","file/Emissive-Cobblemon-Ores-1.7.zip",'
         '"file/emissive-ores-1-21.zip","file/cobblemon-2seats-resourcepack.zip"]'
         '</code></div>')

host += '<h3>What each mod contributes</h3>'

mods_html = '<div class="tw"><table><thead><tr><th>Mod</th><th>Items</th><th>Blocks</th><th>Recipes</th></tr></thead><tbody>'
for m in sorted(D2['mods'], key=lambda x: -(x['i'] + x['b'])):
    if m['i'] + m['b'] + m['r'] == 0:
        continue
    mods_html += '<tr><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td></tr>' % (esc(m['n']), m['i'] or '', m['b'] or '', m['r'] or '')
mods_html += '</tbody></table></div>'

TYPES = ['normal', 'fire', 'water', 'electric', 'grass', 'ice', 'fighting', 'poison', 'ground',
         'flying', 'psychic', 'bug', 'rock', 'ghost', 'dragon', 'dark', 'steel', 'fairy']
CHART = {
 'normal': {'rock': .5, 'ghost': 0, 'steel': .5},
 'fire': {'fire': .5, 'water': .5, 'grass': 2, 'ice': 2, 'bug': 2, 'rock': .5, 'dragon': .5, 'steel': 2},
 'water': {'fire': 2, 'water': .5, 'grass': .5, 'ground': 2, 'rock': 2, 'dragon': .5},
 'electric': {'water': 2, 'electric': .5, 'grass': .5, 'ground': 0, 'flying': 2, 'dragon': .5},
 'grass': {'fire': .5, 'water': 2, 'grass': .5, 'poison': .5, 'ground': 2, 'flying': .5, 'bug': .5, 'rock': 2, 'dragon': .5, 'steel': .5},
 'ice': {'fire': .5, 'water': .5, 'grass': 2, 'ice': .5, 'ground': 2, 'flying': 2, 'dragon': 2, 'steel': .5},
 'fighting': {'normal': 2, 'ice': 2, 'poison': .5, 'flying': .5, 'psychic': .5, 'bug': .5, 'rock': 2, 'ghost': 0, 'dark': 2, 'steel': 2, 'fairy': .5},
 'poison': {'grass': 2, 'poison': .5, 'ground': .5, 'rock': .5, 'ghost': .5, 'steel': 0, 'fairy': 2},
 'ground': {'fire': 2, 'electric': 2, 'grass': .5, 'poison': 2, 'flying': 0, 'bug': .5, 'rock': 2, 'steel': 2},
 'flying': {'electric': .5, 'grass': 2, 'fighting': 2, 'bug': 2, 'rock': .5, 'steel': .5},
 'psychic': {'fighting': 2, 'poison': 2, 'psychic': .5, 'dark': 0, 'steel': .5},
 'bug': {'fire': .5, 'grass': 2, 'fighting': .5, 'poison': .5, 'flying': .5, 'psychic': 2, 'ghost': .5, 'dark': 2, 'steel': .5, 'fairy': .5},
 'rock': {'fire': 2, 'ice': 2, 'fighting': .5, 'ground': .5, 'flying': 2, 'bug': 2, 'steel': .5},
 'ghost': {'normal': 0, 'psychic': 2, 'ghost': 2, 'dark': .5},
 'dragon': {'dragon': 2, 'steel': .5, 'fairy': 0},
 'dark': {'fighting': .5, 'psychic': 2, 'ghost': 2, 'dark': .5, 'fairy': .5},
 'steel': {'fire': .5, 'water': .5, 'electric': .5, 'ice': 2, 'rock': 2, 'steel': .5, 'fairy': 2},
 'fairy': {'fire': .5, 'fighting': 2, 'poison': .5, 'dragon': 2, 'dark': 2, 'steel': .5},
}
tc = '<div class="typelist">'
for a in TYPES:
    row = CHART.get(a, {})
    strong = sorted(k for k, v in row.items() if v == 2)
    weak = sorted(k for k, v in row.items() if v == 0.5)
    none = sorted(k for k, v in row.items() if v == 0)
    tc += '<div class="tcard"><h4>%s attacking</h4>' % a.title()
    if strong:
        tc += '<div class="tline"><span class="tl x2">2x</span> %s</div>' % ' '.join('<span class="pill">%s</span>' % s.title() for s in strong)
    if weak:
        tc += '<div class="tline"><span class="tl xh">&frac12;</span> %s</div>' % ' '.join('<span class="pill">%s</span>' % s.title() for s in weak)
    if none:
        tc += '<div class="tline"><span class="tl x0">0</span> %s</div>' % ' '.join('<span class="pill">%s</span>' % s.title() for s in none)
    tc += '<div class="muted sm">Everything else: normal damage</div></div>'
tc += '</div>'

NOTES = D3.get('notes') or {}
notes_html = ''
for k, v in NOTES.items():
    v = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', v)
    notes_html += '<div class="card good">%s</div>' % v

# ---- fill thumbnail gaps from the jars --------------------------------------------
# The upstream TEX harvest only took the flat assets/<ns>/textures/item/*.png level, but
# Cobblemon nests them (item/type_gem/dragon_gem.png, item/evolution/ice_stone.png), so
# a quarter of the tutorial thumbnails silently fell back to text abbreviations.
# Harvest exactly the ones actually referenced and still missing.
import base64 as _b64, glob as _glob, zipfile as _zip

_need = set()
for _p in dex:
    _t = _p.get('tut')
    if not _t:
        continue
    _stack = [_t.get('key')] + list(_t.get('ki') or []) + list(_t.get('it') or [])
    while _stack:
        _n = _stack.pop()
        if not isinstance(_n, dict):
            continue
        if _n.get('b'):
            _need.add(_n['b'])
        _r = _n.get('r') or {}
        for _g in (_r.get('ings') or []):
            if _g.get('b'):
                _need.add(_g['b'])
            if _g.get('sub'):
                _stack.append(_g['sub'])
        for _row in (_r.get('g') or []):
            for _c in _row:
                if _c:
                    _need.add(_c)
# The items page lists every item in the pack, so it needs every icon - not just the
# ones a dex tutorial happens to reference. Without this, 1,698 of 2,609 rows fall back
# to a text abbreviation.
for _row in D2['items']:
    if _row.get('i'):
        _need.add(_row['i'])

# ---------------- Cobblemon Cards ----------------
# Every number here was read out of the mod's own bytecode and the live server config,
# not from its store page. The two that matter most and are documented nowhere: the
# Grading Station needs a Data Monitor ON TOP of it, and booster packs only ever
# generate in VANILLA chests - a modded structure's chest can never contain one.
_CD_CFG = {}
try:
    _CD_CFG = json.load(open(COBBLEMON_DIR + '/config/cobblemon-cards.json'))
except Exception:
    pass
_cd_dust = int(_CD_CFG.get('gradingStationDustCost', 5))
_cd_chest = float(_CD_CFG.get('boosterChestSpawnChance', 2.0))
_cd_drop = float(_CD_CFG.get('cardDropChance', 1.0))
_cd_god = float(_CD_CFG.get('godPackTicketChance', 1.0))
_cd_grtime = int(_CD_CFG.get('gradingStationProcessTime', 100))
_cd_rctime = int(_CD_CFG.get('recyclerProcessTime', 40))
_cd_statmul = float(_CD_CFG.get('globalStatMultiplier', 10.0))
import math as _cd_math
_cd_p = max(_cd_chest, 0.0001) / 100.0
_cd_per = int(round(1.0 / _cd_p))
_cd_half = int(_cd_math.ceil(_cd_math.log(0.5) / _cd_math.log(1.0 - _cd_p)))
_cd_ninety = int(_cd_math.ceil(_cd_math.log(0.1) / _cd_math.log(1.0 - _cd_p)))


def _cd_recipe(nsid):
    """Grid + ingredient legend for one Cards recipe, straight from the index."""
    rows = (_RX.get('recipes') or {}).get(nsid) or []
    if not rows:
        return ''
    r = rows[0]
    out = ''
    if r.get('grid'):
        cells = ''
        for row in r['grid']:
            for c in row:
                b = _cell_item(c)[0] if c else None
                if b:
                    _need.add(b)
                cells += '<div class="cell">%s</div>' % (ic(b) if b else '')
        out += '<div class="craft"><div class="grid3">%s</div></div>' % cells
    seen, chips = set(), ''
    for ing in (r.get('ings') or []):
        b, tip = _cell_item(ing['i'])
        b = b or str(ing['i']).split(':')[-1]
        if b in seen:
            continue
        seen.add(b)
        _need.add(b)
        n = ing.get('n') or 1
        chips += ('<span class="ting"><span class="ic icsm" data-i="%s"></span>%s%s</span> '
                  % (esc(b), esc(nice(str(ing['i']).split(':')[-1])),
                     (' &times;%d' % n) if n > 1 else ''))
    if r.get('kind') and r['kind'] != 'shaped':
        out += '<div class="tkind">%s</div> ' % esc(str(r['kind']).replace('_', ' '))
    out += '<div class="tcraft">%s</div>' % chips
    return out


def _cd_machine(nsid, title, blurb, note=''):
    b = nsid.split(':')[-1]
    _need.add(b)
    return ('<div class="scard"><b><span class="ic big" data-i="%s"></span>%s</b>'
            '%s<div class="sm" style="margin-top:6px">%s</div>%s</div>'
            % (esc(b), esc(title), _cd_recipe(nsid), blurb,
               ('<div class="card warn sm" style="margin:8px 0 0">%s</div>' % note) if note else ''))


_cd = []
_cd.append('<div class="card good"><b>The loop:</b> open a <b>Booster Pack</b> or beat a '
           'Pok&eacute;mon for a card &rarr; feed spares to a <b>Card Recycler</b> for '
           '<b>Cobblecard Dust</b> &rarr; spend dust on a <b>Grading Station</b> to raise a '
           'card&rsquo;s grade, or on a <b>Structure Disk</b> to build a card of a species you '
           'choose. Cards kept in a <b>binder you are wearing</b> give you real stat bonuses.</div>')

_cd.append('<h2>Where cards and packs actually come from</h2>')
_cd.append('<div class="card bad"><b>Booster packs only generate in vanilla Minecraft chests.</b> '
           'The mod checks the loot table&rsquo;s namespace is exactly <code>minecraft</code> before '
           'it injects anything, so a chest inside a <b>modded</b> structure &mdash; an Observatory, '
           'a Legendary Monument &mdash; can <b>never</b> contain one, no matter how many you open. '
           '<b>Village chests are excluded too.</b> That leaves <b>40</b> vanilla chest tables.</div>')
_cd.append('<div class="tw"><table><thead><tr><th>Source</th><th>Rate on this server</th>'
           '<th>What you get</th></tr></thead><tbody>'
           '<tr><td>Vanilla chest loot</td><td><b>%g%%</b> per chest</td>'
           '<td>1 Booster Pack. About <b>1 per %d chests</b>; %d chests for an even chance, '
           '%d for a 90%%%% chance.</td></tr>'
           '<tr><td>Defeating or catching a Pok&eacute;mon</td><td><b>%g%%</b> base, plus your binder bonus</td>'
           '<td>A single card of that species. Only dex <b>1&ndash;1025</b> &mdash; baby legendaries '
           'and addon species are skipped.</td></tr>'
           '<tr><td>Wandering trader</td><td>up to <b>7</b> offers, <b>one use each</b></td>'
           '<td>A random card, priced in dust. Never a pack.</td></tr>'
           '<tr><td>Instant Dex + Structure Disk</td><td>your choice</td>'
           '<td>A card of the exact species you scan.</td></tr>'
           '</tbody></table></div>'
           % (_cd_chest, _cd_per, _cd_half, _cd_ninety, _cd_drop))
_cd.append('<h3>Best places to look</h3>')
_cd.append('<div class="card"><b>Trial chambers</b> are far and away the best &mdash; they alone have '
           '<b>13</b> of the 40 eligible tables (supply, corridor, intersection, the barrels, and seven '
           'reward variants), and a single chamber holds dozens of containers. After that: '
           '<b>abandoned mineshafts</b> (endless minecart chests), <b>ancient cities</b>, '
           '<b>strongholds</b>, <b>woodland mansions</b>, <b>bastions</b> and <b>shipwrecks</b>. '
           'Buried treasure counts but is one chest per map, so it is the slowest possible route. '
           'The jungle temple <b>dispenser</b> counts as well.</div>')
_cd.append('<h3>What the wandering trader charges</h3>')
_cd.append('<div class="tw"><table><thead><tr><th>Card rarity</th><th>Chance the offer is that rarity</th>'
           '<th>Price</th></tr></thead><tbody>'
           '<tr><td>Common</td><td>50%</td><td>10&ndash;15 dust</td></tr>'
           '<tr><td>Uncommon</td><td>30%</td><td>30&ndash;40 dust</td></tr>'
           '<tr><td>Rare</td><td>15%</td><td>1&ndash;2 pouches (9&ndash;18 dust)</td></tr>'
           '<tr><td>Epic</td><td>4%</td><td>4&ndash;5 pouches (36&ndash;45 dust)</td></tr>'
           '<tr><td>Legendary</td><td>1%</td><td>1 sack (81 dust)</td></tr>'
           '</tbody></table></div>')

_cd.append('<h2>Booster packs</h2>')
_cd.append('<div class="card">Right-click to open. You get a five-card animation &mdash; click each '
           'card, then press <b>ESC</b> to collect them.</div>')
_cd.append('<div class="tw"><table><thead><tr><th>Slot</th><th>What rolls there</th></tr></thead><tbody>'
           '<tr><td>Cards 1&ndash;3</td><td>Common tier</td></tr>'
           '<tr><td>Card 4</td><td>Uncommon tier</td></tr>'
           '<tr><td>Card 5</td><td><b>Rare or better</b> &mdash; this is the one that can be '
           'Epic, Legendary or Mythic</td></tr></tbody></table></div>')
_cd.append('<div class="card good"><b>God Packs.</b> Every pack has a <b>%g%%</b> chance to open as a '
           'God Pack instead &mdash; <b>all five cards</b> come from the elite pool. A '
           '<b>God Pack Ticket</b> guarantees it: use the ticket, and your very next pack is a God '
           'Pack. The ticket is consumed.</div>' % _cd_god)
_cd.append('<div class="card"><b>28 kinds of pack.</b> The plain Booster Pack rolls any species. '
           'There are also <b>18 type packs</b> (Fire, Water, Dragon&hellip;) and <b>9 generation '
           'packs</b> (Gen 1&ndash;9), each restricted to that type or generation. Only the plain one '
           'generates in chests &mdash; the themed ones come from the creative menu or an admin.</div>')

_cd.append('<h2>Cobblecard Dust &mdash; the currency</h2>')
_cd.append('<div class="card">Dust is what everything costs. You make it by <b>recycling cards you do '
           'not want</b>. Yield depends on the card, and the bonuses stack:</div>')
_cd.append('<div class="tw"><table><thead><tr><th>Card rarity</th><th>Base dust</th></tr></thead><tbody>'
           '<tr><td>Common</td><td>1</td></tr>'
           '<tr><td>Uncommon</td><td>2</td></tr>'
           '<tr><td>Rare</td><td>3</td></tr>'
           '<tr><td>Epic</td><td>5</td></tr>'
           '<tr><td>Legendary</td><td>10</td></tr>'
           '<tr><td>Mythic</td><td>15</td></tr>'
           '</tbody></table></div>')
_cd.append('<div class="card"><b>Then:</b> <b>&times;2 if the card is shiny</b>, <b>+1</b> if it has a '
           'background, <b>+1</b> if it has a holo effect. So a shiny Mythic with both is '
           '<b>32 dust</b> from one card. <b>Cosmetic cards give nothing.</b> Recycling takes '
           '%g seconds per card.</div>' % (_cd_rctime / 20.0))
_cd.append('<h3>Storing it</h3>')
_cd.append('<div class="sgrid">'
           + _cd_machine('cobblemon-cards:card_dust_pouch', 'Card Dust Pouch',
                         '9 dust in, and 9 back out again. Purely for stacking.')
           + _cd_machine('cobblemon-cards:card_dust_sack', 'Card Dust Sack',
                         '9 pouches &mdash; <b>81 dust</b>. Also a block, and what a '
                         'wandering trader charges for a Legendary card.')
           + '</div>')

_cd.append('<h2>The machines</h2>')
_cd.append('<div class="sgrid">'
           + _cd_machine('cobblemon-cards:card_recycler', 'Card Recycler',
                         'Turns unwanted cards into Cobblecard Dust at the rates above. It has input '
                         'and output slots, so hoppers can feed and drain it.')
           + _cd_machine('cobblemon-cards:grading_station', 'Grading Station',
                         'Grades an ungraded card. Costs <b>%d Cobblecard Dust from your inventory</b> '
                         'and takes <b>%g seconds</b>.' % (_cd_dust, _cd_grtime / 20.0),
                         '<b>It needs a Data Monitor directly on top of it.</b> The Data Monitor is a '
                         '<b>Cobblemon</b> block. Do not confuse the Grading Station with Cobblemon&rsquo;s '
                         '<b>Display Case</b> &mdash; they look alike, and a Display Case with a monitor '
                         'on it does nothing at all. If right-clicking gives you <i>no message</i>, the '
                         'base block is the wrong one.')
           + _cd_machine('cobblemon-cards:holo_projector', 'Holo Projector',
                         'Place a card on top and it projects a 3D hologram of it. Right-click to cycle '
                         '<b>6 display modes</b>: continuous spin, face player, dynamic, fixed, flat, '
                         'and simple bobbing.')
           + _cd_machine('cobblemon-cards:advanced_holo_projector', 'Advanced Holo Projector',
                         'The same idea for <b>up to 27 cards</b> in a sequence, and it can show each '
                         'card&rsquo;s name.')
           + _cd_machine('cobblemon-cards:card_cabinet', 'Card Cabinet',
                         'The binder interface as a block, holding <b>12,000 cards</b> '
                         '(1,000 pages of 12). This is the end-game storage.')
           + '</div>')

_cd.append('<h2>Grading</h2>')
_cd.append('<div class="card"><ol class="tsteps">'
           '<li>Place a <b>Grading Station</b> with a <b>Data Monitor</b> on the block above it.</li>'
           '<li>Carry at least <b>%d Cobblecard Dust</b>. It is taken from your inventory, not a slot.</li>'
           '<li>Right-click the station holding an <b>ungraded</b> card. An already-graded card is refused.</li>'
           '<li>Wait <b>%g seconds</b>. A <b>Grading Station Bypass</b> item finishes it instantly.</li>'
           '</ol></div>' % (_cd_dust, _cd_grtime / 20.0))
_cd.append('<div class="card warn"><b>The grade is pure luck.</b> It rolls <b>1 to 10, evenly</b>. '
           'Nothing about the card &mdash; rarity, shiny, holo &mdash; shifts the odds. What the grade '
           'does is raise the card&rsquo;s stat: <b>+3&#37; per grade</b>, so a Grade 10 card carries '
           '<b>+30&#37;</b> over its ungraded value. Grade 10 is a <b>1 in 10</b> roll, and it is the '
           '<i>Master Evaluator</i> advancement.</div>')

_cd.append('<h2>Binders, and why they are not just storage</h2>')
# The Master Album is NOT in data/accessories/tags/item/belt.json - only the five metal
# binders are. It is registered as an Accessory but has no slot that will take it, so it
# cannot be worn. That is the whole reason the expensive chain exists, and it is the one
# thing that makes 8 glass + a leather binder for 12,000 cards not absurd.
_cd.append('<div class="card good">Cards only pay you back when the binder holding them is '
           '<b>on your belt</b> (open your inventory, put it in the accessory slot) <b>or held in '
           'your main hand</b>. Then every card inside applies its stat to you, and every equipped '
           'accessory adds together.</div>')
_cd.append('<div class="card bad"><b>The Master Album cannot be worn.</b> It is not in the belt slot tag &mdash; only the five metal binders are. So it is bulk storage and the Card Cabinet '
           'ingredient, nothing more. That is the catch that makes 8 glass and a Leather Binder a '
           'fair price for 12,000 slots, and it is why the expensive chain still has a point: '
           '<b>a Netherite Binder holds 120 cards that actually buff you.</b> You can hold a Master '
           'Album in your main hand for its bonus, but then you are holding a book instead of a '
           'sword.</div>')
_cd.append('<div class="tw"><table><thead><tr><th>Binder</th><th>Pages</th><th>Cards</th>'
           '<th>Wearable?</th><th>How you make it</th></tr></thead><tbody>'
           '<tr><td>Leather Binder</td><td>1</td><td>12</td><td>yes</td>'
           '<td>Leather, string and a book</td></tr>'
           '<tr><td>Iron Binder</td><td>2</td><td>24</td><td>yes</td>'
           '<td>Leather Binder + 8 iron</td></tr>'
           '<tr><td>Gold Binder</td><td>3</td><td>36</td><td>yes</td>'
           '<td>Iron Binder + 8 gold</td></tr>'
           '<tr><td>Diamond Binder</td><td>6</td><td>72</td><td>yes</td>'
           '<td>Gold Binder + 8 diamond</td></tr>'
           '<tr><td>Netherite Binder</td><td>10</td><td><b>120</b></td><td><b>yes</b></td>'
           '<td>Diamond Binder at a <b>smithing table</b> with a netherite upgrade template</td></tr>'
           '<tr><td><b>Master Album</b></td><td>1,000</td><td><b>12,000</b></td>'
           '<td><b>no</b></td><td>Leather Binder surrounded by 8 glass</td></tr>'
           '</tbody></table></div>')
_cd.append('<div class="card"><b>Upgrading keeps your cards.</b> Crafting one binder into the '
           'next carries the contents across, trimmed to whatever the new tier holds. So work up '
           'the chain with the same binder rather than starting again.</div>')
_cd.append('<div class="sgrid">'
           + _cd_machine('cobblemon-cards:leather_binder', 'Leather Binder', 'Where everyone starts.')
           + _cd_machine('cobblemon-cards:iron_binder', 'Iron Binder',
                         'Each tier is an upgrade of the one below it, so nothing is wasted.')
           + _cd_machine('cobblemon-cards:gold_binder', 'Gold Binder', '')
           + _cd_machine('cobblemon-cards:diamond_binder', 'Diamond Binder', '')
           + _cd_machine('cobblemon-cards:master_album', 'Master Album',
                         '12,000 slots for almost nothing &mdash; but <b>it cannot go on your belt</b>, '
                         'so the cards in it give you no bonus unless you hold it. Storage and the '
                         'Card Cabinet ingredient.')
           + '</div>')
_cd.append('<div class="card"><b>Netherite Binder</b> is a smithing recipe, not a crafting grid: '
           'Netherite Upgrade Smithing Template + <b>Diamond Binder</b> + Netherite Ingot.</div>')
_cd.append('<div class="card"><b>Sorting.</b> The binder screen sorts by <b>Pok&eacute;mon</b>, '
           '<b>rarity</b> or <b>grade</b>, and has a search box. There is a keybind to open your '
           'binder without going through the inventory, and another for the Card Showcase.</div>')

_cd.append('<h2>What card stats do</h2>')
_cd.append('<div class="card">Every non-cosmetic card carries <b>one</b> stat and a value. This server '
           'runs a <b>global stat multiplier of %g&times;</b>, so the bonuses are substantial. '
           'The 25 possible stats:</div>' % _cd_statmul)
_cd.append('<div class="card sm"><b>Character:</b> Max Health, Armor, Attack Damage, Attack Speed, '
           'Movement Speed, Mining Speed, Luck.<br><b>Collecting:</b> Card Drop Chance &mdash; this is '
           'the one that raises how often Pok&eacute;mon drop cards, and it compounds.<br>'
           '<b>Spawn rates:</b> one per type &mdash; Bug, Dark, Dragon, Electric, Fairy, Fighting, Fire, '
           'Flying, Ghost, Grass, Ground, Ice, Normal, Poison, Psychic, Rock, Steel and Water Spawn. '
           'A binder full of Fire cards makes Fire types spawn around you more often.</div>')

_cd.append('<h2>Making the card you actually want</h2>')
_cd.append('<div class="card">Chasing one species through random packs is hopeless. The '
           '<b>Card Structure Disk</b> and <b>Instant Dex</b> exist for exactly this.</div>')
_cd.append('<div class="sgrid">'
           + _cd_machine('cobblemon-cards:card_structure_disk', 'Card Structure Disk',
                         'A blank you charge with dust. <b>Right-click to load dust, '
                         'shift + right-click to load a whole stack.</b> It holds up to '
                         '<b>1,000 dust</b>, and how much you put in decides the card&rsquo;s rarity.')
           + _cd_machine('cobblemon-cards:instant_dex', 'Instant Dex',
                         'The scanner. Requires a Structure Disk in your inventory. Point it at a '
                         '<b>wild</b> Pok&eacute;mon &mdash; it will not scan yours or a trainer&rsquo;s. '
                         '<b>5 scans of the same species</b> completes the disk and produces the card. '
                         'Scan a shiny and the shiny data is recorded too.')
           + _cd_machine('cobblemon-cards:card_dex', 'Card Dex',
                         'The checklist. Shows every species as Discovered or Undiscovered, split into '
                         'National Dex, Regionals and Megas. Shift-hover an entry to inspect the card.')
           + '</div>')
_cd.append('<div class="tw"><table><thead><tr><th>Dust loaded into the disk</th>'
           '<th>Rarity you can get</th></tr></thead><tbody>'
           '<tr><td>under 50</td><td>Common</td></tr>'
           '<tr><td>50 or more</td><td>Uncommon</td></tr>'
           '<tr><td>200 or more</td><td>Rare</td></tr>'
           '<tr><td>500 or more</td><td>Epic</td></tr>'
           '<tr><td>1,000 (full)</td><td><b>Legendary</b></td></tr>'
           '</tbody></table></div>')
_cd.append('<div class="card warn">The disk locks to the <b>first species you scan</b> &mdash; scanning '
           'a different one is refused. Load the dust <b>before</b> you finish the fifth scan.</div>')

_cd.append('<h2>Rarity, shininess and holo</h2>')
_cd.append('<div class="card">Six rarities: <b>Common, Uncommon, Rare, Epic, Legendary, Mythic</b>. '
           'A card&rsquo;s rarity is rolled against the species&rsquo; own tier, so a Legendary '
           'Pok&eacute;mon can roll a Mythic card while a Pidgey never will &mdash; the weighting table '
           'gives Common species a flat <b>zero</b> chance at Rare or above.</div>')
_cd.append('<div class="card">There are <b>48 holo effects</b>, from plain Glint and Foil Stars up to '
           'Cosmic Constellation, Distortion Rift, Paldean Terastal and Mega Vortex. Holo and a '
           'background each add a point of recycling value, and shiny cards are worth double.</div>')

_cd.append('<h2>Advancements</h2>')
_cd.append('<div class="card sm">'
           '<b>Booster Addict</b> &mdash; open 100 booster packs &middot; '
           '<b>First Shiny!</b> &mdash; your first shiny card &middot; '
           '<b>Master Evaluator</b> &mdash; grade a card to 10 &middot; '
           '<b>Kanto Starter Set</b> &mdash; Bulbasaur, Charmander and Squirtle &middot; '
           '<b>Complete Collection!</b> &mdash; 150 unique species &middot; '
           '<b>Ultimate Collection</b> &mdash; fill a Card Cabinet with all 12,000 &middot; '
           '<b>National Card Dex</b> &mdash; every base species &middot; '
           '<b>Regional Expert</b> &mdash; every Alolan, Galarian and Hisuian form &middot; '
           '<b>Mega Evolution Master</b> &mdash; every Mega &middot; and a '
           '<b>Generation Master</b> for each of the nine generations.</div>')

_cd.append('<h2>This server&rsquo;s settings</h2>')
_cd.append('<div class="tw"><table><tbody>'
           '<tr><th>Booster in a vanilla chest</th><td><b>%g&#37;</b> per chest</td></tr>'
           '<tr><th>Card from a Pok&eacute;mon</th><td><b>%g&#37;</b> before binder bonuses</td></tr>'
           '<tr><th>God Pack</th><td><b>%g&#37;</b> of packs opened</td></tr>'
           '<tr><th>Grading cost</th><td><b>%d</b> Cobblecard Dust</td></tr>'
           '<tr><th>Grading time</th><td>%g seconds</td></tr>'
           '<tr><th>Recycling time</th><td>%g seconds per card</td></tr>'
           '<tr><th>Global stat multiplier</th><td><b>%g&times;</b></td></tr>'
           '<tr><th>Fakemon cards</th><td>off</td></tr>'
           '</tbody></table></div>'
           % (_cd_chest, _cd_drop, _cd_god, _cd_dust,
              _cd_grtime / 20.0, _cd_rctime / 20.0, _cd_statmul))
_cd.append('<div class="card muted sm">Read out of <code>cobblemon-cards-fabric-1.0.4.jar</code> and '
           '<code>config/cobblemon-cards.json</code> on the server. If a video or another wiki '
           'disagrees with this page, it is describing a different setup.</div>')

cards_html = ''.join(_cd)

# ---------------- what the card stats actually do ----------------
# The card tooltip shows a percentage for every stat, which hides the single most
# important fact about them: FOUR stats are applied as a FLAT attribute value and the
# rest as a percentage multiplier, so identical-looking numbers differ by orders of
# magnitude. Read out of FabricBinderItem.getDynamicModifiers rather than guessed:
#
#     value = summed stat_value * globalStatMultiplier      (10.0 on this server)
#     MAX_HEALTH / ARMOR / LUCK / MINING_SPEED -> ADD_VALUE (flat)
#     everything else                          -> value/100, ADD_MULTIPLIED_BASE
#
# Values SUM across every card in the worn binder (Map.merge), and nothing applies at
# all unless the binder is actually equipped.
_CARD_STAT_MULT = 10.0
try:
    _CARD_STAT_MULT = float(_CD_CFG.get('globalStatMultiplier', 10.0))
except Exception:
    pass

_STAT_ROWS = [
    ('Luck', 'flat',
     'Adds raw <b>luck</b>, the vanilla attribute. Worth more than anything else on this '
     'server: <b>RCT trainer drops</b> weight their uncommon/rare/legendary entries with '
     '<code>quality</code> up to <b>+350</b>, so even one point of luck moves the '
     'legendary tier from <b>0.37%</b> to <b>5.9%</b> &mdash; about <b>16x</b>. Also '
     'improves fishing. It does <b>not</b> affect trial chambers, mob drops or ore.'),
    ('Max Health', 'flat',
     'Adds hearts directly. A 0.07 card is <b>+0.7 health</b>, not +7%.'),
    ('Armor', 'flat',
     'Adds armour points directly, on top of what you are wearing.'),
    ('Mining Speed', 'flat',
     'Adds to <code>player.mining_efficiency</code> directly &mdash; not <code>block_break_speed</code>, which stays at exactly 1.0.'),
    ('Attack Damage', 'percent',
     'A percentage multiplier, so the printed number is divided by 100 before it is '
     'applied &mdash; a 0.05 card is <b>+0.05%</b>. Effectively negligible &mdash; confirmed in game.'),
    ('Attack Speed', 'percent',
     'Shortens the swing cooldown, but as a percentage: a 0.05 card is <b>+0.05%</b>. '
     'You would need a binder full of them to notice. Derived from the code; not yet measured in game.'),
    ('Movement Speed', 'percent',
     'Same percentage treatment, same negligible size.'),
    ('&lt;type&gt; Spawn', 'spawn',
     'Not a vanilla attribute at all &mdash; handled by the mod, and the only stat where '
     'the printed percentage is the real effect. Biases wild spawns toward that type.'),
    ('Card Drop Chance', 'spawn',
     'Mod-handled. Improves how often cards drop.'),
]

_RECYCLE_ROWS = [('Common', 1), ('Uncommon', 2), ('Rare', 3),
                 ('Epic', 5), ('Legendary', 10), ('Mythic', 15)]

_cs = ['<h3 id="cardstats">What the stats actually do</h3>']
_cs.append('<div class="tip">The card shows a percentage for every stat, but <b>four of '
           'them are applied flat and the rest as a percentage</b>. That makes two cards '
           'printing the same number differ enormously. Values <b>add up across every '
           'card in the binder</b>, and none of them do anything unless the binder is '
           '<b>equipped</b>.</div>')
_cs.append('<div class="tw"><table><thead><tr><th>Stat</th><th>Applied as</th>'
           '<th>What it does</th></tr></thead><tbody>')
for _nm, _kind, _desc in _STAT_ROWS:
    _lab = {'flat': '<span class="pill hot">FLAT</span>',
            'percent': '<span class="pill">percent</span>',
            'spawn': '<span class="pill">mod-handled</span>'}[_kind]
    _cs.append('<tr><td><b>%s</b></td><td>%s</td><td>%s</td></tr>' % (_nm, _lab, _desc))
_cs.append('</tbody></table></div>')
_cs.append('<div class="tip"><b>The number printed on the card is the effect.</b> Measured in game with a binder equipped:<br>&#9642; <b>Flat stats</b> &mdash; the printed number is added directly. A card reading <b>+0.66</b> Luck gave exactly <b>0.65636</b> luck; <b>+0.82</b> Max Health gave <b>+0.82047</b>; <b>+0.09</b> Mining Speed gave <b>0.09002</b> mining efficiency.<br>&#9642; <b>Percentage stats</b> &mdash; the printed number is a <b>percent of your current total</b>. A test card printing <b>+10.00</b> Attack Speed took a 1.6 weapon to exactly <b>1.76</b>. So a normal <b>+0.05</b> card is <b>+0.05%</b> &mdash; nothing.<br>&#9642; <b>Spawn stats</b> are ten times stronger per printed point: a <b>+1.50</b> Normal Spawn card reads as <b>+15%</b> in game.</div>')

_cs.append('<h3 id="carddust">Recycler &mdash; card dust values</h3>')
_cs.append('<div class="tw"><table><thead><tr><th>Rarity</th><th>Dust</th></tr></thead><tbody>')
for _r, _v in _RECYCLE_ROWS:
    _cs.append('<tr><td>%s</td><td><b>%d</b></td></tr>' % (_r, _v))
_cs.append('</tbody></table></div>')
_cs.append('<div class="sm">Then: <b>shiny doubles it</b>, a background adds <b>+1</b>, '
           'and a holo effect adds <b>+1</b>. A shiny holo rare with a background is '
           '<b>8</b> dust; a plain common is <b>1</b>. Cosmetic cards give <b>nothing</b>.'
           '</div>')
_cs.append('<div class="tip"><b>What to recycle.</b> Spawn-type cards below about 0.02 '
           'are worth roughly nothing &mdash; a 0.005 card is half a percent. The '
           'percentage stats (attack damage, attack speed, movement speed) are weak at '
           'every size. <b>Keep every Luck card</b>, then Max Health, Armor and Mining '
           'Speed, which are the only ones applied flat.</div>')
cards_html = cards_html + ''.join(_cs)
print('cards: stat reference and dust table added')

# ---------------- the Instant-Dex, and the trap in it ----------------
# The owner built one, calibrated a disk to Vivillon, and assumed dust was spent per scan -
# so they scanned with an empty disk and thought they had locked in a Common. They had not,
# but nothing in game says so. Everything below is read out of InstantDexItem,
# CardStructureDiskItem and DiskData in the mod's nested common-1.0.0.jar.
_ix = []
_ix.append('<h3 id="instantdex">The Instant-Dex &mdash; a card of any Pok&eacute;mon you '
           'choose</h3>')

_ix.append('<div class="card good"><b>This is the only way to beat the rarity table.</b> '
           'Every card from a booster pack is capped by the Pok&eacute;mon&rsquo;s own tier '
           '&mdash; a <b>common</b> species rolls Common at weight 200 and Uncommon at 10, '
           'and <b>Rare, Epic and Legendary are weight <code>0.0</code></b>. It cannot '
           'happen. The rarity config says so outright: <i>&ldquo;Instant Dex and '
           'administrator-created cards intentionally bypass these restrictions.&rdquo;</i> '
           'So a <b>Legendary card of an ordinary Pok&eacute;mon</b> exists only through '
           'this route.</div>')

_ix.append('<div class="tw"><table><thead><tr><th>Piece</th><th>Costs</th><th>Used up?</th>'
           '</tr></thead><tbody>'
           '<tr><td><b>Instant-Dex</b></td>'
           '<td>1 <b>Card Dust Sack</b> = <b>81 dust</b>, plus redstone, iron, a chain, an '
           'ink sac and planks</td>'
           '<td><b>No</b> &mdash; build it once, keep it forever</td></tr>'
           '<tr><td><b>Card Structure Disk</b></td>'
           '<td>1 <b>Card Dust Pouch</b> = <b>9 dust</b>, plus iron, gold and redstone</td>'
           '<td><b>Yes</b> &mdash; consumed when the 5th scan completes</td></tr>'
           '</tbody></table></div>'
           '<div class="sm muted">1 pouch = 9 dust &middot; 1 sack = 9 pouches = 81 dust. '
           'So the whole setup is about <b>90 dust</b> and only the 9 recurs.</div>')

_ix.append('<div class="card bad"><b>Scanning does not cost dust. The dust sets the '
           'card&rsquo;s RARITY, and it is only read at the moment the 5th scan lands.</b>'
           '<br><br>'
           'Scans 1&ndash;4 copy the disk&rsquo;s dust value forward untouched; the '
           'completion branch passes it straight into <code>generateCard</code>. '
           '<b>So you can scan all five with an empty disk and load the dust just before '
           'the last one.</b> Loading early wastes nothing either &mdash; it is simply not '
           'spent until the end.</div>')

_ix.append('<div class="tw"><table><thead><tr><th>Dust on the disk</th><th>Card rarity</th>'
           '</tr></thead><tbody>'
           '<tr><td>0 &ndash; 49</td><td>Common</td></tr>'
           '<tr><td>50 &ndash; 199</td><td>Uncommon</td></tr>'
           '<tr><td>200 &ndash; 499</td><td>Rare</td></tr>'
           '<tr><td>500 &ndash; 999</td><td>Epic</td></tr>'
           '<tr><td><b>1000</b> <span class="muted">(the cap &mdash; the disk then reports '
           '&ldquo;full&rdquo;)</span></td><td><b>Legendary</b></td></tr>'
           '</tbody></table></div>'
           '<div class="sm muted">Right-click the disk to load. It accepts <b>dust (1)</b>, '
           '<b>pouches (9)</b> and <b>sacks (81)</b>, taking the largest that still fits, '
           'so you can top up from whatever you are carrying. The tooltip shows '
           '<b>Potential Rarity</b> and a <b>[&#9632;&#9632;&#9633;&#9633;&#9633;] /5</b> '
           'scan bar.</div>')

_ix.append('<h3>Using it without wasting a disk</h3>')
_ix.append('<div class="card"><b>A fresh disk is blank.</b> It has no target until you scan '
           'something, and <b>that first scan calibrates it permanently</b> &mdash; after '
           'that anything else gives <i>&ldquo;The disk is calibrated for: X&rdquo;</i>. '
           'Pick your species before the first click, not after.</div>')
_ix.append('<div class="card warn"><b>Three rules that will otherwise cost you scans:</b>'
           '<br>'
           '&#9642; <b>Wild only.</b> The check is <code>getOwnerUUID() != null</code>, so '
           'anything owned by <b>anybody</b> is refused &mdash; you cannot scan your own, a '
           'friend&rsquo;s, or one you just caught.<br>'
           '&#9642; <b>Five <i>different</i> individuals.</b> Each one is remembered; the '
           'same Pok&eacute;mon twice gives <i>&ldquo;already scanned&rdquo;</i>.<br>'
           '&#9642; <b>Carry only the disk you mean to fill.</b> The Instant-Dex takes the '
           '<b>first</b> disk it finds in your inventory, so a second one in your bag can '
           'quietly take the scan.</div>')
_ix.append('<div class="card good"><b>You are never locked in by a bad choice.</b> The disk '
           'is an ordinary item and its progress rides on the item, so a half-finished one '
           'can sit in a chest indefinitely. If you calibrate to something that turns out '
           'to be a miserable spawn, shelve it, spend another 9 dust on a fresh disk, and '
           'come back to it whenever. Shiny scans are also recorded separately '
           '(<i>&ldquo;Shiny data detected&rdquo;</i>), so a shiny is never a wasted '
           'slot.</div>')
_ix.append('<h3>Is it ever a dust profit? No.</h3>')
_ix.append('<div class="card bad"><b>The Instant-Dex is a dust SINK, not a source.</b> The '
           'disk is consumed by every card it makes, and the charge dust is <b>destroyed, '
           'not carried into the card</b> &mdash; rarity is only a threshold read at the '
           'fifth scan. So the charge is expenditure, never investment.</div>')
_ix.append('<div class="tw"><table><thead><tr><th>Target</th>'
           '<th>Dust in <span class="muted">(9 disk + charge)</span></th>'
           '<th>Recycles for</th><th>Net</th></tr></thead><tbody>'
           '<tr><td>Common</td><td>9</td><td>1</td><td><b>&minus;8</b></td></tr>'
           '<tr><td>Uncommon</td><td>59</td><td>2</td><td><b>&minus;57</b></td></tr>'
           '<tr><td>Rare</td><td>209</td><td>3</td><td><b>&minus;206</b></td></tr>'
           '<tr><td>Epic</td><td>509</td><td>5</td><td><b>&minus;504</b></td></tr>'
           '<tr><td>Legendary</td><td>1009</td><td>10</td><td><b>&minus;999</b></td></tr>'
           '</tbody></table></div>')
_ix.append('<div class="card"><b>The recycler pays by rarity, then adjusts:</b> Common 1, '
           'Uncommon 2, Rare 3, Epic 5, Legendary 10, Mythic 15 &mdash; then <b>&times;2 if '
           'shiny</b>, <b>+1</b> for a background and <b>+1</b> for a holo effect. The best '
           'card that can exist, a shiny Legendary with both, returns <b>22</b> dust. '
           'Against 1009 spent that is still <b>&minus;987</b>.<br><br>'
           '<b>Booster packs remain the only real dust income.</b> Build the Instant-Dex to '
           'get a card of a Pok&eacute;mon you care about at a rarity packs can never roll '
           '&mdash; never to farm.</div>')
_ix.append('<div class="card warn"><b>The cosmetic Player Card costs a full disk too.</b> '
           'The player branch shrinks the disk stack before it builds the card, exactly like '
           'a finished five-scan run. That joke card of your friend is <b>9 dust</b>.</div>')

_ix.append('<h3>The Instant-Dex also scans PLAYERS</h3>')
_ix.append('<div class="card good">Point it at a <b>person</b> instead of a '
           'Pok&eacute;mon and it makes a <b>cosmetic Player Card</b> of them &mdash; '
           '<i>&ldquo;Successfully created cosmetic card for X!&rdquo;</i>. This is '
           'instant: it does not use the five-scan flow and does not calibrate your disk. '
           'Nothing in game hints that it works, and it is the easiest way to get a card '
           'of a friend.</div>')
_ix.append('<div class="card"><b>Seven cards exist that belong to no Pok&eacute;mon.</b> '
           'The mod treats them as <i>cosmetic</i>: <code>player_&lt;uuid&gt;</code>, '
           '<b>You &amp; Mew</b>, <b>Ghost</b>, <b>God Bidoof</b>, <b>Crystal Onix</b>, '
           '<b>Shadow Lugia</b> and <b>Pride Sylveon</b>. They sit outside the normal '
           'rarity table entirely.</div>')
_ix.append('<div class="card warn"><b>The You &amp; Mew card &mdash; a two-step easter '
           'egg.</b><br><br>'
           '<b>1.</b> Scan <b>yourself</b> (or have someone scan you) to make your '
           '<b>Player Card</b>.<br>'
           '<b>2.</b> Carry that card and scan a <b>wild Mew</b>. The Dex finds the card '
           'whose id matches your own UUID, consumes it, and hands you the <b>mythic</b> '
           '<i>&ldquo;You &amp; Mew&rdquo;</i> card.<br><br>'
           'It bypasses the five-scan count completely &mdash; one Mew, one Player Card. '
           '<b>Mythic is above Legendary.</b></div>')

# Every easter-egg condition, read out of InstantDexItem.generateCard rather than guessed.
# All seven are hardcoded `mythic`; this page used to claim You & Mew was the only mythic
# the Instant-Dex makes, which was wrong.
_ix.append('<h3 id="eastereggs">All seven easter-egg cards, and exactly how to get them</h3>')
_ix.append('<div class="card good"><b>Every one of these is mythic</b> &mdash; the top '
           'rarity, above Legendary. They skip the rarity roll entirely, so each is a '
           '<b>guaranteed</b> mythic for a single Instant-Dex use. That makes them by far '
           'the cheapest mythics in the game.</div>')
_ix.append('<div class="card warn">They only work on the <b>Instant-Dex</b>. The ordinary '
           'Card Dex scanner has no easter-egg path at all, so it makes no difference '
           'whether the species is already in your Pok&eacute;dex.</div>')
_ix.append('<div class="tw"><table><thead><tr><th>Card</th><th>Pok&eacute;mon</th>'
           '<th>What else must be true</th></tr></thead><tbody>'
           '<tr><td><b>MissingNo.</b></td><td><i>any Pok&eacute;mon at all</i></td>'
           '<td><b>Full moon</b>, at <b>night</b>, while you have the <b>Darkness</b> '
           'effect</td></tr>'
           '<tr><td><b>Ghost</b></td><td>Gastly, Haunter, Gengar, Cubone or Marowak</td>'
           '<td>Between <b>16000 and 20000</b> ticks &mdash; the middle of the night '
           '&mdash; standing on or in <b>soul sand</b> or <b>soul soil</b></td></tr>'
           '<tr><td><b>God Bidoof</b></td><td>Bidoof</td>'
           '<td><b>Golden apple</b> or <b>enchanted golden apple</b> in your '
           '<b>off-hand</b></td></tr>'
           '<tr><td><b>Crystal Onix</b></td><td>Onix</td>'
           '<td><b>Amethyst shard</b> in your <b>off-hand</b></td></tr>'
           '<tr><td><b>Shadow Lugia</b></td><td>Lugia</td>'
           '<td>While it is <b>thundering</b>, and you have the <b>Wither</b> '
           'effect</td></tr>'
           '<tr><td><b>Pride Sylveon</b></td><td>Sylveon</td>'
           '<td><b>Pink</b>, <b>light blue</b> or <b>white dye</b> in your '
           '<b>off-hand</b></td></tr>'
           '<tr><td><b>You &amp; Mew</b></td><td>Mew</td>'
           '<td>Carry your own <b>Player Card</b>; it is consumed</td></tr>'
           '</tbody></table></div>')
_ix.append('<div class="card"><b>MissingNo. is the odd one out</b> &mdash; it has no '
           'species requirement whatsoever. Any Pok&eacute;mon will do, so long as it is a '
           'full moon at night and you are standing in Darkness. Every other egg keys off '
           'a specific Pok&eacute;mon.</div>')
_ix.append('<div class="card">The off-hand three are the easy ones: bring the item, find '
           'the Pok&eacute;mon, done. <b>Pride Sylveon</b> takes pink, light blue or white '
           '&mdash; the colours of the trans flag.</div>')

cards_html = cards_html + ''.join(_ix)
print('cards: Instant-Dex, dust-to-rarity table and the wild-only rules added')



# ---------------- fishing: the rod, the ball, the bait ----------------
# The page was a bait table and nothing else, which left the two questions everyone
# actually asks unanswered: how do you attach bait, and does the ball on the rod do
# anything. Both were read out of the jar rather than assumed - see gotchas.
_BE = _RX.get('baiteffects') or {}

# What each effect type means. The names are the mod's; the plain-English column is the
# point of the table, since "rarity_bucket" tells a player nothing.
_BE_DESC = [
    ('cobblemon:rarity_bucket', 'Rarity bucket',
     'Shifts the catch up a rarity tier &mdash; common toward ultra-rare. The strongest effect in the list.'),
    ('cobblemon:shiny_reroll', 'Shiny reroll',
     'An extra roll on the shiny check. Does not guarantee anything; it is a second ticket.'),
    ('cobblemon:ha_chance', 'Hidden Ability',
     'Chance the catch has its Hidden Ability.'),
    ('cobblemon:iv', 'Guaranteed IVs',
     'Forces a named stat to a perfect IV.'),
    ('cobblemon:ev', 'EV yield',
     'Raises the EVs the catch gives when defeated.'),
    ('cobblemon:nature', 'Nature',
     'Weights the catch toward natures that favour a named stat.'),
    ('cobblemon:typing', 'Typing',
     'Attracts a specific type. The largest group &mdash; most berries are a type lure.'),
    ('cobblemon:egg_group', 'Egg group',
     'Attracts a specific egg group, which is how you fish for a breeding partner.'),
    ('cobblemon:gender_chance', 'Gender',
     'Weights the catch toward one gender.'),
    ('cobblemon:level_raise', 'Higher level',
     'Raises the level of what you catch.'),
    ('cobblemon:friendship', 'Friendship',
     'The catch starts with more friendship.'),
    ('cobblemon:pokemon_chance', 'Pokémon chance',
     'Changes the <b>85%</b> odds that a bite is a Pok&eacute;mon rather than an item.'),
    ('cobblemon:bite_time', 'Faster bite',
     'Shortens the wait for a bite. Quality-of-life, not power.'),
    ('cobblemon:drops_reroll', 'Drops reroll',
     'An extra roll on what the catch drops when defeated.'),
]

_fi = []
_fi.append('<div class="card good"><b>Two things the game never tells you.</b> Bait is '
           '<b>attached to the rod</b>, not carried in your bag &mdash; and the Pok&eacute; Ball '
           'you build the rod from is <b>purely cosmetic</b>. Both are spelled out below.</div>')

_fi.append('<h2>How a cast works</h2>')
_fi.append('<div class="card">Right-click to cast, wait for the bobber to dip, right-click to reel. '
           'A bite is a <b>Pok&eacute;mon 85% of the time</b> and an item the other <b>15%</b> &mdash; '
           'and the Pok&eacute;mon <b>spawns next to you to be battled and caught normally</b>. '
           'The rod does not capture anything by itself, which is the root of the next point.</div>')

_fi.append('<h2>The Pok&eacute; Ball on the rod is cosmetic</h2>')
_fi.append('<div class="card bad"><b>A Master Rod fishes exactly like a plain Pok&eacute; Rod.</b> '
           'Each rod definition carries only two fields, a ball id and a line colour, and the ball id '
           'is read by exactly two things in the whole mod: the <b>item tooltip</b> and the '
           '<b>bobber renderer</b>. Nothing in the fishing logic looks at it. It changes what your '
           'bobber looks like and the colour of your line. That is the entire effect.<br><br>'
           'So build the rod from whatever ball looks best to you and spend the good balls on '
           'actually catching things.</div>')

_fi.append('<h2>Making a rod</h2>')
_fi.append('<div class="card"><ol class="tsteps">'
           '<li><b>Get a Pok&eacute;rod Smithing Template.</b> It comes out of <b>ordinary vanilla '
           'fishing</b> &mdash; it is injected into the fishing treasure table &mdash; and also from '
           'Shipwreck Cove chests and legendary-tier trainer fishing loot. So you fish with a normal '
           'rod to get your first one.</li>'
           '<li><b>Duplicate it</b> if you want more: 7 gold ingots + 1 prismarine shard + the '
           'template gives you <b>2</b> back.</li>'
           '<li><b>Enchant the plain fishing rod first.</b> This matters &mdash; see below.</li>'
           '<li><b>Smithing table:</b> template + the fishing rod + <b>any Pok&eacute; Ball</b>. '
           'There are <b>48</b> rods, one per ball.</li>'
           '</ol></div>')
_fi.append('<div class="sgrid">'
           + _cd_machine('cobblemon:pokerod_smithing_template', 'Pokérod Smithing Template',
                         'Fish it up with a plain rod, then duplicate it.')
           + _cd_machine('cobblemon:poke_rod', 'Poké Rod',
                         'The smithing recipe. Swap the ball for any of the other 47.')
           + '</div>')

_fi.append('<h2>Enchantments &mdash; and yes, Mending works</h2>')
_fi.append('<div class="card good">Cobblemon adds every Pok&eacute; Rod to <b>both</b> vanilla '
           'enchantable tags, so all four of the rod enchantments apply:</div>')
_fi.append('<div class="tw"><table><thead><tr><th>Enchantment</th><th>Max</th>'
           '<th>What it does here</th></tr></thead><tbody>'
           '<tr><td><b>Luck of the Sea</b></td><td>III</td><td>Better treasure rolls. Also '
           'improves your odds of fishing up the Pok&eacute;rod Smithing Template in the first '
           'place.</td></tr>'
           '<tr><td><b>Lure</b></td><td>III</td><td>Shorter wait for a bite. The bobber reads '
           'this directly.</td></tr>'
           '<tr><td><b>Mending</b></td><td>I</td><td><b>Yes.</b> Rods are in '
           '<code>#minecraft:enchantable/durability</code>, which is exactly what Mending asks '
           'for.</td></tr>'
           '<tr><td><b>Unbreaking</b></td><td>III</td><td>Same tag, so it works too.</td></tr>'
           '</tbody></table></div>')
_fi.append('<div class="card">You can enchant the <b>finished Pok&eacute; Rod</b> directly &mdash; '
           'it is enchantable in its own right. Enchanting the plain fishing rod <b>before</b> the '
           'smithing step also works, because the recipe takes an enchantable rod as its base and '
           'carries everything through. Do whichever is cheaper; a rod with Mending and Luck of the '
           'Sea III is the only real power choice in the whole system, and it is the one the ball '
           'is not.</div>')
_fi.append('<h2>Bait goes on the rod</h2>')
_fi.append('<div class="card warn"><b>Carrying bait in your inventory does nothing.</b> The effects are '
           'read off <b>the rod\'s own stack</b>, so the bait has to be attached to it.<br><br>'
           '<b>To attach:</b> in your inventory, pick up the bait and <b>right-click it onto the '
           'rod</b> &mdash; the same motion as putting something in a bundle. There is a click sound. '
           '<b>To remove:</b> right-click the rod with an empty cursor and the bait comes back.<br><br>'
           'The rod holds a <b>whole stack</b>, and <b>one is used per cast</b>, so load 64 berries and '
           'forget about it.</div>')

_fi.append('<h2>What the effects mean</h2>')
_fi.append('<div class="card">Every bait carries one or more of these. The count is how many baits use '
           'that effect, so it doubles as a guide to what is easy to find.</div>')
_rows = ''
for _k, _lbl, _desc in _BE_DESC:
    _n = _BE.get(_k)
    if not _n:
        continue
    _rows += ('<tr><td><b>%s</b></td><td>%s</td><td style="text-align:right">%d</td></tr>'
              % (esc(_lbl), _desc, _n))
for _k in sorted(_BE):
    if not any(_k == _x for _x, _, _ in _BE_DESC):
        _rows += ('<tr><td><b>%s</b></td><td class="muted">no description written yet</td>'
                  '<td style="text-align:right">%d</td></tr>'
                  % (esc(_k.split(':')[-1].replace('_', ' ').title()), _BE[_k]))
_fi.append('<div class="tw"><table><thead><tr><th>Effect</th><th>What it does</th>'
           '<th>Baits</th></tr></thead><tbody>%s</tbody></table></div>' % _rows)

_fi.append('<div class="card"><b>Pok&eacute; Bait</b> is cooked in a campfire pot from a honey bottle, '
           'mushrooms and wheat &mdash; but on its own it has <b>no effects at all</b>. It is the blank '
           'you season with fruit and berries to build custom bait.</div>')

_fi.append('<h2>Every bait, and what it does</h2>')
fish_intro = ''.join(_fi)
# Luck is the one card stat that touches fishing, and it is applied FLAT rather than as
# a percentage - see the Cards page. Worth saying here because the fishing loot table is
# one of only four in the game that respond to luck at all.
fish_intro += ('<div class="tip"><b>Luck cards help here.</b> Vanilla fishing and the Pok&eacute; Rod are two of only <b>four</b> loot tables on this server that respond to the <b>luck</b> attribute, and Cobblemon Cards is the easiest source of it &mdash; a <b>Luck</b> card in an <b>equipped</b> binder adds luck <b>flat</b> (stat value &times; 10), pushing your rolls away from junk and toward the treasure pool. See <b>Cards &rarr; What the stats actually do</b>.</div>')

# ---------------- where mega stones and keystones actually come from ----------------
# The mega table above says what to craft; it never said where the raw materials are, and
# the two structures are easy to confuse because only one of them has evolution stones.
# All of this was read out of mega_showdown's worldgen and structure NBT - see gotchas.
_mm = []
_mm.append('<h3>Where Keystones and Mega Stones actually are</h3>')
_mm.append('<div class="card bad"><b>Neither of these generates in the Nether or the End.</b> '
           'Every Mega Showdown structure is tagged <code>#minecraft:is_overworld</code> or '
           'narrower, so strip-mining for ancient debris will never turn one up.</div>')
_mm.append('<div class="card"><b>They are buried meteorites, not ruins</b> &mdash; 13&times;14&times;13 '
           'balls of Mega Meteoroid Block with no rooms, no chests and no loot tables. Surface ruins '
           'do not mark them; the two use unrelated placement grids, checked against eight samples '
           'across the world.</div>')
_mm.append('<div class="tw"><table><thead><tr><th>Structure</th><th>Generates at</th>'
           '<th>Evolution stones?</th><th>What is at the core</th></tr></thead><tbody>'
           '<tr><td><b>Megaroid</b></td><td><b>Y &minus;32 to &minus;20</b></td>'
           '<td><b>None.</b> This is the tell.</td>'
           '<td>exactly <b>1 Keystone Ore</b> &rarr; <b>Keystone</b></td></tr>'
           '<tr><td><b>Mega Site</b></td><td><b>Y &minus;19 to +5</b></td>'
           '<td><b>Yes</b> &mdash; 17 blocks roll for Fire, Thunder, Water, Leaf, Moon, Sun, Dawn, '
           'Shiny, Ice or Dusk ore at ~9% each</td>'
           '<td>exactly <b>1 Mega Crystal</b> &rarr; raw <b>Mega Stone</b></td></tr>'
           '<tr><td><b>Heatran Cave</b> <span class="muted">(Nether)</span></td>'
           '<td>Y 26&ndash;27, roughly <b>3,200 blocks</b> apart</td><td>&mdash;</td>'
           '<td>one hand-placed <b>Keystone Ore</b> sits in the cave itself &mdash; '
           'not in any chest</td></tr>'
           '</tbody></table></div>')
_mm.append('<div class="card good"><b>If it has evolution stones in it, it is a Mega Site and it will '
           'never contain a Keystone.</b> That is the whole difference, and it is why people mine two '
           'of them and wonder where the Keystone went.</div>')
_mm.append('<div class="card warn"><b>Strip-mine at Y &minus;20 for Keystones.</b> A megaroid\'s origin '
           'is between &minus;32 and &minus;20 and it is 14 blocks tall, so <b>every single megaroid '
           'contains Y &minus;20</b> &mdash; a tunnel at that level cannot pass one without cutting it. '
           'No level does that for Mega Sites; <b>Y 0</b> catches a bit over half.<br><br>'
           '<b>Different trip, different level:</b> in the <b>Nether</b>, ancient debris peaks at <b>Y 15</b>. Stand with your feet at Y 15 and tunnel straight ahead &mdash; that puts your eyes at 16 and the two-block corridor covers the richest band.<br><br>'
           '<b>Do not bring Silk Touch.</b> The Crystal and the Ore drop the <i>block</i> with it and the '
           '<i>item</i> without. Neither has any other tool requirement, so a plain pickaxe is fine.</div>')

_mm.append('<h3>The Omni Ring</h3>')
_mm.append('<div class="card">One item that covers Mega, Z-moves, Dynamax and Tera. It is the most '
           'expensive thing in the mod and every piece comes from somewhere different.</div>')
_mm.append('<div class="sgrid">'
           + _cd_machine('mega_showdown:omni_ring', 'Omni Ring',
                         'All four gimmicks in one. The five ingredients are below.')
           + _cd_machine('mega_showdown:tera_orb', 'Tera Orb',
                         'The only part you can craft outright &mdash; no exploring needed.')
           + '</div>')
_mm.append('<div class="tw"><table><thead><tr><th>Piece</th><th>Where it comes from</th></tr></thead><tbody>'
           '<tr><td><b>Keystone</b></td><td>Megaroid core, or the Heatran cave. See above.</td></tr>'
           '<tr><td><b>Wishing Star</b></td><td>Mine a <b>Wishing Star Crystal</b> inside a '
           '<b>Wishing Weald</b>, which only generates in <b>Dark Forest</b> at Y 0&ndash;12. '
           'Same Silk Touch rule. There is no other source and no way to farm it &mdash; it is a '
           'dark-forest hunt.</td></tr>'
           '<tr><td><b>Sparkling Stone</b></td><td><b>Brush suspicious sand</b> at an '
           '<b>Archaeological Site</b> in the desert. Light is 5-in-6, dark 1-in-6; the recipe takes '
           'either, so the common one is fine. Bring a brush.</td></tr>'
           '<tr><td><b>Tera Orb</b></td><td>Crafted &mdash; 4 amethyst shards, an ender pearl, '
           '2 glowstone dust, a diamond and blaze powder.</td></tr>'
           '<tr><td><b>Netherite Ingot</b></td><td>Vanilla.</td></tr>'
           '</tbody></table></div>')

_mm.append('<h3>Finding structures: the Arc Phone needs the key item</h3>')
_mm.append('<div class="card good"><b>The Arc Phone will not locate a structure unless you are '
           'carrying that structure\'s key item.</b> Legendary Tracking checks your inventory '
           'server-side before it will give you a position, and tells you what is missing if you are '
           'not holding it. <b>Every trackable structure is gated this way &mdash; there are no '
           'free ones.</b> Several want an ordinary <b>vanilla</b> item, which is the easy one to '
           'miss.<br><br>'
           'So a key item usually does <b>two</b> jobs: it finds the place, and then it works the '
           'pedestal once you are there. The Magma Stone is exactly that &mdash; it tracks the '
           '<b>Heatran Cave</b> <i>and</i> summons Heatran at the pedestal inside. Its tooltip only '
           'mentions the summoning, which undersells it.</div>')

# ARC_TRACK already exists above and is correct - it was built from the mod's own handler
# and includes the vanilla items. An earlier version of this block hand-typed a SECOND
# table that silently dropped every vanilla entry, which produced a bogus "8 structures
# need nothing" claim. One source of truth; never re-type a table that is already parsed.
_rows = ''
for _sid, _itm in sorted(ARC_TRACK.items(), key=lambda kv: _pretty_struct(kv[0]).lower()):
    _b = re.sub(r'[^a-z0-9_]', '', str(_itm).lower().split(' or ')[0].replace(' ', '_'))
    _need.add(_b)
    _rows += ('<tr><td><b>%s</b></td><td><span class="ic icsm" data-i="%s"></span>%s</td></tr>'
              % (esc(_pretty_struct(_sid)), esc(_b), esc(_itm)))
_mm.append('<div class="tw"><table><thead><tr><th>Structure</th>'
           '<th>Carry this to track it</th></tr></thead><tbody>%s</tbody></table></div>' % _rows)

_mm.append('<div class="sgrid">'
           + _cd_machine('legendarymonuments:magma_stone', 'Magma Stone',
                         '7 Magma Blocks around 2 Netherite Scrap. Carry it to track the '
                         '<b>Heatran Cave</b>, then use it on the Heatran Pedestal inside to '
                         'summon him. Each player can use a pedestal once.')
           + '</div>')
_mm.append('<div class="card warn">Heatran Caves sit roughly <b>3,200 blocks</b> apart (spacing 205, '
           'separation 155), so you have to travel a long way from a known one before the tracker '
           'points at a different cave. Each cave also has <b>one hand-placed Keystone Ore</b> in it '
           '&mdash; a block in the structure, not chest loot.</div>')
_mm.append('<h3>Arc Phone legendary quests, by generation</h3>')
_mm.append('<div class="card good">The Arc Phone&rsquo;s Quests tab shows some entries as '
           '<b>question marks with no name</b>. Those are the mod&rsquo;s <b>unfinished</b> quests '
           '&mdash; and they are <b>excluded from your completion percentage</b>. The mod counts '
           'only the finished ones, so a generation is done when you have the list below, not the '
           'longer list the tab appears to show. Generation IX, for instance, looks like 12 entries '
           'but is really <b>4</b>.</div>')

# Read out of QuestCatalog. 97 quests exist; 37 are workInProgress and both
# trackableCount() and completedCount() skip them, so 60 is the real total.
_ROMAN = {1: 'I', 2: 'II', 3: 'III', 4: 'IV', 5: 'V', 6: 'VI', 7: 'VII', 8: 'VIII', 9: 'IX'}
_AQ = []
try:
    _AQ = json.load(open(COBBLEMON_DIR + '/arcphone-questcat.json'))
except Exception:
    pass
if _AQ:
    _bygen = {}
    for _q in _AQ:
        _bygen.setdefault(_q['gen'], {'ok': [], 'wip': []})
        _bygen[_q['gen']]['wip' if _q['wip'] else 'ok'].append(_q['id'])
    _tot = sum(len(v['ok']) for v in _bygen.values())
    _rows = ''
    for _g in sorted(_bygen):
        _v = _bygen[_g]
        _names = ', '.join('<b>%s</b>' % esc(_SPNAME.get(re.sub(r'[^a-z0-9]', '', x)) or nice(x)) for x in sorted(_v['ok']))
        _rows += ('<tr><td><b>%s</b></td><td style="text-align:center">%d</td><td>%s</td>'
                  '<td class="muted sm">%s</td></tr>'
                  % (_ROMAN.get(_g, str(_g)), len(_v['ok']), _names,
                     ('%d hidden' % len(_v['wip'])) if _v['wip'] else '&mdash;'))
    _mm.append('<div class="tw"><table><thead><tr><th>Gen</th><th>Need</th>'
               '<th>The quests that actually count</th><th>Question marks</th>'
               '</tr></thead><tbody>%s</tbody></table></div>' % _rows)
    _mm.append('<div class="card"><b>%d quests in total</b> across all nine generations &mdash; that '
               'is 100%%. Generation VI is the shortest at <b>3</b>; IV and VIII are the longest at '
               '<b>11</b> each.</div>' % _tot)

# ---------------- what you actually DO with the Omni Ring ----------------
# Every number here is read, not remembered: the toggles from config/mega_showdown/config.json
# and config/cobblemon/main.json, the recipes and item tags from the mod jar, the gmax roster
# from FormData labels, and the Power Spot range from PlayerUtils.isBlockNearby.
# The one that matters most is the soup pair, which is the OPPOSITE of what the item names
# imply -- see the warning card. Found the hard way, in game, mid-session.
_CB_CFG_MAXDMAX = 10
try:
    with open(COBBLEMON_DIR + '/config/cobblemon/main.json', encoding='utf-8') as _f:
        _CB_CFG_MAXDMAX = json.load(_f).get('maxDynamaxLevel', 10)
except (IOError, OSError, ValueError) as _e:
    print('gimmicks: could not read cobblemon config (%s)' % _e)

_MSD_CFG = {}
try:
    with open(COBBLEMON_DIR + '/config/mega_showdown/config.json', encoding='utf-8') as _f:
        _MSD_CFG = json.load(_f)
except (IOError, OSError, ValueError) as _e:
    print('gimmicks: could not read mega_showdown config (%s)' % _e)

for _b in ('max_mushroom', 'max_soup', 'sweet_max_soup', 'max_honey', 'power_spot',
           'dynamax_candy', 'mega_stone', 'omni_ring', 'moss_block'):
    _need.add(_b)

_mm.append('<h3>What the Omni Ring actually does</h3>')
_mm.append('<div class="card good">The ring is listed in <b>all four</b> slot tags &mdash; '
           '<code>mega_slot</code>, <code>z_slot</code>, <code>tera_slot</code> and '
           '<code>dynamax_slot</code> &mdash; so once it is in your accessory slot you never '
           'need a Mega Bracelet, Z-Ring, Tera Orb or Dynamax Band again. Each gimmick still '
           'has its own second requirement, and they are very different in cost:</div>')
_mm.append('<div class="tw"><table><thead><tr><th>Gimmick</th><th>What else you need</th>'
           '<th>Works on</th></tr></thead><tbody>'
           '<tr><td><b>Terastallize</b></td>'
           '<td><b>Nothing.</b> The ring alone is enough.</td>'
           '<td><b>Anything.</b> Tera Shards can change the type &mdash; '
           '<b>%s shards</b> per change</td></tr>'
           '<tr><td><b>Z-Move</b></td><td>the matching <b>Z-Crystal</b>, held</td>'
           '<td>any Pok&eacute;mon that knows a move of that type</td></tr>'
           '<tr><td><b>Mega Evolution</b></td>'
           '<td>that species&rsquo; own <b>Mega Stone</b>, held</td>'
           '<td><b>44 species</b> (46 stones &mdash; Charizard and Mewtwo have X and Y)</td></tr>'
           '<tr><td><b>Dynamax</b></td><td>to be standing near a <b>Power Spot</b></td>'
           '<td>any Pok&eacute;mon</td></tr>'
           '<tr><td><b>Gigantamax</b></td>'
           '<td>a Power Spot <b>and</b> the G-max factor, set with <b>Max Soup</b></td>'
           '<td><b>32 species</b> &mdash; listed below</td></tr>'
           '</tbody></table></div>'
           % _MSD_CFG.get('teraShardRequired', 50))

if _MSD_CFG:
    _mm.append('<div class="card"><b>Server settings worth knowing:</b><br>'
               '&#9642; <b>Mega Evolution works outside battle</b> '
               '(<code>outSideMega: %s</code>) &mdash; you can transform just to look at it. '
               'So does Ultra Burst.<br>'
               '&#9642; <b>One Mega at a time</b> per team (<code>multipleMegas: %s</code>).<br>'
               '&#9642; <b>Dynamax needs a Power Spot</b> &mdash; '
               '<code>dynamaxAnywhere: %s</code>, range <b>%s</b>.<br>'
               '&#9642; Dynamax scales the Pok&eacute;mon <b>%s&times;</b>.<br>'
               '&#9642; Mega Evolution wants a bond of <b>%s</b>.<br>'
               '&#9642; Tera Shards drop at <b>%s&times;</b> the base rate; Stellar at '
               '<b>%s&times;</b>.</div>'
               % (_MSD_CFG.get('outSideMega'), _MSD_CFG.get('multipleMegas'),
                  _MSD_CFG.get('dynamaxAnywhere'), _MSD_CFG.get('powerSpotRange'),
                  _MSD_CFG.get('dynamaxScaleFactor'), _MSD_CFG.get('minBondingRequired'),
                  _MSD_CFG.get('teraShardDropRate'), _MSD_CFG.get('stellarShardDropRate')))

_mm.append('<h3>Turning one raw Mega Stone into the one you want</h3>')
_mm.append('<div class="card">The raw <b>Mega Stone</b> from a Mega Site&rsquo;s crystal is a '
           'blank. Every one of the 46 finished stones uses the <b>same</b> recipe shape &mdash; '
           'only the top item changes, and it is always something thematically tied to the '
           'species:<br><br>'
           '<code>&nbsp;c&nbsp;</code> &nbsp;the catalyst<br>'
           '<code>brb</code> &nbsp;b = iron ingot, r = raw Mega Stone<br>'
           '<code>&nbsp;i&nbsp;</code> &nbsp;a diamond<br><br>'
           'Twisted Spoon makes <b>Alakazite</b>, Black Glasses <b>Absolite</b>, Razor Claw '
           '<b>Aerodactylite</b>, Never-Melt Ice <b>Abomasite</b>, Iron Ball <b>Aggronite</b>, '
           'Shiny Stone <b>Altarianite</b>. <b>Choose before you craft</b> &mdash; a raw stone is '
           'one Mega Site each, and the finished stone only fits one species.</div>')

_mm.append('<div class="card"><b>Two species have a CHOICE of Mega.</b> '
           '<b>Charizard</b> has X and Y, and so does <b>Mewtwo</b> &mdash; Mewtwonite X '
           'comes from a <b>Punching Glove</b>, Mewtwonite Y from <b>Wise Glasses</b>. '
           'Everyone else has exactly one. <span class="muted">Mewtwo has no other form in '
           'this pack: there is no Armored or Shadow Mewtwo species, even though the '
           'trading-card mod ships artwork for both. Nothing here can produce one.</span>'
           '</div>')

_mm.append('<h3>Dynamax, Gigantamax and the Power Spot</h3>')
_mm.append('<div class="card"><b>The Power Spot&rsquo;s range is a cube, not a circle.</b> The '
           'check walks <code>dx</code>, <code>dy</code> and <code>dz</code> each from &minus;20 '
           'to +20 independently, so it reaches <b>20 blocks in every direction including '
           'straight up and down</b> &mdash; a 41&times;41&times;41 box. A Power Spot in a '
           'basement covers the room above it. It is also an ordinary block that <b>drops itself '
           'when broken</b>, so you can move it, and you can craft as many as you like.</div>')

_mm.append('<div class="card bad"><b>The two soups do the opposite of what their names suggest. '
           'Read this before you craft one.</b><br><br>'
           '<b>Max Soup</b> is the one that grants Gigantamax &mdash; to <b>all 31</b> G-max '
           'species.<br>'
           '<b>Sweet Max Soup</b> works on <b>Urshifu and nothing else</b>. Used on any other '
           'Pok&eacute;mon it silently does nothing: your arm swings, the item is not consumed, '
           'and no message is printed.<br><br>'
           'Both are <b>toggles</b> &mdash; feeding a second one turns Gigantamax back '
           '<b>off</b>. One per Pok&eacute;mon, and it is permanent until you undo it.</div>')
_mm.append('<div class="card">Every wild-caught Pok&eacute;mon starts with the G-max factor '
           '<b>off</b>, so each of these needs its own bowl of Max Soup before it can '
           'Gigantamax. Right-click while holding the soup and pick it from your party.</div>')

# The gmax roster is the FormData "gmax" label, which is the exact predicate MaxSoup checks -
# not a hand-typed list. Cobblemon ships 34 such forms; Toxtricity and Urshifu each have two.
_GMAX_SP = []
for _jp in _glob.glob(COBBLEMON_DIR + '/mods/*.jar'):
    try:
        _z = _zip.ZipFile(_jp)
    except (IOError, OSError, _zip.BadZipFile):
        continue
    for _n in _z.namelist():
        if '/species/' not in _n or not _n.endswith('.json'):
            continue
        try:
            _d = json.loads(_z.read(_n).decode('utf-8', 'replace'))
        except ValueError:
            continue
        if not isinstance(_d, dict):
            continue
        for _fm in (_d.get('forms') or []):
            if 'gmax' in [str(x).lower() for x in (_fm.get('labels') or [])]:
                if _d.get('name') and _d['name'] not in _GMAX_SP:
                    _GMAX_SP.append(_d['name'])
if _GMAX_SP:
    _lst = ', '.join('<b>%s</b>' % esc(s) for s in sorted(_GMAX_SP))
    _mm.append('<div class="card good"><b>The %d species that can Gigantamax:</b><br>%s<br><br>'
               '<span class="sm">Urshifu is the odd one out &mdash; it takes <b>Sweet</b> Max '
               'Soup. The other %d take plain Max Soup.</span></div>'
               % (len(_GMAX_SP), _lst, len(_GMAX_SP) - 1))

_mm.append('<h3>Max Mushrooms &mdash; the one ingredient behind all of it</h3>')
_mm.append('<div class="card warn"><b>Max Mushrooms only grow on <span style="color:var(--warn)">'
           'moss block</span>.</b> Tested in game: podzol, mycelium and plain dirt all fail, even '
           'though they behave like vanilla mushrooms in every other way. Light level does not '
           'matter. They are a crop with four growth stages, <b>bonemeal works on them</b>, and a '
           'mature one drops itself &mdash; so a moss floor and a stack of bonemeal is a '
           'renewable farm.</div>')
_mm.append('<div class="card"><b>Wild ones are a lush caves feature</b> &mdash; which is exactly '
           'why moss is what they want. Two attempts per chunk in half of all lush-cave chunks, '
           'placed anywhere from <b>Y &minus;40 to Y 0</b>. Find one, take it home, and never '
           'cave for them again.</div>')
_mm.append('<div class="tw"><table><thead><tr><th>Item</th><th>Recipe</th>'
           '<th>Mushrooms all in</th></tr></thead><tbody>'
           '<tr><td><span class="ic icsm" data-i="max_honey"></span><b>Max Honey</b></td>'
           '<td>honey bottle + max mushroom <span class="muted sm">(shapeless)</span></td>'
           '<td style="text-align:center">1</td></tr>'
           '<tr><td><span class="ic icsm" data-i="max_soup"></span><b>Max Soup</b> '
           '<span class="muted sm">&mdash; grants G-max</span></td>'
           '<td>3 max mushrooms in a row over a bowl</td>'
           '<td style="text-align:center"><b>3</b></td></tr>'
           '<tr><td><span class="ic icsm" data-i="sweet_max_soup"></span><b>Sweet Max Soup</b> '
           '<span class="muted sm">&mdash; Urshifu only</span></td>'
           '<td>max honey above 3 max mushrooms above a bowl</td>'
           '<td style="text-align:center"><b>4</b></td></tr>'
           '<tr><td><span class="ic icsm" data-i="power_spot"></span><b>Power Spot</b></td>'
           '<td>4 redstone, 1 max mushroom, 1 wishing star, 3 stone</td>'
           '<td style="text-align:center">1</td></tr>'
           '<tr><td><span class="ic icsm" data-i="dynamax_candy"></span><b>Dynamax Candy</b></td>'
           '<td>4 Exp. Candy S around a max mushroom</td>'
           '<td style="text-align:center">1</td></tr>'
           '</tbody></table></div>')
_mm.append('<div class="card"><b>Dynamax Candy</b> raises a Pok&eacute;mon&rsquo;s <b>Dynamax '
           'Level</b>, which is extra HP while it is Dynamaxed. It caps at <b>%s</b>, and every '
           'Pok&eacute;mon starts at 0 &mdash; so a fully levelled one costs 10 candies, or '
           '10 mushrooms and 40 Exp. Candy S.</div>'
           % _CB_CFG_MAXDMAX)
print('mechanics: Omni Ring usage + gmax + max mushroom farming added (%d gmax species)'
      % len(_GMAX_SP))


# ---------------- Alcremie: 63 forms, and which knob turns which ----------------
# Read out of milcery.json rather than canon: 63 evolution entries, each naming a held sweet,
# a time_range and a result carrying decoration= and cream=. The sweet sets the TOPPING; the
# time of day sets the COLOUR. Nothing sets stats - all nine creams share Alcremie's base
# stats and Fairy typing, so the whole thing is cosmetic.
# Times are TimeRange's own tick spans, converted to the in-game clock.
_ALC_SWEET = [('strawberry', 'red'), ('berry', 'blue'), ('love', 'pink'), ('star', 'yellow'),
              ('clover', 'green'), ('flower', 'orange'), ('ribbon', 'purple')]
_ALC_CREAM = [('vanilla', 'day', False), ('ruby', 'day', True),
              ('ruby swirl', 'day', False), ('caramel swirl', 'day', True),
              ('matcha', 'night', False), ('mint', 'night', True),
              ('lemon', 'night', False), ('salted', 'night', True),
              ('rainbow swirl', 'dusk', True)]
_ALC_WHEN = {'day': '05:27 &ndash; 18:32', 'night': '18:32 &ndash; 05:27',
             'dusk': '17:50 &ndash; 19:42'}

_mm.append('<h3>Alcremie &mdash; 63 forms from two choices</h3>')
_mm.append('<div class="card"><b>The sweet is the topping. The time of day is the colour.</b>'
           '<div class="sm" style="margin-top:6px">Which sweet the Milcery holds picks the '
           '<b>decoration</b>; what time you evolve picks the <b>cream</b>. 7 &times; 9 = the 63 '
           'forms. They are <b>purely cosmetic</b> &mdash; every cream shares the same Fairy '
           'typing and the same base stats, so pick whichever you like the look of.</div></div>')
_mm.append('<div class="card warn"><b>The Milcery holds the sweet, and it has to gain a '
           'level.</b><div class="sm" style="margin-top:6px">Two things catch people out. The '
           'sweet goes on the <b>Pok&eacute;mon</b>, not in your inventory &mdash; send the '
           'Milcery out, hold the sweet, right-click it and choose <b>Change held item</b>. And '
           'holding it at the right time is not enough on its own: this is a <b>level-up</b> '
           'evolution, so the Milcery has to <b>actually gain a level</b> while holding the '
           'sweet during that time window. A battle or an Exp. Candy does it. Only then does it '
           'show as ready to evolve, and the summary screen offers the creams to choose '
           'from.</div></div>')
_mm.append('<div class="card good"><b>Several become available at once, and you choose.</b>'
           '<div class="sm" style="margin-top:6px">Milcery will show as ready to evolve and the '
           'summary screen lists every cream that is currently valid &mdash; four during the '
           'day, four at night. Pick from the list; the game does not decide for you.</div></div>')

_mm.append('<div class="tw"><table><thead><tr><th>Sweet</th><th>Decoration you get</th>'
           '<th>Cook it from</th></tr></thead><tbody>')
for _nm, _dye in _ALC_SWEET:
    _mm.append('<tr><td><span class="ic icsm" data-i="%s_sweet"></span><b>%s Sweet</b></td>'
               '<td>%s</td><td><b>%s dye</b> + honey bottle + sugar '
               '<span class="muted sm">(Campfire Pot)</span></td></tr>'
               % (_nm, _nm.title(), _nm, _dye))
_mm.append('</tbody></table></div>')

_mm.append('<div class="tw"><table><thead><tr><th>Cream</th><th>Evolve when</th>'
           '<th>In-game clock</th><th>Keeps the sweet?</th></tr></thead><tbody>')
for _c, _w, _eat in _ALC_CREAM:
    _mm.append('<tr><td><b>%s</b></td><td>%s</td><td class="nowrap">%s</td>'
               '<td>%s</td></tr>'
               % (_c.title(), _w, _ALC_WHEN[_w],
                  '<span class="muted">eaten</span>' if _eat
                  else '<b>kept</b> &mdash; reusable'))
_mm.append('</tbody></table></div>')

_mm.append('<div class="card warn"><b>Dusk overlaps night, so it is the best hour to evolve.</b>'
           '<div class="sm" style="margin-top:6px">Dusk runs <b>17:50&ndash;19:42</b> and night '
           'starts at <b>18:32</b>, so between those two the game counts as <i>both</i> and the '
           'evolve list offers <b>five</b> creams &mdash; Rainbow Swirl plus all four night ones. '
           'Rainbow Swirl is the only cream you cannot get at any other time.</div></div>')
_mm.append('<div class="card"><b>Half the creams give the sweet back.</b>'
           '<div class="sm" style="margin-top:6px">Vanilla, Ruby Swirl, Matcha and Lemon do not '
           'consume the held sweet, so one sweet can evolve an unlimited line of Milcery. The '
           'other five eat it. Worth knowing for <b>Star Sweet</b>, which is also the '
           '<b>Cosmic Bag</b> ingredient.</div></div>')
_mm.append('<div class="card"><b>You need a Campfire Pot</b> &mdash; sweets cannot be made at a '
           'crafting table. Craft the pot from <b>5 copper ingots</b>, <b>1 glass</b> and '
           '<b>2 apricorns</b> (<code>CGC / A_A / CCC</code>); the apricorn colour only changes '
           'the pot&rsquo;s colour. <b>Milcery</b> itself is a common overworld spawn at '
           'level 2&ndash;27.</div>')
print('alcremie: %d sweets x %d creams documented'
      % (len(_ALC_SWEET), len(_ALC_CREAM)))


# Real renders of the model, one per form, produced by tools/alcremierender.py on top of
# tools/mcrender.py. These replaced a stand-in built from the texture atlases: a motif
# cropped from the decoration texture over a colour sampled from the cream texture. That
# conveyed colour and topping but was not a picture of the Pokemon, which is what was asked
# for. Palette PNGs with a reserved transparent index, ~6 KB each.
_ALC_ART = {
    'strawberry|vanilla': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////+PU/9T09tzv7s/o6NHi4dDg4cne3tDq6sLf38PW6cDd3sPx9qD//wDd3cLc2r/a2rzY2bvX17jS2bTW1rnU1LfU1bPZ0b3T07TT0bPS1LPS0rbS0rLS0rHS0bLR07LR0bPQ0LHPzrXLzL3S0rDP06/Rz6/Pz6/Q0azOzqvN0KDNzavMzKnJzKvLzKXLzJfWx7TZwbXNyKvLyq3KyqTKyqHJyabIyZ/Ix6zIxp7Hx6zHx5/HyJ7Hx53Hxp7HxJ/GyJ3GxqTGxp3FyZzGxpvFxaHGxZzFxZzFxZvGw5/Gw5zFw5vDxa/DxaDDw7HDw6bBxpbBxJbAw5XBwbjBwbPCwq3Bwa7Bway/wa7BwajDwpnAwZLAwLPAwK3AwKvAwKjAwJPTvK7HvJ/CvpnAvp6/v7S/v6q/v6m/vpq/vIq+vqu9vae9vZy+vYy9u429uoy8vKW7u6S5u6S7vJ66uqK5uaG6uZ27vI28uou7u4i7uY+8uYu7uYu7uYnfrq/Qr6rLrqLQoKbLn57MmaDDtqPAtI/DrprEppnCopjAnZC4uKC4uJm8uIu8tou6t4y7uIq8t4q6t4i7tI27sJa7o5G6mYy3upy3t522t5u2tqa2tpu1tZuzuJa2tpW2toC1tZq1tZW1tJy0tJm0s5i0s5OxspOzsJeur5uxsJGur4+vq5WqqqqqqpSwr4uurIusrYmsq4qqqomurYauq3Cup4ypqYyoqImnp4uuo42lpIehopKjo4ijon2enpCfnoKpmoienI+dnJCdnYScnI2cnISbm4qamomZmY2YmH6ZmWjMk57FkZrFipLAiJK3lIy3jY+alYGVlXyUk3yfj4mhioeTkXmRkXaRkHaQj3OOjnSOjW+Mi3OMjG+Mi22Li22Lim6KiWuJiGqIh2vBhZLCgYm+gpCzg4ejg4KUgXeHhWeGhGR/f3+EgmaEgmKEgmGCgFW+en21eoO3coCod3yqbHeNd3DNVmDLRFu+LkuRQk9+Fij/AIAAAAEAAAAAAAAIsUCQAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADZ5JREFUeNrdmX0022nax2dOaVrHOZJQaappLM0EM5mcapNJt4mUMJLFVNfrTtRvwpjoSvNimqppzKC6WipFS2PimWYkpTiIOIPSoOqlhvEWL8WwhPV6ylLaav+Y546dfx4btDP7zz7fc3KIc/LJ977u67ru6/5555f/jN75L+U4Q/b/Cc43cLj9/t/NMXV2hsFPBR7+nRyY6X4LZ+cjYh+f38Ux22u333k/7Fi+ONDH/rdzEJZh8c5m5oATDfHs/X8jxwzp/E0YHgEzh8Hl4iAo8pT/b+IccE6KP2JlYQ4zR9rmyqFgKPj423OssM5JiUctzc2RaKTNkXi5Mk8McQ9++rYclHNiYhgKh4Tb2NoeCfvG+fj1iOsi6ODb+jkSn3jUxhaDgNseCEuID8OTmSzKOaXcV/SWnMQwGxs03Bxu7RQefpLkzmIQiY6+SkXBecVbrmsvFo9GO9BIHxDfI5AIWCwajT4WGS1TXfAVQ2/BwaHIDAab5UB0IlIJBADBHHJwAzvGEwdDJ6y5b8YxN4dZshkMBp1BIhDwh3BEBwKBxGAxIAgKDgoICAqEduaY74LtMoHBsCw6ADFJTlQHNM6J5OHuQSIRTgVzIcjf/wv/gDfwA4PDzC1gGBadRmMwPNlkG1sbq7DL4a6OEWUq8V8gn9CAoFNvwDmAPL4PBjPHsRgcjgfDlWSFSYjHJ7XHW6Ai8gvVKesNPtCX0aIdOQgE2k3kQBRI0iXpQk9KeGJYfHt7eHI8QFv7vlhfX38965Mql+/ASUIcOWp1NO98JsePw2F7MjlJSR2dHeHuZJt9cBgMkbL8ygC6rfDdnpOYmJCUGJZUFukNOAKhUJhZ0jE1nezu6YTGYfdZ2yGR+DUAKsj5XuW7NQdmGu+V0P5Te3ab6nxmenq6RBLH/6HxYRbFhUF3wqAPYQ59gP1Q9Wp9DYpUqT/J34pjaook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',
    'strawberry|ruby': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX////U///v4OXwy9riydPpwM/bv8rNxMvYvcjXu8bTu8Xbt8bVuMTTtsLXsMDSsb7QsL3LtcDMsb3Mrru9sLW9rrO3r7LlqbPRqrnOqrnNrLrNqrnNqLfMq7rMqbjMqLfMp7bMpbTLqLfLprXLpbTIqrbJp7XAqbLKpbTDpbC7q7G6p667pa24pq6qqqqUqqrKorHIorHIobDPm6jInq3HobDHn6/Gnq7HnKzEoK/Fna3Em6zFmqrEmqrEmqnEmanDn67Dm6zDmqrCmqrDmarDmanCmanDmajDmKnDmKjCmKnCmKjDl6fCl6e9oq26oqu6oaq5oqu5oau5oaq5oam5oKq/nqu/nKu6nqi/mKm6maW2o6S3oaq4oKm3n6i3nae3m6a3mKS1m6W0maS0mKOzmaWkmZ7SkZ7FkqPDlqbDkaHAlqfAlKXAkqS/jqC9laa8k6a9kaS9j6O9j5+8jKC8ip+7ip22laKzlaG1k6CylaGxk6Cxkp+4j6K3j5uykJ26i6C1jJzlgo7RdoHHgI7HdIC/h5nBf4nBeIfAc4K7iZ66iZ66iJ66iJ26h526h5q7hpu7hZi7dYa5iJ25h5y1iJu5hZu2hZe4gpW2f5KzgZK1dYOwlKCwkp+wkZ6vkZ6vkJ2ukJ2vj5yuj5yvjJqpkZqrjJmqipehkpiZj5Obi5Gsh5aqh5WrhZSniJWnhZOphJKmg5GiiJGch4+dhI6Who2XhIuXg4qsgJOqgI2jgI+bgIqXgImVgYike4uhdoiVfYaXd4SaeYCQd4ChcoCScH+EfYCOdn+UcHyNcnyLcnyOb3mIb3mPcWvVYWzHY2/GYm7CZ3XBX2zBWWW6a3yzaXe0ZHSzWn64V2WzVl3LT168UF67T12yUF+ySlqxRlXDO0+uPk22LEL/AP//AADMAACeaHmaZmeLbHiOaHaJbHiJa3eJaXaHanaHaHWHZnOFZnJ7Z3CdXWaFYW6DYW+DYG6DX22BX2ygT1yIT1alKT1qHywAAQEAAAEAAAAAAADZDLjaAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADfRJREFUeNrdmW1U0tm+x8/pwSMTio16DmEihs/aWkT5hHFEZmhiTNHDqOnyIdGWkprJlUR8ognU8jppEuMjETJSaYpMamoghS1TWymKLG9Ypi/Sk/mwDM08L7qbc++b25BOM+fNud9Xf178P//v3r/f3vv32/zhw79Gf/g35Xz/N+d/BefiX75w3vu7Obu+T/kT/IyXze/kmO+GW6Z8Tz8d6vq7OBAzzOHvD0Ncm5K8XF1/OwcKT7mYAjU3d2+iUeOdbX4jx9xIwVhAoBCL/GQKNd7V5jdxHFNGeYf3WkAhUAt7YUMEJTbM9fM5ex1TRjSpVl9AYXYw+8MXi65fTwqLtY74XI6dkYJAWsGQ9sjDFy+muOdn5p6iWn+un8MXNan29g4wiwPoVN5FrqP3NyF+mY35kac+k8NLsbdHwiAW+9zOFNP9goLJPj5OkSJRY2L+Z47LDIXeh3D72hfjjTzkg0WhkHb73OOT8sQ5kYkRn8FxgPuRSGnBbj4YHzzWG4m0c0A5EagUakJSeIT7L2b7Exwo1ByWTiSRiCRfLBaNQvu6YbE4UvC3YRHUMIqHRzglbnsOdBdk5y5zswNpgEMKxmHwbkg0xudYENnX19uLEhH7na2Nh43nr/BjBtIXao5MI+LxJBI5LcAOaW+dyismOsW0iU4fjPT08vD09Nieg4L5f2lmDkGlkbKyyKSv/K1RpdwjI+NcC3hMk6SNu9nnEUZLpG3LsbDcH0pz8WGW88v5ZWRcMS+FOz56toQLMYdah+k3X27+o/8gS5i/DWfE8nDq3tSiREF2RgYjnRzMGBkfnxwvDvK3Q1hAzGFc3czs7D/62cKorTkjI9xRHnfkTmwaIyODef7y5WvtE/qpYkIIBolGWSPQVjD089nZTXGDWBz5aY65Ge9Myfj4+MQDUYyAz/+hvJzPbO9Q1gUcJX2FQSJRDg4YtLt4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',
    'strawberry|ruby_swirl': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////9Tq+9fr7Nfk49Hk4dHf38rq2dLd3cja2Mb9/kna27jX17jT17bV1LbT1LTT06/U0rPS0rPS0rHS0bHR0bHR0a/R0LDQ0K/oys7Ty7bQy7LPzK/OzqzOyqrMzLjMzKnMzKjLy6XKyarJyaLHyaXGyJ/Hx6PHx6DGx5/GxqLGxp/Gxp7Dxp7GxaXGxZ7FxZ3BxZ3lvcvZu7rWub/Owq/Nva3Pt7TPt5fFw6nFwp/FxJ3FwpzGvKrGvJnHtaTGtZLBwbfCwq7BwqzAwKzDw6PCwprCwZzBwZbAv63AvpTAua/At5K8wZe9vZu8vJu7u5+8u466uqC9uo+8uoy9uJ68uYy8uIy8uIu6uZW7uIu3uJy9tqu5tZ+2tqi1tp21tpq1tJq7t4u6t4e8tI21tZS2tYyzs5bfrb7Rr7rOrKnNp7jLq7PLprTGrq3Fq6vGsJXFq5LGpqXGp4vFpobFpIO9sLG6sbC8ra6/r43ArZC7r5a9qbC5qau8pKzBqZ+5qJ+7p4PInq/Cnqq8oKq5oqq5oaq5oKm4oKm3najFmq3DmanDmai/majDl6m7l6XAkabDoIO7oIrDmZO6mYi9nHq5mHe7mHDBkKC9i5+7jZa4lna4kIW0sJ6ysJSwsJCxrJeqqqqpqpOzppmnp5Gyr4etroutrIirq4qsqIqqqHmzoZ21naSroJasooKunIGko4KfoJSdnpacnJCdnYufnn2bm4WzmaWzlqGxk6Cwkp6vlYmwj52ujpmui5iyi3KviWSil5CZmZOhl3uZmHamjJSmi3WcjYGXloeVlXuSkXqRjHiLinDOf4O7hpq6iJ25h5y4iJe5g5SshpanhJKugJKwhoOqhmiofX6eho+XhYyagYudgmyUgYp/f3+LhWuXfYegd4mWeHSQeXuOdH6gaG6Rbn2McHuManiKbXmJbnGJa3eJane7V2jDPVGxK0KfGzKHbHSHaHWHZnOFZnJ5Z2yEYW+DYG6BYW6CXmxLMzr/AEB/AAAAAAEAAAAAAABuYQkrAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADTVJREFUeNrdmXlU02e6x3svmMJJTGo0skZDCBqajGE0yKZhFSLU1iQUkaWyKYaA7LkygGCRyFb2gByEeMoWTopEBYE0glZ2dcAhV0XiIXYyIgVBgRH9y/v8cP6pDaLt/DP3C+FADu+HZ3uf93l/fPLm36NP/kM5u3Oi/x0c+13MaP4f5pjY7mbuihUJ/yCHudOOaWt6ouNU2h/iMHfG7DLdxUzrBlDa7+fw+VH2dkwmM6a7Q5QTLfydHCbfzj4qhg8cZldHtignTfi7OIKopPjoFQpfoFCczRaJ0j6eI4iJSkqM5SMMviDKvkup7Dwr4ud8LEcQlZiYIBDwmQIBUOx3n5Jl1GWKBB9rT1QcQlnBxMbbs2x3ONpQvEJDgzI/kpMYtUJh8k84s6zJ1nRrCwtjh9CQyIMhH+nXTkE033a3oyXRgkAkk4wIG3BYSw9uYCjX4aDHR3Bs7fbSaDbbjC2IFlSSxQYcDr+RaOXh7sHluntYYj0+jGNggEJ7bqNZ0xhkEsl442YykUSi0Bg0D5C7q6ub2wdwDPRQenooFMGJBmJQiFTihs1EMt2aTrYiubkDyBXRB9iDMkSBPXgnGpUKICcKDo9bT0lhWRO/bIzkuu912w/2fACHgLbEoFAGm51obDaDRiOvx7uwzJNK7A2xX9bWNpbN/7h1P/cgd00OGr3BgWtO5vkF+Af4MiisOAqrJJnlYg9orMOz+bn55/1uwSEha3AS0VvImO2hB8O92WxvT4YNOylZXCFmbaPgMIYoFLrswfw8gAJDHd7PSUxkJcezkho9HL092Tyer29YS2lF5RfbGRBrAgZrjEYbPQNQZMjRSIfVOSh9lz0uJeLk0iEwKCDA39/vkG/zTzdKkXgT8Rs24jduMSJFzs8/8/CIlO6rXY2jr4+x2MaqrpAPD7dxef5+iHzDB366/P1X1hQCnkjAUWgWzZEP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',
    'strawberry|caramel_swirl': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////8jn5ubv6rjk4Lbi3a/g3LH//5P//wDn26ri167j06Pn0Z/hzp7lzpvhzZzhy5vkx5PgyprgyJjfyZnfyJjex5bc1rXQ1cjYzKrLzLvYx6Hcx5bKyMDcxJTbw5PZxJnbw5LKxMTSxJ3XwZnYwZHZwJDbwI3Zv43ZvozXv4zLwLXEwMTAv8DNv5jEv5fBwJvYvYvXvYzWvYzXvIzWvIzWvIvXuo7MvKDOvJDTu43WvIrWu4nVu4rVuonSuofVuY7TuIXRuIrTtI/StYXQtYLQsX3Lt5DKtJLMt33Msn/LsIXNsXzMsHu+u8G+u6+8t76/t7C5ucG4t7K4trbAsaa7sq+1s66zsreysa3DvJTBvZbCuZHDt46/u5a8t5i4tpS8tojDtI3DsYvDsIa8spLYrIXMrnvLr33LrnrLrnnLrHnKrnrKq3jBrZzCrojBroXArYTIrXzHq3jArIHOqIXMpIbLp3jKonjBqITCp3jBpHrEoH7ImoXHmnnHl3bEmW/Dk3PDj3C1ra+xrbKwq7KvrLGvqLSwqLGvp7C7rZ6zq567rIm3q4y4p5Swppi6pnyzoZO1o3+4oH66onq0oXq6ona2oXS3moi3mXizmnG4knmxknG2jXSuq7Guq66uq62tqq+qqqqtp7SrqKypo66ppaWmoaSso5OqpnGloKiin6SlnamhnqOgnaOfm6WnnY+gnpGnnXugm3qdnYidmnujl6qhlqmglquhlKaikqShl4qmlnGkj3unj2abmKCZmZmbmJealJ2bmHialHebjW6Wk5mWkJeRkpWSjZWOjYzPgXC8iGm7h2m6h2m2hGmxfWGxeVqqh3ygiHeah2mhgHOifWakfmCOiY+NhpCIhomHg4uDf46Df4aBfIN/f3+BfoJ+eoCWhGeKeXGTgFjAdGGkdFiJc2x8d397dn56d4F7dn16dH54dHt3cnt1b3lzbHfLW1bPRVd1anOQWl7DMUupL0KgHTVxaXZwaHVnZW02NT3tAEkAAIAAAAAAAACPuL71AAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADXNJREFUeNrdmXtUkum+x/dRmbUSLwyh5tElqYmOMGpa5A0aHawcNZkGJkKtcxTHKyYGXnKSZFtkmFApKdKWtnhZItrWzEtuPalompdyO6nsrSscdXTnhTyTl/NP53mdc/4Yw6w9+59zvmshi+V6P3x/l/d5fs/L797+c/S7/6OcL0sp/wzOd1gcBfebOfsOeNphqTnk38ix24e1O3CAWp1D+00cOzsK9gDWjtZRkUOj/OMc3OdJHE87O4hTKidT/kEO7nNPThIFBzg4RUVpqXwnR7twyJ7c1K9PbmFOKRSyUlkp7eM5p8ieWZeogIIj405RUyvr6qrvlZ6UfSxni3LqFA5HPnXq2xMcT5owKV8gI3+sn69Tv6eeIpMBhvxtKofkecDb15HEOk8VfCQH8kIGmTn59QmSL8bD18fW1syLlcyOZHxkXHZkykmsp7eDjS3SxhZthkIgTFzORjJYkV6R9I/g2GNdDnv7+prb2ti6o20RCAQSZe51NoweHhlGd7E6+2EcQ0OYkZ+Pj8/hwxi0jRnSDGOORmPwvj50Oj0szM0tzJW+O8dQH6avD4OhiB54PJ6AsXG3RqBsMD4ePhgM2jWMHkZ3g/QBfvbAYcAP4Li74/G+RCcEwtT4SDrJw9y/gPXvYXTXsA/jII1cLGEwQ2siPiCAgPfAGCM5JJssHsfQ2F/ELuCuSd3ORkRE7MoxMkJ4hds7xMYlxiXGEJyCUo98l51N4nAA2srr9fqbtfW7rlGM5F04WUboI0ZHkiOZx0ikAD9fQgCXyxvgkZwxpsZwGAx+aXYNgIajWF7v56RnBXHTv+QW0P0DSKTgmJiYC/XFA4McZwLINcrY2AwO3/t6bW2dxWBtI/2KAzPgkDi8geySNlYEMz4+IS4uMbjwQX2x02f4w9YIBAqJtNmLZq+tzYaFs8Te7J04BgZwW2fSwFCbStUWFRsf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',
    'strawberry|matcha': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////+Ds+c3Z9sPa6L3W4rrU37rR37HS3LXP3LDN2q///4///wDM36bM26nK2qXL16nI16fH1aXF1KHE06LC1J7G0arD0qHDzqfC0KLC0Z7GzpzB0Z7B0J/B0J7B0J3BzKHA0JzAz52/z5y/z5u/zpy/y6C9zpq9zZq9zJm5zJi7zZS6y5W3zI+6ypm5ypS4ypO3yZK4you1yYy9xqO5xZy2yJC2xZW1yJC1x5C0yI20xZCzxo2zxoyzx4mzxYuyxo+yxYuxxYuyxYqxxI+xxIqyw4qwxIqxxImwxImww4mwxIS8wK66waa4waG2v5+2wZq0v5qzv5m0vpq2wZCzwJSzvpizvpexwJGxvpWvwoe0vZiyvZeyvJeyvZOwvJSxupWvu5O3sZSs1o6twYetwYGtwIWswH+rv4OtvoiqvoKpvoCpvnquu5Ctuo6tuZGsuY6ru4eou4Gnu3msuI6rt46qt4uptouotYuot4eotYiotImntIintIGns4Olvnymu3yku3mmunylunukunimuX6kuXykuXqjuXqkuXalt4ejtn+ltISms4els4WkuHqjuHmjuHWltnqhvnqit3OhtXigtmmbx46ftWyetGiC5YIA/wCmsoeksoOjr4SgsICfroCerX6qqqqiqYueqYCbqX2apICYo36Yn4aisHifrXmcrXmbq3maqniaqHiXo3qcsWybrnGZqHKZr2GjrFKUqmSSqVyUrFSSqVGUpXOSpGiVn4GVnYKTn3aTnH+Sm3uPp1eNpFuOp0uMpEiPoGuOoF+NnGyJokmIoEWHnU2DnUKCmz9zoUmklnOSmn6PmXiOl3eLlXKJmWOKk3KIkm+Gk2qGl1aFkGyEjmuDjmaAmUN+mDl/kVl4lDlmmV11kDeAjGV+i2N9imN8i2B3jEGSiGd8iWB7iF56h194hl53hlR2hFl1g1h0glhzglZzgVhygVNwhTi1cmV/f3VzfVhufUxdcjbTUl3KOVG6KkSnLT9jHSQBAAAAAAEAAAAAAACkNOtSAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADdZJREFUeNrdmX0wG/i6x/e2bMRMvUQ0alYcKQ3bbNEWpciJNN2IRaIrumkctYPGa7wmmuYcKdumvRqNFMNMSE1R70pGiK1ESdUyrZfGS9gOwvW+irmq9U/vj3v+Od2Udvf8c+9D/mDm95nv8/ye3/N7nl++eP/vsS/+j3JuU4/9OzgF5oZ/OfynOXpXrnxpEx14+k9yIPrWZlfizoeTXf4UB6rvcDLuJORYCZPscvqPc6BmcQV+hgYGJ0riqaHH/P8gB2LmXRTnYAiBQk04qRRqaID/H+LY+nVKT5oYGkINTY5wr9Ep1BCXz+eY2Pq1Sr1hUENTSxO4d8EdLpdJDbEI+lwOwq9FRoRbwUwtEYhTBQXeLlejr4aHWHyunpNFLUT4EWtTEyQKWyS9jXb08T0VLeYEh38mR+oNh1uaQE0Q6CspNFd3At7RER0sEOQkcD7TL30bOwQCjXXGYKwcnDAoFHDPJZTJFiQGJ4R8BsfG3BWHIxHsnb528sQ4AgjSBu1GpVDDmUEhLhb0T+NAoQawKCwOh8UDOXY2ts5ojKMrjoALoVMvUPwDLpA/gWN4EHpQDwI5SgIcHMHVwdPe8qiDE84T7+x6gkwJoV7yBxbwCXogJlBDQwiShPXyAiCaB8ISDvOTpmDR0bU5iUGXyIEBgQGfwLE2djsMgUBtSTgGg4DDOsGQRbcxrb0FhmbREknt8+3nJy4x48P35RgZWbuF2zvz+EK+MItw5rbU73ZXV1xhAcQACg/e2n67vf3cLY3D2YfTanzS24QoSMiNjYqKiSIQYlq7enp74tydj8BNoBDTHze2321v/xdLELw3p6Ult1Ma11pziRQTxeBlZmUJG570TeS6Ex0sUSg43A5mjNrY3t4Wc3LEwR/nQPSLIgt7erqeDIrjc4VCIZ8v5DU8bm/2APF2sLK0QVo7oL4Wb29vBIUV114s+RhH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',
    'strawberry|mint': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////9T72+rl5ee/5vLG1ePMztW1z+OvzeDMyMvJxMrFwMS0ydqvyt60wdK/v8Cpx9ymw9igw9qiv9SfvtScwNbAur+9uL28usC5ub+7tbu3tLq2tLe1s7asu8ist8Wjucmws7mqs7+ks8KevdOevNKdvdKdvNKeutCcu9GcutCbvNGautCduM2ZuM+XuM6ctcecssKYs8a2rLSyrbOxrLOwrLKvrK+uq66vqbCvqLOup7Krq8atqbGtqq6sqa6qqqqrqKymrsClrrWersClqrSgqbmeqbuasMKXr8GZr76ZrL2YqLuuo6+po6unoaqko6ujoKWjnqOapLKboLGfoaeXoKqgnqOgnKKcnaaulqill6mjlKail6ihlaihlKecl6ecl5+ZmZmZlZudkqaYkZ6Yjp2UutGVtsyTtsuTtcyTtMoi8vWQtcqPs8mSscaOsciNsciMssiMsMeKsMeTrsOTrL6OrcWMr8aLr8aLr8WMrcSKr8aKrsWKrcSJrcWJrMN+rMSQqb2Nqb6Pp7iOpbiIqcCEqsKJpb2Ro7iQorKKpLiKorWHo7mHobmHobOCqcF/p719pL6Ao7h9orl8orx6pL56orx5orx5obt4o75xp8CNnruRnaqGn7yHn7GBnruCnrKBnLaMlqqGlq6Uk5eHk52BmbSAlLSClKJ8oLl5oLp9nLR7mbJ6mKx3nLVwmrF6lbZ7krpzlbJ6lqp7k6R1k6eTkJqQj5CQjJaNjI6PiJmMiI2Jh4t9kKR+kJ1/j5t9jaZ9jZqAh554j7l1jrh4j6V1i7V1i590iKNuj6xwirBrjqBvh6tnhqGWgJSGgoeDgIWCfIR/fKd/f39/eH+AeH53gpx9eYB8d397dn55dn5pg69ogq5rg55rgpFpf6lqf5JreZRjf6ZhfJRdd6RgeZCacIV6dH55dHx4cnx2cnl1b3p0bXjTRlmdVWm3KT+cIDVtb4FyanZxaXZdcpNbbI1TcZxwaHVhZnhXW30fHSOQAGAAAP8AAAAAAABLw9+OAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADZhJREFUeNrdmXs02+m6x/daOg1StkvatIgiOpq6VhnZzE6PS5BB0tBJcnYG42AmJ1ZREWSEGJdGRXcyaV3rrhQhihR12UoZnKiNvc9xqdBq3VKUqtaZf3reX+ecP3Z30M7sf87+Zv2yJGu9n3zf532e931+P795+4/Rb/6fcthYg38EJ14bbgD/1ZzD1h4a2ngn5K/kaBw+Dre2cSM6oH4VR1PD0NjaWAMVQnJAGf5yDvy4R9HnmhoaRiFErKuB0S/kaP728yIvQ7iGpgbcn+SEdUUZ/SLOCfRAiRlcEwiOpFJxTjgn1Mdz4Ibo/hq3Y4BxHI50K6L6+xOxWCTuYznIz5sBBQmHI5FIM98iEweKb9YF3LGP9WNWVOOGRJ6Aww0M3IpKUkzsE3kxV4TZnviP5Nx2QwIzGvDjZqkiXgSLx2UyrdhCYXla9kfOS8PA8ISxSXyELdPClsnAYMzNEXaEVIEwjZ1G+AiOibF9QgKPa8O0jWAxmObm5hYWNlEEb0JcqjfBTp/wYRwtLZgeP5bLTfgugsGwsrCKsGEwIjlJHAKB4O2NRnt7fwBH65D6oUMw2Kc8FofDSYq0ZdmYW9pGcDncyEjGWW8C4Qs00NkP8APTUQd+TvFYLEBK4kWbf4rQj2rmc2zSpMI0ew97D7SHHfpgjqWevS4MpmXJ44hESRzOJX2Lkis2zfJMHURaebn0q81O2y9SU1MP5OjomEfFnWGK8wryCnKSokVl8VcGB66UlajDtPTZLzY3N7e6IjKysw/gNOsyI3Sjs9MkP/D5In5Skqh/QD4r58dGIvR11GG6wcsQaCxTyN6f09ycOVCW2N9ASBTxReKcnBxJ7aBCIb6cZGtuidHXt9LTOw0sbZVeE75H+hsODFaWUjY4OyifE6ZJCgoK8vIKcmX3/9QSw+Ik2J4yx2AsbE8zSzc3X7DjhNLE8r04MJgu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',
    'strawberry|lemon': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX////5+s3u7Mzk5cPi4rzi38ne3rzZ2Mjw8Z7c3ar//1X//wDb26fY2KfW2KXW1qbV1aPV1aLU1KPU1KHU1KDT06DS06DU1JrPzNTOzL/PzqzKya7T0p/P0KHNy6TIyKHS0ZzQ0JvQz5nPzpjNzpnOzZjNzJfKypjPzZPMy5PMypLKyZLNy47KyI/LyYzMyX3Jx5DJx47Jx4zByIXIw8/IxMTDv8jCwL3HxafDw6TCwazBv6fGxpfHxZHGw5PDxJvCwpvEwZfBwZrAwJnBvpfJxo3Ixo3IxY3HxYzFw4zHxYnFwojHw33FwYjBv4PBvYPFwHjBvHbDvV6/v7G+vpa+ur2+uqK+v4i/vIC+uoK+vXy+u32+u3y9u3y9uny+uHy+uXG8uci8ura8vJu8uJ28v4u7u467uXy5ua26uZG6uYu4uJOou5i8tca7tbi2tba2srizsbSyrbOwrrGvrK+vq7Cuq66uq62wqbiwqbOuqq64tqW4s6K5tpi2tpK0s6e0s5WzsJyvrKGqqqqsqp2sqaHAnLmvqLSup62tpbGrp62pp5mqpKqonrGmo6mlop+joKajn6Glnaqjl6yilquhnqOgnaOfnpagm6OdmaOamZqhlauflaqflaCYlZq7toG+tH63toi2tYS0tIi0s4C1sIGxsICvrn6vrHqurIGurHmrqYC6tm+7tWK4sWazsG+xrGusqW+7tFK3sFCvq1W3r0azq0W0rDuuplu3oGqopXyoo2WupUKtpD2sozupoDqkpIKlpHWioHWilnSknUqhlz6hly+ill6foISenoSfn36cnIObmoCdm3CZl3OXlG+bmGKdlzukkKaZkaC8hWuZkVmVkJmUkoyVkEuRkJOQipOQj22QjUmMio2JhoqHgYuBgIiCfYWLiWt/f3+AfIGKiGCJhT+ednJ+eX19eHp8d317d357dn56dXx5dHx4cnx2cHt1bnhzbnLOWF3NQFWCXm63L0agHDRxaXZwaHVnZW02NT2/AP8AAFAAAAAAAADiMMSNAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADYtJREFUeNrdmWs0m+naxzudsFfWciZTJVWkjmmMpEFplGqrImUMiUlFyRhvSNYqMohDKVWzbYI3aIoWbcQODdE6BCUORTsV511NnaLVhd13Mw7DQveXvnfM/jKdoJ3ZX/b+ZyWSD/nlf93XdV/PdT8OvP/36MB/KMcnMeLfwfE1wkY4/GGO/pcXsUbXvo/4gxysvpPhl77JudHMP8TB6ocgfVF2UbcBKOr3c7AOX/kS7LDYqOJsVlZE5O/kYB3O+16KtMfaYe24uTGsLGbk7+KEeIlF/t/a29nZ2ZPyuIkxcTHMT+d8G4FvEIV+i7VzINlfCaX+b1FRbiKLFPepHJJXPaBccbAnXbniT/W1YbKTU9NYpE/14y+qD71yhWRvHxGRVOPrc/KoM+Y4nnfNP+0TOaJkBQVrRwr5xsfTComxMTczxvF5PCLjE+PSj4ggGZ50tjA11TExR8BhWloaR8/SGTwajuj6CRwjQxdbW08bY0tTc5SZmbaWlq6esYWbqxuR7up2VNPt4zgQVYiapw0aY+tuhUDA9eDmxgiENdod7ebm5urq5OTo8hEc1c8gnx2EQGAetmg02t3KBGWiDTcxt7XFWFkdc3EFJD8/P6dTH+EHAoVAoRAdD1sUCoA8rbW0NdVtRD62xvhKHt3F1eWU0ylHp/05emoW6hAIBO6B9vJyR9uaq+v5+iAamn2hGnj+XyvHNnuOuhGJxH05UKgejnjEnEwJAg93pI/oS59m8UWqL0Br4ta3Nja3elzoDMY+nHq14zZQGx4tzJtA8Cacd/cWNzdJmi4izbXUoRAI9N7Y5iYA0Xi4vTn19V+LRT7iKjc84JDJFEpYV0t7x9dId7DWMHVNuBoUvg5AfAaPj9udA4H4EqhNkubGQR4xLCgokEIJIre+lD60ButtoqOtp6tnCj/G29xcdzvLr3Tm78b5HKJuhvRpl7QN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',
    'strawberry|salted': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////6ro6Ord297a1NvU0tXRzdHMy9DLyM7IyMjLxszJxsrIxcrGw8fFwcjDwMjDvcbDv8LAvse/v7+7v8e+u8a+u76+usC7usLAt8C9ub68ub68uL68uL28tb27uMC7uL27t727t7y7tr26t766tr26try6trq6tby5tsG5trq4tLy3tre3tLe1tLa3s721s7a3sbqzscK1srWzsbTBqbu1sLi1r7i0rrezrrazq7Wyr7iyrLWxrrGyq7WxqrSxp7OwrrKwq7OwqrSwqbWwqbSwqbOwp7OvrbavrK+vrK6vqbSvqrCvqLSvqLOvqLKvp7KtrcWurLOura6uq66tq66uq62tqbmtqq6uqq2tqq2tqa2sqq2sqaytqLaup7OuqLKup7Ktp7Ktp6+uprOtprGtpLGqqsGqqqqasMqnqMWqqLirqKuqp6upp6qnpbqqpa+ppaunpauopamnpKiooq+mo6iqoK6noauhosGioLekoqqjoK2loqajo6OkoaajoKWjoKSioKSYmr2amricm7apn66onq2enbCfmq6mnqmmnKqlmaqgnaefmamin6OinqOhn6OhnqShnqOhnqKhnaOgnqKgnaKfnaGgnKKfnKGem6GfmaGcmp6cmZ+ZmZmcmJ+kl6qjlqmil6milqmilaihlqmhlamhlaihlaeglqmglaialrCdlqGZlp2hlKiglKegk6ehk6aek6eZlJ2kkaOgkqWakqCYkZufj6KZjqCUl7eTk62Wk56VkZ2TkKOWkJmWlJeUkZaTkpSSkZCSj5OUjaWUjZmSjZWMjaSOjZSPjpCOjY+NjY6NjI6Mi42vgpyRiJWNiJCNg5KKipSKiYuKhI6GiayHiaaFhqKHho+HhYiFgoaGfYuAg6h/fo2Cf4SBfYN/eoN/f39+eoB+eH98d396d32icIB7dn56dX15dX14c3t4cnt0coF0b3pzbHdyandxaXZwanS/W2zGQFW4MUarIjh0Z3hoZm9YVWJaFCDlAOUAAP8AAAAAAADtH4oSAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADcZJREFUeNrd2WtQ01faAPAdEchwTxWzxaAGIQJBJJgNgRJYpKHNG/IH+qYLpqU0XGcisMFwX9mEigQEjDalKVHZcFFTuUWIEkmqBKRBQgly0ZcS5DKYBSTlIpfZT+6J2y9rA2i7X/Z9ZpiBD/lx/s855/k/5+R3L/8z8bv/Uuedk57/CQdmCfeE/2bH3NLeGnaM7PIbHZi5vZWluUcmEfebHBuYq6UlDHb8KoCO/noH7uC41x5mCzt6lU2LPeL1Kx3bd2z2OrrBra1htvxMMi0W5/WrnIOOTN+D+2ytrWzgLnxBDJlGPv72jtPhd5gpxxC2NnAnuLOHI0coyKTRnMLf1nF6JyrlmPMRuD3KxcVj714b3JcZ3HTavrcdz+99geKCtLdDI49F7fV1C4pMDMoQ8snpb+mkeDg777eztkVgo6MphIQkKsHPPVwovJx56S2fC+bi7oTAUPyxBHc8AY9GI/cjjseyuaJs8mnaWzhuBwMhKJmBIWAJwXg/JHI/6jDmBI1MS2PTYnD7Yt7MsbGBObAoEESB/PF498PuBAweHwgxImkxNBrZ5ziZ+AaOjZmV2W6YJSoJOBAjEEvCIN2w/oxIyN8fTySf/Pikt5ePF+4NxmNpZ21jC0MmUUJDISgyOfAQytnJNyUawmTIKjNDwkOIuBDcGziH4bg9ljDrw8lxPB4DivR3RkX5ujKZvraIjOorssGNOe+TbHb6jg7cHhmejgmoaZG2SOvjgqOjfH2ZzOhTvlYwawR5bXN9c3Puo4Iv+Ts4THuPY/ve+yL7TllOTllOXGIxk5lXlBcdGeSMsLOG2Q/ObWxsbM5xLu6Q56ioaGaUL7OJnszLyampq6+/U51/VpEVEYlBotEIhPvevQfWAHTlUpUofGvHyjwqMTrvLLNkvDLjzq1b0haJpF724LvS4PchCtYViXZxxR54r2pjY+3j2Cp5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',
    'strawberry|rainbow_swirl': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////8/o//bq6M/R5uz//4bl37v//wDe27nc2bfl16jb2LHk0rfj0avd0Kzdzarcz6zczKnUz7fZzarczKjay6jbyqfayqfbyafXyqjbzqHZyabZzYjcxqzYx6TXxqPWxaLVwarXxZ3WwZzcx3fXv2nTxafUwp/SwZ7SwJ/SwJzRvpvRvZvSvpDKxa3Lw5rPv5zFv57QvprEvpPQvZvQvZrQvZnNvZvBvY/TvK3QvJnOu5nPu5jXuMPSssHXuKPPuZjMu5nLuJTHupnCupzFtZ7HtZPQt4XRuGbIuJDItI3KsY7FsY3HsYTCu4jBun7BunzCtovDsYzDsIjfrJfOq6zKq6nKqoHFq5zEr4rEronErYnEqoPCrpHDronDrYjCrHzMp7LIo67Kpo3MpH7Eo4HJnH3JmYXJmXLIk3jCkXK90NC/v6C+vaO+vKC+uqC9u6C/u5W9uJ++t5m9tJi+tI++spO/tni9sJu9sJK+r5G9ro+8q5e7q42+r3+/q4e7qIe+rm29q2m8qGCszeGpwtC1uKepusGztae1tpWntLKosLSpqqqsr6GzrZazqIutqWWcvc+Xs8aRsMWXr7+Nr8UL+fqJsMmaq7ORqruMrcKGq8J/qcO4pJq2pYe3pIa5oKiypIewoYilo5Ghnoy3ooK3onOwoH+poHy5m4utm4GzlYy3l3a1kHOgm4mcm4ihmHqhlX+gknqhkmaMpLWIoraFo7iIoLSApLl8pL98ort+oLZ+m7B6o716obt2pMJ3nLeZnJCamoCYmIOVkYuZkHODmqeBlqV/kZ99j514lql4kaJtkaPFhm+8iWu7iWu7hWiziXGxfmKajHieimeWjH+ViXClgGiYgmyShWx/iY+Gf3J5godyi5xvhpZsgZNngpRmf5BlfY5ifY5he4xWfJTDdWuzeFekdluXd2FweXxgeYteeIlceIladodZdIVXc4VWcoRSdITAYVrFQlC4MEepIDl2aIJYcYRTb4FiT2JIDBbGAA0AAOEAAAAAAADd0BgrAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADPJJREFUeNrd2WlQk9caB/Db6jBBhBA0osaBDIiJibWghiUNSILFQFK2WjGABIRAk0tQIYZCbmQRl/EiFgrD2kCAiI1hEUGKLFZWBYUAFfD2ArIMhZFFhmXsJ+/zxt4PYgBt++XeB2ZYhvfn/zznnDfnjX97/dfU3/5HnWP5gX+Fc9TOIdDhTzv2x47Z251YM9H7OPb2DvaHDx/Pzz/1pxx7+0C7w3b2p24BFPjHHQeHE0GH7e01Tn5g4B907B0OB50IdADHIR+p1RKt4wQe44d+hSj2DoG3bmmgD3ccEOW4A2I4BB4PuqWBHPI/1Ak8FhJ6PDDQwSEwEJSgw6e+P/F9fv4Hj+uroBBQNMyp0GCW3d7PaOYMSfTn33+gE6pRYNK/OsGy3mtpbU0g4GwkMRLn6A8clz04dnaH9prisaYE/HZjDAa9N0IULRFZOR35AMfOzubQIZq1CcGUQMbjMRgM1hhneSY8PFJ05ojV/jPv5+jqogxoByiUQxQCHo/D4gg4PJ5IoVqHnw4PDxcKz4SFr+/obkBt2IBC7UAcCpVoSjbBGJsSKAeoBAI+LDzizGmhULhf+B55dPRQunqIQyYD5EjCYAwN9gWzDpg4yaSisCNh4IS9h7NN39IIhdLdQaMwGFTKAYLBNm+WKV8QpGfoJJXKQpe6wyIiIyPXdTZv3moZuYfI9vHn+HOoJFawI0sgYHgHAb3FamF5cXm5O0wcE7OOE6Jvvk+PGiPiujIYzgwq1ZnPF3QJWJYEjKGeLkovdGJpaWm5WyyxWdsJCWHxgxn8vAgnFwaDzeZwYgtUnWpfItUEs22boSFOT2/7AkDSaMkK6S0HpePN8BZ0ClQVkkgul+vD4fizC8puK0gkCsUECxLWdDtesrS0EH5EmkeXrubo6BjiLVmdXeW9vbdFXqAgxR14+qDQmWxujDUxxhApeIVkYnlBGB4h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',
    'berry|vanilla': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////+PU/9T29tnv7tXp6dDj48/h4M/f38jd3czp6cDa5sDe3cTa3rzw9p///wDc27/a2rrb2LnY2LrX17jT17XX1bjU1LfT1LTT07TS1LPS0rbS0rLS0rHU0LXQ0rfR0bHQ0LHNzb7PzbPR06/R0a/Q0K/Pzq3Pz6rP0J7Kz6TOzKzMzKjMzKfKy6rKy6TKzJjbxLjPwqzLyqjKyqDJyafJyJ3Ix6rIx5vHx6zHx5/Hx57HyJzHxaDHxJbGyJ3GxqLGxp3GxpvGxZ/GxZzGwp7GwZHFx5/FxaPFxZzFx5vFxZvFwprExK3Dw63CwrHDxpvExJvDwpzCwpbBwbfBwbLBwa3BwazBwKzCwaLCwJbBwJPAwqzAwLPAwK3AwKvAwKq/v7O/v6rAwKDAwo+8wJTRu6vFvJTBvJa/vJG+vqW+u4y9vai9u5S9u4u9uYu8vKW8u5W8vIu8uYu8uIu8uYq6vaK7u6O6uqG5uaG4uJ26upa4uJe6uoi7uIrerq/OrqbJsp/IrJ/Oo6TOnaLMmaDAtpu8tou/sZy+rJnDppfAoZe+nJG2tqi3t563t5y2tpu2tpK5t426t4i2toC3tJe5tIe4p5W5moyztqS1tZu1tZq1tJq0tZmzs5m0tJezs5extJWyspiwrpqqqqqgrsioqpmztI6ysY6wsI2vro6vroarrYqtrIqrq4qsqoupqo2rqoarq2Wvpo+op4mnpoqjpY+kpH+moYahoIefn5CfnoOpmoeenI+Znp2cnY6cnYybm42ZmZOLmaScnIWamoabmnaZmWaYl3/Lkp/EkpjCipS5lYu8jY+skoumi4iXlYSUlIKUlHuVlHOUkX6RkXmRkXGbjIiPj3ePjnKOjXKNjG+BjZSLi3COjW2Mi22Lim2KiGuJh2qIh2nBhZLBgZK+go+vg4Wfg4KMg2yGhWaEg2WEgmKCgGR/f39ngbWBf2OEgmGDgWCCgFW2e4aydIKXeHpgeKmUaHdBZrVKUo8eOXH/AIAAAAEAAAAAAAAck0CrAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADaJJREFUeNrdmXs023nex3eOItMnzolimpifKY3bVkwOTfWRzEwapU9SxAZlK1vJhsdZklEVJhEddUujbUpEtzyJe3fcaXJo0kYVVU5dqzru1P0y2GN4MGX+6H6z3b9s0M7sP7tvJxJ/fF8+38/3c/v+8pu3/xr95t+U48RA/ys41+AI9PFfzdF3coLBfajHfyUHpv8J3MnJme/t+qs48MNWCGCQaxGf6or+5Rwj07BrYFswdBGPwUH7/0LOfx1xuhZmawQ4CAk/gMHx8f9FnM+chIloMzgcBjeGJDJmICPQ9cM5ZpZOwhRnUzjcBGVi7hwmyZfxGKxjgR/KQTqlpjibWZsgzC0g9LVrTq5XQ65GMY59qD1OiSnOgIBAQJBzIvARjuLpEpIvoUZ9IAdQzFEIGOKovUeSB/a8J+nkSVtyfl4xX/6B+zoM2SKRdgSsg6O1PRZjaYlCIV05vIwCPpXH/ACOjTWORKJ52jnaO+IxjigUCrKwO8MIZETwApmux1jvxwEnbepH0gqLwdha2GDtMBgsyZPEZDICA/wvBVCZB3PgejC9QzADS5oWQ8Ha4+1QNvbY8+fdsNjPfQIYrGB/oAvvYY8BAgbsgWgkAoFEcqfhzCFzM+eUJIJdSPnX/ICAQJ9LF3zegwMZu5oYwOA2NBKd7kY6jzWDEhPRwvZEBNL3yZgiM57DpPJ4UQdyjIxQ5ChbbDg3gZsQ6Y5PSnFObG/3SE6EweBHWra3V5+WFUfESSQHcFKPODubOcv4WeFBQXQ/d0qQUNjR2ZF0Hos8ioDBTG4D0pP4YrmEvD8nJSVJmBImrGD50oOC2OzIyKySjtm5NKI78LWl6VEb0yPQTz8xeel5BYXkvTkw/USv5PbOdvHzgm+yEhJiudwEdu3TBrGLC4lkB6EsIEuHTx3lO2MOLE5h9cWivTj6+iaO55NmZx/39T+KkwKK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',
    'berry|ruby': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX////U///w4+fx09zryNbdxc7qvs/avcnXvcjXu8bJwcnXuMXZtMTTtsLSs8DYrr7Tr73QsL3QrLvLtb/Mr73NrLvGrbe+sLW9rbO1r7TrqbHSqbfPqrnNqrnNqbjNprXMqbjMqLfMp7bMpbPLqLfLprXLpbTKqLbJprTBqLLJpbTJo7K/pK+7qK+6pa66o6y3qq2qqqq2o6WYqbzPm6fKoK/IobDInq7HoLDHn6/Gnq7GnKzEn6/Fna3Em6vFmqrEmqrEmqnEmanDna3DmqrCmqrDmarDmanCmanDmajDmKnDmKjCmKnCmKjCl6jCl6e+oay6oqu6oaq5oqq5oau5oaq5oam5oKq/nqy/nKu7najAmKi7maa3oaq4oKm3n6i3nae3m6a3mKS1m6W0maS0mKSzmaWkmqTSkZ7Gj6DDlqbDkKDBlqa/lqbAk6XAkqTAjZ+9lae9kqW9kKK8jaK8i5+9ip+7ip7mfonUcnvLfovEhJPFeIW9iZ67iJ28h5e+fou/c4G4lKG0laKzlKGylaGyk6C1kZ6xkZ64jZ6zjZq6ip+1iZy6iJ26iJy4iJ66h5y5h5y5hpy6hpq3h5yzh5y5g5a0gpO2fpG1dYOwlKGwkp+wkZ6vkJ2vj52qkpyjkpitj5yvjZutjZqtipipipikipOthpishpOohpSphJKlhpWkhZGjhY+sgJSkgJGmgI2nfIymdoWZj5WbipKah46dhJGYhYyXhIqWhIqcgY2XgYqXgIeZfIeaeYSbc4OSg5CSfYaReoKQd4CPdX6PcX17frNUdseAfIaKc3XKaHPIZG+9bXzBZnTGXmnAXmrAWWW4bHy2aHmka3a0YW+gXWfHU168VWO8T1y7UF6tVHmuTVyqT1euRVWsPEv/AP//AADMAACRbXyMbnqJbXiPaYCJa3eJaneOa3WYZmeIbHeHaXWHaHWHZ3SDaXRXap+LY26FY3GEYW+DYW+DYG6DX22BYW5EYqaKWmVJWI1VTXhOLj8AAQEAAAEAAAAAAACKuhH/AAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADetJREFUeNrd2Ws029naAPCzWiqOO0XOIpqkRQnyYdo0FUlzyEw6TTXFZMLQUKFDSpVEnbpf41aHilKSmApxSVFxadSlxn2Wu5I3rNIPYjFunaEX+qnvzpxvnWA6c76877NWsuRDfnn+ez//vZ/997eP/5342/9RJ/Ybs/+Gc9dCz8zkLzuaISEQi5tOZn/RgRyzMAj5F+uGg91fcnS0Tp751xltu8ogJzu7P+/oWITcDdGBaNlVMmn+ZuZ/0tE2BApKD6KjrccP9qD5O5r/KedEyOjdMyZ6Oto6erAsPt3jmqfd5zsmJ0NGR1hG2jqGMH3TM7E5QkGQ57Xj9M91YCEjIyxTuJE+HAY/E3s3xCEzknudZva5+Zy5CxQYQl/v1AlW/N3Yk9ivqTi/cr739c90UkJMTa30tfUs7UPjWDg3dwoWa+MjFIoC+Z95XVpIa0vT0185o7BwFBaDRFrBLO38g7jlad6B9M9wEBY4MjnM3f486jwRi7WygiGQNm40D1pAkBfd4XejvY+jo6NleItEJpPIzhiMNdLa2R6DxZPdL3vSaR5oKBSNZhzu6Ghoa2hoaZ0KAw7ZHY8i2ltZo85fJFCcnbFOaBrdC2oONXf8A/lo6YOyg8DDSEQimUwJI8DgpsdDU+JINn61mcFeaA9HqJPjH3CQhg4mWhBtZBiZzaaQv3Q5joyPOzv6P7F6luE/Dj0WpQbQ0cxA5qGOvi7iKvP0+ei8grz7uRR8XHxo7MTE7eRYCETHcGh3ePjHqoqA4Cz+Ic6owRmWSWhWII8TEcG+RXFnj05MKaZuu7nAjPW1IYbfDw3vtmRWCLJ8DnZGRuImUuJGa6+FsyMiomNiEosaphVzcW5UlJU10tjY2sIC/ssv3zIzhOXl3+3vQDTjbyZPTU286BP68QoLC/Ly7idI2ppKCRfIX6LgcCQCgTp1Pmt3yI7hXyHx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',
    'berry|ruby_swirl': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////97M/8zw79nl5dHk4dHr29Pe3cvb2sjo6Lf//yXa2bjX2bnW1rnU1bXV1a/U07TS0rPS0rHS0bHR0rLR0bHR0a/ly8vSzLPQ0LDQybLPz6/PyK/OzqzNyqrMzLjMzKnMzKjLy6XKyarJyaLHyqLHyKPHx6PHx6DHx57GxqPGxp/Fxp/Gxp7FxabFxZ7FxZ3lvcvZu7rWucXUuK/OwLTMwKLNt7HNtpfFw6vFw5/FxJ3FwpbGvajGt6bFu4/BwbTCwq3BwqvAwKzDw5/CwZ7BwZfBwJW/v67AvpLAua3AupC8vaq7vKS8vKG5uqG9t6y6tqO2tqe6upu4uJy2tpu3tZq0tJi9vI+9uo69uou8uYy8uYu6uY+8uIu6uI+6t4y5to26toe2tpG2tY7grb7SsLvOrKvNqLjLq7PLprTGr63Fq6vGsZXFq5LGp6DGqIrFpoW+srG9r7K6sbC9ra66raq7sZm8rZ2+r4m+qa65qqm+pa24pam8qJ67p4TJoLLBn6u7oaq5oqq5oaq5oKm4oKm3najEmq3DmanDmai/mqjDl6m6l6TAkabBoYa4oYnDmZe5mYq/n326mXi5mHa8mGy8kqK5lIC5lXK9i6C6ipazs5Wzr5errqSvr5Cyp5eqqqqqpo+lp5WxsIqurYitrIirq4qrqIqqp3ezoZ2ynaGmo5Cpn5Wpo4GsnYKioX+eoJadnpWcnZCWnZ2cnIudnX+zmaWylqGyk6Gxkp+wk52wkZ2uloWwj52tjputi5mxi3uxi2qviWSbmJCYl4+emHmYmHifkIqdjnehiomUlYGSknqQjXSCk6OIinrTgZi7iKC6iJ25h5y5hZy3g5W1hYKqhpSjhZGphnOmf5CjfXWZhY2ZgY2XgnmXfYeXeHCOgHSPdn9/gHtffcCScH6NcHyKb3eKbHiPaX+Ja3eTZ2yHbHSHaHWHZ3R7aXJIbLuFZHGFYW+DYW+DYG6DX21pYYKUWW9QWo0sT5gnIzb/AEB/AAAAAAEAAAAAAACvC85+AAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADT1JREFUeNrdmXtQ02e6x/cM0GQnEBNrkFsghFBjYwIaQW5yT1gtFymJgYBRgcaAXBJYuSlQLnITEY0ZjIUNRTBMylWMXDegVFgMMAO4BqgYyGLkUGFA6Iz81fP+sHtmagNou/+c8x3ml4Hh/fy+z/M+7zV/+vk/oz/9H+U4FsT8JziOh7gx3D/MOXj4MPVQXG7SH+RQD3KpZibn2y9l/CEOlRp7yOQQ9VIfAGX8fg6Xe87pMBXA+trzC2KSfyeHyj3sdC6WCzjUrva8/IKM5N/F4R0WJJzjQRQur6v7cl5+bsbHc3iAwocoXB6Xd86pS6HouJwfU/CxHN5hPqDwuFweD1CcDl+SpWVl5vM+1s+5eIjC41JjY88lODk6UFzsbWmskycufiTnFwqVd97dbT/+AHm/tbU5hcVkBTI/Mq6DsTFchyMuNljrPVg8DoNBoZA2/gFMVpBzoM9HcBwcjpJc7PebW2OtiThrFAqF3o2l+Hj7BAR5+zgb+XwYBw6HIeyJJBLJDo/Dme42xmNxOALJjuTj4+Pt5enp5fUBHLgeTE8PZoBxJUEcApaIRRlj8eQDZDzeEgB8fDwhfYAffUMY8IN2JRGBIztXAhqNRDry3UhYWu2xQC8v7w/kYBA2RgYwmLEryc/PjnQAj0THO2EFQic4knZ/tCYqxN/HKyAwYEcOAoGiBJjjQ8M5EZwwO1u/eEenawK3eCcYDI4YXVmZv1dbFRDEZO7A4SMs8YaOJwMjj9Hpx+h29n4CgVAkdCMSUEZwGAzxV0BqDWExmZTtOXy+kyDBUSDx9/Wj00PDwthnGstF4i9s7UCuMUZIY8Qu9Pxb7wAGi8WibM2B6Tu5xQtvCsoHWYGRHA4nIpzDrrnfUE4A+caiUbvRGOwea+bGKNbfnyX1rdyKo69vZH3ATSRqHh6WB52KCIfEjhx6fP9OyH4CBo3FoAgk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',
    'berry|caramel_swirl': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////5z//wDx7dDq5cbk3rfp2Kfp0qfmz53jzZzmzpnh3rvg2ave2r7T2bvf0KTgzJ/V0MPKzbnhy5vgyprgyZnfyZnUyrDhx5Xex5bdxpbcwpHbxZbbw5LawpHav4zYxJrYwI/Yv47ZvYzXvY3YvYvMxsbTxaXOwKvSw5bSv5HTvY7FxMjDwMPDvsC+vsHCwqHCv5PCvpjCvZbXvIzWvIzWvIvWu4vWvIrWu4rVvIvVu4vVu4nXuo7UuonYtZDMupzOu5DTuovOuY3NtZXGs4/UuYbUtoLVs3jQt4TPtYPMs4LRsIHNsHzOr3fMsHzJr4C9ucC/ubTBvJW+uJq/s6q+r6O+s5nBupHCt47CtIvDsYfDr4fAsIm6ub+6t7y3t7u2tLi0sbawsLa6t6W2tpG1saq1sJ3Zq4TMrXvLrnrLq4HLrXjJrX3KrXnJq3bBrY7ArYTBrIPGrHzDq37Bqn3Qp4PJp4DKoXvHoXfBp4PAp3jCoX/HmoHHmHjElXXEl2/BjnC1ra+wq7KvrLGvqLSwqLGvp7C7rJ6yq567rIu3q4y0p5e6pn2yoZK1o3+1oX67onq0oXq7ona6oXa2oXO3moi3mXizmnG3knmxknG2jnWuq7Guq66uq6ytqbStqq2sqrCqqqqrqK2nqLOtpbKopKmon66loqikn6qenaqrpJ2jn6KinqOqo46in4iqpW+nn36hnaGkm36dm46em3qjl6qhlqmglquik6Sfk6egl5SfmXull3OjkI2ikG+nj2eamKGZmZmZk52al4Caj3WUk5iTkZaUjpiPj5KJkJyMjJHAiGq7h2m6h2mzhm2ygGiwfGCoh4KciHmeimiZh2SfgG6fgWCOiZCKiIuLg4+GhYqCf45tgbOFgYV/f3+BfYN/e4KSgWmRflKwd1egdVuSdWF/d358eH98d397dn56dX15dHx4cnx3cnp2b3pXc7KAbGxza3hya3ZxaXZwaHVTaqR+YWRmZm5NWn0zWKUbL1btAEkAAIAAAAAAAADdgn1AAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADVlJREFUeNrdmWtUk1e6x10L8CSezAImIRQ04dIAQYNFkAw0SrlLEIzcIQHSBIoz4WZAwq0SogSBJjgBhJCeID0cLhYCizgIKhTSIIJOUGxEkMoiKhzuUC7OrHxx9ut0PgwNoNP5cs4/i7XICvuX/3728+z32Zt9b/892vd/lOMj/fzfwfm9KeFzh1/NMfbwIJhGFNJ/JcfW+Kit5WfhjZeYv4pDINDxn+FtmYrGQibjX+cQjvpwPGwJtgxFo7SezvgXOYSjeE4kg0CwtSXIGqXS+p0c7cGhe3Avhn8CMASHOJmsTlorZX445xO6Rz5EsXUIdogLP9/67bfN30iDpR/KCYYocXEODvQ4QOHgmS2RgpLa4A/1E86BKHQHQhw9PJdzCm/v5WZBZseGlXwgB6IEOxAIwSG+gSescCdcMVgzT3Z6um/MB86LQKcH4/FHsJiDqENYDBqNRMLto6ix6VRP39AP4NjhPVxIfq5m2ENYHAaDRCJRaLPDoc6h0dTQUHu70PfjIBAGsFM2rq4un2IxGDQKjTXDYKyIbq6hQM6Ojk7OUXtzEPoIfX2EAfqEC5FIJFkdwpkj0ebYT4muWCuMkzMAOUJ6Dz/7DRFAaHcXHI5IdHO3BoGBn8wOJJp5552lhjqFOjk6Ob0HBwWzNzSAOMSAABKRiIWjOIGH8nkchJHfn378YyYtKso5Ojp6T87+/cjD0ZZWFFYqK5VCsg7MOhnI5ZKTOMAi7IF27UV7HjuaGsPeg5MPO3gSdpJNTQskkwP83EgB+VyeihdgY4U0gkAR365p206ns9meu3OyswO52Z/li0K9A8jkIAqFktFRrVIlWZPMkSYmRkYmBw6gXryJio5lp28j/RMHYcDxS+LxuDV97Oi05ORkFis1qHzgZrXFx0QXcyQgmRxCHWRrf7QPjWJXeKXvxDEwMMTYBKhGetXqXupZ1t+VNjbQ3uZrY2GCMkcjrYjY8owHay+OhUbFpgt1c8AaGaGwODdJT2dfX09HHis1NRU4Ciq/1z4w0BGLRtq4WBPdJJUVpWtamaNT6DGqTg4MZohGW33s/my2pxO8enoygoIC/CipySntA52dPfduVpMtjuPSZySijB+1b75wBnmkgwPfD0eboMysM2f/MnsP4nR2Xg3Mzs4uUKlUIxJA7elUz4q8fNmSZ8KK8jfaB56xzro4/wHq2QyO7p+dnR1o7+lpbx/oGx0dffz68Z8LCgpyKELI4cuXvVE04bNn/Wka7Z9oVGqsDg7uOO7jg56d92ZnQViBBjpyuAVJJEtLS6MjlfYguf/Yox4bu3c1KrNSMlNZPnA2lhoVrYPj9pEF6SqIwkvwxwDU6WlkfsHeAPGf+vr6djngF/hHHffG7nXcjKJSac/6M/PEQjZNl5+3B4B1yA4UnZ4eTwMD+xwrwAGyDDI3NLSySenpFFrHtHl6x4pmHuVWVorS2bo45eo+EJWXs2NqCAMzQmCTcYYgFQxRaCQcjf6d9Wlxh4Wrhbc7jhYrGa2mxmRm6s6f3t5OsMBjYwB0E4PFIME+aoJCIAwBxfLAAVdyRmVlprW5iQ3R7XDp6ONcNpvG1p2HHZ03fTtujkEz8zuBgcHhJmZohBGOZO3ZrlCknKkQV1zzhqHtLEnHj0lGhTQ2LWaHumgvPegFw+Se7uhwcSV5e1u5gzJNTkvD6/3P2tqFoIr+apEw8MsIOys3q9JH6THCzJ3qi4bJlFTnXbBw9wpgpa6tGeuZprFYlDTTffprLyAOjTYywjsfDkBHREKasKJyB85B6xiRqPrrRxJxnn/bmlZvHz6NAnHiXmjfcbwRX6t4+cV4S5LN2fJ0oUgn56iegfXpdFoMjUZjizL9H6xp4789C8o0xX9Qq9WupUAc00jVCO9ihJ2lGerCtUrdnLjf6O//UiKRVIuqc4V5EEe7lnEG4jyAOG3+Ff2ejmFfq1S83PP5J2HYSt2cy7am+/cf+Oij0xWV1WKx6N3gFxcAh3WmDOI88K/sb6s9X12tqgH7XD4afviaSKSDE38Ugf8Gb2pqB4PBbCwC/sHJYAWxKJC1QchPwrlSpzJ+iyqfy0HC88RiHZzg3yLCv6lvbKxnMELwhp7/4PgHZZzJffHgYSYUn8OIEEFUAp9f8+d87km4ubhfB4dgalgnLWReYjKYjETmef+Ha2trLzIyJt786J9xxt//TCoL+DEwKCk9lghAYGaGhkd07PNN4Qh8fW08g1EorU1MSIg5k3EBiJWp1Wr8M1JTUigUv8x+Ibt8QBAaXXu9ZeRLUwRivw5OPdcIXy8tjGdKpdLEREEOhZWcnJYclKF9U+YXQPZzd/fjZInEErW89Vx0KZ/PDMEDEOyXnOIC80tSaV19IYORKCj+KotymvwpCWuC9vTzI/uRs/Pz87OS2ML09EjQ29GK44PjQvDAEGw7h3+R49HcWB9fV8hgVl0EX3/Cj2yGwrofP5WWA+ROcidZeEYdk8xIygpLStkl8XR6iCnCwG475wrvZIJCDiBgWmVlIBoUCisH2uN5+RAHNAtEt9PUq69ezT592iZgixoYdDreVDC9nXMx/1CzXMZgMOv+q6RMkAIeXDkFI49HVCMFQWQgEs6FiPVOVz99p6rS6io+nVA7MT25jaPKzjrUKgepU1gnbSkT8FTQwwY8J1JTA2xwQOYosKkd7n0FIH19anVZVW4i/7uffrq/Pc4j5y0jFbK6n6clGIE4BaBPIEL92IkTRDQKhYIf6X/16p0fdZ8gLPrlX/53eGI7h+eDFcha66T1suYWQZkgjfUHFouMwRxCIzEkKwzoD4FQZ8U/c/rUbY5tP01ODG7Pn5FsDy+FQl4nbZbLwbSukkF/6Yp716CC8Uik0Wec33M4OaI+yIxa3dfXF/K9ZmL8F/2PyseydGhI0Sqrr288l3jzqR/oCl1Aq4vBumKQZmZmmHyoxPv7xeqXEEetfto2Pjmho4/yQd8dUsrlMqn0UkhI31Mv3Meu7uRTpwJS8lKsz16rCEy6Jr6AK+/tBxKXA3W0/KC7Dyc1dimam+XNjbUJIR3qgNS8jKAKsTi5QiJmZeTlsWwsDloTwT4pLL9WTqPSaL7f73QuaBlSyOSyQmlIQkJYr/ip+CzOLyCNBRX6GdDceXkDubu7et29e7NcLKTR9jhffPP2XOK5sLC+XgsLC5uTFFZMcXHx+YiIiEgfHx8PDMYcrVA2t7a1lUve65yS0NEeIShOLCq6wr9+/folwPGwA0KhzLGtssZmWX1t63tw+PH8hlvdd7qv84GKiooSIY6lvYcPKDGvVuhk2cz8PCRkT05TQ0MT/wpkpqGp4Z2f4ohI76ysJJy19RG5TNYsldaC1XB0NN2dc6frTlfD5cv87lu3bze1VFVV1UBVz+VykzicLKUSOuuCLfNcaaSp466crluA09TU9OQRaOugeq2pqQFPLRWPy83PUg4CQ411YMssLXV22pNzG+j1z6ppKSup4laLct1/d/yIUqlUQOlaci4sMjpqD07X7dG/6wnQdy3QuqfH+PqSSK5e4+NDQ0pF43+3CL6I/Of255fxudV9exT4AJa6u7ubmmohjjdIIFD4h58D/TAkk41VfVXqTN2VA8UXstLVdedOU1ERPzE8PNzDEuSPCQqJHn/+cmpmZuzJzAzghO7KefL49ShkpQvEuoHPbwjHAwGMIRwOx86+nAEamylr+6rUaXfO4yeQl64uwLgMMrHhUnh4MfDjkxUYkMWdmbn7w9iM7G6ZICxs24nwF/MCAnPqAsnccKWIf72spmb0MY+nGuHmJGUpx+U3QD3LWsrCwvaIM7TuXV03wKyaupvir1x/8np0dARKHi+c1ZEhpUyuBJxzJWFhe8QZ4hRduXLlzndgglVQIvJGuJykpKQDsANmz58rlWDHkyUmhIXtER+IA6x0jYLFfwShIiKKfXzP+3h8VSYoBtkja5TLW9+Dc+fWnW7Iyne3bt3qBnUvv3u3pWSQLp+YmpwfukwnOBAaZbISMC/q7vMCw2+/nnn9WPl8fGhCMz09NzenVChuLG+trm9tLmuGlAyHy3JBSdgXe8R5CHgfrlfcGF+YW11ZWN1cX9/8K9DW5tbWxurC4srUBFNfT8/Y+Le+O3OmmIUPJyeXxmU35pdX18HIra3Njc2N9eXl5Q2gza2Nzc3NpcVp5SCBHlx8dWc/zbKpuenFdfDV62AENGp9ZXFxcX5+fmFxcWF5dWFpfWsdfLy6Oj3eepQZT9hlfx4fnNNMTM2tQHYAZwmCLCxAP0CL6+urGxurK5oFzfSNT4JtbXfZ5x0cxofGpxdWV1fAkPWVheWl+aXlZWBobn5+eXlpStZ4+TK4ByQYG+vt2/W+xTh4YmNIqdGsvovt+tbGikazsDw1NXwfvIaHB5uD6+6DJyF9amJcMTk5PPl2+OHO91r1rRNzmvn5ac0w6KrphOD6h0DDw+PjDyc1S1P3B6eWljSLKyvz83vdj33PlL81NrY11tPT1wNv709MTU9PAM60Zk4zB9b2Q+9p6Q8Hh+9PTs9pFhaXVn7FvfHkxOTcyvzc/9f/F+ylvwEvQQXu0NRmpQAAAABJRU5ErkJggg==',
    'berry|matcha': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////+Dt+8nZ98Xe6r/b4sfT4LXT3rfQ3bHQ2rP3+pX//wDO3qrN26zO2qjJ26PM16nJ16nI1qbH1aTF1p/F1KLE06HE0qXD0aHC0aDC0Z/B0J/C0Z7B0J7DzazAzZ/E0JvA0JzAz53Az5zAzp2/z5u/zpu/zJu9zpu9zZq8zJm7zZS6y5W4zI+6ypm5ypS4ypS4yZG3yZC1yYy9xqO5xZy2yJC2xZS1x5C0yI20xY+zxo2zxoyzx4mzxYuxxI+yxYuxxYuyxIuyxYqxxIqwxIqxw4qxxImwxImww4mww4S8wK66waa4wKG2v5+2wZq1v5u0v5mzv5m1vp6zvpmzvpizvpeyvpezvZmyvZexvZiyuKC2wZCxwI6vwYiuwImuwX6xvJawu5SvvJCuupK0tY6q4pStwYGswIaswH6rv4Orv3iqvoOpvXqtu46tuY6pu4OpuYanvH2mu3ynvHimunqst5Crt42qtoyqt4uptoqotoqotYqntYmntIqptoantoSntIintIams4ems4Olun2lunulunqkuXqjuXqktoqjtn+kt3ultIOkuXmjuHmkuXijuW+ktnmhtn+it3iht3ShtmigtW+cvn+etGyC5YIA/wCksZCksYaksoSjsISisICfsH+erX6qqqqkqYidqYGaqX2apICYo36Yn4afsHmdrnmbq3maqniZqHiXpHqcsW6brXKZqXKbsWKXrWGjrFKUpoCUpXCVqWWRo2yUrFWTqleRqViRp1eVn4CVnYGTnH+Sm32SnXeRoWuNn4CMnmiNoV6Opk+NpkiLo0+IoUqIoUOFnUeDnFJzoUmSmX+PmHqOmHaMlXSJlnWKk3GHkW+OmGWHl2KFlV6FkGqCj2eDjmh8lo5ql3J7jXyAjmN+i2N9i2GAmTx/lkZ4lTl6j0hzjzF5iHR9iWJ8iWF6iF96h154hV54hlt1hFl4h051g1ZzglZwhTx/f39ffrpzgFhyf01nfDlJbsBVa2E2WJ0gOGcBAAAAAAEAAAAAAADnrBDtAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADdBJREFUeNrdmWtQGta2x3syhtAZqfGFoiGJJlo1NL4FFQkJNIj1xTmioTdiJMzIQaIVrK9SKlIinVgxFXUyc+ODVI34iuIc1KvxVcWomaijY1DniEQdH1Gjx0SH+yF3k94vtahJe77c++cDjxl+rLX22nv/9+ajt/8effR/lJNI9fl3cIrPfnzm9J/mmNy4ceJsXLjPn+RAIacsbyReYUb4/ikOFOL2WaI39NOy5Ahfnz/OgVklFofATkAuljGp8WdC/yAHahVUnOgGg0KhJ/lpFGp8WOgf4jjdUCu9zGEwKOykrVAQQ6FG+344x9w5RN0SZAmFWdiZ2wQVZwsEyVSaTdSHchAh7f9FskZYmNvZIrzvFgf5fhf3HTPa5kPj8S5uJ9nYIs1PIs/hipV3XT0uB3vHib6NZn4gRxlkY2NnDoXZuvw9leyHIRLc3V2ui0SlScIPzAvi4GwLd8F5olD2bh6oc452CLhvfHKWKBmdFPMBHIezfng8mejq4eYRiHK3QyCQDq5oKoXKSI6K9rWhvR8HCoNYsnB4PI4AwnF2cPJ0Rbn74Yn46BgqhRIaFhkRczQHZgI1MYFAHMmAgyf6uQW62jm5eeADCV5+FyMpVFpUKFDYe8QDAdWFQZFkHBYLQHR/hJ2NTUhLKs41SfFVMiWSEh72t7D34DiY+dpAoFAnMp7NJuJxHpbI4lSUergYZnt1draqPIURE8lMYh7J+eQTJJrh6smVSCXS20RMqjLk7uDgrXvFUAjMbHZvb+cXRRkjXSg8gtNu5h1kThIlFXHZbA6LSOSoB4dHhm9hPG2tT0Khlg9m9/Q1KfdzhNcP57S33x1UJqprr8WxWWye+PZtaeOATleEIbnZnXO0hJ+zsrLf0UczM0Q/itAHcyAQZcK94eHhgYn7SUVSab5EIuU1dvW2+oN6u9nbOSAd3OzdhfrZT7+ML62L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',
    'berry|mint': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////9T84Ofl5+ra19y54vK61ObMztW1z+OvzeDMyMvIxcnIwcfEwMWxyt21xdS8v8iqx9uow9eiwtmiv9SfvtScwNbAur+9uL28usC5ub+7tbu3tLq2tLe1s7asu8irt8Wjucmus7uks8KevdOevNKdvdGdvNKcu9Gcu9CcutCbu9GautCcuM6ZuM6XuM6cs8WYs8aurcexq7SxrLOvqLOtp7OwrrGvqLKvrK+uq66tq66tqq2sqq2qqqqsqKymrsClrrWfrsClqrSgqbmeqbuasMKXr8GZr76arb2YqbuYqLyrpa2soq6mpKyloqeonqyjn6SinqOapLKboLGfoaeXoKqgnqOgnKKcnaarmKull6mjlKail6ihlaihlKecl6ecl5+Zl5qdkqaYkZ6Yj5yUuc+UtsyUtcuPvM4A//+QtMuTssiQs8mOssiMssiKsciRr8WNsMeMsMeMr8aLsMeLr8aLr8WKr8aQrceLrsWKrsWKrcSTrcCTq72Nq76JrcWIq8OFq8J+qr+Qqb2RqLmNp7uSo7eMpLqPo7OFp8OIpruIpLqJoreGormHobOBqMB+pr19pL17pL5+o7l7o719ort6or16orx6ort6obt5orx5obx3obyNn7+Rn6yGn7mGn7GKm7qIlrWNl6OBnrqBnrCAnLV/l7aAlqeTkpaTj5WFkqGHkZp+kqt9kJ59j5yRjZaOjY6OiZKIiZl+jKGGhpN4oLx5oLh6mrF5l7F5l6t2nbhwm7Nzl7F6k7lxlLl5lKhxkqZ5jrZ1jrZ4j6R6jpx1i7JziK51iZtwjLRojb1rh7VvjaVqjKJoh5yOgpCFgoeDgIWCfIR/fKd/f39/eH+AeH55hJ9vhJl0fpN9eH98d396d39qhK5og65of6thgLZhfqtberdsgpVmgZVkfJFleZRdeJh7dn56dX15dHt4cnx2cXl1bnltcINdc5hQcrNWcZR0anhxaXZwaHVoZnNOaZtcW3k8XqYyUJMaJD2QAGAAAP8AAAAAAAD9Oj0OAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADbBJREFUeNrdmXs02+m6x/faoxoURdKa0miEyrhFt6JCl0uQrVPi0krO2NiKxlouGUJOiEtkq6JNk1KttkqVRKMqynSlmkyjqEtUNazd47bFxP1Sdd1G/+l50zn7j+kJ2pn9zzlfy2Vlrfezvs/zPs/7Pr+fP3z49+gP/0c5aRijfwcnTXefkfbv5uy1sdPcj3Uy/J0czb379yNs3PFO8N/F0dI0NrEx0YRHApDxb+fs+9qzHKmlqXk40h/jZnT4N3K09v+p3NtYW1NLUzsQ74xxgx/+TZxDnu33TLW1gLQNCYSTzi7O8C/naBsjJffdDwLG19qG7uWEoCA8BmPo8qUcw48UQ21tQ0ND02/LEfCQUxX+Lge/1M+fyu+7Gxoe0tY2MnK/V16IiE9nfJ/DZnlhv5ADKMCMpvbXprmFjAQKgxYba53EZrPzWF8Yl6aR8SETREo8mmSBjiWhUGZmMDtcLoudh8vDfQEHYXIsJYVBQ5PQscmkWDMzMwsLdDzOB5eV64Ozg+I+j6OjAzFgptJoKf8ZRyJZW1jF2ZJICVQ6FYfD+fggkT4+n8HR2aOxZw8EcpRBoVKp9AR0sq2ZFTqOlkpLSIgFABzgIJGen+EHoqehowcxZ1AogERnJJodhUHTJIWp6Gwe64IPENLHDrk7x8rgmD4EomPFoHI4dGpqHNSCW4iWSAv1YNlSxVNeXibOJzc3a1eOnp5ZfJYlqai0rLSshJ5YyE0rbG8v5BZqQDT0W7ZWJrp4lVl5LNYuHIkBKd4gjZUt5jCZHCadzpG0S8ekhakJMKieBkSf0bKy9TS/ksVK2pkjkRS2cXMkzbgMDpNTVFJS8oTfKVdcJ9PRZlYoKNQKCrWY2MTl5oN6TNqeA1Hn5nClY+1dQ+xscdmdstLSW8XPHz5+SqZQU9DmZiiUBdriGOu9HIHLZIvSedtx1NX1Y1ML5WMv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',
    'berry|lemon': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////8n09Mzs68/n5MLh4sLh4bTg3sPd3czY1sT//43//wDf3qnZ2anX16fZ2KHW1qXV1aPV1aLT1KPU1KHU06DS06DU1JrPzNTNy77Pz63Kya7S0p/OzqPLyqPS0ZzQ0JvQz5nPzpjOzZjNzJfKyZjPzZPNy5PMypLLyZLKyJLKyI/Jx5DMyo7Kx43Jx47Jx43Ix47LyIvNynnIxM7JxcLGwcfCwL/CvsLGxaXCwp7BwKjHxpTIxo7FxZfFw5XCwpvCwZnCwJXJxozIxozIxYvHxYzFxIzEwovGwYvGw4fDwYbIw3vIwm/Dv4DBv4HAvIHCvXPDvVy/vbu+ub2+v5q+up6+vpO/vIS9uoa/vH6/u3y+u32+u3y9un2+u3u+unG8uca8uq68vJa7u5y8u4m8uXq5uay6uZG6uYe4uJKruqe6tsC4tri1s7i3tbC0sbKysLG6taC3tqO3tpK4tZa0tJ62sp2ysZq2rL6wqrewq7KvqrOvqLO1oMCuprOwrK+urK6uq66vrKyvrJ2tqa6up6Csqq2qqqqrqK2grsiqqZuqpa2ppp2mpKOloainnrCkoKGhn6Shn5+an52knKqgnaGjl66il6ihlauhlaSemp+cl56ZmJuMmJ+3t4q2toq5t4G2toC3tIK0tIi0s3+ysISysHyvroGtq3+urHmpqYK6tm+7tWK4sWazsG+xrW6xqmWrqXC7tFK3sFCvq1W3r0azq0W0rDuppnqmpX6loniioHafoIWgn3yenoOdnX+gmHeamn2XlnSrpWCloWKupkWoo0qdm2ihm1SdllyupkCtpD6sojqjmTugmC2glKeblKCljqaYkJ+VkZuTkpSTjJeXk3aSkXWQjYaWkliZkjqTjkKNi46LiI2Jg4yDh41xhaeKiHGDf4R/f3+KiF+KhjyBfYN+eYF9d4B9dYF7dn56dH5Zdrx6dnx5dHx4cnx2cXp5dGB0bHhya3ZxaXZwaHVKa7FqZXA8XqY5UooiKEW/AP8AAFAAAAAAAACnIZZCAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADaFJREFUeNrdmXs0G9i+x3tmrIxZy7vJVIlXvBuGMRklHqWTYoipKtIJDfVI015JaWhdZdGgxkQbTY94FGGokIjWKx5HREWJqaiu4nY8oh0XMaoYjx79p3envfesNSZoz5x/zv1mZS3+2J/13b/fb+/92zv73vxrtO/flOOfRf5XcAINULGH/zRH90ssyjAhmfwnOShdff0v/aNz4+P+FAelSz7kj0RRbjPi48j/PAd1MiDQ9ysU4OTSssnkf5KDOvx1YMAFFMoR5chkpNOyd3K0B4f8jYAfcsYRUBxjmczsq7R0yodzzpC/aeZfPIP6yinI6UxIxE0mk5FFC8r4UE7sN02AEuvkFBQbezEi0CHuemJSJi3oQ/2E8JsAJcjJEVDqAv2dzd0wtj7lCdRLH8jhR585E+SI+ioo8tQJB8tD9g5mpkbu5exyHPsD56UbSz6p72xjZmKy39gMAYdpa2sZBuPY5SR3nMcHcAz1PWxsHByMLEzMkAhTHW1tKMzI3MPDIwqH9jTUCn4/DgQCUff93M7exs0SAazAzYwQCCs7jJ2np4cH2sUFjfbcmwP5CPLRRxDIZ142dnZ2GEtjpLEO3NjMzcbe0tIUjfbw9HCJdNF3eQ8/EHVgBwL1skEiAeiYlbaOlroDH2tj5MM5hQMkFxcX5/fgwNTMNQAH7mXn54exszFTh/H9Ec1t/hAt79FnvMqYKE90FA63J0dNTcc8ysAsIIwQRsBjrE/wsSfaBNgIf4BWK9taei68UxVMYrP34DSp2TqoO7BxxOO+fn6+X2P8BG2tD1uxh8y0NdRA7P+jbGmLHlPFZrvvzmlqOiHgYwWcYG8/X78APB5P6OgdlJ6wxoBYwzQ04Jqa0OevPHGkcnaV+84ciEqgb0Trw7YWcTmOSAg/HRZG+LZ9tKvBytbOzhiqA4PCjPebsV8/Nw4OruIeqdqJo6Ki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',
    'berry|salted': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////6rq5+nd297a1NvU0tXPzdHMys/LydDLyMzIyMjLxszJxsrIxcrGw8fGwsfDwcjDvcbDv8PDvb/Avse/v7+/u8G+usK+ur66u83At7+9ub68ub68uL68uL28tb27uMC7uL27t727t7y7tr26t766tr26try6trq6tbu5t8e5tb25tru4tLy3tri2tbe1tLa3s764s7q1s7a3srqzscK1sbazsbTArMG1sLe1r7i0rrazrrazrLayr7iyrLWxrrGyq7WxqrSxqLOwrrKwq7OwqrSwqbWwqbSwqbOwp7OvrbWvrK+vrK6vqbSvqrCvqLSvqLOvqLKvp7KtrcWurLStqbaura6uq66tq66tqq6uq62uqq2tqq2tqqysqq2sqaytqLaup7OuqLKup7Ktp7Ktp6+tprOtprGtpLCqqsOqqqqpqcVsx9qnqMWqqLerqKuqp6upp6qnpbqqpa+ppaunpauopamnpKiooq+mo6iqoK6noauiobyfob2koaumoqWkoaakoKSjo6OjoKWioKWXmr6cnLiWmLiamrepn66onq2em7CmnqqnnKummKminqegmaijn6Oin6OinqOhn6OhnqShnqOhnqKhnaOgnqKgnaKfnaGgnKOfnKGem6GfmqCdm5+cmZ+ZmZmcmJ+ll6ijlqqil6milqmilaihlqmhlamhlaihlaeglaiflamalrCdlqCblp+Zlp2hlKiglKigk6eflKigk6WdlKmZlJ2ikaSckqaYkpyaj6KUl7eUlK2Wk56WkZ2WlJeVkpaTkpKVkKCVjaKUj5eTjZePkKWQj5WRkJGPjo+QjJiOjY+OjY6JjaqNjI+Mi42ahp6NhZKLiY6LhY+JiaGJiY+Jg46GiKuGhY2FgoaFfYp9hbRofryBg5mAf45/fIyCf4N/f3+AfIJ+eoB/d4F8d397dn57dX56dX54dXx4c3t4cnt1cX5Yc7R0bHlya3ZxaXZwaHVYapt0Y3hmZm4/YKZAVIMeLU/lAOUAAP8AAAAAAADOQ/QEAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADb1JREFUeNrd2XtU0mneAPA9mZpH0ZHZRRzDLUypTC1DOYImUjk0L4OgTi/bDDvmkKLHg5c0FNSkpY3E1F5qmBlGKtcLljnmJS9HhEDLKyocGbPwkh4UM1kvdV77p/ehM+c9ZxvU2tl/dr8d/nw+fZ/n+f6em79786+J3/2bOu5fHfhXOO47oP7Q3+zY7nB32oEmef1Gx8H2I8cdtruy8Zjf5EAcvHfs2GEffAtA/v+8A3Xd7/6Rg7PD4VtsWtzegH/Scf49xH2/D9TJycFZlE2ixW2U0RbOLndW0C64s5MjBOolEp8i0UjBH+7A97inJB+CO0OgHh977trPk4izaTR41Ic6Hu6xyYc890GhSC+vXe7uEMy3WfwMGvxD89kfBBQvBNQFhTgU6x7kExHDiMiSiEgZH+gAxXPnR04uMPTJk2RcApOCw/pGSSQ3sq9/YL/svXw93PzIoWjsvhAcFoVC7IQHx7H5Ug7pHO0DHJ9d4VQqkxGIQ2MJIVgEYidyT+BxGomWzqadwsBPvZ8DgTi4ZpKpVDI1NATru2cfzg+LDacyYminaCTSYQwJ/x4OxMbRZru9PZIJHCojHE0MRPigQxkx1NDQkGMkGp0WEHDYH/Me+di7OEGcHRBMcmQklRrDDN+N9PQ4lHyaGpjVUJBNIn2OxxzDvIezB4r5g72D0x5mvFDIoMaEeiJjg7xTWEEubmljU6qbBel0PJudsaUDhSKiMgLDqpuam5pl8YTU2KAgFutkapCjA+TjyfXlqbGKG2mcb0VbOCkf7ToEP3KR01rM5RZz4xmFrJR8Qf7JmAhPmIuTAzR/cnm9r+CGWLTFOMfGHkmJDUpp+HOSkMutrpbJWssvCRQ50TGBCBQKBkN9/LH38qsv2TxJmTRqY8fRNjYxlXWJVWT4Pqv1/v3mptpamXzgQRHhUyo50BuB8vJGewd/uz55kJ5W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',
    'berry|rainbow_swirl': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////8/o//bl7N7b4NH8+pXh3br//1X//wDe2rfm16Xb2Lbb2K/k0rbh0Krdzqvcz6zczKnTz7jZzKrfzqjby6jbyqfayqfVyqjZyafdzqLayabZzYjcxq3Yx6TXxqPWxqPWxKHVwarXxZ3WwZzcx3fXv2nTxajUw6DUwp/SwZ7SwJ/SwJzRvpvRvZvSvpHKxa7MxJvOwJ3EwJ7QvpvEvpDQvZvQvZrPvZrQvZjIvZvBvY7Tu7DSvJnPvJnOu5nUtcTXtqvQu5jOupfMu5nMuZbIuprDu5zFtpzHtpTMuJLKtpLPuX3RuWXPs47QtH7Js4nBvIbBun7BunzEtI3FsYzmrI7Rrp/NrKXGrpbGr4fErpjEr4rErobCrpDCrorCrn3Cq4bMqLfIpbXKppvOqIXNpH/EpYLJnYzGnn3Km3PGlnXEkXK90te/v5+/vqG+vaS+vJq+u5+9u5+/upO9uKC+t5m9tJi+tI++spS/tni8sJu9sJK+r5G9ro+8rJS9rI2+rYi8q4y8qYi+r3K+rGy9qmeszeGpwtC1uKepusK2tpyptbKnsbWpq6qqsKeyrpmoq52tqWqcvc+Xs8aRsMWXr7+Nr8UL+fqJsMmXq7iMrcKGq8J+qsS5pJy5oKq5poi1pYeypIixoYelo5Ohnom4pIK4n4K4o2yyooGvnn+poHy5m4asnH+wlpq0l3y3l3W2kHOhm46cnIqhmnycmoGhlH6hkmeOpLOIo7aPn6ebm4WCpLmDn7KPlaqWlZOClKOZmYOZmH2Yknh8pL57orx3pMJ7obl4obx5m7R4l6h8kaFykqbDiWy8iWu7iGqxjX23h2q3g2evfWKWjYeYjXafjGmWinKig26lfmOYg2qKioiRhWyHgHR1jKB1hpZth5hrgpNpgJdlg5plfo9afqK0eFete1+ed1+PeV1jfJFie4xneYdaea1geotdeIpeeIlcdodYdIaDcWhXcoVWcoRQcJxRb4B1ZnhCZKdLUogbNGXGAA0AAOEAAAAAAACe+EpCAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADPZJREFUeNrdmWtQk2cWx9vqZAZDQ6IbIuIAWRADJlsLaAAlUm4tpERuGV03GsEGGpNdbhoMhRTCzQsqFgqDwZYQLgu7kZsgAZEAQiRhYU2lIHUDtFkNUiAw0E52P7jnTbszuzaAbvfL7p93gGTm/fE/5znPeU5eXnv+39Fr/6Mcxuen/hsczjv+p/x/Nsf/yBH/gx98HvczOf7+B/3fcTn6+XqhvfYymFPv+EFcNwF06j/n+Md9wDni72/mrA16bUPKEc4Hp/wR3URAa8W2ASfuCO/Do2aKf9x/zAEvPO7ROIThH3f0w5s3EVLc56/KiTvCBQpg4uKAwnnn1M3ffPbZWou/NufohwjFjAEK4+CeQzSXYFHGe5+9IudHCmB+zfDZ4+XjQyTZeYgyRaEZrxgXEs/Bg/v3OBLxTiQnOwIOZ+ORmpYhSvN9L+UVOL88uH//fh8fB6IjiUIk4nA4PMHeIzUlRZCWmuK5PfXlOGg0ChvoRaXup7oRnezx9m72RKI7leaTgigpKTUxZWMOepPV6ygUajsNOFSauyPFAUdwJHl70dzcSIk/cJL2Jr2EH5S1FRpttT3Ai0IBUCAZEoP1i2d4OYTmxKSlpCKcxJfg2GI8tqKs0NsDqHQ6jepFwuI5DEcen4O2Ce6ZkonPCVISBQLBhpw338R5CHZ7MFlsFptJIzPi/Rh8HoPDsbJCY+6a5udbcsSCtMzMDTg8jIuftV9m2vGYsDB6MI1G5/H4I3yGlxsOa422wlxQzJuqY0SZGUHrc+K5DF48g1eZEkKnhzFB2TWNo9pj7jQHnK0tFmuL2YL/63fJAmGmSOS7NgeF4oRx4M83tYsEscePs1gQmay1vY5MplId8ECyddrmnGHSvZ2aIpIGidfioFBYkgdjdLR9bOyWkMkyixk78bC1OpTiQsA7EHDuVJIsW2ka9kxJEYorLXOwKCss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',
    'love|vanilla': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////+PU/9T29tnt7tXp6dDj48/h4M/f38jd3czp6cDa5sDe3cTa3rv5/5jZ3rD//wDb27/b2bzY2LrW17rW1rTS17TX1brU1LfT1LTT07TS1LPS0rbS0rLS0rHW0LjS0bLR07LR0bPQ0LHNzb7PzbPR06/R0a/Q0K/Pz63P0KrMzanMz6DOzKzMzKnMzKfKzKrKy6TKzJjbxLjPwqzKyqTLx6bJyafJyJ/IyKTIxqTHyKvHx5/HyZ7Hx57Hx53Hxp7Hw5/GyJ3GxqLGxp3GxpvGxZ3GxJzGwpzFx53FxaTFxZzFxZvFw53ExLHDxafDw7HDw6jCwrLDxpnExJvDw5vCwpbBwbfBwbLDwa3BwazBwK3CwaLCwJbBwJO/xK3AwLPAwKzAwKvAwKq/v7O/v6q/wKDAwo++wZO6wI7Pu6vBvZy/vJK+vqq+vZm+vI29vai9u5W9u4y9uYy8vKW8u5a8u4u8uYu8uIu8uoq6vaK7u6O6uqO6up+5uaG4uJ27u466uZG5uJW7uIq6uofhrbHRravMq6TOnqXMmaHDtJvGrp3EppnDn5i6tqG3t529to24tpW8t4q7tYq5toe7sZi6qJS8npG6mY21uJu2tqe2tpu1tpq1tJ21tZq0tJm2tpK2toO0s5WztJWxs5KxsJuwr5OxsJCur46uq5OqqqqqqpSwroqsrYmrq4mtrYWtq2+up4ypqYyoqImnp4uto4ulpIejo42goZCjpH6ioX2enpCfnoKpmoeenI+dnJCdnYScnI2cnISbm4qamomZmY2YmH6ZmWjLk5/Ek5rIjZvBi5S5lI27j5K+iZKclYKVlXyljYibjYqUk3+TknWRkXaRkHaQj3OOjnSOjW+Mi3OMjG+Ni2yMi26Li22Lim6KiWuJiGqIh2vGg5jAhJK9g5Czg4mkg4OUgXeHhWeGhGR/f3+EgmaEg2KCgGOEgmGDgWCCgFXZeKvAeZK1d4Sqdn+MeXDSZqW0aYe6UpCWXnNyNFn/AIAAAAEAAAAAAAAHmIhsAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADb1JREFUeNrdmXtU0um6x/esUpkOrhZeSika3IaKJuZS9qYjKBmihWOrSTEpKXHQtAw2kmhe2I0loKYeNdGN8ivL21JwpeUFNfOS2/uQd8fchoe8re3kcTLTf+a8NOef06DWzP7nnIeFrKXr9+H7fH/P73mf9/UPP/9r4g//RzkuLMy/gnMbjsAc/t0cAxcXGPyboMO/kwMz+Aru4uKa4Of3uzjwPdYmQJBbaUKQH+a3c4z3R6aAtGCY0ngWFxP4Gzn/ZuqSEmlnDDgIWQKDFeUX+Js4aBdJCmYfHA6Dm1rJZKEMFsPv8zn7AEXsagaHmyBND7imyCB5Aot9kPG5HEsXsdh1n40Z4oCVFeb2bRe3wisyPuvg5+pxSQEUK5QJwgrtKgIeOdN8Cdcg2Rn+Z3LErgcOIBEwhIX98dTj+JO+FCcn7BlI/iBR/pl57UHbWVpi3Z0dnGwcnHFoNBJp6RYVnwklnokP/QyOrQ2eQvH3xTrZOxFxTkgkEnUIe4zFYPETGKFuFuxP44A7bUqnUChkCh7nYHfI1hmLw+EpvpRQNovBCLx0Pih0Zw58F2zXbpgh2p8MQDS8IxGLtHV09jrphcfj/BhsdkggiHOfoMcQAQN6UP5kd3cKhep/7IDVgX2uolR37BVFccLFi+fPXTrn9wkctKnbfkMY3NafwmR6UU4670OJUjCS7hSEeVhp6UBfEfdiUHw8f0eOsTHyNN8OzxEkC5J5VFKqyDWlu9snLQUGg1twC7Qbm+97MpIKC3fgiE1cXfe5FiXmXg0Ovkqn0oIlkt7B3iuezpYWCBhs/1HR+sbG+np3wZntOWKxSCKKlJSzv2YGB3N4PF5OZY9Wm0qiAq/RZha2lubInwCou6AYOr01B2Yg8knr7euWdkE3cpOTYwWCWN6j1qdSkgeFjEUhD6HQWOSfhRsbq+KLxYoLpVtxDAxMnTxT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',
    'love|ruby': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX////U///v3uTuytngyNDov8/avsnKxMvXvcjVu8bbt8bVuMTTtsLWscDXrr7Rsb7Ltb/LsLvMrbu9sLW9rrO3r7LlqbPRqrnOqrnNq7rNqrnNqLfMq7rMqbjMqLfMp7bMpbTLqLfLprXLpbTHqrbJp7XBqLLKpbTDpbC7qbC7pa23p62qqqqUqqrKorLIorHIobDOm6nInq3HobDHn6/Gnq7GnKzEoK/Fna3FnK3Em6rFmqrEmqzEmqrEmqnEmanDn67Dm6zDmqrCmqrDmarDmanCmanDmajDmKnDmKjCmKnCmKjDl6nCl6e+oq27oqy6oqu6oau5oqu5oau5oaq5oam5oKq/nau7nanAmKi7maW3oqa4oKm3n6i3nae3m6a3mKS1nKa0maS0mKSzmaSkmZ7Qk6LSjZ3GkqPDlqbDkaHAlqfAk6XAkqS/jqC9laa9kqW9j6K8jKG7i569ip+7ip7de63ufIDPgZLPdYzGhJPEfY7Hd4i9iZ+7iZ68h569h5e/gZC/eIi+coe3laO0laGzlKGylKG3kZ6ykZ+3jp26i5+6iZ62ipu6iJ66iJ26iJy5iJ26h565h5y5hpy5hpq2hpi3g5W2gJS2d4qwlKGwk6Cwkp+wkZ6vkZ6wkJ2vkJ2wj5ywjZutkp2tj5usjZqkkZmbkZWcjZKtipitiJeoiJashZWphZOohZOjiZKeiZCfhY+XiI6XhY2XhIuugZGogpGlgpChgY2agouXgoqVgoipf5OpfouYfoileYudeIiYfIKSe4Ohc4OTdYCPeoJ/f3+Pdn+Tc32Nc32LdH2McHuOcm3RaZnKZW7FaHXEYI3EX2vFXGbDWGS7bXy6aXmxaXq4YXOvYXK5WW/HU2K8U2G7UWOvUpGvUW+wUVqxSF+wQFD/AP//AADMAACean6ZZmePbnyNaniJbHiJa3eJaXaHanaHaHWHZnR/aHGXYmqFY3CEYW+DYW+DYG6DX22BYG2fWmShUmOHWGGgQlpmND8AAQEAAAEAAAAAAAAw2yP0AAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADd9JREFUeNrdmXtUEti+x88qc2GomDIXtYDCV9paSr5COxwfMzQxhJLDgfTi25X5SjF1lVpY4yNfl1EiUSGRskQU0lRUlmJoS42ljoraXLPsjx6YOvlIy3+6m5n7z21Qp5nzz7lf/QP/4LO+e+/f/j22f/v0r9Hf/k05F7+3/VdwLv2Hka3ZX+YYxMZCEPFOFn+RA9mDMI29GBcZYP+XOFBD56MXz0Ls66Kc7O3/PAeKuHgpFgoxBBxqqK3Fn+RATGMvXXQ2hkCNjPnRFGqoo8Wf4hyMHcs+amYMNYIaHxDwaRTqafsv55gdjB0ZPQczgsKsYeZnL9XeuhV1mrqP9qUcax3FHAmDIQ8gj166dPZwYXJhJHXfl/o5mg0oB1Aw40OYc9mjFw+6fUv2TBby6eFfyBk9aw7MGBlbOsRnxnn6kYju7jZ0Yc2dCP4XrssQjbE0d/jGw8UN6eKORaOR1paHQ6MKhLn0CNoXcFAITwIhgeTg7uyOx7ohkdYotI0vlUINiwqiHf7dbm/BgUINYYn+BII/wQOLxaAxHg5YLI5A+u40jUqhwB2DAhk7c6C7jXYbGBoeSgAcAgnnjHdAYpzdT/gRPTzcnCg0WhDcAm7h+Af8GBobQaEQZII/Hk8gEBO8rZHm5uc0Of42IU010UecKE6OTo5/gIM2DdhnCDFCJxBSUoiEr4+Zo7MzXUf+O9sYkVsn5vEKw4KcoiIid+QYm+wPiLRzv8DmsDklRFxm9rnM8bHzWdlGEOi+M7d5Pz2bvRGSJyjcgTNievSc2bnaCG5qUhIzkUhijoxPzIyf9ztmZW5sBIEdSwKc4WHWbfr2nJGRzLHRzJFGRgIzKelC+pUrZfLJmZmrvmRnJAZtbo6xtN7Pm/0JcGpqz2zNgezJjs+amBifUglDuDdulLPZnMvtLR0ar+OEr52RSDQK5bzfN392NuPcf9Y2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',
    'love|ruby_swirl': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////97M/8zu79nk5dHk4dHr29Pe3cvb2sjx8af//wDb2rrX2bjW1rnU1bbU1bDW0rXT07TS0rPS0rHS0bHR0rLR0bHR0a/jysrRzrLQ0LDQybLPz7HOzqnPya3MzLXMzKnLzKbLy6bLyK7KyaXJyaLHyaXGx6XGyJ/Hx6DGx5/GxqLGxp/Gxp7ExqDGxaTGxZ7FxZ3lvcvZu7rWub/Ow6/OvKrQtqnGw6rFwp/FxJ3FwpzHvazGvZrHuKbHtpPCwrTCwq3BwqvAwK3Dw57CwZ7CwZbBwJXAv7DAvpbAua/AuJS9wJe6wIm9vZ+8vJi7u5i6uqC9uo68uoy7uZ+3uJy8uYy8uI27uY28uIu7uIu6uIi7tqe2tqe3tpu0tZq8t428tZC6toi2to+ztZXgrb7SsLvOrKvNp7jLq7jKr6PMp7jKp67Frq3Fq6jGsZXFq47GpqPGp4vFpYW+sbG8sLK8ra68sZm+sYu+rZS9qbC6qau8pKy/qaK8qYu9pY7KnrLEm6vDm6m8oau/nKm5oqq5oaq4n6nEmazDmajCmKfBlqe+j6XCoIS7oInEmZe6mYm9nHq5mHa7mG/Bk5S5lXi4lHq/jJ27ipuzspu1rp6ysZKvrpG0qZuqqqqqpo+np5Oyr4etroutrImtqYqpqYuqqXmzo560oKC0naSwpIiwnoSmo4igoJSdnpajo4Ofn4OenY6cnI+bnJGenYK0mKSylaGxk6CvlpaymHqxkZmwj52ujpmui5iyjHCxiW+uiWKcm42llpKZmZKil3yamHeWloGUkn6kjJSkjHiajYCPjnWNinDkfa3Jf5e7h5+6iJ25h524iJe5hZushpanhJKugJKthImne4ushG6eho+XhYyagYudg2uUgYp/f3+LhWuXfYegd4mWeHSQeXuOdH6ycJGQbXyMb3uKbXmJbnGJa3fMY6GdZXOLZ3WwVIOmRn+HbHSHaHWHZnOFZnJ5Z2yEYW+DYG6BYW6CXmxLMzr/AEB/AAAAAAEAAAAAAAD7CXBYAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADT1JREFUeNrdmX1U0mnax3ePFp5DMsGUzmIWKUxRsGJhpYYolqWtPAOKJesjvkUhvgWapmlZCpqagrM5+XJS1IOTjubMIjWMleVLaq4vyWNr0pFmGXX0jKZu1l8916/mn2lQa2b/eZ6vIsI5fPxe133d1++6f/7h9X9Gf/g/ytkrF/0nOHt3C0XC3835ZM9e+u64i4m/k0PfJaTbrY/VnE39XRz6rpjddrvpqa0ASv3tHKEwOnovnY5wZHJR0m/k0IV7mdExQuDQtZpsmTw16TdxTu6Vxp8QIRShWKuVZ8tkqR/OOQkUSQxQYM3FJ6K1Ol2LTCaSfyjn5F6JJOakWCgUi4ESvedsXXpFtkz0oX5OxCMUsZAuFsckMBkuTq7OpIOC0JD0D+RITojFJyHBolgGYwdxB5VMIOD3XRVEsQUfGNcusUjosseVaG+/keBAsLHBYjGO3pxQAYfFZn0Ax8XFg0Jz3m671d4BrGCxWNzH+G3eLG82h8VytPZ+P46VFWqd83bKDgqNCOF8bOuAJxCIFBqF5e3N8vL0POzFWp1jZYGysEBZ2rhRQDSiPRmPtbV3oO6gEokELy9vb29PRO/hxxKNAj84NwqZDCA3EhaHwRATGDts2aqrHJaX92HPw+/DsUE7WluiULZuFF9fGoXigMExGZulBUw0hl1e9sUXpSyWF4fNWZWDRmO3hWxy4Abxg/lcGokRT2QUSBlMJgplZc3iPZqZ+6EkhBMaugpHgt5MXOcUGhjh6+Pj60Nz9pVKFUoFYzsRa41GoawJcTNzszMzebxV8pwgYUoTGFKV94FDPj5cLjeAX3lZWXyERLPH2tpYY2yxGOw/gJMviBLsW56DsmS6MwsU0vpOATuCzw8ODuJzr91vvo7k2x6H/RhnY4/7NHR2ri+HFVV9sGw5jqWlNWE7Q6m80dV1g8MNDkIUENF9v7GSTSbZ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',
    'love|caramel_swirl': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////5z//wDv7tDq5MTk3rfp2Kfo0qblz53jzZzmzprh3sDg2ave2bzQ2brf0KPgzJ3X0LvMzb3hy5vgyprgyZnfyZnTyrPkxZHfyJjex5bdxpbcwpLbxJXbw5PawpHav4zYxJrYwI/Yv47ZvYzXvY3YvYvMxsbTxaXOwKvTw5bSv5HTvY7FxMjDwMPDvsC+vsHBwp3Cv5PCvZfEvZPXvI3XvIvWvIvWu4vWvIrWu4rVvIvVu4vVu4nXuo7UuorXtpDNuqHMu5HTuovOuY3LtpDKspXUuYbTtoTQt4PQtIHKs3vRsIHNsHzMsHzJsIHLr3m+usC8t76+ua+5uMC4t7K5tru2ta/Asai6srG1s6+0srGysLWysK3BvJTBuZDCto28t5m4tpC5tZ7CsozDr47CsIa/sZK5sZfdq4XNqoDMrXzLrIHLrnrLrXnKrXnKq3rCrY/ArYTBq4PIrHrCrIDEqXnQopTNpYHDpoXEn4bKonjKnXrBpHfNkpbGmnzGmHfFlXXDmW/Dk3PCj3C1ra+wq7KvrLGvqLSwqLGvp7C7rZ20rJ22qJqwp5m7q4m3qoW7pny1poWzoZO1o3+3oH66onq0oXq6ona6oHe1oXK3moq3mnmzmnG3knmyk3G2jXSuq7Guq66uq62tqq+qqqqtp7SrqKypo66ppaWmoaSso5OqpnGloKiin6SlnamhnqOgnaOfm6WnnY+gnpGnnXugm3qdnYidmnujl6qhlqmglquhlKaikqSilpegmXumlnGkj3ynj2abmKCZmZmbmJealJ2bmHialHebjW6Wk5mWkJeRkpWSjZWOjYzTgpm8h267h2m5hmy1fmioiIOqhXCch2ykf3GsfmOue16QiJGMh46IhoqEgI6Df4aCfoSTiHZ/f3+Ae4CYhWOWfmWTgFnGc4OndViYdWCIdG59d397d357dX56dn15dHx4c3t3cHt0bnnJZpCEaWdyanfBWpmvVYeiRn5xaXZwaHVnZW02NT3tAEkAAIAAAAAAAAB/OsJbAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADWZJREFUeNrdmXlQ02max7sKUaLZgt6E0AFNODoE0ODYuJ2F5hjCFZAjHMZMGSEsGByQw3AYuQShNXJO1Akgl5u4hKMICS6IgMrANqeAGZHmauhCFIycNpf7j/v86JnaGjuATs8/u98iRfLH++H7HO+b5/fy2ft/jD77P8pxFTP/EZzf61GYlr+aQ3Z0pOixrjF/JYdMPkp2PMiqPc3+VRwKhWn+W3Myu6PqGpv593MoR135jmQKmdlRJZYymX8nh3LUke/KpFDIZIqsSiyWbudoF46fY3qi/28AQ7EMkMkkYomY/emc3zAd0xJZvhSypZ9lAOtidX197V2xr+RTOX6OyYmsgABLS7+AgN9dvOjIzjuXmyPx+1Q/rMTLQPGzpAQEsBL5dHMLJxtDdx43OOcTOYk/Uyi+/q6edsYkO2siEU/j8eJduJ8YF4XJ9DU3P0IkHMQeIhLwOAwGZRHI4caG0lyOfwLHzJxGtXWz1iceIpIIBAwGg8XpHw4MDAziBAYeNwv8OA4aranlZmptTf2GSCDgsXiiPoFgTLWxBk6g1bFjVlYfwUHvQe/Zg9bE2ZGoVKqt8SGSAQZnQPyGak00JlghoGOIPsLPXm00SMeORAKSjZsJJAZln+xJ1XcW8ThfWYEhq4/hYLUstDXRaJwd1d3dlkolorB8z0NpmefROs5CYWpqftBXVhwOZ1fOvn2Yw0FGxt6R0ZHR3rYmnnx7z4x0eng4WNR24b5a21hPDQvl8nbhpO07aK9lz+NEedDdPdxsbD3S0jOVmXRTYx0dBES8CJy1t6lc2s6c5GTPdD49TRjoDBwvb2/vuIYSpTLcxNYAo6urrYNHoTCv1tfWUrmxPNr2HLQmnx6e+TSjrI3HiY6OjoqMjPYquN9QYvgllWqAARLWAGPMXV8fTP0qttApdjuOpqY2wZSuVLb1DLeF+kT+rLjh7vs3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',
    'love|matcha': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////+Dt+8nZ98Xe6cfY6LTX4cDS4LPT3rfQ3bHQ2rP7/ZL//wDP36rN26zO2qnJ26PL16rI1qfH1aXF1KHE06LB1J3E0qPD0qDC0p/C0aC/0aLCzanBz5/B0Z3B0J7B0J3A0J3Bz57Az52/z5y/zZ3Az5q+zpnBzJm7zpa8zJa7y5a6y5W6ypW5y5W5ypS4yZO3yZK3yo60yoa9xaO5xZy2yJC2xZW1x5C0yI20xY+zxo2zxoyzx4mzxYuyxo2yxYyyxYuyxI2yxYixxJCxxYqxxIqwxIqxw4qxxImww4mww4iww4W8wK66waa4waG2v5+1wZq0v5qzv5m0vpq2wZGzwJOzvpizvpewwY6xvpWvwoazvZmyvZeyvJexvZexvJO0upy1t4+vu5O6qJus1Y6uwYetwYKswIOsv4OtvomqvoOpvoCpvnquupCtuZGsuoupuoSnvH6mu32nu3mmunusuI+ruIyqt4urto2ptouptYuot4int3+otYmntYGotIqntImns4mms4ims4emtIOkvXqlunykunikuX2kuXqjuXqkuXmjuXKkt4qjtn+kt3yktISkuHmjuHmktnqjuHWhvHait3OhtXigtmmdv36etGsh+CGmsoimsoOksoOkr4Wgr3+froCerH+qqqqrqoadqIKapICYo36an4afr3mdrXqbq3maqniZqHiYpHqcsWybrnGZqXKZr2GjrFKUq2KSqVyTq1KVpnKSo3GTpWSVn4GVnYKTn3aTnH+Sm3uPp1eNpFuOp0uMpEiPoGuOoF+NnGyJokmIoEWHnU2DnUKCmz9zoUm7kZOglXaRmnySl3mOmXWNl3WLlXOIlW2Ikm+ImVuFlFyGkG2EjmuEj2WAmEh+mDmBj2d/kFR5lDpmmV11kDeAjWaAi2Z+i2N/imV9imJ8i2B3jEKPiG98iWB7iF56h194hl53hlR2hFl1g1hzgldxhT7QfaR/f3VzgVZwf09lfDjTaaaJZmeyToplNUwBAAAAAAEAAAAAAAAswjPBAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADcxJREFUeNrdmX1QEli/x/e2GrEzkYomy2jkA8qN2BRTAWW5yxpsSqloK/YYbvdhh3zHRFF8IW0pXa4+tYtkTGNoTlqIbzEBtoqGZiZjZr6smraTa+j4/jKmj//sPezeP+7jktbu88+9v3GcgZnzme/5nd855/s7fPDLvyY++D/KKWb7/Cs4Co+PXFz+NMc2KWmPR3yYy5/kQG0POCYVU7ks3z/FgdpivZOOQt2VfJavzx/nwByTFCdgeyDuymR2jE/IH+RAHI8qknAwKBRqLxaGs2NCQ/4Qx+OEUeNtD4NBYfbI/DxOODvK9/059h5HdZpAOBTmgLR3/lRx6eJFPpvjHPG+HORRnTbQCQl3QCKQZIXiqG9OfA43yuV99XgrtIHOyIMO9ig0VaEpxnrSgsjxZeJI7ntyNIHOzkh7qD0Cey6N6Udi0D09sZESiTJZ/J7zsnXDIBBYKgGHd8V54dFoJALh+xU/S5JBTI56D86B/X40GpOB9cJ5BXziiUQiUG5YIjuczeVHRPm6cN6NA4VB4NFUGo1KJ+DxGDcMAYs/4kdj0KI47PDwkNBTrHfgwGygNjYQCCYYcGgMP1wAFonBedEC6AS/w6zwM5yIEBCh76AHYg+FwSBuTCqFAkDRZCTS2fmEJo2KjVeXCYmsU2GhYaHvwDloR3SAQKAYJi0ujkGjesHdFMV4XbcChoi/VdHTc5F7jMVP5u7I2bfvIJHr7iWQyqSyAgapUHOiuL09SaGAQqDOZ//es7m52fM3oVi8A0dnRw60D5QI5YmxsYnRDEaCrr2ruyuJREA62UMh8CNfb2xubmz0/D1ye45OV2zUJBlrzsQDjqCgoEBW/9A0JicF4ZBotJMTGrEf2fMr56Yk8u0ciK3inKKrq/3hgCRZLpMVSaWy9PrmlgdkkG+cK9INdRDnShABQT3HytWnlW/j2NrCPUlJpu7O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',
    'love|mint': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////9TY8vbg3uLa0NXA2O7Ez9my1OW0zuKwzeOzzN+ry9zLxsvHxcnFwcbEvsOzx9yqxtu9wMavv82kxNqjwNWdwdifv9SivtGfvtSevdPBub69uL27ub+7tru3uL22tLe1sresusevtb+kuceysbSusrimssCevNKeutCcvNKcu9GcutCbu9GZuc+dt8qdtMWYt82cscOesL6YscO3q7WyrLKxrLOwqrOvq6+vqLOurK+uq66uqLKrqsasqLGtqq6sqK6qqqqrqKuircGkrbaYr8KXrsCarb2jqbampq2eqLmZqbqZprutoa+ooKumo6mmnqujoaein6SinaWinaGaorKZoKmgnaSgnKGcnKWwkbCmlaujl6qjkaSilqqhlaihk6mclqqcl5+Zl5qdkqaYkZ6Yj5yUus+VtsyTtsyTtcuTtMo85OuQtMqSscaOsciNsciMssiMsMeKsMeTrsOTq76OrcWMr8aLr8aLr8WMrcSKr8aKrsWKrMOJrcWHrsSGq8ORqb2Nqb+Pp7iSo7eMpLqPo7OFqsKHp8CKpLmFpLyIoriHobOBqL59pb58pL5+o7p7o719obt6orx6obx4pL55orx5obt1pr5vp72OnruRnaqIn7yHn7GBn72Cn7OCnL2BnLCPl62Hlq+Uk5eJk56CmLWAlLSClaSEkp57oLl8nLR6mbJ6mKx3nLVwmrF7lbZ7krp1l7Nzk7V6lqp7k6N1lKeTj56Sj5OPjo+OjI6OiZWKh4t+kKR+kJ1/j5t9jaZ9jZqAh554j7l1jrh4j6R1i7V1i590iKNuj6xwirBrjqBvh6tohqHCfq6Rf5iFgoaDfYWAfaeAfIJ/f39/eX95gZh8eIB7d39pg69ogq5ug5Vqgptsf51repZmf6ZigKZhfJZeeKNgeY2xcZt7dn56dX15c314c3t3cXt1b3pzbHdlcYxXdKNXc5VXb5XUZKK6XZOwTYJyandxaXaVU39uaH1pZ2tQaI5XW30fHSOQAGAAAP8AAAAAAAAvgWr6AAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADY5JREFUeNrdmWs0m+nax2dNT8axiiLOh1Ta1FnVIbbM0jgM1ZBpwqA1S9EMK1QIGYm0zlJB0Ql1TNCKapRK1SFbKQ1vlMa2FEmrpUOduh1q9tv50veO2e+HbaLamf1l7z/J8mSt55f/dd3Xc1/X8/jiw79HX/yHchIQ+v8OTqKasr7Kn+bstbRRPORlr/8nOYp7Dx2ytDZDQ6F/iqOkaKBmaaxoFIa2hxr+cY7yoVNlf1FSVDQMQyPc9A3/IEfx0F8qThkpKyopKmPQjgi3nRztwjE41V9hoqKkpKikrIvBIJ2Rjkafz1ExONVXj9JRUlLRU9E1Kws4exaNQOgiP5eje6rlFkpHV0VZT1fX5HSZKRTnk/UNUudz/ZhUAC+6eirK+vpmZawU0+hkWlwOg47y+kzOrVM6OrrKisp6Jqk5tGgijRIVZZ7AYFSnMT4zLkV9Az0108Ro/A8w6yg8HA6BaFt6pNIZ6Qlp7p/BMTW2S0q6TLGIso4m4qMgEAgMZhHj7u5OSnX3sNLw+DSOgoKcenY8hZL0YzQeb37MPNoCjyeQqWR3qcxsbWzcd+co7JPft09ODkYjkslkKsGaaAExt46mkCkEgrWVu4eHu5mZmantJ/iRU5UHfiCXiURAol6OhUA0NWJacsgWaVxGaoydu62trZXN7hxzdSsNOTl588vk7GwqmUzQgLFyrFuEOaqaaWz2uXNZpBi71NTUXTnq6pAY0vGo/OKS4pJCamwOKzFH0J9dlSMvJ69Byvt5fePnc6fTc3N34bSo46PVY3PTSvKys/OuUKl5ff3CKWFOPEFbQ1VeTiPKe31jY20t6FrCxzmslpx+VkrfHY9kwCkoLCy8zRGIxVWXqNYQc7iGhrm2JuznjXXAYTASdubIHWBdqRJMCYQSRloJUHHx9QLew7/eiyOSk6xhEDgcZg0jZK5vrAUlVHKTq3fiHDigHhWfI54akEgG0q8xi6UqLJnuvclJiyfAYRZwCIEcxWt8CjgxHvRqtmyOxr6vNGHRRMqT7l7JQO/9O8VSR9eLC3jPGhoe8ujHj8UTYym0J23c2o2RICsbd/dUmRx1dQ34cUIcbWaltxuo9/7t/Py8y/mA1dAADnu7H1+JIxOr/z7IbXx6GlDcrdxlcLTVNY8B53GN73/99Vm3lPSQndPc3Nw6JRaLB7c+kKxwk9MYgzNcHi83jURKt5PFUcfDzS204S9WVlZ6b3Z3g0gGZ2dnX719NfU/QmFTAVtKml4ZINHZMzPD3JrvGZmp6XQZnFhKLJGQAL5zZbq3Aeghp7VVWEXFH7XQInLx8grHOb2SaYmkksTmPV5tq12rpKd7kGRwKD/EUTm9vQPT09MSgOm207x421JOYf/+/ftgd/Ggki3u904/43BI6ZmZM8/Za4NcBj1dVp4Pc4F1yfuVrSz3JsjJ4e8S5OT3g1+LAnNVdUL8te5u9qWrlXZpdO7qixEel8tgyOLwJBKQlemVaYkUo6khhy+JVVeVl1eHwSHaR48mXbr6+H4cJS4thUinD78YychlV3NlrvvAwMOGhw8lIK7e7qhoPAR+XBsOU5BThWjDLC9epGTf5vEaYy3M48jUmMwXTysZDDpDdh1yuhvSOH8FmZZ0X6HhNTW1zc3hChqx5NiEmqCgIubdIW5bmvpRU0sqxW5wlk3fkfPhZhaBeviH6qscDpGSlJgYTSsoBGV413iPztpaVeHdoTYuN4flrRVNi818UZ3LZu90fdGjGgd5d6ovpaTkFV9fW9u7R62puLigSe3LPWsjRYX3hul0sVhYZqYVS0vksjPZXN4OnB+IufX13MHBwcd3SmvW1vd8adpUWFzYpKYYtD4C/MzEHBSKhX0ZZkep8dd41Ttw9L48cOkqg54r/eE13gha+0XnRB645K+Xfr/xy8ZaUcHd4RS108AQy9vU2gJW3caTzdE9uO+rO8BLT319NbexFHA21qoAp+hG0Dr4s6b03nCCmc8T8ZSwrKwlRiOaJ5tzUlHtwIHDFy/mc7ltj9vulJ4DJ49Ubfkpk3KCAKfcNaNe8EogFPb1mWvGgKzL4JzQO2iKMD540PTw4cNxcdk3pMEAzvViJjN/TbqRSv2YeFXa1jhhxX19LG3tO0NtMji6aqoohBuQoaGhsWrMjXPr6yC5zNLC2z+xRoLCq6T5iZEzwZJMnBx6plr6EzUthoZlcBTVVL9GOEOhUEOjI0eg6TfC19dGRopuP/3laWkR80Ypk8kEnH1y2Cx3lJODQNjXoqoua5/3NZM3dkNCDQ0dEUgUCpXLLCoqqipiNm5sPC0tKSkqKiy83Dh8J5fbgPMkeZ3Aim+pycsryOB8I9A2c0NAoUbOjs4oFLa5kMksKWEWFG38XJadnU0DqqrmDg3NBPh7p2Y5ORgZGB+UV1D/Pee0wOIksAKmUUOvDGwGqzA/Oykp6tixmCuXAacFiFXBYDNyfaD+PrnYE7q6BmoH5b86vJ3jdItl5Y/+GgoiM6qtvwK+/kq2hXk0LSm7pLmluTkFfBAX4+ExuDpcbu+VzvA6oadnoiZ/QGs7x1VIRAUGOhsaOTs719RcA220sLipWQiqV2qlGQwLZEpOauVrqcqxjHpffV19NTXs6HZOfZ+1/1mMoSEU6fgNDlcEek1Tq/ileErcWgDaczYVzC+EtErJFud1bVZ9rb2+iqtIxN/GEbewrDGBblscHA4nFE+BbtPa2lpSkhcPZiCi9TEwHNoNAMaMBKim9paXw6N//KNue55flVn6nA1AGhohEEjAkbasqVZghCydx2g0CpgwYdoxz99v2QFdA+uZuvLrZAd/O0dAisaBod/RDYP2x+GwJcXXr1/PjsLj4TA8lYCPwh87Dj8Oudr2W1ivJZJy45olPr9ue/2IW6ySw8ICkQh0YCCuHMfJJlIoFCJEWxsGBz0WTLuJFTkVFc3c51sQqY5cGON3/m7+ESdYZ0VGhmEwbm5oL1TD6xQwFSYRgR8CBQ8xv2gR1SIU9rc8Hx6a+SfndXnnv+T4/+PyMC+PjAwMxCAcoSYmEsAhUmhgmfKK7l2LvdbGzatqa2u8xBt4/vz50OP7QBzcM9lzePKZb8P8/QP90a6oIxxJXknT7fx7Q0OgRQwV325qYhIJhEs/ZtIZbE4bj55Op6df2Om+wA+EFYhxRJqgULa9Q6+HrhGv5DQxf/rpJyazoKAgJTk5MZmWQk2OuNlw/zE7k77L/QXygxfg2A4MxMXFxyflF9MzgLy9vT0SEhKs8Hjro2GR/gHl5byhT7pPMePc9M7I8HJxdXWyd7B3AhwrLS1LLRjMOtof4+Z/1g2J+QSOw0kH15DQc8FOTg4OTi4uLl6AY2tpZZdAJtNSAjBIBBIN1Tcw2ZXj5+TrJz3fxcXXz9f+xIkjgOOTVsGqIMZdSvoOg/FHOCKRRwyMTdU+zgkPDQ91AVb8QsLD/bC1NbUC6VXf39/PqqpiPQiTlr10y8zyUTP7KCc0JPS8i6+vX8/L2dmXYvGrqR5BzxNwvU31gy4RERmA8UcjEYCTZWOzGyc0HOjtP9WDrcFWtgqaq2mgyCMiwfWDcUZ4oWx9SB67ccJnf9PfHj0afIAF+UnNpadl/kilpHR1dUVeCEO74XAZPpmM3TnAB7AUHBzs6+u1lWdQQAQ8PrqL39X17AEG84KTlfWvY/jvOMHB4cDPYE8oCM/PxckBBW7+rCy1LC3hMO2jXU9Xnq2uTj9aXa3M2nZnuZ0z+PLtbHhocPB5vzN+vg5OTkeMjY1NtYDAgBa1svL+/erfp1fLgZ9dOC97gBewZq4OQE5OTsCPt42laQIrJ4UleP8+4tH0DOZBOdbWk0T6KCfELyQYxBQKEKAWneyxgp7ZV1OgdQhaqlgRXd+hMaAYcThPT/oueT4fDih+Z874+gb7nnC173k7OysWCvr7UoixiQ8iMAFg4QO8sJ6eNqm71yFQ6M3Bv/XUgi1/6smUoAIIDDQWfH5EGNjxMCgU4LjvWofASsgsWPyXPT09tadOeZNS00k25eVZ3u1dYQFgE/8kzvnwkAeDPYM1IefPh5w75xd28zt/bJ3Bd3yRaDzypL6SihIaE4D1svVM/Xhc54NDvn/7fvVlJChd/vjo6PjkeERY4Jk3m0vLm5sLY5ERRioOgTisZ/ouee6KjIxo/zrs2865yaXFuaXNd8ub/wu0CfRucW5+UcSH7gHaf4hUuSNHZHSyUySa53/rN/Fmafnd5tbJgLS4uPgOSHqwuflmfuxCnZKuDpazsx80RjQxOg8cABe/nbW8OD8/Pzk5OTc/P7ewNPdmeVPKX1oa7fr2kBFU6SP7c+eFyTG+aGJxy83m8hspZA68pO9z88vLIE/LS2NzE6N+OnqKih/Z51WUO9s7x+aWlhaX3oGY5hbeTLxZWACGJiYnFxbeiALQDvZKe5WU9+zd88VHn7fs1eMv110YH1+Sxib9+oXx8bkFkaijvb29o6OjDq2LrAOdUH+U3xkmErWLPnR07vxcyw3DnxibmBgda/8GjdZX1vm6o7Ozs0P6xh+bF9XVjc4vjM8vLk5O7PZ87AI08MNeIOkqg8M6vmh0lA84Y2OA/+HD6Oc+p9XvqGuvE4GTJ+fnF//Ec2M+WLyFyfH/1v8X7Kb/A5I7HhU2WwwDAAAAAElFTkSuQmCC',
    'love|lemon': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////8n09Mzr687n5MLi4sLh4bTh3sXd3MzY1sT//43//wDe3qna2qfY2KbW16TW1qbV1aPV1aLU1KPU1KHU06DS06DU1JrPzNPNy7vPz6vJyazS0p/R0aDOzKPJyKLR0ZvQz5nPzpjNzpjOzZjJypjPzZPNy5PMypLLyZLKyJLKyI/Jx4/Myo7Kx43Jx47Jx43Ix47KyIvNynnIxM/HxL3GxaPCw57EwMbEvcTCwavBv6fIxpPFxZfGw5PCwprBwZvDwJTAwJnBvpfJxo3Ixo3IxY3HxYzFw4zGxInEwojGxH3EwYfBv4TBvoHAuoPFwHjBvHTDvV6/wK2+vpq+ur2+uqK+vYm/vH++uoG+wnq+vHy+u32+u3y9u3u9uny+uXG8uci8ura8u5u8vYu8uoO8uX26uaO6uYy4uJOwu4+9tcS4tL64trW0tLS0sbSzr7O6tqK6tpe2tqG2tpG6s6C3spy0s52zr5+wr7KvrK+vq7Cuq66wqbiwqbOvqbCvrKmurZqtqq2qqqqsqp6sqaLHm6evqLSup66rp62qqJyrpKunpKmmpJ2koKejoKGnnq2kmK2in6ShnqOgnaOgnpugm6SdmaOamZqhla6hlqihlK2flaqglaOZlZu7toK3tom2toq2toG4s4K6sIe0soKysYKwr4awr32urX6urHmqqYSsqXq6tm+7tWK4sWSzsG2xrWytqWy7tFK3sE+uqlO3r0ayqUW0qzuvo3uno3SmpHykoX2goISgoHmgmHmdnoqcnYadnXyamnuXlnSrpV+tpUSloVqfmWihmVCYll+tpEGtpDysojqimTqglj6glyvOipy4iZGhkqagkGiXkZuWjpuWkFKSkZSRjpORipSSkW2Sj0eNjI6LiI2JhoqHgoqIf4yCf4eMi2d/f3+CfoKJh1uKhjjZdqqRe4h/enx9eHt8d397dn57d3d6dX15c3x3cXx2cXbFZpx1bXlya3a6V5KkRoBxaXZwaHVnZW02NT2/AP8AAFAAAAAAAADVwnRfAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADZ1JREFUeNrdmWlQE1i2x3u6mQxdRdgzCESEdNgMdBiMBhUkiEjAiAwYmyWQNCAkZdgXBQMCjbIYEQk7TUwcgZBAGFkCRmOzBAQBQfqxQ7DxsVRPGEBZZL44N3bNVI0TQKfny3v/qlTBh/vjf84953LuzWfv/jv67P8oxzM9/L/B8TLC0I/+as6+Q2cwRnGJQb+Sg9l3zPCQVwwzKvJXcTD7wg8eQmEiS5iJkeH/OQdD9PAiHMZgIoqZjHR6+H/IwRw95XUuHANkl89MYqTv5GgPThBBJLzwrR2g2NFZ+elJjKTIT+d8G4RvEsZ/i7E7SrS7FEy5VVTEZDCIjE/lXHJrrI//ln7UjniJfoHiZRuZE5N2nUH8VD8XhI3xly4RQUD0+DovzwMHTrta47lxYVc+kVMfo6Bg7IhB33jamtvb2CKRcAcuh+PE/cS49tGDiIZH7E1NTHRMkAg4TEtL48B5GpUb4uDk+AkcQ0NHKytbW2MzEyTqK6S2lpYuzNgUh8M507C4A5q4j+NAIBCo29doGysXcwSwAjc3RiAs0C5owMFhvY9hsY57cyCfQz7/HAL5vasVGo12MTdBGWvDjZFWB23MzZFYHO4kztvb+9jxj/ADgQI7EB1XKxQKgNwstLQ11W2FnlbGeB6H5oDFHT92/MixvTkwqKkm4MBd0QSCC9oKqQ7z8kQ0tXpBNEKqK4eH4046YGlOznty1NS0Tc/vN/MgkUlkHxdLT+EZz1bRGYoXQGs6hwxvbm0Ox4Bd24PTpGZtC7XlhASedXc/637K5ayotaWv5cxBcy11NZD7r+LfbG2+WXpBddid09j4R5HQU8TD4QnuBA8fH//QR139A3+0dAG5hqlrwrU0dIYVHC6H67AzB6LiRaC09rU2S7lOgWRyAIlE9qhte/zAwhqNNtbRhunCTHRNqZtbSzdOcmpOVO7EUVGBIg96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',
    'love|salted': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////6ro5+nd297a1NvU0tXRzdHMy9DLydDLyMzIyMjLxszJxsrIxcrGw8fGwMfDv8XCvsXAvsi/vr++u8e+u7++usC8usLAt8C9uL68ub68uL68uL28tb67uMG7uL27t727t7y7tr26t766tr26try6trq6tby4t8e5tb24trq4tLy3tre3tLe1tba3s764s7q1s7a3srq2sre1sbizsbqysbLLpMO2qre1sLi1rLe0r7ezrbazq7ayr7iyrLWxr7KxrbGyq7WxqrSxpbKwrrKwrLCwq7SwqrSwqbWwqbSwqbOwprKvrbavra+vrK+vrK6vqbSvqrCvqLSvqLOvqLKvp7KtrcWurLStqbaura6uq66tq66tqq6uq62uqq2tqq2tqqysqq2sqaytqLaup7OuqLKup7Ktp7Ktp6+uprOtprGtpLCqqsCqqqqpqcNU1OOnqMWqqLerqKuqp6uop6qqpbGppayppqqopamopKmmpbSmpKepoq6poK6moa+loqekoaakoKahosGiobSjoKajo6OjoKSgoaOYmr2amriamrepn66onq2fm7CnnauknqelmaqgnKiemaiin6OinqOhn6OhnqShnqOhnqKgnqOinKOgnaKgnKKfnKGem6CdmZ+ZmZmcmKCjl6qjlqmil6qilqmhlqmilamhlamhlaiilqaglqiglaialrCelqOblqCZlp2ilKiglKeflKiik6efk6ajkaOck6aZk52Zk5uakZ+ZjqCWlamXkZ6TlbGSkaWTkKSWkJqWlJeUkZaTkpSSkZCSj5OUjaOTjZaMjaSOjZSPjpCOjY+NjY6NjI6Mi43VfrS6g6ejg52NiZKLiYyNhpGNg5KHiaiJiZCIhYuIf4yDh7F/gqKBgJaEgoaEgIWCfYiCf4N/f3+AfIJ+eoCwc5l9d4B8d397dn57dX56dX53dIN4cnx3dHp2cHpzbnnTZaS3XpGwToZ4bHpyaneUUHxwaXlwaHVqZ2xeWmUYGR/lAOUAAP8AAAAAAAA5WLqZAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADcZJREFUeNrd2WtQk2e+APAdETTDRYKSbQjVIEREKLdiOmni4VYRw9ScwAupfddttkgjBA4TYQnQAImQoVzCRaJGiYENFzUKAtEsRBD6BmQDoSBLBKNcJwhIkduww37yPLEfzowbQdv9sucPGfLl/c3/eZ7/+9z43et/T/zuP9Rx+ObIv8PZvdvey/43O5a7HWx2+59y+Y0OytLBerelKy+I+JscW5TrbhB+1bxg4ie/3rFHHz7sgLJDfVqdAcce8vqVjh3a9vBhN3sbG5SdmEeDY4lev8px3cdh7He0s7G2tXcRS87QYJrfhzvYgw7JyT4YO1t77F7n/YeFUgkPhp0iP9TBOjCSfbCH0PZ4F5f9+xxsyVe4F/4MO35oPr8HirMLzt6OgPNhgD4KiUkI4UrFYekf6CT5ODs77bGxw/h/eZpOjmdHkUkekVJpVeblD2wXysUDi/GkUwLI7gFkEoGAc8L4xWYIZbywTPgDHLf9gRDEZvmS/cmhJBIO54Q/6HsCpsGpGfAZouOZ93NsbVHoRDoE0SEKieRx0J3iSSIFQqwY+AxMo/n5nQp7D8fWwtpi5+5deDZwIFagP9UX5+ZPYcVAFAop6BTMhL29/LyI75HPLnsbWzsUjk0PD4egGHbgAbwz1ifpLOTLVVdmfn2cFux3nPgezkE0ee8ulM1BdpxIxIJiKFg8g+HK4TDsMNxq+fBwZcrXpzIy0rd17O1xkX/2PVbTomxR1seFnmf4MDic0+cZ1igbx9gfXqytrw1z+VfE2zjJe/b7OB4VZqrKs7NLs+ISijmc3MLc0zEhzpg9Nig08Yu19fXV1eEfIrd2GIwkDsOH0/SnRFF2dk1dfb1KnldQ8H10jC+OQMA4umOdsC/W14BTKYt8t2NtyUhIyi3glBgkXJVSqWxRKG62PXpYEnoSovu64ggurv7Y42Vr66vD/3NdHV/1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',
    'love|rainbow_swirl': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////9/o//bq6NDR5uz//4nm4Lz//wDf3Lrd2bjh2K3b2bLm0rPf0Kzdzqvc0K3czKnV0LjZzavfz5nby6jcyqTayqfVyqjUzY7dyKvZx6nXx6TWxaLXxaDXwp3cx3rYwXLUxabUw6DTwKHTwJzUv4XPx6PQwqDIxa/HwprQv5zGv57Rvp7RvpvQvpvQvpnGvpLRvZrQvZvQvZrQvZnNvZvCvY/SvKvQvJnOu5nPu5jWuMTSssLXt6XPuZnMu5nLuJXHuprCu5zFtZ3HtZPOtozQuWnHtYzKsY7FsY3HsYXBvIbBun7BunzDs4nDsIjgrJbOrKrKq6zKq4LFrJTErYvEr4rErofCrZHDronDrYjCrXjNp7XPpZTFpZrOpoLEpH/IoH3Jm4/Jm3rKlYrImG3FlXTDkHG8z82/v5+/vaO+vKC+u6C9u6C+u5a9uKC+t5m9tJm+tI+/spO/tni9sJu9sJK+sJG9r4+7q5i8q42+roO8qYi7qIi+rm+9q2m8qGKszeGmwdO1uKeousG1tpyotbOmsbOpq6qprqOxr5uxqZCuqWibvc6Xs8WRsMWXr7+Nr8UA//+DuceJsMmZrLWQqbuMrcKGq8J/qcO4pJe3pYa5oKayo4avoImlo5Ghnoy4pIK3oIK3onKwoH+poHy5m4utm4G4lomuk5G4l3W1kHOgm4mcm4ihmHqhlX+gknqhkmaMpLWIoraFo7iIoLSApLl8pL98ort+oLZ+m7B6o716obt2pMJ3nLeZnJCamoCYmIOVkYuZkHODmqeBlqV/kZ99j514lql4kaJtkaPZg6TCiYG9im+9hmu6iXC6h2m4gmedi3uXjHmjimqrgW6sfWGdgGuUinuThmyQgWd3i5pyi5x6gohrhZdqgpJof5BkfpBifI1Sfpm/eHKxeVugd16TeF9teoFheotgeoteeYteeIled4hbd4hadIZXc4XUbqfNYqGca1qyVYSlRXZYcoNWcoRUcYNmZ5hSbX8xMEXGAA0AAOEAAAAAAADaIdOtAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADPVJREFUeNrdmWtQU2cax7vVYYJAAjVGtwnYpqfihqJiuKSAEiwGUi5W2KQSogGjUAJqMAhp5CKIiFgozHBtDGKKTQ0XEaTIxcpVAoiGRaEiBcOsZLiDgDj94j4ndj/UBtC2X3b/YSYDM+eX//N/n/c9Tw5vvfhr9Nb/KGf/Be5fweE5OHOd/zTH6bPPnBwOLOvodThOTlynHTt8L1zw/VMcwDjs2OHEvQIg7h/nODvv5+1wctJxLnB9/yDHyXkHbz/XGTjOKOeCr+8f4nD3BgftRSlOztwrL0FvznHm7uDzfZ1RhjN37/4rOhD3wptydBQu19mZywUKb4fvNwe+ubDU4i/N2ctDKTqM70HebocPPna0oIujPnlTP0F7UQqsk+8/d9silK1byWSCnVgsdot6w7qcgOPgsP0DkjmeRCYRCKam2E3CiCix0OqTXW/AcXD4aPt2x61EMpFsTSKZmpriCUTKkbBwYcSRXVbrj7wex9AQg3PcQqVup5JJJAKeQCaSSAiVZhseHh4WJhAcCQ1fmWO0ynDVKgxmPcqh0hCiNdGUQCRTt9DICCk07Fh4uEAg2Cx4DT8GZoZGRobAsbYGkCMCwZjYBHlsIdKlkojQUJQjeA0O3tjSDIMBDtXNjUbdQsbheR7m/BA/I6xrbOyh778UhoYKhcIVOcbGppbCTZZMtj+8aIgHz9EjJJju52eIMXzH9fidpwvz358QRUevwOEbW9issYmO4HjQ6W50Gs2NHxyiDvGgkE1xRpA9+QBwns4ePG63PCeI7xEctJsvDXd1o9OZTDabU6C8282i0CBrAg5HwGL/fgc4ncfFYrulORgDHt0vpCtEWS4Wcjgcfzbbn1lQelWOIFQqEQ8kPNHUUjQ/P3sgVCJ1kSzFMTDAkSked9VlPT1XI8CLTpy+xlsX3WwsgEEwRahkmeTOwqxvqDBKEqufgzMw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',
    'star|vanilla': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////+PU/9T29tnu7tPn59Hh4dHg4cne3c/p6sHf38PW68Dd3sL5/5jf4Jn//wDd3cTc2sHZ2r/Y17zY2rfX2ZnW1rnU1LfU1bPZ0bzT07TT0bPS1LPS0rbS0rLS0rHS0bLR07LR0bPQ0LHNzb7PzrPT067R0bDR0K/P0a3Qzq7NzazNzqjNzKnMzKjLzKjKz6LLzJ3Wz2PUyLLXwrXLy6vMyKbKyqnJyqPJyaHHyLLHyKTIyp/Hx5/FxbDGxaLCwrTCw63BwbbBwa/Cw6jBwazBwajAwLPAwKzAwKvAwKjIyZ7GyZ3Ix57Hx57Hx53Gx53Hxp3Gxp7Gxp3GxpzFxpzGxZ3FxZ3FxZzGw53Ew5zGx5vFxZvDxZrExJrEwprCwpnCw5XBwJTAw4/PxWDQvKrCvqO/v7O/v6q/v6O+vqu9vae9vaG8vKa7u6W7vKC6uqK5uaG6uZ3Av5TAvo+/vI2+u469vo+8u4+9uo28uY26uZG9u4u9uYu8uYu9uorCvHu6uojcr67Or6XJsaDIsJDQpKfOnKTLnpvBtqLBrZ7AtILBq3zDpZi/npTAn2m4uJ+5uJa7uIu8t4u5uI67uIq7t4m6t4i7toy6s5a6tYe7q5C6nHi3upy3t5y2tqa2tpu0uJa2tpW2toC2tZu1tZu1tZm1tJq0tJq1tJWytJWzspqzspeyspOyr5mwsJCsrZSysYiwrYOtr4qsrYqtrImrq4mvqpKqqqqqqpOxpZOoqJCmpY+iopGqqoeppoirqHOkpIOkpHujoX+pnIOfnouenYydnZCdnYScnI2cnISam4uZmZKamn6ZmWbMlqHKkJ7Bkpi2lJG+i5G3lHGdl4mVloOejomVlX6XlXSZkXWSkn2RkXeOjnWRkG+OjW+NjG+Mi2+Mi22Lim2KiW3Ah5PAhJO7hYWihISOhnSTh1eIh2qHhWaFg2OEg2SEgmOEgmGEgmC/f5C0fIWefW2EgWN/f3+Af1a0doObdWanbGxlQkr/AIAAAAEAAAAAAADGvqI5AAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADa1JREFUeNrdmVtQk1m2x7tLJEr5ECAH0hEDDGK4YwtqggTkkpYIg0AgAqaBBHAi4RISgQZiQEmBcBoIwQiDx0yq20RoAhGBTMn1cAejFYjTXIYAggQjgeFm19C+9OzPmSeHi3bPyzn/qlTl5fvlv9da39pr73z2y39Gn/0f5bgTbf8TnFvGJrbHfzPnoLs7zPi8z/HfyIEd/ALu7u7G9PL4TRyjwzZfuH8B82hg+nh4/HrOETP3W+5wI4hDZNj6/krOEQSgOJjA4DBjMZNApHv5/irOUXdVoRsCDmRi/UBMJBAJHp/OQVi5FxUlmh2Bm6JMLdxuPah9yCTSj/l/KgcJUZCWpiYW1tZut265e0njKlKIxz7Vj1thUaKFNdrE2PpoYsGtRAfPSEpgcr3YP+UTOYVuFhYoE7ixuf1VXtSZKxSSq6u9f71Ulib5xHUdtrJDoRyCsc6uGCesMwaDQqE86EyRNN0/jfgJHMwJHIkUQ3FwdXLFu7gACNrS4RzIGAOk38uc/nEcOByGiCORSGEkrIuznSUG6+DijCVRSMSLRALB97yfD3F/DvwA7IABDIaJCQOgSKwj3gGFccRGXAnHYp19/Aj0AF+gCx/hBwbKFw5Dx4QFB5NI5BichbUFMvF2cYhDckttzVW/AL/zfl4fwTmK8DKFweCYGBKbHU6KwCLRBQUORaMFxshkeWN5+XdJAT7M5JR9OQgE6lyKw5lMrpArzCZ78goTC1Sqq7wCgDa/9qfy8kf/+21SulS8D6fI1C0Rkfggreo6lcaOI0eyVapR7ejVK1gLM2MYDOERn5D+bXmdROy/N6ewkKcqTFTJ6dFsKi0zOzu7qm1Mu1kSRAaxxpiZY5DHTuSXl6fxa+tk/rtzYAcLYnmjWpX6uTS5SigUcrkCTvuzobLAQFKYIxplicY4Hj1bsbz8FYEha41u2I1z8KCp6xXe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',
    'star|ruby': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX////U///p48r10d7dz9jlw9PbwMrg0GXNw5vbvMjXu8bVu8XVuMTZtsXZscLStcLNtb7Qsb7Rr73EsLe7sbXDs4rmqrXRq7nPrLrOqbjNrLvNqrnNqLfMq7rMqbjMqLfMqLbMp7bMprTLqLfLprbLprXLpqrHrLjIp7XJpbS8rbO/qbK9qK+6p67Ap4m4qK2qqqqUqqrLpLPNoLTJorLIorHIobDInq/HoLDHnK3GobDGnq7Fna3Fm6vDn6/Dna3Dm6vEmqrDmqrDmarFm6nEmanDmanDmajCmanFmKjDmKnDmKjCmKnCmKjMmaDFoFu+o627oqy6o6u6oqu6oau5oqu5oay5oaq5oam3oqu+oKy5oKq/nau/mqq4oKm2nay4n6i3nae2nKa5mqa0mqW2o6O0maS1mKOsmp66nFrNk6jDl6fDlKPClqbAlqjAlaa/kqTAkKO9laa+kaO9jaG9ip+9iaC4lqS0laKylqGzlKG4kqKzk6CykqC5jqK6i6C7ip+6iJ+5iJ65hKPQjJjAjJK7jJi7iJq6i5e6iJ26iJu6h5zmfYLMfInFf4zHd4O7hpm+gYzAeYi/dIK2i525h5y5hp23iZu2jX64g5m2go62f5K1d4WxlaGxk5+wkp+wkZ6ukp6jkZ2wkJ2vkJ2vj52tj52wjZutjZysiZusi5egjpSoiZWshpWnhpSki5GmhZKbi5Gbh46WiI6fhm+rg5GohJKng5Gig5CZg4uXg4qVg4msgJKkgJCne4ycf4qVgIifeoqgfIWVfYWgdIOSfYWReoOQd4GSdn6lfD2EfH+LdHTJa3e/bXvIZW/GX2rBX2vCWWW7bX25a3utbHm2ZHarZG+yWmfHU168VWO8T1y7UF6uVHexTVyqT1euRVWtPEv/AP//AADMAACWb4COcHuQbHyLb3qKa3iJbXiJa3eIaniMa3aJaHaGanWGaHSQamKLZXmFY3GNYm2YZVyDYm+DYG57Y2yPXWiAXWuOU1tiLjYAAQEAAAEAAAAAAACp/PdPAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADcRJREFUeNrdmWtQ0mn7x59nNnElE6X6e6BUSsc89cywLqEoCq2s5uLZ2ERZRVem8Iia4fmUxfKIZmJhKpQoRh5SVzzl6dFEZ8zz4UEn7YWoOFvMWDqub3xu2hf/mRZ1233e/P9fhoHfi9+H63dd131f13Xzt/3/jv72f5RTeM3qv8H55/8cP6n/lzla+fkQw2j7k3+RA4UYG+b/0zvS1/YvcaAQlHe+N9S2LsrX1vbPc3QN8wvzdaE6F+oiyWFWNn+SAzXML8pHwaC6UJiAHkAOs7P5U5xz+ZNFN/R1daG6sLNCASWAHGj7+RzYufzxMW+D47oGCJjJjULxY2FUINmK8rkchJpiYgo3MD1reqOw0Ns3g5lOI1t9rj03igDlrJkB7Pw58JWLcvJguKTUCoJpn8kBFBNjGBSGsE64HePoSvLCYCxDRNV1KYLPfC4I0hJhZH0Z64AxdXBCI5HGCCPbsKiMmlvBdMpncMyNHYnEGBIK44DBYzDGxggzJMqVHECmRQVRfH/n7QM4uro68DgCkUggYtFoS6QlFoXGOBNJ3wVSvg/yt7Hx96MezdHVgmpp6UDOxwIOkeTsgEcZWzpgL7t5YbFOvlevUoJsgOz/gD06IH11oaaxBDyeSPSKcUGYmph4v7pNQKU0CC/+6Odvb2NvZ3c0BwnH6UOgUGQsMTHRi0jAmiCLuOjxfxfCDFMkT6/7VP/wg38kPfJIDkzvTDDtAiabzWHzcrxcbxflcycmkrmFUB1dkwjBdZ+nDx/+QBcKjuCMG97w1o+upvOT4uOT4r1IieMTU/KpZFcswggGhcJxp7XpPj41QmHI4Zyxce5EUf5427XYhPj47Oxs9oP2GfniPRzDwdgCaWRkgUAY+vj40Fmi6pqQgzlQSFECd2pqam5YFMEvK+Ow2byb7a3/qnDBEz1QpqZIc3OHM7iq0dHvKeG10tC6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',
    'star|ruby_swirl': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////97q+9fr7Nbk49Hk4dLf38rp2tPd3cba2Mby8p339xvZ2rra2p7W1rjU1bbV1afU07TS0rPR0rPS0rHR0bHR0a3jysrRzbLQ0LDQybLPzrHOzqrOyazLy7jMzKnMzKjLy6bJyajHxqnJy6HIyaHHyKHIx6HHx6DGx5/KxaDGxqDGxp/GxZ/FxaHGxp7GxZ7FxpzTylvmv8zZvr7Vu77VtsLJwrDKurLBwbbCwq3CwqrAwLPAwKnAurDIxJ/Fw57ExJ3Dw53JvaDNuJ3Bvp7CwZfBwJbGu5jAvpHHtpLHvm+9vqe8vKS7uqO9vJS7upi7uaO4uJ+6uZS9u4y9uo29uom9uYy8uYy8uYq7uY28uIu7uIy8uIm8tqu2tqi3tpy0tZy7t426toe2tpK0tZbjsMDTr73PrbjOqLrKrrTMqbfLp7TAsbG8sLG/rrG6r7HBqrHApq+6qa3LspzFsZvFq6PEqJy7s568rp+8qZ/Gr4y+r4zGqIq9qIu/rXXCpnrIoLHCoau6oqu+nqm5oqq5oaq4oKnEmq3DmanDmai/mqjEl6rAl6bAkabFo4W9oYnDmpa6moW/nny5mXe/nUq8kpm9i5+5lnW5lGy1tJmzs5mzsJ+xsZOzrJyqqqqoqZW0sYmur4uurIirrYuuqoupqourqnKzpJ6zoJ20nqOtpJCvooClpY2ko3+foJahoIGdnpSenYa0mqW0l6KzlKGxk5+rl5Wdm46ampOykp2wkZ6vkp2wkJ2xjZytjZmhjZOsmoCdmoalkH+bjnyrlmisjGaZmYiYmHaUk36TkHqOjXKMi3DRgZm7iKC6iZ26iJ26h6G5h5y4iJS3gZKziIOqiJaqg5GviWiuh2ythkWihZCXhIyhfo2WfoqZgnufgV6JhmyAf32QfHKZeISPd4CTcH+NdH6LcHuLbXqKbHiJa3eHbXeJaneJbXKXdECKZ3iGZ3SSZmKEZHGDYW94ZGuIX2+DYG6BX22SV20rGx7/AEB/AAAAAAEAAAAAAAChlCQ7AAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADUNJREFUeNrdmXlQ02cax7uLxjiTJZtIqFyGAEHQlASkIQRDOQOEQxvAgiBFg6VyVQ1yBy1IAsihHEMMxkGuJSuHymFsRKBSOXQUceUQiDgYueumMAP/uc+P7v6xbgBt95/d7wwDk+H98H2e93mf9/n9+OTdf0ef/I9y3ERR/w2Omy39FP13c/bpu9FtEzJjfyeHvi/SVn9nVPPp07+LQ6fH2Orb2p7uaM48feq3cyIj4+MZdDr9VEezUBQV9xs59EiGW3xMJJ1uS29ryRSKTn/3mzjRboWpUSfADT0y+oc2UaYw89THc05EMwSChBMII/JEVHzbvfYWoTBK9LGcE24IJTqSHn0iOibejXFallyXJYz+WD9R8QgFMDExCYkcVztTJ2szd4kkLOUjOUBBzNC/jYr3pJIsrS2MjfUcyiXH/SQfGde+mJhv9RlWJobGOwxJRAIBh8Ma+fiFS7gOvqyP4OgzXD/7zJqqSzIk7SYa43A4vI6uKYvJ8vFjsuywrA/joNEojLUlxXIvjUQk6unokXSJRDKFRmGxWEymvT2T+QEctBZKSwuFIjjvpVAoNLKhhS6OYEiiWlJJJkTmfiYLOKAP8IPajgI/eOe9FhYAcibj8VjsnlRPS1336qM8dyZzv/3+D+EQMKbaKBSa4Ezx8KBRKCQsnuNmJCh2Q2PdpeVnS4/7sJh+vr6bcjAYnKmvASkwKDQ4NJBG9uTs8Sws9OTEA1rb58rZUulfzvpww8M34QgwRiTMHokfz4vN9mLTrD0KC4tLij0tSThtDAqlbcq24YIlSbjDxpzUVM/CVFdBJcvFg+0RCDpWcVF8mWNOM8QRCNpYqCEd79JSP67keLnp+hzUFg6bU1xcWNQr8eWFHgkJDgoNqL0jTyebUyiGeJwOnmCIM/V/8YLF9CmvdpGux9myBWNs6SkuudHXf4vrHxyEKJDXLW+q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',
    'star|caramel_swirl': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////8jm5eH6+KX//wDo4bLh3rTj3Z3i16/k06Pn0Z/izZ7lzpvizJzhy5vkx5PgyprgyZjfyZnfyJjex5bc16fQ1sPQzcTVzYHTyLLIyMTayJvZyGPVxKjZxJrHxMvKxLfcxZTbw5PXxJTZw4bXwJjPwKfHwL7HwJjBv8fAv7zBv57awZDZwI/Vv5Dav43Xv43Uv3rUvJHNvJbTt5jNtZfFvKPFupDFtJu/u67BvJXAu5O/tKy+sKG/tpO7ucC7try4t726uKq4tpS3tLi2srizsre2s6eysbC3sZrYvYvXvYzWvYzXvIvWvIzWvIvWu4vUu4zWvIrVu4rVvIHVuonSuYrTuYTTtYXNt4nDtozEs4rFsYjBsYjRtoPQsoHLsX/NtHHMsHnOroLLrn3JrYHCrozBroXBrYTCrIHMr3rMrnrLrnrLrnnKrnrKrXnKrHnHrHnKrXjJrGvYp4LNpYDLporKoXHIonvHpmfImXjCp4TEnoPDp2fDnlzEmHbElXbDkXG9rqK3raOxrbSxraa1qaGwqbSwp6K+rIa5rI29qIC5qIq5pYC7pXa1ooe1onu5oni4oXi3nYy3nXm2lIG8onK0nHS2nl24k3K1lFWvrLCuq7Kuq66uq62tqrCqqqqtqbCvqLOvp7KuprKrp7Cso6+lo62nnq6qpqWmoqWkoKSupZWpoZCqpXWjn6ShnqOmno+fnpmenYOkmqujl6ugmK6ilamglamhlKaikqShm5+kmoKnmXWfmnmkko2mk3CpkWedmqKcmoWdmXmblJqck3OZmJuYkpuUkJyUkpWWlYCSjovEim68iGm7h2m6h2m0iGGxfmOoiYOdi3KjgnWfimikh0mmf1KSi5SNi4+LiY2Ig5CFgoeFgYV/f3+BfYOXh2iWgmSUgVmqeV6Xd2Ktd1indjmAeoOLdmh9eIB8d355d357dn56dX15c3x2cneKb2N2cHp0bnhybHdyanZxaXaLY1NwaHVtZHJhYWoaGh3tAEkAAIAAAAAAAAAZ3TGFAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADYJJREFUeNrdmWlQU+max3ucChWWxLBdm8sSE8soEggNArImrZFd0oQJO4EOQQJCs/QNTUcaiCJbWiAspgJNrg0KSKKevogsIhImINDTQAPSRSIMIAhCATabOF+c99hTU3XtAHr7fpl5KKhzPpzf+T/L+7zPefnozT/HPvo/yrGrpv4zOH8xMqea/2HOoZMnsYcv5VD+IAd76Nixk0dd6j3d/xAHi6UYnSRg3bsbq9yp/zgHe+JUGuHPWOzZ7lvVEgr1H+RgjxHSTlHNscDuNlZVS3ZTtA+HYped4fKWYk6+e1dSLaly/3COOeUkL8OFDDPMyS5p0u7u+r9Wn5B8KIf8lvKpuTmFDChpBHeZV2GuhPyhelzSMi6RyRRz808/dUnjBhOO+jNIIZyIU7kfyAFayGRz7J/JjnaRDEtfOh2P17cp4MSFxX6gX1gK5YQRwYaIw2FwRLy+Hhqtc9Q5NIITZhvm9AEcAsHWz59BNyDi8D54PBqNxugZWDk7OYWGOjkdN3Z+Pw7SUEPr3+h0up8fEY/Tx+gTDfB4Sxqd7gRAThYWTk7vwTFEIBEIpIYxw5dGowVY4nwM0Ho4YoAvnWh55DggOFnYg5/30IMwRBoaIgHHx4dGozOs0WiUtl96pK9BiLAgJRTWY3H8PTgYLVtDhAbg0JjMAJovURvDDcbx+NGG2iECQWZmwdsYhe7L0dRCW7kZW7ETkhKS4gOso7l+0fzsYG40EqAdzn9TKfjmG7eI2Nh9ODwtvI2WX2xoaiSTGRlED2DysvmD/GBvS5S2IVJD8+gnJmHfVMbFxtrszUnnRWdzg3lC5xAmk8lmx8endJQPDkVbB+DQurra2roobfSXmZmgiDgcm905SAQ3mAteL+4qCE1NTU1KSEhilfx7RznJm+ZngEbrYjA4tE3MwoKzk0OBMFCwGweB0MRbBw8Od42PP4xgX0iA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',
    'star|matcha': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////+Ds+crZ9MHc48vW5LbU4bPR3rLR3bPT27fN2q///4///wDW4JDK3qPM2qvM2p3L16rI1qfG1aXF1KLH1ZTE0qXD0qHD0qDC0p/C0aDA0aLDzqnB0J+/y6LB0Z3C0J3B0J7B0J3A0J3Bz57Az52/z5y+zZ3Az5u+zpq+zZrAzZnNzWa8zZa6y5W6ypW5ypS4ypO4yZO3yo60yoa+xaS5xZu2yJG2xZW1yI+1xJK0x46zxo6zxoyzxouzxY2yxI+yxYuxxYuyxIu7xnayxYixxYqxxIqxw4qxxIiwxImww4mww4W8wK65waW3wZy3wKC2v560wJq1v5u0v5mzv5mzvpm0wJizvpizvpeyvpezwJS6wHi1vZiyvZeyvJexvJSxupe5t4G1r3XCpD+t0o6vwoeuwYetwYGtwIWrv4Orv3+uvY2uu5CqvoKsvIepvYKovX6nu3+ovHiuupKtuY+tuJCsuI2rt46qtoyptYupt4qouX+otYmotYeotImntIiotIOlvH2mu3ylunylunukunumuX6kuXykuXqjuXykuXmluXOlt4ejtn+ltISkt3ujuHmktnmjuHWhuXyit3iht3GhtXigtmmcwYWetGsh+CGns4mms4ilsoemsoWksoSjsIWhsIGqqqqmrYegr4Cfq4Sdp4OaooSfr3qdrXydrHubq3qaq3mbqnmZqXeapnydsHKarnGaqnSbsWSlrFOWrGaUq12VrVSSqVWXp3aWp2yXoYGWnoOVnYGUo3KUoHeQqFmQqE2OpVKRo26Qn3GPoGKLpEyKoFOGn0WEnUNppk+XmnaylzuTm36Sm32Qm3iQmXmPmHqNmHSLlXOKm2CImGaJk3GHkm6HkW2DnEGBm0CElVyFkGyEjmuCj2V+mEF+mDl8kU9tl050kDOMi1mAjGV/jGN+i2N9i2B9imJ8imB8iV96iF96h194iFNyijWFhE12hFh0g1h0glFzglZygVVvg0GCf2xtf0h+eTdLTCcBAAAAAAEAAAAAAAAFxRWYAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADeZJREFUeNrdmX1QEtjex/dWhMvMzVVYJR61i15SvEKmKRKKkQmrdPH1EuY+aDcH1CVfAvKF1WjR3bi2Jtcwxgk1Z9R8KdEoDdOU8AVnxPeXdJV0GjNNdCx1dv/Z59A8/zxd0tq9/9znNwP/MOcz33PO75zf93f47Nd/T3z2H8q5xnL6d3AUX8KcHH43B3Iq8fM/pYb5/E4OFHII8fW1IEGY7+/iwCDu3vxjUNfbwjBfp9/OgSH5itMwK8ARsOKcGL+RA0UcU/NxMCsY1CZHGM2KC/f5TRy3RK3a2wYGwgYlvnw2mnXG99M5Nthj2pZgOAxmi7KxIytyb90SsmLsmJ/KQR1rbQlGoOC2KHsUWaE45pvLyxXEOHyqHm91a7AdytnWGo0JVqivYT1PhpJ5ypwzgk/kqIPt7FA2Vtb22G/4HAKJRvX0xMYqlRUXcj9xXhAXN3t7bKAXDu+IO4rHYFBIpG+cUFSeEXvh7CdwDh0iUCh0mvtRnJf/EU8UCol2wR5nRbPihcwYXzv2x3FgMCgiiUyhBFK98Hg3FzcvLN6TQKFRYmJY0ZGM8KjIs7tzYHuhe/dC9x+mB1IoFBoB5++OOozzovhTCYQjYVHMGCaDwfAJ/wg9+22gMGuoCz0wIACAOCQUys7udAs/EMtrKDsfG8WMYESEfwTH2dbXdj8U5kanJCfTKIFecBfFNby2X2GN5FVWP0i4co4ZKbgg2JVjbe3sJ3D1uiiVSWX5NCJfffpab2+6QmFlBbOLzX6QUFV6/lxmrngXzqMvvINtQsRCeXpSUkoSjZai7dX369NJXiiEDRQK9z3lITyfUCHOjd2Z09p6TavmaxtY3JSkZElefr5M1TU9X0wMwaEwGDgCg/yvg+cTEoSZyuvlsR/mQCHqRIVer+8aK+PJZbICqVQm0XR0PiSBDHB3RLmgnXGH/HIHBv6bGV/RcOL2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',
    'star|mint': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////9Tv5e3f3r2+5uTB1ejT1LK5z+HVzqOzzuGqzd6xyt2zxt2oxtulwteiwtidwdmfvtWev9bMyMvJw8vNxJnBwMjAwLmowNKtwLezu8mnucqhvNCht8qevdOdvNKdus+cvNKcu9Gbu9GbutCZuc6atsu+ur66ub+7tr27t7m2tLi7taCut8Cqs7+ysrastpGessSZscShs72urceyrLSyrbOwrrGvrK+uq66tqq6xqbOvqLOuqLOxpLOsp7Groq+lrcKgrcCdrsGlr7ekq7SasMKYr8Kar72Zrb6iqbaeqbqaqbujpLKao7GjnbCvqqyqqqqqpquopailoae5oliioaaaoqugnqWhnqOfnaKgoI+omKmjl6uilqmhlaiglKickqidmaCgkqKZmZmZkpunkGGVuM+Vts2UtsyUtMyPvM4A//+QtMuQs8mTscWQsciNssmNsMeLsciMsMeLsMeQrseMr8aLr8aLr8WLrsWUrsKOrcKTrLqKr8aKrsWKrcSJrcWJrMOErMORqb2NqL6TqLeNp7iSo7eMpLmPo7GFqsKIp7+IpLuIoriIorWHobOCqcKAp7t/pbt7pL6Aorh+orh8o7x7orp6o756or56orx6ort5obt4or1ypMOMn72FoLeOn6yOmrOHmLiTl5+Il6WBnruBnL2CnrGAnK+Bl7aAlqaJkqCDkqKLjqF+kaR/kJ1/jZ+TkpOSjZONjo+NjI6LiY55oLl6nLJ6mbJ6mKx0n8JznLxyma96lrZ7k7tzlbJ5l6p6k6Z1k6d5j7R3j7d8j514j6F3jLN5i51xjqtyi69xia5tkKZpip6RhJSIhIuCga54haB2gZmigT2EgIWBfYN/f39+eoBshbBog69shaJthJRqgZtsfJtmgqpmfqBigqNifJtgeouFd2t8d397dn56dn15dHx5cnx3cnptdYlgeJtjc5JadZ5Wcpl2b3p0bHhza3d1a21xaXZbbY1zZ3JhZnhjWnFKYIgfHSOQAGAAAP8AAAAAAADqhbv0AAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADW1JREFUeNrdmWlQk1nWx6eooZw0AqYDGYslQSAETLEXQgIMqIFII8ECQkxkk5k0kKqAgQAZowmBAEKQhJZFZVBAkEW0jexGWSIEQbbIVhDROFKAgLJY6Dt+6feG8UvTAXR6vrzvnyLk+XB/9T/nnnvveS5/+OW/oz/8H+UQsIf/G5wUI4PD8N/NgVk5wox8XG1+JwcGM4KbWtkFu9r/Lo4BzMbIygiGiQYgzH/OMUAfKz9qAFNzsLjDmP+QA4Mblx/DwGEGMDgl2A2L28nRHhybo/Iquz8bAMFtKBScG87N/ts5fwaUO3g0YFjD0XblpymUYCwWjftWDvpoF6AchsOt0Wg7QbmxPTkrNwCH/lY/duWAgraBw21s8OW16aYJ5/lJeWIRPuAbOVVH0Wg0HAZH2woK+PEsPpdOt+SIRRWZom+MC2ZjY21knEqPiUPGMmLNzREIqJWfQCTOTMgkfAPH2NgpNTWDi4qLoSfG0REIBBKJSiD4EgQCAsHqIOHrODo6EP2MZC439e+MuFjLQ5YMVFxcPJvHJvgRfH2dnX2dvoKjow3R1oZAkHwWm83mxccmohAWsQxuMjc+PtbRiUAgONs5Gzt+hR+ILgT4QfBZLEDi8c8hkFBoSpcwGZUpraD6OPkedz7u+BUcC30rPQhEx4LPLijgsZMZUGRtHqprKE8Xmlnf9iMpNyXFVyAQ7MnR1UUkXDSLKyktKy0r4THzalPy5HJhbTlA63FqfiQ9bDxzIVsk2oPTpU+n66WIMtt+EgoLMni8Arl8UDkjTI5H6OvqQPToDqSsMySxSMTZnVPblSevTZc/9EsrEBYUlpSUtDX0KlU1TB7Itbm+viX0exMHEikrR1wh5uzMgeyrFdYOzsgHZ8WZbWVlZaWlZddkkge9SSx2KgqJMDdHohCM3ImJEwQ/sfRC3U6cffv06Ml5SuXT2dmn2VdK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',
    'star|lemon': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////8nz88jp6N/q57jk5Ljh4sbh4bTg3sXd3MnY18L//43//wDd3are3onZ2ajW1qbY2JvV1aTU1aLU1KHT06PU1KDT06DS06DU1JbPzNPNy7vPzqvLyarS0p/R0Z/My6HR0ZvQz5nPzpjOzZjNzJfKypjPzZPNy5PMypLLyZLLyJHKyJHKyI/Jx5DNyo7Kx43Jx47Jx43LyYnTy1rJxMvFw8PEv8vDv8HHxafDw6TCwKrIxpTFxZbFw5TCwp3Dw5nBwZvDwJXIxo3IxovHxYzGxIvFworEworDwIzGw4TEwYbCv4DGwnTDvnHJwFi/vb+/vau/v5m/u5q/vozAvYC/u4W/vH+/vH2/u32+u32+u3y+uny/u3rAumq8u7S8vJm8vJO8u4e9un28uX+9uXq7u6q7upO7uou1uZi9tse6tsC6uLe5tbm2tba1s7i0sLSxr7KvrLCwq7Kuq66uq62tq62uqrK6t6a6t5y5tKK1taW4t4+2tpG4tZW0tJS1saWwrqOyr5Stq6yqqqqtq5yvqbavqLOvqa61oMCup7OtpbOtp6aqp6unpKmpp5iooa6moqWnnK6joKajoKOhnqOgnaOin5mdnpCgnZqjmKyilqufmqadmpuZmZibl5y4t4m7uHy4tYG1tYq1tYO0s4CxsIKvroGysHqvrXyurHutq3qrqoG+t2u5tWy8smK0sWqxrnOwq2W7tFG3sE+uq1S5sUW4rkKzqz2tpnOop3mmpXuiooGfn4KhoHWenoOinnahmHObm36ZmHS0p0aupUatpEWspVC5nz2sojynpF2jnlmemFiimTyhmC6hla6hlaiglaedk6yhlaGalJyVk5eekaKVkJqRj5OQjJGOiJKclHSZklWljTGUk2+SkG6UkEmMiouOjWeIhomNjFiJhk6QgYyZfiyEgIaDf3uAgIt/f3+Ae4KAei59eYB8d397dn96dnaAcml4c3t2cXp1b3pzbXdyanZzaXhzaG9pZm9GP0a/AP8AAFAAAAAAAABySF/+AAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADZJJREFUeNrdmWlQk2m2x3sEbkarYmJAMsMaCPtABCQNshggAZQkgmgkAw0YIcIYQMBIG8zIYrGUCJElNAo2SOgY1jQBAlEWAUGCIDBCRxjAsNgwVSypDsvUfPE+8XZN1bUDaPd8ufdfJCQf3t97zv+c93nP8+aL9/8ZffF/lENmxv4nOAEoZ4bLb+bokf31DG9di/2NHKyemz7ZiXUvMeE3cbB6sTZOdtirD/MTE+J+Pcc5kBLu/yVWD3CYt+PifyUH62IfQIl1xmKxXxbnJzFvJ8T/Kk6sn1h44wqgYJ0ZxcXJzOtJCZ/PuRLr1yJkAYpLoPMVVvg35eX5TGbg9c/lMPyaAYXh4sJgMFLCA+wTOLcy0pmMz43nnLAZUBguXzLiWI0B5BMWeMKxUzz2jfTP5IBYrjCcsV8GRlwgE6zcHe3NzYw9eJWVNPZn5qUXFxtoeAJjYWp61NQcjUQiEAhUEI3No3nQvD6DY2joicEQ7E0sTc1t0WbaCISOromFF84riIbzQsG9Po0DgWjB/O0dHDF4KzTaSNfI3ASNtnbAO3h5eeFwbm6uOM/9OZADkAMHtLSQPhgHBwe8lamtiTbSxNwB42hlZYbD4by83CLOurl9QjxaUAiI56gPxs4OgAjWCG047LiQhDE5XcN75I3zcnVzdf0Eji7MAqalBTHycSAS8Q4Yc5huOBnd0h4OQZzn84SDlUFeOBqNti8HCtW1uGhsTgmJDImk4m3IQn9yexspPByiBYF7/1U4yP++MSi6kr0Ppxl67Dj0eCWNTiISiX54PFHc1j7wnGRrjoBBgfeo4wG0hkHQRR57c5qbz4iFZLHAy5foR6QEU6lRT1ul0jAbAvAaCYODHtINfz5Ii+ZV8jx252hpCv3D2/vbW/t4NHokPTQkJJL0pLRDZA38NtHW1tVBmupaXJqd9fYK4tWcrN6No6kJM7MhSQe65uaeRV8AFCAqXd53n3PezhKpbYLUtnIwq+MNLYP+CWJX89VzYJoQhI657fGhzu6+vt6O7/4cSafTQyNJkrnS0u76GGNtO4y1A2GorqZq8BzoRC9PmloOFApDGlnZ+Mjf9XYC9XY8Il0g+lLoYVGlpeBrb4eIaO1oVy0fquGTD4OmBn9qOHAoXBepY2wtWFtb6+vs7ezu7K4nCRsahANSqXSoU4VekNfgz/OG5Pw6weHzF4OiPb3UcKBoIyNjxB+G19be9X7T3Q0yGR559WrklbS/tbW1gcLvAiT5Uu9FNl8uf1lPvsRjR0fHqOHY2tvYWXp0zr2Ty3tLS1WGCEWiMLwZCmXgUWMGgZhIemfk8rkM7+q6oZG6Gj6PTfMMUsPBmx7D1/f29snl8mEVxgNhUoXSghzUOKhh0GgKOtmkvm9m7mnHxejoaPkwv6aLz4uJVufzkccdvd0La2vyPmBNr4eWllmjOeAcPPhfKIoRFGZlF9XZybe+lOFxmt20PFJdW/u4kqeOU/+2D7iyJJfPgOJ4wuFaZnQbGPT3ENhRpDZCF+lgfenp02OO1qd97WLYL1+JaJXV1TVq6/6sV+UuMGGmtwNtjkYgjRC6OhAtqA5C1/SoMd6/qq7uOxtjXTsHR/fKkZHv2JUxPPV92NFZer6+Y+bd2kKnHwENhwMSEgK3cbDBNJLJVGqTpPbJaZixIcrR0XNoRMDmxbB3uS5KUy3doejGsPp6cFJ7gpVPcDAlkt5oqPFHp8NhlKYuUd3jMGGKgQXBpuolj82v3iWe9zHmgpeipipLHwwx5CungEMaBvSQEArdQONgwOFQSlNPTMwLabvgrIGNo3sNn82vrd2FY2lT+b1I9GJgSCIIPuM0qKFxgh4cEkw30JcMquIZdj/UKu0X89yM8faXaqv5NWo5Lr/TtKZWsVWqrHsU5eS07OpPigwJCY0Kn12edVJxTuuzpAPtwhRDM2Od6rpa9RzGoQOaTS9fDIi+FwkeC6ICnJaXxWGA8+cop0HAOQPy8najDUj72xujmo/DLHbhZGH1NTXhun8k1YlaJU8FFKHqYOqHeMiqj04XmoY416taRdKh/nZxixHc/UmNuv5JcIGcyHE7pG8IhUJtjvlHCWeXlwHnqxBqJEk8O+gUcKGp5+TZNAGuPosjbRGHwxECiUQNh6EPvZGTl5+fFxsbawhzjxIODooBh0ilB4c5BQjDVPWy0IpIDYq4kyVqb2k7Djfu6lHDwerDbjOTEhITrl6Nj42PpgoHnZwOU+mtsy+IYZFRlMiQsKZhjwNa6ameaVlZQ+3iZhhU3Tqfd+PQibzrifHxSczrNy/feEQNpYeFUan05eUXFDqdSg0Oxlf1CCprujODgm6DzIQG4I6rhnP3+RG3PGZiYgKTmXQzXiCkgLvFo0jKV7ODdF8i0ZdA8A+nP5Z0zXELWLTU7Kz4WLdDEAj0lxx2u2kik5l8OzH+aqqA910jheSHcTBDIv/ki/H19WsGEtLZ/MpKVkImKyY9i8GIMAQg2MecrO8DThTlJycmg8xaWvzxPgRfotFRc4I9kS4E8icQCFYeQbgh+VDG1+m3Kj+A9CGaBh9zctrJlytKkuLjmczrtXXBH9TY0Dow8LxZxSFgMBjH8zTeu6WlhYVvMniivDhGnL5+5srHHJHYtKCkKD4+ITnpLiczik6PbBSC+8SAVEg5BYQH84vlSd7cgkpvJYJWSVacc9LiyuJHHGlzg2lRSV58fGIyM5PDaZUOgLsNiINOJ9qpZKKDNNK26ALBvJ0Dqm9tTLz2959+mvzYZykddaucmxx/FaTF4WQMAPULiaf8MBjVGEVwRGprH0V49L1b+hDPXB8viLa0tjA1/zGn7bxFZklxclIet+guh5PaEPpVaKifGRqN1EaD8dAMjTQxMjpCfbL07kNic3OciPqfFucnP+4fabPryYqKkmRmQUkJh5NZfwpMFw52YEDVRuqCRR4BJwcACR/3qKJ5+7Zvri/i29X5+V/MP1ISKkMmqyjm5uXlp6V1L/l+4JihTa3sTRFGJiaW4v5+cctwj+StKhigBc704ryaOeq00TcyWUkJl5mUGBExt+ADyuND9PcnRgqirKOe1JLCJZIqu/qunr6+nqcqdXDm1c/h+PzyiqKikqL825cjOt6C4x+RBF2S0KYuSeQjgSDE1tLS2iEmhsevf1IXQ4uJif52t31BgawCYJKYETdu4Hq7Frou2foSH4VSSaSwMEpwsM9JIB9fR8zD0u6nT/i0mH32Fznv026m4HB9z45ZHrfDUELYGampt1JSUs55e3uj0GhT44eyomIOp77rk/YpZztKUzIy0rJzcrKzsrISU1LSXA0MUAbaOqbmxcV5ReV5t4s/gQOOzS37299G72RnZwHUnTQQjyvqBA7n4EjwLeaCnWVBQlxgxL6cwtzcwmwAycnOLcwF8STcAHmdbmhosLWxci/hcguYYKm77GJ4Qn9vzvjY+Nida9eyR8te/1CYIalrAuPz8xZxW1t4eHjD5ASXm6xaMm+msvTd9uSMPRgfy71XWNgzPDKiulxfSESSF+DS7xeLxQ0TMm5xAdjrAk4GznVfzuvXryte/axndzl3+SJRU7UPwd59QlbxELQrM/3mORYtaG9O2djrkf9RD1D3XeDzLR4YKvF4x1PT029kP0zk383MvMWKqdzbn7Ky12BSfQViGh0dLSwEnDSWt7entzUabTH94/T028nyopmOjAwcbU/O6IPx16pQxsfGfij8+lp22tmzZ11RBigUUgfxh+nppX/IZ2f65CO81P89hv+C0zP8auT1+OjoWOG9wtzs7Nx4Qzc3QwMgOAxu+W5peW1ZLl/mdPw1Fee1J2cYmDJeBmqWnX0tOzv7TsLlyyk4FOpUA5ksbFteK/37jJxbyslkXdzHZ2DK6Nj4+BjA3FH1NEckGZH290ulbc3hDRPz9+9x73OLOBwWi83bp14AokrqXu5oblZO1jOwO5C2t7WJ/W0t3GUyLneihFucls66uI/Pqv7JvnMnZ7y7p+eZZEDVgQMtZ840nDkCO2L0448TFWDFK755E3Bw+3LuFY6WjYDiDz971iM5x0o5d+7WOdcMTkbKG9lESX7JJ3GAx2XdqgZ8MPZAdd2Xf3v/bvq3sffnV1YUskQG1gWbX8TNTGexaHvnVfagbHxk+dXMD9PTsvn1ldX1jfWJifJ7yp2t7Z0d5aps4qrL1yWZmay/7NPPb2SyiTd5Dx9Mb2xsKRWbOzvbO/8C2lFpU6HYXJlP0ADS07+4e71WribNLy4qp8uLFIqtf/5z52dtbyo3d/4tpWJ1YhLLCEyv3z2eAu7K+qpiG5x++98MhUKxsbEB3hXKLYVye0fF39panS52uZqA3WN9nprcWF1cWf85gm3lBwh4qd4Viu1t4NP25qpifbUwkIHF7rHOu7hMyaZWFVtbm1sf4lEqN5RKJfi3vqH6sFKSfy3RWc/ZWU9P44s9n7foMea3ZRPrq5s7wF7V6ZUgWeXKytQblaYmCwKTJ8GdMG5lcf7h4uKbxfdTU7s/18ornl9f3QCFnwJTdZzzlbypqfl51Wt+cVW5Mjm5AuJTbG5ubOz3fGwioeS9HpCqyuDrJGjEFQCaXl0FfFDbz31OGzs1+WZyUXUwsOg3PDdeXFxcV26s/3/9vWA//TcY2C0DJM3m7gAAAABJRU5ErkJggg==',
    'star|salted': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////6rk4ubY1NvSz9PY1H3MydDLyMzKx8zJxsrIxcrJwsvCwM/Gw8fEwMXDvsTAvcTAv8DAvcHOwmzAusK+usC9ucC9ur69uL+8uL69tr+6ucy7t767uL27t726t726tr66tL61s8K8uby7t7u7tru6try5tru6tby5tLq4tLu4s7u3t7i2tbe2s7e0s7e1s7XBtofErsW2rrm1sLm1sbW1r7i0r7e0rbizrrqzr7WzsLOyrLayqrWxrbmxqrWwqrSxqrOxqbSwqbawqbSxqbOwqLSurb+uq7yuqbavqbOvqLSvqLOuqLWvp7Oup7Otp7StpbSzr7Gxr7Gwr7CwrLCvrbCvrLCvrK+vrK6vqrGurK+uq7Cuq66tq66uqq+uq62uqq2tqq23rIuvqLKvp7Gup7Kup7Gtp7GuprKuorGuqK6xoY29nkSrq8mrqbysqa6rqK2qqqqrqKqasMqnqMOrprOmpr6qpq6qp6qopamopaaro6+ppKynpKmpobCooayhor6ioLmloqykoK6mo6akoaWjo6SloKWjoKWioKWYmr+cnLifnbSpn62on62kna2lnqiin6Wmm6mjmqegnKain6Ohn6OhnqOinqGgnqKkm6CgnaKgnKKfnKGem6CdmZ+ZmZmkl6ukmKijlqmilqmilqeilaihl6uhlamhlaiglaihlaeglKqglKiglKedlq6flKqZlq+fk6edk6qbkKyVl7mVl7WSkqyQjq2fl6Kcl5+al6CalZ+hkaKcj6OZkZ6blZmYk5uXlJiXkZuXkJuYkJSUk5iSkZ2Tj5mTkpSSkZCRj5KSjpaPjpCOjpmOjY+OjY6yg0yai5ORi5iQhpWNjJGNi42NhZKKipyLioyKh5CJh4qJgo6Dhr2FiKyBhKKGhIuCgI2EgYWCf4N/f3+CfoOCe4Z+e4V/eIKIeGN8d394d4d7dn55dYB6d3x6dXx4c314cXx1b3p4bnFybHhyanZxaXZ2Z3RoZm9hWmAYGR/lAOUAAP8AAAAAAAB2nplcAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADaZJREFUeNrdmXtQ01faxzsQCCAhllsawbwY2BiM2DBGoBBNbCNU+FWqlMqq0ZpCGna5yDChJCVBrMmYrgQJF9MaYpabCpqwIOFeMCTDpRAui1wCjEC6sExEIQww+5fvCe1fNoC2+8/7fmfy5+8zz/Oc73nOc07eefXf0Tv/RznOl/f/NzjO9kj/d/8wB2bv7GR/IHbvH+TAYS4O9jAfwZkjf4izC+5tD3REwY854v/7OS67vbyc4Qj4IQWXzvAL+J0cxG5nLy8fpKMjHCHhx9EZRwJ+F8fbi431RCEcHZyQfhLpxTh6HPHtOb4+zmw21gPhiPR09fXxEsqkfDoddeltOSjnFDYW7Y90wfj5eXo5O4dKeDc4dNTbxuOJZWN9/4R2QeC8sRFe2H1HExIpPJnkLOctORFYX19PF0eEx6FjJ6OCv2JFBQfhL8hkd/m33zIvOA7v6UGIJJOC8KRgEg6HRqOOMLgiOf8sn/4WHB9PMgQlMgnBpBAKKQiNRmMwhOP0ODqHS78Y9ptqb8FxcoIjsyIhKBIKIZHwGHzIARKJDDFP0S9/ERdHJH4e+wYcR1sHW1t7ewwLcCAm+RCNgPYhkL9KgMhk0pnPL1ymBwQQD4a9QTz2Lo5OCDiaFUmlQtCpRPJeDBqFZZ+ECDxNUVL653+OIX4W9gYcH2Soqz3cEZ8I5eUxoQQyGhOB9QFWQnjwFI+Hk7/PYMVyuZwdOUgX9AUOIaRUqVKqKqIpqRHYCDb7ZCrWAe7kml70ZXJbUlKmQFq8A4ft4oNFffAdv64gW3wrKzoxj52So845mXAU7e7iCHc9Fuj2zZfJd6WSHeqckvIxOwXLbmVk5WWLSysqKupac9Xq7PhTBDQO5+qB9/T0DUxO/kYoK5Ff2JrjAIs4nZpzk507K+XVqVRKZVVVRcdP3TWUj6BIgjcg/Q8Bfez75OEvLqWVaFl3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',
    'star|rainbow_swirl': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////9/o//bq6NXQ5/Hy7rni3rze27nb2rb//3X//wDf3nLm1LPf0a3d0Kzc1rTczavX1LvYz63gz6nczKnby6jZy6je0KPWy6Dc0HDeyK7ayqfayabZyKXXyKfXxqLXxaLVxKLYxp/Vw5/VwZ3bxoHXw1vNx7LOxaXSwZ/JwqPSwJ/Sv5zPv53Hv6HTwJvSvpvRvpvQvpvLwZTNwXfUva/SvZrQvZrQvJrPvZrQvZnPvJnXucPUs8HWuKDPu5jNvJrNupfJvJzFu5rIt5zNuZXLt5PJuJPMs5DGso/EspHHtojFsYrTvGbStmrKt2zYrKHOqqvMq7DMo6nGsJHFr4rHqp/KpK3Dr47Er4rDrorEronDrJLDp5rYqHjMp37Ip3TJm33Lmm7HlnbDrojDrXjEoWvElXK/0dK/v6C/vaLBvY2/vKG/u569u6DAvJTBu4G+uZ6/uJXBun3BuXq/uHu+tZm/tJS/spO9spW9r529r5G+rpC/tIe/s3S/r3q/rXu/q4W+q2ax0uW0wb+1uKeturqxtaqntbO3tZOssLeqqqqyr5urr6S5rpG5q4+wq2igwtadtsOesLmWsMEA//+KssmMr8WHr8qZrLaMrsOErMS9pqi2o5G6qIu6qIe4pYa1pYespY64oaCyooW1maGroIekoIejmY27pYG2o4C4noG9oXG6okqzoXeroXmrnHy2mHukl3y5lWWlk22Xp66MpbicnYuPoKWGpbuIorWGoLKYl5qHl6KbmoOZmISbmYGZmHuZk3V/psB9o7p7obp3pcN4ob1+n7R2nrx7mqp9lKR1larFjXG+imu8iWu7iGq0i3S2hVejjniYjXubiHShiluhgWOVjIGGjpN6jZyThm2SgmiEgXlxjqFyiZlthZVtgZFohJdof5FagZuufGGlfGSuekqSel9wfIJkfI1ifI5he4xgeoxfeYpfd4hcd4mndVKDdWFadYZXc4VVcoSKbltVcYNRbn+SYDZmZpknKEjGAA0AAOEAAAAAAADr3fWdAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADRhJREFUeNrd2XtUk+cZAPBt2oRzxJBB4uUkXEK4GAsiyEUTMAQKJBjEorQkcUvTpGNFQCIaQhPAxGo9R4RhOULBAcEICGVLkEuFgigGKNdQiDJgAeUIjJswQNq/3PPh9scsEF33z/YcOAk55/3leZ/v+d7v/T5+8fK/E7/4H3WYNyL+Gw7Tyy/C72c7voeP+Xrd2DSjN3F8fSN8Dx9+/9aNGz/LAcbrsJfvh7dubZKSacfP7wP+MV/fNedmxI3/0PHzO8b/4EM/cPyQfG5uNDcTTsQxoeB9RPH1i0CcG/+J44cox/0Qwy/i+Mlbt9YqdONtnYhjAsHxiAg/v4iIiONM/uEPb/3m5s2NKr2x8z4fUdaY4wI+0+tdf5pDSIbsg5tv6bxS4KBHnGBSHVypVDLZ2j9DLj8je8t5gRDh5XXwXVv7HbZkOyIBh8PuFUtk8qSAwLi3cLy83vM4SKdak23J7iQSDofDE6xd4+PjJJL4uH3O8W/mmFmgtwd5+Ph4HCST7Ih4ItmaRKL40Khx4rj4+JiY+Ng4047ZFvSWd9AoGzo4PjSKrbs1jmBLPuRBpTiQgBCDE7M35g3yQVmgLSzQO+ge7u4AMVygMBhvAdPDOkSVoTgdExeDhGkHv32vJQptZkP3CQ6m+XiQMXg+007YHWmBDSnIVFZmxMfHSs5ITDrm5jhXyR5XNo/H4bFpLkw+nRkdzeRFotFmloHJysqCr8+Lk+UyE47A3MHbwluWJGIFBwcH0WjBQmF3bzfTlYLFWJihMRRHpyRlpVwmC9jcEQiYQj5TWCQOBIbFZrNFJVq9PpJCtcURCBgMAYvdGV5ZmZQsl8sDNnbQKH4wr7unW9ufcUYkEvE4HC675F5VhZubj48tHiS8Lf7dqMrJuHhxZpF/wUYOCoUhuTL1+qoBQ1VyFCgQbNHjwbripP0OBLw1AUfxIakz7vwY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',
    'clover|vanilla': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////+PU/9T29tnu7s/o59jk5crh4dLf38jd3Mzp7MHf4L/d3cLx95///wDc27/a27vZ2LvV2LfV1rfX1LjU1LbT1LTT07TT0rPS07XS07LS0rLR0bXS07HR0bHQ0bDR0qnWz7bRz7DQ0K/Pz6/Ozq7NzqfRyrLMzLzXw7XMzKjMzJzNyai52Jq8zJfLy6i+y5bKyqXDypzJyaPDyZrIyLPJx6XHx5/IyJ3Ix57Hx57Ex53HxqbHxp7Hxp3Gxp3GxZ3GxpzHxpfFxabFxpzFxZzFxZu3xY7ExLLDwrXBwbfBwbLDw6nCwqzBwazBwanBwKzGxJ3ExJ/ExJrCw5jEwZvCwZzCwZXBwJTAwLPAwK3AwavAwKvAwKrAwpW+wpebwmvQvKvEvZnBvpnBu5C/v7S/v6q/v6i/vpe/vI2/vYa+vqu9vae9vaS+vZe9vYy+u429uoy9uYy8vKW7u6S5u6S7vJ26uqO5uaG5uZ28u4y6u4e7uY+8uYu7uYu6uYngrq/PsanKsaDKraDOpqbOoKLNm6HCt5++uIzBsJzDp5fDpJq+npC4uJ+3t523t5y4uJS8uIu7uIq7uIm7t4q6t4i5tZi7tou5tYe6rJa6nZK2tqi2t522tpu1tpq1tZu1tZqxuou2tpO2toG0tZO0s520tJmzs5izs5ayspaysoywrpqvr5Gvr42trI2vroWrrYirq4m2qqGqqqqrqo+qqmeup46wn42nroWoqIqnpoqlpI2lo36hrHt/rU+hoYeYn4CfnZSdnJGdnY2cnIydm4+gnX2dnYGcnISam4yZmZOamn6ZmWaAm1vNlqHGlpvHkJzEjJe6louylo65jpGdl4aXl4GWlnyVlHyhjoeWkYGSkn2RkXiRkHGOjnSOjW+NjG6Mi3GMi26Lim2FjGZgkTDBh5PBhJK9hY6fhYGJiGqIh2qHhWaFg2OEgmOEgmGEgmBkgz29f42nf4WKgGl/f3+Bf1ZsfUW2d4ScdnmpbXtjQE3/AIAAAAEAAAAAAAAb9lxMAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADZlJREFUeNrdmXtUEmjex2dOZszoOYoGMqLUSHhhO+sh1oHYHORVeM0LO4YXMnRh1qX1iHdXNIfMe5momI7phNJUIIkXPJy8wOoxzKQps3RNG7xylMTryTl70n96H5rdf1zUmtl/9v394eF4zvPhd3t+z/d5+Ojtf8Y++i/leLE8/xOcS7Z2Lp6/mmPl5QWxPR3q+Ss5EOvDtl5eHvxAn1/FsbF2s/P6HOIj54f6+Pxyjs1hrzwvCARwMljnPYN+IccG6nWJ42YPsYXYifl0Fjcw6BdxEF7DhR4OthCIrb1zoziGzqL7fDjHAeVVXMQBFKgTFO6RJ5Y28llcWMiHcuBeRUUcuCvUztnV2ePSJS+fbyO/TWe5fKg/XoVmCsLODongFOZx3PBUGjFTJg5J/0BOIQcOd7KD2MEwYSVhuAAa2dsbHSKTyDMlHxjXp0g0DIYh4bDuR9xxWBTKyQnmw82okGaFZMR8AAfliieTGTQMzh1HwGKdnJyQrphTLDqLx6fH+MC478exBUUKJ5PJvmQcFot2ReMwWCyeTCPHxLDo9KCz0aEx+3MgByAHrKytUQxfAKLiMQSMEwqDowVQcHjvwFA6lxUUFHQ6+D38sYZCgD9Ihi+JRCZTGHhnZzicU1RCwkS2Vjzp8vkq+Gxw4HtwEPY+UGsIBM0gM5kUcgAOjizM8ygeybODZcpbF5486Qqk8xPT9+XY2zv5px/DpQiqBFWpFGJJISdveLgkPw/sjcOJWU8WFp7IeFkNDftwiu09OA6cO5k1cVFRzHAKlVk8PLI4UvI7PNzRDgJx8M5cWHhc3iQRh+zNKSrKHy7kFLeej2RGMVNSU1OrO58uGq8QKSDXKEdHFByOftJ1OkMobZL5786xti6MKBh5Nlz/gzSxpuqaSCCoSr73qL+eSCT7YhBOrkgUBoFRPLn5x694Tcoz8t041lZQ79+V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',
    'clover|ruby': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////wD81eLo197oyNS41bKkyIDlws/Zv8mrwY/bvMnXu8bVu8XVuMTatsbUtsLWscDPtcHRsb7PsL3Cs7m9r7SWtHXmqrXRq7nPrLvOqbnNrLvNqrnNqLfMq7rMqbjMqLfMp7bMprTLqbjLp7bLprXLpbTGrLfGqLS9rLLKprXCprG7q7G6pq65qKuqqqqtrHiTqm7Mo7PJo7LIorHIobDPnKnInq3HobDGnq/HnKzEoK/Fna3Em6vFmq3FmqrEmqrEmqnEmanDna3DmqrCmqrDmarDmanCmanDmajDmKnDmKjCmKnCmKi+o667oqy6oqu6oau5oqu5oau5oaq5oam/nq2+nqi5oKm/nKu/mai6mqa2o6S3oaq4oKm4n6i3nae3m6a3maS1nKa0maS0mKOrnJSDnGPQlKLUjZrGk6PDl6fDlKPCl6fBlqfBk6W9lqe+lKe+k6W+kaO+kKG8j6K8jaLtforRfonHgY7HdoLCiJ3AgY/CeojAdIG9ip+7ip+7ip28iZ+8h567h5e9f5a4lqO0laKzlqKylaG1kqG1kpyykqC4jp20j5y4i5y6iZ62ipq6iJ26h526h5u5iJy5hpy4h5q5hZq5g5W1g5S2f5O2d4axlaGxk6Cwkp+wkZ6ukpykkZiwkJ2vkJ2wj5ywjZytj5ytjZyqjJeuiZiqiZeshZWphZOmiZSmh5OnhJKsgJSlgZGqgY2kgY+pfIundoWbkJObjJGhiJGZiI6dhY6XhYydgoydf4qXgYmde4iddISViIuVgomUf4aAf3+Ej1RgjTGTeoKPeYKPd4CQc36Lc3vJa3e/bXvIZW/GX2rBX2vCWWW7bX25a3uubHm2ZHarZG+yWmfHU168VWO8T1y7UF6tVHmzTlyqT1euRVWtPEv/AP//AADMAACWb32Xa3iMcHuManiKbnmJbHiJa3eJanaGbXaHaneGaXWIaHWFaHOaZW6IZXGEY3CDYm+DYG57Y2yPXWiAXWuPU1xlMDcAAQEAAAEAAAAAAAAAKOOCAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADexJREFUeNrd2XlU0uneAPA5k/eVG2OiDr5iFlCI43ZPLhQqvHGViYpQY8hRu7lijbuJ+rpkWnRduuS+5QYl4opRuYRSYHKUUHM3X/Sk/VHk0s39OP7T+9B9z3vObUinmfvP+345cI5/8OH7e9bv8/jVh39NfPV/1En8weJf4ST++zcWBr/b0Q0NhZhE2H77Ox2o7gGT0P8MC3a3/l0OdK/90cSfoNb1THfr7367o2cSmhiqB4F8V89k+FvAf6OzV6PY60P1oPrcEE+Gvw38NzmHQkeSjxro60H1DA7yuN6eF85af7ljcCh0aDDM6Bs9QzOD/T8l5vB5zLMXDv7wpY6ZRtl/2NAQeRB5NDHxJ3dODCeYYfGl+RxNBspBlKE+6lBY8mCSPf5UpHNGHdcr8AudwZ/270caQvXNrMJSwp3daFQ8HuvDr6nP4H7hc+1Fm5shrE44OeIPO+BxGDTSDGHtz+TwM72CvL/AQZk6UyhRNKyTgxMJh0cizVBorBuDzghg0r3d93v/OkdPD2IYS6ZQyBQnHM4cbe6ExeEIFNqZc+fO0emWNnQP/90dPR2ojs5eyOEo4FBoBAcSFmnu4HSSSHUi4N09zvqdg8Nt4La/Ip+9BlA9fSgyikwiUSjUKKIZcv/+sOcpZPsMIae3w5pua2Nra7O7g4a5G0GgUEwUhcWiUr53MUInJx0b+q9EfZOM+pa+3t6L7nRmUPCujj7sgFewlVN6QVFBcR6VkJIcljQ8nJKaCIXoGQXe7O3r6xUEZ/G4uzhDsKNhBmG1QWUJsbHx0VRa3NDwqGo0xc3FDKEPhRi5BPX1XbpZV8Pz2dkZHEoaTk4aar4Qw4qNTb+Wd624dVw1fcUt0gFpjkEgzE1NrXo7XJjZ/Npan887kL3Jcamjo6OTCv75spKSwoKC4uuip08qiccp3zsgkWgUygGFb+i9+BevgDqhb/3nHIiuEd4tZUbV/WzgSVYuUEDk3V5VdNzNcHVGo7AYJIHiKBJcsvs3W0//bEGTdsdQVw+BciKGT0p7FPKersaC4qKSsqLihLbXjzqfijlWpmQy4UT4hEh4x9j4T5a2DG+mVgcGM8KYE4hRq9tSTfQ8zk+Ij/VNKCrK7XgkkfTIJe0s59MkwWz7vUY7Yy86neF+VotjCjNBY1BYQvn29rZCIpVIpE9bUq6mXh1TqVQzE9IeiUTyZlvoG3SnfbZJKDYOCQjIOuutxYHhrMyxppgXgJF3dEo6Op6+mZubezk3PTI+Pp6a3iTrkUpWt+TBnKapqYlmu4s12czMbC0O0ZVIOvZj5+vt7VVpB4in4rHx8ds0HAZj5CV0gOpj2+Srq6vKuwH1Dydm73c0CKqZ/gFaHJr9cVpLT49ia2vrTSdoEHeElcAaoqero7PHrMIR8g3CXqxYVYi7gkOymFMvGptlTTxOlrZ2Nrkn6el8o2mdTmlnz497IbiKYxAoBALRsUrHGBoSjudLJA2EnLvuMVVtc1MCoVBYW6fNuTfwrLOjY3V7a1Uq6fEyQUBwJUQjQwjUEIk5YIoxP+V867HYmeocE0W6WfVitp3Jq28Uau13uVTy6KnkI9SFd8KZYczN0Cg9iD7SFGVtan+alS8SNRKxh0gUqlfO7FQjl5fN1z4OOyWPgsRdq9vbbySxkTiEKZDQegji6f/4UXzkSC77vkzYmmGEsXI4Q3V/MfuwqjaT+5l50VF1zAeGK78hFpOoZ3x9naLSr6UVlVRY7PmjnXH+9fvd7Q+bbiSfRjlFEvJf8LmNjZ+bX5n48onK+znOMb5xhcV2dpA9RrevFaTdNvhqz6WPzk3O1MxokiOaQPURNmU3CUWfcY651VRWVk5OTbQ3sy/a9e75yqLsWsG1CoM/GPdqnNe+BpMzo0MpVlia6y1R/Wcck691CSn5VdXglfOwkX3kUt8f/nhLs3Cwj/T19dnlgnxiDIJUqtFk8mEHK5SgVdSs1TmwT2dfxcSLqYnKyvKWj07fpXz2/zoXgXPe8vzIjGo0NWkoDOEi0u4Q9hnt1UVY2d96WDnR/rg5xQ582Tj3Yz4XNc4R4DReyB0fn34+Mjo8hEX4tDZrGz8uCL3v/A7q6ZvBYDCiM4v9P05pAbvw2qW+Xrsj7PvdPtYXyj1SyVdmhoaTD5o2t7VpcUyM9N39AoKDL8DhcAt9osa5ZJzLTmGXsvONj9jlF6fd7/aCWIYEWIYTnquGhsP2Y2XdWpx9hob+DM3+BrZKG3gQ2+6SsbFxbqm891JCaSGbzS4sAI4OhFl9zseVODk6PGho6KtlnY87Cv3Oz9sGDrdlnPO09bhRmA8il50PNqu00uLc3Lz0M43dzbx7rRy/gFinFFUyAgrdp8WJGLG3BvnYWtIZdLrtlavpRSUlZYVp+X29F6NZrAgQqRX32rpf38kOZHJOEXEoM1B5wn7phI7ibEEx6m8Lh5+/cuvGlfSE2NOnnTCoH6NOxPjGDoJIvsFtqs0JtskK5GY4m6HMEd9A9yE+db4fTLbODvG3YdjCLZ8/jzgTGRkdiznsFEFl3b4KIiI8ItzFy58+MTtRaxsUwotxRiHNjaAQ5KdO9Gioe30NQOh0z/KKvHQQeVdTJ1WqkUGNQyWTya4ZIXWbm2vL6oa/8SsjsCgrhH5V/6fO4BAum59tCbfx9mRyqwrKyoqujE9PT6tmxtJjL1++TCWRKcfO1/WvLM4vLA88vD1eSUDDfBT9ik+cmaFkx2xBAOgtb3pWTc2kZq+ZHhsbKyuLI/8ZhAMajTF1ka0sLKmVyn5189UKn+PtW1viT9t5OgkTw6/xg1syGN48bo5KE2MgkROgIKNF0k6ikEjUQa/XP28sLS4sqpXP/ubP3Npek8g/dUbD8De51X6eAbysLB4/469FIC7jcDjMARyNgMPjUYcOYQ/daF3bXFxcWlpSDtyFN2zK5eJPx8/MoOPJhkaBHyOEXysQZN+LdT158iQJaQYKVBQods0OJiYnJg9ebep+v7igHhh4plRY3h2QS39R/0yHWt168KCxmhcQEOJ/oXU5ClSFFDIe7+jk6ojE2mOPDY2MjAy96W5Tr/xdqVQOKOfvShVyLXVU2IFmkaiWzzvrCcahcsGXdJwSGR0dzSouzyXmtAoTrrS15bvek3W/VnQ/Fnd1dYnvKLXX4adicxo5HH4284ItvEXNKi0vTbsvaysES3teaXl5sZvTMcL3mZn8BvHjVk5mJieo5XPnglsPGjl8jpePhYe7h1T2VnbreAyrtPh62vWSwrS09HAaiKgo2snmlq6ux02Z1bucL3w++DO8PT3lcoIziXQ8rSCBFcdiAYJCJpNA9zmYN4oy+XUNYtmvOqdYi++djgOFMy2SQiRpKnEaHok2B7WhI57DDczmnffn/gqH5EyOSisoTnClkIkUanh4OIV8guDo4OJGoUZGgZMl3S/E2uJb+K4O63R4nCt4lMjTUawoggvBhQisiKTUJDcQAi4v66wnw9vmWwvrb3d2StglxVQSyTU+vex2HKjsUsFWMzI0PDycmpSaKmri8fw8GQw//6pAA/iOTkFacR4tNjZufGpubgZMVxWYryPTYNsaHh5KFYpquFlMbwb9bDbfw3Y3B6wbZRVzr+ZevQLv8Zj0y38dH6ssDg+nuglFTfUCnicjwNszINB/Fyev7OXcy5fgPQmiMp4a7no5gRXLopykRLe3tT1oamIGVmeFBP9z+fMLpwg4cyCZiqKyhPj4mNgoCo0WGelKJBLAgbC9u1X24mE190Ubl+fB3NGJTyi7/fLl5Dg4NJXFU13/TAQDEO+ANseiD5iat8m2VmfnpiZmZwVcD88dnUkVyKUkISEvjhUHJj7NCY1GYsCB0Ai8nLe3QJPNTr0SPORUezB2dDStUpRXVBBJIhHBckgl4F2ine3Nw1KTkpKHX71qnpia5T0UZNH9AoN3dNJjExIKCouLXSmnIiOpFMLt8bG5l6MjqpnhwdRUYbuAyRXwqrh8bz9O3c79db2kqADMUNblmHhfl2jC+CswjkZBqRLh5uLzQMitaarj8fyZ3n67tLNmHFIjI8NLKicnx66CjUM1qhpJAmGKMMF2dwubHoj4XDCm/Tx+2HUcXr4cn/4SdP4UGMtXj7tGhPtm+Fjz66rPt7Y1C4Lq+VyGxjm7o1N8rTS9cnJ8sjKNzU7PzY0XiBpuZoit7sifPVML3dAwQ70MDi8rmO4dtPNzgTWwDMyIqWaZTCRT9/fPz883NwoyljbX1jc3l9WiZnuYT31miB+4L9nRaRWJhE9iGnNk7+ZX3i+sbG6sb/6siU0Qa4tLK0qpu86ePTq6+oGf7y+Fi5f02bN3Ms7Nt281P6+JDSAtLy9vgND8sbn593cDLeJ9h/d/stj/Uz6ZNf3q/rfr4Nc3Nv/xrfUVsIMuLCyAjXRxeW1xeX1zfWPz5/X1ftktEweXfTusz09a3qnlyvnlf6SzvqxBFsG+rvlcWlpfX9vYWF9Rv33df9PEDArdYZ03hD1pfTKwsLa+tgYckMPSwvLKyuLyMmjy98tLytoMHy+YLgymo6Pz9Y73Lbqm0o3WFrV6BbTw5vr6zxsravXb98pnkkePHnVKOh+FHAwQ3/3wwUoplzYoFF2KDxLp5++1Aqqk6tdv3/arW2MyMg7BTM5LNKdxSU+PVDHwTikWK9+/Vy+urLxb2O1+rMX9zgddEF9//TF9sVzZ3y97/ORJ/8C8ev7Dh/4vvae1kIi7xArw5YWlpeXfcW8slyvm3y/M/3/9f8Fu8d+4sBhVaUEYPAAAAABJRU5ErkJggg==',
    'clover|ruby_swirl': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX////05+rv79Pj48/g4M3e3c7g4MLc28H//0Tc3LPd2sLY2Lnyztra0L3V1rnU1LjU1a/Vz7fT1bTT07PS0rTS0rLS0rHR0bHR0a/SzbPM1a7Lz6rKzqnNzLbMzKnMzKi3zJLNyq/LyqfKyqPJyKTIyaO3yZDNxrDKxqPHx6THx6DGxqLGx5/Gxp/GxZ/Gxp7GxZ7FxqTFxZ7FxZ2wxobmv8zZvrvWucXVuLLPwbXMwafOuKXFw6fFxJ3Fw5zGvqrFvpfHuafFt5TBwbPBwazAwK3Dw5/BwZ7BwZbAvrTAv6HAvZHBuKfAuJC9vqi9vpy8u6C9u429uo29uY28uYy8uYu7uYy9t6u8uJC8uIu7t4q5uqC5uZ64uJ62tqa3tpy5uou5t4y2tpS4toqvvYm0tZaTvV/hsL/Tr7vQsbPPq7DMrKvMqLfLp7XHsK7FrKrHs5jGrpLGqaXGqIvGp4a+srG9r7K6squ8ra2+sZK5spa+rZC+qqy5q6m8pq29qZ67p4TGobC7oau5oqq5oaq5oKm4oam3nqjFmq/EmqrDmqnDmam+mqjDmKnBk6jFo4m8oZHDmpe6moq/oX69nHy6mXO8lpq5l3a5lnK9kKK5kIG0tJmzs5mzsJ+xsZOyrZqqqqqzppyysYqvroqvrYasrIuwqYyrqoqsqXCzoZ6znaKvoY2vnYizmaWzlqKvlputmIOyk6CwkZ6vkp6wj56vjpuxjnymrYempoulo4WhoJadnpehn4OenY6cnI+fnIGhlYaijYCampKamX2NoWxtnzyXlIWUk3uZjoCPj3V0jk3IhZy7iKC6iZ26iJ26h6G5h5y5iJe5hZu0iISriJaygZGwiWqviWKwhmykh5Kbh4+mgZGcgomihGaWgYuTg3SJh2x/f31ThCOheoSUenuQeX2TdIGSb3+Qb3eKcXeIbXeJbHiJa3eHanOLaHqHaHWUZmmGZXKEZHF6ZWyGYG+DYW+DYG6DX22BYG2OWW0rGx7/AEB/AAAAAAEAAAAAAAB1fHGyAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADS5JREFUeNrdmWtQU2cax1eCMIWC20RMHMa4CTBoJIKgIgViChGDlHCXcomhoGlag00gWJXlfjdAXUAJBuNwCWmqXJKSCkKwitwcQGyzKkICI+WOpbAL8q37HOyX2gDa7pfd/wzkMnN+/J/L+77POfzll/+O/vI/ynHNPvPf4LgedI7l/GnOgUOuzgc/T0/4kxznA58ePLj9TG1y8p/iODvHHtx+0DlNBaCzf5zD4bjyDjkDTFWbmRN79g9ynDmHeKdjOcBxVtSmZ+as5WgDDtdVwP9slcLhKr/JyshM//vbc7jcQ4L401yEweGe5ikaG+uysrnZb8vhHooHCpfD4XK5n7m6HkqTp1RkZ3Lf1s9nfITC5TjHxp7m8yi2u72crI6KWaFJb8n5leLMPcOj2lvb2ZN2EnFu5eJT/uK3jAuMcFwO7yVaWmLxRDwWi8GgCQx/ljjCzZ/2FhwXYOx1ssfttCSS8DsxGIzFNtxuGo3GiKDRbLcceTOOkYmhqZMd2Y7sQMTjcdtwRBweb012JNMQeXseodE25pgYGBkYGKKw7mSQo7UlCYfBWRId7eytrPGe4Ifm7e3t6fkGflDGRibGhlspZBKJTHagWG/FoM138al2OD8p68EtW5onoo05WFNbc5ShEY5CptMdyGQi2oJHJQiKecZoP4n0+YP7tzxpEf6MDTnGxhg3BoHoExwWEhboaEPlv08tFlA9eIaGRluORdx//vyBmBHBYm3AEZjid5nuYvmH+9DpPhQHJ7pAUFxaQrWzwpgbGxmaEvw6nt9nSsQst/U5/HgPAZ8iqGJ40en0gMDAwJjbRZdFvjYOlhgc1nwLDo3GPbjl4s8Unyp3W5uDQnlQPYpLBDfbxf7hYeFhIcHHA2T31DVIvi23YrZZYC0tCJIHJ/2OMMqlXpK1OIYG5kQ76uXS1q6uVuZHIcGIAmPu3mu57Uey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',
    'clover|caramel_swirl': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////8jq6eHh3uL7+qH//wDr4rHh37Ph263i1a3l0qHkz57mzpvizJzhy5vkx5XgyprgyJjfyZnfyJjex5bV2b7P0LPUzK2ly4fYx6Hcx5bNyMG1x6fcxJTbw5PYxJrbw5LPxLnUxJq4xKjWwZvYwZHZwJDbwI3Zv43ZvozWv43EwMfLwLHMwJnDv5jBwLzBv56rwInVvI/XvYzWvIzXvYvWvYvWvIvWu4vVu4vWvIrWu4nUvInVu4rXuo7UuonSuY3UuYbVtIrTtYLKvJ/Mt5rOupDNuYnQt4bOtobJspTMsoTOsXzNsHzKsHu+usC/urXBvZbAupu+trPAsai+s5vBvJTBuY7Cto3Csom/s43CsIW6ub66t7u5tru4tLq6uKS4tKe3tY21tLe0s6q0sa6ws6SZtlzOrobNrnzMrnvMrnrLrnrKr3rLrXrLrnjKrXnJrnnbqIHOp4LMp4jMonXKq3jJp33JonvImXjCrozCroXBrYTCqofFrXvEqXrDo3/FnnzEmnjElXXDkHG9rqO1raaxrbSxram1qaKwqbSwp6K7ro+7q468q4C9p363poa4ooGyoZC4onq7o3W5oXi3onO3m4q4nHmzm3G7lXe0lHi1kHevrLCuq7Kuq66tqrOvqLOvp7Gtp7Ouq62qqqqrqKytp52pq2mqpKyooK+loqikoKiso5mkoKOroYSnnKOklKKpm3iplm6pkWqioKWhnqOgnKSfnKGfn4ugnJSgnHmfmnqgmK6hlqqhlaiglKihlKSflnycmqKZmZmalJ+cmn6bl3ablH2VmImWkpmVkJh0oEF8kmnDi268iGm7h2mzi3Ssgni2h2m1gWSii3uajHaei2eghnGfgWqRjpOQipKOioqPhYeWgmCIhomEgJGEgYaCfoR/f39/fwBWhyewfF+xeFejeGCSeWOEe3x/eoF8eX97d397dn57dX55dHx3c3qVcFx4cXx1cHlzbHdyanaOYltxaXZwaHVoZW02NT3qAFUAAIAAAAAAAAAsgPxkAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADXFJREFUeNrdmX8022m+x+eOc4iQbBp2XVxpZi6hgnaE2jJpaqKp9aOqJJIJ7biZ1s8qG5NKk2qngqHIHBGkqjnI8bNkpyJ+lqpir7hNtEWJkeGcKpv6/WN0/+l9vp3dP7YN2p395973Ob7EOc/L+/N5nufzfL6Pj17/a/TR/1FOgPTMv4Lzx0/wZ/C/mmNkfxz/SWZ21K/k2NoetLW3D284x/pVHDw+ysXexZbV11DOOvvPc/AHA1L9bPGAUyetjmL9kxx8iF9qQBgej7fFtzSUS6t3crQHJ+p4RmpYCETBRyqVMqmsnPXhnJCo49xvwwEFH4KPDE9tam1tuC0NkX0oJxKiREYCJ5GR4SBH2Y3U/BxZ5If6CU+FKFEAcyb8CvsLP/tjPo7+fAY15wM51wAlEoopLIDsg3P28cZiLSh8Pp/O+8C48FFRIS5+7g52WJQdFmOBRiIRn9LoTD6DQqd9AMfa5bjHER8fS6wdloDBIpFIFNrSnRZKi6DTaK7WtPfjwGAmcF9Pb28PDxzGzgJlgbPEYHBePt40Gi009NChULf34MCMYcbGMBM0ycPLy4uIsyPYINF2OOJhbxwO4xYaSqMdgvQefoxNYTBTGOAQCF5ePiQnkBizo2mxhy1PiJjDta40t0On3d6Dg4K7WpnAYDYkLzKZ6HUYZ4Zix9pxBammiD8UiJ4PD9e6hdLp9D05cDjSPeJTh+DE5MTkeKJTLPtorCDDnx0Lg8Gs6Zf/5/nzYX7ElzzeHhwuHHMUfpRH5wSR/cm+PsRAboZALfD3xCEQIFozzInnz2MYBXweZXdOGjc2I+0LrpB2gkz2D46Lj0+R31Rr2M5EkGu0GWIfAmEzXOtHZ4D1SNmZY2zM9mULHgluKvh0TnJycmJiUpDovx+UOh3w8rBBItEolB0KUzD82WehEXzxsYKdOCbGcKwnWa1pHh+/yziZ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',
    'clover|matcha': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////+Dt+8nZ98Xe68Db48jU4rXT37XS3rXQ3bHQ27T//4///wDO36jN26zN2qbM2KvJ2KjH1qXF1p/F1KHE06LE0qTD0qHD0qDC0p/C0aDC0Z+/0aLEza/AzKPBz5/B0Z3B0J7B0J3A0J3Bz57Az52/z5y+zZ3Gz5q/z5u+zpq9zZm7zpa8zJe6y5W6ypW4y5W5ypS4yZO3yo60yoa9xaO5xZy2yJC2xZW1x5C1xZO0yI20xouzxo2zxoyzx4mzxYuyxI+yxYuxxYuyxIuyxYqxxIqwxIqxw4qxxImww4mwxIiww4ixxIC8wK66waa5wKO2wZy1v5y4wJC0wZS0v5mzwJawwYyvwoW1vp2zvpmzvpizvZmyvpiyvpeyvZexvZexvZOxvJawu5Swu5Gztpezs4Wr15CuwYetwYKswIOrv4OtvomqvoKpvoCpvnquupCsu4qpu4Gnu3+nvHymu32munynu3ituZCtuJCruIyrt4ypt4qrto2ptouptYuotYqot4inuH6otYiotImntIimtIakvX6lunylunqkuXykuXqjuXqku3mkuXmkuXKkt4mjtn+ktIOkt3ujuHmktnmjuHWhunait3eht2uhtnSgtmaftHCWynmWuWoX/xeGw1ens4mms4ims4alsoaksoOisIOhr4GqqqqirIqhrYGerH+cp4KZooSfsHqdrXucq3qaq3iaqnmZqXeZpnucsHOarXKZqXSbsWajrVWVrGOTqlyVrVSSqVGWpnWUpmeWoX+WnoKVnYGSo22ToHWPp1eMpFaOpkqPoGyOoF6Jo0yIoEWGnkeCoEhqp0eWnICTm32Sm3yQm3iRmX6PmHeLlXSRmmmJmmSHmF6Jk3CHkWqCmkaDlF6Bmj2EkGmBkGaDjmd8lz14lDl5kUFomUxtkDOBjGV/jGN+i2N9i2B9imJ8imB8iV97iVx6iF56h152iFBoii93hFx1g1l1g1NzglZzgk9ugkd/f3Vqf0hqe0FASS0BAAAAAAEAAAAAAACViBYhAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADdZJREFUeNrdmWlQE1i2x3ssDGaqjBBkaSjFwAsM0IkSWkIMIKZJ2kAcCEWGJTYZiR8ia5BF9kU6TCQtFppuE7ApjAFK2QIJmiEQdgiCCkgGAh3WYRGUsAxajy++m56eL0wE7Z4v804VVIqq+8s595x77v9cPnv/n7HP/ks5t+jH/xOc0j/8/vix38wxunDB+A8x1OO/kQOFnDh64ZYvk+r+mzhQiItb/JdQx8pUqvvpX8+BmcWXXoAdMnasZNMjjwf8Sg7U7MvSeBQMCoWa5KfR6JGBAb+K43ShT+5mCoNBYSbWnG8jaHS6+6dzTJwvtCrOwqEwuI2pxVlhwf37qXSGRfincqwvtCjI5tZwUxtLa09h6ZfueTF5zAiLT/XHrbSFbGFtZ2qCQHqWttxyOfUVGR8jyg++/Ikc+VkLCxtTqIml85VrFCyORHR1dQ4WFYjZ+Z8YF8TeydLS2QeDQtuiMGgk0sbKyj0yNftBejA74hM4J05gCQQKyQWDwniddLWxtkLYu5yh0+jM1PAIdwvGx3GgMGN4qA+B4EPEoNFO9k4YZ7QrlkAiRETQabTAwCBqxP4cmBHUyMgY4uAHOAQSFuXlYuOAwhC8iFjsSWoQjUEPABb4Ef5ATKAw2CF7io+3NwBR8NY2Fhahims+LjGS/L/Xn6aFBYZRP4JjB/eAGx+COlEI0dEkgg8Gbl96C906IIRZJVTWb/z9WR2Vlsq+vC8HdsTOg+mISebxeXwuCXdNfuHWQF+8UAg9BLW4lDW+sTEvZmbl5+/DaTXzPGtC4aQK4qKiYkNJpNjWvoHBgXgcxtrcBHoI7h6zsdGfU8HJD96b09Jyq08e3yq5GBIbFZXM5XL5sn6t9gccGWWDRFqYI62sHJ41BKZliAoeBH+YA4GUXhEODAz0asRsAZ9fxOPxk5Sd3W14TwLBxdbGHmGHQqCKn/0lJIwp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',
    'clover|mint': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////9T44e3k4ua95/PS1d641eXJz9W1z+Ovzd3MyMvJxMrFwMSxyt22xdu5wMepxtuixNqjwdeewNehv9WfvtSevtSiv8vAur+9uL28usC5ub+7tbu3tLq2tLe1s7asu8ist8Wjucius7uks8KevdOevNKdvNKdvNCdu9Gcu9GcutCbu9GautCbuc+Yuc+Yts6btcaascOordeorbyprbeyrLSnq7SyrLOvqLOsqLObr8abr8GdrryXr8Ggq72eqLyYqb2xr7GvrK+xqbGuqq+tqq+kqbGtqq2qqqqsqKyqqlWrpa6una2no6qnmqqloailmKmioaein6WinqOimaiilqmik6WZpLWbo6yfnqeXoKyenKafm6GamZuglaeflKialp6dkqaYkZ6Yj5yTvq2Uts+UtsyRtr+TtcyStMuTs8iMxlka++qNtceFuHKPscmNsciMssiMsMeLsMiOsMaJsaCOrseLr8aLr8WLrsaKr8aKrsWKrcWIrcaOrsSIrcSRrcGLrZ6SqryQqLyPqbyLqsCGqsKOpb2Lpr2IpL6PpraRo7WKpLeIo7eIpaaKorSDqsKDqcKBp8B+pL56pb97o796osB9o7t6o7p6orx6orp5orx/o7d7pLd3p4GPn7mKnr6HoLeGoLWDn7uDn7KCnbl6ob95ob16obp7n7h3oL11nbuKmbaBmbt7mbl7mq+Ck7N7kbd6krl3mLZxmLF0kbV2jbZxi7SRm6eDmKiNk5yAlKSUkpaLkpyAkZ6SjpaOjo6Pi5GGi5p+j516mKx3mKx4lKlykaRyjad7kJ56jpx0jJ1wlHtjkzKThZaLho+IhIqEgYaAgLKBfIN/f3+Ae4B4haFxh6h1gZl6eoZrhq5og65ngK1ofadhfatshZZkh5xpfpZmfo9cfG9+eIB8d397dn56dn17dX55dXx5cnx3cnptdYlgeJtjc5JadZ5Wcpl2b3p0bXhzbHdyandxaXZbbY1yZ3ZhZnhaW3sfHSOQAGAAAP8AAAAAAAAcT4vrAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADZFJREFUeNrdmXtU0um6x/caR2MU8pLsifJCiNqgJnpSMxVveVkuQ022g8NmFHPiiK4lihYllA6aU4p5K8tu4wAl5QWHEnRrqCOiYgYeV+lR8rbQTNO00s78M+elmfljt1FrZv9zzvcHawFr/T7r+zzv877v8/74yy//Hv3l/yjHJ9zq38E5YQq1gv5pjqGPj7GpVxDiT3KMt5ma/gd2Pz7I9k9xTIytkViksS0ZgKz/OAe6K6AGbWJsbEPGh0RY2fxBjsmuPTUB1lBjE2NoLD44JMLW5g9xdvtIauygJkBQBCE2NDg02PbjOVBrtLhh/07A2AVF7P/uKwIBHx6CCP1YDsJHR0FAoQgEwi6wBuVJIpLCQnd+rB+7mh/3IxC7oVArq/01NWxU6klWViGv1D/sIzkN+xHAjDF0l11++Wka43ROSopLHo8nKCj9yLiMrax3I1HZqcdS9mJpVAzG3h7uhsvn8gpwBbiP4KCQ7szs06ddU7A0BjXF3t7e0dE1FeeO4+T74twscR/GgcEg5mVZOTnMkzQq1cXRmeZKpdKZLCYOh/N1R6N93T+AA/sU9qkRBLI3l8FkMll0LMPV3hlLy2Hm0GhUNx93nC8ayPcD/EDMYMCPQy6DAUisXLq9I9yS3ljOdD0r5w5+i/X1Rfu6obfmOJu7WUAgMOdcZnk5i8mkWTryz2PF0vNmlucE8sHBh9/6uHMKOFtyzMzsUzlOKZXVQnCxMioaTpyXSAr5NTDIZxac7x4ODg7+wCkqKdmCIzY/RrM48UNBXUVZeUUhi1UhlkjHpYUMOtzCDAaxwBYAQyUCXkne5pwG8XlJA1sswrErCssrL1VXC9sk45rKDBbINcbC0hn+170Pv8XmF5XyeLiNOUYQfiFfOibpm+QV1Amv1QLMRcVP3c2ZIN+uDvaYL/a6Ohy78PD4Nz4cnvyMYCMOxMgihVE4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',
    'clover|lemon': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////8nz88fs6dLl5MTh4sLh4bTg3sPd3MzY18PV0s3//43//wDf36rb3KnZ2anW1qfY2KLW1qLV1aTV1aLU1KHU06PU1KDT06DV0aDU05zO1J3S0aHN0JrQz53PzpvPzo/BzpbOzaTOzZWjzXTNzK/NzJbNy5PNy4m/y5PLyL3KyZPLyZHKyI/LyI7LyIbJx5XJx47Jx4zAyJXIxM7JxcLGwcfCwL/CvsLHxabDw5/CwajBv6XGxpbIxY/Fw5PCwpvCwZnBwJXJxozIxozIxYvHxYvGxIrFw4nEwonDwIjEwYDCvoHFwXXGwVvBvYDCu4HBu22+vbu9ur++vpy+up++vpK9vI69uo67u6q7u5S6uo20u5W/vH++vH+/u36/u32+u32+un6+u3y9uny9uXu+unK7vHu7uXqkwGuIwVC8uMW6uLq5tr23sry4trO1tLS0srS7tp+3tqO6tpa2tpK4s6O0s6a1s5iyrrexrrKwra+vrK6uq66wrauxrpyzqL2vqLWuprevqa+upqu4uI24t4y4t4a2toa2tIi0s4aysoa8uHa6tXC1s3e7tWK8tVG5sVKxr4OvroCyr3SwrnGvq36vqnK1rl22r022rkKwqlevp0uwp0Ctqq2qqqqrqK2tpbGsqpypp56oo6unoaukoailoaGnnq2kmK2rrH6qqH2npoanpnqqqWCppGespEStpTakoHymoGGsoz2nnjqin6ShnqOgnaOfnpien4ifn4CdnYWhm6WilqudmqKamZqcm4mbl5qgpm2gn3aenGZ9qEySm22hl1ShlzKbmFeDl1mhla6hlaiglKehlaOikqObkqaXkZuYlI2XlHGXkJOYlWOXkViYkDiRkJOOjY+PipKRkWuOjXCPjE2LiI2LiV6HhXJgjTGPgXOFgX+CfoaCfn1/f41/f39/eoKAei59eYB8d398doJ7dn58d29yd215c3x5cX13cXp1b3p0bXhyandybHJzaXdwaHVpZm9CPUi/AP8AAFAAAAAAAABpx0gDAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADWtJREFUeNrdmWlUmmcWxzPJlElyThSjRIaTkRys0IlLhENN0GjQUsUFjVFJhTFxwbrHJW4xEqsGEY1g1KDiUkWrxqBiQtxwqYiO6WicUkxwGXGc4ZxxiT3WpWO/dB7ofGmKmrT9MvN3ATnn/Z3/vc997nvfx0Pf/zo69D/KodTG/hocbxQ+7vwv5hyneOJRKbdifyEHf9zBguKd3JiR+Is4eHy8pbcN/tYQAN34+Rz8+cve5Pfx+IShRmZdbMLP5ODPf+B9OR6Pt8PbdTVmMusSE34WJ9ajkhcQYwcodnHdXbWZzMzEt+fExLpVViTF4N+/4HchJsC3eWDgMybTL/NtOX5uxYASd+GCX0xckq83LrEhPSuL6fe2fgJ495NiYmIv2MXFJRV5Uwj2TqT33Dl5AVlvyeElx8T42eHf94v3oOAwtjicOdrMkcPOp+a9ZVz4uNgrFgQnNNL8FBJtDocbGxuh/GkszlVHKvEtOCgLItYJh0OYI9HWaLSJsTHMFGFLJBJdaERneyjxzTgQCMSAbIPFYYEdJNwUjkaYm2OwJKyzMyA5ONjbOx/MgRyGHD4MgcBdsUAkDNLazASORDtZ4zAYpL090RlwgN7AD8QQ2IGccsVaWwOQq5WxCdTwHI9ijaDyWWOtBOJFh4uEN+CYGthCITo/Hh4kLBZtaMqjmFd2+kKMqIWlS2NjrfZEGpV6IOfECVNHmpm5TwgjhBFEsqTwzlEEAk9fX4CGutD+srQ0xnGh5eUdwCk2OPOe4Tk2NdKL7O5F/oDkVSmoEdd4WqKNoQYQiCGSurT0Z3pBXp7j/pziYoqAR6nkE908ye4+QUHBjEdVks4wSxLSBA43hMJPnoSDDNHoefkcx705EIi3p29NjaBKyaFGMhhhISEMn0dfPX5gZYPFImEmpjBTJAxZOJZPJbpw+JcK9uJAfmuItvSUiEeVysf0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',
    'clover|salted': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////6rm5Ojb2dzY09nS0tPPzdHMyc3JycvLxszJxsrIxcrGw8nGwsfDwcjDvcbDv8LAvse+u8e+vr6+usC8usPAt8C9ub68ub68uL68uL28tb67uMG7uL27t727t7y7tr26t766tr26try6trq6tby5tsG5trq4tLy3tre2tbe1tLa3s721s7a3srq2sbmzscO1srWzsbO/rMC1sLi1rri0rrezrrazrLayr7qxr7KxrrGyrLWyq7WxqrSxqLSwrrKwra+wrLCwq7SwqrSwqbWwqbSwqbOwp7OvrbevrK+vrK6vqbSvqrGvqLSvqLOvqLKvp7KtrcWurLStqbaura6uq66tq66tqq6uq62uqq2tqq2tqqysqq2sqaytqLaup7OuqLKup7Ktp7Ktp7CuprOtprGtpLGqqsmqqbmqqqqqtnKXu3miqq950m+At0uqp7mrp62qp6uppqqop7yYp56qpa6opaqnpKunpKipoq+mo6ikoq+koaajo6OkoaWhoryOonuqoK+qn62mn7KloKijn6yjoKWin6Sin6Oonq2nnKujnqakm6mhn6uhn6OhnqOgnqOhnaOhnqKgnaKhm6Sfnq2fnKGfm6KenJ+cnK2Im4KWmL6WmLiVl7efl7CjkrCZlrCQkbClmKujl6qil6milqqilaqhlamclaqUkKuimKeilqiilaehlaihlaeglaeclqahlKiglKegk6efk6ebkqeemaGcmZ6el6Gblp+ZmZmal5+ZlZyjkaOdk6GZk52bj6KYk5uYkpuXkZuVlJmVkZmTk5KWj5qTj5aQkJuRkJGPjpCIkIVnlDmfiqWTjJiRi5mOjY+PiJONjJKNh5KKiqGLipCLioyLiI2Kg4+Dhr2FiKyChaOHho+CgZGFgoaDf4R/f39XhiiEfYmBfYJ/e4Z+e4CAeIN9eIB8d396eIZ6doB6d3x6dX53dYN5dXt4cnx1cX52cXl0bHlya3Zwa3d1aXlwaHVpZnBeWmUYGR/lAOUAAP8AAAAAAABI4IcPAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADalJREFUeNrd2W1QmteeAPA78YXrO7XcIrbBKDG+o3IRja+JMdhS9FGayzXl1liMgnecGNGCxDDi2wXRtGyC0WSL0WjQqiVGpCiJE4yioI5jMCbi1IjbWF+SuGHVGfdT9uDsfthcosnt/bL7n9Hx+fD85n/O+Z/znHP83et/Tvzu/6jzwZd+/wzH2R7uB//Njp2DqyMs+LjXb3Rgdq4O9vZHuNG43+Q4wbxh9jBYeD83Bhf4jztwN3d31987wUL6OdTMw4H/oOPygbO7uw/c0RHmIuSSqJlvy2gfx9udGfYJwsXRwQnuJRRnkKik8Pd3kIc+YFKCES5OcCTc84g7TyLmUqlI6vs6SIvieRjuivby+sTd3Tmyjl1XREW8bz5/CAOKF8rVBYMKpriH+cSl58SVSISJRe/pUI54enq4OrogsJ+dIhPO5qYSInxTJJJG7nfv2S6Yly8S4U+ODI3wDSWEYjAoD0R4JkfQWJpYQn0Px+eTWAhi0LGEUEI8PgKF8kAf8j9BJVFZHGoGDpHxbo6TE8yNTYYgMhSJD/U95Evwx+NjIXo69fTpz0kh4YmJ7+A42TjY2MJg6FzgQPRYLBGL8sFG0tOhyEh8dGLK6dOBgSEBuHfIB+bi6OQMQ+WSk5IgKJ0RexDtiQwuPgP5szV1U2MRpGPhx3Dv4ByCR8JhMMdDjCyRiA6lR3qiKWHeTGaYC4LTP/jLVEF53OccTtG+DtwVlVLkH9XWq+hVyLLi8yhhYUzmqfNhDjBHBKv63375ZaqeVSqu2cdhuh4JRh4VlCovVVTUXsjKETGZfCn/VHqcJ5hlMDihaOqX8rprYuE+/UxhHmVSwpjqvzBEFRVtt2Qy5T2+VFqVlo5FYTAIhC8S6TdVHsEpk1xuSHm7Y29PySnmf8+8brrMUfb1KXrl8nbNhPZ6/EmIjPVGYby8sQcjrk1989fkTMnw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',
    'clover|rainbow_swirl': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////8/o//bl69zb39H6+pPh3br//1X//wDd2bfk16fb2LPk0bPez6zdzqvcz6zczKnTz7fZzarczKjay6jbyqfayqfayafXyqjazaPZyabZzYjdxq3Yx6TXxqPWxaLWxKHVwajXxZzWwZzbxnfXv2fTxafUw5/SwZ7SwJ/SwJzRvpvRvZvSvpDKxa3Lw5rOv57Ev5/QvpvFvpHQvZvQvZrPvZrQvZjEvZTSvKvQvJnPu5jXuMPSssHWuKDOuZjMvJnMupfIupvCu53Gt5rEsqHHtpTPuIfRuGbKt5HItY3MsZDIsYfBu4TBunzBt4PFsYzDsY7CsIbTq7jMqbvcq4nNqoPJrJrJq4XLpK7Mo4vMoXzJmnrHlnbEr47Er4rErorDrorEronCrnzDqpbDrIjCq4HDoofElXO709a/v6G+vaS+vJu/u5+8u6G+upC+uJy+tZm5tqC6to6/t3m9sp++spS+sZO+sZK+r5C7rZS8ro+7q42+sIS9rYO9qom/sG+9rG+9q2iqzeWnxbWkvc2svYustbCltbe1t6Wstn+nsrajrqypq6qqr6ayrpinrI6orGCUxn6Xs8aWr7+MsMaDwlkA//+HsMuGsZaLrsSCrMaQrL+Oq5y8p5e4poe5oaq3o5KzpIilo5G4pYO3oYK4pGmzooOson+2nYWsnYO3mJCulpO8mnmsm3a3lXafnIqcnImemIeimXailHKhknCMpbiHpbqBp8B/o7iJobaBn7R7pL57orx2pcR3o796obt7n7d0nr6SoKOXmpOWnXWamYCVlo6YlHl+mqx5mK14lal9k6J6mXlrmzrFjXG+imu8iWu7iGqzjHW3hGidjn2YjXmXjYKfjmyig2yZhWuUiniJioaRgmiAf356j551iZhvjqFvhpZrgZJmhI1UhFuvfGCzeFilfGKUel53fHpkfI1ifI1gfY9ge4xfeYteeIlbd4mndVhxdXdadYZXc4VVcoSAb2dVcYNRbn95Y3AnKEi/AA4AAOEAAAAAAACxsR6uAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADNRJREFUeNrdmXtQk3e6x7fVyQyGS2wD1rhABtTExLKABjQBJZSlxBww0JSCAQJhA1kxJak0kiaWmxQFjizLZRh0Nk6ExpOVcBVpEIXFRrkM12yAsJRLdigZQCMDHPqX53mj54/DBtC2/+z5khkuM+/n/T6X3+/3vC+/efnr6Df/phzmLfavwfn0ZCA78BdzAk6dCgj4/baO3oQTEPAJkGJv3br1izgBAbEnT50MiL0LIPbP5wR+8tk5COs1h/0zOQGfnDr3WWwgcAIRzpaOduCwT8Wfs1ICAtl3raDYt+ewY0/FxcWyEUYgO/bcXSuIfettOWwrhR0YyGYD5dyp2L/+4S8/I67YcwjFiok9F808ecSP5hkq++r3f3lLTqqVEhDAjv2M6X/E198fT8B5y6SykMy3jCuAzf7k5MnjR9zcsW4E930uGIyjt0h8SSYODvnoLTgnT546ftzf3xXvRiDj8RgMBuuC8xYKhSKxUOjjJXwzjp0dyoHuS6EcpxDw7jgsjoDD44kUqr/wApDS0j4XvgEHvctuFwqF+oAGHAqV6EZ2xbi4Efx8qQQi/rwQSGlpaV5pb+AHhbZDo+2AQyYD6DQJEuNwlMP0dQ1VXhoo9EI459+A42zvvRdlBxwKg0Gl+BIcnKOZbnGDMWjHULlyYGCg0EcoFot35Njbv+8tOuzN4vG4PBaVxIymMQUCZkyMnZ3deyEh3wNIJpJkSnfgxNl7HkVTpWL+GQaDQadSGfHxg8ODTF8CxgkNuXc/MTDwvUQuzQzansPhMAUcZrxCFAwYFoivrh/RJxKprhhnZycnZ0dHHGRILJHKZEFbc1CoaEbM4NBgfbNMzOdBYNwklvpJUx2JRKG4YoHk7IZ1lw98841QJKsJkm/FQaGc8CTmyEizwaCWRAIFxOJPjD2+HUr2dMG6umCIFLxK/n3ln9OEIolcYZvjhLJz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',
    'flower|vanilla': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////+PU/9T09tzt7M/k5dDi4c7g38vd3Mrk7cDe38Hd3MPa28D5/5j//wDa3rPa2b/a2bbY17nX17jU17XU1bXR1rPW1LnT07TT07LW0LfS0rbS0rLS0rHS0bLR0rbR0bHR0bDQ0LHNzbzPzbHR0q3Q0K3Pz63PzqzNzarLzKvMz6HMzKjLzJrMy6jKyqLHyp/WxLPYwLbNxanJyKbJyJ/IyKXIxqPHx63Hx5/HyJ3Hx57Hx53Hxp7Hw53GxqLGyJ3Gxp3GxpvGxZ3GxJzGwpzFxqXFx5zFxZzFx5vFxZvExK7Fw5zEw5rCw7TCw63BwbfBwbPBwa3AwazCxZzDw6PBw5TCwaPCwZXAwLPAwKzAwKvBv6vAwKrBwJzBv5TAv5O+w62/v7S/v6q/v6i/wZe+wIq5wJHRu6vCvKXAvZG/vIu+vqq+vaG+vI29vai9u5S9u4y9uYu8vKS8u5G8u4u8uYu8uIu8uYq6u6O6uqO6up+5uaG4uJ26upK4uJe7uoi7uIrbranNrKTPnqPMmaLNnI7Fs6HCtJPHrZrEppfDnpW6tqG3t527to28t4m8tIi5toe7sZW6qJO8npC6mY22tqi1t522tpu1tZu1tpq1tZmytZm0tJq0tJiztJiysp+zspizspevrZmqqqqqq5m2tpG2toKyto+yspS0sYmwsJGxr4mtr4yurI2srIyrq42rq4etq3Cup4ypqYyoqImnp4uto4ylpIehopKjo4ijon2enpCfnoKpmoeenI+dnJCdnYScnI2cnISbm4qamomZmY2YmH6ZmWjLk6DGkofHjprHjHu5lYy4kJHAiJK5iXSdlYKVlXyUlH+Uk3Wij4mfiYmTkXmRkXaRkHaQj3OOjnSOjW+Mi3OMjG+Mi22Li22Lim6KiWuJiGqIh2vWg2PBg5PAhJK+go+ugoCeg4ONhG2GhWaFg2OEgmOAf3mEgmGDgWCCgFXHeW61d4O0dIKmd3qMeW/JaVLBUTuRW1d2Lxj/AIAAAAEAAAAAAAC9/sqyAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADcJJREFUeNrdmX0023n2x2dOkY44x0OF2A0jaMk0R1SrE9V0RDw1pB52GJUhdqOtVZKGI/GUmkySVeqxYhuydOnRTpp6+G5VaULVQ41RdD22GJYgdHD4rabymz+6n3T2n7VBO7P/7L7PcTjOyevcez/33s+9n3zw5j+jD/5LOa5U+/8ExxVu5GD/izl6rq6G8JAg+1/IgelZwl1dj6QF4H8Rx/AjBxNXExhemh6Ad/j5HEMz169d9xvCHKRp1Fj74J/J0VLiHI1gcJiROD2UmnAm+GdxbFyF/CPmcPh+uAmqTBwVSg3Fvz/HHFAERwHFBGlmcSROfKMsnUr/ddT7chCuAsFRC2szE6Q16giIET4rOiuZ+vH72nPkay3FysQIZXOUD2Lk4k92i64SByW/J0dwxMICabLfCOF4KvvUsdNkorPzobAqSXWi5D39+sgGjUA4euAwWDQGh7G1RSIR+IS0/MqMoMSo9+CgrXBEIoXs6IxxdsdirZBIlLXjcWoolZkeGoW3pL8bBw6HmUYQiUQCEYfFoK3Rzo5YLI5IJkZFUUNDQ0JCg6L25sD3wfbpwQxsKQQA8sc5uTtaoZ1wp0974XCfBAT9JooaDBTyDvYYmMCAPSgKwcODSCRRcEiUhXmcINvDMbr+xkLOmcizIWcD3oFjY4q3NIDB0RQijeZF9MOZo/hxDsJevhEiUVa3tbCQ89vQ9OTkPTmmpkjfZAdnBpvH5rFILtn8OH5vr08OHwaDW8ZKt7a2FqqYmeXle3CEJkeOmh8tyyiOj4iIjyD504TCvsG+7NM4K3MjGMzs2FMAKr0uEYftzhEI+EJ+nLCOHk2LoDFYLBav5qpq8YonyQmJtj2AQCPMHRa2FhK4FZVVvjtzDPT5Pjl9g70DPZWJxTxeKpvNu3iv/ZHI5QSR4ISyskbZOtngL/xlK/e3zGroC+lOHJieGfZ0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',
    'flower|ruby': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX////U///v3+XuytnhyNHov87bv8rNxMvYvcjWu8bZuMbUuMTascLTtMHRsb7Ur77UsazLtb/LsLvMrbu9sLW9rrO3r7LlqbPRqrnOqrnNq7rNqrnNqLfMq7rMqbjMqLfMp7bMp7XMpbTLqLfLprXLpbTKqLfEqrXJpbXFprLAp6q7qa+7pa22p6+qqqqUqqrKorLIorHIobDPm6fInq3HobDHn6/Gnq7HnKzEoK/Fna3FnKzEm6rFmqrEmqrEmqnEmanDn67Dm6zDmqrCmqrDmarDmanCmanDmajDmKnDmKjCmKnCmKjDl6jCl6a+oq27oqu6oqu6oau5oqq5oau5oaq5oam5oKq/nqy/nKu6najAmKm7maW3oau2o6O4oKm3n6i3nae3m6a3mKS1m6a0maS0mKSzmaSlmp7HlKjDlabBlaa/laa/kqTRkZfGkZzBkqHBi5u9laa9kqW9j6O9j5+8jKK8i528ip+7ip3Sg5XGf4zBhZXDe4q8iJ28h5i8g5TtgGradl/Ne3bNcnbCen7CdX/AcXu4laO0laKzlKGylKG1kZ63jp25i6K5iqG4ipy6iJ66iJ25iJ66h5y5h5y5hpy4hpe3gpi2gY62doWwlKGxk6Cwkp+wkZ6vkZ6wkJ2vkJ2wj5ywjZutkZ2tj5usjZukkZmljZeaj5KtipiriZeth5WoiJaphpSrhZKohJOnhJKjiJKeiZCfhY+XiI6XhY2XhIusgpCmgpGjgY6agouXgoqVgoipf5OpfouleouYfoideIiae4KSeoOcc4KPeoJ/f3+Pdn+Uc32Nc32LdH2McHuOcm3LZnDUaELEaHTGYGrLXU7BXmrCWVu7bXy5anq1anara3WzY2+4WmPGU1i8U2G7UF6yUW2uUUiwR0yvQEr/AP//AADMAACdaX2ZZmaSbX2LbXmMaXaJbHiJa3eJaXaHanaHaHWHZnR/aHGXYmqFY3CEYW+DYW+DYG6DX22BYG2fV2KFV2ChQj5oMDEAAQEAAAEAAAAAAADfJFhTAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADeRJREFUeNrd2WtQ0uu6APC9yzwSgtuUfUgL2IapW9eMUt6wWCJrUbG9ZB4WmjV4zUlFS8lDKerJNineSpEQhUTSEq9Z5pURDRs0xsuwvQ7s7MNK09SVlyTOh85rZ+bMnBbqaq39Ze8HPvDpN8/7vs/7f5/3z+8+/WPid/+kzo2LDv8I59a/Qx0sf7NjkpT0b8grLta/0THbh7RIunE5xsX5Nzn7TV2P3TgGcaiNdXF2+PUOFHkjJwlqZuZUG0ONcLD+lc5+i6RbN1yhECgEJroUTI1wtv5Vjl3S2K1jllDgwA6LRbRg6jmnr3cs7ZKGb1+GQ6BwW5jVsfTq+/djz1EP0L7WsU0aHr1shYLDUYdRx9JzkoIKUrhR1ANfm88xDlAOo+GwI9jL7Fs37NxPB3qlSEShUV/p3E62skLBILCDjskZ8V5+/hQPD/swSVVNtOgrx2WKwR60wn7v6eaOcvPAYTAo24NOEbGVkrzQaNpXOGikF5mc4G/v4epBwLmjULZojD2RGkyNjA2hBf1strdxoFAzi0QSmUwie+JwWAzW0x6Hw5P9/3KORg0ORji7nKXv7kD3QvaamJkeSQAO2R/vSrBHYV09TvlRPD3dXVwu0kIQ1ghr51+QjykMAvJBJZAIBDKZkuBji7KySr59lWSf2/TgZvI3IS4IF+df4GAsgg6YmkEwCWQGg0L+ztsKw04/Pvy3dCgyt7Zh5GZO8sWzsdExuzow2KGgGEcPVgmvpOwuBZ/BSU4fG7vKToeYQQ+cl46MjNysjcwTi3Zxhi2OXba8XB0tSGMwmAyKP3NsTKPVXPXztrGCQczgxBwAld+vEoft7AwPp49xMoabLyYyGAzW9evXy7omtboMYqArCouxsgIFZZczcjOCK6muDtveMTXlXGFrtGOTSskFPp/PKykpYz1u6xL6nCR/54pCYdBo10PEuP8aSf4m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',
    'flower|ruby_swirl': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////97M/8zu8Nrk5dLn4dDg4NPs2tPe3cnb2sjv76j//wDa2rrW2bnW1rjU1bbU1bDV07XT07PS0rPS0rHS0bHR0bLR0a/iysnRzrHQ0LDQybLPz7HOzqnPya3MzLXMzKnLzKbLy6bLyK7KyaXJyaLIyqPIyKTFyaLHx6PHx6DGx5/GxqLGxp/Gxp7ExqLGxaTGxZ7FxZzmvc7avLvWu8DWtr/NwrLMvrPMuLXCwrfCwq7CwqrAwLLAwKrBurHIw5/Fw57ExJ7Dwp3Jv6DBv5/JuKDDwZjAwZbCvpTNt5fDuJbEt4i8wZe9vZ+7vKG9vI66uqG8upG8uo27uaS4uJ+5uJa9uYy8uYy7uYy8uIu7uIu8tqq2tqi3tpy4tZy0tZq7toy7toi2to+ztZXgrbzSsLvOrKvNp7jKsKnLqq3Mp7jKp6vFrq3Fq6nGsZXGq47GpqHGp4nFpYS+srG9r7K6sbC9ra66raq/sZC6sZS+rZK9qbC5qau8pKzBqZ+5qJ+8poPInrDCnqq8oKq5oqq5oaq5oKm4oKm3najEma3DmanDmajAmafBlqe+j6XCoIG6oIjEmZW6mYe9m3m5mHa/mW+4m3bFjnu8i5q5lnO5jouyspqzrp2ysZKvr5GyqZaqqqqqpo+oqJKyr4esroutrIitqoqpqYqrqXezo52zoJ2oopSynaCvoYSlo4WfoJSdnpacnZChoYCenYSdnImzmaWzlqGyk6Gxkp+umYiulJOwkZewj52ujputi5m0i3yximqviWSbm42cmJKcmnaglX6WloGUkn6jjJSljHeajYCPjnWNinDAhqm6iJ25h53lf1nKgW+5h5ashpanhJKwh3ivgJKqfnueho+Xho2ZgYuYfYiheIqReoOVhHKggmCHhWl/f32VeGuOd3u2cGOQb32NcnyMbnqKbXmJbnGJa3fPYz2ZZm6LaXe2VUyjQB+HbHSHaHWHZnOFZnJ5Z2yEYW+DYG6BYW6CXmxLMzr/AEB/AAAAAAEAAAAAAAD4rlsRAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADTVJREFUeNrdmWtQk2fax/sO6oaZQGqCsA2CERJpwyYlQUAOBjmGwyLREIHAG2KkEd9UghxWUBQQiZwkUcC+GzkNEmCAEgU5RCcgUM44IJJuEYw4Wg4l0yqwop/c68H9sjaAtvtl9z9hHh5mnl/+13Vf931f98Mnb/89+uQ/lOObffLfwQnY65jq/Ls59pYnHPbGShJ/J8fBXuhg/tnJ1vOpv4vjaC/aa77XIbUTQKm/nSMUnghwdnBAOJJsUdJv5DgK9wacEAmB46hqzZJkpyb9Jk7M8QTxcaEjYIQilepSlkSS+vGcmJjj8fFfxzg6CGOEouMBKrW67ZJEmP2xHKDEfR0jEjqKRKL/8w1wOl+flp4uEX2sn+Ni8CJaw3wdF+DtZOdBJ/nwoyLTP5ITd1wkihE6OApP+jJtibZUWwIB71bCjw7mf2Rc9mDGad8BooWFKcGKgDfFYjHWjGAe/5BbMOMjOE77vCk0uq3ZbgsrMoGAxWJxJngbhhsjJMSNYY1hfBgHhUKh6bYUWwqNCOGYmFnhCQQbCo3CYDDcXF1cXF0/gIMyQBkYoLaaelJANBsLMh5rZmFFtaUSiQQAMBguiD7Az1Y0ytAQhaNTyGQA0Uk4HAZDjPO3NfNR8MfF+133u+z/EI4p2tp4KwplRqf4+dEoFCsMThxgGS8LMMT4lJfrxsfjXF1DgkM25aDRWLuQnVassAhuBJu2J1DsHSBLYAYGQMqMGWW6Bw/GS0IO8XibcOLRlkQjm6iDAn8m059Jo/slJMiKZUzbPVhjNAplRJTpdLoMPp9ntzEnLi4wIc47QcHw8mf6sdjs0KMNV4rlgZ/TLLBmpsYYM4zRZ9d04wwOP7rEbn3O1q0BTLGsKOFKP/+gICKCyw0LD628dfMKCfJtgcOa4EwsTKyDruniXBnR1T5l63FQW4wItkx5sXJgoIVzmBuGKFTQ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',
    'flower|caramel_swirl': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////5z//wDv7tHr5MPl37fo2Kfp0qbkz53mzpviy5vh38Tg267g1qjgz6Dc2LvM2cjX0MTZz6LhzJzhy5vgyprgyZndypvfyZnOy7rkxZLfyJjex5bdxpbcwpHbxJXbw5PawpHav4zYxJrYwI/Yv47ZvYzXvY3YvYvMxsbTxaXOwKvTw5bSvpDTvY7Fw8vEwrvDvsC+vsHBwp/Cv5TBvpjCvZXXvIzWvIzWvIvWu4vWvIrWu4rVvIvVu4vVu4nXuo7UuorYtZDNup7Nu5HTuovOuY3LtJvKtIrUuYfTt4TQuIXPtIXQtYHLtX/Os3bQsIHNsH3MsHzLr3zJsIC+usC8t76+ua+5uMC4t7K4trbAsai6srG1s6+0srGysLWysK3BvJXCuo/CtpDCtoy8t5q4tpDCsovDr47DsIbCr4W/sZS5sZfdq4XNqn7MrHrLrnrLrnnLrH3Lq3fKrXrKq3nCrZDArYTBrIPIrHrCrIDDqXrNpoXLpXnMn3nCpoPBpXfDoXvDnXzGmn/GlnbElHTOlmnBmHHFjmu1ra+wq7KvrLGvqLSwqLGvp7C7rJ2yq567rIm3qoq0p5e6pn2zoZK2o3+6onq0onq7ona2oXO3moi3mne2mnKxmm+3knmxknG2jXSuq7Guq66uq62tqq+qqqqtp7SrqKypo66ppaWmoaSso5OqpnGloKiin6SlnamhnqOgnaOfm6WnnY+gnpGnnXugm3qdnYidmnujl6qhlqmglquhlKaikqShl4qmlnGkj3ynj2abmKCZmZmbmJealJ2bmHialHebjW6Wk5mWkJeRkpWSjZWOjYzYglm9h2a7h2i5hmm1fV+oiIOrhW+ch2yjf3GrfWOue16QiJGMh46IhoqEgI6Df4aCfoSTiHZ/f3+Ae4CYhWOWfmWTgFnCdU+kdFmQdWZ9d397d357dX56dn14c3t3cXt2cHt0b3nBakZ3bHZya3dyaHXNXTinWj6iQSVxaXZwaHVnZW02NT3qAFUAAIAAAAAAAAB8YKMUAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADXZJREFUeNrdmX0023m+x3tOq2jDbCVp0wltQkwQbWoMbS5DraiHYjyGSXYaUVYTHeWEUk2x2wTbpkRFQyl6k15Bjkh0qaK13CLUQ7Q1SoY5+hCph+o6ivtP7/dnd++5Y4J2Z/+593P8zonj/F55f56+38/3a9uHf41t+z/K8RZT/xWc7/cTqQ6/mrPH05u4n3aV8is5tnuO2HoepNWdov8qDpFIJfyWYEvvrLlKp/7zHKKDN8fTlmhL7awRSynUf5JDdPDkeFOJRFtborxGLJZupGgLDsWby4n4ElBsiZFyuUQsEdM/nfMlxZN7mRZOtHWgfBlJO1/b0FB3Rxwu+VQOxfPyZVpkpIMDJTLyd+c5nnRZfKFAQvlUPTQORKE4ECMjaZkcf4K9l6vlyVRWrOATOWsUEODwiDNB7ji8u8sBLJqcmpbuw/pEv4gUajiBcBiLOYA8iMWgUQiEkT0jhpkWR/Zx/gSOHcHzmJu7izn2IBaPwSAQCCTK/BDDmREdw2B8Zcb4OA7MBGbkZ+PicuxrLAaDRqKx5hgMjuTqwmAwnJ0dHZ2cP4ID2wHbsQMG2+d+jEQiueEO4i0QKAvs1yQXLA7jBAgMR8g+Qs9OE5iJCcTB40kkV19rBAJudDwjiGTuIyoYDHNiODk6fQwHaWxvBoP0kAIC3EgkrBGS43+Qm8sxgfsIs94NZic4OcfEnN6SY2i469BpK1xIYnJicoibdRDneBCP55/AAWgzcuYgsILoOCZrCw7X8MBxo+OpMewgP78AP1c3fy6Xp871t8HBTU1gMFNc9rulpRxWKou8OScjI4h7yZ8rYpwI8PMLDgkJudBYoVYnWLtZIPbuNTVFw03R2a8Ho5mpaankjTk7DTh+CbxcXkU7EJSUlJSYmBxcfK+xzPIL0jELBCAhLXbZB34zmOl0OrXEK20jzk4DU4yNv3q4XTXSHhcG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',
    'flower|matcha': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////+Ds+c3Z9sPb5sPX5rTU37rS37HS3LXQ3LDN26///4///wDN4KbM26nL2qXL16nI1qfH1aTG1KXF1KHE06LB1J/G0arD0qHDzqfC0KLC0Z7GzpzB0Z7B0J/B0J7B0J3BzaLA0JzAz52/z5y/z5u/zpy/y5+9zpq9zZq8zJm7zZS6y5W3zI+6ypm5ypS4yZO3yZK3yY61yYy9xaO5xZu2yJC2xZW1yJC1x5C0yI20xZCzxo2zxoyzx4mzxYuxxJGyxYuxxYuyxIuyxYqxxIqwxIqyw4qxxImwxImww4mwxIS8wK65waW3wZy3wKC2v5+1wJq0v5qywJqzvpm2wZCzv5izvpizv5SwwI+xvpWvwoazvZiyvZeyvJexvZexvJWwvJCzupmvu5O4t4e8p4Cs1Y+uwYetwYKswIWswH+svoirvoKqvoCpvnquu46uupGtuZGruY2ru4iou4Gnu3msuI+ruIyqt4uqto2ptountoqotYuotomotYmotoCotImntIins4mntISlvX2mu3ymunylunujunukunemuX6kuXykuXqjuXqkuXalt4ejtn+ltISms4els4WluHqjuHmjuHWltnmhvHuit3OhtXmgtmmcw4aetXOetGmC5YIA/wCmsoeksoOjr4SgsICgroCerH+qqqqiqYueqYCbqX2apICYo36Yn4agr3idrnibq3maqniZqHeZo3mdsG6Zrm6bqHCZr2GjrFKUqmSSqVyUrFSSqVGUpXOSpGiVn4GVnYKTn3aTnH+Sm3uPp1eNpFuOp0uMpEiPoGuOoF+NnGyJokmIoEWHnU2DnUKCmz9zoUnDj2OdlmqTmX6QmXmPmHqNl3WKl2uKk3KHk26HkW2HmFqEk2CFj2yDjmaAmUN+mDl/kVl4lDlmmV11kDeAjGV+i2N9imN8i2B3jEGbh158iWB7iF56h195hll2hVp0g1hzglVxhTvgek7PcUqGfm7FWzilQCFzgVZsf0ZoeD83QCkBAAAAAAEAAAAAAABAt+V8AAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADb9JREFUeNrdmXtQ0vn6x/dUSjKTWmhhzooreYnY0FLJK0vChrikkhu2Susu06B5T8XLUTdKtFPUGoZmjM6o5OQVxYoRxU0wNTMdT4W3QGtUdBXv4+2fzgfPOX+cDmntnn9+v7fDHzLzec37eT7P9/k+nw9fvP/f6Iv/o5xbNPv/BUdgA/3qwJ/mGFy8aGgTedr5T3IgBtb7LsacYpx2+VMcIwPU1zHHIfZl8YEuzn+cAzWLEfhBdwNOHC3MnvIHORAzb0EMCgoxMjLNZFFpYf6UP8Sx9WuXHDOFQo2gpgfZl+lU2lmXz+eY2vo1S7xhUOheS1Nzb8HVK1fiaaEWQZ/Lgfs1SUnmVrC9lnD4cYHA2yUjMoNBs/hcP8cETSTzg9Z7TRFIXLHklgPmpO/xyJLMYMZnciTe5uaWpkamcIeLSSGubkQCBuMQzOPlxWZ+ZlwGNnZwuAPOCY22QjmikUgQnsuP8Wm8S9jYs5/BsbFxxePJxMOOKEdPNAZAEDYOWBqVxogPorlY0D+NA4VC9oXg8HgcAdixs7F1ckBjXPFEPC2UFkSl+FMDP4ED3Wm0cxcEcogMOHiiK8rzsOUhlCPek+DkevT0mTOhNAqF4uz/CX4gpkbAD4KM8/ICoBB3uKU5zE+ShHOIreP1XTgTFEAJ8P8EjrWJywEIxMiWjI+KIuJxjjBE8S10c48AahYrvL/cB0jU+FjGthxjY2ss47Ajh8vn8nOIJ/4m8bvV0REjEEB2Q2HBZUtLS8tlYaxM9jacZpPj3qYk3qX86IiI6BAiMaq5o7unO8bN6aC5qREEhu1bXl6+8CvvcvDWnKam/HZJTLMolBwdEc7JzsnhNzztHc13I6EskUiYORK+375vqe+HFN7tkuCPcwwMisMF3d0dT/tLYvP5fD6Xy+c0PGltdAf5RllZ2iCsUdbYiL6lC2fC8urOlX2MAzGA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',
    'flower|mint': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////9T72+rl5Oi/5vLG1eLNztS3zuGzzuKqzd7MyMvIxcnIwcfEwMWxyt21xdS4wM/Av8Cqx92oxNijw9iew9qiv9SfvtScwNa/ur+6usG7tr26trm5tLCtu8eku8yptcaitcWstL2ws7KevdOevNKdvNKdu9CcvNKcu9Gbu9GbutCbuM6XuM6dtcicssKYssaurcexq7SxrLOvqLOtp7OwrrGvqLKxrK2urK+uq66uqautqq6sqq2qqqqrqKylrcCfrsGnrrairLWjqbaeqbqasMOXr8Kar76arL2ZqLuuo6yqo66opKmon6ylo6qjoKWinqOknaeapLKboLGfoaeXoKqgnqOgnKKcnaa0lZimmKqjl6qjkaGil6ihlaihk6Scl6ecl5+ZmZmZlZqdkqaYkZ6Yj5yUutOVtsySts2TtcyTtMok8fSQtcuQs8mSscaOsciNsciMssiMsMeKsMeTrsKUq76OrcSMr8aLr8aLr8WMrcSKr8aKrsWKrcWIrcaJrcKHq8ORqb2Nqb6Pp7iOpbiIqcCEqsKJpb2So7aNo7uPo7OJpLiJorSHo7mHobOCqMF+pr18pL5/o7h7o719obp6orx6obt4o795or15obt2pcJvqMSNn76QnquGn7mFn7GJmLaNl6J/n7qBn7OBnLZ/mLeAlqeUkpqTkpOVj5mGk6CKkJd/kqh+kZ5/kJyRjZaOjY6OiZKFipuFhpN6nrd6mbB6l653nbZ3l65xmbB6lLx6kbp6lKp6kaN0k61wkKh5jrN2jrV8jpx4jp52i7F3iZpvja1xibJvh7Fuip1liJvOgGWagYeGg4eFf4iAfqyAe4N/f3+AeoB7gpp8eIB8d39qhK9og65pgq5vhJhqg5htgJtsepVmga5mf51if6VifJZgeKJgeouxdGF7dn56dX15dHx3c3p3cXt1b3qdbGJza3hya3bRXjenV0ilQB5ldJJmb4VwaXdXdKNXc5VWbpRwaHVhZnhXW30fHSOQAGAAAP8AAAAAAAAnbJuFAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADZZJREFUeNrdmWlQk+mahk8VKmkQUEAiJA0mbLIEqLANMRayRmjA0CjJEUv6MKCdhmKRkEDaBGQTOAQT2ZdmDwbIkSW2CauGoOwGUwhokKggILTQggrTf5w3OvNjnAB6+vyZuSmgAvVd3M/9Pu/7Pfn4y4d/jf7yf5SDw8D/FZzkA/vhB/80Z5+Nm9oBTyfYn+So7TPQsLFG+jsZ/ymOuhrM0NpQDR4GQPB/nrPfwK3yiLqagoNxhcP/SY76wSOVbnANNXU1jUB/F4zrdo524cDcxJXIg+pAGjAC4bgL1sX46zkHYYieGyf0AcNAQ/9EJSEw0B+D0cd+LUcf0X3DXR+moQHThyGplUfsg31zT2H1v9YPslJBUWBgJyorUxFRlxnxV1l5Hp5fyQEV6etrqGnoI9PYKVHkFHpkpBWFxeKk531lXWowmIHhkcQo1E9mqEiShYWJCdQGl8ZkpePScV/BMTK0S0pKSUFFoqLIpEgTExMzM1QszhtHTfPG2ejhvoyjqQnRzUqg05N+jiKRrI5aRVmTSDE0Bg2Hw3l7IxDe3l/A0dwD2bMHAjFLJtNoNEYMimxtYomKotPoMTEkOzsc7iQCgThi+wV+IDoQTW2IaQqZDEiMlDgTM6heTDebhkoXssb8o71tEbY2iN05lrp2OhCIpmUKjc1m0GjRemb1V1E9Q5Xa0HQOd21sDB9rm5aWtitHW9sklmoVmV9cXlxeyIhj18ddFYtT6ysBWo9Stba29rKempHH3IXToxsZpRuXl15+PSuLncVgsHvEQ9PDWQkxUD1tkL3dWQAKL8hjUnbmdHdni29c7hHgLrOz2PmFhYXl3D65vP4SA2ViaaGrZwU9ZD22NpaYyWKxKNtzVCH1qfVD0+L7MlZ6OVBxcUl+762WvngyLQllamJhboYyjc4YWwuMorKEiTXbcVRVdSMTrsqn78lm7mVe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',
    'flower|lemon': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////8ny89Xr6cbm48Xi4sPg4bTh3sXd3MzY1sP//43//wDe3qna2qfY2KbW16XW1qbV1aPV1aLU1KLT06PU1KDT06DS06DU1JrPzNTOzL/PzqzKya7S0p/Rz6HKyqPS0ZzQ0JvQz5nPzpjOzZjNzJfKyZjPzZPMy5PMypLKyZLKyJLKyI/Jx4/Myo7Kx43Jx47Jx43Ix47LyIvNynnIxM7JxcLGwcfCwL/CvsLGxaXCwqDBwKfIxpXIxo/FxZfGw5LCwprBwZvCwJPBvpTJxozIxozHxYzFw4zGxInEwojGxH7EwYbBv4LAvYHHv2DDvnDAum2/v62+vpu+ury+uqC+wYi+vY6/vIK+vH6/u32+u32+u3y9u3y+uny9unu+uXG8uci8ura8vZm7u568vY28uoO7uHy5ua26upG6uYu4uZOnupm8tca7tri2tba2srizsbSyrbOwrrGvrK+vq7Cuq66uq62wqbiwqbOuqq64tqa6tp25tpS2tpG5s6C1sqO0spqysZyurKCtqqyqqqqsqp6sqaG+nrqvqLSup62spa6qp6qpp5Wooa6mo6mkoaikoaCmnamkl6yin6ShnqOgnaOen5ShnZ6fm6SamZmhlq2hlaihlqOalpy7toC3t4m2toq2toK6soG0soCxsYOwr3+vroKvrXuurH6uq3mqqYG6tm+7tWK6sGayr3CxrWutqWq7tFK3sFCvq1W3r0azq0W0rDu7pGCupUytpUqtpD2spEyroD2npoKnpXekoHumo2ymolWkm0ugoIOenoOdnYafn3ydnX2cm4Cal3uenGiamWmblmqgl0Ogly7Yh12/iWihk6ahk3ebkqKakWGVkZuUjZmTkYyTkm6Uk2SUj0GPjo+NjI6MiI6JhYuLgJGDgYiOjWaKiGyDf4R/f3+MilCIg0SveWOBfHx+eYF+eXV8d397dn57d3d6dX15c3x3cXx2cXabbGNza3hya3a+Wz2hPyRxaXZwaHVnZW02NT2/AP8AAFAAAAAAAADeZYRRAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADX1JREFUeNrdmWtQk9e6x911moMzhGtJVe6E+61h0xSBAiViCBBuMYgRSiyomMwYTJEAcq85OAghqAmIYEoQBAIBwQQ8RmCHS0CQqzYUA0FtNjgpDMTBCPuLe8X2y6EBtN1fzvnPJAwf3t/8n8u71rNW9rz7z2jP/1FO1EXKf4ITaYmkHPrLnANfhiEtc76n/EUO8gDO7MvI7NJU6l/iIA8kukS6Is/fYKZSz/95DvJQRCT2K6SGQ6NTUv4kB3noSORxChLphfRiMS/Q6NSUP8WhhAr5Md95AYoXns2iX0i/QP14zncUzD1+9nfIr7zx3udORV+trGRepOHTP5aDD+kAlHPe3vhz52KiIz2phTkFl2j4j/UTw+/IPncO7+1FoWS3REb52Puj3THc3Jj8j+TwNRQv5Ff4xGNRno4uHp52tlYB3JqaWO5HxnWAQsGb+XxjZ2PzmbUdHAYzNNS3PEoic2MDYgM/gmNpFujm7+lp5WBj5wq3NTI0NDaxskehUEEkFMrSAPVhHAgEAg35AuHh5u8Ih5ubmNtZweFOCDQCpREO5+sbuDsHsheydy8EAgt2QyAQaEdrV2sjmLWdv4uHo6Otr+97Dg739Qf4gUCBHYhxsJurKwCFOBkaG+h58sPcrGLvcCdv+6J8cV/7fADHBGpvADjmwQgsFo1ws9Mz4UfB73VFQ/Rj6+smJydvo1CkoKBdObq6JvZJFnYRcQlxCQS0cxQ/LKpLGBYdDdAGgbcBZ7I+CFRtF06Hrrsn1LMmlhgeGhoeegSNFXZ1ijrDXOwM9XRB7u2n1Go1j8utCdiZ09ERJeSHCRtRGGwoNoJAOJHcIxB1E53RINcwPX2Yvp7F/cnJJDK3hhuwPQcCicRGd4q6BGPcWGICMT4uLiGCJxm66+SOQFgbG5kYm1ib2B+LBLkO4jZ+U7sdB7IXausSJhKJZ2eHSGcA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',
    'flower|salted': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////6rm5ejb2dzZ09rT0dXOzM/NyczKyM/LxszJxsrIxcrGxMnGwsfDwcjDvcbDv8LAvsi/vr++u8a+u76+usC8usK/ucK9ub68ub68uL68uL27uL+9t7+7t767t727t7y8tL25t8W6tr26t7y6try5tby5s720s8K6t7q5tbq3tbm4s7q3srm2sbm2tba0tLe1sra0srW8s6jNnp22rbi1sLi1rLW0r7ezrbazq7ayr7iyrLWxr7KxrrGyq7WxqrSxp7KwrrKwra+wq7KwqrSwqbWwqbSwqbOwp7OvrbevrK+vrK6vqbSvqrGvqLSvqLOvqLKvp7KtrcWurLOtqbaura6uq66tq66tqq6uq62uqq2tqq2tqqysqq2sqaytqLaup7OuqLKup7Ktp7Ktp6+uprOtprGtpLGqqsSrqa6qqqqpqsRvxs+nqMOnpr2qpa+qp6yppayppqqopamnpKiooq+mo6iqoK6noauhosGioLekoqqjoK2loqajo6OkoaajoKWjoKSioKWYmr2amricm7apn66onq2gmrCcmrCnnaqlmaqinqagmaiin6OinqOhn6OhnqShnqOhnqKhnaKgnqKgnaKgnaGhnKKfnKGem6GemaCcm56bmZ+ZmZmbmJ+kl6mjl6qklaail6qilqmilaihlqmhlamhlaihlaeglquglamclq+ZlrCdlqGZlp2hlKeglKeflKigk6ejkqOmkpyhkqKck6WZk52Zk5uakZ+ajZ+Ul7eTk6yWk52VkZ6TkKOWkJmWlJeUkZaTkpSSkZCSj5OUjaKTjZaMjaSOjZSPjpCOjY+NjY6NjI6Mi43af2W7f3mWiZSWg5CMiZOLiYyMhJCHiayIiJ2Iho2Gg4iHfoyDh7J/gqKAf5OEgYWCf4WBfISCf4J/f3+BfYJ/e4F9eH+ldWx8d397dn57dX56dX12dIZ4c3x3dHp2cHpzbnnDaVR0bHhyanbCWjekQR9waXlwaHVqZ2xeWmUYGR/lAOUAAP8AAAAAAADuPDiRAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADcZJREFUeNrd2WtUk1e6AOBZYogBAsExBUklCiZGrmOO5hBLhBFpKGnIB6mTOmYaaRSCi8U13EcmoEi4GTVtI5E6QI0ayzVEC5FETEBOJDTATIIYDiBdgFyklIuL+eXscM5ZZy0bQKfzZ+ZdsPTP96x37/3u/b3741ev/znxq39Rx/Xk/n+Gs20bygf1ix3YNleHbb5hu3+hg4A5I7bB3s+gEH+R4wj33LZtG5xYlXGE6PuPOygXLy9nhCPcv4rP4uwP/AcdpIuTq5c3ysEBgRRl0Fic9TLaxPF0TWK+twPpgHBE7RaJT9BYNOK7O+6erokJBDTSEeW+HePlJbgmzmCx3Fnv6ri7MhMIGB+UM2b3bi9XVydiRVpBOmvHu+bjZVV2ezgjce8TmF4E75CYuJA0iYiW/o4OUDA7nR2QaP/I4/SgM/GMIBI+SiK5nnHlHccF34t3R++jkwOCfAKCAnA4j51oIodfIM2i8Vnv4HjvCoYgHtcvyD8olETy8NiJ9fY7xqKxUvmsE5QdJ97OcXSEu6TQIYgOkUkBeG882Y9ECoa4EOsk62MakRgW9haOox3CbiscjokHDsQN9qf6eXj7k7kxEJlMohz99CQrMJDoS3mLfOyRDo5OCI94eng4BMXwgjFYjDsh4RTkl9Z2tf9gJOsI8SiRuLnjiSJut4c77OHFCoVcKIaMwTIJ3olJBCQ67UbVYn//wU/C+Pz0TR2Us0dUut/h2mZFs0IWG3qKSSAkJh1PZiIQDuiz94GzeIOTdVW0iZPg7EXY8cH5LGV5dnZZdmxccVJiblHu8ZgQDBrpAEcFDywurty/+qVok3lmMiMTmYTExj/whNnZtTdlMuWNvAvqzOgYPw8cDo3Go9/b07/Yf1YgqZRGre/AYcy45NwLSaWWL9OUSqWiWS6XtT1+WBr6IUT38/TA7fX2x0T+qb///iecStWZ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',
    'flower|rainbow_swirl': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////9/o//bq6NDR5uz//4nm4Lv//wDf27nc2bjh2K3b2bLk0rbj0avdz6zdzarc0K3czKnV0LfZzavfz5jby6jcyqPayqfVyqjUzYrdx6vZx6nXx6TWxaLXxaDXwp7cx3rYwXXUxabUw6DTwKDTwJzUv4XPx6PQwqHIxa/HwprQv5zGv57Rvp7RvpvQvpvQvpnGvpLRvZrQvZvQvZrQvZnNvZvCvY/TvK3SvJnPvJnOu5nPu5jXuMPSssHXt6POuZjMu5nLuJTHupjCu5zFtZ7HtZPKtpLNs5DGtI7HsY3Ks4bQuGfBvIbBun7BunzCtYzDsYzDsIjUq7nMqr3grIjNrITIq5vIq4HFq5zFr4rEr4rEronErITCrpHDronDrYjCrX3Mp7TQpZHFpZnNpH3Eo4DLm4TMmm/GmnvHlXPCknG9zs6/v6C+vaO+vKC+u5+9u6C+u5a9uKC+t5m9tJm+tI6/spO/tni9sJu9sJK9r5G+rpC7ro+8q5q7q42+roK9qoi7qIi+rm+9q2m8qGKszeGmwdO1uKeousG1tpyotbOmsbOpq6qprqOxrZeuqWibvc6Xs8WRsMWXr7+Nr8UL+fqJsMmZrLWQqbuMrcKGq8J/qcO4pJe3pYa5oKiypIewoYilo5Ghnoy3pIK4n4K4om+woH+poHy5m4qtm4GzlYy3l3a1kHOgm4mcm4ihmHqhlX+gknqhkmaMpLWIoraFo7iIoLSApLl8pL98ort+oLZ+m7B6o716obt2pMJ3nLeZnJCamoCYmIOVkYuZkHODmqeBlqV/kZ99j514lql4kaJtkaPcg13HiGW9imy9hme7iWu6hWevinawhWmufmOai3CdgWyWjH+UiHCShWyTgWd6ipSDgHhwiJhrhJVqgJJmgpRlfo9Yfpe9eFSweVukeF6UeV5veoBie4xheotge41eeYpeeIlddohZdYbXbEStb06Ra1VmZpnIXjm6TCiaRSRYcoRWcoRUcYNTaIoTFB2/AA4AAOEAAAAAAAB8oskkAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADPtJREFUeNrd2XtUkmkaAPDZqePBHBUtws6A1iAztrhWhtdFU2y9LV6Yce2EmEhHEpnQLQgXZRnRNDNrdPR4HcILY0t4yTTHvDR5nbRScdTKWTTOqIvmJU+l/dU+n+0fuw1qzew/u48cQI7fj+d93ud7efl879V/J977H3WOX2b/N5w/uXqyPX+143HokIfr0cthv9Lx8PgMpKOXNxrae2/DsF0PuXqwrwLE/uWO52dHjh/y8Fhz1oc2czw+OxR+hO0JjufltWD/Iod9KO4EO8wDYdhXr/5CJ4x9iMs9AopnmGcY+/jVNSjs8rs6YWsK29OTHcZmHz9+iP310a8vrzf56zvsE9yjYWsM++iJGH9X299TiD4S8R/++o7OiSOI4uERxj7i72RL2r+fQMA6S5IlPuJ3HJcHm/2Zq+tBW7w1Bk/AY7EWFmZ2CUKxRGDvc/gdHFfX3x08SNmPI+AIDni8hYUFBosjJcQnCIR/TrC3Sng7x9gYhabsI5MPkgl4PBaDJeDweFuyu1NCQkJ8PJ//55Nv4ZhsMd6yBYWycgeH7G6Lc8BZYHEE8j4ngi3h5Mn4hAQ+n7+X/xb5GFkam5igrCj7HBwA8iJCYczcOP77cD5yyX0mH3FOvoWDMbWzRKGMrShkPz938j4CGhPub83lhZuY+UhlS/diw/nxAoFgU2fbNgs7wSd2dGZURBTDnegf4+bPi/MPDwd6+2HZ0tLST1KB8FjSJg7X1MZtm1uSkBVApfpR3d39uHG8IZ4/iWCBNoHa28YCxBUnJzlv7MRw/eNi/LnyBB8/KjWQzmCwytSDgwySE9Qai0ZjzdAfxi7dSxAnJ0uc13eMjMKp4byBOHW9RMBisZgREVGBZbXXlEQimYzDgITBYexcaEssvkAi95au56CM0ASS/+BQXXf3NSEdFAgGa+zB7XJfRxswsBa2ZELl17Sle/z4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',
    'ribbon|vanilla': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////+PU/9T19tvu7s/p6dDj487h4M/f38jd3czo6cDZ5sDe3cTa3rv5/5jZ3rD//wDc3L/c2b3Y2brW17rW1rTS17PX1bjU1LbT1LTT07TS1LPS0rbS0rLS0rHU0LbR07LR0bPR0LHNzb7PzrPR06/R0a/Q0K/Pz63P0KrNzanMz6DOzKzMzKnMzKfKy6nKy6TKzJjbxLjPw63LyanKyqDJyajJyaDIyKrIyJ7Hx6zHx5/HyZ7Hx57Hx53HxaDHxZzGyJ3GxqLGxp3GxpvGxZ3GxJzGwp3Fx53FxaTFxZzFxZvFw53Exa/Dw7DCwrHBwbfBwbHBwazBwavAwavAwLTAwK3AwKvAwKrDxp/DxKDCxZPDw6LBw5PBwaHCwZbBwZC+wYvOvKjBv5bAvpy/v7O/v6q/v6m/vpq/vIq+vqu9vae9uqu9vaG+u5K+vYy9u4y9uoy8vKW7u6S5u6S7vJ66uqO5uaG5uZ27vI+7uY68uYu7uYu8u4i7uYnbrq7Nr6XIs5/IrJ/PoaXIpJvNmqHKmJ+/tae/tZG8uIu8tYu/q5nCpJm+npC+mpG4uKC3t523t5y6uI+7uIq7t4i5tJO6tYi5q5e5m5G2tqi2t522tpu1tpq1tZy1tZq0upW2toqztpG1tZW0s520tJm0s5izs5azso6xsJuwsJOwsJCuro6uq5KqqqqqqpSvroqrrYmrq4murYWtq2yvqJWnp5CpqIWnpoauo5eno4OkpIujpH2hoYienpCfnoKpm4menI+dnJCdnYScnI2cnISbm4qamomZmY2YmH6ZmWjLkp/EkpjCi5XBh5O0kpq1lIa1i5iZlYKVlXyUlH+Uk3WfjI6VkXmRkXaRkHaQj3OOjnSOjW+Mi3OMjG+Ni2yMi26Li22Lim6KiWuJiGqIh2vGg5vAhJK+go+xg4iigpyjgYCNhG2GhWaFg2OEgmOAf3mEgmGDgWCCgFW4e421eYO0cYqidouMdnigZJ6USrRvQopTJHb/AIAAAAEAAAAAAABE8HXjAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADZ1JREFUeNrdmXs02+m6x/cst0x3LCsuFdE4mgahZLI4xnZrx0SoBENMxdlK6rLDliGip5FzQt0mNCl13VgNmV4SLVrEasI0DW1Da0dNj2tdqjaxggwWZ1qG/cecN+3555hgOrP/2ee7VtayLPms7/O8z+95n+fndz/9Y/S7f1KOOwX9j+DkQWHoE7+ZY+TuDoF+QT7xGzkQI2uou7sHKyzsN3GgR1DmwJBPMys8DP3rOabWHnkgLAi6+QKFjo74lZzfW7jneTiZAg5MwCJTUsIjfhXnuHtxEdoSCoVALewFghgyhRz24ZyjKHdukYc1FGqOsLD1yBOIGlkU2rGoD+XYuBcVeRx1sDS3tbf3yMtz92lIrsyiHPtQP+55gGKPNIfZIz3y8xKdPIkk72SRICrrAzlFHra2CHMIDO6cWHAad4aEx2IxISJhU7rwA+M6gnSCwzH+OBesgwvOBYVCIOA+KRcqxdlR6TEfwHF08MLjSSQM1gXr64ZFIBBIO0wIhUyhs8gxPsdov4wDTtqCitcJ5+biZOeIw7i54PAkfEwMhUw+ezY6POZwDtQAYmAIMUaRdBgiztUXg3B0xQWeCcTh3MKjaTGUCKDIX+DH2BwC/CBJeH9/PJ5A8rK1tz3q8XWBPya542Z8GDkqEvg5ezgHaeFjaQyBOpLwSUmB+DO4o8j8fDRXlQ+DJzff3XrM/irKh5WedSjH1BQRkuWEy+BUc6qZBL+CIo98lSq4MB8CgcJTGnZ+vL37472LwoZDOFxzD4+jHo0XazKo1AwqgZjE5Q4ODRYE4GysYRCItfO9lfjdnZVvGkMO5hQV5RcXJXJbU0KTqEmZTCaztntwSFPgRwC5RlnCHeE2Vvd2d3ZuNYjFIftzIEb5wYWq56r6AXF6TfUlHoeTw5A+flTv543HY5AIOyQKg/jkPuB8ldLUEd+8H8fIyAIbUKAZ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',
    'ribbon|ruby': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX////U///w3+PuytnhyNHqv8/bv8rMxMvYvcjXu8bTu8Xbt8bVuMTTtsLXscHXrr7Rsb7LtcDLsLzMrru9sLa0sbK8rrPlqbPRqrnOq7nOqbjNq7nNqLfMq7rMqbjMqLfMp7bMpbTLqbjLp7bLprXLpbTIqbbBqLLKpbTDpbC7qbC7pa23prCqqqqUqqrKorLIorHIobDPm6jInq3HobDGnq7HnKzEoK/Fna3Em6zFmqrEmqrEmqnEmanDna3DmqrCmqrDmarDmanCmanDmajDmKnDmKjCmKnCmKjCl6nCl6e9oq26o6u6oqu6oau5oqu5oay5oaq5oam5oKrAnau8nqq/ma27m6a+l6a2o6S3oaq4oKm3n6i3nae3m6e3mKS1m6W0maS0mKSzmaWkmZ7SkZ7GkqPDlqbDk6LAlqe/lKbAkaPAjZ29lae9k6a+kKO8jqO9jZ+8i57bgZvvfX/UcnvJf43Jc3/DhpXEfYvCdYK9ip+9ipy7ip68h5m9doS4laO0laKzlKGylaCxk6C1kZ6xkZ64jaC0jZq6iZ62iZy6iJ26iJy5iJ24hqC5h525h5y4hpy6hpq1hpe4hJq1gZm2gJC2doiwlKCwkp+wkZ6vkJ2ukJ2vjqGvj5yvjZqpkZqjkZmrjJiakJSajJGtiZqsiJapiZeph5SqhZaphJKphJGjiJKjhZCeiJCdhI6Xh42XhYyXhIurgZWqgY6lgY+jf5GdgYyXgoqVgYitfZKke4yZfYmndKKfdo2be4KSe4OhcoKVc4GQeoKAf3+PdoCacX2Ocn2Nc32LcnyMcHmOcmrJZ3HIY26/bHnBZHLGXmi/XGm/WGWoZcesa5azaXq1ZXKmZ3KrXGnHU168VWO8T1y7UF6tVH2tTl2rTleuRVStPEv/AP//AADMAACSa4aKbHiJa3eKaneaZmmLaHOHanaHaHWHZnOFZnJ7Z2+MYI2EYW+DYG6CYW6OXmiCX21/XWuVU6iWUVaBSpZ+On5OJmoAAQEAAAEAAAAAAABzqWDkAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADedJREFUeNrd2WtQ0un+APCdLo5sqJj+OaApGKikZ0YpUIijtFisoeayaHVC89J4wUtYO3lDUvGSLplk3gCDk3mLrNTVSQLKy5DlKHkZ1INO2Rsvx8ukZWrnRedhz6vTktbueXP+35EXzPj7/L6/5/k+tx/ffPzvxDf/o07qGZf/hnPpT9+6WP9hZ9dPMWaIeHfbP+iY70ZYxfwUdy7A9Q85EDOPgz8dhLjWRrm7uv5+B4qIuRQDNTd3rY1khrnAf6djbgUUDwsIFGIhjg5ihrnZ/i7HKWYw7aC1BRQCtXAoFLOCzpxw/XrHGii6WNi3UJg9zOFgalGNJOrEGRvW1zr2MQO6WIf9MJijg+PB1EsxBwqSBeHMvV+bz8E0oDigYBYobGzmpVQnwlGGV06NOPTsVzppMQ4OdjCIBRKXlB7n5etPJxCcQ6RSeYT4K5/LDI1FInHfET0J+z0JeAzazh55ICwqX5obEsH6CgeF8KLROP44ogeRgifY2dmj0M6+zCBmeFQw68Be1pc5UKg5LIFKo1FpRDwei8YScXg8ieb//QkWMygQ7hYYyN7ege6E7NxlbrafAxyaP8mDgrPDehD9yHQikeD+A5sVDIfDbd2+IB8zUL5Qc0cOlUKh0egcsr2jg01sWjrVOadJ+lf3wEB3N3e3L3DQVt57zcwhGA6Ny6XTjnjboDNTDw3+PdUCkVN7540m7+yP7lERkds6Fpb7AiJxxItCkVBUTCelp8WmDg0lZaRCzKE2oeL19YbN0ZtRheJtnAGrg7HWsYUR5RcSE1MS6P7cwaERw3CSr7e9jQXE3ObATU34h01NoSR0a2dgIHUoLX1QceY0NzHxIp/P//me3jCZ7svwsMNibJCgoJA3P6yP5kukstDPO+ZmaUkZIyNDY13SU+UiUalQKOLdbXlYRT5MO+Lh6IhGoTzQ3vXACQ+TKU7LP+eY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',
    'ribbon|ruby_swirl': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////97M/8zu79nl5dDn4dLg4NLr2tLe3cnb2snx8af//wDb27rY2bjW1rjU1bXU1bDW07bT07TS0rPS0rHS0bLR0rLR0bHQ0a7iy8rRzrLQ0LDQybLPz7HOzqnPya3MzLXMzKnLzKbLy6bLyK7KyaXJyaLHyqLHyKLHx6THx6DHx5/FxqjGxqHGxp/Fxp/GxZ/GyJzGxp7GxZ7FxZrlvcvZu7rWucXUuK/Owq/Ovq7Ot7DOt5bFw6rFw5/FxJzFwpzGvavGvZrHtp3BwbTBwazBwarCw5zCwZrBwo/AwJDAv67AvpPAubHAuZa9vqa9vpS8vJi8u5a6uqG9uo68uou7uKa5uZ24uJe+uY68uYy8uI27uI28uYu7uIq7tqe2tqa2tpu1tZq7tY+6tom2to+ztZTgrb7SsLvOrKvNqLjLq7PLprTGr63Fq6vGsZXFq5LGp6DGqIrFpoW9sLa8rbO9sKu8rKm+qa65qaq8pa2/sJLArY65sZS+qqC8qoi8po3JoLLBn6u7oaq5oLG5oaq5oKm4oKm3najEmq3DmanDmai/mqjDl6m7l6XAkabDoYW6oYnDmZe6mYi/n326mXi5mHa8mGy8kp+5lXm4lXG9i6C7ipm0sKCyspexsJKxrJeqqqqpqpO0p5ypp5SysImvrYitrImrq4mrqIuqqHq0oqCtoZixnZ6so4SunYGkooSfoJSdnpacnJCdnYufnn2bm4WzmKSylaKxk5+wkaKvkJ2wjqCwlYqxkJCvjY2xiXuviWOil5GZmZOgl3yZmHaoi5afjJGgjXeXloeVlXuSkXqRjHiLinDXgaG7iKC6iJ25h5y5hZy3g5W1hYKphpmogJ6qhXilfYSbho6fgZaYgoafg2aUgYp/f3+LhWuZe4mReoOSeXGRdHmharKRb4SObnuLb3qKbHiJbHWJaneUZ2yIa3aHZ3SGaXN7aG6OY4iEYnCDYW+DYG6DX22AYGycUqOAUIp0OJc8HlD/AP//AAB/AAAAAAEAAAAAAADr/lz7AAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADRtJREFUeNrdmW1Qk2fWx/cZGDfMANFETbogGiGgQdAN1YgCUSAhKJhnN0mjyEuJYGNAwIR3BSw08iaCEjM0FnCWt6QJEhGENHSrVsKrA1ijgDAkkgIPS9hBlOWbe27tl3UDaLtf9vkPQwZmrh//c65zruvcN79785/R7/5LOfvz4/4THJ99/Dj+b+Z8sn8/ZV9CXvJv5FD28imOfzjblpn+mzgUSvw+x32UdB2AUn49h88/47OfAjBdmzg/LvlXcij8/T5n4vnAoWja8sT56cm/iiPYL0o6I0AofIFGcylPnJf+8RwBUIQIhS/gC84EaDo62sXiuPyP5Qj2C4Ei4PMFAqD47M9szK7JEAs+1s+ZRIQi4FPi488k+fgf2OlHdQvi8VIzPpLzC4UiOBvg707c/Ud3AgHvW8U7zeJ9ZFx74+P43gf8iE5OmwnOBBwOg0G7MFnRPJYvi/4RHO8Dh/fsof4Rv93JmUQgYDAY7Eb8TjqNzmTR6C72tA/joFAou0/dPd09vIgEgsNGvDOeQCB6ennS6XQaLTDwKI2+NgdlhbKyQlnjqB6enp5eRCcSHoNzcibvJhOJBBoQjgYi+gA/1rYolA0KS/UgkQBEdcVg0WjiBX93PKPhdJAvjf6BHJydi701CoWjeoaEeHnudkZjE322iiQ+tmhGteLnB9wo+i4Wi7kmx9YWs4u5xZkdFhkRyfZy808k+peV+Sf6QMrsmceXTHXLpgwWL3oNjtB2K9FuJ48VE8JghDC8qCEikUQq8ScRMfYQrb1T/lPm8rLpOM93dY5Q6C9K8hfV04OAw2azOTG1V6WyE25eThgczt4eh0aj85eXTJU8XtWulTkoa59DiZLrZVd7wVBkZEREWPgJxY8PrrpCvvFYzEYszmmTcw1wPmNWNfhVr8SxtrYj7PaXStV9fS0sdkQYIk5M94/NtVx3VxwWj8MQ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',
    'ribbon|caramel_swirl': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////8jm5uD6+aT//wDr4bHh3rPh263j1a3l0aHmz53hzp3hzJzlzpnhy5vkxpPgyprgyJjfyZnfyJjex5bc1rnQ1cXXzKrKzLvZx6Hcx5bQyLjGx8TcxJTbw5PZxJnbw5LJxMXSxJ7XwZnYwZHawZDXwJDbwI3Zv43ZvozXv4zGwMTNwKvBv8fAwLjJv5XDv5fBv5rXvY3XvYvWvYzWvIzWvIvWvIrWu4rMvJ3RvI/Vu4rTu4zWuo7XtpDQt5TLuJLJs5PVu4jUuYXTt4bSt3rRt4LPt4HRtITPs3rQsX/LsoDMsHy+u8G+u6+8t76/t7C5ucG4t7K4tra7s7a1s7a/saO2sqSzsreysa3BvZXAvJfCu5LCuI+8t5q4tpDDtIzDsYzDsYS/s5G5spbarITMrnvLr33LrnrLr3nLrXnKrXrKrHrBrZfBrobBrYTBrIPIrHvJqnnCq37PqIPJqILNo33IonzCqILDp3fBpHvFoIDGm4bIm3nGmXfFlXbEmW/Dk3PCj3C1ra+xrbKwq7KvrLGvqLSwqLGvp7C8rZ60rJ62p5uwp5m7rIm2qoq7pn61poW1oZe1o4C6onu0oXq6ona6oXa1oHG4mZG0kYu2m3i5k3izmnCzlm+2jm+uq7Guq66uq62tqq+qqqqtp7SrqKypo66ppaWmoaSso5OqpnGloKiin6SlnamhnqOgnaOfm6WnnY+gnpGnnXugm3qdnYidmnujl6qhlqmglquhlKaikqShl4qmlnGkj4iljm2nj2abmKCZmZmbmJealJ2bmHialHebjW6Wk5mWkJeRkpWSjZWOjYzDh3S7h2m6h2mzg4+1gGWxe12miIaeiHGnf4yfhmalfmaOiY+NhpCIhomHg4uGf4mCfYWAfYqQh35/f3+Ae4CXg2STgFimdmetdFGVc2uIdG59d397d357dX56dn15dHx4c3t3cXt1b3pzbXiZaY5yanZxaXZvaHloZmmeYLCRTL1tVH11Op8/IFbqAFUAAIAAAAAAAAA/eZebAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADWdJREFUeNrdmWlQU+max3ucghASMR1oKbBAogRQg0rAAAkOGIMTFIlKE2gEJiwXCEsgEERoFslFIwjpgCGobEMcwlKEgBdkbRRGVqECghJIm+oCRCO7UgPFF+c99J2punYAvX2/zPyLL/lwfvV/tvd9zuGbT/8YffN/lHOm3PMfwfnTAWvPY3+Ys/+wM+YAPZP2BzmY/ccxhw/TazO9/hAHg/kedxiH8emuyvTy/Ps51hejOY4YDMaru6pcQvP8OznWx3Cc6O+tAeeYtKq8XLKdo104NMf0lEsQBWN9WSoVl4vLvb6eY01zTEuhXwRWaNaXL52pbmiofVh+Ufy1HJpjagr98mXrY7TLgMJx9MmNzrkjpn2tn0sJP9Iv02gAQ6OncKi4w04OlpQYFv3OV3IgLzSQmouXzlDJ5nZkezMzfWJsTDyD9ZVxYWjfX8ThiOYmZigTrKk+Wg+pe8iPwYplEBm+X8E5hHM85UQmG5iZmOFNzfT0kCi0AdHX19ef4et3wsj3yzgwmDb8rK29/alTWFMTfZQ+1sDUFEtwsPf1AyQbm6sn/XbnwLRgWlowbTTZjkAgkLAmeGM9tAmWZGePxZqevApINh42OJsv8KNlCIPpwAAHjycQHMhWICbE6USqnQFFGON/EvIDtDsHpXvCUBsGMyYTqFQSwQ6LQHGoJmlcjg6CKhB+eBIU4HcymOG/KwcO1yP6H7RwD48MjwwlWVGvnaZmpFM5HBgMZuQStPEhaXM9h8Fi7cJJg5vi4adZjIjzVOq/UhxI1LR0rpxLtcUiETowGMI4v8N/c7MjiEXcmXMtlZN+jZIm9KOco1Ld3UND2Y3FcjnnKAnkGo1AfItE7s3f3Fjnx8TGELfnwLQ4FA6Xm1H8NIYRFxERER4e6VbwuLHI6gjhlLGeHhqFMkGZ5wFOgF+syCl2O46WFtzsKFU+0tnf38kI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',
    'ribbon|matcha': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////+Dt+s3Z98Xc67vZ5L3W4LzS4LLT3rfQ3bHQ27H//4///wDN36fN26zN2qbM2KvJ16jI16bH1aXD1pzE1KDE06HGz67E0qPD0aDC0aDAy6TC0Z/C0J/B0J/B0J7A0J7Azp7E0JzA0JzAz53Az5zAzp2/z5u/zpu/zJy9zpq9zZq8zJm7zZS6y5W4zI+6ypm5ypS4yZO3yZK4you1yYy9xqO5xZy2yJC2xZW1yJC1x5C0yI20xZCzxo2zxoyzx4mzxYuyxI+yxYuxxYuyxIuyxYqxxIqwxIqxw4qxxoaxxImwxIiww4mww4S8wK66waa4waG2v5+2wZq0v5qzv5mzvpm2wZGzwJSzvpizvpexwI+xvpSvwoe0vZmyvZeyvJexvZexvJWwvJCxupWvu5O1s5yq0YatwYeswYCtwIWswH6rv4OtvoiqvoKpvoCpvnqtu42tupCpu4Snu3+mu3ymunymvHmnu3etuZGsuI+suY2st4+qtoyqt4uptoqpt4inuIGptYuotYmntYmntIins4qms4intIWms4elvnalunykunikuXykuXqjuXqkuXmjuXKkuHyjuHmjuHWktoqjtn+ktIOktnyit3eitnmht3ChtmahtHicv36etGmC5YIA/wCmsoiksoOjr4Wgr4CerH+qqqqmqYudqYCbp4Gco4SYo36anoifr3mdrXqbq3maqniZqHiXpHqcsWybrnGZqXKZr2GjrFKTqmOSqVuUrFORqVCVpXKSo3GSpWSVn4CVnYGTnH+Sm32SnXeRoWuNpVWNpkmNnWqMoFiIoUqIoUOFnUeCnEBopk+Tmn+hj5+PmXiPl3mLlnOLlHOIknCSmWaIl2WHlWaFlV2GkGyDj2eDjmiAl0h+mDmAj2d/j1h4lDlnmFp0jzaAjGV+i2N/imV9imJ9i192i0iMh318iWB7iF56h195hll2hVp0g1hzglVxhTuedqt/fnZ0gVeZW7yDQbJygFRofD5fVVlRI3MBAAAAAAEAAAAAAAApcdLSAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADdRJREFUeNrdmX1Q0unax/f0WKQzsr6HypHtqKuZsaGVkm8RK+ymtCqsRyyibeOMa/iaaKioSbgixrrRuBA2zoiYmi+oKROK5bumTL7EaL5tjZpxlHxpFZ39o+dmz/PMM8eDWrvnn/NcDD9+MPP7/K7fdV/3dX+vm4/e/Xvso/9QTh7Z/t/BKbIysT/whzlGV67s+0tMmP0f5BhD/mJ5JS+QRvT6QxxjiPtneceMD5UyiV4nfj8Hah1fdBa6H3KoNJF8yT7kd3Ig1meK4t2hxibGZuxUEvlSaMjv4ricbZEfM4dCTaBmdhw2lUSO9PpwjpnrmRb5KUsTqAXcHHaqKDcnh0mOhIV/KMfuTLMiCGZnaQ63tTteVHTKKysmixYJ+1B/jhU1AwrC3AzhjCmS57mhPg8+HlNyI4L2gRz5GRgMbm5iZut25RrF2wePQ6HcIrhcSQL7A58L4uhqa+OG8UQiHdw9kM5OcFtbr2+Ymdy0iITID+A4WnljsQT8YQ93D38kCm5ni3B0Q5NJZBozPNILRn0/jgkUYhmNwWIxOOCOq6OLpxsS5Y3FYyOpZBIpJJREfA+OiZGxkREE4kQAHCze293/MNzF3QPrj/P0Pkq8QKVeCAEW+h7+QMyMoVDIJwRMQAAAUXzt4DDYGXkKxi1BlvslmhQZFhIW+h4cRwu0JQRi4kLA0ul4LMbD8pPia8iW/iKoTYK04pfqrL9FoJmJtF050I8RaNohzyS+gC/g4U9ek5/9sb8nvrjIGGICO5+le3tXt34vgXNjF06LxbFTZsHcNFFcdHRsNB4f29LTP9Af7+NpBzMzhlgeuTd47lfd26s5ETtzmpt/7JHHt9SSCbHRdAaPx7vToFBN3/YJcoc7O8FgzrbWVvd+1a3ncHK5EdtzIJCi74r7+/v7RrgJIoGggM8XMBraOh/5gni7O8AdEQh3B49ywLl8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',
    'ribbon|mint': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////9T54erk5ujZ1tq54vK61ObMztW1z+KvzeDMyMvJxMrFwMS1ydmvyt60wdK/v8CrxtylxNqkwNWdwdeev9SfvtTAur+9uL28usC5ub+7tby3tLm1s7asu8ist8Wjucmus7uks8KevdOevNKdvdKdvNKdu9Gcu9GcutCavNGautCduMyZuM+XuM6bs8WbscKXssWurcexq7SxrLOvqLOtp7OwrrGvqLKvrK+uq66tq66tqq2sqq2qqqqsqKynrrylrbWgrsGkqrWfqbqasMOXr8Gar72arL2ZqLuspa+npKmqoaynna2ko6ujoKWjnqOapLKboLGfoaeXoKqgnqOgnKKcnaarmK6ll6mjlKail6ihlaigk6qcl6icl5+ZmZmZlZudkqaYkZ6Yj5yUuc+UtsyUtcuPvM4A//+QtMuTssiQs8mOssiMssiKsciRr8SNsMeMsMeMr8aLsMeLr8aLr8WKr8aTrcKTrL2OrsWOq8SLrsaKrsWKrsSKrcSJrcWJrMODrMKRqb2Oqb6Pp7iPpbiGqb+Jpr2Ro7iQorKKo7iKo7WHormHobOCqcF/p7x/pL17pb6Ao7h8orx7o715p755o7x6orx5orx5obt1pbyOnruRnaqInryHn7GEnraAnrmBnLeNlqyGlq+Uk5eHk52BmLWBlLOBlKJ6oLx6n7Z7nbp7mrN6max3nrh3mbJwmrF6lrZ7k7t5l6p6lKd2latxlLCSjp6Sj5OPjo+NjI6OiJWMiI2Ihop9kKx9kJ5+kJ1+j5t/iqx9i5p4j7l1jrh4j6R1i7V1i590iKNuj6xwirBrjqBvh6tnhqGcf7SIf5uEgYaDfJqAfaiAfIJ/f39/eX95gZh8eIB7d397doFpg69ogq5ug5Vpgp1sf5xrepdmf6digKZhfJZed6RgeY6Bc5N6dH55dHx4cnt1b390bXdxbXhyanZkcY1Vc5xWbpSYZbpxaXZwaHhrZX5mZmZOZYaQTbRdVIR0Npw7IVGQAGAAAP8AAAAAAADu5OvaAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADYlJREFUeNrdmXsw2/nex88cqkHKEZWmJRqhGnVfdQsdl5AibOhKnmN5xkM1ZlyypGyEWonLU5U0GVrXJViXYom2calbpO6y0TpGRllJl9KDdaqYOYx/9vnGnj+e7Qnas+ef5/nMJCOZ+b7y/ny+n8/n+/l9/eGXf4/94f8oJw1r9O/gZOhCDaG/m6Nu5a2li3NG/E6O1unzUCtrT4Iz8ndxtLWMjK2MtZCRAGT0r3Og570r0dpaWkaRBKyHodG/yNH+02d8byOolrYWNJjgivU4StEJHEPvMb4JVBsYFEEiXXN1c0V+OgdqiB595HkOMM5DEZ6VpOBgAhaLcPtUDsJbCCgIKBSBQJjkZKCQof4Fn7ud+1Q9n/GFngjEBSjU0NCzkp+Biv+a+dVdLscH94mcR54IIEYLet4kh8dMoDHpsbGWSVxuTS7nE/3SMrxwwRiVHm9DMbeJpWAwpqZwK3wOh5trn4v/BA7K2P72bSbdmmITm0yJNTU1NTe3jsf74hk5vnhbffzHcXR0ILDsFDr99tdxFIqluWWcNYWSkJqZisfjfX3RaDvfj+DonNI8dQoCucSkpaamZibYJFubYmzi6Cn0hASKrS8goYF5f4QeiJ6mjh7EjEmjAVImM9H0koF+vPBuinWugMuwtcPboe1s0SdzrsBs9SEQnSvMVB4vMzUlTt+cn289KuXrwXOrBbPD7DS8bU5uzokcGMzUnmFBKSyrKKsozkzk1abnT4zdreVrQnT00zj7s4KDnco8DucEjhBGiYfFc3LbC7N5vOzMTN7omHRRejclAa6vpwnRt6mcZhwcTHM4acdzhML8sdqMUQE+i5fNKywuLq5oHpTLC6mZNqYYjL6+JdzAoPJgf4fNreEmHc2BaPBZtROLE1IFN7e9oqKirKyiqHNIPEilpd62MTPFXDa3MYutBxw/PLcjo/oojoYGLDbl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',
    'ribbon|lemon': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////8nz9dHs687n5MHh4sLh4bTg3cPd3MnY18X//43//wDf36rb26fY2ajW1qbY2KHW16LV1aPU1KLT06PU1KDT06DS06DT1JrPzNTMy7/Qz63KyK7S0qDPzqPLyqPS0ZzQ0JvQz5nPzpjOzpjOzZjNzJfJyZnPzZPMy5PMypLLyZLKyJLKyI/Jx4/Myo7Kx43Jx47Jx43Ix47KyYvLyXnIxM7JxcLGwcfCwL/CvsLGxaXCwqDBwafBv6bGxZbIxo/Gw5PCw5rBwZvDwZPBvpPJxozIxozIxYzHxYzFw4zGxIjFwofFxH3FxHLEwYbBv4HBvYHEwHfBvHDDvV2+vcC+u6++v5m+u5u+vpG/vIC+uoO/vHy+u32+u3u9uny+uXG8uci8uri7u528vJC8uXu6uaO6uYu4uZKrupK8tcS3tLu4trK1tLS1sbKzsrKzrrO5taK5tpa1taG2tpG0tJC1s521sJywr7GvrK+vq7Cuq66uq62wqbiwqbOuqq6wraSvrZitqqyqqqqsqp6sqaGvqLavqLGrp62rp52upq21nrCro6enpKmmpJ2koKejoKGnnqykmK2in6ShnqOgnaOfnpigm6SdmaOamZqhla6hlqihlK2flaqglaOZlZu3t4q7toC6tIK2toq1toG0s4i1s32zsIGxsH+vroWvrXyuq3+urHmqqoK6tm+7tWK4sWazsG+xrGusqm+7tFK3sFCvq1W3r0azq0W0rDurpn6npnumpYGlo3qnoHWgoIOenoGdnoyfn3uenYChl3mamn2WlnSrpV6upkWmoViem2igmlKalV6upkCtpD6sojqimDugly2yiKyjjpWfjZOXkZuWjpuWkFKSkZSRjpORipSSkW2Sj0eNjI6LiI2JhoqHgoqIf4yCf4eMi2d/f3+CfoKJh1uKhjiLeY5/eYF8eH98dYF7dn58eGl6dX15c3x3cXx2cHp1cHKLaplyanZxaXZvaHloZmmXVL9sVH90N547IFG/AP8AAFAAAAAAAADghz97AAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADY5JREFUeNrdmXs02+m6x2dPnWyzFlFJ5VSJW0bcGY7JaGmjdE9GUHWvW2JIpEukdanSuhSjLt2jqq5FJaggQlQQthzXiohW0LrfOrowjHFZwzo5/ul5o/v8sTtBu2f/c873t7JWflnr/azv87zP+/6e35vP3v1r9Nn/Uc7lu0H/Co6HBoZ69g9zVL92xmjeDA/6gxyMqrr615cjs2Kv/yEORjXM+LIJhvoYgKj/PAdz1tXD6RsMhlaUFZcSRPsnOZiz33q4hmEwVhir3KzbcSmHOTqGE+TE44R8bwUoVqF5uSm342/TPp3zfRC+hRPxPeabc57nQoPdHxQWZt2N84z/VE6oYzOghJ475xkaGuLuYXk9MzI5Kc7zU/2EcJojQkODzllRqRENHpet9WxxZvjKmyFJn8jhXA0N9bTCfOPp5edmaWBsYYnW1cJWMip9GJ8Ylyo1yFPd2hato3NKG41CImAwZU1vEqWShPWx+wSOprqdqa2lpZa+DtrkS10YDAZX0dKzt7f3Jtnb6ynZfxwHAoEoOn5lbmFqa4BCIVWQaC0UytAcZ24vldd5Gzu74zmQzyGfn4BAkA6m5ubmOANtE20YQhtta2xhYKBrc8Dx8lI//xF+IFBgBwJ3MDUxASAHQxhcCWrJcTPV8mFV4vVs7C6cv2D9ERwVRT0pCOlg7uKCMzdFQ1U8LqNa2t0hyj5VdT/3UK7a6V3z8TmWo6CgouetgXYNIIILZ+TGcb7cznN2dwdopUsUyW/MfUkSicE4htOsaGYJtWT4kK84Obk4fotz4bW3vWxzNkbDoAoQCPR0ZpnP/v6YHwN7NKe52Z3HceOx7PEuTi6uvgH+5fyBYTHBCAdyjYAqIWDKJ+/t70tuMhiV2MM5EDkPF/e2l+2tgkofMpFICAggunb09DYZmpmba8NhKnCENhwdvS+RXPWuYl2sOowjJwfV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',
    'ribbon|salted': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////6rp6Ond297a1NvT0tXPzdHMytDLyM7IyMjLxszJxsrIxcrGw8fGwcfDwcjEvsfDv8LAvsi+u8a+vb6+usC8usLAt8G9ub68ub68uL68uL28tb27uMC7uL27t727t7y7tb66t766tr26try6trq6tby5tsG5t7q4tLy3tre2tbe1tLa3s764s7q1s7a3sbqzscO1srWzsbO+q8G1sLi1r7i0rrezrrazrLayr7iyrLWxr7Gyq7WxqrSxp7OwrrKwra+wrLCwq7SwqrSwqbWwqbSwqbOwp7Ovrbevra+vrK+vrq6vqbSvqrCvqLSvqLOvqLKvp7KtrcWurLStqbaura6uq66tq66tqq6uq62uqq2tqq2tqqysqq2sqaytqLaup7OuqLKup7Ktp7Ktp7CuprOtprGtpbGsobOqqsGqqqqqq6easMqnqMWqqLirqKuqp6upp6qnpbuqpa+ppaunpauopamnpKijpKOpoq6mo6iqoK6noauhosGioLekoauloqajo6OkoaajoKWjoKShoKKYmr2amriamrepn66ona6fm7CmnqqmnKqlmaqinqeim6ahmaiin6OinqOhn6OhnqOhnqKhnaOgnqKgnaKfnaGgnKOfnKGem6CemaCcmp2amZqbmJ+kl6mjl6qil6milqmilaihlqihlamhlaihlaeglaialrCclqCalp6ZlZ2hlKmglKiglKegk6Wek6eZlJ2ikaafkqeakqGYkZubj6SUl7eTk62Wk52VkZ2UkKOWkJqWlJaUk5KUkZWRkZKSj5OTjaiVjJ2TjZaMjaeOjZaPjpCOjY+NjY6NjI6Mi42sgLmRhpiNiZCNg5KKipmLiYyKhI2GiayHiaaFhqKHho+HhYiFgoaGfYuAg6h/fo2Cf4SBfYN/eoN/f39+eoB+eH98d396d32RcqR7dn56dX15dHx4cnx1coN2cXh0bnlzbHdyandxanWaZbVxaXZvZ3hnZWmPTrhkTXpxNpo3HEzlAOUAAP8AAAAAAAAiNmWzAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADb9JREFUeNrd2WtUk1e6AOBZIpDFrQTMMYbRIMQo9wAnJpTAskhD25yQD6iToc1IaeQia1a4TDAMV1kJIxKuRlObEmMxBky5CIEsDFBNBCFDKCAQPTRBLgszXFJBYQ6LP54dp+ePE0Hb+TPnXYsf/Pge3v3u99vf3pvfvPzXxG/+TR23z4/9KxyYPdwX/qsdW3s3R3ufDzx/pQOzfc/B3vZoHin0VzlOMC97e3tYiARAgb/cgbu5u78Hc4YFSTj0pCN+v9BxdnNyc/eGOzrCnAV5FHpSqN8vcg66sYIPIpwdHZzgngJhIoVOCXl3B3nYjZURgHB2giPhHkfduSJhHp2OjH1XB+mWkBHgcQTuivb0POrm5kSszeXl0Pe9az7/EQwUDMrVBYMKSHAPPhwRnxqRKxJE5byjk3HUw+PAe44uCNzHp6iElDQa4Tg2ViS6lnflHccF88QiET5UIo6AxRPwGAzqACIkicMTF0Sdo7+D430wHILSmYEEHCESfxyFOoD2DjxJp9CzOfTE0H2Jb+c4OcFc2VQIokJEPB7rjSX44PHhEDOenkinUIJCPol6C8fJxsFmL8wenQYciBmOIweivHFEZjxEJOJJlERGor9fkG/oW+Rj7+Lo5AxDpVGjoyEoPj38ENoDGZCRCQXmKq/+kRT1uxOhpNC3cA7DiXB7mOPh9OSKCiYUT/RAJwR7sVjBLojc68qlodL0z0gcTs6uDtwVFZsTGCZtV7QrZMmRmQnBwSzWqcxgB5gj4vRftpaub2/w864KdnFY7x0NQL7PK+iuLiyszk9OrWCxisuLT8VHeCBcHGHu/u1Lf9ze3vjz5V3qnJCQwUoIZrX+IZ1fWCi9KZN1NpRc6M2Piw9EYTAIBBaJRLZvb23UXqkXx77ZcbBNSM0svsCqNFzN7VYoOtrlcply4PvKyA8haqAXCuPphfMidm5vjaec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',
    'ribbon|rainbow_swirl': 'iVBORw0KGgoAAAANSUhEUgAAAEcAAABaCAMAAADdJrtoAAADAFBMVEX//////8/o//bv7dPj4srQ5uz//4bl37v//wDe27nb2bfg2K3k0rfj0avdz6vdzarc0K3czKnSz7/Y0K7Zzarfz5rby6jcyqPayqfVyqjUzYzdyKvZx6nXx6TWxaLXxaDXwp3cx3rYwXLUxabUw6DTwaLTwZ7TwJzUv4XOx6bQwqHHw6TQv5vGv57Rvp7RvpvQvpvQvpnFvpPRvZrQvZvQvZrQvZnNvZvCvY/SvKrSvJnPvJnOu5nPu5jXuMPSssLYt6TPuZrMu5nMuZfLuJTHuprCu5zFtZ7HtZPNt4zQumrItorNspDMsnrHsozBu4TBunzCt4LFsYzDsY7EsIbgrJbOrKrLq7XLq4TFrJnEr4rEronFrW/Cq5LCrYvDrYjCrXzMp7PHpK3Kpo/NpX/Eo4DIm4LJmXPFlnTDkHG90M+/v5+/vaK+u6C9u6C/u5a9t6K9t5q+tZi+tJC/tnm9sZy+sZO9sJK+sJC8ro+8q5i8q42+r32+rIO+rmu9q2i8qIm8qGyszeGpwtC1uKepusGztae1tpWotLOks7KosLSpqqqrr6KyrpiyqI2uqWicvc+Xs8aRsMWXr7+Nr8UL+fqJsMmaq7ORqruMrcKGq8J/qcO5oay3o5W4pYi3o4a0o4awo4evoIqlo5Ghnoy3pIK4n4K3onGwoH+poHu0maSwkaC1mn+pmYKdnIuemoKeloO+mXmzmHm4kXKml3KjlG+ikG2MpLWIoraFo7iIoLSApLl8pL98ort+oLZ+m7B6o716obt2pMJ3nLeZnJCamoCYmIOVkYuZkHODmqeBlqV/kZ99j514lql4kaJtkaPGiHW8iWu7iGqyi4W4iGu0gHGejHyXjHmjgoqfhWilfmWUinuThmyQgWd3i5pyi5x6gohrhZdqgpJof5BkfpBifI1SfpmseXGzd1WVeWyYdlloeohheotgeotdeYpdd4hbdodadIVXc4VVcoSiapFzZ35WcYNRbn+VVKyDQKRfO444F1K/AA4AAOEAAAAAAADS/xhcAAABAHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8AU/cHJQAADO5JREFUeNrdmWtQU9cWx3urDhOUl5QYvE3ANiaCUFAMrzRAIVAMEQSsYKJBlEdyCWiiBmJ4FdHBQRQKw1sMKjSIIfIQkCKvCgQkMGRoEapSEKaY8tbhgl+868T2w7UBtO2XexeZCYeZ/Tv/9d9r773O4YPXf0988D/KoRcG/B2crxycA5z/MsfJ5Ssnp2OrKnoXjpNTgJOLy8Fbhcf+EsfJKdjBxcXpWDmAAv48x9n50HEXJyc1pzAg4E9ynJxdAg8FOwPHGeEUrmTSGpzgg+ywgwjFyTmgvBzhHHt/jnOwCzvsWADCcA44eLy8XJ1Z4ftyAlzCgBLs7BwQAJTjLsduHbr6J/I6eBwoAQHOzsHBx8JC6A7bP6eYUoXRX559T07YQYQCtRNwiG5LsNi1C4/H2AljhJ7R75mXU3BwgIPDnu04EzQOj8NgDAx0zXn8aCHf0t3jPTgODl/s2UPZhcVj8VY4nIGBARqDtYuKjOTxozx2Gke9G0dbG6VPsSCR9pDwOBwGjcFjcTgCiWwbiQSXG8WNXJujvQ61bj0KZUy2JpFIZALWCmuAweJJ1rYEAo4bBYq4O+HnHfRoGaJAjzHF2soKQBQiGKPrGEq3xrqLhbsjuBFcJNbmoHXMDVEobWMKiUolk6zx+uhAugmbE6it6ykqennz1MmICD6ftyZn40YDc56ZuR+TyWD6kYn0EEc6h00PDAS0oXvM8su45aVCfkz0GpxwHVPHjY5CfpA3lepJJZM92WxOP4duQTDQR7w3uVV+4tVy+alou9U5IWF0dgidXRTpTqVS/SBY16uUSibBFrzG6Oti9PR0b71aXjobIxTarcxBaQVSA+H2VT+CoKAgJoPB8C7ukN4mEkkkLBpIaCwafxU4Jz2E11xFK3G0tPTxFnSlsmZwUMr3RygMhl/QUMeDG542psDAGBBIeLH/S+BE8ASiIs2c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',
}


def _alc_cell(deco, cream, when, eats):
    return ('<div style="width:104px">'
            '<div class="alcs" title="%s %s">'
            '<img alt="%s %s" src="data:image/png;base64,%s" class="alcimg"></div>'
            '<div class="sm" style="margin-top:4px;line-height:1.25"><b>%s</b></div>'
            '<div class="muted sm" style="line-height:1.25">%s &middot; %s</div>'
            '</div>'
            % (esc(deco.title()), esc(cream.replace("_", " ").title()),
               esc(deco.title()), esc(cream.replace("_", " ").title()),
               _ALC_ART["%s|%s" % (deco, cream)],
               esc(cream.replace("_", " ").title()), when,
               "uses it up" if eats else "keeps sweet"))


_mm.append('<style>'
           '.alcs{height:96px;display:flex;align-items:flex-end;justify-content:center}'
           '.alcimg{max-width:100%;max-height:96px;image-rendering:pixelated}'
           '</style>')
_mm.append('<h3>Every one of the 63</h3>')
_mm.append('<div class="card"><b>How to read this.</b><div class="sm" style="margin-top:6px">'
           'One block per sweet &mdash; that is the <b>topping</b>, and the heading says how to '
           'cook it. Within a block, each tile is a <b>cream</b>: the colour is sampled from '
           'that form&rsquo;s own texture, and under it is the time you have to evolve at and '
           'whether the sweet survives. Pick a tile, cook that sweet, hand it to a Milcery and '
           'level it up at that time.</div></div>')
for _d, _dye in _ALC_SWEET:
    _mm.append('<h4 style="margin:18px 0 2px"><span class="ic icsm" data-i="%s_sweet"></span>'
               '%s Sweet <span class="muted sm">&mdash; %s dye + honey bottle + sugar, '
               'in a Campfire Pot</span></h4>' % (_d, _d.title(), _dye))
    _mm.append('<div style="display:flex;flex-wrap:wrap;gap:11px;margin:8px 0 4px">')
    for _c, _w, _eat in _ALC_CREAM:
        _mm.append(_alc_cell(_d, _c.replace(" ", "_"), _w, _eat))
    _mm.append('</div>')
print('alcremie: %d form tiles rendered' % (len(_ALC_SWEET) * len(_ALC_CREAM)))


# ---------------- dex sprite atlases ----------------
# Rendered by tools/dexrender.py and served as files from /mc-wiki-img/ rather than embedded:
# ~2000 sprites is about 18 MB, which would take this page past 20 MB. The manifest is small
# enough to inline, so the page needs no extra request to know where a sprite lives.
try:
    _SPR = json.load(open('/tmp/dex-sprites.json'))
    _SPR['base'] = '/mc-wiki-img/'
    # Re-key on the normalised species so the page can look a sprite up from the display
    # name it already has ("Mr. Mime" -> mrmime), and index the variants per species so the
    # "How it looks" strip does not have to scan 2000 keys per row.
    _m, _by = {}, {}
    for _k, _v in (_SPR.get('map') or {}).items():
        _sp, _, _var = _k.partition('|')
        _n = re.sub(r'[^a-z0-9]', '', _sp.lower())
        _m[_n + ('|' + _var if _var else '')] = _v
        _by.setdefault(_n, []).append(_var)
    for _n in _by:
        _by[_n].sort(key=lambda v: (v.count('|'), v))
    _SPR['map'], _SPR['by'] = _m, _by
    # Cache-bust the atlases. The sheets are served with max-age=14400 and keep the same
    # filenames across a re-pack, so a browser holding yesterday's dex07.png would pair it
    # with today's inlined manifest and draw the wrong sprite in every cell. Stamping the
    # URL with a hash of the manifest makes a re-pack a new URL.
    _SPR['ver'] = hashlib.sha1(
        json.dumps(_SPR['map'], sort_keys=True).encode()).hexdigest()[:10]
    print('dex sprites: %d in %d sheets, %d species'
          % (len(_m), len(_SPR.get('sheets') or []), len(_by)))
except Exception as _e:
    _SPR = None
    print('dex sprites: manifest missing (%s) - dex will render without pictures' % _e)


# ---------------- Primal Reversion ----------------
# Lorelei's Kyogre in the Kanto Elite Four is Primal - her entry carries aspects ["primal"]
# and a mega_showdown:blue_orb - and the page said nothing about how that is done. Worse, the
# item list has exactly one "Blue Orb" and it is the WRONG one: mythsandlegends:blue_orb
# SUMMONS Kyogre, while mega_showdown:blue_orb is the held item that triggers the reversion.
# The Mega Showdown pair never made the item list at all, lost to the name collision, so
# anyone following the page would craft the summon item and wonder why nothing happened.
_mm.append('<h3>Primal Reversion</h3>')
_mm.append('<div class="card"><b>Kyogre and Groudon have a Primal form, and it works like a '
           'Mega.</b><div class="sm" style="margin-top:6px">It is a <b>battle transformation</b>, '
           'not something you catch or keep &mdash; give the Pok&eacute;mon the right orb to '
           '<b>hold</b> and it reverts during battle. Lorelei&rsquo;s Kyogre in the Kanto Elite '
           'Four is exactly this, which is why it does not look like the Kyogre you have '
           'seen.</div></div>')
_mm.append('<div class="card warn"><b>There are two different items called &ldquo;Blue Orb&rdquo;.'
           '</b><div class="sm" style="margin-top:6px">The one in the item list below is '
           '<code>mythsandlegends:blue_orb</code>, which <b>summons</b> Kyogre. The one that '
           'makes it go Primal is <code>mega_showdown:blue_orb</code> &mdash; a different item '
           'from a different mod, with the same name and a different source. Same trap for '
           '<b>Red Orb</b> and Groudon.</div></div>')
_mm.append('<div class="tw"><table><thead><tr><th>Form</th><th>Hold this</th>'
           '<th>Where the orb comes from</th></tr></thead><tbody>'
           '<tr><td><b>Primal Kyogre</b></td>'
           '<td><code>mega_showdown:blue_orb</code></td>'
           '<td><b>Lugia Temple</b> chest &mdash; about <b>1.6%</b> per chest</td></tr>'
           '<tr><td><b>Primal Groudon</b></td>'
           '<td><code>mega_showdown:red_orb</code></td>'
           '<td><b>Bell Tower</b> chest &mdash; about <b>0.8%</b> per chest</td></tr>'
           '</tbody></table></div>')
_mm.append('<div class="card sm"><b>If it does not trigger,</b> wear the <b>Omni Ring</b>. Mega '
           'Evolution needs the ring as well as the stone, and it is the first thing to rule '
           'out here.</div>')
print('primal: reversion section added')


# ---------------- transformations ----------------
# Every form you trigger yourself, what triggers it, and whether a wrist item is also needed.
# The page previously documented Mega and Gigantamax and nothing else, so Primal, Crowned,
# Origin, Therian, the fusions and Ultra Burst were invisible - you would only meet them by
# losing to one. Trigger items are read off Mega Showdown's own item registry; the aspects
# come from the resolvers, so a row only exists if the form is really in the pack.
# Use the FULL aspect name: it is 'origin-forme', 'therian-forme', 'black-fusion',
# 'ultra-fusion', 'complete-percent', 'sky-forme' - grouping on the hyphen while
# auditing hid that and six rows silently rendered no sprite.
def _spr_img(species, variant, px=54):
    """Reuse the dex atlas server-side, so these tiles need no extra request."""
    if not _SPR:
        return ''
    key = re.sub(r'[^a-z0-9]', '', species.lower()) + (('|' + variant) if variant else '')
    e = (_SPR.get('map') or {}).get(key)
    if not e:
        return ''
    t = _SPR['tile']
    sc = px / float(t)
    return ('<span class="dexspr" title="%s" style="width:%dpx;height:%dpx;'
            'background-image:url(%s%s?v=%s);background-size:%dpx %dpx;'
            'background-position:-%dpx -%dpx"></span>'
            % (esc('%s %s' % (species.title(), variant.replace('|', ' + ') or '')),
               round(t * sc), round(t * sc), _SPR['base'], _SPR['sheets'][e[0]],
               _SPR.get('ver', ''), round(_SPR['cols'] * t * sc), round(_SPR['rows'] * t * sc),
               round(e[1] * t * sc), round(e[2] * t * sc)))


# (label, species, form aspect, how, ring needed, works here?)
# "Works here" is the column that took the digging. Mega Showdown drives Mega itself, from
# data/mega_showdown/mega_showdown/mega/*.json, and that is where the bracelet requirement
# lives. Primal, Crowned and Origin are NOT MSD mechanics at all - the orbs are registered
# with CobblemonHeldItemManager.registerRemap(BLUE_ORB, "blueorb"), so the Showdown battle
# simulator applies them exactly as the games do. Nothing checks for a ring, and none is
# needed.
#
# The rest is the uncomfortable part. MSD declares registries for held_form_change,
# form_change_interact and form_change_toggle_interact, and NOTHING on this server fills
# them - not MSD, not Myths & Legends (which only uses those items as spawn conditions),
# not a datapack. So Therian, the Kyurem and Necrozma fusions, Zygarde Complete and Hoopa
# Unbound have models and items but no trigger. Listing them as obtainable would send
# someone hunting an item that does nothing.
_TRANSFORMS = [
    ('Mega Evolution', 'charizard', 'mega_x',
     'Hold that species&rsquo; <b>Mega Stone</b>. 76 species have one; Charizard, Mewtwo '
     'and Raichu have both an X and a Y.',
     'Yes &mdash; Mega Bracelet, Mega Ring or <b>Omni Ring</b>', 1),
    ('Primal Reversion', 'kyogre', 'primal',
     'Hold <code>mega_showdown:blue_orb</code> (Kyogre) or <code>red_orb</code> (Groudon). '
     '<b>Not</b> the Myths &amp; Legends orb of the same name &mdash; that one summons.',
     '<b>No.</b> The battle simulator handles it from the held item alone.', 1),
    ('Gigantamax', 'charizard', 'gmax',
     'Feed it <b>Max Soup</b> (Sweet Max Soup for Urshifu). 32 species can.',
     'Dynamax Band or <b>Omni Ring</b>', 1),
    ('Crowned', 'zacian', 'crowned',
     'Hold the <b>Rusted Sword</b> (Zacian) or <b>Rusted Shield</b> (Zamazenta).',
     '<b>No</b> &mdash; simulator-side, like Primal.', 1),
    ('Origin Forme', 'giratina', 'origin-forme',
     'Hold the Mega Showdown <b>Griseous Orb</b> (Giratina), <b>Adamant Orb</b> (Dialga) or '
     '<b>Lustrous Orb</b> (Palkia).',
     '<b>No</b> &mdash; simulator-side, like Primal.', 1),
    ('Eternamax', 'eternatus', 'eternamax',
     'Eternatus only.', 'Dynamax Band or <b>Omni Ring</b>', 1),
    ('Therian Forme', 'landorus', 'therian-forme',
     'The <b>Reveal Glass</b> exists, but nothing on this server makes it change the form.',
     '&mdash;', 0),
    ('Black / White Kyurem', 'kyurem', 'black-fusion',
     'The <b>DNA Splicer</b> exists, but no fusion mechanic is installed.', '&mdash;', 0),
    ('Ultra Burst', 'necrozma', 'ultra-fusion',
     'The N-Solarizer, N-Lunarizer and Ultranecrozium Z exist, but no fusion mechanic is '
     'installed.', '&mdash;', 0),
    ('Complete Forme', 'zygarde', 'complete-percent',
     'The <b>Zygarde Cube</b> exists, but nothing here assembles the Cores.', '&mdash;', 0),
    ('Unbound', 'hoopa', 'unbound',
     'The <b>Prison Bottle</b> exists, but nothing here uses it to change the form.',
     '&mdash;', 0),
    ('Sky Forme', 'shaymin', 'sky-forme',
     'Cobblemon has the form as a feature, but no installed mod makes the <b>Gracidea '
     'Flower</b> apply it &mdash; an admin can set it.', '&mdash;', 0),
]

_mm.append('<h3>Transformations &mdash; what turns into what, and how</h3>')
_mm.append('<div class="card"><b>Give the Pok&eacute;mon the item; it changes during battle '
           'and reverts after.</b><div class="sm" style="margin-top:6px">You never catch or '
           'keep these. The column people miss is the last one: <b>Mega, Gigantamax and '
           'Eternamax also need a wrist item worn by you</b>, and nothing happens without '
           'both halves. The <b>Omni Ring</b> covers Mega, Dynamax, Tera and Z at once. '
           'Primal, Crowned and Origin need <b>no ring at all</b> &mdash; those orbs are '
           'handed straight to the battle simulator, which applies them the way the games '
           'do.</div></div>')
_mm.append('<div class="tw"><table><thead><tr><th>Transformation</th><th>Looks like</th>'
           '<th>What you do</th><th>Ring needed?</th></tr></thead><tbody>')
_ntr = _nwork = 0
for _lbl, _sp, _asp, _how, _ring, _works in _TRANSFORMS:
    _b = _spr_img(_sp, _asp)
    if not _b:
        continue                      # form not present in this pack - do not claim it is
    _ntr += 1
    _nwork += _works
    _tag = '' if _works else (' <span class="pill hot">not available here</span>')
    _mm.append('<tr%s><td><b>%s</b>%s</td>'
               '<td class="nowrap">%s<span class="muted">&rarr;</span>%s</td>'
               '<td class="sm">%s</td><td class="sm">%s</td></tr>'
               % ('' if _works else ' style="opacity:.72"', _lbl, _tag,
                  _spr_img(_sp, ''), _b, _how, _ring))
_mm.append('</tbody></table></div>')
_mm.append('<div class="card warn"><b>Six of these are not obtainable on this server.</b>'
           '<div class="sm" style="margin-top:6px">Mega Showdown leaves its '
           '<code>held_form_change</code> and <code>form_change_interact</code> registries '
           'empty, and nothing else fills them &mdash; Myths &amp; Legends uses those items '
           'only as <i>spawn</i> conditions. The models and the items exist, so the form '
           'looks reachable and is not. Marked above rather than left for you to '
           'find out.</div></div>')
_mm.append('<div class="card sm"><b>Some forms change on their own</b> &mdash; Aegislash&rsquo;s '
           'stance, Castform in weather, Mimikyu&rsquo;s busted form, Darmanitan&rsquo;s Zen '
           'mode, Wishiwashi&rsquo;s school, Palafin&rsquo;s Hero form, Cramorant gulping. '
           'No item, nothing to do; they flip mid-battle by themselves.</div>')
print('transformations: %d listed, %d actually obtainable here' % (_ntr, _nwork))

megamining_html = ''.join(_mm)

# Icons render at 15-22px. A few mod textures are enormous - temple_lock is 1024x1024
# and costs 1.3 MB of base64 on its own - so cap what gets embedded. Anything over the
# cap falls back to the text abbreviation, which is the right trade for ~130 decorative
# blocks nobody looks up by icon.
# Measured, not guessed: of the 82 referenced icons with no thumbnail, exactly ONE
# (instant_dex, 2604) sits between 2500 and 3000, and admitting it costs 2.5 KB.
# temple_lock and friends are still far above this.
_TEXCAP = 3000


def _tex_put(base, raw):
    enc = _b64.b64encode(raw).decode('ascii')
    if len(enc) > _TEXCAP:
        return False
    D3['tex'][base] = enc
    return True


_missing = {b for b in _need if b not in D3['tex']}
_added = 0
if _missing:
    for _jp in sorted(_glob.glob(COBBLEMON_DIR + '/mods/*.jar')):
        if not _missing:
            break
        try:
            _z = _zip.ZipFile(_jp)
        except Exception:
            continue
        for _n2 in _z.namelist():
            if not _n2.endswith('.png') or '/textures/' not in _n2:
                continue
            _base = _n2.split('/')[-1][:-4]
            if _base in _missing:
                try:
                    if not _tex_put(_base, _z.read(_n2)):
                        continue          # too big to embed; leave it to the fallback
                except Exception:
                    continue
                _missing.discard(_base)
                _added += 1
# Blocks do not have a texture named after them. CobbleFurnies' acacia_cabinet resolves
# as models/item/acacia_cabinet.json -> parent block/cabinet/acacia_closed_left ->
# a textures map. Follow that chain for whatever the basename sweep could not find,
# which is almost all of the furniture and breeding blocks.
if _missing:
    _models = {}          # "ns:path" -> (jar, entry)
    _texfiles = {}        # "ns:path" -> (jar, entry)
    _jars = {}
    for _jp in sorted(_glob.glob(COBBLEMON_DIR + '/mods/*.jar')):
        try:
            _z = _zip.ZipFile(_jp)
        except Exception:
            continue
        _jars[_jp] = _z
        for _n2 in _z.namelist():
            _pt = _n2.split('/')
            if len(_pt) < 4 or _pt[0] != 'assets':
                continue
            _ns = _pt[1]
            if _n2.endswith('.json') and _pt[2] == 'models':
                _models['%s:%s' % (_ns, '/'.join(_pt[3:])[:-5])] = (_jp, _n2)
            elif _n2.endswith('.png') and _pt[2] == 'textures':
                _texfiles['%s:%s' % (_ns, '/'.join(_pt[3:])[:-4])] = (_jp, _n2)

    def _model_texture(ref, depth=0):
        """Follow parent chains to the first real texture reference."""
        if depth > 4 or ref not in _models:
            return None
        _jp, _n2 = _models[ref]
        try:
            _d = json.loads(_jars[_jp].read(_n2).decode('utf-8-sig'))
        except Exception:
            return None
        _tx = _d.get('textures') or {}
        # "particle" is the dust colour, not the face - use it only as a last resort
        for _k in sorted(_tx, key=lambda k: (k == 'particle', k)):
            _v = str(_tx[_k])
            if _v.startswith('#'):
                continue
            if ':' not in _v:
                _v = ref.split(':')[0] + ':' + _v
            if _v in _texfiles:
                return _texfiles[_v]
        _par = _d.get('parent')
        if _par:
            if ':' not in _par:
                _par = ref.split(':')[0] + ':' + _par
            return _model_texture(_par, depth + 1)
        return None

    _byname = {}
    for _key in _models:
        _ns, _pth = _key.split(':', 1)
        if _pth.startswith('item/'):
            _byname.setdefault(_pth.split('/')[-1], []).append(_key)

    _viamodel = 0
    for _b in sorted(_missing):
        for _key in _byname.get(_b, []):
            _hit = _model_texture(_key)
            if not _hit:
                continue
            try:
                if not _tex_put(_b, _jars[_hit[0]].read(_hit[1])):
                    continue
            except Exception:
                continue
            _viamodel += 1
            break
    for _b in list(D3['tex']):
        _missing.discard(_b)
    print('textures: %d more resolved by following block models' % _viamodel)

print('textures: filled %d missing thumbnails, %d still unresolved' % (_added, len(_missing)))

tex_payload = json.dumps(D3['tex'], separators=(',', ':'))
# ---------------- items & recipes ----------------
# The page used to show, for each of 2,609 items: a "What it does" column filled from
# tags (empty for 90% of rows) and a "Recipe" column holding the recipe TYPE - the literal
# string "furni_crafting" - rather than a recipe. Everything needed to answer the actual
# question (what is this, where does it come from, how do I craft it) is in the index, so
# join it here and let the client draw it.

# Index 3 stays the generic fallback (anything not listed lands there), so new kinds
# are appended AFTER it and the template's label array matches position for position.
_KINDS = ['shaped', 'shapeless', 'furni', '', 'pot', 'potless', 'brewing']
_SBL = []            # string table: basenames referenced by grids and ingredients
_SIX = {}


def _sid(b):
    if b not in _SIX:
        _SIX[b] = len(_SBL)
        _SBL.append(b)
    return _SIX[b]


def _mod_ns(display):
    """The row's own namespace, not whichever mod _NSFIX prefers.

    35 item names are defined by two mods. Resolving by name alone would attach Mega
    Showdown's griseous_orb recipe to the Myths & Legends row, which is a different item.
    """
    return re.sub(r'[^a-z0-9]', '', str(display).lower())


def _row_nsid(row):
    bare = str(row.get('i') or '')
    want = _mod_ns(row.get('m'))
    # A row that already carries a namespaced id AGREEING with its own mod column is
    # better evidence than the index, which only knows the mods it was generated from -
    # it has no Cobblemon Cards in it, so every Cards row would fall through to _NSFIX
    # and lose its recipe. Self-consistency is the check: the namespace has to match the
    # mod column, so this cannot rescue a row that is simply wrong.
    _x = str(row.get('x') or '')
    if ':' in _x and _mod_ns(_x.split(':')[0]) == want:
        return _x
    cands = (_RX.get('items') or {}).get(bare) or []
    if isinstance(cands, str):
        cands = [cands]
    for c in cands:
        if _mod_ns(c.split(':')[0]) == want:
            return c
    return _NSFIX(bare)


# Loot tables are not all places a player can go. bca:item_groups/* (923 references),
# */support_tables/* and cobblemon:sets/* are intermediate pools that real chest tables
# pull from - their percentages are chances WITHIN the pool, so printing "Ability Items
# - 90.9%" as a source is actively misleading. Classify by table shape and hide plumbing.
_POOL = re.compile(r'(:item_groups/|/support_tables/|:support_tables/|:sets/|/sets/)')

_RCT_TIER = {'common': 'common', 'uncommon': 'uncommon', 'rare': 'rare',
             'epic': 'epic', 'legendary': 'legendary'}


def _chest_label(parts):
    """Name a chest without stuttering.

    Tables nest: chests/trial_chambers/reward_ominous_rare, chests/village/village_weaponsmith.
    Use the parent as a prefix, drop it where the leaf repeats it, and only append the word
    "chest" when the name does not already end in it - otherwise you get "Turnback Cave
    Chest chest".
    """
    seg = parts[parts.index('chests') + 1:]
    leaf = seg[-1] if seg else 'chest'
    if len(seg) >= 2:
        parent = seg[0]
        if leaf.startswith(parent + '_'):
            leaf = leaf[len(parent) + 1:]
        label = '%s: %s' % (nice(parent), nice(leaf))
    else:
        label = nice(leaf)
    if not label.lower().rstrip().endswith('chest'):
        label += ' chest'
    return label


def _classify(tbl, pct, self_bare):
    """(rank, key, text-without-percent) for one table, or None to hide it.

    The key is what dedupes: RCT ships the same tier under several categories
    (generic/epic/pokeballs, generic/epic/archeology), which would otherwise print
    "Trainer drop - epic" twice at two different rates.
    """
    if _POOL.search(tbl):
        return None
    ns, _, rest = tbl.partition(':')
    parts = rest.split('/')

    if 'chests' in parts:
        return (1, 'chest:' + tbl, _chest_label(parts))
    if ns == 'rctmod' and len(parts) >= 2 and parts[0] == 'generic':
        tier = _RCT_TIER.get(parts[1], parts[1])
        return (2, 'rct:' + tier, 'Trainer drop &mdash; %s' % esc(tier))
    if 'archaeology' in parts:
        return (2, 'arch', 'Brushing suspicious blocks')
    if parts[0] == 'fossils':
        return (2, 'fossil', 'Fossil dig%s' % ('' if len(parts) < 2 else ' &mdash; ' + esc(parts[1])))
    if parts[0] == 'ruins':
        return (2, 'ruins', 'Ruins loot%s' % ('' if len(parts) < 2 else ' &mdash; ' + esc(parts[1])))
    if parts[0] == 'shipwreck_coves':
        return (1, 'cove', 'Shipwreck cove gilded chest')
    if 'entities' in parts:
        return (3, 'ent:' + parts[-1], 'Dropped by %s' % esc(nice(parts[-1])))
    if 'gameplay' in parts:
        return (3, 'gp:' + parts[-1], esc(nice(parts[-1])))
    if 'blocks' in parts:
        if parts[-1] == self_bare:
            return None                       # the block simply dropping itself
        return (4, 'blk:' + parts[-1], 'Mined from %s' % esc(nice(parts[-1])))
    return (5, 'x:' + parts[-1], esc(nice(parts[-1])))


# The Entrepreneur's stock is registered in code, not in a data file, so the index only
# ever found the two trades that happen to be declared as JSON. Read out of
# ModVillagersImpl.registerTrades: five profession levels, each a separate lambda group.
# HE MUST BE LEVELLED UP - the interesting stock only unlocks from Apprentice onward,
# which is why the PokeTreat Box looks unobtainable if you only ever met a Novice.
_ENTREPRENEUR = {
    'legendarymonuments:poketreat_box':
        (2, '32 emeralds + 32 relic coins', 5),
    'legendarymonuments:firescourge_seal':
        (3, '40 emeralds + 48 relic coins', 1),
    'legendarymonuments:icerend_seal':
        (3, '40 emeralds + 48 relic coins', 1),
    'legendarymonuments:grasswither_seal':
        (3, '40 emeralds + 48 relic coins', 1),
    'legendarymonuments:groundblight_seal':
        (3, '40 emeralds + 48 relic coins', 1),
    'legendarymonuments:lightstone_shard':
        (4, '32 emeralds + 16 relic coin pouches', 3),
    'legendarymonuments:darkstone_shard':
        (4, '32 emeralds + 16 relic coin pouches', 3),
    'legendarymonuments:celestica_flute':
        (5, '64 emeralds + 64 relic coins', 1),
    'legendarymonuments:silver_wing':
        (5, '60 emeralds + 64 relic coins', 1),
}
_LVLNAME = {1: 'Novice', 2: 'Apprentice', 3: 'Journeyman', 4: 'Expert', 5: 'Master'}


def _sources(nsid):
    """Human-readable provenance, best first, plumbing removed, one line per real source."""
    fixed = []
    _rr = (_RX.get('recipes') or {}).get(nsid)
    if _rr:
        fixed.append(RSOURCE.get(_rr[0].get('kind'), 'Crafted'))
    _ent = _ENTREPRENEUR.get(nsid)
    if _ent:
        fixed.append('Bought from the <b>Entrepreneur</b> at <b>level %d (%s)</b> '
                     '&mdash; %s, %d use%s'
                     % (_ent[0], _LVLNAME.get(_ent[0], '?'), _ent[1], _ent[2],
                        '' if _ent[2] == 1 else 's'))
    else:
        for t in ((_RX.get('trades') or {}).get(nsid) or []):
            fixed.append('Bought from the %s &mdash; %s'
                         % (esc(t.get('villager', '?')), esc(t.get('costs', '?'))))

    self_bare = nsid.split(':')[-1]
    best = {}
    for l in (((_RX.get('loot') or {}).get(nsid) or [])
              + ((_RX.get('mnl_loot') or {}).get(nsid) or [])):
        c = _classify(str(l.get('table', '')), l.get('pct'), self_bare)
        if not c:
            continue
        rank, key, text = c
        pct = l.get('pct')
        prev = best.get(key)
        if prev is None or (pct is not None and (prev[2] is None or pct > prev[2])):
            best[key] = (rank, text, pct)

    rows = sorted(best.values(), key=lambda x: (x[0], -(x[2] or 0)))
    out = fixed + ['%s%s' % (t, ' &mdash; %.1f%%' % p if p is not None else '')
                   for _, t, p in rows]

    # Nothing survived the filters. That is not the same as "no way to get it", and a
    # blank cell was the single biggest source of "this page is incomplete": 152 rows,
    # mostly CobbleFurnies, whose only loot table is their own block drop - correctly
    # hidden by _classify as saying nothing, but leaving no answer at all.
    #
    # A block you can only get by mining one is still obtainable IF something places it.
    # structblocks (from wikiindex) says which structures do. When nothing places it and
    # there is no recipe either, say so plainly rather than leaving it blank - the same
    # treatment the legacy CobbleCuisine dishes already get.
    if not out:
        _st = (_RX.get('structblocks') or {}).get(nsid) or []
        if _st:
            # The scan matches any id inside a structure template, which includes items
            # sitting in its chests - so "mine it" is wrong for something like a Cherish
            # Ball. "Found in" is true either way. Village template pools are named after
            # their variant folder (dark/default/fairy/...), which means nothing to a
            # reader, so collapse those to the village they belong to.
            _VAGUE = {'dark', 'default', 'fairy', 'fighting', 'ice', 'small', 'mid', 'large'}
            _names, _village = [], False
            for _x in _st[:3]:
                if str(_x).lower() in _VAGUE:
                    _village = True
                else:
                    _names.append(nice(_x))
            if _village and not _names:
                _names = ['a Cobblemon Additions village']
            elif _village:
                _names.append('Cobblemon Additions villages')
            out.append('Found in <b>%s</b>' % esc(', '.join(_names)))
        elif nsid.startswith('cobbreeding:') and nsid.endswith('_pokemon_egg'):
            # 326 of these - one per type pairing. They are not craftable and never
            # will be: Cobbreeding produces them when two compatible Pokemon breed in
            # a Pasture. Calling them "creative only" was simply wrong.
            out.append('Produced by <b>breeding</b> &mdash; put two compatible '
                       'Pok&eacute;mon in a <b>Pasture</b> and the egg appears there')
        elif not (_RX.get('recipes') or {}).get(nsid):
            # Deliberately NOT "creative only". That is a claim about intent this cannot
            # support - it over-fired on 902 rows including every booster pack. State
            # only what was actually checked.
            out.append('<span class="muted">Not found in any recipe, loot table or '
                       'structure &mdash; ask an admin if you need one</span>')
    return out[:5]


_it_recipes = _it_sources = _it_keyfor = 0
for _row in D2['items']:
    _nsid = _row_nsid(_row)
    _row['x'] = _nsid
    _src = _sources(_nsid)
    if _src:
        _row['s'] = _src
        _it_sources += 1
    _rr = ((_RX.get('recipes') or {}).get(_nsid) or [])
    if _rr:
        _r = _rr[0]
        _cells = [-1] * 9
        if _r.get('grid'):
            _k = 0
            for _gr in _r['grid']:
                for _c in _gr:
                    if _k < 9:
                        _cb = _cell_item(_c)[0]      # tags resolve to a drawable member
                        _cells[_k] = _sid(_cb) if _cb else -1
                    _k += 1
        _ings = []
        for _g in (_r.get('ings') or []):
            _gb = _cell_item(_g['i'])[0] or _g['i'].split(':')[-1]
            _ings.append([_sid(_gb), _g.get('n', 1)])
        _kind = _KINDS.index(_r['kind']) if _r['kind'] in _KINDS else 3
        _row['g'] = [_kind, _r.get('count', 1), _cells, _ings]
        _it_recipes += 1
    _mons = sorted((_RX.get('keyfor') or {}).get(_nsid) or [])
    if _mons:
        _row['k'] = _mons
        _it_keyfor += 1
    # CobbleCuisine ships 13 dishes its lang file prefixes "[LEGACY]". Six are still
    # craftable, so they stay - but as a flag rather than bracket-text in the name, and
    # the seven with no recipe and no source are called unobtainable rather than listed
    # as if you could go and get one.
    if str(_row.get('n', '')).startswith('[LEGACY]'):
        _row['n'] = _row['n'].replace('[LEGACY]', '').strip()
        _row['lg'] = 1
        if not _row.get('s') and not _row.get('g'):
            _row['s'] = ['Not obtainable &mdash; an older entry the mod still ships']
    _row.pop('r', None)          # the recipe TYPE string - replaced by the real thing
    if not _row.get('t'):
        _row.pop('t', None)


# An item whose only purpose is to be a cosmetic looked like a dead end on the items page:
# Old Gateau showed a Cooking Pot recipe and nothing else, so the owner found one in a
# chest, could not eat it, and had no way to learn what it was for. The Pokedex knew - the
# per-species cosmetic block has said so since it was added - but nothing pointed the other
# way, from the item back to the Pokemon. _COS_DEF is species -> {item: [aspects]}; invert
# it once and every one of these items can explain itself.
_COS_FOR = {}
for _sp2, _items2 in _COS_DEF.items():
    for _ci2 in _items2:
        _COS_FOR.setdefault(str(_ci2), [])
        if _sp2 not in _COS_FOR[str(_ci2)]:
            _COS_FOR[str(_ci2)].append(_sp2)

_cos_noted = 0
for _row in D2['items']:
    _nsid2 = _row.get('x') or _row_nsid(_row)
    _who = _COS_FOR.get(_nsid2) or _COS_FOR.get(str(_nsid2).split(':')[-1])
    if not _who:
        continue
    _names = [_SPNAME.get(re.sub(r'[^a-z0-9]', '', s)) or nice(s) for s in sorted(_who)]
    if len(_names) > 6:
        _txt = ('A <b>cosmetic</b> &mdash; %d Pok&eacute;mon accept it, including %s'
                % (len(_names), ', '.join(_names[:4])))
    else:
        _txt = 'A <b>cosmetic</b> for %s' % ', '.join('<b>%s</b>' % n for n in _names)
    _txt += ('. <b>Sneak</b> and right-click your own sent-out Pok&eacute;mon while '
             'holding it, then pick it from the interaction wheel. Plain right-click and '
             'simply holding the item both do nothing. It is consumed, but the look can '
             'be swapped later.')
    _row.setdefault('s', [])
    if not any('cosmetic' in str(x).lower() for x in _row['s']):
        _row['s'].append(_txt)
        _cos_noted += 1

print('items: %d cosmetic items now say which Pokemon they are for' % _cos_noted)


print('items: %d rows | %d with a real recipe | %d with a source | %d that summon a Pokemon'
      % (len(D2['items']), _it_recipes, _it_sources, _it_keyfor))

items_payload = json.dumps({'items': D2['items'], 'S': _SBL},
                           separators=(',', ':')).replace('</', '<\\/')

tpl = open('/tmp/wiki_tpl3.html', encoding='utf-8').read()
_XREF = '<div class="tut" style="border-left-color:var(--acc2);margin:0 0 14px"><div class="tut-h">This page is now a browsable index</div><div class="ttip">Every route below also lives on the Pok&eacute;mon\'s own <b>Pok&eacute;dex</b> entry &mdash; the summon item, its recipe, where each ingredient comes from and what it costs, all in one place. Searching the Pok&eacute;dex by name is usually faster than reading down this page.</div></div>'
out = (tpl.replace('__GUIDES__', _XREF + gh)
          .replace('__FURNIES__', fh)
          .replace('__CHIPPED__', chh)
          .replace('__STRUCT__', sh)
          .replace('__BAIT__', bh)
          .replace('__CUISINE__', ch2)
          .replace('__MOUNTS__', mh)
          .replace('__TRAINERS__', th + '<h3>Everything else</h3>' + (D3.get('trainers') or ''))
          .replace('__MYTH__', _XREF + (D3.get('myth_html') or ''))
          .replace('__URNS__', _XREF + (D3.get('urns_html') or ''))
          .replace('__CRAFT__', D3.get('craft_html') or '')
          .replace('__RESEARCH__', D3.get('research_html') or '')
          .replace('__PASTURE__', D3.get('pasture_html') or '')
          .replace('__MULCH__', D3.get('mulch_html') or '')
          .replace('__RIDES__', D3.get('rides_html') or '')
          .replace('__NOMODEL__', D3.get('nomodel_html') or '')
          .replace('__PASTURESPACE__', D3.get('pasture_space_html') or '')
          .replace('__LM__', P['lm'])
          .replace('__MNL__', P['mnl'])
          .replace('__MODS__', host + mods_html)
          .replace('__TYPECHART__', tc)
          .replace('__NOTES__', (D3.get('system') or '') + notes_html)
          .replace('__DEXPAYLOAD__', json.dumps(PAYOBJ, separators=(',', ':')))
          .replace('__ITEMPAYLOAD__', items_payload)
          .replace('__CARDS__', cards_html)
          .replace('__FISHINTRO__', fish_intro)
          .replace('__SERVERADDR__', os.environ.get('WIKI_SERVER_ADDR', 'your server'))
          .replace('__DEXSPR__', json.dumps(_SPR, separators=(',', ':')) if _SPR else 'null')
          .replace('__MEGAMINING__', megamining_html)
          .replace('__TEXPAYLOAD__', tex_payload))
# Belt-and-braces: known-bad source ids must not reach the page by ANY route. The
# load-time pass fixes P/D2/D3 and the parsed payload, but one pre-baked blob still
# arrived with "prism_bottle" intact and instrumenting the splice did not explain why,
# so this final substitution guarantees it. Cheap, and it also catches future blobs.
for _bad, _good in _BARE_TYPO.items():
    if _bad in out:
        out = re.sub(re.escape(_bad), _good, out)
        print('post-render: scrubbed remaining "%s"' % _bad)

# the 20s cooldown / voucher cap only applies when enable_vouchers=true, and this
# server has it false. Catch the copies baked into notes/dossier.
for _old in ('There is a <b>20 second cooldown</b> between attempts.',
             'There is a <b>20 second cooldown</b> between attempts',
             'There is a 20 second cooldown between attempts.',
             'There is a 20 second cooldown between attempts'):
    out = out.replace(_old, 'There is <b>no cooldown</b> on this server')
out = re.sub(r'[Tt]here is a (<b>)?20 second cooldown(</b>)?[^.<]*',
             'there is <b>no cooldown</b> on this server', out)

open('/tmp/mc-wiki.html', 'w', encoding='utf-8').write(out)
print('wrote %.2f MB' % (os.path.getsize('/tmp/mc-wiki.html') / 1048576))
print('guides %d  furnies %d  textures %d  chipped fams %d' % (len(guides), len(D3['furnies']), len(D3['tex']), len(fams)))
