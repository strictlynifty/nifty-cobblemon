# -*- coding: utf-8 -*-
"""Build the recipe + acquisition index the wiki has never had.

Guide chains name their ingredients but never resolve them ("sub" is always []),
which is why "how do I get a Celestica Flute" lives on a different page from
"Summon Arceus". This produces, for every item:

    recipes[item]  = [{kind, ings:[...], count}]        how to craft it
    loot[item]     = [{table, chance, rolls}]           where it drops
    trades[item]   = [{villager, costs, maxUses}]       who sells it   (hand-verified)
    keyfor[item]   = [species]                          what it summons

Writes /tmp/wiki_recipes.json. Run on the server, where the jars live.
"""
import zipfile, glob, json, collections, os, sys

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")

MODS = COBBLEMON_DIR + "/mods"
VANILLA = COBBLEMON_DIR + "/versions/1.21.1/server-1.21.1.jar"
MNL_LOOT = COBBLEMON_DIR + "/config/mythsandlegends/loot_tables_config.json"

recipes = collections.defaultdict(list)
loot = collections.defaultdict(list)
keyfor = collections.defaultdict(list)


def norm_item(x):
    """Recipe ingredients come as str, {item:..}, {tag:..} or a list of those."""
    out = []
    if x is None:
        return out
    if isinstance(x, str):
        return [x]
    if isinstance(x, list):
        for e in x:
            out += norm_item(e)
        return out
    if isinstance(x, dict):
        if "item" in x:
            return [x["item"]]
        if "tag" in x:
            return ["#" + str(x["tag"])]
        if "id" in x:
            return [x["id"]]
    return out


def result_of(d):
    r = d.get("result")
    if isinstance(r, str):
        return r, 1
    if isinstance(r, dict):
        return r.get("id") or r.get("item"), r.get("count", 1)
    return None, 1


def parse_recipe(d):
    """-> (kind, ingredient list, grid) or None for types we don't surface.

    grid is a 3x3 of item ids (None for empty) for shaped recipes, so the wiki can draw
    the actual layout instead of listing ingredients - the layout IS the information for
    a shaped recipe.
    """
    t = str(d.get("type", ""))
    t = t[10:] if t.startswith("minecraft:") else t
    if t == "crafting_shaped":
        key = d.get("key") or {}
        pattern = d.get("pattern") or []
        counts = collections.Counter("".join(pattern))
        ings = []
        for sym, n in counts.items():
            if sym == " ":
                continue
            for it in norm_item(key.get(sym)):
                ings.append((it, n))
        grid = []
        for r in range(3):
            row = []
            for c in range(3):
                sym = pattern[r][c] if r < len(pattern) and c < len(pattern[r]) else " "
                got = norm_item(key.get(sym)) if sym != " " else []
                row.append(got[0] if got else None)
            grid.append(row)
        return "shaped", ings, grid
    if t == "crafting_shapeless":
        c = collections.Counter()
        for e in d.get("ingredients") or []:
            for it in norm_item(e):
                c[it] += 1
        return "shapeless", list(c.items()), None
    if t in ("smelting", "blasting", "smoking", "campfire_cooking"):
        ings = [(it, 1) for it in norm_item(d.get("ingredient"))]
        return t, ings, None
    # Cobblemon cooks in a CAMPFIRE POT and brews in its own brewing stand, with three
    # recipe types of its own. They were all skipped, which hid 92 items from the recipe
    # column - every aprijuice, sweet, mochi, malasada and candied berry, every medicine
    # (Antidote, Awakening, Burn Heal) and every vitamin (Calcium, Carbos), plus Old
    # Gateau. The page showed these as having no recipe at all.
    if t == "cobblemon:cooking_pot":
        # same shape as crafting_shaped - key + 3x3 pattern - so draw the real layout
        key = d.get("key") or {}
        pattern = d.get("pattern") or []
        counts = collections.Counter("".join(pattern))
        ings = []
        for sym, n in counts.items():
            if sym == " ":
                continue
            for it in norm_item(key.get(sym)):
                ings.append((it, n))
        grid = []
        for r in range(3):
            row = []
            for c in range(3):
                sym = pattern[r][c] if r < len(pattern) and c < len(pattern[r]) else " "
                got = norm_item(key.get(sym)) if sym != " " else []
                row.append(got[0] if got else None)
            grid.append(row)
        return "pot", ings, grid
    if t == "cobblemon:cooking_pot_shapeless":
        c = collections.Counter()
        for e in d.get("ingredients") or []:
            for it in norm_item(e):
                c[it] += 1
        return "potless", list(c.items()), None
    if t == "cobblemon:brewing_stand":
        # `input` is the berry, `bottle` is what it goes into
        c = collections.Counter()
        for f in ("bottle", "input"):
            for it in norm_item(d.get(f)):
                c[it] += 1
        return "brewing", list(c.items()), None
    if t == "stonecutting":
        return "stonecutting", [(it, 1) for it in norm_item(d.get("ingredient"))], None
    if t == "cobblefurnies:furni_crafting" or d.get("materials"):
        # CobbleFurnies uses its own recipe type with "materials" instead of
        # "ingredients" - 348 of its 367 recipes, i.e. nearly all the furniture,
        # were silently skipped and the wiki showed an empty ingredient list.
        c = collections.Counter()
        for e in d.get("materials") or []:
            for it in norm_item(e):
                c[it] += (e.get("count", 1) if isinstance(e, dict) else 1)
        return "furni", list(c.items()), None
    if t.startswith("smithing"):
        ings = []
        for f in ("base", "addition", "template"):
            ings += [(it, 1) for it in norm_item(d.get(f))]
        return "smithing", ings, None
    return None


def walk_loot(node, out):
    """Collect (item, weight) from a loot pool entry tree."""
    if isinstance(node, dict):
        t = str(node.get("type", "")).replace("minecraft:", "")
        if t == "item" and node.get("name"):
            out.append((node["name"], node.get("weight", 1)))
        for k in ("children", "entries"):
            for c in node.get(k) or []:
                walk_loot(c, out)
    elif isinstance(node, list):
        for c in node:
            walk_loot(c, out)


jars = sorted(glob.glob(os.path.join(MODS, "*.jar")))
if os.path.exists(VANILLA):
    jars.append(VANILLA)

nrec = nloot = 0
for jp in jars:
    try:
        z = zipfile.ZipFile(jp)
    except Exception:
        continue
    for n in z.namelist():
        if not n.endswith(".json"):
            continue
        if "/recipe" in n:
            try:
                d = json.loads(z.read(n).decode("utf-8-sig"))
            except Exception:
                continue
            res, cnt = result_of(d)
            if not res:
                continue
            p = parse_recipe(d)
            if not p:
                continue
            kind, ings, grid = p
            if not ings:
                continue
            row = {"kind": kind, "count": cnt,
                   "ings": [{"i": i, "n": c} for i, c in ings]}
            if grid:
                row["grid"] = grid
            recipes[res].append(row)
            nrec += 1
        elif "/loot_table" in n:
            try:
                d = json.loads(z.read(n).decode("utf-8-sig"))
            except Exception:
                continue
            tbl = n.split("/loot_table/")[-1][:-5]
            ns = n.split("/")[1]
            for pool in d.get("pools") or []:
                got = []
                walk_loot(pool.get("entries") or [], got)
                tot = sum(w for _, w in got) or 1
                rolls = pool.get("rolls")
                if isinstance(rolls, dict):
                    rolls = rolls.get("max") or rolls.get("min") or 1
                if not isinstance(rolls, (int, float)):
                    rolls = 1
                for it, w in got:
                    p1 = w / float(tot)
                    loot[it].append({"table": "%s:%s" % (ns, tbl),
                                     "pct": round((1 - (1 - p1) ** rolls) * 100, 2)})
                    nloot += 1

# --- key items -> what they summon -------------------------------------------------
for jp in jars:
    try:
        z = zipfile.ZipFile(jp)
    except Exception:
        continue
    for n in z.namelist():
        if "/spawn_pool_world/" not in n or not n.endswith(".json"):
            continue
        try:
            d = json.loads(z.read(n).decode("utf-8-sig"))
        except Exception:
            continue
        if not d.get("enabled", True):
            continue
        for s in d.get("spawns", []):
            c = s.get("condition") or {}
            ki = c.get("key_item") or c.get("keyItem")
            if ki and s.get("pokemon"):
                mon = str(s["pokemon"])
                if mon not in keyfor[str(ki)]:
                    keyfor[str(ki)].append(mon)

# --- the owner's M&L loot config overrides the jar odds ----------------------------
mnl = collections.defaultdict(list)
try:
    cfg = json.load(open(MNL_LOOT))
    for tbl, groups in cfg.get("lootTables", {}).items():
        for g in groups:
            if not g.get("enabled", True):
                continue
            tot = sum(e["weight"] for e in g["entries"]) or 1
            for e in g["entries"]:
                pct = g.get("chance", 1) * g.get("rolls", 1) * e["weight"] / tot * 100
                mnl[e["itemId"]].append({"table": tbl, "pct": round(pct, 2)})
except Exception as ex:
    print("  (M&L loot config unreadable: %s)" % ex)

# hand-verified, code-only sources that no datapack scan can reach
TRADES = {
    "legendarymonuments:celestica_flute": [
        {"villager": "Entrepreneur", "costs": "64 diamonds + 64 relic coins", "maxUses": 1}],
    "legendarymonuments:silver_wing": [
        {"villager": "Entrepreneur", "costs": "64 diamonds + 64 relic coins", "maxUses": 1}],
}
SPAWNER = {
    "legendarymonuments:griseous_key": [
        {"source": "Turnback Cave trial spawners", "pct": 50,
         "note": "100% from the three small-room spawners; ~58 spawners per cave; they reset"}],
}

# keep the loot lists short and useful - best odds first
for d in (loot, mnl):
    for k in list(d):
        d[k] = sorted(d[k], key=lambda r: -r["pct"])[:6]

# --- item existence, for namespace resolution --------------------------------------
# Guide items are bare paths ("time_globe"). Resolving them by "does it have a recipe
# or loot" was wrong: shrines, pedestals and legendary drops have neither, so 79 of 108
# guide items silently failed to resolve. Resolve by EXISTENCE instead.
import re as _re
bare = {}
allids = set()
for jp in jars:
    try:
        z = zipfile.ZipFile(jp)
    except Exception:
        continue
    for n in z.namelist():
        m = _re.match(r"assets/([a-z0-9_]+)/models/item/([a-z0-9_/]+)\.json$", n)
        if not m:
            continue
        ns, path = m.group(1), m.group(2).split("/")[-1]
        full = "%s:%s" % (ns, path)
        allids.add(full)
        # ALL namespaces that define this bare name, not one. 35 item names in this pack
        # are defined by two mods, and picking one arbitrarily resolved griseous_orb to
        # the copy with no recipe. The consumer picks by which candidate has a source.
        bare.setdefault(path, [])
        if full not in bare[path]:
            bare[path].append(full)

# Recipe ingredients are often TAGS, not items: 134 distinct ones, including
# #cobblemon:pokedex_screen, which reads on the page as if "Pokedex Screen" were a
# craftable item. It is not - it is a tag of five things you may substitute. Index the
# members so the page can draw a real item and say what else is allowed.
itemtags = {}
def _tagsources():
    """Every zip that might hold item tags, including nested ones.

    Fabric API ships as a bundle: its modules are JARs inside META-INF/jars/, and the
    conventional #c: tags live in there. Without descending, #c:ingots/gold resolves to
    nothing and every recipe using it falls back to printing the raw tag name.
    """
    import io as _io
    for _p in jars:
        try:
            _z = zipfile.ZipFile(_p)
        except Exception:
            continue
        yield _z
        for _inner in _z.namelist():
            if _inner.startswith("META-INF/jars/") and _inner.endswith(".jar"):
                try:
                    yield zipfile.ZipFile(_io.BytesIO(_z.read(_inner)))
                except Exception:
                    continue


for _z in _tagsources():
    for _n in _z.namelist():
        if not _n.endswith(".json"):
            continue
        _parts = _n.split("/")
        # data/<ns>/tags/item[s]/<path>.json
        if len(_parts) < 5 or _parts[0] != "data" or _parts[2] != "tags":
            continue
        if _parts[3] not in ("item", "items"):
            continue
        _tid = "#%s:%s" % (_parts[1], "/".join(_parts[4:])[:-5])
        try:
            _d = json.loads(_z.read(_n).decode("utf-8-sig"))
        except Exception:
            continue
        _vals = []
        for _v in (_d.get("values") or []):
            _id = _v if isinstance(_v, str) else _v.get("id")
            if _id:
                _vals.append(str(_id))
        if not _vals:
            continue
        # tags/*.json are additive across mods - merge rather than overwrite
        _cur = itemtags.setdefault(_tid, [])
        for _v in _vals:
            if _v not in _cur:
                _cur.append(_v)

# A spawn needs clear room equal to the Pokemon's hitbox: PokemonSpawnDetail.autoLabel
# sets height/width to ceil(hitbox * baseScale). That is why a big legendary will not
# appear in dense jungle until you cut it back. Two mods can define the same species at
# the same path (Mega Showdown overrides Cobblemon for Rayquaza), and which wins depends
# on load order - so keep the LARGER, because clearing more space is never wrong.
import math as _math
space = {}
for _jp in jars:
    try:
        _z = zipfile.ZipFile(_jp)
    except Exception:
        continue
    for _n in _z.namelist():
        if "/species/" not in _n or not _n.endswith(".json"):
            continue
        try:
            _d = json.loads(_z.read(_n).decode("utf-8-sig"))
        except Exception:
            continue
        _hb = _d.get("hitbox")
        if not isinstance(_hb, dict):
            continue
        _sc = _d.get("baseScale") or 1.0
        _w = int(_math.ceil(float(_hb.get("width", 1)) * float(_sc)))
        _h = int(_math.ceil(float(_hb.get("height", 1)) * float(_sc)))
        _nm = str(_d.get("name") or _n.split("/")[-1][:-5]).lower()
        _nm = "".join(ch for ch in _nm if ch.isalnum())
        _prev = space.get(_nm)
        if not _prev or (_w * _h) > (_prev[0] * _prev[1]):
            space[_nm] = [_w, _h]

# Form changes are the least discoverable thing in the pack: an item sitting in a chest
# can change what a Pokemon looks like and how it battles, and nothing in game tells you.
# Three separate sources, all indexed by species.
def _norm_sp(x):
    return "".join(ch for ch in str(x).lower() if ch.isalnum())


megas, battleforms, interactions = {}, {}, {}
for _jp in jars:
    try:
        _z = zipfile.ZipFile(_jp)
    except Exception:
        continue
    for _n in _z.namelist():
        if not _n.endswith(".json"):
            continue
        try:
            _d = json.loads(_z.read(_n).decode("utf-8-sig"))
        except Exception:
            continue
        # Mega Showdown: one file per stone, naming the species it works on
        if "/mega_showdown/mega/" in _n and isinstance(_d, dict) and _d.get("showdown_id"):
            for _sp in (_d.get("pokemons") or []):
                megas[_norm_sp(_sp)] = _n.split("/")[-1][:-5]
        # Mega Showdown: in-battle / weather / stance forms
        elif "/battle_form/" in _n and isinstance(_d, dict) and _d.get("pokemons"):
            for _sp in _d["pokemons"]:
                battleforms.setdefault(_norm_sp(_sp), []).append(_n.split("/")[-1][:-5])
        # Cobblemon: right-click-with-an-item interactions (shears trim a Furfrou, etc)
        elif "/pokemon_interactions/" in _n and isinstance(_d, dict):
            _sp = None
            for _r in (_d.get("requirements") or []):
                if _r.get("variant") == "properties" and _r.get("target"):
                    _sp = str(_r["target"]).split()[0]
            if not _sp:
                continue
            _rows = []
            for _it in (_d.get("interactions") or []):
                _need = None
                for _r in (_it.get("requirements") or []):
                    if _r.get("variant") == "owner_held_item":
                        _need = _r.get("itemCondition")
                _eff = []
                for _e in (_it.get("effects") or []):
                    _v = _e.get("variant")
                    if _v == "drop_item":
                        _eff.append("drops " + str(_e.get("item", "")).split(":")[-1])
                    elif _v == "give_item":
                        _eff.append("gives " + str(_e.get("item", "")).split(":")[-1])
                    elif _v == "script":
                        _eff.append("form:" + str(_e.get("script", "")))
                if _need and _eff:
                    _rows.append({"need": _need, "eff": _eff})
            if _rows:
                interactions[_norm_sp(_sp)] = _rows

# Which structure belongs to which Pokemon. Nothing in the pack states this: the Arc Phone
# will track a "Throne Room of Knightly Heroes" without ever saying that is where Zacian
# and Zamazenta live. Derive it from the structures themselves - the pedestal, shrine,
# cocoon and lock blocks placed inside each one name their species.
import gzip as _gzip
import re as _re2

_GZMAGIC = bytes([0x1f, 0x8b])
_SPECIAL = _re2.compile(
    rb"legendarymonuments:([a-z_]+?)_(pedestal|shrine|cocoon|lock|jukebox|footprints)")
_SHRINE_SP = {"firescourge": ["chiyu"], "grasswither": ["wochien"],
              "icerend": ["chienpao"], "groundblight": ["tinglu"]}
_ALIAS = {"ho_oh": ["hooh"], "latias": ["latias", "latios"],
          "steed": ["glastrier", "spectrier"], "elekidrago": ["regidrago", "regieleki"]}
# Which structures PLACE which blocks. Rides the same raw-bytes pass below rather
# than parsing 1300 NBT files: a block that only ever "drops itself" reads as
# unobtainable on the items page, when usually the real answer is "find one in a
# structure and mine it". The ones that match NOTHING here and have no recipe are
# genuinely creative-only, which is also worth saying out loud.
_BLOCKID = _re2.compile(
    rb"(cobblefurnies|cobblemon|legendarymonuments|mega_showdown|bca|chipped|cobblecuisine|cobbledollars):([a-z0-9_]{3,48})")
structblocks = collections.defaultdict(set)

_SKIP = {"pedestal", "sanctuary", "temple", "distortion", "regi", "correct_regi",
         "false_regi", "shadow"}

structmons = {}
for _jp in jars:
    try:
        _z = zipfile.ZipFile(_jp)
    except Exception:
        continue
    for _n in _z.namelist():
        if not _n.endswith(".nbt") or "/structure/" not in _n:
            continue
        _parts = _n.split("/")
        _st = _parts[_parts.index("structure") + 1] if len(_parts) > _parts.index("structure") + 1 else ""
        if _st.endswith(".nbt"):
            _st = _st[:-4]
        if not _st:
            continue
        try:
            _raw = _z.read(_n)
        except Exception:
            continue
        if _raw[:2] == _GZMAGIC:
            try:
                _raw = _gzip.decompress(_raw)
            except Exception:
                continue
        for _bm in _BLOCKID.finditer(_raw):
            structblocks[_bm.group(1).decode() + ":" + _bm.group(2).decode()].add(_st)
        for _m in _SPECIAL.finditer(_raw):
            _base = _m.group(1).decode()
            if _base in _SKIP or _base.endswith("_dummy"):
                continue
            for _x in (_SHRINE_SP.get(_base) or _ALIAS.get(_base)
                       or [_base.replace("_", "")]):
                structmons.setdefault(_st, [])
                if _x not in structmons[_st]:
                    structmons[_st].append(_x)
    _z.close()
# --- datapack loot + recipes -------------------------------------------------------
# wikiindex only ever read the MOD jars, so anything a datapack adds was invisible to the
# items page. That bit immediately: the booster packs added to Cobblemon-Additions town
# chests (nifty-booster-loot) showed no source at all, and the fallback then labelled the
# single most important reward item in the pack as unobtainable. Datapacks override mod
# data on this server, so they must be read the same way.
_ndp = 0
for _dp in glob.glob(COBBLEMON_DIR + "/world/datapacks/*/data/*/loot_table/**/*.json",
                     recursive=True):
    try:
        _d = json.load(open(_dp, encoding="utf-8-sig"))
    except Exception:
        continue
    _ns = _dp.split("/data/")[1].split("/")[0]
    _tbl = _dp.split("/loot_table/")[-1][:-5]
    for _pool in _d.get("pools") or []:
        _got = []
        walk_loot(_pool.get("entries") or [], _got)
        _tot = sum(w for _, w in _got) or 1
        _rolls = _pool.get("rolls")
        if isinstance(_rolls, dict):
            _rolls = _rolls.get("max") or _rolls.get("min") or 1
        if not isinstance(_rolls, (int, float)):
            _rolls = 1
        for _it, _w in _got:
            if _it == "minecraft:air":
                continue
            _p1 = _w / float(_tot)
            loot[_it].append({"table": "%s:%s" % (_ns, _tbl),
                              "pct": round((1 - (1 - _p1) ** _rolls) * 100, 2)})
            _ndp += 1
print("datapack : %d loot entries read from world/datapacks" % _ndp)

print("structs  : %d structures mapped to a species" % len(structmons))
print("structs  : %d block ids seen placed by structures" % len(structblocks))

# Fossil revival. 15 species come out of the fossil machine and nothing else - four of
# them (the Galar four) have no spawn pool at all, so without this the Pokedex has
# literally nothing to say about them.
fossils = {}
for _jp in jars:
    try:
        _z = zipfile.ZipFile(_jp)
    except Exception:
        continue
    for _n in _z.namelist():
        if "/fossils/" not in _n or not _n.endswith(".json") or not _n.startswith("data/"):
            continue
        try:
            _d = json.loads(_z.read(_n).decode("utf-8-sig"))
        except Exception:
            continue
        _f = _d.get("fossils") or []
        _r = _d.get("result") or _n.split("/")[-1][:-5]
        if _f:
            fossils["".join(ch for ch in str(_r).lower() if ch.isalnum())] = _f
    _z.close()
print("fossils  : %d species revivable" % len(fossils))
# What actually fills a Restoration Tank. The machine wants 128 units of "content" and
# every food/plant item is worth a different amount, so "put some organic material in"
# is useless advice - a player needs to know it is 8 hearty grain bales or 128 seeds.
natmats = {}
for _jp in jars:
    try:
        _z = zipfile.ZipFile(_jp)
    except Exception:
        continue
    for _n in _z.namelist():
        if "/natural_materials/" not in _n or not _n.endswith(".json"):
            continue
        try:
            _d = json.loads(_z.read(_n).decode("utf-8-sig"))
        except Exception:
            continue
        for _e in (_d if isinstance(_d, list) else []):
            _it = _e.get("item") or _e.get("tag")
            _c = _e.get("content")
            if _it and isinstance(_c, int) and _c > 0:
                natmats[str(_it)] = _c
    _z.close()
print("natmats  : %d organic materials with a fill value" % len(natmats))
# Bait effect TYPES, counted. The bait table lists what each berry does; this is the other
# direction - the vocabulary, so the page can explain what "rarity bucket" even means.
baiteffects = {}
for _jp in jars:
    try:
        _z = zipfile.ZipFile(_jp)
    except Exception:
        continue
    for _n in _z.namelist():
        if "/spawn_bait_effects/" not in _n or not _n.endswith(".json"):
            continue
        try:
            _d = json.loads(_z.read(_n).decode("utf-8-sig"))
        except Exception:
            continue
        for _e in (_d.get("effects") or []):
            _t = str(_e.get("type") or "")
            if _t:
                baiteffects[_t] = baiteffects.get(_t, 0) + 1
    _z.close()
print("bait     : %d distinct bait effect types" % len(baiteffects))

# Species that addons invent outright - the 28 Baby Legends pre-evolutions are the big
# case. They are not in the base 1025, so the Pokedex would never show them at all
# unless we collect them here and splice them in.
customspecies = {}
for _jp in jars:
    try:
        _z = zipfile.ZipFile(_jp)
    except Exception:
        continue
    for _n in _z.namelist():
        if "/species/" not in _n or not _n.endswith(".json"):
            continue
        try:
            _d = json.loads(_z.read(_n).decode("utf-8-sig"))
        except Exception:
            continue
        _nm = _d.get("name")
        if not _nm or not _d.get("primaryType"):
            continue
        _key = "".join(ch for ch in str(_nm).lower() if ch.isalnum())
        _evo = []
        for _e in (_d.get("evolutions") or []):
            _res = str(_e.get("result") or "").split()[0]
            _reqs = []
            for _r in (_e.get("requirements") or []):
                _v = _r.get("variant")
                if _v == "level":
                    _reqs.append("level %s" % _r.get("minLevel"))
                elif _v == "friendship":
                    _reqs.append("friendship %s" % _r.get("amount"))
                elif _v == "held_item":
                    _reqs.append("holding %s" % str(_r.get("itemCondition", "")).split(":")[-1])
                elif _v == "time_range":
                    _reqs.append("at %s" % _r.get("range"))
                elif _v == "weather":
                    _reqs.append("thunderstorm" if _r.get("isThundering") else "rain")
                elif _v == "biome":
                    _reqs.append("in %s" % str(_r.get("biomeCondition", "")).lstrip("#").split(":")[-1])
                elif _v == "properties":
                    _reqs.append(str(_r.get("target", "")))
            if _res:
                _evo.append({"to": _res, "req": _reqs})
        customspecies[_key] = {
            "name": _nm, "t1": _d.get("primaryType"), "t2": _d.get("secondaryType"),
            "evo": _evo, "src": os.path.basename(_jp)}
    # spawn rows for those same species, so the entry can say where to look
    for _n in _z.namelist():
        if "spawn_pool_world" not in _n or not _n.endswith(".json"):
            continue
        try:
            _d = json.loads(_z.read(_n).decode("utf-8-sig"))
        except Exception:
            continue
        for _s in (_d.get("spawns") or []):
            _pk = str(_s.get("pokemon", "")).split()
            if not _pk:
                continue
            _key = "".join(ch for ch in _pk[0].lower() if ch.isalnum())
            if _key not in customspecies:
                continue
            _c = (_s.get("condition") or {})
            customspecies[_key].setdefault("spawns", []).append({
                "b": _s.get("bucket"), "l": _s.get("level"),
                "bi": _c.get("biomes") or [], "w": _s.get("weight")})
    _z.close()
print("custom   : %d species carry a name + typing" % len(customspecies))

out = {"items": bare,
       "customspecies": customspecies,
       "fossils": fossils,
       "natmats": natmats,
       "baiteffects": baiteffects,
       "structmons": structmons,
       "megas": megas,
       "battleforms": battleforms,
       "interactions": interactions,
       "space": space,
       "itemtags": itemtags,
       "recipes": {k: v for k, v in recipes.items()},
       "loot": {k: v for k, v in loot.items()},
       "structblocks": {k: sorted(v)[:3] for k, v in structblocks.items()},
       "mnl_loot": {k: v for k, v in mnl.items()},
       "trades": TRADES,
       "spawner": SPAWNER,
       "keyfor": {k: v for k, v in keyfor.items()}}
json.dump(out, open("/tmp/wiki_recipes.json", "w"), separators=(",", ":"))
print("itemtags : %d tags indexed" % len(itemtags))
print("space    : %d species sized from their hitbox" % len(space))
print("forms    : %d megas, %d battle-form species, %d interaction species"
      % (len(megas), len(battleforms), len(interactions)))
print("recipes  : %d results, %d recipe rows" % (len(recipes), nrec))
print("loot     : %d items" % len(loot))
print("mnl_loot : %d items (owner-configured odds)" % len(mnl))
print("keyfor   : %d key items -> %d species links"
      % (len(keyfor), sum(len(v) for v in keyfor.values())))
print("items    : %d distinct ids, %d bare-name shortcuts" % (len(allids), len(bare)))
print("wrote /tmp/wiki_recipes.json (%.2f MB)"
      % (os.path.getsize("/tmp/wiki_recipes.json") / 1048576.0))

# sanity: the two chains we know by hand
for probe in ("mega_showdown:griseous_orb", "legendarymonuments:azure_flute",
              "legendarymonuments:celestica_flute"):
    r = recipes.get(probe)
    print()
    print("  %s" % probe)
    print("     recipe : %s" % (json.dumps(r[0]) if r else "none"))
    print("     loot   : %s" % (json.dumps(loot.get(probe, []))[:150]))
    print("     trade  : %s" % (json.dumps(TRADES.get(probe, []))))
