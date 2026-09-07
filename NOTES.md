# Notes

Findings from running one small Cobblemon server for a few months: mod conflicts, datapack
behaviour, Bedrock model quirks, and a fair number of things that looked like one problem and
turned out to be another. Written as we hit them, so they are specific rather than general -
that is the point. Most were expensive to work out and cheap to read.

Player names, UUIDs, coordinates, hostnames and paths have been replaced; the findings are
unchanged. Sections are numbered in the order they were discovered, so later ones sometimes
correct earlier ones - where that happens it is said outright rather than edited away.

Public domain (CC0), like everything else here.

---

## 1. Read the EFFECTIVE data, never the base species file

`data/cobblemon/species/**.json` is only the starting point. `species_additions`
from **mods and datapacks** overwrite fields on top of it.

**Burned by this twice:**

- Groudon's base hitbox is a placeholder `1x1`. Three separate sources override it
  to `5.5 x 6` (mega_showdown, cobblemon-journey-mounts, our twoseat datapack).
  Reading the base file gave a pasture-clearance answer that was wrong by 6 blocks.
- Riding data likewise: several species look unrideable in the base file but are
  fixed by journey-mounts additions, and vice versa.

**Rule:** merge base + every `species_additions` targeting it before concluding
anything. Kyogre/Eternatus share the same `1x1` placeholder trap.

---

## 2. The species registry is NOT reloadable. `/reload` does nothing.

`CobblemonDataProvider.registerDefaults()` registers `PokemonSpecies` and
`SpeciesAdditions` with the reloadable flag **false** (`iconst_0`). Cobblemon logs
it outright:

> "Cobblemon data registries are only loaded once per server instance as Pokémon
> species are not safe to reload."

`SimpleResourceReloader` only reloads a registry when `firstLoad` (server not yet
running) **or** it is in `reloadableRegistries`. During `/reload` the server is
running, so species and additions are filtered out.

**How to tell it actually loaded:** the log line

```
[main/INFO]: Loaded 1025 Pokémon species
```

appears **once per JVM start** and never on `/reload`. If you changed species data
and did not see that line after your change, nothing you did is live.

**Rule:** any species/species_additions change requires a **full server restart**.
There is no command that can force it.

*(Spawn presets, mechanics and action effects ARE reloadable — those register with
`iconst_1`. So `/reload` is fine for spawn tweaks.)*

---

## 3. species_additions are keyed by `namespace:filestem` — the folder is discarded

`JsonDataRegistry.reload` builds the key as
`fromNamespaceAndPath(id.getNamespace(), FilesKt.getNameWithoutExtension(File(id.getPath())))`.

So all of these collide into one key `cobblemon:dodrio`:

```
datapacks/ride-fix/data/cobblemon/species_additions/zzz_ridefix/dodrio.json
datapacks/twoseat-mounts/data/cobblemon/species_additions/zzz_twoseat/dodrio.json
jar journey-mounts data/cobblemon/species_additions/generation1/dodrio.json
```

The winner is decided by a TreeMap sorted on **path**, so `zzz_twoseat` beats
`zzz_ridefix` alphabetically. The loser is dropped **silently** — no log, no error.

**Rules:**
- A `zzz_` prefix does not guarantee winning. Check what else claims the stem.
- Different namespaces do *not* collide: `cobblemon_drops:dragonair` (Legendary
  Monuments' drop tables) is a separate key from `cobblemon:dragonair`.
- The addition's `target` field decides what it modifies — the filename does not.

---

## 4. species_additions merge Collections with `addAll` — never put `forms` in one

`SpeciesAdditions.reload` applies each field through a `KMutableProperty` setter,
but Collections and Maps are merged with `addAll` / `putAll`. Writing a `forms`
array into an addition therefore **appends duplicate forms** instead of merging
them.

**Rule:** to change a FORM, ship a full species override, not an addition.

---

## 5. A full species override must sit on the EXACT original resource path

Cobblemon's Zapdos is at `data/cobblemon/species/generation1/zapdos.json`. Writing
an override to `data/cobblemon/species/zapdos.json` does **not** replace it.

Datapacks in `world/datapacks` are highest priority (confirmed from
`level.dat` → `DataPacks.Enabled`, where `file/ride-fix` sorts last), and
`MultiPackResourceManager.listResources` returns exactly one Resource per
identifier — the top pack's. But only if the path matches.

**Rule:** mirror the jar's full path, generation folder and all.

---

## 6. Riding needs TWO things: server data AND a model seat locator

This is the big one. A Pokémon is only rideable if **both** are true:

1. **Server:** `riding.behaviours` is a Map keyed `AIR` / `LAND` / `LIQUID`, and
   `riding.seats` is **non-empty**.
2. **Client:** the `.geo.json` model contains a `seat_1` locator.

Symptoms of each failure:

| Broken thing | What you see |
|---|---|
| No `behaviours` (old singular `behaviour` schema) | **No Ride tab at all** in the summary |
| `seats: []` | No Ride tab either — seats are mandatory |
| No `seat_1` in the model | Ride tab appears, you mount, then **the camera detaches — mount runs off without you, jumping flings the camera up** |

Diagnostic shortcut: Rapidash has a locator and rides fine; Mew has none and
desyncs. If riding half-works, check the model first.

### The dead schema

`RidingProperties` declares exactly three fields: `seats`, `conditions`,
`behaviours` (Map). There is **no singular `behaviour` field and no
`getBehaviour()` accessor**. 41 species/forms in the 1.7.3 jar still use the old
`riding.behaviour` + `riding.stats` shape; those parse to an empty behaviours map
and are silently unrideable. `cobblemon:land/vehicle` and `cobblemon:composite`
are likewise **not valid keys** in 1.7.3 — no working entry uses them. Valid keys:

```
LAND    cobblemon:land/horse
AIR     cobblemon:air/bird | air/hover | air/jet | air/rocket
LIQUID  cobblemon:liquid/dolphin | liquid/submarine | liquid/boat
```

### Forms do not inherit riding field-by-field

`FormData.getRiding()` is `_riding ?: species.riding` — **all or nothing**. A form
with `behaviours` but no `seats` does NOT borrow the species' seats. It is simply
unrideable. 38 of the 41 broken entries had `seats: []`.

### Seat placement

Locator coords are model space (16 units = 1 block). Convention from the 137
models that ship a working `seat_1`: `x = 0`, `y` roughly 50–95% up, `z` varies.

When injecting one: use the **biggest bone's own bounds**, not the whole model's.
Mew and Onix have long tails that drag the model-wide centre backwards and put the
rider floating behind the Pokémon. Sit on top of the body bone
(`y = bhi[1]`) — interpolating inside it puts riders underground on Venomoth and
Dragonair, whose body bones sit below the origin.

---

## 7. Resource pack order: CCC vs the 2-seat pack

Complete Cobblemon Collection and our 2-seat pack ship **111 of the same model
files**. Whichever is higher in the Selected list wins outright. If CCC wins,
those 111 lose their second seat.

**Rule:** `cobblemon-2seats-resourcepack.zip` must sit **above** CCC.

CCC's `zapdos_galarian.geo.json` has **no seat locator**, so Galarian Zapdos
cannot be ridden while CCC is enabled — its resolver
(`1_zapdos_galarian.json`, aspect `galarian`) points at that model. Cobblemon's
own resolver has no galarian variation, so with CCC off the Galar form falls back
to base `zapdos.geo` which *does* have `seat_1`.

---

## 7b. Model, poser and animation are ONE SET — never override just the geometry

The 2-seat pack shipped `.geo.json` files only. Resource pack order put it **above**
CCC, so our geometry won — but CCC still supplied the `posers/` and `animations/`
for those same species, because our pack had none to override them with.

Result: CCC's poser calls `q.bedrock('reshiram', 'ground_idle')`, and that animation
drives **CCC's 157-bone rig**. Applied to mega_showdown's **69-bone** mesh that our
pack forced in, 152 bone lookups miss. Symptom reported in game: *"a lot of the mesh
is missing or invisible."*

**12 files were affected** (bones CCC expects that our geometry lacks):

| File | Missing bones |
|---|---|
| `reshiram.geo.json` | **152** |
| `zekrom.geo.json` | **120** |
| `dialga.geo.json` | 35 |
| `venusaurmega.geo.json` | 21 |
| `palkia.geo.json` | 8 |
| `giratina`, `palkia_origin` | 2 |
| `corviknight_gmax`, `melmetal_gigantamax`, `zygarde`, `metagross_mega`, `charizard_gigantamax` | 1 |

Note the tail: a **1-bone** mismatch is enough to lose a body part, so bone-count
deltas are not a safe filter. Compare bone **name sets**, not counts — and remember
our injected `locator_seat_1` / `locator_seat_2` legitimately add 2.

**Rules:**
- Before overriding a `.geo.json`, check whether any lower-priority pack ships a
  `posers/<species>/` or `animations/<species>/` for it. If it does, either ship the
  matching poser and animation too, or **do not override the geometry at all**.
- The correct test is `set(ccc_bones) - set(our_bones)` being empty, per geo path.
- 111 geo paths overlapped between our pack and CCC; only 12 were actually broken.
  Dropping all 111 would have needlessly removed 99 working second seats.

Fix applied: rebuilt the pack with those 12 paths removed so CCC's matched
geo+poser+animation set is used for them. Those forms lose the second seat; the
model renders correctly. `seats1_geo.py` must apply this exclusion when regenerating.

---

## 8. Pastures fail silently

`tether()` places the Pokémon `ceil(size) + 1` blocks **behind** the block and
retries at **six** positions stepping outward, calling `makeSuitableY` (a ±16
block vertical scan for a clear box on a solid floor). If all six fail it returns
`false` — and `PasturePokemonHandler` does `tether(...); pop; return`, **discarding
the result**. No message, no sound, no log line.

It reads as "this Pokémon is banned from pastures" when the spot is just blocked.
Kyogre needs 11 blocks of clear run; Groudon 7.

Other silent gates in `canAddPokemon`: per-player count, total tethered
(`defaultPasturedPokemonLimit`, 16 here), and `isFainted`. Only the nearby-entity
density check prints anything (`pasture.too_many_nearby`).

---

## 9. Two mods, one item name — check the namespace

Several items share a display name or an id across mods. Always check with F3+H.

| In game | Real id | What it does |
|---|---|---|
| Liberty Pass | `mythsandlegends:liberty_pass` | key item, force-spawns Victini in a valid biome |
| Liberty Pass | `legendarymonuments:liberty_pass` | opens a Victini Lock at Liberty Island |
| Reins of Unity | `mythsandlegends:reins_of_unity` | key item, spawns Calyrex |
| Reins of Unity | `mega_showdown:reins_of_unity` | fuses Calyrex with its steed |
| **Lunar Wing** | `mythsandlegends:lunar_feather` | **spawns Cresselia** |
| **Lunar Feather** | `legendarymonuments:lunar_feather` | a reward Cresselia drops |

That last pair is the only case in the whole modpack where two mods use the **same
item id** with **different display names** — a name map keyed on the basename picks
one arbitrarily and mislabels the other.

---

## 9b. 33 item names are duplicated across mods — 13 between LM and M&L alone

§9 documented Lunar Wing/Feather as "the only case". That was wrong by a factor of
33. A scan of every mod's `en_us.json` for `item.<ns>.<name>` / `block.<ns>.<name>`
keys finds **33 basenames defined by more than one mod**, 13 of them shared by
**Legendary Monuments and Myths & Legends** specifically:

```
azelf_fang  azure_flute  clear_bell  gs_ball  iceroot_carrot  liberty_pass
lunar_feather  magma_stone  mesprit_plume  old_sea_map  shaderoot_carrot
silver_wing  uxie_claw
```

These are not cosmetic duplicates — they are functionally different items:

- The **Red Chain** recipe wants the **LM** `uxie_claw` / `azelf_fang` /
  `mesprit_plume`. The M&L twins do not craft.
- The **Arc Phone** tracker wants the **LM** `clear_bell` / `magma_stone` /
  `liberty_pass` / `old_sea_map`. Carrying the M&L twin silently fails to locate.

The rest mostly collide with `mega_showdown` (orbs, masks, zygarde parts).

**Rule:** never key an item on its basename. `wiki_data3.json`'s `NAMES` map does
exactly that (2527 entries, **zero** contain a colon), which is why it mislabels.
Build a `basename -> {mods, collision}` map from the lang files and badge every
rendered name. The wiki now does this: 🏛️ = Legendary Monuments, 📜 = Myths &
Legends, both = ambiguous, badge + ⚠️ = shares with a third mod.

**Rule of thumb that resolves most cases:** if a *structure* is involved (lock,
pedestal, Arc Phone, temple) you want the LM item. If you are standing in a biome
right-clicking something, you want the M&L item.

---

## 9c. Dyna Tree grows 10 east / 9 south of where you plant it

`DynaTreeSaplingBlock` needs a **5×5 sapling formation** plus **50 Galar Particle
Blocks** (`REQUIRED_GALAR_PARTICLE_BLOCKS = 50`), then stamps the
`legendarymonuments:dyna_tree` template at
`formationCentre − (10, 0, 10)` (`GIANT_TREE_TEMPLATE_X_OFFSET/Z_OFFSET = 10`).

But the trunk sits at template-local **x 10–29, z 10–28** in a 40×64×38 template —
*not* at that anchor. Net result, confirmed in game:

> **trunk lands at formationCentre + (10, 9).** Plant **10 west and 9 north** of
> where you want it.

Deterministic — a `static final int`, so replanting identically drifts identically.
A *single* sapling is unrelated: it rolls one of four random small oak shapes
(`generateClassicOak/TallOak/WideOak/ShrubOak`).

---

## 9d. Trainer Spawner is keyed by signature item

Verified from bytecode, not inferred.
`TrainerSpawnerBlockEntity.addTrainerIdsFromItem` resolves the held item's
`arch$registryName`, filters `TrainerManager.getAllData` on
`TrainerMobData.getSignatureItem`, and adds every match to `trainerIds`.

So **putting a trainer's signature item in the spawner makes it spawn that
trainer** — the fix for "I know the biome but I still can't find them".

16 signature items map to more than one trainer entry, but every one of those is
the *same character at a different story stage* (Cedric ×3, Rival Wayne ×3,
Agatha ×2). **No two Gym Leaders share a signature item**, so one item = one leader.

---

## 9e. Legendary Monuments pedestals — the Medallion of Renewal decision

`MedallionOfRenewal` calls exactly one method: `removePlayerMark`. It clears **your
own** entry in the pedestal block entity's `usedByPlayers` set. It never returns
items, it is per-player, and it refuses on anything that is not a pedestal
("This item can only be used on legendary pedestals").

**So the only question is whether the key items exist outside the structure.**

Requirements come from `PedestalConfig`'s embedded default JSON (no config file
exists on the server, so defaults are live):

```
reshiram  lightstone + fire_gem      → gives Truth Bottle
zekrom    darkstone  + electric_gem  → gives Ideals Bottle
kyurem    truthbottle + idealsbottle → gives nothing
zacian    totem_of_undying + herosword   → gives mega_showdown:rusted_sword
zamazenta totem_of_undying + heroshield  → gives mega_showdown:rusted_shield
hoopa     temple_key + prison_bottle → gives Prison Bottle back
lugia     vortex_stone               → gives Lugia Key
heatran   magma_stone
hooh      rainbow_feather   entei/raikou/suicune  their Poké Treat → coloured feathers
regis     regiglace/registone/regimetal/regivolt/regidrac, then regigigassoul
```

**Verdicts:** 9 worth a medallion, 2 situational, 2 pointless, 3 have no pedestal.

- **Pointless:** *Knightly Heroes* (Hero Sword/Shield exist only in that structure's
  item frames — you get back a *Rusted* item, not the Hero one) and *Snowpoint
  Temple* (every Regi tablet is earned inside; the Titan Key needs all five).
- **No pedestal:** the three *Lakes* (trial spawners), the four *nether shrines*
  (`AreaClearingLockBlock`), *Liberty Island* (`VictiniLockBlock`).
- **`PokemonTrialSpawnerBlockEntity.COOLDOWN_TICKS = 36000`** → the Lakes reset
  themselves every **30 minutes**, forever. No medallion needed or possible.

**Lugia trap:** the pedestal *gives* the Lugia Key; it does not need one.

**Correction to an earlier belief:** Reshiram/Zekrom pedestals *do* reward — they
are where the bottles come from. `giveReward` as a method name only exists on
Hoopa/Zacian/Zamazenta; the others hand out rewards through a different path, so
grepping for that method name under-reports.

Stones are craftable: **9 shards → 1 Light/Dark Stone**. Medallion fragments:
**4 → 1 medallion** (2×2).

---

## 9f. Cosmetics, forms, and two summon-item traps

- **Pokémon cosmetics are real**: `data/cobblemon/cosmetic_items/*.json` map
  `consumedItem` → aspect `cosmetic_item-*`, for **34 species / 250 item options**.
  Pikachu/Raichu/Pichu have 11 including `minecraft:leather_helmet` — an actual hat.
  Sudowoodo wears gold armour, Conkeldurr any concrete, Hawlucha any leaves,
  Gurdurr any ingot, Gengar/Alakazam/Jigglypuff/Electrode/Smeargle/Furfrou any dye.
- **Players get four Accessories slots** (mega / z / tera / dynamax), battle-mechanic
  only. **No cosmetic headwear for players exists in any installed mod.** The
  **Omni Ring** fits all four slots at once.
- **Dusk Lycanroc is unobtainable.** Rockruff has two evolutions only — midday
  (`day`) and midnight (`night`), both level 25. Vanilla needs Own Tempo, which is
  not in Rockruff's ability pool here (keeneye / vitalspirit / h:steadfast). The
  form exists (`wolf_form` = dusk/midday/midnight) but is command-only.
- **Ash Cap is Greninja-only.** `battle_form/greninja_ash.json` → `"pokemons":
  ["Greninja"]`. No Ash artwork for any other species.
- **Darkrai wants a Member Card, NOT Nightmare Essence.** Cresselia wants a Lunar
  Feather at night — and two of its three biomes (`mushroom_field_shore`,
  `snowy_tundra`) were deleted in MC 1.18, so only `mushroom_fields` can fire.
- **`/pokegive <player>` ignores the player argument** and gives to the sender. Use
  `/execute as <player> run pokegive ...`.

---

## 9g. Tooling notes that cost real time

- **`pgrep -f <pattern>` matches its own watcher shell**, because the pattern appears
  in that shell's command line. A `while pgrep -f x; do sleep; done` waiter never
  exits. Worse, `pkill -f x` run over SSH **kills your own SSH session**. Use a
  **sentinel file** (`echo done > /tmp/x_done`) instead of process polling.
- **Region-file scans must test the needle against the DECOMPRESSED chunk.** Testing
  the raw `.mca` bytes silently matches nothing and returns a confident zero. This
  produced two wrong "0 found" answers (bells, Cobble Merchants) before being caught.
  **Any scan reporting zero needs a positive control before it is reported.**
- **A "find item X anywhere" scan must recurse**: player `.dat` (inventory *and*
  `EnderItems`), container block entities, entity NBT, and items nested inside
  shulker boxes at any depth. `X:\claude-tmp\scratch\itemhunt.py` does this.
- **Bytecode beats inference.** `X:\claude-tmp\scratch\calls.py` dumps a class's
  method calls in order; `constvals.py` prints `static final` constants (which
  `cpstr.py` cannot see, as it only reads UTF8 pool entries). These settled the
  Arc Phone table, the Trainer Spawner mechanic and the Dyna Tree offset after
  name-based guessing had failed repeatedly.
- **Vanilla items appear as intermediary names** (`field_8288`). Resolve them from
  `class_1802.<clinit>` in `.fabric/remappedJars/*/server-intermediary.jar` by
  pairing each `ldc` string with the following `putstatic`.

---

## 9h. Form changes: 491 aspects, only 161 change the model

**How to tell a real form from a repaint.** Walk every
`assets/*/bedrock/pokemon/resolvers/**/*.json` in every jar. The variation with
`aspects: []` gives the species' base `model`. A variation whose aspect set minus
`shiny` is exactly one token, and whose `model` differs from the base, is a real
model change.

> **Do NOT credit a multi-aspect variation's model to each of its tokens.** The
> first pass did, and reported `shiny` (63 species) and `female` (82) as
> model-changing — because the *mega* resolver file contains a `["mega","shiny"]`
> variation carrying the mega mesh. Strict single-token matching fixed it.
> (`female` survived the fix at 82 — those meshes really are separate.)

Result: **491 aspect tokens, 161 change the model, 6 change only the poser**
(aegislash `blade-forme`, gourgeist/pumpkaboo pumpkin sizes, urshifu
`rapid_strike-style`, sneasler `cosmetic_item-composter`). Biggest families:
female 82, mega 74, gmax 23, alolan 17, galarian 15, hisuian 13,
region-bias-hisui 8. Everything else is 1–4 species.

**Where each mechanic is defined:**

| Thing | File |
|---|---|
| Battle forms + revert behaviour | `data/mega_showdown/mega_showdown/battle_form/*.json` (53) |
| Mega / Dynamax / Tera tuning | `config/mega_showdown/config.json` |
| Furfrou trims | `data/cobblemon/pokemon_interactions/furfrou.json` |
| Aspect definitions | `data/*/species_features/*.json` (`isAspect: true`) |

`data/mega_showdown/mega_showdown/mega/*.json` looks promising and **is not** —
those are advancements. Mega logic is in code, not data.

**`pokemon_interactions` is 137 files and exactly one of them changes a form.**
Furfrou: shears (`#c:tools/shear`), 8 durability, cooldown 1, runs
`q.pokemon.run_action_effect('cobblemon:furfrou_trim')`. The other 136 are
brush / bone-meal / bucket drops. Grepping the directory for "form" returns
nothing — the effect variant is `script`.

**Live server settings (they gate the battle forms):** `outSideMega` **true**,
`outSideUltraBurst` **true**, `multipleMegas` **false**, `dynamax` true but
`dynamaxAnywhere` **false** with `powerSpotRange` **20**, `dynamaxScaleFactor`
4.0, `teraShardRequired` **50**, `teraShardDropRate` 10%, `stellarShardDropRate`
1%, `minBondingRequired` 200, `likoPendentDuration` 72000 ticks (60 min).

**17 form-change items exist in both Myths & Legends and Mega Showdown**:
`dna_splicer`, `reins_of_unity`, `prison_bottle`, `reveal_glass`, `zygarde_cube`
/`core`/`cell`, `red_orb`, `blue_orb`, `adamant_orb`, `lustrous_orb`,
`griseous_orb`, `rusted_sword`, `rusted_shield`, `wellspring_mask`,
`hearthflame_mask`, `cornerstone_mask`. Mega Showdown implements form changing
and (confirmed for Rusted Sword) resolves its own copy first, so the M&L copy is
the dud. Mega-Showdown-only: `adamant_crystal`, `griseous_core`,
`lustrous_globe`, `n_lunarizer`, `n_solarizer`, `tera_orb`. M&L-only:
`jade_orb`, `meloetta_headset`, `teal_mask`, `type_null_mask`.

**"Chonkachu" is not a Pokémon.** `missingmons` ships
`assets/minecraft/models/block/custom/chonkkachu.json`, reached through
`minecraft:bowl` custom model data — 1 = iono_plushie, 2 = mimikyu_plushie,
3 = chonkkachu. No recipe, no loot table, no lang entry: command-only decor.
`/give @s minecraft:bowl[custom_model_data=3]`.

---

## 10. Spawn conditions hide in `presets`

A spawn entry's own `condition` block is not the whole story. `presets` pull in
extra conditions from `data/cobblemon/spawn_detail_presets/`, and that is where
**structure requirements** live.

Charcadet looks like "Any Nether" but its `nether_structures` preset restricts it
to **inside a Bastion Remnant or Fortress**, standing on the structure's own
blocks. 99 species are gated this way.

Also: entries use `spawnablePositionType`, not `context`, in 1.7 spawn files.
And dead biome names persist — Cresselia lists `mushroom_field_shore` and
`snowy_tundra`, both removed in 1.18, so only `mushroom_fields` can ever fire.

---

## 10b. Key items do not bypass spawn conditions — and are not the only route

Right-clicking a Myths & Legends key item feels like a summon, but `ForceSpawningUtils.forceSpawnInternal`
just builds a `SpawningZone` around the player and calls Cobblemon's own
`getMatchingSpawns` up to 400 times. That evaluates the **entire** condition block.
Biome, ground type and **`timeRange`** are all still enforced.

Lunala is `timeRange: "night"`. In daylight all 400 attempts fail and the player
gets *"No Pokémon matching '…' conditions could be found for spawning."* — which
reads like a broken item, not a time gate. Solgaleo is the mirror case (`"day"`).

Config on this server (`config/mythsandlegends/config.toml`):

| Setting | Value | Effect |
|---|---|---|
| `force_spawning_spawn_pool` | `ultra-rare` | bucket is pinned, so all 400 tries are real attempts |
| `force_spawn_check_width/height` | 100 / 50 | the search box around the player |
| `force_spawn_item_cooldown` | 20 s | enforced even on a **failed** attempt |
| `item_consumption_mode` | 1 | key item is destroyed on success |

Consumption is deferred: `DebtUtils.addDebt` records it and
`PlayerDataUtils.updatePlayerData` later calls `InventoryUtils.removeItemFromInventory`.
`config/mythsandlegends/debts.json` shows anything still owed.

### A key item gates its own entry, not the species

`spawn_pool_world` files from different mods have different filestems, so they do
**not** collide (unlike `species_additions`, §3) — they stack as extra options.
Kubfu has three entries, and the best one needs no key item at all:

| Source | Biomes | Key item | Weight | Other |
|---|---|---|---|---|
| `mythsandlegends-kubfu.json` #1 | any jungle | `kubfus_band` | 0.1 | `natural` preset |
| `mythsandlegends-kubfu.json` #2 | bamboo | `kubfus_band` | 0.1 | `natural` preset |
| `missingmons/kubfu.json` | bamboo | **none** | **1.5** | `canSeeSky: true` |

**Rule:** before telling anyone a key item is required, grep every jar's
`spawn_pool_world/` for that species. `missingmons` in particular re-adds plain
natural spawns for mons M&L had locked behind items.

---

## 10c. RCT trainers: ask the SERVER, not the jar

Got this wrong live. The mob JSON for a Gym Leader reads:

```json
"series": ["radicalred"],
"requiredDefeats": [["leader_lt_surge_01a0"]],
"type": "leader"
```

I read `series` as a spawn gate and told the user no Gym Leader could spawn while
their series was `empty`. **Wrong.** The server disagrees:

```
/rctmod trainer get required_series leader_erika_01a1   ->  []
```

`series` is **membership** (which campaign she belongs to). `requiredSeries` is the
**gate**, and it resolves from the *series definition's* own `requiredSeries` — which
is `[]` for all three campaigns. So every trainer spawns regardless of series.

What series actually gates is `TrainerMob.canBattleAgainst`, which checks four
things and emits a refusal dialog instead of a fight: `wrong_series`,
`missing_required_series`, `missing_required_trainer`, `over_level_cap`.
**Leaders spawn freely and then refuse to battle.** That is why players see them.

**Rule:** rctmod exposes read-only introspection — use it instead of inferring.

```
/rctmod trainer get (type|required_series|required_defeats|max_trainer_defeats) <id>
/rctmod player  get (series|level_cap|luck|progress|defeats <id>|type_defeats <tier>) <player>
```

`player get` needs the player **online** — offline names return "No player was found".

### The id prefix lies about the tier

`leader_erika_0041` and `leader_erika_01a1` both exist. Only `01a1` has a file under
`data/rctmod/mobs/trainers/single/`. `0041` has none, so it falls back to
`mobs/trainers/default.json` — `type: normal`, no biome restriction, no prerequisites.
The server confirms `/rctmod trainer get type leader_erika_0041` → **Normal**.

So a player can "beat Erika" while `type_defeats leader` stays at 0. Never infer a
trainer's tier from its id; query it.

### One more trap

`/rctmod player set series <bad> <player>` prints its rejection **to the player's
chat**, not to the RCON console. Do not use invalid arguments to probe syntax while
someone is online.

---

## 10d. Cobble Merchant can never spawn — BCA vs CobbleDollars

CobbleDollars injects `cobbledollars:cobble_merchant` into
`data/minecraft/worldgen/template_pool/<type>/villagers.json`.

Cobblemon Additions overrides `data/minecraft/worldgen/structure_set/villages.json`
to generate `bca:village/*` instead, and its `#bca:villages` biome tag `replace`s the
vanilla `has_structure/village_*` tags. BCA's 54 template pools **never reference
`minecraft:village/*/villagers`**.

Result: the injection lands in a pool nothing uses. Confirmed empirically — a scan of
all 1919 entity region files across all three dimensions found **0** merchants (and
`/locate structure minecraft:village_plains` fails; only `bca:village/*` resolve).

**Workaround:** `cobbledollars:cobble_merchant_spawn_egg`, placed manually. The shop
(`config/cobbledollars/default_shop.json`) is otherwise fine — Master Ball is in it at
100,000, and the config is live-editable.

Same class of bug is worth checking for any mod that injects into vanilla worldgen
pools, because BCA replaces villages wholesale.

---

## 10e. Non-op waypoint teleport (LuckPerms + VanillaPermissions)

**Problem:** Xaero's minimap teleport button runs `/tp @s {x} {y} {z}`
(`config/xaero/minimap/profiles/default.cfg` → `default_waypoint_teleport_format`).
Vanilla `/tp` is permission level 2 — and so is `/gamemode`. Vanilla cannot separate
them, so opping a player to give them waypoint teleport also gives them creative.

**Fix, installed 2026-08-17** (both server-side only, no client changes):

| Mod | Version | SHA-1 |
|---|---|---|
| LuckPerms Fabric | 5.4.140 | `5368c9a12f181eeeae124b70395691780e5cb657` |
| VanillaPermissions | 0.3.3+1.21.1 | `0f03bc587452f132d5139b7864d47e248cf82ec3` |

Both bundle `fabric-permissions-api-0.3.1` as a JiJ, so there is no third jar.
On boot you should see:

```
[main/INFO]: found fabric-permissions-api, disable vanilla permission system
```

### The node scheme has TWO independent axes

This is the part that is easy to get wrong. VanillaPermissions gates on both:

- **command nodes** — `minecraft.command.teleport` for the root, plus a sub-node per
  Brigadier argument (`minecraft.command.teleport.targets`, `...destination`).
  Granting only the root is **not enough** for `/tp @s x y z`, because `@s` goes
  down the `targets` branch. Grant `minecraft.command.teleport.*` as well.
- **selector nodes** — `minecraft.selector.{self,player,entity}.<command path>`.
  *These* are what restrict who you may target, and they are the self-only lever.

### The live config

```
group default   minecraft.command.teleport            true
                minecraft.command.teleport.*          true
                minecraft.selector.self.teleport.*     true
                minecraft.selector.player.teleport.*   false
                minecraft.selector.entity.teleport.*   false
group admin     (weight 100)
                minecraft.selector.player.teleport.*   true
                minecraft.selector.entity.teleport.*   true
```

`/gamemode` is simply never granted, so it falls back to the op check and stays
closed for non-ops.

### TRAP: an explicit `false` on `default` also hits your ops

`default` contains **everyone, ops included**, and fabric-permissions-api honours an
explicit `false` from the provider *instead of* falling back to the op level. The
`selector.player.teleport` deny therefore removed the admins' ability to teleport
other players until an `admin` group at weight 100 put it back. Any time you deny
something on `default`, add the counter-grant for admins in the same breath.

### Verifying without a player online

`lp group <g> permission info` returns **nothing over RCON**, and so does
`permission set` — silence is not failure. Use the exporter instead:

```
lp export permsdump      # writes mods/luckperms/permsdump.json.gz
```

then read it with `gzip`+`json`. That is the only reliable confirmation from a
console session.

---

## 11. Recipe slots can be tags

`pokedex_screen` is not an item — it is the tag `#cobblemon:pokedex_screen`,
accepting redstone, glowstone dust, glow ink sac, blaze powder or bright powder.
Rendering the bare tag name makes it look like a craftable component that does not
exist. Always expand tags (recursively) when displaying a recipe.

---

## 12. Rebuilding the wiki: `/tmp` on the server is NOT canonical

`build3.py` lives in `X:\cobblemon-ops`. The copy in the server's `/tmp` drifts —
it survives only until the box reboots, and it was found **four `.replace()` calls
behind** the local one:

```python
.replace('__MULCH__',       D3.get('mulch_html') or '')
.replace('__RIDES__',       D3.get('rides_html') or '')
.replace('__NOMODEL__',     D3.get('nomodel_html') or '')
.replace('__PASTURESPACE__', D3.get('pasture_space_html') or '')
```

Rebuilding from the stale copy silently emits the literal strings `__RIDES__`,
`__MULCH__`, `__NOMODEL__`, `__PASTURESPACE__` into the page — four whole sections
gone, and it still "builds fine". Nothing errors.

**Rules:**
- Always upload the local `build3.py` before rebuilding, `tr -d '\r'`-ing it on the
  way up if it picked up CRLF (§13).
- Before deploying, prove the diff is only what you intended: strip your new blocks
  out of the rebuild and assert the result is byte-identical to the deployed file,
  then assert `re.findall(r'__[A-Z_]+__', html)` is empty.
- Keep a timestamped `.bak` of `public/mc-wiki.html` before overwriting.

---

## 14. Reading and editing the world for a build

Written while helping with the Poké Ball gym at **<coords>** (37-diameter
arena floor, Poké Ball inlay, four archways, leaded-glass drum).

**Read the world properly.** `berryscan.py` only reads palettes; `voxel.py` decodes
the packed `block_states.data` and gives real per-coordinate blocks. Notes:

- Run `rcon.py "save-all flush"` first or you read a stale chunk.
- Bit width is `max(4, bit_length(len(palette)-1))`; values never span two longs
  (post-1.16); index order is `y*256 + z*16 + x`.
- A section whose palette has one entry has **no** `data` array — the whole
  section is that block. Skip it when it is air, or you get 4096 phantom blocks.
- Filter natural terrain out before rendering or the build is invisible in the noise.

**Minecraft circles use a half-block radius.** The arena floor matched
`dx² + dz² ≤ 18.5²` **exactly**, all 37 rows, no fudges. Any dome, sphere or
second storey must reuse the same rule and the same centre or it will not line up.
Derive the rule from the build rather than assuming — one row of disagreement
throws the whole shell off.

**Watertight shells: use the neighbour rule, not a radius band.** `r-1 ≤ dist ≤ r`
leaks. Keep a block if it is in the solid AND (any of its 4 lateral neighbours is
not, OR the layer above does not cover it). Watertight by construction.

**A correct dome still springs inboard of the wall.** Layer 0 of the sphere is
already narrower than the equator, so at the diagonal positions the first course
steps in by one — an *uneven* ledge at 36 of 104 positions here. Force-add the
full wall-line ring to the first course.

**Flood-fill to verify, and get the escape boundary right.** Treat only the SIDES
and TOP of the test box as escapes. Counting the floor reports a false leak,
because the interior is legitimately open downward. Cost me one wrong "LEAK".

**`fill ... replace air` is the safe way to lay a shape through existing geometry.**
The four wool spheres pass straight through the glass dome; filling air-only left
all 1,329 dome blocks intact, so the arena still has a glass ceiling from inside.
Replacing outright would have blacked out a quarter of the sky.

**…but `replace air` leaves every non-air block embedded, and that dents a solid
shape.** Always run a second pass: rescan, find non-air cells inside the volume
that are not the thing you deliberately preserved, convert those, and append their
original ids to the undo. 88 blocks of hillside needed it here — and logging their original ids meant the
later resize could put 82 of them back automatically.

**A ball resting on a dome eats the dome's interior, and you will not notice.**
The bloom's underside curved down *inside* the glass shell: 3,996 of 7,933 enclosed
cells filled, so from the battle floor the ceiling read 1,676 wool faces to 501
glass. Measure it, do not eyeball it — rebuild the solid set **without** the new
blocks, flood from the room's centre, and that flood is the true interior. Then
`target = shape - interior` trims the shape at the inner surface and hands the
ceiling back. Final: 0 wool inside, 7,933 cells, ceiling 100% glass.

**Two spheres facing each other across a centre touch only when the centre offset
equals the radius (D = R).** So "meet exactly in the middle" and "overhang by
nearly a full radius" fight each other: overhang/radius = 2 - 18.5/R, which only
reaches ~1 at R≈18.5. Pulling the centres inward for a smaller bloom also drives
them *deeper* into the dome, because the dome's surface rises as you approach the
apex. Say that out loud before offering sizes.

**Out-then-down, not down-then-out.** A hanging appendage reads upside down if
the centreline descends before it extends. Gloom's bangs hold their height while
running outward and only drop at the far end - the hand-built one sat at y81-89
from u20 all the way to u29, then fell to y74 over the last three steps. A
"hug the surface on the way down, flare at the bottom" centreline looks
plausible in numbers and inverted in game. Sanity-check any swept shape with a
u-versus-y table against the reference before placing.

**Check the ground under a drooping shape.** The southwest hillside steps from
y62 to y69 at u28 and y74 at u34, so a tip that hangs at y72 is fine at u31 and
buried at u34. `max(y where block is natural)` per column, sampled along the
centreline, catches it before it is placed.

**A round tube hides its own curve; a flat ribbon shows it.** The first pass at
Gloom's bangs swept a sphere along the centreline. From every angle a tube has
the same silhouette, so a curl just reads as a fat blob — the owner's words were
"hard to tell it curves without looking from certain angles". Rebuilding with an
elliptical cross-section (wide along the curve's vertical plane, thin
horizontally) made the same curve legible at half the block count. Check the
reference before choosing a cross-section: Gloom's bangs are flat blades.

**Extract reference frames on the server.** No ffmpeg or PIL locally, but the
Vultr box has ffmpeg. `ffmpeg -i clip.mp4 -vf "select=not(mod(n\,37)),scale=400:-1,tile=4x4"`
gives a contact sheet of a full rotation in one readable image.

**To duplicate a build across a structure, rotate 180 degrees - do not reflect.**
`x' = 2*CX - x, z' = 2*CZ - z` maps north->south and east->west in one transform,
and because rotation preserves handedness the stair `shape` property is untouched;
only `facing` flips and sign `rotation` gains 8. A reflection would force every
inner_left/outer_left to swap sides, which is easy to get subtly wrong.

**Check for per-side differences before any whole-box copy.** The gym's four gates
carry four *different* CobbleFurnies statues (ancient / squirtle / charmander /
pikachu). Copying the north box wholesale would have silently replaced Charmander
and Pikachu. The fix was to shrink the source to the rows that are genuinely
identical (staircases y 63-68, statues y 69-70). Then verify `rot(source) ==
target` for every cell — both staircases came out 0 mismatched over 2,508 cells.

**A mirror is not done when the source blocks are placed.** Anything on the target
side that the source does *not* cover still has to be removed — 15 blocks of
village debris sat where the north side has open air.

**Scale is a non-issue.** 2,601 fills / 85,181 blocks went through batched RCON in
**0.56 s**; shaving the bloom from r=18 to r=16 was another 4,929 commands, also
instant. Because a smaller concentric ball is a strict subset of a bigger one, a
resize is a *shave* (`air replace red_wool` on the difference), never a rebuild. `/fill` is capped at 32768 blocks per command — the two Petalwake house
clears were 15,750 and 6,384-block volumes, so one command each.

**Generated village structures are not player builds.** Petalwake Village comes from
**cobblemon-additions**. Before deleting any of it, run `blockentities.py` over the
box — house 1 had 11 containers with generated loot still in them. Ask first.

**Bulk edits.** `rcon.py` opens a socket per command. `rconbatch.py` sends the
whole list over one connection — 745 fills in seconds. Success string is
`Successfully filled N block(s)`, not `Changed`. Always:

1. check what currently occupies every target position (all 1365 were air here),
2. write an **undo file** of `fill ... air` in reverse order,
3. keep it somewhere other than `/tmp` — `$COBBLEMON_DIR/dome_undo.txt`.

---

## 15. RCT trainer spawning: the numbers, and where they hide

Config is `config/rctmod-server.toml`; the logic is in the rctmod jar
(`api/service/TrainerSpawner`, `world/blocks/entities/TrainerSpawnerBlockEntity`,
`world/blocks/entities/TrainerRepelRodBlockEntity`,
`world/entities/goals/MoveToHomePosGoal`). Read with `tools/disasm.py`.

**A wandering trainer can NEVER spawn near you.** `nextPos` rolls `|dx|` and `|dz|`
*independently*, each in `[minHorizontalDistanceToPlayers, maxHorizontal)` =
`[25, 70)`. Both axes, so the true minimum is **&radic;(25&sup2;+25&sup2;) &asymp; 35
blocks**, not 25. Any building under ~70 wide is inherently spawn-proof while you
stand in it. This is the whole reason gym leaders "always turn up somewhere else".

**`canSpawnAt` is only three checks**: chunk loaded, `pos.below()` not air, `pos`
and `pos.above()` **are air**. No light level, no sky, no solidity. But `isAir()`
is strict, so carpets, snow layers, grass and torches block a spawn point.

**The Trainer Spawner block bypasses almost everything.** It calls
`attemptSpawnFor(player, id, pos.above(), true, true, boosted, 1.0, 1.0)`, and the
booleans skip the repel-rod check, `maxTrainersPerPlayer`, the trainer-card
requirement, and (when boosted) the chance roll. It does **not** skip
`maxTrainersTotal`, `isUnique` (500 blocks) or the level-gap chance.
It also never calls `nextSpawnCandidate`, which is where the **biome tag filter
lives** — so a spawner ignores biome entirely.

- Spawns at **exactly** `spawner.above()`, `setPos(center - 0.5y)`. No scatter.
- Its player range is `maxHorizontalDistanceToPlayers * 2/3` = **46.7**, as a cube.
- Retries every **80 ticks**, owns **one** trainer at a time, and adopts a loose
  matching trainer within range every 200 ticks.
- Calls `setHomePos`, and `MoveToHomePosGoal` is registered **above every wander
  goal** with `searchRange = 64`. Homed trainers walk back — until 64 blocks out,
  after which the goal stops applying and they are gone.
- **POWERED = boosted = no chance roll.** A lever makes it deterministic.

**The Repel Rod is inverted and chunk-based.** `TrainerRepelRodBlockEntity` sets
`canSpawn = !POWERED`, and that flag is what gets applied — so an **unpowered rod
repels and redstone switches it off**. `markChunks` walks `chunk.x &plusmn; 3` by
`chunk.z &plusmn; 3`: a **7&times;7 chunk (112&times;112 block) area, full height**,
Y irrelevant. Marks are a counter, so overlapping rods are safe.

**Rods do not block the Trainer Association.** `TrainerAssociation.spawnFor` reuses
`TrainerSpawner.nextPos` but never calls `isMarkedAt`. Blanketing a base in rods
will not cut you off from switching series.

**Signature items are in the jar**, `data/rctmod/mobs/trainers/*.json` —
`signatureItem`, `series`, `type`, `spawnWeightFactor`, `biomeTagWhitelist`,
`maxTrainerDefeats`. 116 of 166 trainers have one.

---

## 16. LinguaChat: Google killed `client=gtx` (client-side mod)

Symptom: chat translation stops for **everyone at once**, no config change, no
update. It is not a quota, an IP ban, or a setting.

`linguachat-1.21.1-2.0.0.jar` hardcodes Google's free undocumented endpoint
`translate.googleapis.com/translate_a/single?client=gtx`. Google now answers
that parameter with **HTTP 429 "your computer or network may be sending
automated queries"**. Proven from an unrelated server IP that had never made a
translation request, and with three different User-Agents — so it is the
parameter, not the caller.

**`client=dict-chrome-ex` still returns HTTP 200 and byte-identical JSON.**
The mod parses `root[0][i][0]`, which both variants produce, so swapping the
parameter is a true drop-in. Six rapid calls: all 200.

Fixed with `tools/patchconst.py` — two UTF8 constants in
`GoogleTranslateClient.class`, 1 of 61 jar entries, +22 bytes. Output lives in
`client/linguachat/linguachat-1.21.1-2.0.0-FIXED.jar` plus per-player zips.

Other facts worth keeping:

- `GoogleTranslateClient.isAvailable()` is a hardcoded `return true`, so the mod
  can never tell that Google is dead and never routes around it.
- `buildProviderChain()` only adds DeepL/Kagi when a key is configured. With the
  stock config (`preferredTranslator: google`, no keys) the chain is **Google
  alone — there is no fallback**.
- Any non-200 becomes `TranslationException(NETWORK_ERROR, "HTTP code: n")`.
  There is no retry and no backoff, and with `debugMode: false` nothing is shown
  in game — it just silently stops translating.
- Durable fix is a free **DeepL API** key (500k chars/month, keys end in `:fx`);
  the mod bundles the official `deepl-java` library and will then fall back to
  Google on DeepL failure.
- Latest release is **2.0.0, 2026-04-03** (Modrinth API) — updating does nothing.

---

## 17. Fossils and sherds: vanilla archaeology is the wrong place

**Pottery sherds have no use in this pack beyond decorated pots.** Searched every
recipe in all 43 jars: zero consume a sherd. Cobblemon adds six of its own via
`data/cobblemon/tags/item/decorated_pot_sherds.json` (bygone, capture, dome,
helix, nostalgic, suspicious) but they are still just pot faces.

**`dome_sherd` and `dome_fossil` are different items.** Easy to misread in loot.

**No vanilla archaeology loot table contains a Cobblemon fossil.** Desert
pyramids, ocean ruins and trail ruins will never give one no matter how many
brushes you break. Fossils come only from Cobblemon's `prehistoric_*`
structures, whose suspicious blocks use `data/cobblemon/loot_table/fossils/**`.

**The structure IDs are namespaced under a subfolder.** It is
`cobblemon:fossils/prehistoric_dripstone_oasis`, NOT
`cobblemon:prehistoric_dripstone_oasis` — the short form fails with "There is no
structure with type". Easiest route is the tag:

```
/locate structure #cobblemon:fossil
```

**Each fossil structure GUARANTEES exactly one fossil type, via its `rare`
block.** Read the structure's processor list, not the loot tables: the third rule
names `cobblemon:fossils/rare/<x>_fossil`, and those rare tables are single-entry
(100%). Searching loot tables for a fossil name instead finds the *uncommon* pool,
where it is only ~5% - that mistake sent a player to `suspicious_mound` for a Dome
when that site's guaranteed drop is `bird_fossil`.

**Dome Fossil has exactly ONE source: `prehistoric_hydrothermal_vents`** (temperate
ocean, and NOT the `vibrant_` variant, which guarantees Cover). Helix is
`sandy_den`. Full map is in the processor lists.

Fossil sites drop no gems and no sherds, so if a site is giving you those, it has
no fossil in it.

**"Relic Disc" does not exist.** The item is the vanilla **Music Disc "Relic"**,
and its only source in the game is `archaeology/trail_ruins_rare` at 1/12 =
8.3% - suspicious *gravel* in Trail Ruins. The other 11 slots are 7 sherds and
4 armour trims.

**Fossil sites are BURIED and tiny - and you can read their loot in advance.**
`terrain_adaptation: "bury"` plus a gravity processor at `offset: -3` against
`OCEAN_FLOOR_WG` puts these structures *three blocks under the seafloor*. Nothing
shows on the surface. For the vents the marker is a bubble column with a magma
block at its base; the suspicious sand is directly beneath the magma.

Counts are small by design: the rule processor converts only **15% of the
template's sand/gravel** to suspicious. One scanned vent had **3 suspicious
blocks in the entire 240x240 sprawl**, not a field of them.

**Read the brushable block entities before digging.** Each carries a `LootTable`
tag naming exactly which table it will roll - `common/...`, `uncommon/...` or
`rare/<specific>_fossil`. The rare tables are single-entry (weight 2/2 = 100%),
so a block tagged `rare/cover_fossil` IS a guaranteed Cover Fossil.
`tools/blockentities.py` over the site tells you which blocks are worth brushing
and which are coal and bone.

**`#cobblemon:fossil` finds the nearest site of ANY type.** It sent a player
48k blocks to a `prehistoric_vibrant_hydrothermal_vents`, which is a Cover/Helix
site and can never drop a Dome. Locate the six dome structures by name instead.

**Never break suspicious sand/gravel with a tool** - the loot is destroyed
silently. Brush only. A Titan Hammer through a vent erases the fossil.

**Alternative fossil source:** `rctmod/loot_table/generic/legendary/archeology`
carries dome, helix, claw, cover, armor, jaw and all four fossilized parts at
equal weight, so high-tier trainers drop them too.

---

## 13. Other traps worth remembering

- **`set -e` + `tar` on a live world**: tar exits 1 on "file changed as we read
  it", which is normal. With `set -e` that aborts the backup script before
  `save-on` runs, leaving auto-save **off indefinitely**. Always `trap ... EXIT`
  the re-enable.
- **`save-all flush` on a big backlog** can exceed `max-tick-time` (60 s) and the
  Server Watchdog will kill the JVM. Do it with nobody online, or stop the server
  and let shutdown flush.
- **Region files can be 0 bytes.** 209 of ours are. Guard header reads or the
  scan crashes.
- **`ps %CPU` is a lifetime average**, useless for "what is it doing now". Read
  `/proc/<pid>/stat` utime+stime across an interval instead.
- Only **`Server thread`** is profiled by spark's background profiler by default;
  worldgen happens on worker threads and will look like it costs nothing.
- **CRLF from Windows-side edits.** Anything rewritten in `X:\cobblemon-ops` can come
  back CRLF. A shell script with CRLF fails with a useless `\r: command not found`;
  a Python script survives but `diff` then reports *every* line changed. Compare with
  `diff --strip-trailing-cr`, or `tr -d '\r'` both sides before diffing.
- **Don't trust byte-size arithmetic to prove two files match.** Normalise line
  endings and run `cmp`/`diff` — the maths lies when CRLF is involved.

## 18. Poké Snacks — measured behaviour (2026-08-23)

Investigated because snacks in a dripstone cave "seemed dead" vs a forest.
**They were not dead. They were working the whole time.** Measured on a live snack
at `<coords>`: `AmountSpawned` went 3 → 4 → 5 in under 3 minutes.

### The two radii are different — this is the whole trap
From `PokeSnackBlockEntity.spawner_delegate$lambda$0` and `FixedAreaSpawner.getZoneInput`:
```
FixedAreaSpawner(dim, WORLD_SPAWN_POOL, level, blockPos, horizRadius=8, vertRadius=8, perChunk)
base   = snackPos.offset(-8, -8, -8)
length = width = height = 2*8 + 1 = 17
```
- **Spawn zone: a 17x17x17 cube centred on the SNACK** (snack +-8 on every axis). Not
  on the player.
- **Activation radius: 40 blocks** from the player, via
  `getNearestPlayer(x, y, z, 40.0, false)` in `randomTick`.

### THE BIG ONE: every nearby living entity vetoes spawn positions
`CobblemonSpawningZoneGenerator.generate`:
```
world.getEntities(cause.getEntity(), AABB.ofSize(zoneCentre, len+8, hgt+8, wid+8))
     .filter { it is LivingEntity }     // class_1309
     .map    { it.position() }
     -> zone.nearbyEntityPositions
```
`AreaSpawnablePositionResolver.resolve` then **rejects any candidate position within
`minimumDistanceBetweenEntities` (8.0) of any of those positions.**

`ServerLevel.getEntities(except, aabb)` excludes exactly **ONE** entity: the cause,
which is the single **nearest** player. Therefore:

| Who | Vetoes an 8-block sphere? |
|---|---|
| Nearest player (the cause) | **No** — exempt |
| Second, third player | **YES** |
| Bats, wild Pokemon, NPCs, any LivingEntity | **YES** |

Two players standing together at the cake = one exempt, one blanking the zone. That
looks exactly like "the snack is broken". It is not.

**Correct placement:**
- Exactly **one** person may stand at/near the snack — they are the cause and are exempt.
  Put your catcher there.
- **Everyone else >= 17 blocks away** (8 zone radius + 8 veto radius). >= 22 blocks to
  clear even the zone's corner cells (corner is at 8*sqrt(3) = 13.9).
- **Kill living mobs within ~17 blocks of the snack.** Bats in a cave are the usual
  culprit; a single bat parked next to the cake removes a large slice of the zone.
- Someone must still be inside 40 blocks or nothing fires at all.

⚠️ An earlier revision of this file said "stand within 8 blocks". **That is wrong for
everyone except the nearest player** and will kill your spawn rate. Corrected 2026-08-23
after decompiling the resolver.

### randomTick is the rate limiter
```
counter -= 1.0
if (counter > 0) return
player = getNearestPlayer(..., 40.0, false)
if (player != null) attemptSpawn(player)
counter = getRandomTicksBetweenSpawns()      // resets EITHER WAY
```
**The counter resets even when no player is in range.** Running in and out of the
40-block ring throws away whole cycles — it can only hurt. Stand still, stay close.

Rate maths: random ticks are 3 blocks per 4096-block section per game tick, so a
specific block is ticked every ~68 s on average. `getRandomTicksBetweenSpawns()` =
`max(1, biteTimeMultiplier * 2)`. Two snacks side by side will finish at wildly
different times — it is a geometric lottery per block, and the variance equals the
mean. That is normal, not a bug.

### Bait effects come from the crafting ingredients
Read them with `data get block <x> <y> <z>` → `BaitEffects` / `Ingredients`.

| Ingredient | bite_time | rarity_bucket | shiny_reroll |
|---|---|---|---|
| golden apple | 0.25 | 1 | 1.0 |
| **enchanted golden apple** | 0.1 | **10** | **9.0** |
| glistering melon slice / golden carrot | – | 1 | – |
| **berries** | – | **none** | – |

`biteTimeMultiplier = 1 - value`, so golden apple → `max(1, 0.75*2)` = **1.5 random
ticks** per spawn; enchanted → 1.8 (slightly slower per bite, hugely better rarity).

### Bucket influences a snack always applies
1. `BucketMultiplyingInfluence({uncommon 2.25, rare 5.5, ultra-rare 5.5})` — **always
   on**, regardless of ingredients. Snacks are already a strong rare-hunting tool.
2. `BucketNormalizingInfluence(tier, gradient=0.2, firstTier=1.2)` — only if the summed
   `rarity_bucket` > 0. `factor = 1.2 + 0.2*(tier-1)`.
   - 3× golden apple → tier 3 → **1.6**
   - 3× enchanted golden apple → tier 30 → **7.0**  ← ~4.4× better
3. `SpawnBaitInfluence(effects)`

### Other constraints
- `affectSpawnable` accepts **pokemon-type details only and excludes
  `PokemonHerdSpawnDetail`** — snacks never produce herd spawns.
- `pokeSnackPokemonPerChunk = 2.0` — a hard cap on Pokémon in the snack's chunk.
- 8 bites per snack, then it's gone.
- `AmountSpawned` on the block entity is the honest counter. **Poll it to tell
  "not spawning" apart from "spawning where I can't see".** This is the single most
  useful diagnostic.

### Things that turned out NOT to matter (verified, don't re-chase)
- **Torches / light level.** Zero dripstone-eligible entries have a `maxLight`
  condition. The light-gated ones use `maxSkyLight`, which needs *absence of sky* —
  satisfied underground and unaffected by torches. Light the cave freely.
- **Cramped space / Genesect being big.** Genesect's hitbox is 0.8 w × 2.0 h
  (`species_additions` overrides the base 1×1). The cave had 197 grounded positions
  in r=8, *all* with 4+ headroom.
- **Biome pool size.** With vanilla biome tags loaded, dripstone caves have **181**
  eligible grounded entries vs forest **277 day / 116 night**. Comparable.
  ⚠️ An earlier "forest pool is 7× bigger" figure was WRONG — it came from substring-
  matching biome names and from loading tags only out of mod jars. **`#minecraft:is_*`
  tags live in `versions/<ver>/server-<ver>.jar`, not in the mod jars.** Always load
  the vanilla server jar when resolving biome tags, or every vanilla-tagged spawn
  silently fails to match.
- **Entity crowding.** Zero Pokémon were within 16 blocks during the slow period.

### Genesect specifically
`bucket: ultra-rare, weight 5.0, biomes: #cobblemon:is_dripstone, grounded`, no light
or Y condition. It is **9.77%** of the ultra-rare weight available in a dripstone cave
(competing with fluttermane 29%, screamtail 21%, beldum/gible 12% each).
Best setup: enchanted-golden-apple snacks, stand within ~8 blocks, don't move.

## 19. The wiki generator (2026-08-23)

**Where it lives.** `build3.py` runs on **the server**, not locally — it reads `/tmp/wiki_parts.json`,
`/tmp/wiki_data2.json`, `/tmp/wiki_data3.json`, `/tmp/struct_nbt.json`, `/tmp/wiki_tpl3.html`,
which exist only there, and writes `/tmp/mc-wiki.html`. `X:/cobblemon-ops/build3.py` is a mirror:
edit locally, `scp` up, keep the hashes equal. Deploy target is
`X:/the website repo2/public/mc-wiki.html`, owned by the **the website repo** session — hand them
the file and the sha, do not write into their worktree.

**Biome labels are the wiki's main failure mode.** Three distinct traps, all now fixed:

1. **A tag rendered as its internal category name.** The old `pretty_biome` turned
   `#cobblemon:is_spooky` into "Any Spooky". No player knows what a spooky biome is. Resolve
   through `D3['tag_map']` (tag -> concrete ids) filtered by `D3['bio_ok']` (the 69 biomes that
   exist here) and name them: "Dark Forest or Plains Of Death". Several tags collapse to a
   *single* biome — "Any Desert" is just Desert, "Any Lush" is just Lush Caves.
2. **A biome whose plain name is a DIMENSION name.** `minecraft:the_end` printed as "The End",
   which reads as the End dimension. It is the central island biome only — End Highlands,
   Midlands, Barrens and Small End Islands never match. This cost a real trip. Same shape for
   "the Nether" vs one specific Nether biome.
3. **A tag that resolves to nothing.** `#cobblemon:is_nether` and `#cobblemon:is_nether_wasteland`
   do not exist in Cobblemon 1.7.3 (they were renamed to `#cobblemon:nether/is_*`), so they must
   render as nothing and be dropped, never printed as a destination.

**Some HTML is pre-baked and bypasses the renderer.** `myth_html`, `dossier`, `notes`,
`craft_html` and friends are HTML strings produced by *earlier* scripts, so their biome labels
never pass through `pretty_biome`. Fixing the function is not enough — sweep the assembled page.

**NEVER sweep labels over the assembled page.** This was got wrong twice and is the
single biggest lesson here. A whole-page sweep re-enters the renderer's own output: the
renderer emits `Nether Wastes (this Nether biome specifically)`, the sweep then matches
the bare prefix and appends the note a **second** time. It also stamped a solo-only
qualifier onto every entry of a list, producing 139 runs of
`Basalt Deltas (this Nether biome specifically), Crimson Forest (this Nether biome
specifically), ...`. Guard conditions do not fix this - the architecture does. **Sweep
the pre-baked blobs one at a time, at source, before rendering.** Then renderer output
is off-limits by construction. Doing that took the sweep from 14,716 occurrences to
1,176, which is the honest size of the job.

**The blobs hide at every depth.** A top-level-strings-only pass missed all of: guide
prose (`"That structure generates in: Any Nether"`), spawncond anticonditions
(`"not in Any Floral, Any Freezing, Any Spooky"` - these live in `['c']`, not `['bi']`),
and dossier sub-dicts (`{"ped": {"bio": "Any Nether"}}`, which reached the dex payload).
Recurse, and skip only the keys already handled with list-awareness (`mnl2`, `bi`,
`biomes`).

**The old label spellings are inconsistent - do not guess one.** The upstream namer kept
`/` in nested tags (`#cobblemon:nether/is_crimson` -> "Any Nether/Crimson"), sometimes
kept the `has_` prefix (`#cobblemon:has_block/mud` -> "Any Has Block/Mud"), and sometimes
used only the last path segment (`#cobblemon:has_season/autumn` -> "Any Autumn").
Generate every variant and register exact spellings first, so short forms only fill gaps.

**Other regex traps in the sweep:**
- *Inner-word matches.* An alternation of only the CHANGED labels lets "Plains" match
  inside "Dyna Plains". Put **every** known label in the alternation, longest first, and
  map unchanged ones to themselves so the long label consumes itself.
- A lookbehind of `(?<![\w>])` looks sensible and is wrong: in HTML a label usually sits
  right after `>`, so it silently skips exactly the cases you care about. Use `(?<!\w)`.
- The trailing guard must reject an *optional space* before `(`. `(?![\w(])` misses
  `Label (note)` and doubled 506 labels.

**`#empty` is not a biome tag.** It marks a structure that is not placed by biome at all
(the Hall of Origin sits in its own dimension). It was rendering as "Any Empty".

**Not every "Any X" is a biome.** "Defeat Any Count" is prose. Verify before sweeping.

**Marker counts prove presence, not correctness.** Every doubling bug above passed a
count-based check. Read a few entries end-to-end as rendered text before shipping.

**Bucket weights live in `config/cobblemon/spawning/best-spawner-config.json`**, not `main.json`:
common 94.3 / uncommon 5 / rare 0.5 / **ultra-rare 0.2**, summing to 100. So "a 0.2% ultra-rare
roll" for passively carrying a key item is correct — verify before "correcting" it. (Poké Snacks
are different: they multiply ultra-rare by 5.5 via `BucketMultiplyingInfluence`, see §18.)

**Force-spawn facts worth not re-deriving:** `enable_force_spawning = true`,
`enable_vouchers = false` — so the 20-second cooldown and the voucher cap in
`config/mythsandlegends/config.toml` are both inert. Any wiki text claiming a cooldown is wrong.

## 20. Cross-mod item name collisions (2026-08-23)

**35 item names in this pack are defined by two different mods.** Reading a bare item
name and assuming which mod owns it is the same failure as reading "The End" and
assuming the dimension. Enumerate them from `assets/<ns>/models/item/*.json`:

```
adamant_orb  azelf_fang  azure_flute  blue_orb  clear_bell  cornerstone_mask
dna_splicer  griseous_orb  gs_ball  hearthflame_mask  iceroot_carrot  liberty_pass
lunar_feather  lustrous_orb  magma_stone  mesprit_plume  old_sea_map  pedestal
pokemon_trial_spawner  prison_bottle  red_chain  red_orb  reins_of_unity
reveal_glass  rusted_shield  rusted_sword  scroll_of_darkness  shaderoot_carrot
silver_wing  soft_sand  uxie_claw  wellspring_mask  zygarde_cell  zygarde_core
zygarde_cube
```

Mostly `mega_showdown` vs `mythsandlegends`, or `legendarymonuments` vs `mythsandlegends`.

**The Giratina pedestal is the live trap.** `GiratinaPedestalBlockEntity` `<clinit>` does
a registry lookup for **`mega_showdown:griseous_orb`**. Every other LM pedestal
references LM's own `ModItems` (Heatran → `ModItems.MAGMA_STONE`, Zacian →
`ModItems.HEROSWORD`, Lugia → `ModItems.LUGIA_KEY` / `VORTEX_STONE`, Ho-Oh →
`ModItems.RAINBOW_FEATHER`), so Giratina is **the only pedestal that reaches across
mods** — which is exactly why it is the one people bring the wrong item to.

**How to check any pedestal:** disassemble its `<clinit>` for a namespace+path pair; if
there isn't one, look for `ModItems.X` in `handleSpecialAction` and it is LM's own item.
All pedestals are once-per-player via `hasPlayerUsed`, so each player can use each one.

### The Arceus chain, verified end to end
```
space_globe + time_globe + antimatter_globe + celestica_flute
  -> legendarymonuments:azure_flute  (shapeless)
  -> right-click: AzureFluteTeleporter sends you to the Hall of Origin, flute consumed
```
- `antimatter_globe` has **no** use outside this recipe. It is *not* a Giratina item,
  whatever the wiki says.
- `celestica_flute` has **no recipe** and exactly **one** source in the whole pack: the
  Turnback Cave vault at 0.9% per vault. That is the bottleneck of the chain.
- The globes have no recipe either; they are tied to the `brilliant_diamond` /
  `shining_pearl` / `renegade_platinum` advancements.
- `mythsandlegends:azure_flute` is a *different* item — a key item that spawns Arceus by
  biome, unrelated to the Hall of Origin.

### Turnback Cave vault is the single most valuable chest in the pack
3 rolls, total weight 3228. Notables: `ghost_gem` 9% per vault,
`mega_showdown:griseous_orb` 4.6%, `enchanted_golden_apple` 1.8% (the snack
`rarity_bucket: 10` ingredient, §18), `griseous_core` / `adamant_crystal` /
`lustrous_globe` / `celestica_flute` 0.9% each.

## 21. Pokédex consolidation — the recipe/acquisition index (2026-08-24)

The wiki spread one Pokémon's information across four pages, so the only way to answer
"how do I get Giratina" was Ctrl-F across all of them. **Root cause: every guide carries a
`chain` naming its ingredients, but `chain.sub` was always `[]`** — the ingredients were
never resolved, so "Obtain the Celestica Flute" lived on a different page from
"Summon Arceus" with nothing linking them.

**`tools/wikiindex.py`** builds the join the wiki never had. Run it on the server before
`build3.py`; it writes `/tmp/wiki_recipes.json`:
- `recipes[item]` — 1,810 craftable results from every `data/*/recipe/*.json` across all jars
- `loot[item]` — 2,453 items, with per-container % computed from pool weights and rolls
- `mnl_loot[item]` — the owner's `loot_tables_config.json` odds, which override the jar defaults
- `trades[item]` / `spawner[item]` — hand-verified, code-only sources no datapack scan can reach
- `keyfor[item]` — 74 key items → 89 species
- `items[bare]` — **a list of every namespace defining that bare name, not one**

### Traps found building it
- **Resolve guide items by EXISTENCE, not by "has a source".** Shrines, pedestals and
  legendary drops have no recipe and no loot table; the has-a-source test silently
  dropped 79 of 108 guide items.
- **`items[bare]` must return ALL candidates.** 35 names exist in two mods, and picking
  one arbitrarily resolved `griseous_orb` to the M&L copy (no recipe) instead of the Mega
  Showdown one (craftable), losing the entire chain. Prefer the candidate with a recipe.
- **Never expand vanilla ingredients.** `Brick → smelting → Clay Ball → Clay 50%` is true,
  useless, and exactly the wall of text the rewrite existed to remove. Cutting vanilla
  expansion took the average entry from 1,552 to 921 characters.
- **Drop self-referential loot.** A berry's own block drop renders as
  "Liechi Berry — Liechi Berry — 100%".
- **Deduplicate summon item vs key item.** They are usually the same item (the Tidal Bell
  is both), and rendering it twice with an identical source list is pure noise.
- **A species' gear is wider than its guide's one `item` field.** The Urn of Frost is
  Articuno's and craftable, but Articuno's guide item is the Tidal Bell — so the urn
  recipe only ever appeared on a separate page. Attribute items from several signals:
  key-item spawn conditions, whole-token name matches (`entei_treat` → Entei, token-exact
  so "mew" never claims "mewtwo"), and the urns table, which states `frost → Articuno`
  where the name alone cannot.

### Splicing the template (tools/wiki_uipatch.py)
Patch `wiki_tpl3.html` by **exact anchors, asserted unique**. A regex for "the first
`return` in `dexRow`" put the declaration inside a nested `map()` callback. Anchors also
have to match the real text — `'</details></td></tr>'`, not `'</details>'`.

**Validate the result properly:** the box has `node`, so extract the single script block
and run `node --check`, then `(0,eval)` the DEX literal and the `tut*` functions and
render real entries. Note the payload uses `const DEX=`, and a `const` inside an indirect
eval does not leak to global — rewrite it to `globalThis.DEX=` first.

Result: 92 species carry a full tutorial, ~921 chars each, 83 KB total on a 3.8 MB page.

## 22. Meloetta — both routes, verified in code (2026-08-24)

The guide data knew the Disc of the First Song and its recipe, had an **empty `structs`
list**, and said nothing about the rest of the ritual — so no page on the wiki actually
described how to summon Meloetta.

### Legendary Monuments route (the ritual)
From `MeloettaJukeboxBlock.method_55766`:
1. **Disc of the First Song** = **9× `disc_of_the_first_song_fragment`**, filling the whole
   3×3 grid. Fragments are common in LM chests — Liberty Island 33.9%, Bell Tower 33.7%,
   Lugia Temple 33.3%, Calyrex 27.5%, and Turnback Cave.
2. Find the **Amphitheater**: `#cobblemon:is_desert`, `surface_structures`, spacing 250 /
   separation 150. The template is 43×8×30 and contains **exactly one
   `legendarymonuments:meloetta_jukebox` and four `minecraft:jukebox`** — matching the
   four discs.
3. Load the four ordinary jukeboxes with **Pigstep, 5, Creator and Relic**
   (`class_1802.field_23984 / field_38973 / field_51628 / field_44705`). The mod states it
   itself in the failure string: *"The melodies seem incomplete... You need Pigstep, 5,
   Creator and Relic in nearby jukeboxes."*
   ⚠️ **`music_disc_creator_music_box` is a DIFFERENT vanilla disc** and does not count.
4. Hold the Disc of the First Song and **right-click the Meloetta Jukebox**
   (`getMainHandItem`, `ItemStack.is(DISC_OF_THE_FIRST_SONG)`). It scans **±20 blocks**
   for the four discs — so you can place your own jukeboxes rather than use the
   structure's. On success `emptyJukeboxes` clears all five.

### Myths & Legends route
`mythsandlegends:meloetta_headset`, ultra-rare, level 50, in **Cherry Grove, Flower
Forest, Meadow or Sunflower Plains** (the byg/terralith/wythers biomes in its list do not
exist here). Headset drops from Ancient City 0.63%, trial chambers, End City.

### Two generalisable lessons
- **`_TUT_FIX` in build3.py** now exists for facts verified in mod code that the source
  guide data does not carry. Meloetta's ritual is the first entry. Prefer this to editing
  the built artifact.
- **A tag that expands to biomes already listed individually produced a duplicate.**
  Meloetta rendered *"Cherry Grove, Flower Forest, Meadow, Sunflower Plains, Cherry Grove,
  Flower Forest, Meadow or Sunflower Plains"*. `_relabel_list` now drops any combined
  label whose parts are all already present on their own.

## 23. Mod badges, crafting grids and thumbnails (2026-08-24)

### Tag the mod on every ROUTE, not only on ambiguous names
Mod tagging originally fired only when a bare item name existed in two mods. That misses
the case that matters most: Meloetta's `disc_of_the_first_song` (LM) and `meloetta_headset`
(M&L) are each unique, so neither got tagged and the two routes looked like one. Every
resolved node now carries `m` (its namespace) and every top-level route renders a badge.
Nested ingredients stay bare or the tree becomes noise.

### For a shaped recipe, the LAYOUT is the information
Listing "4x brick, 2x gunpowder, 1x ice stone, 1x netherite scrap" does not tell anyone
where things go. `wikiindex.py` now captures the 3×3 `grid` from the pattern + key, and
the tutorial draws it.

### The page already had thumbnails and the dex never used them
`TEX` ships 2,607 base64 item textures and `paintIcons(root)` fills `.ic[data-i]` from it.
Two traps:
- **`TEX` is keyed by BARE name** (`brick`, not `minecraft:brick`), so nodes need a `b`
  field alongside `i`.
- **`renderDex` never called `paintIcons`.** Icons added to a dex row silently degraded to
  text abbreviations. `renderItems` did call it, which is why the items tab looked fine.

**The upstream harvest only took the flat `assets/<ns>/textures/item/*.png` level.**
Cobblemon nests them — `item/type_gem/dragon_gem.png`, `item/evolution/ice_stone.png`,
`block/evolution/deepslate_ice_stone_ore.png` — so 56 of the 225 thumbnails the tutorials
need were missing. `build3.py` now harvests exactly the referenced gaps by basename,
recovering 42. The remaining 13 (`dry_30`, `spicy_10`, `tier_3_poke_ball_materials`,
`pink_group3`) are recipe **tags**, not items, and correctly fall back to text.

### Source-data typo: `prism_bottle`
Exists in no jar. Hoopa's item is `prison_bottle` (M&L's copy is the obtainable one;
Mega Showdown's is the Unbound form-change item with no sources). The bad id was in
**four** places: guide `item`, the spawn-condition `k`, a pre-baked HTML summary table in
`P['mnl']`, and the JSON payload string.

⚠️ **Unresolved:** normalising `P`/`D2`/`D3` at load time plus the parsed payload fixed
three of the four, and an isolated test of the same function on the same blob fixed it
cleanly — but instrumenting the splice showed `P['mnl']` still carrying the typo at render
time, with no reassignment of `P` anywhere in the file. Cause never established. A
**post-render substitution** now scrubs known-bad ids from the finished HTML as a
guarantee, and prints when it fires. If that message appears, the load-time pass has a
hole worth revisiting.

### Order matters in build3.py
The typo normalisation had to move ahead of every consumer — the key-item summary table
is built early, so a fix applied later left it stale. Same class of bug as the blob sweep:
**normalise source data on load, not partway down the file.**

## 24. Consolidation, and how to build the wiki (2026-08-24)

### The build has an ORDER and it fails silently
`tools/wiki/build-wiki.sh` is the only correct way to build. `wikiindex.py` must run
before `build3.py`: without `/tmp/wiki_recipes.json` the build **still succeeds**, prints
one line about a missing index, and drops every recipe chain. The script enforces the
order and verifies the result.

**Counting tutorials is not a sufficient check** — without the index 79 still attach from
guide data alone, and only the resolved *chains* vanish. The guard counts tutorials with
a resolved recipe/source chain (88 healthy, 0 when the index is absent).

### The template is versioned now
`tools/wiki/wiki_tpl3.html` is the source of truth; `build-wiki.sh` ships it to `/tmp`.
It previously lived only as a mutated file in `/tmp` on the server, so any regeneration
would have silently erased every UI change. `wiki_tpl3.base.html` is the pre-tutorial
original. **Edit the template directly — do not re-run the one-shot patch scripts
against it.**

### Prove parity before hiding anything
`scratch/parity.py` checks every guide's item against every item reachable from any dex
entry at any chain depth. The first run found **20 orphans** — content that would have
been lost. Improving `_mon_of` to match a species anywhere in the title (not only as a
prefix) fixed three; the remaining 17 are genuinely cross-cutting prerequisites (Red
Chain, Arc Phone, Origin Ingot) that no single species chain reaches.

Result: 91 of 108 guides marked `covered` and hidden with a toggle, 17 left visible, and
the Legendaries and Mythicals tabs retired via `data-retired` — **hidden, not deleted**,
the sections remain in the file.

### Species with no route at all
Nine legendaries/mythicals had nothing. The Mythicals page already held the answers; they
had simply never reached the dex. Now in `_TUT_FIX`:
- **Melmetal / Meltan** — evolve with 64 Meltan Candy; Meltan spawns with no key item
- **Manaphy, Phione, Okidogi, Munkidori, Fezandipiti** — *not obtainable on this server*:
  no spawn entry, no key item in any installed jar. Saying so is the useful answer.
- **Silvally, Urshifu, Cosmoem** — evolution-only
- **Articuno/Zapdos/Moltres** — the urn mechanic, including the Galarian trap (different
  type than you would guess, 50 → 75, progress resets)

⚠️ `cobblemonresearchtasks:species/<mon>.json` exists for **all 1,027 species**. Those are
rewards *for registering* a species, **not** a way to obtain one. Do not mistake them for
a route.

### A mod bug, and how a "typo fix" masked it
M&L's Hoopa spawn pool declares `key_item: mythsandlegends:prism_bottle` while the item it
ships is `prison_bottle`. **That route can never fire.** v20 rewrote the id, which made the
wiki promise a route the game cannot satisfy. **Never normalise a mod's own declaration** —
correct the wiki's copy of an item id, but leave spawn conditions alone and document the
breakage. Hoopa's entry now says to use the Hoopa Ring or the pedestal.

The explanation had to entity-encode the id (`pris&#109;_bottle`), because the post-render
scrub rewrote it into "declares prison_bottle but ships prison_bottle". Blunt string
substitution over finished HTML will eat prose that talks *about* the string.

### Versioning
Restarted at **v20** and increments from there. The old sequence had gone v19 → v12 → v15.

## 25. Client-side packs, and three route corrections (2026-08-24)

### CCCwLegendSpawns_2.1 — the pack that is not in this repo
Lives in the owner's Downloads and is hand-added to the client update zip. **It is the
only thing supplying models for the seven "modelless" Pokémon** — Raikou, Suicune,
Heatran, Cresselia, Virizion, Yveltal, Zeraora. Verified: Cobblemon ships 1,124 Pokémon
models and none of the seven is among them; no server mod has them either.

Now bundled into `client/cobblemon-client-COMPLETE-v2.zip` at
`resourcepacks/CCCwLegendSpawns_2.1.zip`, with a `READ-ME-MODELS.txt`.

⚠️ **It is client-side ONLY.** The pack also carries **221 spawn-pool files**, and those
do **not** apply — it is not in `mods/` or `world/datapacks/`. Server data governs spawns.
Do not read its spawn data as authoritative for this server.

**Lesson:** when checking "does X exist", server jars + this repo is not the whole world.
Client-side packs the players install by hand are invisible from here — ask.

### Searching for models: check under `/pokemon/`
`legendarymonuments` has `raikou_pedestal.json` and `yveltal_cocoon.json` **block** models,
and M&L has `zeraoras_thunderclaw.json`. Matching on "species name + /models/" produces a
confident false positive. The test is `/pokemon/models/<num>_<name>/*.geo.json`.

### Held items are NOT in chunk NBT
A full 2.7-million-chunk world scan found one bottle in a chest and **missed** the one
that mattered, because party and PC Pokémon live in `world/pokemon/pcstore/` and
`playerpartystore/` as gzipped NBT — not in region files. Scan those too:
`gzip.decompress`, then walk for `HeldItem`.

Result here: a player's **Hoopa holds `mythsandlegends:prison_bottle`** (the working
one). The chest at `1687 65 -458` holds `mega_showdown:prison_bottle` (inert).

### Zygarde — both mods' items are usable, for different things
- **Myths & Legends:** cells + cores fill the M&L Zygarde Cube (a bundle item). **95 cells
  + 5 cores** is the key item for the Zygarde-100% spawn — level 70, forest / jungle /
  mangrove swamp / cave / swamp. Cells ~19% and cores ~3% from Ancient City.
- **Mega Showdown:** a *crafted* cube (black apricorn + green apricorn + netherite ingot)
  opens a GUI (`ZygardeSlots`) that accepts **Mega Showdown** cells and cores and switches
  Zygarde between 10% / 50% / Complete / Power Construct.
- **The two do not mix** — each cube accepts only its own mod's items, and the icons are
  nearly identical.

### Genesect has two routes
- **No item:** it is in the dripstone-cave ultra-rare pool at weight 5.0 (§18).
- **Key item:** `mythsandlegends:genesect_drive`, level 70, **Deep Dark or any End biome**
  — not dripstone. Ancient City 0.63%.
- **Dome Fossil + Dubious Disk does not work here.** No such recipe in any installed mod.

### 37 Legendary Monuments quests are stubs
`QuestCatalog` holds 37 `"Work in Progress..."` descriptions, not one. Includes Kyogre,
Groudon, Rayquaza, Jirachi, Deoxys, Shaymin, the weather trio, Genesect, Zygarde, Diancie,
Volcanion, Type: Null, Silvally, all four Tapus, Necrozma, Magearna, Zeraora, Kubfu,
Urshifu, Zarude, Enamorus, Koraidon, Miraidon, the Loyal Three, Ogerpon, Terapagos,
Pecharunt. Most have another route — check the dex entry before burning a key item.

## 26. Reading data out of mods — techniques that worked (2026-08-24)

### Resolving intermediary names (`class_1802.field_47315`)
Mod code references vanilla items by intermediary field id. To resolve without guessing:
disassemble `net/minecraft/class_1802` (Items) or `class_2246` (Blocks) from
`.fabric/remappedJars/minecraft-<ver>-<loader>/server-intermediary.jar`, then walk
`<clinit>` pairing each `ldc "<id>"` with the next `putstatic class_1802.field_N`.
Block-items register from a `Blocks` reference with no string, so resolve those against
the Blocks class the same way.

⚠️ **Always sanity-check against something you can verify in the bytecode, not memory.**
I asserted `field_8687` was `diamond`; it is **emerald** (diamond is `field_8477`). The
check caught my bad assumption, not a bad method.

### Java string-switch order
A switch on strings lists the cases in hashCode order but the branches in source order,
so pairing "Nth string" with "Nth item" is **not guaranteed**. It happened to hold for
`getRequiredItemFor`, and I only trusted it after **fourteen** unambiguous semantic
matches (Ecruteak→Clear Bell, Snowpoint→Golem Scrap, Spear Pillar→Red Chain,
Dyna Tree→Cherry Sapling, Amphitheater→Disc of the First Song, Liberty Island→Liberty
Pass, four shrines→their own Seals). Confirm before relying on positional pairing.

### Custom recipe types
`parse_recipe` must not assume vanilla shapes. **CobbleFurnies** uses
`cobblefurnies:furni_crafting` with a **`materials`** field instead of `ingredients` —
348 of its 367 recipes. Skipping it left the furniture page with an empty ingredient list
for everything. Also: strip `minecraft:` from the type only, or foreign namespaced types
stop matching.

## 27. Arc Phone structure tracking (2026-08-24)

`LegendaryTrackingServerHandler.getRequiredItemFor` maps structure → the item you must
**carry** before the Arc Phone will locate it. 28 mappings:

| Structure | Carry | Structure | Carry |
|---|---|---|---|
| dragonspiraltower | Lightstone Shard | yveltal_cocoon | Soul Jar |
| turnback_cave | Trial Key | tree_of_life | Aurora Essence Jar |
| traditional_village (Ecruteak) | Clear Bell | amphitheater | Disc of the First Song |
| heatran_cave | Magma Stone | kyuremcave | Ideals Bottle |
| firescourge / grasswither / groundblight / icerend shrine | its own Seal | dyna_tree | Cherry Sapling |
| outskirt_stand | Emerald | giratina_island | Origin Ingot |
| southern_island | Axolotl Bucket | final_island | Old Sea Map |
| lugia_temple | Vortex Stone | snowpoint_temple | Golem Scrap |
| hoopa_pyramid | End Rod | spear_pillar | Red Chain |
| eternatus_cocoon | Galar Particle | lake_valor / acuity / verity | Fermented Spider Eye / Sweet Berries / Glow Berries |
| crown_shrine | Iceroot **or** Shaderoot Carrot Seeds | liberty_island | Liberty Pass |
| throneroom_of_knightly_heroes | Totem of Undying | | |

## 28. RCT trainer series (2026-08-24)

Three series: **radicalred** (Kanto), **bdsp** (Sinnoh), **unbound**. The walkthrough data
lives in `data/rctmod/mobs/trainers/single/*.json`, **not** in `series/*.json` (which is
only metadata) or `trainers/*.json` (which is team data):
- **`signatureItem`** — what goes in the Trainer Spawner (Gardenia = `minecraft:sunflower`,
  Cedric = `cobblemon:everstone`, Maylene = `cobblemon:black_belt`)
- **`requiredDefeats`** — the dependency graph; topologically sort it for the order
- **`optional: true`** — side trainers, not on the path. Filter them or the list triples.
- RCT ships **one mob file per encounter**, so Cedric is 12 rows and Rival Wayne 6.
  Collapse consecutive identical entries into "beat N times".

Required-path lengths: Kanto 27, Sinnoh 25, Unbound 30.
`tools/wiki/wikitrainers.py` builds `/tmp/wiki_trainers.json`.

## 29. Chipped has SEVEN workbenches

mason_table, carpenters_table, **glassblower**, loom_table, alchemy_bench,
botanist_workbench, tinkering_table. Each ships a `chipped:workbench` recipe whose
`ingredients` tags declare exactly what it accepts — read the split, do not guess it.
Searching block *model* names for "table|bench" misses `glassblower`; count the recipe
files instead.

---

## §30 Resource pack order is load-bearing, and one pack was missing

**Verified 2026-08-24 against a working client, not from memory.**

Three packs matter and they overwrite each other. `cobblemon-2seats` and
`CCCwLegendSpawns_2.1` share **113 model files, and all 113 differ** — so load order
silently decides what renders. Nothing errors when it is wrong; the second seat just
stops being drawn.

**Priority, highest first:**

1. `cobblemon-2seats-resourcepack.zip` — must win all 113 shared files
2. `CCC-seat-patch.zip` — must sit above CCC
3. `CCCwLegendSpawns_2.1.zip`

Why 2-seats wins and not CCC: the seven Pokémon CCC exists to fix (Raikou, Suicune,
Heatran, Cresselia, Virizion, Yveltal, Zeraora) have **zero collisions** with the seat
pack — checked explicitly. So putting seats on top costs nothing and keeps the passenger
seat on Charizard, Kyogre, Latios, Salamence, Aerodactyl and the legendary birds.

### The direction of "order" — two independent confirmations

- `options.txt` lists **lowest priority first**; the last entry wins.
- The in-game list shows **highest priority at the top**.

Confirmed by: the live client has `cobblemon-2seats` last in `options.txt` (and it must
win), and `patch-ccc-seats.py` says to enable its output "ABOVE CCC" while `options.txt`
has it *after* CCC. Two sources, same conclusion. Do not restate this from memory —
`options.txt` is unambiguous, quote that.

### CCC-seat-patch is now in the client package (2026-08-24)

The owner ran the script and distributed their copy, so it ships in the package rather
than each person generating one. It is **version-locked to the CCC beside it** — swap CCC
and the patch must be regenerated.

Originally it was missing, which meant:

**252 CCC models ship with no `seat_1` locator.** You mount, the Pokémon runs off, your
camera stays behind. Affected: Kubfu, Urshifu (all forms), Ogerpon (all forms), Galarian
Zapdos, Hoopa, Meloetta, Calyrex, Dialga Origin, Terapagos, every Mega and Gigantamax.

`patch-ccc-seats.py` (repo root) generates the fix from the local CCC copy. Its own header
says to run it per machine rather than pass the output around. The client package bundles
CCC but **not** the patch, so everyone who installed it has 252 unrideable forms.

## §32 Cloudflare will serve a replaced download stale for a full day

Proven, not assumed. After replacing the client package on disk:

    /dl/cobblemon-client-package.zip              -> 207,627,488 bytes, cf-cache-status: HIT
    /dl/cobblemon-client-package.zip?v=b39f3ed0   -> 208,178,757 bytes, cf-cache-status: MISS

The `Cache-Control: public, max-age=86400` set on `/dl/` is what makes the edge hold it.
So **every download link the wiki emits carries `?v=<first 8 of sha256>`**, which changes
with the bytes and is therefore never stale by construction. `wikiclientpkg.py` computes
it, `build3.py` appends it. A bare `/dl/` URL handed out after an update serves the old
file until the TTL expires — do not paste bare URLs into chat.

Related: `/tmp/wiki_clientpkg.json` used to be hand-written, which is how the page came to
advertise a LinguaChat build the package did not contain. It is now generated from the
served package by `wikiclientpkg.py`, run as step 0 of `build-wiki.sh`.

## §33 Loot tables are not all places you can go

`/tmp/wiki_recipes.json` maps item → loot table, but a third of those tables are
**plumbing**, not destinations:

- `bca:item_groups/*` — 89 tables, 923 references. Cobblemon Additions' item pools.
  Referenced by `bca:support_tables/*`, which real chest tables then reference.
- `*/support_tables/*` — the middle layer.
- `cobblemon:sets/*` — 9 pools, referenced by the ruins and villages tables.

**Their percentages are chances within the pool**, so printing one as a source produced
"Ability Items — 90.9%", which is both meaningless and wrong. `_POOL` in `build3.py`
filters them out. Everything else is classified by table shape in `_classify()`: chests,
`rctmod:generic/<tier>` trainer drops, `fossils/<rarity>`, `ruins/<rarity>`, archaeology,
entity drops, gameplay tables, and block drops (a block dropping *itself* at 100% is
suppressed — it is noise).

Two naming traps: `legendarymonuments:chests/turnback_cave_chest` already ends in "chest",
so appending the word gives "Turnback Cave Chest chest"; and RCT ships one tier across
several categories (`generic/epic/pokeballs`, `generic/epic/archeology`), which prints the
same label twice at two rates unless you dedupe on tier and keep the best.

## §34 Mod item icons: most items are blocks, and one texture cost 1.3 MB

Only 911 of 2,609 items had a texture named after them. The rest are **blocks**, whose
icon resolves through the model chain:

    models/item/acacia_cabinet.json  ->  parent cobblefurnies:block/cabinet/acacia_closed_left
                                     ->  that model's "textures" map  ->  the png

Following that (up to 4 parents deep, skipping `particle` unless it is all there is) took
coverage to **97%**. `#`-prefixed texture values are references to another key in the same
map, not paths — skip them.

**Cap what you embed.** Unfiltered, this took the page from 4.0 MB to 7.0 MB, because
`temple_lock` is 1024×1024 and cost **1.3 MB of base64 on its own** to render a 15px
icon. A 2,500-character cap on the base64 keeps 4,278 textures for 2.3 MB and costs only
~130 decorative blocks their icon, which fall back to a text abbreviation. Pillow is
**not** installed on the VPS, so downscaling is not an option — capping is.

## §35 The client package must be diffed against a working client, not assembled by hand

The hand-built package was **7 mods short**, including `EasyShulkerBoxes` and its
`PuzzlesLib` dependency — both `environment: *`, and both installed on the **server**.
The Mods page claimed "client needed: no" for them, but that column was computed from
*membership in the package*, which made it circular: it could only ever confirm itself.

Read `fabric.mod.json` from each jar for the truth. Of 41 server mods, 40 declare `*` and
only LuckPerms declares `server`. Of the owner's 40 client mods, five declare `client`
(sodium, iris, continuity, entity_model_features, entity_texture_features).

**The owner's own mods folder is the ground truth** — four people play with it. The
package is now built directly from it, and every jar is byte-identical.

Two traps when reading these jars:

- `mega_showdown`'s `fabric.mod.json` contains a **raw control character** and
  `json.loads` / `ConvertFrom-Json` both reject it. Use a regex for `"id"`.
- **The same mod under two filenames crashes Fabric on startup.** This was nearly
  shipped: the owner runs `linguachat-1.21.1-2.0.0-FIXED.jar` while the package carried
  `linguachat-1.21.1-2.0.0.jar`, and the installer copies rather than replaces — so both
  would have landed in `mods/`. The installer now identifies what is already installed by
  the **mod id inside the jar** and removes older copies of exactly the mods it ships,
  leaving anything the user added alone.

## §36 The legendaries guide invented sources for 43 items

Retired 2026-08-24. Whenever it had no recipe and no loot data, it printed:

> No recipe - this is found in the world (structure loot, a pedestal you interact with,
> or dropped by a mechanic)

That is a guess rendered as a fact, and it appeared **43 times**, including on Cobalion
and Virizion Footprints (world-generated features you walk over, not loot) and on **Origin
Glass**.

**Origin Glass cannot be obtained in survival.** No recipe, no loot table, no trade — it is
one of 66 Legendary Monuments blocks with no drop table, all of them
monument furniture (pedestals, locks, shrines, stakes, footprints, cocoons). It exists
only as the material the Hall of Origin is built from. Creative mode or `/give` is the only
way to hold one, and it is not a step in the Arceus route.

**Correction (same day):** I first wrote that it is "not in any creative tab". That was
wrong — the owner built a gym out of it in creative. The mod registers
`legendary_monuments_group` in **`ModItemsTab.class`**, populated from its own registry, so
every LM block is there. I had searched for class names containing `ItemGroup`/`CreativeTab`
rather than for the API being used (`class_1761` / `method_47324`). **Search for the API,
not for a naming convention.**

**Never emit a source you did not read from mod data.** Print nothing instead.

### What was actually true on that page

The Pokédex had every Myths & Legends route but almost none of the **Legendary Monuments
pedestal** routes. Recovered from the mods' own tooltips and recipes:

- **Red Chain** = shapeless(Uxie's Claw + Azelf's Fang + Mesprit's Plume). Tooltip: *"Used
  to summon Palkia and Dialga at the Spear Pillar and to craft Ancient Origin Balls"*, and
  *"Can be fixed with origin ingots found in the Distortion World"*. Origin Ingot smelts
  from Raw Origin, which smelts from Distortion Origin Ore; one also drops in the Turnback
  Cave vault at 0.93%.
- **Proof of Conquest (U/M/A)** — tooltip *"Right-click to summon Uxie/Mesprit/Azelf"*.
  No recipe, no loot: earned from the Lake Guardian Trial.
- **Rainbow Feather** = shapeless(red + blue + yellow feather), summons Ho-Oh.

Cobalion, Terrakion, Virizion, Keldeo and Cosmog were **already fully covered** by the dex.

**The guides data must stay even though the tab is retired** — `build3.py` builds all 104
dex tutorials by iterating `guides`, so deleting it would empty the Pokédex.

## §37 "Needs X nearby" is a 4-block gate, and it is measured from the spawn

`neededNearbyBlocks` reads like flavour text. It is a hard requirement with a radius that
comes from **server config**, not from the spawn file:

    config/cobblemon/main.json
      "maxNearbyBlocksHorizontalRange": 4
      "maxNearbyBlocksVerticalRange": 2

Traced through `GroundedSpawnablePositionCalculator` → `AreaSpawnablePositionCalculator.
getNearbyBlocks$default`, whose Kotlin default-argument path reads both values off
`CobblemonConfig`. **Watch the bytecode carefully here:** the `bipush 40` in that method
feeds `getHeight`, and the `bipush 6` next to the call is Kotlin's *default-argument
bitmask* (0b110 = both radii defaulted), not a radius. Reading either as the answer gives
a wrong number.

The radius is measured **from the spawn position, not from the player**. Spawns roll
16–40 blocks away, so a single block placed out in the world is almost never within 4 of
whatever spot the game picks — a dense patch is what works. 453 conditions across the dex
carry this gate.

### Pumpkaboo, the worked example

Two spawn entries ship:

- `pumpkaboo-1` — common, weight 5.7, level 9–34, `#cobblemon:is_overworld` (the 55-biome
  tag), **`timeRange: night`**, **`neededNearbyBlocks: [pumpkin, carved_pumpkin]`**.
- `pumpkaboo-2` — uncommon, weight 9.2, `#cobblemon:nether/is_overgrowth`. **Dead on this
  server**: that tag lists only BetterNether, Biomes O' Plenty and BYG biomes, none of
  which are installed.

Both use `presets: ["natural"]`, and that preset is the sting:

```json
{"condition":  {"neededBaseBlocks": ["#cobblemon:natural"]},
 "anticondition": {"neededBaseBlocks": ["minecraft:farmland"]}}
```

**Farmland is explicitly excluded.** A tilled pumpkin farm blocks the exact spawn it is
farming for. Carving is not required — plain `minecraft:pumpkin` satisfies the check.

So the answer to "why have we never seen one": the biome line says any of 55 overworld
biomes, which is true and useless; the real gate is night + a pumpkin within 4 blocks of
wherever the game happens to roll + natural, untilled ground.

## §38 Sky light and light level are different numbers

This decides whether you can torch a cave without ruining a hunt, and the spawn files use
two separate fields:

| field | entries | torches affect it? |
|---|---|---|
| `minSkyLight` / `maxSkyLight` | **2,023** | **no** — sky light is daylight reaching the spot |
| `minLight` / `maxLight` | **14** | **yes** |

So for practically everything, **light it up freely**. The only spawns that care about
torch light:

- **Gastly, Haunter, Gengar** — `maxLight: 0`. A single torch stops them.
- **Misdreavus, Mismagius, Morelull, Shiinotic** — `maxLight: 7`.
- **Zekrom** — `maxLight: 7`. **Reshiram** is the opposite: `minLight: 8`, it wants bright.

Nothing in the dripstone-cave pool checks torch light, which is why lighting one up for a
Genesect hunt costs nothing.

When labelling these on a page, check whether the same spawn *also* has a light-level
rule before telling anyone torches are safe — Gengar has both a sky-light and a light-level
condition, and printing "torches are fine" beside "torches break this" is worse than
printing neither.

## §39 A spawn needs clear room the size of the Pokémon

`PokemonSpawnDetail.autoLabel()` sets the spawn's required height and width to
`ceil(hitbox * baseScale)`. If the room is not there, the spawn silently never happens —
no message, it just never appears.

- **Rayquaza: 5 wide × 8 tall.** That is why it will not show up in dense jungle until you
  cut a hole. It has **no Y / height condition at all** — altitude is irrelevant, space is
  not.
- Wailord wants 8 × 6, Regigigas 4 × 7, Arceus 4 × 5.
- 69 of 973 species are big enough for this to matter; the rest fit anywhere a player does.

**Two mods can define the same species at the same path.** Cobblemon gives Rayquaza
hitbox 2.5 × 3.8 at baseScale 1.5 (→ 4 × 6); Mega Showdown overrides
`data/cobblemon/species/generation3/rayquaza.json` with 5 × 8 at scale 1. Which wins
depends on mod load order, so the index keeps the **larger** — clearing more space is never
wrong.

## §40 Recipe ingredients are frequently tags, and one is a lie

134 distinct tags appear as recipe ingredients. Rendering the tag's own name as if it were
an item produced **"Pokédex Screen"**, which cannot be crafted and does not exist. It is
`#cobblemon:pokedex_screen`, a tag of five substitutes: redstone, glowstone dust, blaze
powder, glow ink sac, Bright Powder. **Redstone is the cheapest and is what the owner
uses**, so that is what the Arc Phone recipe draws.

Three traps when indexing tags:

1. **Tags nest.** `#cobblemon:tier_3_poke_ball_materials` contains only `#c:ingots/gold`.
   Resolve recursively or you get an empty list.
2. **The conventional `#c:` tags live in nested JARs.** Fabric API ships its modules inside
   `META-INF/jars/*.jar`, so a plain walk over `mods/*.jar` finds 709 tags; descending into
   the nested ones finds **946**, and only then does `#c:ingots/gold` resolve.
3. **Guide chain data stores tags with the `#` stripped**, so `pokedex_screen` arrives
   looking like an item id. Map bare paths back to tags, but only when no real item of that
   name exists.

## §41 Every Legendary Monuments pedestal consumes an item

The wiki generated the line *"This route needs no key item and no biome luck"* for any
pedestal route it found. That was invented, and wrong for **all eight** — it sent players
to the Burned Tower to stand in front of a pedestal that does nothing.

Read each `*PedestalBlockEntity` class for the item it validates before spawning:

| pedestal | needs |
|---|---|
| Entei / Raikou / Suicune | the matching **Treat** (and gives a red / yellow / blue feather) |
| Latias / Latios | the matching **Treat** |
| Ho-Oh | **Rainbow Feather** |
| Heatran | Magma Stone |
| Dialga / Palkia | Red Chain |
| Giratina | Griseous Orb |
| Kyurem | Truth Bottle + Ideals Bottle |
| Reshiram / Zekrom | Lightstone / Darkstone |
| Zacian / Zamazenta | **Hero Sword / Hero Shield + Totem of Undying** |
| Hoopa | Prison Bottle + Temple Key |
| Lugia | Lugia Key or Vortex Stone |
| Mew | Old Sea Map or Tuft of Mew Hair |

**`field_8162` is `air`** — the first item registered in `class_1802.<clinit>`, from
`Blocks.AIR`. It shows up in these classes as an emptiness check, **not** an ingredient.
`field_8288` is `totem_of_undying`; `field_8687` is `emerald`; `field_8477` is `diamond`.

### The Burned Tower chain

Confirmed by the owner in play and by the bytecode: a Treat goes **in**, a coloured feather
comes **out**. Red from Entei, blue from Suicune, yellow from Raikou → shapeless-craft the
**Rainbow Feather** → Ho-Oh at the **top floor of the Bell Tower**. Ho-Oh is the end of
that chain, not a separate hunt.

Every Treat needs a **PokéTreat Box**, which has no recipe and no loot table.

## §42 The Entrepreneur's stock is in code, and level-gated

`ModVillagersImpl.registerTrades` registers five profession levels, each its own lambda
group. Only two of these trades are declared as JSON, which is why the index found two.
**He must be levelled up** — this is why the PokéTreat Box looks unobtainable to anyone
who only ever met a Novice.

| level | sells | cost | uses |
|---|---|---|---|
| 1 Novice | relic coins, XS exp candy (buys Galar Particles) | 1 emerald | 30 |
| 2 Apprentice | **PokéTreat Box** | 32 emeralds + 32 relic coins | 5 |
| 3 Journeyman | **Firescourge / Icerend / Grasswither / Groundblight Seal** | 40 emeralds + 48 relic coins | 1 |
| 4 Expert | Lightstone Shard, Darkstone Shard | 32 emeralds + 16 relic coin pouches | 3 |
| 5 Master | Celestica Flute; Silver Wing | 64 / 60 emeralds + 64 relic coins | 1 |

## §43 The four Nether shrines have no summon item

Chien-Pao, Chi-Yu, Wo-Chien and Ting-Lu are **not** summoned by an item, and the seal the
Entrepreneur sells is the trap: it is **Arc Phone tracking only**, never used on the shrine
and never consumed.

`ShrineBlock.method_55766` calls `ShrineTracker.getProgress(player, type)` and compares
against **8**. Stakes are collected by **right-clicking them where they stand** —
`StakeBlock.method_55766` does `getProgress + 1 → setProgress` — so they are a per-player
counter, like the Swords of Justice footprints, not inventory items.

**Correction (2026-08-24).** I first wrote that the stakes are "not spent" and that the
counter "resets to zero". Both wrong, and the owner caught it in play:

- the bytecode is `bipush 8; isub` → `setProgress(progress - 8)`. It **subtracts 8**. So 8
  *are* spent, and the counter **accumulates past 8** — 12/8 is a normal thing to see.
- `destroyNearbyShrines(world, pos, 10)` and `destroyNearbyBedrock(..., 10)` run on a
  successful summon: **the shrine is destroyed**, one use per shrine for everybody.

Read the whole handler, not the first call that looks like the answer.

Shrine → species, from the enum's `<clinit>` (do not infer from typing alone, though it
happens to agree):

    FIRESCOURGE -> chiyu      GRASSWITHER  -> wochien
    ICEREND     -> chienpao   GROUNDBLIGHT -> tinglu

## §44 Okidogi, Munkidori and Fezandipiti really are unobtainable

Checked a fourth time, now including nested JARs. Across every installed mod they have
**only** a species file, a dex entry and sounds. No spawn pool, no key item, no evolution,
no trade.

Two near-misses worth recording so nobody re-checks them:

- `data/cobblemon/pokemon_interactions/fezandipiti.json` is a **brush-for-feathers**
  interaction. 130 other species have an equivalent file; it is not an obtain route.
- `cobblemonresearchtasks/rewards/species/okidogi.json` is what you are **paid for**
  researching one, not a way to get one.

Pecharunt, by contrast, **is** obtainable: M&L key item `mythical_pecha_berry`, ultra-rare
at level 70 in dark forest / swamp, or woodland mansion / swamp hut / pillager outpost.

## §45 Eternatus: 500 loose Galar Particles, banked in the cocoon

`EternatusCocoonBlockEntity.consumeGalarParticles` scans the player inventory for
`ModItems.GALAR_PARTICLE`, takes up to `500 - particlesConsumed`, and stores the running
total in block NBT. So:

- **500 particles**, not 50 — but a **Galar Particle Block is 9 particles**, so the owner's
  "50 galar blocks or something" was right: it is ~56 blocks' worth.
- **Progress persists in the cocoon**, so it can be fed over many trips. At 500 it says
  *"The cocoon is ready to break"*.
- It reads **loose particles only**. Blocks in your inventory are ignored — unpack first.
- Particles come from Galar Particle Ore / its deepslate form at ~50% a block.
- Tracking: hold a **Galar Particle** and the Arc Phone points at the nearest cocoon
  (`ARC_TRACK` already had `eternatus_cocoon → Galar Particle`; the dex entry did not).

## §46 Form-change items are the least discoverable thing in the pack

An item sitting in a chest can change a Pokémon's model and its battling, and nothing in
game says which item or which Pokémon. Three data sources, all indexed by species:

| source | count | what it gives |
|---|---|---|
| `mega_showdown/mega/*.json` | 81 | species → its mega stone |
| `mega_showdown/battle_form/*.json` | 52 | alternate forms (Aegislash stance, Arceus plates, Greninja Ash…) |
| `cobblemon/pokemon_interactions/*.json` | 137 | right-click-with-item effects |

**The battle_form files do not encode what gates a form.** Greninja's Ash form needs an
**Ash Cap** (5 red + 2 white + 1 green wool) and nothing in that JSON says so — I first
wrote "these switch on their own", which is wrong. Say the forms exist and that some need
an accessory; do not claim a mechanism the data does not carry.

`pokemon_interactions` requirements use item **tags** (`#c:tools/shear`), so pass the tag
to the resolver intact — stripping the `#` was what produced the label "Tools/Shear".

### The accessory chain, none of it documented in game

    Keystone Ore  --50%->  Keystone  ---+ 5 iron + diamond + 2 white apricorn -->  Mega Bracelet  (you wear)
    Mega Crystal  --50%->  raw Mega Stone  --+ 2 iron + diamond + species token -->  Gengarite etc  (Pokemon holds)

Both are needed at once — the mod's own messages are *"No mega bracelet"* and *"Don't have
the correct stone"*. Also craftable: **Dynamax Band** (3 pink + 3 blue apricorn + 2 iron +
Wishing Star), **Tera Orb**, **Z-Ring**.

### Zacian and Zamazenta drop a *different* sword

The **Hero Sword / Hero Shield** (from the loot rooms under the Throneroom of Knightly
Heroes, blue side and red side) plus a **Totem of Undying** summons them. Summoning then
drops a **Rusted** Sword / Shield, which is what changes the caught Pokémon into its
**Crowned** form. Mega Showdown's Rusted versions are craftable (iron sword / shield +
netherite scrap + fire charge), so binning one is recoverable.

## §47 Which structure belongs to which Pokémon — derive it, don't trust the guides

Nothing in the pack states this, and the guide data is incomplete: **Zacian had a route
line and Zamazenta had none**, purely because `whereOwn` was filled in for one guide and
not the other. Anything built on that text inherits the hole.

Derive it from the structures instead. Each `data/legendarymonuments/structure/<name>/*.nbt`
contains the pedestal / shrine / cocoon / lock blocks that name their species, so scanning
the palettes gives **24 structures mapped** and both directions of the relationship.

Notable pairings that are not guessable: `southern_island` → Latias **and** Latios,
`throneroom_of_knightly_heroes` → Zacian **and** Zamazenta, `crown_shrine` → Glastrier and
Spectrier, `dragonspiraltower` → Reshiram and Zekrom, `amphitheater` → Meloetta,
`final_island` → Mew, `thalic_camp` → the Swords of Justice footprints.

**Two build traps hit while doing this:**

- Reading a file with `io.open(p, "rb")` and writing it back with text-mode `write()` turns
  every `\r\n` into `\r\r\n`. The file still *parses* and still runs, but every
  multi-line string match against it silently fails afterwards. Always round-trip with
  `newline=""`, and repair with `b"\r\r\n" -> b"\n"` if it happens.
- `except Exception: continue` around `zipfile.ZipFile(...)` in a scan that runs *after*
  several other jar-walking passes will swallow the real error. Print it.

## §48 Mega, Dynamax, Gigantamax and Z — what actually differs

The accessory **slot tags** are the authority, and they answer the "is the Mega Bracelet
my only option" question outright:

| slot | items that fit |
|---|---|
| `mega_slot` | Mega Bracelet, **Omni Ring** |
| `dynamax_slot` | Dynamax Band, **Omni Ring** |
| `tera_slot` | Tera Orb, Liko's Pendant, **Omni Ring** |
| `z_slot` | Z-Ring, **Omni Ring** |

**The Omni Ring fits all four.** There are also a dozen cosmetic mega accessories (Lysandre's
Ring, May's Bracelet, Maxie's Glasses, Archie's Anchor, Brendan's Mega Cuff, Mega Ring).

The three systems are not the same thing:

- **Mega** — per species. **81** have a stone, and the stone is species-specific, so
  crafting one commits the materials to that Pokémon. Needs the stone *held* and a
  bracelet/ring *worn*.
- **Dynamax** — **not** per species. The Band works on anything.
- **Gigantamax** — the shape change while Dynamaxed, and only **24** species have one:
  alcremie, blastoise, butterfree, charizard, cinderace, coalossal, copperajah,
  corviknight, drednaw, duraludon, eevee, garbodor, gengar, machamp, melmetal, meowth,
  orbeetle, pikachu, rillaboom, sandaconda, snorlax, toxtricity, urshifu, venusaur.

Base Cobblemon only ships Gigantamax **textures** for Pikachu and Eevee — the other 22
come from Mega Showdown's own assets.

## §49 Server icon and wiki branding

**The server icon is `server-icon.png`, exactly 64×64, in the server root.** Minecraft
reads it **at startup only**, so it needs a restart. Sources are kept in `brand/`.

Verify it the way the multiplayer list does — a server-list ping returns the icon as
base64 in the status JSON:

```python
hs = b"\x00" + varint(770) + varint(len(host)) + host + struct.pack(">H", 25565) + varint(1)
sock.sendall(varint(len(hs)) + hs); sock.sendall(varint(1) + b"\x00")
```

The bytes will **not** match the file — Minecraft re-encodes the PNG — so compare the
decoded pixels instead. Ours came back pixel-identical.

### Matching artwork to the page

The wiki's palette, for anyone making assets:

| token | dark | light |
|---|---|---|
| background | **`#0f1115`** | `#f7f8fa` |
| card / panel | `#171a21` | `#ffffff` |
| border | `#252a34` | `#e3e6ea` |
| accent | `#7ec699` | `#1a7f4b` |

A banner drawn on **pure black** does not need re-exporting to match: **screen-blend it
with the page colour**. `255 - (255-src)(255-bg)/255` maps black exactly onto `#0f1115`
and leaves white at white, so the artwork and glow are untouched. Do it with a per-channel
LUT via `Image.point`, then mask the edges with a CSS gradient so JPEG noise cannot show a
seam either.

Put the banner **above** the sticky header, not inside it — inside, it permanently eats
the viewport; above, it scrolls away and the nav still sticks.

Pillow is not installed by default on either machine. `python3 -m pip install --user
Pillow` works locally; plain `pip` resolves to a different interpreter on this box and
silently installs somewhere the scripts cannot see.

## §50 Fossil revival — a whole route the Pokédex was missing

`data/cobblemon/fossils/*.json` holds **15** revival recipes. Four of them have **no spawn
pool anywhere in the pack**, so those entries were completely blank before.

| Pokémon | fossils |
|---|---|
| Dracozolt | Fossilized **Bird** + Fossilized **Drake** |
| Arctozolt | Fossilized **Dino** + Fossilized **Bird** |
| Dracovish | Fossilized **Fish** + Fossilized **Drake** |
| Arctovish | Fossilized **Fish** + Fossilized **Dino** |

Bird and Dino are the **top** halves, Drake and Fish the **bottom** — the pairing is what
picks the Pokémon. The other 11 (Aerodactyl, Amaura, Anorith, Archen, …) take one fossil.

Fossils drop from brushing: `galar_top_fossils` / `galar_bottom_fossils` at 50%. The
machine is a **Fossil Analyzer** + **Restoration Tank** + **Monitor**, all craftable.

## §51 26 species genuinely have no way in

After the fossil pass, 26 entries still had no spawn pool, no key item, no evolution and no
fossil recipe in any installed jar: the whole **Paradox** line (Great Tusk, Iron Valiant,
Roaring Moon, Walking Wake, Gouging Fire, Raging Bolt, Iron Leaves, Iron Boulder and the
rest), the Ultra Beasts **Pheromosa, Celesteela, Guzzlord**, and oddly a few ordinary ones
— **Zangoose, Seviper, Oranguru, Passimian, Indeedee, Bombirdier**.

They now say so. **"There is no route" is checkable and useful; a blank entry is neither.**
Recheck this if a mod is added or updated — the check is cheap: no `spawn_pool_world` file,
no `keyfor` entry, no evolution, no fossil.

## §52 MOTD and server.properties

MOTD set to `Keepin' it nifty since '94!` on 2026-08-24. Edited **in Python, not sed** —
the value contains apostrophes, and `server.properties` is 0600 and holds the rcon
password, so a careless rewrite is a bad way to lose it. Backup: `.bak-premotd`.

Verify with the same status ping used for the icon (§49) — the MOTD comes back as
`description`. Takes effect on restart only.

## §53 The 2026-08-24 addon update — what was added and what was checked

Seven addons, all downloaded from Modrinth, **checksum-matched against the API**, and
inspected before install:

| addon | code | why |
|---|---|---|
| Baby Legends 2.4 | **0 classes** | 28 baby legendaries that evolve into the real thing |
| BoniMons 1 | **0 classes** | Okidogi, Fezandipiti, Bombirdier, Gouging Fire, Sandy Shocks |
| Monkeymons 1.1 | **0 classes** | Munkidori, Oranguru, Passimian |
| Rustling Spots 4.3 | 109 | rustling spots, custom spot definitions via datapack |
| Cobblemon Cards 1.0.4 | 10 | TCG; packs from chest loot and Pokémon drops |
| Party Extras 1.8.15 | 98 | party screen, type matchups, team analyzer |
| Highlight 1.0.0 | 27 | battle UI polish. **`environment: client`** — not installed server-side |

**No duplicate Fabric mod ids**, so the server starts. The only shared file paths are
per-jar metadata (`MANIFEST.MF`, `pack.mcmeta`) and `lang/en_us.json`, which merges.

### BoniMons and Monkeymons overwrite base Cobblemon assets

35 and 22 files respectively, **all genuinely different**. Checked key by key: **no stat,
type, ability, catch-rate, evolution or egg-group changes anywhere.** What does change is
`hitbox`/`baseScale` (they ship their own models) and movepools. Affected: Furfrou, the
Pansage/Pansear/Panpour line, Clobbopus, Grapploct, Sandaconda, Silicobra, Smoliv, Dolliv,
Arboliva, Brambleghast. They will look different; they will not play differently.

Because hitboxes change, so do the "clear space to spawn" figures from §39.

### BoniMons ships a broken Fezandipiti spawn

The species is registered as `fezandipiti`, but its spawn file asks for **`fezandipti`** —
one letter short. That spawn can never resolve, so Fezandipiti would never appear. Same
class of bug as Hoopa's `prism_bottle` (§21).

Repaired with `world/datapacks/bonimons-fezandipiti-fix`, which overrides just that one
spawn file. Datapacks load after mods, so the override wins, and a BoniMons update cannot
silently undo it — it will simply stop being needed. `mkfix.py` regenerates it and exits
cleanly if upstream has fixed the typo.

### Datapack-only addons were rewrapped as jars

BoniMons and Monkeymons ship only as datapacks, which on a client means two more resource
packs to enable and order. **Both are MIT**, so they were rewrapped as Fabric jars using
the same wrapper Baby Legends uses — a `fabric.mod.json` with
`"depends": {"fabric-resource-loader-v0": "*"}` makes Fabric read the jar's `data/` and
`assets/` directly. Everything lands in `mods/`, nothing to enable. `REPACKAGED.txt`
inside each records the origin, author and licence; no content was changed.

Stray `desktop.ini` files that the authors accidentally zipped are dropped in the rewrap.

## §54 Addon species are invisible to the Pokédex unless spliced in

The dex is a fixed 1025. The 28 Baby Legends pre-evolutions are **custom species**, so they
existed in game and were entirely absent from the one page anyone would check.
`wikiindex.py` now collects any species carrying a `name` and `primaryType`, and
`build3.py` appends the ones the dex does not already have — 1025 → **1053**.

Two traps when splicing:

- The **unreachable-biome filter runs after the splice** and reads *raw* biome ids. Feeding
  it display names blanks every entry. Add spliced species to `_FULL`, which the filter
  skips.
- `pretty_biome()` is built for the structures page and its prebuilt tag map; handed a raw
  id it returns junk (`minecraft:soul_sand_valley` came out as `"B, I, M or Nm"`). Addon
  spawns use `_addon_biome()` instead, which just strips the namespace and `is_` prefix.

## §55 Delta updates beat re-downloading the pack

The full client package is **240 MB**; the seven new jars are **25 MB**. A player who
already has the pack should never re-download it.

`client/NiftySMP-update-<date>.zip` mirrors the `.minecraft` layout so its contents drag
straight in. **No .bat** — an earlier installer replaced people's shaderpacks, and nobody
trusts a batch file from a friend anyway. `wikiclientpkg.py` picks up the newest
`NiftySMP-update-*.zip` in `/var/www/dl` automatically and the Mods page grows an
"Update only" row with its own content hash.

## §56 RCT series are per-player, and that decides whether gym mods are worth it

`initialSeries = "empty"` — every player starts in **no series** and picks one from a
League NPC. The three are:

| id | title | region |
|---|---|---|
| `radicalred` | Radical Red | **Kanto** — "a difficult series" |
| `bdsp` | Brilliant Diamond/Shining Pearl | **Sinnoh** — "a casual series" |
| `unbound` | Unbound | Borrious |
| `freeroam` | Freeroam | pauses your series, removes the level cap |

Read from `world/data/rctmod.player.<uuid>.stat.dat`, 2026-08-24: **a player is in
`radicalred`; the owner, a player and a player are all in `bdsp`.**

**Trainers spawn regardless of your series but refuse to battle.** The mod has dialogue
for each case, which is how we know the mechanic without testing it:

- wrong series → *"You're not in the right series for this battle!"*
- out of order → *"You need to earn more badges before you can challenge me."*
- another series first → *"You need to complete another series before you can challenge me."*

So finding a gym early is harmless — **save the waypoint and come back**. The order is
enforced by refusal, not by absence. `requiredDefeats` in each trainer file is the chain
(Brock has none and is first; Erika needs Lt. Surge; Clair needs Giovanni).

**Switching series wipes progress in the current one** — the trainer association warns
*"Starting a new series will reset your current series progression!"* `freeroam` pauses
without losing anything; switching does not. Commands live under `/rctmod`.

### Why both gym structure mods were declined

**Radical Gyms & Structures** and **Radical Trainers Structures** ship **only
`radicalred` (Kanto) gyms** — 9 and 8 structures, zero code, all series-tagged
`radicalred`. Three of the four players are in `bdsp`, so they would generate buildings
with no one inside. Worth revisiting if the group finishes Sinnoh and moves to Kanto.

### And why Extra Structures was declined

Its latest 1.21.1 build is **NeoForge-only**; the Fabric build is older, and the author
states plainly that on Fabric the spawner blocks do not work — Pokémon generate once with
the structure, **with no random IVs, no defined movepool and no shiny chance**. That is
worse than the Legendary Monuments structures we already have.

## §57 Check nested jars before declaring a dependency missing

Catch Rate Display declares `fabric-language-kotlin` as a hard dependency. A scan of
top-level mod ids said it was **missing**, which would have meant shipping a client
package that crashes on startup for four people.

It is not missing: **Cobblemon bundles it**, along with fourteen other Kotlin artifacts,
inside its own `META-INF/jars/`. Counting nested jars takes the reachable mod-id count
from 41 to **131**.

Always recurse into `META-INF/jars/` before concluding a dependency is absent — the same
lesson as the conventional `#c:` tags in §40.

## §58 Radical Gyms — installed server-side only, and it changes the 8 Kanto leaders

Installed 2026-08-24. **Pure data: zero classes, zero `assets/`.** The gym buildings are
made from CobbleFurnies, Cobblemon, RCT and CobbleDollars blocks — all of which the
client already has — so **no client update was needed**. Server went 122 → 123 mods and
the log shows `Found new data pack rgs`.

Nine structures: 8 Kanto gyms (Pewter, Cerulean, Vermilion, Celadon, Fuchsia, Saffron,
Cinnabar, Blackthorn) plus **`kanto_league`**.

**It overrides the 8 Kanto leaders' RCT trainer files.** Diffed field by field — three
changes each, and one of them matters:

| field | before | after | meaning |
|---|---|---|---|
| `spawnWeightFactor` | 0.25 | **0** | they stop roaming; they exist only in their gym |
| `maxTrainerWins` | -1 | 3 | capped instead of unlimited |
| `signatureItem` | e.g. `hard_stone` | **null** | **they can no longer be summoned with a Trainer Spawner** |

That last one is a real trade: a Trainer Spawner loaded with a Hard Stone will no longer
produce Brock. It only affects the **8 Kanto leaders**; every other trainer keeps its
signature item, so a Sinnoh-series spawner gym is untouched. Reversible with a small
datapack restoring `signatureItem` if both behaviours are wanted.

## §59 Series are not one-shot — completing one banks a permanent bonus

Answering "do you only ever get to pick one series": no. From the trainer association:

> *"Starting a new series will reset your current series progression! In return
> **completing** a series will permanently increase your luck for better loot from
> trainers."*

So finishing Sinnoh and then starting Kanto **loses nothing and gains a permanent luck
bonus**. Switching *mid-series* is what costs progress. `freeroam` pauses without losing
anything. Commands live under `/rctmod`.

## §60 The Structures page read a list the build never regenerated

`D2['structures']` comes from the prebuilt `/tmp/wiki_data2.json`, which `build-wiki.sh`
does not rebuild — so an installed structure mod was **invisible** on the page no matter
how many times the wiki was rebuilt.

Structures are now discovered by walking every jar for `data/<ns>/worldgen/structure/*.json`
and merging anything the prebuilt list has never heard of. That took the page from **104
to 177 cards** — the 9 Radical Gyms entries plus **64 structures from mods that were
already installed and had simply never been listed**.

**The bug that hid this for three builds:** the discovery loop used `zipfile.ZipFile(...)`,
but `zipfile` is not imported until much later in `build3.py`. The resulting `NameError`
was caught by the loop's own `except Exception: continue`, so every jar was skipped in
silence and the pass reported nothing. Catch the errors you mean — `except (IOError,
OSError, BadZipFile)` — never a bare `Exception` around code that can raise `NameError`.
Third time this pattern has cost time (see §47, §57).

## §61 Server-side data changes need no client download — ever

Worth stating plainly because it decides a lot of "should we bother" questions:
**anything under `data/` is server-authoritative.** Trainer definitions, spawn pools, loot
tables, recipes, structures — a datapack in `world/datapacks/` overrides a mod's copy and
**no player downloads anything**. Only `assets/` (models, textures, sounds) needs to reach
a client.

Proven twice here: `bonimons-fezandipiti-fix` overrode a mod's spawn file and the log
showed `Found new data pack ... loading it automatically`; Radical Gyms itself is a
data-only jar that changed 8 trainers with no client involvement.

### The staged Kanto-leader toggle

Radical Gyms nulls `signatureItem` on the 8 Kanto leaders (§58), so a Trainer Spawner can
no longer summon them. A datapack restoring just that field is prepared but **deliberately
not active**, at:

    $COBBLEMON_DIR/datapack-staging/kanto-leaders-spawnable

It keeps every other gym-mod change — `spawnWeightFactor` stays 0 so they still do not
roam — and restores only `signatureItem`. Verified field by field against both sources.

To turn it on:

    mv $COBBLEMON_DIR/datapack-staging/kanto-leaders-spawnable \
       $COBBLEMON_DIR/world/datapacks/
    # then in game:  /reload      (no restart, nobody re-downloads)

To turn it off, move it back and `/reload` again. `datapack-staging/` is outside
`world/datapacks/` precisely so its presence is not its activation.

`mkgymfix.py` regenerates it from whatever the two jars currently say, so a Radical Gyms
update does not strand it.

## §62 A content hash in the QUERY STRING is not enough — put it in the FILENAME

This one shipped a wrong download to a real person, so it is worth being blunt about.

The update zip was republished **under the same filename three times** as mods were added
(7 → 9 → 10). Cloudflare caches `/dl/*` for 24h. Result: over an hour after the 10-mod
build was on disk, the bare URL was still serving the **7-mod** build —
`content-length: 25054136`, `cf-cache-status: HIT`, `age: 4515`. The owner installed it and
correctly reported that the last three mods added were missing.

`?v=<hash>` (§32) is **not** sufficient protection. It only helps a link that is
*generated after* the rebuild. It does nothing for:

- a wiki page already open in someone's browser, which has the old `?v=` baked in
- a URL typed or pasted without the query string
- a link shared in chat before the rebuild

**The filename itself must change with the bytes.** `NiftySMP-update-<date>-<sha8>.zip`
cannot be served stale, because a stale copy is a *different file*.
`wikiclientpkg.py` now requires a `-[0-9a-f]{8}.zip` name and prefers it over any
unhashed sibling.

Keep the unhashed name in place pointing at the current build as well, so anyone holding
the old link self-heals within the TTL instead of hitting a 404.

**Rule: never republish a download under a name someone may already have fetched.**

## §63 Rustling Spots ships its own shiny rate

`config/rustlingspots/rustlingspots-server.json` is independent of Cobblemon's
`shinyRate`. Defaults:

    shiny_spot_chance   0.0025    = 1 in 400      (Cobblemon's own rate is 1 in 2048)

So spots shipped **5.1× more generous** than an ordinary encounter. **Halved to 0.00125
(1 in 800) on 2026-08-24** at the owner's request — still 2.6× a normal spawn. Backup:
`.bak-preshinyhalve`.

It is a shiny **spot**, not a shiny roll on the Pokémon: 1 in N spots is flagged shiny and
whatever it holds comes out shiny, so the species is unrelated to the luck.

Other knobs worth knowing in the same file: `max_spots_per_player` 8,
`spot_lifetime_ticks` 6000 (5 min), `player_spot_radius` 200, `empty_spot_chance` 0.02,
`announce_shiny_finds_globally` true.

**Edit it as JSON, not with sed.** A malformed file fails *silently* — the mod falls back
to defaults, which would quietly restore 1 in 400 while looking like the change applied.
`halveshiny.py` parses, edits, re-serialises and reads the file back to prove it still
loads. Mod config changes need a **restart**; unlike a datapack, `/reload` does not re-read
this file.

## §64 BoniMons ships 10 models with the same geometry identifier

Reported in play as "Clobbopus's mesh is messed up", then Bramblin too. It is a BoniMons
bug affecting **10 of its 16 models**.

Each `.geo.json` declares `"identifier"` inside `minecraft:geometry[].description`. Ten of
BoniMons' files still carry Blockbench's default **`geometry.unknown`**:

    arboliva, bombirdier, brambleghast, bramblin, clobbopus,
    cobalion, dolliv, fezandipiti, grapploct, smoliv

Cobblemon registers geometry by that identifier, so all ten collide and whichever loads
last renders for every one of them. Note **Cobalion** and **Fezandipiti** are in that list
— a Sword of Justice and one of the Loyal Three.

**Not a resource-pack conflict.** Checked first: no installed pack supplies these species,
so pack order was never involved. The species file points at the model by *file path*
(`cobblemon:clobbopus.geo`) and the poser does not mention the identifier at all — which is
what makes renaming safe.

Fixed in the rewrapped jar by `fixbonimons.py`: each `geometry.unknown` becomes
`geometry.<species>`. Re-run it after any BoniMons update; it is idempotent.

**But this was not why Clobbopus looked wrong** — see §65. The rename is correct hygiene
and matters for the models we keep, but it fixed nothing visible on its own.

Monkeymons is clean — 9 models, 9 distinct identifiers — which is why nothing was wrong
with the Pansage line.

## §65 BoniMons replaces 10 Pokémon Cobblemon already models — that was the real bug

Clobbopus and Bramblin rendering wrong was **not** the `geometry.unknown` collision (§64).
It was simpler: BoniMons ships its own, lower-quality models for species Cobblemon already
models perfectly well, and those were winning.

**The check that missed it.** A collision scan compared file paths and reported BoniMons'
assets as "new". They *are* new paths — the two mods use different layouts:

    Cobblemon   assets/cobblemon/bedrock/pokemon/models/0852_clobbopus/clobbopus.geo.json
    BoniMons    assets/cobblemon/bedrock/models/clobbopus/clobbopus.geo.json

Same species, different path, so nothing "collided" by filename while both models existed
and BoniMons' species definition pointed at its own. **Compare by species, not by path.**

Of BoniMons' 16 models, **10 duplicate a Cobblemon model**: arboliva, brambleghast,
bramblin, clobbopus, dolliv, furfrou, grapploct, sandaconda, silicobra, smoliv. Only **6**
are genuinely new — bombirdier, cobalion, fezandipiti, gougingfire, okidogi, sandyshock —
and those are the reason it was installed.

`tools/stripbonimons.py` drops all files belonging to the 10 duplicated species (72 of 145
entries), so Cobblemon's own models *and* data win and the hitbox/baseScale/movepool
changes revert too. The 6 that matter still arrive.

Not every replacement looked broken — the owner reported Grapploct as fine. Reverting all
10 is the predictable choice rather than curating per species: nobody installed BoniMons
for alternative Clobbopus art.

**General rule: an addon that "adds missing Pokémon" should be checked for what it also
replaces.** Diff its species list against the base mod's before installing.

## §66 Cobblemon numbers its asset folders; addons don't — so the collision check lies

The §65 strip was written and it still shipped the bug, because the check that was supposed
to prove it worked compared folder names literally:

```
Cobblemon   assets/cobblemon/textures/pokemon/0852_clobbopus/clobbopus.png
BoniMons    assets/cobblemon/textures/pokemon/0852_clobbopus/clobbopus.png   <- SAME PATH
BoniMons    assets/cobblemon/bedrock/models/clobbopus/clobbopus.geo.json     <- different
```

BoniMons uses **both layouts in the same jar** — bare `clobbopus/` for models, numbered
`0852_clobbopus/` for textures. A drop list keyed on `"clobbopus"` matched the models and
missed the textures. Six files survived, including both Clobbopus textures and both Bramblin
textures, and a texture built for the addon's UV layout stretched over Cobblemon's mesh is
*indistinguishable in game* from a broken model. Same symptom, different file.

Two further layouts were missed on the next pass too: `sounds/pokemon/<species>/` had no
pattern at all, and `bedrock/species/arboliva.json` has neither the dex prefix nor the
`_base` suffix the pattern required.

**Normalise `^\d{3,4}_` off both sides before comparing anything.** Without it the audit
reports a clean bill of health:

```
monkeymons  DUPLICATES: []                               <- literal compare, wrong
monkeymons  DUPLICATES: panpour, pansage, pansear,       <- normalised, correct
                        simipour, simisage, simisear
```

Monkeymons had the identical bug and would have gone unnoticed — it was only caught by
re-running the comparison normalised. It ships 9 species, of which only 3 (Munkidori,
Oranguru, Passimian) are genuinely new.

`tools/stripdupespecies.py` replaces the hardcoded drop list with one derived from the
Cobblemon jar at run time, covers all nine path layouts, and prints the leftovers for the
dropped species so "none" is proven rather than assumed. Run it against any new addon:

```
python3 tools/stripdupespecies.py Cobblemon-fabric-1.7.3+1.21.1.jar <addon>.jar
```

The lesson is the general one from §65 and before it: **a verification step that can only
print success is not a verification step.** Both times the strip "succeeded" and both times
the file that actually caused the glitch was still in the jar.

## §67 Cobblemon Cards: the two rules the mod never states

**Booster packs only generate in vanilla chests.** The `LootTableEvents.Modify` hook in
`FabricCobblemonCards` checks four things before it injects anything:

```
LootTableSource.isBuiltin()                  datapack overrides kill it
namespace .equals("minecraft")               <- every modded structure fails here
path .startsWith("chests/")
!path .startsWith("chests/village/")         villages excluded
randomChance(boosterChestSpawnChance / 100)
```

The namespace check is the one that catches people out. Mega Showdown's observatory chests
are literally named `chests/observatory_chest`, so they pass the *path* test and fail on the
namespace - meaning a player can clear observatory after observatory at a **0%** rate while
believing they are unlucky. 40 vanilla tables qualify; trial chambers own 13 of them.

**The Grading Station needs a Data Monitor on top.** `GradingStationBlock.isMonitorAbove`
requires the block above to be exactly `cobblemon:monitor`. Cobblemon's own **Display Case**
(`cobblemon:display_case`) looks almost identical to the Grading Station and is what people
build by mistake - the giveaway is that a wrong base block produces **no message at all**,
because the three failure messages only fire from a real Grading Station.

Numbers worth keeping (all from bytecode, not the store page):

| Thing | Value |
|---|---|
| Pack contents | 3 common, 1 uncommon, 1 rare-or-better |
| God Pack | `godPackTicketChance`% of packs open as 5 elite cards |
| Grade | `1 + rnd(10)`, uniform - **nothing** about the card shifts it |
| Grade effect | `statValue x (1 + 0.03 x grade)`, so Grade 10 = +30% |
| Recycler dust | 1/2/3/5/10/15 by rarity, **x2 shiny**, +1 background, +1 holo |
| Binder pages | leather 1, iron 2, gold 3, diamond 6, netherite 10, master 1000 - **x12 slots** |
| Card Cabinet | 12,000 (master tier) |
| Structure Disk | holds 1000 dust; 50/200/500/1000 are the rarity thresholds; 5 scans |
| Pokemon card drop | dex **1-1025 only** - our 28 baby legendaries are outside it |

**The config tooltip for `godPackTicketChance` is wrong.** It says "chance of obtaining a God
Pack Ticket when opening a Booster Pack"; the code uses it as the chance the pack *itself* is
a God Pack. No ticket is ever granted by opening a pack.

**Normalise `^\d{3,4}_` when comparing anything asset-shaped.** Same trap as §66 - Cobblemon
numbers its folders and addons do not.

### §67a The Master Album is not wearable - and that is the whole balance

A reasonable challenge - "8 glass and a leather binder for 12,000 cards, cheaper than the
iron binder? that can't be true" - turned out to be right to make, and the page was wrong.

The recipe is real (`DDD/DND/DDD`, D=glass, N=leather_binder) and the capacity is real
(`BinderTier.MASTER` = 1000 pages, `getMaxSlots(12)` = `pages * 12` = 12,000, confirmed
against the Card Cabinet's own `sipush 12000`). What the first pass missed is one file:

```
data/accessories/tags/item/belt.json   leather, iron, gold, diamond, netherite
                                       -- no master_album
```

`onInitialize` calls `AccessoriesAPI.registerAccessory` on MASTER_ALBUM, so the log says it
is registered and it looks equippable. **Registering an accessory is not the same as being in
a slot's tag.** With no slot that accepts it, it cannot be worn, so its cards give no stat
bonus - and stat bonuses are the entire point of a binder. Bulk storage is cheap; *wearable*
storage is what the metal chain buys, capped at 120 cards on Netherite.

The lesson is the recurring one: **when a number looks too good, the balancing constraint is
usually in a data file, not the code.** Two classes and one enum all agreed; the tag file was
the only thing that disagreed, and nothing pointed at it.

(`ShapedRecipeMixin.copyBinderContainer` also carries binder contents across an upgrade craft,
trimmed to the new tier - so working up the chain never loses cards.)

## §68 Riding: bird self-rights, jet does not, and one config field is dead

"Mewtwo rolls weirdly and feels glitchy" is a real difference, not a feel. Cobblemon's own
`mewtwo.json` has ride **stats** but `"behaviour": null` - **Cobblemon does not make Mewtwo
rideable at all.** Journey Mounts adds the behaviour, and picks a different controller:

```
zapdos / lugia / honchkrow    "key": "cobblemon:air/bird"
mewtwo  (journey mounts)      "key": "cobblemon:air/jet"
```

The two are not variations on a theme. Roll-related members in each class:

- `BirdBehaviour` - rollCorrectionTimer, timeToRollCorrect, maxRollCorrectionRate,
  currRollCorrectionForce, rollDampen, rollError, pitchInfluencedRollCorrection,
  rolledOverPitchCorrection, noInputTimeRoll, isInputtingTowardsRoll, desiredRoll ...
- `JetBehaviour` - angRollVel, rollRot, shouldRoll. **That is all of it.**

Bird actively levels you out after you stop steering; jet has no correction and no damping.
Mewtwo also has the highest SKILL of the group (80-100 vs Zapdos 70-85, Honchkrow 30-50),
and skill drives turn responsiveness, so it is twitchier on top of never self-righting.

**`disableRoll` works; `rightingDelay` and `invertRoll` do not.** Only `getDisableRoll()` has
callers (`MountedCameraRenderer`, `OptionsMixin`). Nothing anywhere calls `getRightingDelay()`
or `getInvertRoll()`, and nothing outside `CobblemonConfig` touches those fields. Bird
self-righting comes from `BirdSettings.timeToRollCorrect` in the species data instead. So the
setting whose tooltip describes exactly the fix you want is inert - don't send anyone to it.

`disableRoll` is **global and camera-only**: it keeps the view upright on every mount, and the
Pokemon still banks. Per-species handling needs a datapack swapping the controller.

Client settings live in `.minecraft/config/cobblemon/main.json`. **Editing it with the game
running is safe** - `saveConfig` is only called from `initializeConfig` at startup and from the
config GUI, never on shutdown. The GUI itself is a **Mod Menu** entrypoint, and Mod Menu is not
in our client pack, which is why the Riding options appear not to exist.

## §69 The Galar fossil halves - the wiki had them backwards

Checked against all four recipes rather than memory:

| Pokemon | head | body |
|---|---|---|
| Arctovish | Fossilized **Dino** | Fossilized **Fish** |
| Arctozolt | Fossilized **Dino** | Fossilized **Bird** |
| Dracovish | Fossilized **Drake** | Fossilized **Fish** |
| Dracozolt | Fossilized **Drake** | Fossilized **Bird** |

The rule is in the names: **Dino -> Arcto-, Drake -> Draco-** (head); **Fish -> -vish,
Bird -> -zolt** (body). The page previously claimed Bird and Dino were the top halves, which
puts Bird and Drake on the wrong sides.

**Every Galar fossil is used by exactly two Pokemon**, so a complete set of four makes
**exactly two** - and the pairs are forced: Arctovish leaves Dracozolt, Arctozolt leaves
Dracovish. No set of four yields three.

Machine facts (from `FossilMultiblockStructure` / `FossilMultiblockBuilder`): Data Monitor
directly **above** the Fossil Analyzer, Restoration Tank on any of the 4 horizontal sides,
**128** units of organic material, **14400 ticks = 12 minutes**, and the machine is locked to
the player who started it. Our `maxInsertedFossilItems` is **2**.

Fill values come from `data/cobblemon/natural_materials/*.json`. Sorting them by value is a
trap - the top five are Nether Star, Dragon Egg and Enchanted Golden Apple. **Hay blocks are
the real answer: 16 each, so 8 fill the tank.**

### §68a Fixing it: the datapack, and why disableRoll was the wrong lever

`disableRoll` works, but it is **global and it forces third person** - you cannot keep a
gentle bank on Zapdos and lose it only on Mewtwo, and the camera change is not subtle. The
right fix is per-species, server-side, and needs no client download.

`world/datapacks/mewtwo-bird-ride` overrides `data/cobblemon/species/generation1/mewtwo.json`
with `riding.behaviours.AIR.key` set to `cobblemon:air/bird`.

**Journey Mounts ships a COMPLETE species file** (27 top-level keys, 233 moves, 2 forms), not
a partial patch, so the datapack override has to be complete too - build it by reading their
file and editing one value, never by hand-writing a stub. Built by `tools/mkmewtwo.py`.

The AIR block is modelled on Zapdos: `key`, `rideSounds`, `stats` only. The jet-tuned
`speed`, `gravity` and `jumpVector` expressions are **dropped**, because no `air/bird` species
sets them and the bird controller handles gravity itself. Stats are left alone, so exactly one
variable changed. (Mewtwo's SKILL is 80-100 against Zapdos' 70-85, so it will still turn
faster - if it is still too sharp, SKILL is the next dial, not the controller.)

**`restart-when-empty.sh` is now parameterised**: `restart-when-empty.sh "<reason>" [hours]`.
It polls RCON, needs 3 consecutive empty minutes so a relog does not trigger it, flushes the
world, restarts via the NOPASSWD systemctl rule, and verifies RCON answers again before
declaring success. Logs to `logs/restart-<slug>.log`. Launch it detached:

```
nohup setsid ./restart-when-empty.sh "reason" 24 >/dev/null 2>&1 </dev/null &
```

**Do not run that inside `ssh the server '...'`** - the script is full of single quotes and the
outer quoting eats it. Write it locally and `scp`, then `sed -i 's/\r$//'`.

## §70 Fishing: bait goes ON the rod, and the ball is decoration

Two things the mod never states and the wiki got wrong by omission.

**Bait attaches to the rod.** `PokerodItem.overrideStackedOnOther` handles a SECONDARY
(right) click of a bait stack onto the rod in the inventory - the bundle gesture - with
`playAttachSound` / `playDetachSound` either side. The bait lives in a `RodBaitComponent`
on the rod, and the bobber reads its effects through
`SpawnBaitEffects.getEffectsFromRodItemStack(stack)`. **Carrying bait in your inventory does
nothing at all.** `PokerodItem$Companion.consumeBait` calls `shrink(1)`, so the rod holds a
full stack and spends one per cast.

**The Poke Ball on the rod is cosmetic.** A rod definition in `data/cobblemon/pokerods/` has
exactly two fields:

```json
{"pokeBallId": "cobblemon:ultra_ball", "lineColor": "#282828"}
```

and `getPokeBallId` is referenced by exactly three classes: `PokeRod` itself,
`FishingRodTooltipGenerator` and `PokeBobberEntityRenderer`. **No gameplay path reads it.**
A Master Rod fishes identically to a Poke Rod. Fishing *spawns* a wild Pokemon to battle
(85% of bites; the other 15% is an item) - the rod never captures anything, which is why the
ball cannot matter.

What does matter: the smithing base is `#minecraft:enchantable/fishing`, so **enchant the
vanilla rod first**. The bobber reads both `luckOfTheSeaLevel` and `lureLevel`.

The **Pokerod Smithing Template** is injected into vanilla fishing treasure, so you fish it
up with an ordinary rod. Duplicate: 7 gold + 1 prismarine shard + the template -> 2.

**Plain Poke Bait has `"effects": []`** - it does nothing on its own. It is the blank you
season with fruit and berries (`recipe_filters/bait_seasoning`).

14 distinct bait effect types exist; `rarity_bucket` is the strong one and `typing` is the
most common. Indexed as `baiteffects` so the page explains the vocabulary rather than just
listing berries.

## §71 Megaroid vs Mega Site, and the "50%" that was never a chance

Two buried meteorites, same size, same material, and only one of them has what you want.

| | Megaroid | Mega Site |
|---|---|---|
| origin Y | **-32 to -20** | **-19 to +5** |
| processors | **none** | `mega_showdown:mega_site` |
| evolution stones | **none** | 17 stone blocks roll Fire/Thunder/Water/Leaf/Moon/Sun/Dawn/Shiny/Ice/Dusk ore at ~9% each |
| core | 1 **Keystone Ore** | 1 **Mega Crystal** |

The difference is entirely in the **template pool**, not the NBT: megaroid declares
`"processors": []` while mega_site points at a rule processor that rewrites its
`minecraft:stone` blocks into evolution ores. Reading only the NBT makes them look almost
identical and hides the single most useful distinguishing feature.

**If it has evolution stones, it is a Mega Site and will never contain a Keystone.**

**Every megaroid contains Y -20.** Origin spans [-32,-20] and the structure is 14 tall, so
the intersection of every possible placement includes -20 exactly. No such level exists for
Mega Sites (origin -19..+5, 14 tall) - Y 0 catches a bit over half.

**Neither generates outside the Overworld.** All five Mega Showdown structures are
`#minecraft:is_overworld` or narrower. Nether strip-mining will never find one.

**The Heatran cave contains a hand-placed `mega_showdown:keystone_ore`** - one block, in the
structure NBT, *not* in `heatran_cave_chest` (which has no keystone at all). Caves are
spacing 205 / separation 155, so ~3,200 blocks apart.

### The "50% a block" that never existed

The wiki said Keystone Ore and Mega Crystal were "50% a block". They are not. The loot table
is `minecraft:alternatives` with two children - silk touch gives the **block**, otherwise the
**item** - and the indexer split a two-child alternatives node into 50/50 as though they were
weighted entries. **It always drops.** Watch for this any time a loot percentage comes out as
a clean 50 on a two-entry table.

**The Magma Stone does BOTH** - see §72. An earlier draft of this file said it only summons,
on the strength of its tooltip. That was wrong. Recipe is 7 magma blocks around 2 netherite
scrap.

## §72 A tooltip is marketing copy, not a spec

The Magma Stone's tooltip reads *"A stone used to summon Heatran at his cave in the Nether"*.
From that I told the owner it does not locate the cave and that the Arc Phone finds it
separately - and I wrote that onto the Mechanics page, contradicting the Structures page,
which had been right the whole time. The owner pushed back from memory. The owner was correct.

The code:

```
LegendaryTrackingScreen.STRUCTURES
    StructureData("Heatran Cave", ModItems.MAGMA_STONE, "legendarymonuments:heatran_cave")

LegendaryTrackingServerHandler.handleLocateRequest
    -> playerHasRequiredItem(player, structureId)      gates the position
```

`StructureData` carries `requiredItem` and `missingItemText`. So the key item does two jobs:
**carry it to track the structure, then use it on the pedestal.** The tooltip only describes
the second.

**19 of 27 trackable structures are gated on their key item.** Free ones: Turnback Cave,
Southern Island, Hoopa Pyramid, Knightly Heroes, Dyna Tree, and the three lakes.

Two lessons, and the second is the one that keeps recurring:

1. **A tooltip describes the headline use, never the whole contract.** Behaviour lives in the
   handler. §70 was the same shape from the other direction - the Poke Ball on a rod has a
   tooltip mention and *no* gameplay effect, which only reading the callers proved.
2. **When the wiki already says something and I am about to contradict it, that is a signal to
   check harder, not a stale line to overwrite.** The Structures page disagreed with my new
   text and I did not treat that as evidence. Existing correct content is a source, not noise.

## §73 Vanilla items are invisible to a `ModItems.` regex - and don't re-type a parsed table

§72 fixed one wrong claim and introduced a worse one. Extracting the Arc Phone's tracking
table, the parser matched only:

```
getstatic  ModItems.MAGMA_STONE
```

Vanilla items are `getstatic class_1802.field_47315`, so **eight structures came back with no
item** and were published as "trackable for free". They are not - every one of the 27 needs
something, and those eight need ordinary vanilla items:

| Structure | Item | Why it was missed |
|---|---|---|
| Turnback Cave | Trial Key | `class_1802.field_47315` |
| Southern Island | Axolotl Bucket | `class_1802.field_28354` |
| Hoopa Pyramid | End Rod | block item -> `class_2246.field_10455` |
| Knightly Heroes | Totem of Undying | `class_1802.field_8288` |
| Dyna Tree | Cherry Sapling | block item -> `class_2246.field_42727` |
| Lake Valor | Fermented Spider Eye | vanilla |
| Lake Acuity | Sweet Berries | vanilla |
| Lake Verity | Glow Berries | vanilla |

Worse, the loop carried the last-seen mod item forward, so a vanilla row could have
**stolen the previous structure's item** rather than just going blank. Match `class_1792`
generally, not one registry class.

**Block items need a second hop.** `field_8056` is not registered from a string literal - it
comes from `class_2246.field_10455` via `method_7989(Block)`. Resolve the *block* field
against `class_2246`'s clinit (`class_2248` is `Block`; **`class_2246` is `Blocks`**).

### The bigger mistake

`ARC_TRACK` was **already in build3.py**, already correct, already carrying every vanilla
item, already handling "Iceroot **or** Shaderoot Carrot Seeds" - and the Structures page had
been rendering from it correctly the whole time. Rather than reuse it, a second table was
typed out from a fresh parse, and the fresh parse was worse than the one already committed.

**If the codebase already parses something, render from that. Never hand-type a second copy.**
The Mechanics block now iterates `ARC_TRACK` directly, so the two pages cannot disagree again.

Related: the dex looked the same table up with `ARC_TRACK.get(id)` while the structures page
used `arc_track_for(id)`, which prefix-matches. Exact lookup missed every path-suffixed id
like `traditional_village/ecruteak`. Dex entries naming their tracking item went **8 -> 34**
by switching to the prefix matcher. The 3 left (Cobalion, Terrakion, Virizion at Thalic Camp)
are correct - that structure is not in the Arc Phone's list.

## §74 Right information, wrong page - and check before claiming a gap

The owner spent an afternoon failing to summon Meloetta because he had
**Music Disc "Creator (Music Box)"** instead of **Music Disc "Creator"**. Two different
items - `class_1802.field_51629` and `field_51628` - both called "Creator" in game, both
happily playing in a jukebox. `MeloettaJukeboxBlock` checks for `field_51628` only, so he sat
at 3 of 4 with no way to tell which one was wrong.

Sources differ, which is how you end up with the wrong one:

```
music_disc_creator             chests/trial_chambers/reward_ominous_unique   (ominous vault)
music_disc_creator_music_box   pots/trial_chambers/corridor                  (smashing pots)
```

**The wiki already documented this.** The Meloetta dex entry has carried the warning since
commit bf955e59. I then told the owner "nothing warned about the near-identical Music Box
variant" without looking - the second time in one session I claimed a gap that was not there
(see §72, where I contradicted a correct Structures page).

**Check the wiki before saying the wiki is missing something.** It is one grep.

### The real defect was placement

The information existed on the **dex entry**. He was reading the **Structures page**, because
he was standing in the Amphitheater. That card listed the structure, the Pokemon and the
tracking item - everything except what to bring.

Added `STRUCT_NOTE`, a per-structure hook for **what you must bring on arrival**, rendered
onto the structure card. Generated fields can describe a building; they cannot describe a
ritual. When a structure needs something the moment you get there, it belongs on the card
someone reads while standing in it - not only on a dex entry they would have to know to
search for.

The ritual itself, for the record: four vanilla jukeboxes within **20 blocks** of the Meloetta
Jukebox holding Pigstep, 5, Creator and Relic - **order and position irrelevant**, it is a
HashSet matched into a HashMap - then right-click the Meloetta Jukebox holding the Disc of the
First Song (9 fragments). All five jukeboxes are emptied on success.

## §75 Wardens never burrow because watching them prevents it

Reported as "wardens do not despawn, ancient cities are unlootable, never happened once across
4-5 cities". Two wrong theories from me first, then a live measurement that settled it.

**The mechanic.** A Warden leaves by digging down. `Activity.DIG` has exactly two conditions,
both `VALUE_ABSENT`: `roar_target` and `dig_cooldown`. `dig_cooldown` is set to **1200 ticks
(60s)** in `finalizeSpawn`, and `WardenAi.setDigCooldown` refreshes it to a full 1200 on any
disturbance - so the Warden needs **60 uninterrupted seconds**.

**The cause.** `Warden.canTargetEntity` is hardcoded to any `LivingEntity` (no tag, no
datapack lever), and Cobblemon spawns Pokemon in a ring **16-40 blocks around the PLAYER**, up
to 8 per second. Standing near a Warden puts that ring on top of it. **Observing the Warden is
what stops it leaving.** The owner's 40-block test was the worst possible distance - exactly
the outer edge of the spawn ring.

**Measured live**, one Warden, `PersistenceRequired: 0b`:

```
player  9 blocks away    ttl = 1189 1200 1200 1174 1200 1178 ...   pinned for 4 minutes
player 87 blocks away    ttl = 1065 863 661 459 256 54 -> gone     burrowed in 61 seconds
```

**The fix needs no gamerule, no killing and no spawn changes:** retreat to **60-120 blocks**.
Simulation distance is 8 chunks (128 blocks) so the chunk still ticks; the spawn ring maxes at
40; the despawner clears what is already there at 64-96.

### Three lessons

1. **A calm heartbeat is not the despawn signal.** Anger and the burrow timer are separate -
   detection resets the timer *without* making it angry. The owner's observation ("calm, but
   never leaves") was exactly right and looked like a contradiction only because I assumed
   calm implied the timer was running.
2. **I guessed twice before measuring.** First "constant re-disturbance" (right shape, no
   evidence, and I could not defend it when challenged), then `PersistenceRequired` (a real
   mechanism, disproven in one query: `0b`). The whole thing took ~10 minutes to settle once I
   asked for a live entity instead of reasoning at it. **Ask for the entity first.**
3. **`pkill -f` over SSH kills your own session** - already written down in this file, and I
   did it anyway while cleaning up the monitor. Kill by PID.

## §76 Keeping RCT trainers out of the deep dark

RCT has a biome lever that is easy to miss because the config example only shows bare vanilla
tags (`["is_overworld", "is_forest"]`), which reads as "minecraft namespace only". It is not -
`TrainerSpawner` builds a set containing **both** forms of every tag on the biome:

```
lambda$nextSpawnCandidate$19   ->  path only          "is_deep_dark"
lambda$nextSpawnCandidate$18   ->  namespace + path   "cobblemon:is_deep_dark"
```

then does `blacklist.stream().noneMatch(set::contains)`. So a modded, namespaced tag works
fine. Set in `config/rctmod-server.toml`:

```toml
biomeTagBlacklist = ["cobblemon:is_deep_dark"]
```

`cobblemon:is_deep_dark` resolves to `minecraft:deep_dark` here (its other entries are
optional Terralith/Wythers biomes we do not have). `minecraft:has_structure/ancient_city` is
an equally exact alternative - same single biome.

**Caveat, from the config's own wording:** `spawnTrainerAssociation` "will respect the
'dimensionBlacklist' and 'dimensionWhitelist' settings" - it does **not** mention the biome
tags. So the single Trainer Association NPC may still appear in the deep dark even with this
set. The battle trainers are the ones this stops.

Server-side TOML, read at startup - needs a restart, so pair it with `restart-when-empty.sh`.

## §77 Worldgen lag on 3 cores: the levers that exist, measured

Reported as "flying in straight lines 200k blocks out, worldgen lags the server, Chunky does
not help because we are not filling areas".

**Hardware is the ceiling.** 3 CPU cores, 7.9 GB RAM, 5 GB heap, 409 MB already in swap with
187 MB free. Chunk generation is the most parallelisable thing Minecraft does and it is what
these three cores are spending everything on. No mod removes that.

**Already correct, so no easy wins there:** Lithium, FerriteCore, Krypton and spark installed;
`sync-chunk-writes=false` already set. Idle is healthy - TPS 20, 1.5 GB of 5 GB.

### view-distance is the big lever

Chunks the server must generate per player is `(2*VD+1)^2`, and flying into virgin terrain
means every one is generated from scratch:

| view-distance | per player | x5 players |
|---|---|---|
| 12 | 625 | 3,125 |
| **10** | 441 | 2,205 (-29%) |
| 8 | 289 | 1,445 (-54%) |

Set to **10**. Free, instant, revertible; `server.properties.bak-vd12` holds the old value.

### Noisium

Server-side worldgen optimisation. What made it an easy call:

- `client_side: unsupported, server_side: required` - **no client download**, which matters a
  lot here after repeated client-update fatigue
- **no dependencies**, loader `>=0.15.11` (we run 0.19.3), MC `>=1.21 <=1.21.1`
- **5 mixins total**, one of which is `compat.lithium.LithiumNoiseChunkGeneratorMixin` - it
  ships explicit Lithium compatibility rather than fighting it
- declares `breaks: biox`, which we do not have
- sha512 verified against Modrinth before install

Loaded clean: 0 mixin failures. The 180 `No data fixer registered` ERROR lines are
**pre-existing** - identical count in the previous boot - so do not blame a new mod for them.

**Rejected: C2ME.** It parallelises chunk generation, which sounds like the answer, but it is
built to exploit many cores. On 3, the gain is small and it adds real instability risk to a
48-mod server.

**Chunky is not useless, it is being used wrong.** Pregenerating *between* four players 200k
apart is pointless, but Chunky takes a centre and a radius - running it around each player's
frontier while nobody is online moves the cost out of the play session, which is the only part
that hurts.

## §78 Parked: booster packs in BCA village chests

Deliberately not built. Recording it so it is not re-researched from scratch.

BCA ships **124 loot tables and zero village ones**; its village pieces reference no loot
tables at all, and its villages reuse `minecraft:village/plains/town_centers`. So **BCA village
chests use the vanilla `minecraft:chests/village/*` tables** - which the Cards injection
explicitly skips (`!path.startsWith("chests/village/")`).

Adding packs there is possible but not cheap: **a datapack REPLACES a loot table, it cannot
append to one**, so it means reproducing each vanilla village table verbatim plus an extra
pool - roughly a dozen tables across five village types. Scriptable, but real surface area for
what would be a ~1% drop.

Parked because BCA villages are extremely common and already the main loot activity; adding
packs there would undo the scarcity the rate is tuned for. Revisit only if village looting
stops being rewarding on its own.

**Also dead: RGS gym structures.** 9 structure files, **zero chests, zero barrels, zero loot
tables**. There is a display case block but no container to fill, so there is nothing to hook
without editing structure NBTs.

## §79 Arc Phone reward automation, and what the question marks are

**The unnamed question marks in the Quests tab are the mod's unfinished quests**, and they do
**not** count against you. `QuestCatalog.trackableCount()` and `completedCount()` both do
`if (e.workInProgress()) continue;`, so the real total is **60 of 97**. Generation IX looks
like 12 entries and is actually 4 - the Ruinous quartet - which is exactly what the owner
observed in game before we had read the code.

Trackable per generation: **I 4, II 6, III 5, IV 11, V 9, VI 3, VII 7, VIII 11, IX 4**.
Every generation is completable and so is 100%.

### The automation

`tools/arcphone-rewards.py` (deployed to `$COBBLEMON_DIR/`, cron `*/3`):

- reads `world/data/legendarymonuments_quest_rewards.dat` - **plain NBT, per player UUID ->
  completed quest ids**, so no command and no online player is needed to READ progress
- grants `cobblemon-cards:booster_pack_gen<N>` on completing a generation's trackable set
- grants `cobblemon-cards:god_pack_ticket` at 60/60, once ever
- `--status` prints everyone's progress, `--dry-run` grants nothing

Three things that make it safe to leave running:

1. **State is only written after the `/give` is confirmed.** The rcon reply is checked for
   `Gave` before recording. A failed give retries next pass instead of being lost.
2. **Items can only go to an ONLINE player**, so a reward earned offline stays pending rather
   than vanishing. That is a feature of the same check.
3. The `.dat` is SavedData, written on world save - so a reward can lag a few minutes behind
   the actual completion. Expected, not a fault.

Item ids verified against `ModItems` in the jar (`booster_pack_gen1`..`gen9`,
`god_pack_ticket`) **and** end-to-end with a live `/give`, which returns
`Gave 1 [Generation 2 Booster Pack] to <player>` - the string the script parses.

### Why RCT rewards must ride on advancements, not loot tables

`getCompletedSeries()` is a Map of series -> **count** with `addSeriesCompletion`, and
`removeProgressDefeats()` clears `defeatedTrainerIds` - the set that enforces
`maxTrainerDefeats: 1`. So switching series makes the same gym leaders beatable again and
series completion is explicitly repeatable. **Loot-table rewards would be farmable; player
advancements fire once ever and are not.**

## §80 — Two Cobblemon Cards items that are not what their tooltips imply

Asked what **Champion's Ribbon** and **Grading Station Bypass** actually do. Neither is
obtainable the way the tooltip suggests, and one of them does nothing at all.

**Method that settled it:** dump every class's constant-pool strings and ask which classes
mention the field name. An item that is *used* anywhere gets referenced by the code that
uses it; an item referenced only by `ModItems` and `ModCreativeTabs` is registration and a
creative-tab entry and nothing else.

**Grading Station Bypass — unimplemented.** `GradingStationBypassItem` exists but its only
constant-pool string is its tooltip key. `GradingStationBlock` and `GradingStationBlockEntity`
never mention it. No recipe, no loot table, no chest spawn. The tooltip promises to skip an
analysis that already takes only 100 ticks. **The item has no effect.**

**Champion's Ribbon — cosmetic, auto-granted.** Referenced by exactly three classes:
`ModItems`, `ModCreativeTabs`, and `CardAdvancementManager`. In `checkAdvancements` it is
constructed exactly once, right after the **`kanto_starter`** advancement is granted — i.e.
you get it for collecting Bulbasaur, Charmander and Squirtle cards. Nothing else in either
jar reads it, so it is a trophy with no function.

**Why this matters for reward design:** the ribbon looked like an ideal series-completion
prize until we checked. It is already handed out for three common cards, so awarding it for
finishing a battle series would land as a duplicate, not a trophy.

**The general lesson:** a tooltip is a translation key, not a contract. Before building a
reward around an item, confirm some class other than the registry and the creative tab
actually references it.

**Advancement namespace, while we are here:** `cobblemon-cards:` — root, first_shiny,
kanto_starter, master_evaluator, booster_addict, full_cabinet, complete_gen1..9,
complete_megas, complete_national, complete_regionals, complete_collection.

## §81 - rctmod:defeat_count does not mean what the JSON looks like it means

Built booster-pack rewards for RCT battle series milestones ("beat 4 of this series' 8 gym
leaders"). The obvious encoding is one criterion with `trainer_ids` listing the 8 leaders and
`count: 4`. **That is wrong, and it fails silently** - it would pay out only after beating a
single leader four times, which `maxTrainerDefeats: 1` makes impossible.

`DefeatCountTriggerInstance.matches()` has three branches:

**1. non-empty `trainer_ids`** - checks whether the trainer *just defeated* is in the list,
then whether the player's defeat count **for that one trainer** is `>= count`. It is a
per-trainer test, not a distinct-count over the list. rctmod's own
`defeat_champion_terry.json` is the tell: `count: 1` with three Terry ids, meaning "beat any
one Terry once".

**2. `trainer_type` + `count >= 0`** - this one *does* count distinct trainers of that type.
But it calls `getAllData()` with an empty varargs array, and `getAllData` returns **every
trainer in every series** when given no arguments (`if (args.length <= 0) return
trainerMobs.entrySet().stream()`). So it can never be scoped to one series. Unusable for a
per-series milestone.

**3. `trainer_type` + `count: -1`** - all trainers of that type, again across all series.

**The encoding that works:** 8 separate criteria, one `trainer_ids: [single_leader]` each,
plus a CNF `requirements` block. Minecraft `requirements` is an AND of ORs, and "at least 4 of
8 hold" is equivalent to "every 5-element subset contains at least one that holds" - because
if only 3 held, the 5 that did not would form an all-false group. C(8,5) = **56 groups**.
Verified live with a throwaway datapack: 3 criteria granted -> nothing; the 4th -> completes
and delivers the reward.

**Second trap: `trainer_ids` criteria never back-fill.** They only evaluate at the moment that
exact trainer is defeated, so every win earned before the datapack existed is invisible.
Ground truth for past wins is `world/data/rctmod.trainers.*.mem.dat`, shape
`data.defeats[trainerId][playerUuid] = count` - the same store the trigger reads. Back-fill
with `advancement grant <player> only <adv> <criterion>`.

**Third trap: `/advancement grant` only works on ONLINE players** - "No player was found"
otherwise. So a back-fill has to be a cron job that catches each player at next login, not a
one-shot. Same shape as arcphone-rewards.py.

**Safety rule worth keeping:** a back-fill script must refuse to grant a set of criteria that
would *complete* an advancement, because completing one pays out. Report and skip instead, so
any actual payout stays a deliberate decision.

**Method note:** the shipped advancement JSONs in a mod jar are the cheapest spec you will
find - `data/rctmod/advancement/**` gave the exact condition schema before any bytecode was
read. Read the mod's own usage first, then confirm semantics in the class.

## §82 - a reward that lands on the ground is a reward the player never sees

Real scenario raised by the owner: a player earns a booster pack while flying, their inventory
is full, `/give` drops it at their feet, and they fly on without ever knowing. The item
despawns. Nothing in the logs looks wrong.

**Both delivery paths drop on a full inventory.** `/give` does, and so does an advancement
`rewards.loot` -- `AdvancementRewards.apply` calls `player.giveItemStack(stack)` and falls back
to `dropItem` when that fails. Neither reports the difference: `/give` says "Gave 1 [X] to
player" either way, so the response cannot be used to detect it.

**Fix for anything script-driven: check for a free slot BEFORE giving, and hold if there is
none.** If there is no room, do not grant -- tell the player exactly what is waiting and retry
next pass. State stays un-written, so the reward cannot be lost.

**But do NOT count the slots by parsing `data get entity <player> Inventory`.** RCON truncates
any response at 4096 bytes, and a single Cobblemon Cards binder carries enough component NBT --
every card's stat_value, grade, effect, rarity, background -- to exceed that on its own. The
list comes back cut off mid-item, the parse silently stops early, and the count reads far too
low. Measured live on the owner: real inventory **27/36 used, parser reported 7**. That is a
fail-*open* in the worst place -- it declares "room available" on a full inventory, so the item
drops and, because the code thought it succeeded, no warning is sent. The guard would have been
worse than useless: it would have hidden the very failure it exists to catch.

**Let the server do the counting instead.** `execute store result score <holder> <obj> run data
get entity <player> Inventory` stores the **list LENGTH**, read back with `scoreboard players
get` as one small number that cannot truncate. That length includes armour (100-103) and
offhand (-106), which `/give` never targets, so query those individually --
`...Inventory[{Slot:100b}].id` keeps each response tiny -- and subtract. Verified live:
31 total - 4 armour = 27 main, matching what the player saw on screen.

The general lesson: **any rcon response near 4KB is suspect.** Prefer commands that return a
number over commands that return a structure.

Fail *open* when the response cannot be parsed (give anyway, plus a "check your feet" line).
Failing closed would silently block a reward forever on a parsing quirk; failing open is no
worse than the old behaviour and the player is warned.

**Fix for the advancement path**, where there is no clean way to test inventory space in an
mcfunction: attach `rewards.function` alongside `rewards.loot`. The function runs as the player
the instant the advancement completes, so it can announce the reward BY NAME to everyone and
tell the earner to look at their feet. Instant beats correct-but-late here -- the original
problem was not knowing, not the drop itself.

**Two smaller things worth copying:**

- `announce_to_chat: true` gives the generic "X has completed the goal [Y]". It never names the
  reward. If the reward is the point, a `rewards.function` tellraw has to say so.
- Announce to `@a`, not to the player. A private confirmation is a receipt; a public one is the
  thing people actually enjoy. And write `an Ice Booster Pack`, not `a Ice Booster Pack` -- pick
  the article from the first letter.

**Verifying tellraw without players online:** run it through rcon. "No player was found" means
the command PARSED and only the selector failed. A genuine syntax error returns "Incorrect
argument for command" with a caret. That distinction makes it possible to validate every
message on an empty server.

**And a third trap, found by ear:** `playsound <sound> player <name> ~ ~ ~` issued over RCON
plays the sound at **world origin**, not at the player. `~ ~ ~` is relative to the command
EXECUTOR, and over rcon that is the console, sitting at 0,0,0. A player far from spawn hears
nothing at all; one a few hundred blocks out hears something faint, oddly timbred and panned to
one ear, which reads as "my headphones are acting up" rather than "the command is wrong". The
server will tell you outright if you look: **"The sound is too far away to be heard."**

Fix: `execute at <name> run playsound ... <name> ~ ~ ~`. This does NOT affect sounds played from
an advancement `rewards.function`, because those run with the player as executor -- only
console/rcon-issued ones. Worth checking any `~ ~ ~` in a script that talks to rcon: position,
particles and teleports have the same failure mode and the same silent-looking symptom.

## §83 - a hopper steals from any container above it, including another hopper

Built a dedicated line to carry Cobblemon eggs from two pasture blocks to their own chests,
routed at y=64 directly on top of the existing y=63 collection slab. It leaked immediately:
test items injected at the pasture turned up inside the serpentine, in the wrong chests.

**Cause:** a hopper pulls from whatever container sits directly above it. The whole y=63 field
was quietly draining the new y=64 line from underneath, one item at a time. Nothing errors,
nothing logs; the items simply end up somewhere else.

**The check that catches it:** for every hopper in a new line, ask whether the block below is
also a hopper. Sixteen of mine were.

    leaks = [p for p in line if is_hopper(p) and is_hopper(below(p))]

**Two fixes, depending on what is underneath:**
- where the lower hopper was expendable (start of the chain, nothing lands on it any more
  because the new line now covers those squares) - delete it, replace with a solid block
- where it was load-bearing (the main conveyor) - move the new line one block sideways to a
  lane where the level below is air

**Design rule for this world:** the only safe lane for a transport hopper is one with air or a
solid block beneath it. Check before building, not after.

**Related geometry worth remembering:** `dirt_path` is 15/16 of a block tall, so an item
resting on it still sits inside the block space a hopper one level below scans. That is what
makes a buried hopper floor collect drops through a walkable surface - and it is why a full
block (grass_block, planks) in the same position collects nothing. The owner's pasture uses
this deliberately; the `x=1701` border column is grass_block and therefore dead space, which
made it a free corridor to route through.

**Hoppers cannot move items upward.** A collection floor can only be fed from above, so any
line that must reach a conveyor has to travel at or above that conveyor's level the whole way.
That single constraint dictated the entire route.

## §84 - build3.py rebinds `_resolve` halfway down, and pretty_biome() breaks below it

Added a per-form spawn block to the Pokedex and it produced 9 species out of 52. The data
was fine, the name matching was fine (51/52 matched a dex entry), and the biome tags all
resolved when tested standalone. The rows were being dropped inside `pretty_biome()`.

**Cause:** `build3.py` defines `def _resolve(ref)` at line 232 (biome reference -> installed
biome ids) and then defines a *completely different* `def _resolve(item, depth, seen)` at
line 1685 (item id -> recipe/source node). Python has one module namespace, so the second
definition silently replaces the first. `pretty_biome()` looks `_resolve` up at CALL time,
so it works above line 1685 and returns nonsense below it - and its failure mode is a
returned empty string, which reads as "this biome is not installed on this server" and
quietly drops the row.

**Fix:** alias the biome resolver at definition time and have `pretty_biome()` use the alias:

    _resolve_biome = _resolve      # the bare name is rebound to an item resolver below
    ...
    got = _resolve_biome(b)

**Every existing caller of pretty_biome sat above line 1685**, so nothing was previously
broken - but that is luck, not design, and the next person to add code near the end of the
file will hit it exactly as I did.

**The check worth running before debugging data:** `grep -n "def _resolve" build3.py`. Two
hits for one name in a 3,700-line module is the whole answer. More generally, when a
function works in isolation but returns empty inside a long script, suspect a rebound global
before suspecting the data.

**Related, on the same feature:** spawn rows in `wiki_data3.json` are keyed by BARE species
name, so regional forms are merged with no label. They cannot be split after the fact - base
and regional rows share bucket, level and condition keys and differ only by biome, so
matching the rendered prose back to jar rows failed on 55% of rows. Read
`data/*/spawn_pool_world/*.json` from the jars directly instead; the form is the aspect after
the species name (`voltorb hisuian`). Note `region_bias=alola` is NOT a form - it decides
which regional form the Pokemon EVOLVES INTO (a beach Pikachu gives an Alolan Raichu).

## §85 - Cobblemon's cosmetic items, and two ways I got them wrong

Cobblemon lets you put a cosmetic on **33 species** and documents none of it. Pikachu gets
Ash's league caps; Squirtle's line gets the Squirtle Squad glasses; Smeargle takes 16 paint
colours; Komala and Timburr take 12 wood types. Nobody on the server knew it existed.

**The trigger is SNEAK + right-click**, not right-click. `PokemonEntity` guards the whole
path behind `isShiftKeyDown` before calling `showInteractionWheel`, which is what offers the
cosmetic. A plain right-click does nothing and consumes nothing, which reads exactly like a
broken feature. The Pokemon must also be **yours and sent out** - `getOwnerPlayer()` is
compared against the clicking player.

**Merely HOLDING the item does nothing.** The held item renders in the Pokemon's hands and is
a separate system. Confirmed in game: a Pikachu holding a Big Malasada shows the malasada and
no hat.

**Read `data/cobblemon/cosmetic_items/*.json`, NOT `species_features/cosmetic_item.json`.**
Both exist and both list choices. The species_features one is INCOMPLETE - `pewter_crunchies`
is missing from its choice list - and trusting it made the wiki report Ash's signature Partner
cap as permanently unobtainable, which was wrong and published. The cosmetic_items files are
the real assignment data: species, `consumedItem`, and aspects. When two files in a mod define
overlapping things, find out which one the CODE loads before believing either.

**A second parallel-definition trap on the same feature:** Pikachu also declares a `league_cap`
choice feature with eight cap choices, and Cobblemon ships all eight cap textures. **No
resolver keys on `<choice>-cap` at all**, so setting `league_cap` changes nothing. The art is
wired to `cosmetic_item-*` instead. The owner tried every value and correctly saw no
difference. Aspect existing + artwork existing does NOT mean the two are connected - check the
resolver.

**Resolver gotchas when mining labels from them:**
- skip `resourcepacks/` inside the jar; those are alternate-form resolvers and they labelled a
  pair of shears "Fluff Alola Bias Male"
- key on whatever aspect the definition names, not on a `cosmetic_item-` prefix, or you miss
  `dyes.json` entirely (16 dyes on six species) and report hundreds of dead rows
- `dyes.json` lists both `color-white` and `colour-white` for one dye; key rows by the consumed
  item so the double spelling collapses

## §86 - Cobblemon Cards stats: four are flat, the rest round away to nothing

Every card prints its stat as a percentage, which hides the only thing that matters about
them. From `FabricBinderItem.getDynamicModifiers`:

    value = summed stat_value * globalStatMultiplier          (10.0 on this server)
    MAX_HEALTH / ARMOR / LUCK / MINING_SPEED -> ADD_VALUE      (flat)
    everything else                          -> value/100, ADD_MULTIPLIED_TOTAL

**Do not trust a Yarn field name for an enum constant.** I read `field_6330` as
ADD_MULTIPLIED_BASE and predicted a 1.0-value Attack Speed card would take a 1.6 weapon to
2.0 (base 4.0 x 0.1 = +0.4). Measured: **1.76**, which is 1.6 x 1.1 - it multiplies the
CURRENT TOTAL, not the base. The measurement is what settled it; the mapping guess was
wrong and would have shipped as fact.

So a 0.0656 Luck card is **+0.66 luck**, while a 0.0054 Attack Speed card is **+0.05%**.
Two cards printing similar numbers differ by orders of magnitude. Values SUM across the
binder (`Map.merge`) and apply only while it is equipped.

**Spawn stats are not vanilla attributes at all.** `getVanillaAttribute` returns null for
them and the code skips the attribute path entirely, so they are mod-handled - and they are
the only stats where the printed percentage is the real effect.

**Verify with `/attribute <player> <id> get`, not by reasoning.** Measured with the binder
equipped, every flat stat matched to five decimals: Luck 0.0656 -> 0.65636, Max Health
0.0820 -> +0.82047, Armor 0.0656 -> +0.65634, Mining 0.0090 -> 0.09002. Attack Speed showed
**no measurable change at all**. The measurement also corrected a wrong assumption: Mining
Speed lands on `player.mining_efficiency`, NOT `player.block_break_speed`, which stayed at
exactly 1.0.

**Luck is the strongest stat here, and not because of fishing.** Of the 120 loot tables in
the pack that use `quality` (the field luck scales), **116 are RCT trainer drops**, weighted
`+350 / +220 / +72` against base weights of `150 / 40 / 2`. One point of luck moves the
legendary tier from **0.37% to 5.9%** - about 16x. The rest: 2 Legendary Monuments SwSh
temple chests, the Poke Rod, and vanilla fishing. **Trial chambers use zero quality** - all
26 of their tables checked - so luck does nothing there.

**Recycler payout** (`CardRecyclerBlockEntity.calculateDustAmount`): common 1, uncommon 2,
rare 3, epic 5, legendary 10, mythic 15; then shiny **doubles**, a background **+1**, a holo
effect **+1**. Cosmetic cards give **zero**.

**Reading a player's cards:** they nest - inventory item -> `cobblemon-cards:binder_contents`
-> card items. A recursive walk must skip re-entering `components` after handling the binder
list, or every binder card is counted twice (I got 63 cards for a 34-card inventory).

**The rule, once measured, is simple: the number printed on the card IS the effect.** Flat
units for the four flat stats, a percent of your current total for the percentage stats,
and ten times that for spawn stats (a +1.50 Normal Spawn card reads +15% in game).

**Equipping a binder moves it OUT of the vanilla `Inventory` NBT** into an Accessories
slot, so a playerdata reader that walks `Inventory` + `EnderItems` reports **zero cards**
for a player wearing one. That looks exactly like data loss and is not.

**Measuring a tiny effect needs an exaggerated input.** A real Attack Speed card is ~0.005
and moves the attribute below display precision, which is indistinguishable from "no
effect" - and I published exactly that error once, from a reading taken after the owner
had already recycled the only such card. Hand out a test card with an absurd value, read
the delta, take it back.

## §87 - a dropped item stack over 99 crashes the whole server on save

2026-08-29: the server died mid-session and kicked both players. Crash report:

    Entity Type: minecraft:item      Entity Name: Lapis Lazuli
    Location:    <coords>
    IllegalStateException: Value must be within range [1;99]: 108
      at ItemStack.save -> ItemEntity.saveAdditional -> ServerLevel.save

**Minecraft's ItemStack save codec rejects any count outside [1;99].** A dropped stack of
108 Lapis Lazuli - above lapis's own 64 max stack, so something merged mining drops past
the legal limit - made `ServerLevel.save` throw. The server shut down, the watchdog
force-killed it, systemd restarted it. The item was in the owner's Titan Hammer tunnel at
exactly the depth he was mining, and the hammer breaks 3x3 and collects nine blocks' drops
at once, which is the obvious source (not proven - I could not find the merging code path).

**The bad entity destroys itself.** It is the thing that cannot be written, so it never
reaches the region files; on restart the world loads the last good save without it. Nothing
to clean up afterwards - but nothing to find on disk either.

**Which is why detection must be IN MEMORY, and selectors cannot compare NBT numerically.**
They can compare SCORES, so:

    scoreboard objectives add stackguard dummy
    execute as @e[type=item] store result score @s stackguard run data get entity @s Item.count
    execute as @e[type=item,scores={stackguard=65..},limit=1] ...

`tools/stackguard.py` does this and clamps anything oversized to 64. **A 2-minute cron LOST
THE RACE** - it crashed a second time, same 108, inside the polling window, because an
autosave / chunk unload / disconnect can save the entity seconds after mining creates it.
It now runs every 3 seconds: cron fires it once a minute, it loops for 55s and exits, so
cron doubles as the restart-if-it-died watchdog.

**It needs a lock.** Two copies overlapping at the cron boundary interleaved their RCON
responses - a real log line read `CLAMPED 64: 6Tuff has the following entity data: 3Tuff
has the following...` - and a mis-parsed response could clamp the wrong entity. A PID
lockfile with a stale-lock check fixes it.

**And `pkill -f stackguard.py` over SSH killed my own session, again** - the ssh command
line contains the pattern. This is the second time in this project. Put test/cleanup steps
in a script file on the server and run that, so no pattern can match the invoking command.
Losing 44 lapis beats losing the server. Verified by planting **70**-stacks of lapis, redstone and tuff (over the
threshold, safely under the fatal 100) and watching it be found and clamped - never test
this with a real 108, that is the crash itself.

**And the operational lesson: `save-all flush` is not a read.** I had been running it
freely all session to get fresh player NBT, and it is what tripped the landmine. The
entity would have killed the next autosave anyway, so the flush only changed the timing -
but on a live server with players on it, treat a forced save as a write-path action and
not a free way to refresh data.

**This is a mitigation, not a cure.** There is still a ~3-second window, and the real bug is
whatever merges the drops past the max stack size - Legendary Monuments ships no config for
the Titan Hammer, so it cannot be turned off from here. Worth reporting upstream.

## §88 - Max Soup grants Gigantamax; Sweet Max Soup is Urshifu-only

The names say the opposite, and I told the owner the opposite, and they stood in
game swinging a Sweet Max Soup at a Butterfree that would never take it. The
failure is completely silent: `canUseOnPokemon` returns false, `applyToPokemon`
returns `method_22431` immediately, the arm animates, nothing is consumed and no
message prints. It reads exactly like a broken item.

```
SweetMaxSoup.canUseOnPokemon -> species.getName().equals("Urshifu")
MaxSoup.canUseOnPokemon      -> species has a form labelled "gmax"  AND  name != "Urshifu"
```

Both **toggle** `Pokemon.setGmaxFactor` rather than setting it, so a second bowl
turns Gigantamax back off. Both hand a bowl back and only consume in survival
(`method_7337` is the creative check). MaxSoup shrinks the stack (`method_7934(1)`);
SweetMaxSoup replaces the held stack outright (`method_6122`).

**The gmax roster is the `gmax` FormData label, not a list to type.** That is the
exact predicate MaxSoup checks. Cobblemon ships **34** such forms across **32**
species - Toxtricity (Low-Key) and Urshifu (Rapid Strike) each have two. Mega
Showdown's own jar and the `ride-fix` datapack re-declare a few of the same forms;
dedupe by species name or you will over-count.

### Max Mushrooms: lush caves, and moss block only

`mayPlaceOn` resolves to `class_2246.field_28681` = `minecraft:moss_block`. Vanilla
`MushroomPlantBlock.canSurvive` has a `#minecraft:mushroom_grow_block` shortcut that
would normally admit podzol and mycelium, so I expected those to work too. **They do
not.** Falsification test, placed with `setblock` then poked with a neighbour update:

```
moss_block  YES     podzol  no     mycelium  no     dirt  no     grass_block  no
```

The reason is obvious in hindsight: the worldgen feature is injected into
**`minecraft:lush_caves` only** (`BiomeSelectors.includeByKey(class_1972.field_29218)`
in `MegaShowdownFabric`), uniform **Y -40 to 0**, count 2, rarity 1-in-2 chunks.
Moss is the lush-cave floor. The block is a crop with ages 0-3, is bonemealable, and
drops itself at age 3 - so a moss floor plus bonemeal is a renewable farm.

Note the biome is wired **two different ways**: `data/mega_showdown/neoforge/biome_modifier/`
for NeoForge and Fabric's `BiomeModifications.addFeature` in code. Reading only the
JSON would have been right by luck here; it will not always be.

### Mushroom cost, since everything runs through it

| item | recipe | mushrooms all in |
|---|---|---|
| Max Honey | honey bottle + max mushroom (shapeless) | 1 |
| Max Soup | `aaa` / ` b ` - 3 mushrooms over a bowl | **3** |
| Sweet Max Soup | ` c ` / `aaa` / ` b ` - max honey, 3 mushrooms, bowl | **4** |
| Power Spot | `RMR` / `RWR` / `SSS` - 4 redstone, mushroom, wishing star, 3 stone | 1 |
| Dynamax Candy | ` E ` / `EME` / ` E ` - 4 exp candy S + mushroom | 1 |

### The rest of the gimmick numbers, read not remembered

`config/mega_showdown/config.json`: `outSideMega true`, `outSideUltraBurst true`,
`multipleMegas false`, `dynamaxAnywhere false`, `powerSpotRange 20`,
`dynamaxScaleFactor 4.0`, `minBondingRequired 200`, `teraShardRequired 50`,
`teraShardDropRate 10.0`, `stellarShardDropRate 1.0`.

`maxDynamaxLevel` is **Cobblemon's**, not Mega Showdown's - `DynamaxCandy` calls
`CobblemonConfig.getMaxDynamaxLevel()`. It is `10` in `config/cobblemon/main.json`.

**Power Spot range is a cube.** `PlayerUtils.isBlockNearby` walks dx/dy/dz each from
-20 to +20 independently - a 41x41x41 box, not a sphere and not a flat radius. A
basement Power Spot covers the room above it. The block drops itself when broken.

**One recipe shape makes all 46 mega stones**: ` c ` / `brb` / ` i ` where b = iron
ingot, r = raw Mega Stone, i = diamond, and c is a species-flavoured catalyst
(twisted spoon -> Alakazite, black glasses -> Absolite, ...). 46 stones, **44
species** - Charizard and Mewtwo have X and Y.

**The Omni Ring is in all four slot tags** (`mega_slot`, `z_slot`, `tera_slot`,
`dynamax_slot`), and its recipe takes either sparkling stone - the tag entry is
`sparkling_stone_dark|sparkling_stone_light`, so dark vs light genuinely does not
matter.

**Why this section exists:** I asserted the soup pair backwards from memory instead
of reading `canUseOnPokemon`, and the owner burned 4 mushrooms and a honey bottle on
a bowl they cannot use. Two lines of bytecode would have caught it. See §85 for the
same lesson on cosmetic items.

## §89 - a Gigantamax faint can kick the player, and why it is not a fluke

2026-08-29, first occurrence in the server's whole history (0 hits in every rotated
log). Owner Gigantamaxed a Butterfree near a Power Spot, the form expired after its
2 turns, and when the Butterfree fainted around turn 7 **only that player** was
disconnected:

```
EncoderException: Failed to encode packet 'clientbound/minecraft:custom_payload'
                  (cobblemon:battle_update_team)
Caused by: java.util.NoSuchElementException
  at Object2ObjectOpenHashMap$MapIterator.nextEntry
  at AbstractObject2ObjectMap.putAll
  at Object2ObjectOpenHashMap.<init>
  at class_2487.method_10553          <- NbtCompound.copy()
  at BattleUpdateTeamPokemonPacket.encode
```

**No data was lost.** The Pokemon read back clean: `FormId normal`, `GmaxFactor 1`,
`ScaleModifier 1.0`. The race is in the *copy made for the packet*, not in the source.

### The mechanism

`BattleUpdateTeamPokemonPacket` stores a **live `Pokemon` reference** and serialises it
at encode time, not a snapshot taken at construction:

```
<init>  putfield  BattleUpdateTeamPokemonPacket.pokemon
encode  Pokemon.Companion.getS2C_CODEC().encode(buffer, this.pokemon)
```

The log tag is `[Netty Epoll Server IO #1/ERROR]` and the frames run through
`class_2535.method_52917` -> `AbstractEventExecutor.runTask`, i.e. the write was
**scheduled from another thread and executed later on the IO thread**. So the server
thread mutates the Pokemon while Netty encodes it.

`fastutil`'s `AbstractObject2ObjectMap.putAll` reads `size()` **first**, then calls
`next()` that many times. A map that **shrinks** mid-copy therefore throws
`NoSuchElementException`, not the `ConcurrentModificationException` a `java.util.HashMap`
would give you. **Treat a bare NoSuchElementException out of fastutil as a concurrency
symptom.** `Pokemon.PersistentData` is the NbtCompound being copied, and
`AspectUtils`/`CobbleEvents` remove keys from it (`battle_end_revert`, `is_tera`,
`is_max`) all through the revert path.

### The part that makes it recur

**`CobbleEvents.dynamaxEnded` never clears `is_max`.** It calls
`startGradualScalingDown` and `revertEffectsBattle` and returns - it does not
`putBoolean("is_max", false)` and does not remove the key. Only `devolveFainted`
(offset 264) and `AspectUtils.revertPokemonsIfRequired` do.

So `is_max` stays **true** for the rest of the battle after a Dynamax expires. When the
Pokemon later faints, `devolveFainted` reads it, believes the Pokemon is still
Dynamaxed, and runs the whole revert **a second time** - `revertEffectsBattle` ->
`AspectUtils.updatePackets()` -> `new BattleUpdateTeamPokemonPacket(livePokemon)` ->
`sendUpdate`, then `startGradualScalingDown`, then finally sets `is_max` false.

That redundant revert is **deterministic**: it runs on every faint that follows a
Dynamax in the same battle, gmax or plain. Only the encode collision on top of it is
chance. `is_max: 0` in stored PersistentData is the fingerprint that it ran -
`dynamaxEnded` alone would have left `1`.

Empirically confirmed rather than only read: the fainted Butterfree carried `is_max 0`
and `orignal_size 1.0`, two keys **no other Pokemon on the server has** (checked all
569).

### Avoiding it

Switch a Dynamaxed Pokemon out rather than letting it faint. At battle end
`revertPokemonsIfRequired` clears `is_max` without a live battle-update packet in
flight. There is no config toggle for this short of `dynamax: false`.

**1.9.5 does NOT fix it - checked, not assumed.** Installed is
`mega_showdown-fabric-1.9.3` (2026-07-27); latest is 1.9.5 (2026-08-22). 1.9.4's
changelog reads "Fixed all gmax species/sizing and hitboxes" and "Added all gmaxes",
which sounds promising and is not. Downloaded 1.9.5 to `/tmp` (sha1 verified against
Modrinth, never installed) and diffed the three methods:

| method | 1.9.3 vs 1.9.5 |
|---|---|
| `CobbleEvents.dynamaxEnded` | **byte-identical** - still never clears `is_max` |
| `AspectUtils.updatePackets` | **byte-identical** |
| `CobbleEvents.devolveFainted` | only two constant-pool indices shift (700->696, 715->711) from unrelated edits elsewhere in the class. **No logic change.** |

A constant-pool index shift is the thing to recognise here: it makes a diff look like a
change when nothing executable moved. Compare the mnemonics, not the operands.

So updating buys nothing for this bug and costs a 20 MB client push to four people -
1.9.4 changed models and species files, so `assets/` moved and clients cannot stay
behind. See [[cobblemon-client-updates]]. **Not upgraded.**

**Reported upstream 2026-08-29 as
<https://github.com/yajatkaul/CobblemonMegaShowdown/issues/285>** (filed on the owner's
account with their explicit go-ahead; no server address, player names or credentials in
the body - verified after posting). Note the repo was renamed from `Mega_Showdown` to
`CobblemonMegaShowdown`; the old URL redirects, so `gh` accepts either. There was no
existing report - #263 "potential data corruption" is a datapack/registry problem,
unrelated. **Watch that issue before considering any future upgrade for this bug.**

### Unrelated but worth knowing

`config/mega_showdown/config.json` has `msdPatchAutoUpdate: true`. The mod can pull its
own patches. Worth auditing before blaming a version number.

## §90 - the guide data has one item per legendary, and that is not a route

The Pokedex said Marshadow's summon item is the Shadowy Cowl. Using it does nothing.
The real route wants a Thalic Well, a bucket, a cauldron and two items **dropped on the
floor**. The owner knew this from playing; the wiki did not.

**Root cause: `D3['guides']` carries only `itemName` + `item` per legendary.** There is no
mechanic field at all. `_PED_NEEDS` had already patched the pedestal summons (§ the item a
`*PedestalBlockEntity` validates), so those read correctly - which disguised how bare
everything else was. Legendary Monuments has **many** non-pedestal mechanisms and the page
modelled none of them.

**Find them by listing the blocks, not by reading the guides.** `blocks/` in the LM jar is
the index: `ShadowCauldronBlock`, `IlexShrineBlock`, `VictiniLockBlock`, `AuroraXLogBlock`,
`YveltalCocoonBlock`, `EternatusCocoonBlock`, `MeltanBoxBlock`, `MeloettaJukeboxBlock`,
`RegiStatueBlock` + `Correct/FalseRegiLightBlock`, `collecting/*` (stakes, footprints,
essence, souls, cosmic dust), `locks/*`. Each one's `useWithoutItem` / `checkForSummoning`
holds the whole recipe.

**The fastest read is the class's string constants**, not the bytecode. The mod prints its
own requirements: *"You need Pigstep, 5, Creator and Relic in nearby jukeboxes"*,
*"/16 soul jars offered"*, *"/50 metal value stored"*, *"This box only accepts metal
ingots"*. Then confirm the numbers against `bipush`/`sipush`.

**`assets/<ns>/lang/en_us.json` settles intent in one file.** It gave the Marshadow route
verbatim (*"can be combined in a cauldron with the Shadowy Cowl and the Old Fighters
Towel"*), the GS Ball's purpose, Dream String's source, and the Titan Key's
(*"Unlocks the Regigigas Room at Snowpoint Temple"*). Read it before disassembling.

### The routes, as verified

| Pokemon | mechanism | the number that matters |
|---|---|---|
| Marshadow | Shadow Cauldron | both items **dropped**, not used; box is 1 wide x 2.5 tall |
| Celebi | Ilex Shrine | GS Ball, **crafted**: 4 yellow apricorn + 1 netherite scrap |
| Victini | Victini Lock | once **per player**; the lock stays usable by others |
| Xerneas | Aurora X Log | **16** Aurora Essence Jars (Jar = 5 glass) |
| Yveltal | Yveltal Cocoon | **16** Soul Jars |
| Eternatus | Eternatus Cocoon | **500** Galar Particles |
| Darkrai / Cresselia | dream chain | Dream String **8%** at night -> 9 = Dream Catcher -> sleep -> ~25% Lunar Feather else Nightmare Essence -> **5** = whistle |
| the 5 Regis | statue + light puzzle | all correct lights lit, all false lights unlit, within 10 h / 3 v |
| Regigigas | Titan Key | the **5 tablets**; opens the Snowpoint room |
| Lugia | pedestal | Vortex Stone = the **three bird stones**, one per urn summon |
| Meltan | Meltan Box | **50** metal value: copper 1, iron 2, gold 3, netherite 50 |
| Meloetta | jukeboxes | Pigstep + 5 + Creator + Relic within **20** blocks |
| Treasures of Ruin | stakes -> shrine | **8** stakes each (already documented) |
| Swords of Justice / Cosmog | footprints | **50** each (already documented) |

**Two things the wiki had backwards or missing entirely:**

- **The Regi tablets are the reward, not the key.** `RegiStatueBlock.getTabletForRegi`
  *gives* you the tablet when the statue breaks; nothing in LM consumes it as a summon
  item. All five craft the **Titan Key**, which opens the Regigigas room, whose statue
  gives a **Titan Core**, which is what makes the **Titan Hammer** (core + 2 netherite
  ingots + 2 breeze rods) and the Titan Pauldron. That is where the owner's hammer came
  from and nothing said so. Note Myths & Legends ships *its own* differently-named tablets
  (Ice Tablet vs Regice Tablet) - do not conflate them.
- **The Meltan Box is a renewable Meltan Candy machine.** `if isReady(): if
  !hasSpawnedMeltan() -> spawnMeltan() else -> giveMeltanCandy(); reset()`. First fill
  gives Meltan, **every fill after gives one candy**, and Melmetal needs **64**. The entry
  described only the wild spawn.

**An item referenced nowhere outside `ModItems` is a stub - but check the item's own
class first.** `NEWMOON_WHISTLE` looked dead by that test; the behaviour lives in
`items/NewmoonWhistleItem`, which spawns Darkrai. Contrast §80's Grading Station Bypass,
which genuinely has no implementation anywhere. Ownership matters too: `ironwill_sword`
and `tidal_bell` are **Myths & Legends** items, so their absence from LM code is correct,
not a bug - `assets/<ns>/models/item/<id>.json` tells you which mod owns an id.

### Cosmetic items had no path back from the item

Old Gateau showed a Cooking Pot recipe and nothing else, so finding one in a chest taught
you nothing - it is a **Pikachu/Pichu/Raichu cosmetic**. The Pokedex has had the
per-species block since §85, but the mapping only ran species -> item. Inverting `_COS_DEF`
gives item -> species, and 21 item rows now say what they are for and how to apply them
(sneak + right-click, interaction wheel).

**Why this section exists:** a single-item field read like a complete answer for months.
When source data has one slot for a thing that has many shapes, the page will look
finished and be wrong. See [[cobblemon-verify-dont-assert]].

## §91 - lag with TPS at a flat 20: it was the heap, not the tick loop

2026-09-01, reported as "lagging a lot even when people aren't flying around". Every
obvious culprit was clean, which is the point of writing this down.

**What was NOT wrong.** 454 entities total (84 Pokemon, 24 dropped items, 15 villagers).
No force-loaded chunks. Load average 0.64 across 3 cores. **Zero** "Can't keep up"
messages in the log. `spark tps` reported **20.0 across all five windows**. Anyone
checking TPS alone would have concluded the server was fine.

**The tell was the tick DISTRIBUTION, not the average:**

```
Tick durations (min/med/95%ile/max ms) from last 10s, 1m:
  12.5/14.4/20.6/25.4;   11.0/16.1/32.7/243.8
```

Median 16 ms against a 50 ms budget is healthy. The **95th percentile at 32.7 ms** and a
**243.8 ms** outlier are not - that is one stall every few seconds, which players feel as
stutter while TPS stays pinned at 20 because the server catches up before falling a whole
tick behind. **Always read `spark tps` for the percentiles, never the TPS line alone.**

**Cause: the heap was 5G on a 7.7G box.**

```
java RSS       5.94 GB      (AlwaysPreTouch commits the whole heap up front)
free            256 MB
VmSwap          186 MB      <- of the JVM ITSELF, from /proc/<pid>/status
```

With a 33G world the kernel wants page cache for chunk I/O, and at `vm.swappiness=60` it
bought that cache by paging out JVM heap. GC then had to fault those pages back off disk.

**`start.sh` had already predicted this.** Its own comment read *"2G heap + ~500MB JVM
overhead leaves ~600MB headroom. Do not raise further without re-measuring `free -h` with
the server stopped."* The flags immediately below it said `-Xms5G -Xmx5G`. **The comment
was not updated when the value was changed**, so the warning sat there being ignored.

**Size the heap from the live set, not from total RAM.** `spark health --memory` gives it
directly - *G1 Old Gen "Usage at last GC"*, which was **2.3 GB**, plus 366 MB non-heap.
Measured with the server stopped, everything else on the box (next-server, PM2,
another service, another service, journald) needs **~450 MB**, leaving 7.0 GB available.

Set to **4G**: live set keeps ~1.7 GB of headroom and ~2.5 GB is left for page cache.

| | 5G heap | 4G heap |
|---|---|---|
| free | 256 MB | **1.0 GB** |
| JVM VmSwap | 186 MB | **0** |

Old `start.sh` kept as `start.sh.bak-5G-2026-09-01`. Note `start.sh.bak-4G` from
2026-08-13 already exists - this has been tuned back and forth before.

**Still worth doing (needs the sudo password, so it is the owner's to run):**
`vm.swappiness` is **60**. At 10 the kernel strongly prefers dropping page cache over
paging out a running JVM, which is what you want on a game server.

### Reading spark at all

**`spark` returns nothing over rcon.** Its output goes to the command sender through a
path rcon does not capture, so `python3 rcon.py "spark tps"` prints an empty string and
looks broken. It is not - run the command, then read `logs/latest.log`:

```bash
L=$(wc -l < logs/latest.log); python3 rcon.py "spark tps" >/dev/null; sleep 2
tail -n +$L logs/latest.log | grep -v RCON
```

`spark profiler` uploads to a spark.lucko.me URL, which is a JavaScript app - **not
fetchable as text**. For anything you need to read programmatically, use
`spark health --memory` and parse the log.

### Entity counts over rcon

`execute if entity <sel>` returns "Test passed", not a number. To get a **count**, store it:
`execute store result score #c <obj> if entity @e[type=item]`, then read it back with
`scoreboard players get`. Same reasoning as §82 - prefer commands that return a number.

### The RCON log flood was a design bug, not a cadence problem

`stackguard.py --loop` was writing ~49,000 of the ~50,000 lines in `latest.log`. The obvious
read is "it polls too often". The real cause was that **`rcon()` shelled out to
`python3 rcon.py` per command**, so every single command paid a Python interpreter start
*and* opened a fresh TCP connection - and vanilla logs two lines for every RCON
connect/disconnect. ~36 processes and ~72 log lines a minute, forever.

Holding **one socket open for the whole 55s loop** fixed it without touching protection at
all. Measured after: **2 RCON lines per minute, down from ~82** - a 41x cut, and one python
process per minute instead of ~37.

Cadence was separately relaxed 3s -> 15s (2026-09-01, owner's call: the players now know to
pick lapis up while Titan-hammering with Fortune, so this is a backstop). 15s still leaves a
wide margin against a 5-minute autosave. A subprocess fallback was kept so a socket failure
degrades to the old path rather than silently guarding nothing, and it was **verified
end-to-end** - plant a 70x stack with `summon item`, let the real cron loop find it, confirm
`CLAMPED 64` in `logs/stackguard.log`. Old copy at `stackguard.py.bak-3s-2026-09-01`.

**The general lesson:** before slowing a poller down, check what one poll actually costs.
This one was cheap to run and expensive to *call*.

### Two rcon footguns hit while testing this

**`setworldspawn ~ ~ ~` over rcon sets spawn to WORLD ORIGIN.** Same trap as 82's
`playsound ~ ~ ~`: `~` is the *console's* position, not a player's. There is no command that
merely reads world spawn, so do not reach for `setworldspawn` to find out - read
`SpawnX/SpawnY/SpawnZ` out of `world/level.dat` instead. Caught and restored the same
minute, because level.dat still held the pre-save value.

**A wide `kill @e[type=item,...]` is not a safe cleanup.** `distance=..120` around origin
killed 7 items, only one of which was the test stack. That was harmless purely because both
players happened to be ~200,000 blocks away. Tag what you summon
(`summon item ... {Tags:["sgtest"]}`, then `kill @e[tag=sgtest]`) rather than clearing a
radius that could contain someone's dropped loot.

## §92 - the wiki build depended on three files that only existed in /tmp

Found 2026-09-01 while auditing for loose ends, not because anything broke.

`build3.py` opens **three** inputs at the top:

```python
P  = json.load(open('/tmp/wiki_parts.json'))    # dex payload
D2 = json.load(open('/tmp/wiki_data2.json'))    # items/structures/bait/cuisine/mods
D3 = json.load(open('/tmp/wiki_data3.json'))    # guides/tex/furnies/chipped_fams
```

`build-wiki.sh` regenerates **none of them**. It runs `wikiclientpkg.py` and
`wikiindex.py`, and `wikiindex.py` produces only `wiki_recipes.json`. The other three were
built once by one-off scripts that were never committed (`dossier2.py` and friends, still
sitting untracked at the repo root) and dated **2026-08-11 and 2026-08-22**.

**`/usr/lib/tmpfiles.d/tmp.conf` contains `D /tmp 1777 root root -`.** The `D` directive
empties the directory **on boot**. The box happened to have 20 days of uptime. A single
reboot would have made the wiki permanently unbuildable - and it would have failed
*quietly*, because the deployed `mc-wiki.html` lives in the website repo and would have
carried on serving perfectly while every future build was impossible.

**Fixed:** the three now live in `$COBBLEMON_DIR/wiki-inputs/`, and `build-wiki.sh`
restores any that are missing from `/tmp` before building, aborting loudly if both copies
are gone. A gzipped set is committed at `tools/wiki/wiki-inputs.tar.gz` (1.0 MB) as a
last-resort backup.

**Verified by falsification rather than assumed:** moved `/tmp/wiki_data2.json` aside, ran
the build, watched it print `restored wiki_data2.json from wiki-inputs/` - and the output
came out **byte-identical** (`sha256 6acabaec...`) to the page already live, which also
proves the build is reproducible.

**The general shape of this bug:** a pipeline whose inputs are older than its scripts.
`wiki_recipes.json` was hours old; the other three were weeks old and had no generator.
When a build reads a path under `/tmp`, ask what recreates it - and if the answer is
"nothing", that is not a cache, it is the only copy.

## §93 - the Instant-Dex: dust is not spent per scan, and the outer jar is empty

Owner built an Instant-Dex, calibrated a disk to Vivillon, and deliberately loaded **no
dust** because they assumed each scan would consume some. Reasonable, and backwards.

**Dust is never spent by a scan. It sets the card's RARITY, and it is read exactly once -
at the moment the 5th scan lands.** In `InstantDexItem`:

```
618  if scanCount >= 5  -> 728
624  (under 5) new DiskData(... DiskData.dust() ...)   // copied forward untouched
730  DiskData.dust()  ->  generateCard(player, pokemon, dust)   // read here, only here
738  disk stack method_7934(1)                                  // disk consumed
```

So scanning four with an empty disk and topping up before the fifth is free. Nothing in
game says this; the tooltip just says "Potential Rarity".

| dust on disk | rarity |
|---|---|
| 0-49 | Common |
| 50-199 | Uncommon |
| 200-499 | Rare |
| 500-999 | Epic |
| 1000 (cap) | Legendary |

Loading accepts dust (1), pouch (9) and sack (81), largest-that-fits. 1 pouch = 9 dust,
1 sack = 81. **Instant-Dex costs 81 dust once and is never consumed; each disk costs 9 and
is consumed at the 5th scan.**

**Why the tool is worth building at all is buried in a config comment**, not in any
tooltip - `config/cobblemon-cards-species-rarity.json`:

> *"Instant Dex and administrator-created cards intentionally bypass these restrictions."*

The restrictions are real: for a **common**-tier species the weights are Common 200,
Uncommon 10, and **Rare/Epic/Legendary literally `0.0`**. A booster pack can never produce
a Legendary of an ordinary Pokemon. The Instant-Dex is the only route. **Read a mod's
config `notes` array - it documented the single most important fact about this item.**

### Rules that quietly eat scans

- **Wild only.** `Pokemon.getOwnerUUID() != null` -> refused. Includes your own and other
  players' - you cannot line up a friend's Pokemon for a scan.
- **Five DIFFERENT individuals**; the same one twice gives "already scanned".
- **`findStructureDiskSlot` returns the FIRST disk in the inventory.** A second disk in the
  bag can silently take the scan. Carry one.
- A fresh disk is blank - `targetSpecies` is an empty Optional, and **the first scan
  calibrates it permanently**.
- Progress rides on the item, so a badly calibrated disk can be shelved in a chest
  indefinitely. Nobody is ever locked in.

### The outer jar had 10 classes in it

`cobblemon-cards-fabric-1.0.4.jar` contains only a Fabric shim. Every class that matters is
in **`META-INF/jars/common-1.0.0.jar`**. A `grep -rl` over the extracted outer jar for
`instant_dex` returned **nothing**, which reads exactly like "this feature does not exist".
This is the §"recurse into META-INF/jars" rule biting for the third time - it is not just for
dependencies, some mods ship their whole implementation there.

**Fastest way in was `assets/<ns>/lang/en_us.json`.** Before touching bytecode it gave the
whole design: "The disk is calibrated for: %s", "You can only scan wild Pokemon!",
"already scanned", "Potential Rarity", "Accumulated Card Dust". Same lesson as §90 - read
the lang file first, then confirm the numbers in code.

### The Instant-Dex scans PLAYERS, and that unlocks You & Mew

Initially written up as "a lead, not a route" because the Mew branch searches the inventory
for a card whose `pokemonId()` starts with the player's own UUID and I could not say what
made one. The owner pushed back - *"I don't know what you're talking about"* - which was
the right call: a half-identified code path should not have gone on the wiki at all.

**`CardUtil.isCosmeticCard()` resolves it in one method.** Seven ids are cosmetic, tied to
no species: anything starting with **`player_`**, plus `you_and_mew`, `ghost`, `god_bidoof`,
`crystal_onix`, `shadow_lugia`, `pride_sylveon`.

`player_` is the missing piece. The lang file confirms the mechanism:
`message.cobblemon-cards.instant_dex.player_capture_complete` = *"Successfully created
cosmetic card for %s!"*. **Point the Instant-Dex at a person and it makes a cosmetic Player
Card of them** - instant, no disk calibration, no five-scan count. That is an entire
undocumented feature of the tool.

So You & Mew is: make your Player Card, carry it, scan a **wild Mew**. The card is consumed
and you get the **mythic** `you_and_mew` - the only Mythic the Dex produces, and it skips
the scan count.

**Method note:** the answer was one `isCosmeticCard` method plus one lang key. When a code
path tests for something you cannot name, look for the *validator* that enumerates the
category - it is usually a single method listing every member.

### Mewtwo has exactly three forms here

Checked because the owner asked whether Armored Mewtwo exists. **It does not.** Cobblemon's
`mewtwo.json` ships **Mega-X** and **Mega-Y** and nothing else, in every jar that defines
it. Mewtwo is **not** gmax-capable.

The confusing part: `cobblemon-cards` ships **`mewtwo_armored.png`** and
**`mewtwo_shadow.png`** card artwork. The card mod carries art for form variants that other
addons provide, so **artwork is not evidence a form exists**. Check the species JSON, not
the texture list. (`myutu` is Baby Legends' baby Mewtwo - a separate species, not a form.)

Charizard and Mewtwo are the only two species with a **choice** of Mega: Mewtwonite X from
a **Punching Glove**, Mewtwonite Y from **Wise Glasses**.

## §94 - "Gave" from /give does not mean the player has it

2026-09-01. a player completed Generation IV; `logs/arcphone-rewards.log` recorded

```
2026-09-01 22:39:01 GRANTED a player -> cobblemon-cards:booster_pack_gen4
```

and he did not have the pack. `deliver()` logs GRANTED only when the give response contains
`"Gave"`, so the command **was accepted** - and the caller then persisted state on that
`True`, so **the cron never retried and the reward was silently lost**.

### Ruled out, one at a time

- **Item id wrong** - no: `cobblemon-cards:booster_pack_gen4` is real, and a manual give of
  the identical command worked immediately.
- **Inventory full, dropped at feet, despawned** - no: 30 of 36 slots used, and
  `free_main_slot()` would have held it rather than granting.
- **He died or relogged** - no deaths, no disconnects in the window.
- **He opened it** - nothing in the log, and no card-mod pack-open activity for him.
- **Stale player file** - he was ONLINE, so `world/playerdata/*.dat` is his last save, not
  live state. That file proves nothing about an online player; query the server instead.

**Best remaining lead, unproven:** he had an Arc Phone **Ender Chest screen open** ~49s
before the give. Handing a player an item while they have a container GUI open is a known
source of client/server desync. Not demonstrated, so it is recorded as a lead.

### The probe that makes this checkable

**`clear <player> <item> 0` is read-only** - it reports `Found N matching item(s)` and
removes nothing. Verified against items the player demonstrably had before trusting it,
which is the step that turned "he says he didn't get it" into a fact.

**Do not use `give <player> <item> 0`** to probe - that errors with *"Integer must not be
less than 1"*.

### Fix

`deliver()` now confirms with that probe **after** the give and returns `False` if the item
is not actually present, leaving the reward pending for the next pass and telling the player
to close any open menu. GRANTED now means *verified in hand*, not *command accepted*.

**The general rule:** a command's success response describes the COMMAND, not the world. Any
delivery whose state is persisted on success needs a read-back before it commits. Same shape
as §82 (parse a number, not a structure) - trust a measurement, not an acknowledgement.

Old copy at `rewardutil.py.bak-2026-09-01`. a player was re-delivered his pack manually and it
landed and was verified.

## §95 - the Instant-Dex is a dust sink at every tier, and §93 failed to say so

The owner spent their entire dust reserve building an Instant-Dex plus a disk on the
reasonable reading that it was a way to farm dust. It is the opposite. §93 documented that
the tool beats the rarity table and never stated the cost, which is the omission that let
that assumption stand.

**Recycler payout, from `CardRecyclerBlockEntity.calculateDustAmount`:**

```
common 1 | uncommon 2 | rare 3 | epic 5 | legendary 10 | mythic 15   (default 1)
  isShiny()          -> x2
  shouldHaveBackground() -> +1
  hasHoloEffect()        -> +1
```

**The ledger.** A disk is 9 dust and is consumed by every card, and the charge dust is
**destroyed rather than carried into the card** - rarity is only a threshold read at the
fifth scan, so charging is expenditure, not investment.

| target | dust in (9 + charge) | recycles for | net |
|---|---|---|---|
| Common | 9 | 1 | **-8** |
| Uncommon | 59 | 2 | **-57** |
| Rare | 209 | 3 | **-206** |
| Epic | 509 | 5 | **-504** |
| Legendary | 1009 | 10 | **-999** |

The best card that can exist - shiny Legendary with a background and a holo - returns
**22** against 1009. It never profits, and **the loss grows with rarity**.

**The cosmetic Player Card costs a full disk too.** The player branch calls
`method_7934(1)` on the disk stack before `generatePlayerCard`, exactly like a finished
five-scan run. 9 dust for a joke card.

**So booster packs remain the only real dust income.** The Instant-Dex's value is entirely
collection-side: a card of a chosen species at a rarity packs can never roll, since a
common-tier species has Rare/Epic/Legendary at weight `0.0`.

**The lesson for this wiki:** documenting what a thing *enables* without documenting what it
*costs* is how a reader ends up spending everything on it. When a mechanic has a price, the
price belongs in the same section as the capability - not left for the player to discover by
paying it.

## §96 - loot tables roll on FIRST OPEN, so a datapack reaches already-generated chests

Asked whether the booster-pack datapack (§ nifty-booster-loot) would only affect newly
generated villages. **It does not.** Worldgen writes a chest with a `LootTable` tag (plus
`LootTableSeed`) and leaves it empty; the contents are rolled the first time a player opens
it, using whatever loot table is loaded **at that moment**.

**Verified by reading region files rather than trusting the mechanic.** Scanning 9 `.mca`
files around one located village found the tags still sitting there unrolled:

```
bca:general/kitchen  34   bca:general/bedroom      9
bca:general/pokecenter 16 bca:general/sittingroom  8      = 67 unopened chests
```

So the ~30 waypointed-but-unlooted villages all get the new chance. Only chests already
**opened** are fixed, because opening is what consumes the tag.

**Region file header trap:** the 1024 location entries are **4 bytes each** - offset is the
top 3 bytes, sector count the low byte. `struct.unpack_from(">IB", ...)` reads 5 and
desyncs the whole table.

**And a false positive to expect:** grepping decompressed chunks for `bca:general/` also
matches **jigsaw structure** references, not just chest loot tables - `bca:general/lamp_posts/
lamp_post_bench` is a `.nbt` structure path. Filter by the known table names.

## §97 - the items page was hiding 92 recipes, not merely lacking them

Owner: *"the items and recipes page feels overall very incomplete."* Correct, and an audit
(`tools/wiki/itemaudit.py`) separated "we have no data" from "we have it and do not show
it". Only the second is a bug, and it was 92 items.

**Audit it against the BUILT page, not the input.** `/tmp/wiki_data2.json` has no `g`
(recipe) or `s` (source) fields - build3.py adds those at render time - so auditing the input
reports 0 recipes for all 2,659 rows and looks catastrophic. Extract the items payload out of
`mc-wiki.html` instead.

**Cause: three Cobblemon recipe types `parse_recipe` did not know.** Cobblemon cooks in a
**Campfire Pot** and brews in its own brewing stand:

| type | items | shape |
|---|---|---|
| `cobblemon:cooking_pot_shapeless` | 51 | `ingredients` list, like crafting_shapeless |
| `cobblemon:brewing_stand` | 25 | `input` + `bottle` |
| `cobblemon:cooking_pot` | 16 | `key` + `pattern`, a real 3x3 |

That covered every aprijuice, sweet, mochi, malasada and candied berry, every medicine
(Antidote, Awakening, Burn Heal) and vitamin (Calcium, Carbos), and Old Gateau - which is
where this started, since its recipe was on the Mechanics page but not the item's own row.

Result: 1254 -> **1346** rendered recipes, exactly the predicted 92, bug class now **0**.

**When adding a kind index, keep the fallback slot.** `_KINDS.index(k) if k in _KINDS else 3`
means index 3 is "anything unrecognised", so new kinds must be appended AFTER it
(`['shaped','shapeless','furni','','pot','potless','brewing']`) and the template's label
array kept aligned position for position.

### What is left, and what it actually is

976 rows still show neither recipe nor source (37%). Characterised, not guessed:

- **326 Cobbreeding eggs** (`bug_dark_pokemon_egg` and every type pairing) - from breeding,
  never craftable. Needs one sentence, not a recipe.
- **~517 "other"**, including `ancient_*_ball_model` and `*_rod_cast` intermediates.
- **152 are in a loot table** but render no source line - mostly CobbleFurnies chairs and
  stools dropping from their own blocks. This one IS still a bug.
- Regi tablets: correctly sourceless (statue rewards, documented on the Pokedex).
- 7 worldgen blocks, 4 creative-only.

## §98 - filling the last 976 blank source cells, and three ways I got it wrong first

Follow-on from §97. Every one of the 2,659 item rows now states a source, up from 1,683.
Three distinct causes, and my first attempt at each was wrong in an instructive way.

### 1. A block that only drops itself is not unobtainable

`_classify` returns `None` for `blocks/<self>` - correct, "mined from itself" says nothing.
But when that was an item's ONLY entry the row went blank, which reads as unobtainable. 152
rows, mostly CobbleFurnies.

**The real answer is usually "something places it, go mine one."** `wikiindex` already
decompresses every structure `.nbt` for the legendary-structure map, so a second regex on
the same raw bytes gets block placement for free - no extra I/O, 1,412 block ids.

**But the scan matches ids inside a template's CHESTS as well as placed blocks**, so
"Generates in X - mine it to collect one" was wrong for a Cherish Ball. Reworded to
**"Found in X"**, which is true either way. Village template pools are also named after
their variant folder (`dark`, `default`, `fairy`), which means nothing to a reader - those
collapse to "a Cobblemon Additions village".

### 2. wikiindex only ever read the mod jars

**It never looked at `world/datapacks`.** So every booster pack - the single most important
reward item in the pack, and the whole point of the loot table added the day before -
rendered with no source at all. Datapacks override mod data on this server; the index has to
read them the same way. Now does, and packs list their rooms and odds.

**Generalise this:** any index built by walking `mods/*.jar` is blind to
`world/datapacks/`. The dex spawn reader already had this fixed (see the regional-forms
note); the item indexer did not, and nobody noticed for months because the symptom was a
blank cell rather than an error.

### 3. "Creative only" was a claim I could not support

My first fallback said *"No recipe and generates nowhere - creative only"*. It fired on
**902 rows**, including all **326 Cobbreeding eggs**, which are produced by breeding two
compatible Pokemon in a Pasture and are not craftable by design. Also every booster pack,
via cause 2.

**A false source is worse than a blank one** - the whole value of this wiki is that it is
more trustworthy than guessing. The fallback now states only what was actually checked:
*"Not found in any recipe, loot table or structure"*, with Cobbreeding eggs given their real
answer.

**The rule:** a fallback may describe what the search found. It may not infer intent. "I did
not find a source" and "there is no source" are different sentences, and only the first one
is verified.

## §99 - Gigantamax visuals come from Mega Showdown, not Cobblemon

Owner asked whether a Gigantamax Snorlax has its own model or just scales up with the red
halo, because it decides whether a shiny hunt is worth continuing.

**Cobblemon itself ships almost no gmax art** - two textures (Pikachu, Eevee) and nothing
else. **Mega Showdown supplies it**, shipping `assets/cobblemon/...` overrides: 24 models,
24 animations, 25 posers, 26 resolvers, 78 textures. Look in the wrong jar and you conclude
the models do not exist.

**24 of the 32 gmax species have a model in 1.9.3.** The 8 without: appletun, centiskorch,
flapple, grimmsnarl, hatterene, inteleon, kingler, **lapras**. 1.9.4's changelog reads
"Added all gmaxes", so an update likely fills those - see §89 for why we are still on 1.9.3.

**Snorlax has both a model and a distinct shiny texture** (`snorlax_gigantamax.geo.json`,
`snorlax_gigantamax_shiny.png`).

**The model is driven purely by the `gmax` aspect**, with an explicit `["gmax","shiny"]`
resolver variation. Nothing about the battle or the Power Spot is in the resolver - those
gate *reaching* the state, not rendering it. That is what makes a display-only toggle
possible at all (`/pokeedit <slot> <properties>` exists).

**Max Soup changes nothing about base stats or moves.** It sets `GmaxFactor`, which decides
Gigantamax vs plain Dynamax. Plain Dynamax = scale-up + halo on the base model; Gigantamax =
the distinct model plus the species' `gmaxMove`. An unfed Butterfree has identical stats and
identical moves outside of Dynamax.

### Mega out of battle already works, and nobody knew

`outSideMega` is **already true** on this server, and `CobbleClientEvents.addGimmickButtons`
uses it to add a **Mega Evolve button to the Pokemon interaction wheel** -
sneak + right-click your own sent-out Pokemon, same wheel as the cosmetic items and the
Zygarde cube. `outSideUltraBurst` adds an Ultra Burst button the same way.

**Only Mega and Ultra Burst get wheel buttons.** There is no out-of-battle Dynamax or
Gigantamax path in the mod - `dynamaxAnywhere` only removes the *Power Spot* requirement,
it does not remove the requirement to be in a battle.

## §100 - items page: 100% sourced, and two things deliberately NOT added

Final state after §97/§98: 2,659 rows, 1,346 with a rendered recipe, **2,659 (100%) with a
source**, **0** hidden recipes, **0** blank cells.

**Deliberately excluded, because adding them would mislead:**

- **`botanypots:crop` - 86 recipes.** Cobblemon ships Botany Pots compatibility, and
  **Botany Pots is not installed here**. Rendering "grow this in a Botany Pot" would send
  players after a block that does not exist. Check the mod is present before surfacing its
  compat recipes.
- **`ancient_*_ball_model` / `*_rod_cast`.** No recipe, no loot table, no structure, no lang
  entry beyond a statistic. They are registry artifacts; the page correctly says it found
  nothing rather than inventing a route.

**A `type` count over `**/recipe*/**` is inflated by advancement files.** 724 entries came
back with `type: None` - those are `data/<ns>/advancement/recipes/*.json`, matched because
the glob `/recipe` also hits `/recipes`. Filter on `/recipe/` exactly.

## §101

Deleting a file from `/var/www/dl/` does not unpublish it. Cloudflare caches that path with
`max-age=86400`, and a zip removed from disk still answered `HTTP 200` with
`cf-cache-status: HIT`. There is no purge credential on the box, so a link stays live for a
day after you retract it.

Two rules follow. The content hash in the filename is not optional -- reusing a name once
served a stale build that a player installed. And every published zip has to be internally
self-consistent, its own read-me matching its own jar, because whoever already has the old
link will keep getting the old zip no matter what you replace it with.

## §102

When shipping a mod upgrade to players who will not edit their mods folder, put the new jar
under the OLD jar's filename. Two versions of one mod in `mods/` crashes on launch, and
"delete the old one first" is precisely the step that gets skipped. Under the old name the
drag is an overwrite -- Windows asks "replace?", they say yes -- and there is no state in
which both jars exist.

This is safe because Fabric and Mod Menu read the version from `fabric.mod.json` inside the
jar and never from the filename. Confirm it before shipping rather than assuming:

    unzip -p new.jar fabric.mod.json | python3 -c       "import json,sys; print(json.loads(sys.stdin.read(), strict=False)['version'])"

The 1.9.5 jar shipped as `mega_showdown-fabric-1.9.3+1.7.3+1.21.1.jar` and Mod Menu reports
1.9.5. Say so in the read-me, so nobody who checks the filename thinks the update failed.

## §103

`pokeedit <slot> form=normal` reverts a Gigantamax display, and `form=gmax` applies it. This
replaces `msd hard_reset`, which was the only revert we knew: hard_reset wipes megas across
the player's whole party AND PC and clears GmaxFactor, throwing away the Max Soup they spent.
`form=normal` touches one Pokemon and leaves GmaxFactor alone, so the toggle is genuinely
two-way and the entitlement survives.

Everything else still silently does nothing: `dynamax_form=none`, `dynamax_form=normal`,
`unaspect=gmax`, `gmax=false`. All five print "Edited <player>'s <mon>." identically. Only
the NBT is evidence.

Read that NBT more than once. A single read after a fixed 4s delay showed a working revert as
a no-op, and the wrong conclusion went into a script's output as "round-trip clean" because
it checked the final state instead of whether each step changed anything. Sample repeatedly.

## §104

Mega Showdown 1.9.5 renders 32 Gigantamax species, up from 24. Do not derive that list by
scanning one jar: `alcremie`'s poser and model come from base Cobblemon, and `pikachu`'s
region-bias texture lives under `resourcepacks/regionbiasmsd/assets/...` inside the MSD jar
rather than at the top-level `assets/`. Scanning MSD alone reports 22 and wrongly drops both.
`tools/gmaxassets.py` checks the union of every jar; re-run it after each update.

Resolver fields are namespaced and the geometry is named differently from the aspect:
    poser   "cobblemon:snorlaxgmax"             -> posers/snorlaxgmax.json
    model   "cobblemon:snorlax_gigantamax.geo"  -> models/**/snorlax_gigantamax.geo.json
Matching on the string "gmax" alone finds no geometry at all, because the geo files are named
`*_gigantamax`.

## §105

The 2-seat resource pack silently reverts model fixes. It overrides ~116 MSD geometries with
copies taken from an older jar plus a `locator_seat_2` bone, so any model the mod later
changes is replaced on the client by our stale copy. After 1.9.5 that is 26 models, 24 of
them megas.

This is worse than it sounds when the mod also updates the matching texture: 1.9.5 shipped a
new `blastoise_mega.geo.json` AND a new `blastoise_mega.png`. Our pack forces the old
geometry while the jar supplies the new texture, and the UVs no longer correspond - the body
gets painted from the shell's region of the sheet. Regenerate the pack against the current
jars on every MSD update, not just when a new mount is added.

## §106  (WRONG - superseded by §108, kept so the mistake is not repeated)

I claimed a cosmetic item wrecked the Gigantamax Blastoise model: Cobblemon's
`0_blastoise_base.json` adds a glasses render layer on `cosmetic_item-black_glasses` with no
form guard, the layer texture is 256x256 and `gmaxblastoise.geo` declares 512x512, so the
layer smears over the whole body. The mechanism is real and the numbers are right. It was not
the cause. The owner removed the cosmetic and the model was still wrong; the actual cause was
a resource pack whose resolver stopped overriding after a rename (§108).

Two failures worth keeping. I never TESTED the hypothesis before reporting it as the answer -
removing the item was a ten-second experiment available the whole time. And a mechanism that
fits the symptom, plus a correlation (one Pokemon in six looked wrong and it was the only one
wearing a cosmetic), is not proof; it is a reason to run the experiment.

Also, on the numbers: a texture SMALLER than the declared UV space is not automatically
broken. Bedrock scales the image to the space the geometry declares, which is exactly how a
higher-resolution texture pack works. See §108.

## §107

Diagnose from the entity's own data BEFORE diffing assets. This one cost hours: two jars were
unpacked, geometry compared bone by bone, posers and animations parsed, textures hashed,
resource packs regenerated - and the answer was a single NBT field, `CosmeticItem.id`, that a
full dump would have shown immediately.

The tell was available from the start and was ignored: exactly one Pokemon in the party looked
wrong, and it was the only one carrying a cosmetic item. When one instance misbehaves and
others of the same kind do not, the difference is in the instance, not in the shared assets.
Dump every field of the broken one next to a working one and read the diff.

## §108

A resource pack that overrides a mod file stops overriding it the moment the mod RENAMES that
file - and what was a clean replacement silently becomes a duplicate.

CCCwLegendSpawns shipped `3_blastoise_gigantamax.json`, exactly matching Mega Showdown 1.9.3.
The pack's resolver, model, poser, animation and texture therefore all won together as a set.
1.9.5 renamed the mod's file to `3_blastoise_gmax.json`. Now both load, both at order 3, both
claiming `["gmax"]`; `gigantamax` sorts before `gmax`, so the mod's loads last and takes the
model slot, while the pack still wins the TEXTURE because both write the same path. The
result is the mod's 112-bone `geometry.blastoise` painted with art drawn for the pack's
59-bone `geometry.gmax_blastoise`.

Do not diagnose this as a resolution mismatch. A 256 texture on a 512 UV space is perfectly
fine by itself - Bedrock scales the image to the geometry's declared space, which is exactly
how a higher-resolution texture pack works. Several of this pack's overrides do that
deliberately and render correctly. The fault is the model and the texture coming from
different SOURCES, having been authored against different geometry.

So the check to run after any mod update is not "do the sizes match" but "for each resolver
variation, do the model and the texture resolve to the same source?" `tools/mkcccfix.py`
documents the fix; the split-pair scan found 11, of which only Blastoise, Orbeetle and Latios
are ordinary forms rather than obscure aspect combinations.

## §109

Players can be given admin-gated abilities with no client download at all, using a vanilla
`trigger` objective. `/trigger` is the one scoreboard command an unprivileged player may run,
so `scoreboard objectives add <name> trigger` plus a poller is a complete, permission-free
interface:

    /trigger gmax set 3

A trigger disarms itself after each use, and a player who has just joined has never had it
armed, so the poller must re-enable it periodically. Clear the score BEFORE acting on it, or a
slow action re-fires on the next poll. `tools/gmaxwatch.py` is the working example.

This beats a datapack function whenever the decision needs data no command can read - here the
gate is `GmaxFactor`, which lives in the party-store NBT and is invisible to mcfunction.

## §110

The Gigantamax halo is positioned by DATA, not code, and the data lives under `assets/` - so a
resource pack can retune it and F3+T reloads it with no restart and no server change:

    assets/mega_showdown/msd_sizer/<name>_clouds.json
    { "pokemon": "<name>",
      "size_config": { "Gmax": { "msd:dmax": {
          "scale": [x,y,z], "translate": [x,y,z], "rotation": [x,y,z] } } } }

`DynamaxCloudsLayer` attaches the halo to a `clouds_loc` locator, falling back to `head`, then
applies these settings via `LayerDataLoader.getSettings(pokemon, "msd:dmax")`.

Mega Showdown 1.9.5 ships seven of these against 32 species with a gmax model, so 25 render at
the default transform. Charizard has an entry that sets `scale` but no `translate`, while every
other tuned species sets both - the likely reason its halo sits wrong.

Related, from the same disassembly: the 4x battle size is applied through
`Pokemon.setScaleModifier()`, a PERSISTENT field, with the previous value stashed in
PersistentData as `orignal_size` (the mod's spelling). `startGradualScaling` sets it and
`startGradualScalingDown` restores it. Setting a form directly never touches it, which is why
a display-only gmax stays normal-sized and stays rideable.

`tools/mkhalopack.py` scaffolds a tuning pack: the mod's own values where they exist, an
explicit identity transform marked UNTUNED elsewhere, so guesswork is visible rather than
disguised as tuned numbers.

## §111

Two corrections to §108's method, both found by the owner testing rather than by me.

A resource pack overriding a jar file is only a problem if the CONTENT differs. The first
split-pair scan flagged any variation whose model and texture resolved to different sources,
which over-reported: a pack shipping a byte-identical copy changes nothing. Comparing bytes
cut 11 flagged splits to 10 and removed Orbeetle entirely, which I had been about to describe
as broken.

And "nobody owns one" was the wrong claim. Party and PC stores are not the only place a
Pokemon lives on this server: a player's Latios and a player's Orbeetle are CARDS, held as
`cobblemon-cards:card_data.pokemon_id` inside binder contents in playerdata. Card art is a
flat entity_icon texture so a model/texture split does not affect the card itself - but a card
can be redeemed, so it still counts as owning one. Search playerdata for card_data as well as
walking the Pokemon stores before saying nobody has a species.

## §112

Resource packs on 1.21.1 use `pack_format` 34. Datapacks use 48. Copying the number from a
neighbouring DATApack put 48 in a resource pack, and the game refused it as "made for a
different version" - so edits to it appeared to do nothing at all rather than failing loudly.
The 2-seat pack has always had 34; check against a pack of the SAME KIND that is known to
load.

## §113

`/trigger` disarms itself the moment it is used, and a player who has just joined has never
had it armed at all. Re-arming on a 20s timer meant several uses in a row hit "you cannot
trigger this yet", which reads to the player as the feature being broken. Re-arm every poll.

Separately, a revert that reads the saved NBT ONCE reports failure on reverts that worked -
the save is asynchronous and the first read beats it to disk. The apply path already retried;
the revert did not, and logged REVERT FAILED on a Corviknight that had in fact reverted. This
is §103 written down and then not applied, in the same file, hours later. Sample repeatedly on
BOTH directions.

## §114

Bedrock locators are entries in a bone's `locators` object. They are NOT bone names. I checked
bone names, concluded 17 of 32 gmax models had no `clouds_loc` and that Snorlax's was a
four-character typo, and told the owner so. Both claims were false. Checking the real field
gives 30 of 32 declaring `clouds_loc`; only garbodor and melmetal lack one, and Snorlax's
`clouds` bone carries a perfectly correct `"locators": {"clouds_loc": [0, 49, 0]}`.

    "name": "clouds", "parent": "snorlax", "pivot": [0,0,0],
    "locators": { "clouds_loc": [0, 49, 0] }

What the data does show is that the locator's PARENT BONE varies a lot, and that is visible in
game: blastoise gets a dedicated `clouds_loc` bone, charizard's hangs off `tail` (which the
owner spotted unaided), and corviknight, pikachu, urshifu, rillaboom, cinderace and butterfree
hang theirs off `head`, where the halo sits tight to the body and rotates with head-tracking.
There is exactly ONE halo model and texture for every species - `dmax_clouds.geo.json`, 32
bones, id `geometry.pikachu_gmax`, with a Calyrex-only blue variant - so any difference in
appearance is placement and scale, never model quality and never CCC versus Mega Showdown.

The lesson is narrower than "check the field": when a scan's result contradicts something the
mod plainly does (30 species render a halo fine), suspect the scan before writing up the
finding.

## §115

Removing a resource pack's override can expose a gap the pack was covering. Dropping
CCCwLegendSpawns' Blastoise gmax set fixed the texture fault (§108) and immediately broke the
walk animation, because the pack's poser defined six poses and Mega Showdown's defines two.

The mod ships 26 animation clips for `blastoisegmax` - ground_walk, ground_run, water_idle,
water_swim, sleep and more - and its poser references three of them. With no WALK pose the
model plays its idle while moving, which reads in game as walking diagonally. It also explains
an older observation that gmax Blastoise "does not spin in its shell": `ground_run` is shipped
and never referenced.

The pack's poser cannot just be kept, because its `rootBone` is `blastoisegmax` to match its
own 59-bone geometry while the jar's model roots at `blastoise` with 112 bones. Rebuild the
poses against the JAR's rootBone and the JAR's clip names instead - `tools/mkgmaxfixes.py`.

Scanning all 32 gmax posers for poseTypes that are uncovered DESPITE a matching clip existing
found only two species: blastoise (WALK, SWIM, FLOAT, SLEEP) and corviknight (SLEEP).

The general lesson: when a fix removes files, check what those files were PROVIDING, not just
what they were breaking.

## §116

`PokemonInteractionGUICreationEvent.getPokemonID()` returns the world ENTITY's uuid, not the
Pokemon's. They are different values, so passing it to `ClientParty.getPosition()` always
returns -1 and any code keying off the party silently does nothing. Mega Showdown never hits
this because it forwards the id to the server and resolves it there.

    val entity = level.entitiesForRendering()
        .firstOrNull { it.uuid == event.pokemonID } as? PokemonEntity ?: return
    val slot = CobblemonClient.storage.party.getPosition(entity.pokemon.uuid) + 1

Diagnosed by logging both uuids side by side: entity 038ad6d7..., Butterfree dcf3f397....
Guessing at it would have been hopeless; the log made it a five-second answer.

## §117

Cobblemon's `PoseType` has no RUN or SPRINT value: STAND, WALK, SLEEP, HOVER, FLY, FLOAT,
SWIM, GLIDE, SHOULDER_LEFT, SHOULDER_RIGHT, PROFILE, PORTRAIT, OPEN, NONE. Sprinting is a
SECOND pose with poseType WALK carrying a `q.is_sprinting` condition, exactly as Cobblemon's
own base Blastoise poser does:

    walk  poseTypes=[WALK]  condition=!q.is_sprinting  -> ground_walk
    run   poseTypes=[WALK]  condition=q.is_sprinting   -> ground_run

Two poses may share a poseType only if something distinguishes them - a `condition`, or
`isBattle`. Two UNCONDITIONED poses claiming the same poseType is ambiguous; base Blastoise
avoids it by putting `!q.is_ridden` on its surfacewater variants, and copying its structure
without that condition reintroduced the ambiguity until a check caught it.

Corviknight's gmax poser is the worst example of the underlying problem: four poses, and all
four play `ground_idle` - including `fly` and `walking` - while its `air_fly` and `ground_walk`
clips go unreferenced and it has no sleep pose. Ride-specific clips (`ride_ground_run` etc.)
exist for base models but not for the gmax ones, so a ridden gmax Pokemon falls through to the
ordinary walk/run poses.

Cinderace's gmax poser writes its expressions as `bedrock(cinderacegmax, x)` rather than
`q.bedrock('cinderacegmax', 'x')`. That looks like a real upstream typo but is NOT fixed here,
because it has not been verified in game.

## §118

A worn Binder rewrites wild spawns near you, and REBUILDS the Pokemon from scratch when it
does - destroying shiny, IVs, nature and ability. This ate a shiny Pansage.

`BinderSpawnModifier.onEntityLoad` fires whenever a wild Pokemon loads: it finds the nearest
player within 64 blocks, checks their equipped accessories in the `belt` or `legs` slot, and if
one is a Binder runs `handleSpawnModification`. That walks the binder's cards, and for every
non-cosmetic card whose stat name ends in `_spawn` uses its `statValue` as a chance to convert
the Pokemon to that card's elemental type - but only when it is not already that type.

The destructive part is three instructions in `transformPokemon`:

    Pokemon.getLevel()
    Species.create(level)          <- a brand new Pokemon
    PokemonEntity.setPokemon(...)  <- replaces the entity's Pokemon wholesale

ONLY the level survives. The replacement rolls its own shiny check at base rate, so a shiny
that gets converted is simply gone. It also picks from `PokemonSpecies.getImplemented()`
filtered by type alone, ignoring local spawn tables - which is why a Vigoroth appeared
somewhere Vigoroth does not spawn.

The percentage in the log is `statValue * globalStatMultiplier`, which is 10.0 in
`config/cobblemon-cards.json`. Confirmed: the owner's six `normal_spawn` cards sum to
0.2460542, and the log recorded 2.4605422%.

Per-player exposure, from `tools/binderrisk.py` - the chance any given wild spawn near them is
rewritten: the owner ~11.9%, a player ~12.8%, a player ~7.8%, a player ~2.0%.

There is no config switch for the modifier. To protect a shiny hunt, take the Binder out of the
belt/legs accessory slot, or pull the big `_spawn` cards - one Virizion card was 72% of the
owner's entire Normal-type conversion chance. Lowering `globalStatMultiplier` would work but
nerfs every other card stat with it.

This matters for the Snorlax/Munchlax shiny farming: a shiny that spawns within 64 blocks of a
worn Binder has a one-in-eight chance of being replaced before it is ever seen.

## §119

Cobblemon Cards is **CC0-1.0** - public domain. Mixing into it and shipping the result carries
no obligation whatever, unlike Mega Showdown. Its distributed jar is only shims, though: every
real class, `BinderSpawnModifier` included, lives in the nested
`META-INF/jars/common-1.0.0.jar`, which must be extracted to compile against. Fabric loads that
nested jar at runtime, so the mixin target exists in game.

`tools/deploy-niftycards.sh` installs the resulting mod. Two things it gets right that are easy
to get wrong:

A mixin config with `"required": true` stops the server BOOTING when an injection fails to
apply. That is the correct failure mode - silent non-application would look like the feature
simply not working - but it must not be deployed unattended, hence the automatic rollback.

An `@Inject` handler's parameters must match the target method's descriptor EXACTLY. Declaring
`Object type` where the target takes `ElementalType` makes the injection fail to bind, which
with required:true means the server will not start. Caught before deploying, but only by
re-reading the signature.

## §120

`grep -q "Done ("` is not a restart check. `logs/latest.log` is NOT truncated on every restart,
so it matches a boot from hours earlier and reports success before the server has even stopped.
My deploy script did exactly that and printed "BOOT OK" with a `Done` line timestamped 00:16
while the real restart was 17 seconds in. Count the matches BEFORE restarting and wait for the
count to increase, or read the timestamp and compare it to now.

The same trap sits behind §111: any check that greps a long-lived log for a success marker will
find yesterday's.

## §121

Check the current upstream source before writing a patch for someone else's repo. The Binder
shiny fix we run locally was already solved upstream and better: commit `7f2c829d` "Spawning
Logic & Stat Refactor" rewrote `BinderSpawnModifier` as a `SpawningInfluence` that biases spawn
WEIGHTS before spawning, instead of replacing an already-spawned Pokemon. The shiny-destroying
path does not exist there at all. A PR against `transformPokemon` would have been a PR against
deleted code.

CORRECTION: the refactor is in `main` and is NOT RELEASED. The newest published build is 1.0.4
(14 July 2026), exactly what we run - so there is nothing to update to, and the
shiny-destroying binder is live for every one of that mod's ~18k downloads. Our `niftycards`
mixin therefore stays until they publish. Its config is `required:false` deliberately: on a
future build without `transformPokemon` it simply will not apply, which is correct because the
bug will be gone by then. Delete niftycards after updating past 1.0.4.

Check Modrinth for what is PUBLISHED, not just the repo - `main` having a fix says nothing
about what users are running. And a mod's `modrinth_id` belongs to THAT mod: I read SszvX85I
out of Mega Showdown's gradle.properties and queried it expecting Cards, which is 9asBGJMf.

## §122

`grep`-ing a server log to decide whether a restart succeeded is wrong in both directions, and
I managed both within an hour. `logs/latest.log` IS rotated on restart, so:

  - grepping for a success marker BEFORE the rotation finds the PREVIOUS boot and reports
    success while the server is still running the old process
  - counting the marker before the restart and waiting for a higher count never succeeds,
    because the new log starts from zero

Ask the server instead. `python3 rcon.py list` succeeding is unambiguous. `tools/
deploy-niftycards.sh` does that now.

Related: a `.sh` file edited on Windows and scp'd to the box carries CRLF and dies with
`$'
': command not found`. `.gitattributes` marks `*.sh` as LF but the existing working copy
was already CRLF - pipe through `tr -d '
'` when copying, or re-checkout the file.

## §123

The Binder whisper works, confirmed in game: `[Binder] Chikorita -> Smeargle (2.46%)`. Three
things are verified by that one line - the mixin applies, the message reaches the right player,
and 2.46% is exactly the owner's remaining `normal_spawn` total after pruning every other type,
which independently confirms the statValue * globalStatMultiplier arithmetic from §118.

Chikorita is Grass, so it was eligible; Smeargle is Normal, from the surviving cards. Still
unconfirmed: the `shiny kept` path, which needs a shiny to actually be converted.

Booster packs are wired into other mods four ways here, and only two are portable:

  rctmod              advancement using `rctmod:defeat_count`, rewards.loot grants the pack
  cobblemon-additions extra pool in bca's loot tables, pack weight 1 vs air 594
  legendarymonuments  cron script reading SavedData - no advancement trigger exists
  baby legendaries    cron script reading Pokedex NBT - same reason

The loot-table one is a full REPLACEMENT of bca's table, so it goes stale whenever they change
theirs; `tools/mkboosterloot.py` regenerates it. That caveat belongs in anything we send.

## §124

Shiny preservation across a Binder conversion is CONFIRMED end to end, not just in the code.
Forced with `tools/shinytest.sh`: spawn shiny Gastly (Ghost/Poison, so the surviving
normal_spawn cards can take it - a Normal-type would hit the same-type guard) until one
converts. Took 20 attempts at 2.46% each.

    BINGO ! ... transforme un sauvage (Gastly) en type Normal (Rufflet) ... 2.4605422%

and the resulting Rufflet reads:

    Species: "cobblemon:rufflet"   Shiny: 1b
    spawn_bucket: ""               Friendship: 50

The empty spawn_bucket and default friendship are the signature of `Species.create()` - a
freshly built Pokemon rather than a natural spawn. A fresh Pokemon that is nonetheless shiny
can only be shiny because the mixin set it, so that pair of fields is the actual proof; the
shiny flag alone would not distinguish it from a lucky natural spawn.

Cleanup discipline: 21 Gastly were loaded and exactly ONE was non-shiny, i.e. natural and not
mine. Killing by species alone would have destroyed someone else's spawn. The selector included
`Shiny:1b` and removed 20, leaving it. Count and characterise before any mass kill - §(the
radius-kill lesson) applies to selectors too, not just distances.

## §125

Mega Showdown 1.9.9 contains nothing we want. Checked against 1.9.5 directly rather than
trusting changelogs:

  - config flags are unchanged: `outSideMega`, `outSideUltraBurst`, `dynamaxAnywhere`. There is
    still no `outSideGmax`, so our sidemod remains the only route to a wheel button.
  - `blastoisegmax` is still 2 poses with ground_walk, ground_run, sleep and water_swim shipped
    and unreferenced. `corviknight_gmax` still ignores ground_walk, air_fly and sleep.
  - ZERO gmax assets differ between 1.9.5 and 1.9.9, and none were added.

So our poser pack and the sidemod stay as they are. 1.9.6-1.9.9 do carry unrelated crash fixes
(zacian/zamazenta, type effectiveness on multiplayer) which are a separate reason to update, but
not a gmax one.

`SlotCount` also starts with "Slot". Any code walking a party store must filter on the VALUE
being a Pokemon, not on the key prefix - `int(key[4:])` throws on it. gmaxdisplay.party() gets
this right; an ad-hoc script written in a hurry did not.

## §126

All seven Cobblemon Cards easter eggs, from `InstantDexItem.generateCard`. Every one is
hardcoded `"mythic"`, so each is a GUARANTEED top-rarity card for one Instant-Dex use - the
wiki previously said You & Mew was the only mythic it produces, which was wrong.

  missingno      ANY Pokemon. getMoonPhase()==0 && isNight() && player hasEffect(DARKNESS)
  ghost          gastly/haunter/gengar/cubone/marowak, dayTime%24000 in [<coords>],
                 block at feet OR below is SOUL_SAND or SOUL_SOIL
  god_bidoof     bidoof + GOLDEN_APPLE or ENCHANTED_GOLDEN_APPLE in the offhand
  crystal_onix   onix + AMETHYST_SHARD in the offhand
  shadow_lugia   lugia + isThundering() && player hasEffect(WITHER)
  pride_sylveon  sylveon + PINK_DYE, LIGHT_BLUE_DYE or WHITE_DYE in the offhand
  you_and_mew    mew, consuming a Player Card whose id matches your own UUID

None of them exist on the Card Dex scanner - `pride_sylveon` appears in `InstantDexItem` and
`CardUtil` but never in `CardDexItem`. So "the species is already in my Pokedex" is not why a
scan does nothing; the scanner simply has no easter-egg path.

Intermediary names resolve from loom's downloaded mappings at
`$GRADLE_USER_HOME/caches/fabric-loom/1.21.1/loom.mappings.*-v2/mappings.tiny` - a tiny v2 file
of official/intermediary/named columns. That is how field_8330 became PINK_DYE.

## §127

`"

" in s` is the wrong test for a file's line endings. build3.py has 5099 bare LF and 17
CRLF, so that test picked CRLF and every anchor lookup failed. Compare the COUNTS:
`nl = "

" if s.count("

") > s.count("
")/2 else "
"`.

## §128

The Gigantamax display is driven by the `gmax` ASPECT, which comes from Cobblemon's
`dynamax_form` species feature. `FormId` is a DIFFERENT field and changing it does nothing
visible. Every revert this project reported as working was verified against `FormId` and was a
false success; the models never changed, through recall, resummon and relog.

`dynamax_form` is a choice feature:

    {"type":"choice","default":"none","choices":["gmax","eternamax"],"isAspect":true}

`none` is the default but is NOT among the choices, so the property validator rejects
`pokeedit dynamax_form=none` while `pokeedit` still prints "Edited ...". That is the whole
explanation for a silent no-op recorded three times without being understood. `unaspect=gmax`,
`gmax=false` and an empty value all fail too, and `aspect=gmax=false` actively sets FormId back
to gmax.

The only working per-Pokemon revert is Mega Showdown's own call, which is what `hard_reset`
makes internally:

    Effect.getEffect("mega_showdown:dynamax")
          .revertEffects(pokemon, List.of("dynamax_form=none"), Optional.empty(), null);

`sidemod/niftygmaxserver` exposes it as `/niftygmax revert <player> <slot>`. Verified: the
aspect clears, and GmaxFactor is PRESERVED, so reverting does not cost the player their Max
Soup - unlike `hard_reset`, which wipes GmaxFactor across the whole party and PC.

## §129

Cobblemon's party store persists on ITS OWN schedule, not on `save-all flush`. A revert can
take up to a minute to appear in `world/pokemon/playerpartystore/**.dat`. Three separate tests
here read the file within 12-36 seconds, saw the old value and reported failure; every one had
actually succeeded. Trust the command's own answer - it inspects the live object - and treat
the .dat as eventually consistent.

Two more self-inflicted ones from the same session. `pkill -f gmaxwatch` killed the ssh session
running it, because the pattern appears in that command's own argv; `ps | grep "[g]maxwatch"`
then matched the checking command itself and reported a daemon that was not running. Put such
commands in a FILE and run the file. And the daemon holds a lock for its 55s loop, so a
freshly scp'd script is not picked up until the running instance exits - kill it by PID (found
via a script, not an inline pattern) or wait.

## §130

APPLY was as broken as revert, and for the mirror-image reason. `pokeedit <slot> form=gmax`
sets FormId only. It appeared to work for months because every test subject already had
`dynamax_form=gmax` from real battle Dynamax - the feature was already set, so the model was
already right, and FormId changes rode along invisibly. The moment the revert genuinely
cleared the feature, apply had nothing left to hide behind and started failing.

The working pair is:

    apply   pokeedit <slot> dynamax_form=gmax      `gmax` IS one of the feature's choices
    revert  /niftygmax revert <player> <slot>      `none` is NOT, so it needs the sidemod

And the payoff: setting the FEATURE updates the model LIVE. No recall, no resummon. All the
earlier advice about resummoning existed only because nothing was actually changing - it was
covering for a broken write, and it is now removed.

The general lesson: a test subject that already satisfies the postcondition cannot prove the
operation works. Every gmax test here was run on Pokemon that were already gmax.

## §131

The RadicalGymsStructures gyms are NOT all in the overworld, which is why an overworld
`locate` finds only six of nine:

    cinnabar_gym    nether_wastes, crimson_forest, warped_forest   -> THE NETHER
    blackthorn_gym  end_highlands, end_midlands                    -> THE END
    kanto_league    end_highlands, end_midlands                    -> THE END

There is no viridian_gym at all - `locate` answers "there is no structure with type". Giovanni
is a leader in the series but has no structure, so a Viridian gym has to be built by hand.

A bogus waypoint came out of this: a `#rgs:gyms` tag search appeared to name cinnabar_gym in
the overworld at [<coords>], and a direct locate there finds nothing. That reply was garbled
by rcon interleaving - gmaxwatch polls every 3s on the same connection. Space admin rcon calls
by ~4s when reading anything whose answer matters.

## §132

The radicalred badge order the mod ENFORCES is not the Red/Blue order. From
`required_defeats`, confirmed live:

    Brock -> rival_terry_014c/d/e -> Misty -> trainer_brendan_0032 -> Lt. Surge -> Erika
      -> boss_giovanni_015c -> leader_giovanni_015e -> rival_terry_01b0/1/2
      -> rocket_admin_archer_ariana_m000 -> boss_giovanni_015d
      -> SABRINA -> trainer_brendan_0039 -> KOGA -> trainer_may_003d -> BLAINE
      -> rocket_admin_archer_0043 -> rocket_admin_ariana_0044 -> boss_giovanni_0045 -> Clair
      -> rival_terry_01b3/4/5 -> trainer_brendan_001a -> Elite Four -> champion_terry -> Red

So Saffron is 5th, Fuchsia 6th, Cinnabar 7th - the reverse of canon, where Koga is 5th and
Sabrina 6th. Waypoints were labelled from canon first and had to be corrected.

`tools/rctchain.py` rebuilds the whole graph by topological sort. All 53 trainers carry
spawnWeightFactor 0.25 in rctmod, but RGS ships overriding copies of the eight gym leaders with
weight 0 so they only appear inside their gyms.

Place trainers deliberately with `/rctmod trainer summon_persistent <trainerId>`, or the
crafted Trainer Spawner block (BSB/DRD/BSB - stone bricks, slabs, 2 diamonds, redstone).

## §133

Waypoints: the players use XAERO's own files, not the server_waypoint mod. Pushing with
`/wp add ... true` DOES reach the Xaero file, but lands in a separate set named after the list
with `visibility_type: 1`, so it only shows if you switch sets in the Xaero menu. All 346 of
the owner's own waypoints use set `gui.xaero_default` and `visibility_type: 0`.

Write directly instead - `tools/xaerogyms.py`. Format is documented in the file's own header:

    waypoint:name:initials:x:y:z:color:disabled:type:set:rotate_on_tp:tp_yaw:visibility_type:destination

Per dimension, under `xaero/minimap/Multiplayer_<host>/dim%0` (overworld), `dim%-1` (nether),
`dim%1` (end). Xaero keeps waypoints in memory and rewrites these files when it saves, so an
edit made while the game is RUNNING is lost on exit. Write with Minecraft closed.

## §134

Trainer team levels live in `data/rctmod/trainers/<id>.json` (`team[].level`), NOT in
`data/rctmod/mobs/trainers/<id>.json`, which carries only spawn and requirement data. The wiki
generator was reading only the mobs path, so the trainers table had no levels and the owner had
to Ctrl-F each name further down the page.

This matters because a spawner-summoned trainer IGNORES the level cap, so the highest level on
the team is exactly the number a player needs before choosing to nerf their party. It is now a
column, with a span where repeat encounters differ.

The owner's actual workflow, worth remembering: they never hunt leaders in the world. They use
a Kanto gym structure when one is reachable and otherwise summon the trainer into a custom-built
gym - the whole Sinnoh series was done that way. Finding NPCs is the un-fun part.

## §135

`gym_note.py` — the script that generates the Gym Leader table — existed only as
`/tmp/gym_note.py` on the server. Its output is not rebuilt by `build-wiki.sh`; it is baked
into `wiki_data3.json`, which the build merely restores from `wiki-inputs/`. So the table
looked permanent while the only copy of the code that could change it sat in a directory
`tmpfiles.d` wipes on boot.

The same class of problem the build script's header already warns about for
`wiki_parts.json` / `wiki_data2.json` / `wiki_data3.json`, one level further back: the DATA
was rescued, the GENERATOR was not. If a wiki section cannot be traced to a script in
`tools/wiki/`, it cannot be changed after the next reboot.

Now versioned as `tools/wiki/gymnote.py`. It writes `/tmp/wiki_data3.json`, so anything that
runs it must copy the result back to `$COBBLEMON_DIR/wiki-inputs/` or the change
survives exactly until the next boot.

## §136

Structure-to-trainer mapping is readable straight out of the `.nbt`. The gym structures in
`RadicalGymsStructures-RGS.jar` are gzipped NBT; decompress and the trainer ids are plain
bytes:

    for t in set(re.findall(rb"[a-z][a-z_]*_[0-9a-f]{4}", gzip.decompress(raw))):

Do not take the mapping from the file name. `pewter_gym.nbt` containing `leader_brock_019e`
is a fact; `pewter_gym` meaning Brock is a guess that happens to be right. The pattern also
matches block names — `stripped_acac`, `data_written_by_acce` — so intersect the hits with
the real trainer list rather than trusting the shape.

Verified: eight gyms hold one leader each, `kanto_league` holds Terry plus five Elite Four
entries. Blackthorn (Clair) is in the End despite being a Johto gym.

## §137

`locate structure` reports where a structure was PLACED, not whether it can be used. The
Vermilion gym at <coords> located fine and was unplayable: floor at y55 with surrounding
ground at y68, and 677 water blocks through it. `tools/gymsite.py` answers the real question
from the saved chunks - water inside the bounding box, and ground level outside it.

Two traps in reading that back:

**The bounding box is on the Children, not the start.** `structures.starts[<id>]` holds
`Children`, `ChunkX/Z` and `id` - no `BB`. Each jigsaw piece under `Children` has its own BB;
union them. Chunks the structure merely touches hold no start at all, only a `References`
long[] of packed ChunkPos naming the start chunk - decode and follow it.

**`locate` writes proto-chunks.** It computes structure starts without generating terrain, so
a candidate parses cleanly and reports "0 water, nothing around" - which reads as a perfect
site and really means "not built yet". Gate on `Status == minecraft:full` before judging, and
forceload + `save-all flush` to generate. Remove the forceloads afterwards; 216 chunks stayed
loaded for as long as it took to notice.

Placement cause, for picking replacements: `project_start_to_heightmap: WORLD_SURFACE_WG`
includes fluids, so a gym landing on water sits at the water surface. Floor Y below sea level
63 is the tell - the broken one was 55, the clean replacement 69.

## §138

LinguaChat translates the Binder whisper because `[Binder] ` looks like a chat sender. Its
`EXTENDED_MESSAGE_PATTERN` is

    (?:<([^>]+)>|\[([^\]]+)\]|\(([^)]+)\)|(?:^|\s+)([\w\d_-]+):)\s*(.*)

so `<name>`, `[name]`, `(name)` and `name:` all parse as "sender + text", and the text - our
species names - gets sent to Google Translate. There is no ignore list in its config.

`MessageHandlerMixin.shouldTranslateMessage` returns false early for a message that contains
`[System]` or `[CHAT]`, or that **startsWith `* ` or `-> `**. A leading `* ` is therefore the
whole fix, and it is ours to make: niftycards is `"environment": "server"`, so the prefix
changed server-side and nobody downloaded anything.

## §139

Sweets are not trainer-only, and the wiki said they were. All seven are cooked in a
**Campfire Pot**: dye + honey bottle + sugar, where the dye picks the sweet (yellow -> Star,
red -> Strawberry, blue -> Berry, green -> Clover, orange -> Flower, pink -> Love, purple ->
Ribbon). The pot is 5 copper + glass + 2 apricorns.

The index already parsed `cobblemon:cooking_pot_shapeless`; three separate renderers each
mapped recipe kinds their own way and only the item browser named the station. The others
printed "Shapeless" or "Potless" - both of which say "use a crafting table", which cannot
work. One label table now feeds all three.

Research note: the first scan for sweet sources MISSED these recipes because it deduped hits
by `(jar, basename)`, and `star_sweet.json` exists twice in the Cobblemon jar - once as the
recipe, once as the recipe-unlock advancement. The advancement won and the recipe was thrown
away, leaving "trainer loot only" looking correct. Dedup on the full path, not the leaf.

## §140

Rendering Cobblemon models is worth doing - the wiki now shows 1,972 real sprites - but three
things have to be right, and each was found by rendering and looking, not by reasoning:

**The bind pose is not the pose you see.** Bulbasaur's Vine Whip bones lie flat out to
x=+-34 until an animation tucks them in, so it renders with two green spears through it. The
poser names a pose whose `poseTypes` include PROFILE; that pose names a bedrock animation;
its first frame is the pose the party screen shows. MoLang expressions need no evaluation -
they are all `math.sin(q.anim_time*...)`, which is 0 at rest (1 for scale).

**Bedrock negates Y and Z rotation** against a right-handed matrix; order is Z, then Y, then
X. A model with one or two rotated bones looks fine under any convention - Pikachu did - so
test on a deep chain. Alcremie's head swirl is four bones deep and flings pieces clear of the
model until this is right.

**Minecraft shades by face direction, not by a light.** Lambert shading turned Vulpix brown.
Use the game's own factors (+y 1.0, -y 0.62, z 0.88, x 0.76).

Two data shapes to expect: a layer texture can be `{"frames":[...]}` rather than a path
(Charizard's tail flame), and a species can be split across several resolver files - a base
with model+texture and a second holding only the female texture. Treating each file
independently and keeping whichever named a model throws the second file's texture away, and
every `female` sprite fails on a missing texture.

`region-bias-*` is a spawn hint, not a form. It names textures that do not exist.

## §141

**New files under `public/` are invisible until the web app restarts.** The portfolio is
Next.js under PM2; `next start` reads the public directory ONCE at startup and serves from
that list. Editing `public/mc-wiki.html` therefore deploys on a plain `git pull` - the path
is already known - but a NEW path 404s from the origin even though the file is on disk, and
`cf-cache-status: BYPASS` proves the CDN is not the culprit.

Adding `public/mc-wiki-img/` needed `pm2 restart nifty`. That is supervised (fork mode, 10
prior restarts, 0 unstable) and takes a few seconds, but it restarts the WHOLE site, not just
the wiki - so it is not part of the normal wiki deploy and should not be done casually. Only
a first deploy of a new path needs it; updating files at an existing path never does.

## §142

A string replacement hit the wrong occurrence and took the whole dex tab down. The edit was
meant to insert `VARS` into `dexRow`'s output, but the anchor `'<div class="card sm" style="marg`
appears earlier, inside `dexStrip` - so `dexStrip` ended up returning `VARS`, which only exists
in `dexRow`. Every species with more than one variation threw a ReferenceError, `dexRow` threw
with it, and the dex rendered nothing. It shipped, because the build succeeded and the page
still looked fine in a grep.

A build that succeeds proves the file parses, not that the page works. Anchor on a unique
string, assert the occurrence count, and for template JS load the deployed page and call the
function - `dexStrip('Vulpix')` in the console would have caught this in seconds. That check
is now what confirms a dex deploy.

## §143

Sprite atlases keep their filenames across a re-pack, and they are served
`cache-control: public, max-age=14400`. The manifest that says which cell a sprite sits in is
inlined in the page, so it updates instantly - which means for four hours a returning browser
pairs TODAY's manifest with YESTERDAY's atlas and draws the wrong sprite in every cell.

It only became visible because repacking 196-per-sheet instead of 100 changed the sheet from
960 to 1344px, and the browser still reported 960. Had the grid stayed the same size the
sprites would simply have been wrong, quietly.

Atlas URLs now carry `?v=<hash of the manifest>`, so a re-pack is a new URL. Any asset whose
content changes under a stable name needs this; the wiki HTML itself is fine because it is
served `no-cache`.

## §144

**The gym structures' buttons need `enable-command-block=true`.** It was `false`, so pressing
the button in Pewter Gym did nothing at all - no message, no failure, just nothing. The gyms
spawn their leader from chain command blocks:

    /rctmod trainer summon leader_brock_019e ~ ~3 ~
    /effect give @e[type=rctmod:trainer] minecraft:slowness infinite 100 true

The slowness is what pins the leader in the arena. Every `rctmod trainer` subcommand needs
permission level 2 and command blocks run at exactly 2, so nothing else was in the way.

Two things that mislead while diagnosing this:

Most of the command blocks in the structure are EMPTY - the chain is padded - so a quick look
suggests the gym has no logic. Only four of the sixteen in Pewter carry a command.

`rctmod trainer summon <id>` with no position answers **"Caller is not a player"**, which
reads like a command block could never run it. The structure uses the positional overload
(`~ ~3 ~`), which has no such requirement. Verified from the console: the positional form
summoned Leader Brock with no player anywhere near.

Scraping the commands with a regex over the decompressed NBT produced `//rctmod trainer
summon leader_brock_019e` - a doubled slash and the position silently cut off. Parse the NBT
and read `Command` rather than pattern-matching the bytes.

Unrelated to the structures: Brock's Trainer Spawner item is a **Hard Stone**, not a Rock Gem.
No gem is a Kanto leader's signature item - the gems belong to Unbound leaders. A Rock Gem is
the crafting ingredient for a Hard Stone (8 stone around it).

## §145

A rename loses nothing on this server, and the panic is worth short-circuiting next time.
`online-mode=true`, so Mojang issues the UUID and it survives a username change. The logs
prove it directly:

    UUID of player a player is <uuid>
    UUID of player a player is <uuid>

Same id, so advancements, stats, playerdata, Cobblemon party and Pokedex, research tasks,
CobbleDollars, RCT series progress and miniteleport homes all carry over untouched - every
one of those is filed under the UUID. a player's advancement file still runs continuously from
2026-08-07 to entries earned after the rename.

Our own reward state (`arcphone-rewards-state.json`, `series-catchup-state.json`) is also
UUID-keyed; the `name` field in them is a display label refreshed from the usercache on the
next run, so a stale old name there is cosmetic and self-correcting.

The check that settles it in one command:

    zgrep -hoE "UUID of player [A-Za-z0-9_]+ is [0-9a-f-]+" logs/*.log.gz logs/latest.log | sort -u

Only offline-mode servers derive the UUID from the name, and that is where a rename really
does orphan everything.

## §146

**Journey Mounts ships stale copies of Mega Showdown's mega models at identical asset paths,
and wins.** Mega Kangaskhan renders with scattered UVs and missing faces because the geometry
being drawn is not the geometry the texture was painted for:

    assets/cobblemon/bedrock/pokemon/models/0115_kangaskhan/kangaskhan_mega.geo.json
      cobblemon-journey-mounts   84 bones, 141 cubes
      mega_showdown             131 bones, 164 cubes

Only Mega Showdown ships `megakangaskhan.png`, so Journey Mounts' mesh has no texture that
fits it. 30 asset paths are contested between those two mods.

**Not every collision is a bug, and overriding them all breaks riding.** Journey Mounts
deliberately re-rigs models to hang a seat off them - Appletun is 24 bones/36 cubes in Mega
Showdown and 25/36 in Journey Mounts, same mesh plus one bone. Forcing Mega Showdown's copy
there would strip the ride point and fix nothing. The signal that separates a stale copy from
a re-rig is the MESH: a different cube count, a different declared texture size, or FEWER
bones than the other mod. That rule cuts 30 contested paths to the 11 that are actually
broken - slowbro, gengar, kangaskhan, steelix, scizor, sceptile, blaziken, swampert, aggron,
manectric, altaria. Rendering the excluded ones both ways confirms they are identical.

Fixed with a resource pack (`tools/mkmegafix.py` -> `client/nifty-megamodel-fix.zip`), because
a resource pack outranks every mod's own assets. It is CLIENT-side only - the server never
reads these - so each player needs it.

Diagnosing this needed a renderer that could be pointed at either mod's copy: Pack lets the
last jar win a path, so rendering with the jars in one order and then the other showed the
intact model beside the scattered one.

## §147

**A form that declares its own `riding` ignores the species-level two-seat addition.** Hisuian
Arcanine rides one-up because `arcanine.json`'s Hisui form carries

    "riding": { "behaviour": {...}, "seats": [], "stats": {...} }

and a form's riding block wins outright over the species'. 27 forms across the installed jars
do this, 17 with an empty seat list - the Galarian birds, Galarian Rapidash and Mr. Mime,
Paldean Tauros, Braviary Hisui, Giratina Origin, Kyurem Black/White, Enamorus Therian, Gmax
Melmetal and a dozen Megas.

**A species_addition cannot fix it.** SpeciesAdditions applies collection properties with
`Collection.addAll`, so a `forms` entry APPENDS a form instead of merging into the existing
one. The only route is overriding the whole species file - `tools/mkformseats.py`, rebuilt
from the installed jars each run because a full override goes stale on any update.

Two things that look like the problem and are not:

The MODEL is already fine. These forms mostly reuse the base geometry - Hisuian Arcanine is
`arcanine.geo.json` - which the two-seat resource pack already gives a `locator_seat_2`. Only
`melmetal_gmax.geo.json` lacks one. So this was never a resource-pack gap.

Galarian Rapidash needs nothing, because Journey Mounts overrides `rapidash.json` and its
Galar form has NO riding block at all - so it inherits the species-level riding, which the
addition has already made two-seat. Check which jar actually wins a species path before
assuming a form is broken.

## §148

`tools/modwatch.py` answers "can we move to Cobblemon 1.8 yet" in one command, and runs
weekly into `modwatch-latest.txt` on the server. It identifies each jar by SHA1 through
Modrinth's bulk hash lookup rather than guessing slugs, so renaming a file does not break it.

Three things it has to get right, each of which was wrong first:

**A bare "1.8" substring is not a signal.** cobblemon_party_extras is on its own version
1.8.15. These version strings embed the Cobblemon version as one token among several
(`1.7.3-fabric-2.3.0`, `1.9.5+1.7.3+1.21.1`), so find the slot holding 1.7 in the installed
string and read the same slot in the candidate.

**A version string that says nothing may still require 1.8.** rctmod `0.19.0-beta` names no
Cobblemon version anywhere in its version number, and its Modrinth dependency does not pin
one either - but its changelog says "Update min required version of Cobblemon to 1.8".
Offering it as a safe in-line update would stop the server booting. Read the dependency, fall
back to the changelog, and treat anything still unresolved as UNKNOWN rather than safe.

**The newest release is not the newest USABLE release.** Mega Showdown's newest is a 1.8
beta; 1.9.9 on the 1.7.3 line is a real update available today. Report both.

As of 2026-09-07 the blockers are unchanged: capture_xp, spawn_notification and tim_core all
still publish 1.7.3 only, and tim_core is the root - the other two depend on it.

## §149

Removing one enchantment from a player's worn item: `/data modify entity` refuses to touch
players, and `/enchant` only adds. The route that works is an item modifier applied to the
equipment slot:

    data get entity <player> Inventory[{Slot:102b}]        # 102 = chest, 100 boots -> 103 helmet
    item modify entity <player> armor.chest nifty:decurse

with `data/<ns>/item_modifier/decurse.json` (singular folder since 1.20.5) holding a
`minecraft:set_components` that rewrites `minecraft:enchantments` to the levels map you want
to KEEP. It replaces that one component and leaves everything else alone, so trim, durability
and custom name survive - which `/item replace ... with <item>[...]` would not.

Read the item first: the keep-list is written out by hand, so anything not listed is dropped.
a player's chestplate kept Thorns 2, Protection 4, Unbreaking 3, Mending 1 and its
amethyst/flow trim while losing both curses.

Needs a `/reload` to register the modifier, and delete the pack afterwards - the keep-list is
specific to one item and would silently strip enchantments off anything else it touched.

## §150

**The "Exception ticking world" crash is an entity-tracker desync, and it is chronic.**
2026-09-07 05:31:48, mid-battle:

    NullPointerException: Cannot invoke "IntArrayList.getInt(int)" because "this.wrapped" is null
      at Int2ObjectOpenHashMap$MapIterator.nextEntry
      at class_3898.method_18727        <- ChunkMap.tick(), iterating the entity trackers

The trigger is 29 seconds earlier, and it is the thing to grep for:

    [05:31:19] WARN: Entity PokemonEntity['Zacian'/92638, ..., removed=KILLED]
               wasn't found in section class_4

An entity is removed without its section bookkeeping being updated, the tracker map is left
holding a dangling entry, and the NEXT ChunkMap tick that iterates it dies. Whatever happens
in between - here a `/tp` - looks like the cause and is not.

This warning has fired **5,187 times** across the logs, so it is long-standing rather than
new, and it is overwhelmingly legendaries: Lugia 680, Zapdos 479, Eternatus 244, Kyurem 175,
Arceus 86. On the day of this crash Zacian led with 38 - the species that actually crashed it.

Worth checking before blaming a recent change: none of the 63 Alcremie or the Mewtwo spawned
by hand that day appear in the warning at all. Spawned entities were not involved.

    zgrep -h "wasn.t found in section" logs/*.log.gz | sed "s/.*PokemonEntity\[.//;s/.\/[0-9].*//" \
      | sort | uniq -c | sort -rn | head

The world saves cleanly on this crash - all dimensions flushed before shutdown - so nothing is
lost beyond the session. `systemctl start cobblemon` is the whole recovery.

## §151

**Two different items are called "Blue Orb", and the wiki was showing the wrong one.**

    mythsandlegends:blue_orb   SUMMONS Kyogre        (Ancient City chests, 3.2%)
    mega_showdown:blue_orb     triggers Primal       (Lugia Temple chest, ~1.6%/chest)

Same for Red Orb and Groudon (Bell Tower, ~0.8%/chest). The item list is keyed by display
name, so only one row survived - the Myths & Legends one - and neither Mega Showdown orb
appeared anywhere on the page. Four item names are claimed by two mods; this pair is the one
where the collision actively misleads, because both orbs are Kyogre-related and only one does
what the reader wants.

**Primal is a battle transformation, not a form you keep.** The `primal` aspect is code-driven
- there is no species feature and no form in the species_addition, only a resolver at
`2_kyogre_primal.json`. So it cannot be spawned persistently, exactly like the battleOnly
Megas. Lorelei's Kyogre in the Kanto Elite Four is Primal because her team entry carries
`aspects: ["primal"]` AND `heldItem: ["mega_showdown:blue_orb"]` - reading only the ability
(`drizzle`) suggests a plain Kyogre and is misleading; Primal's ability is applied on
reversion.

When a species looks wrong in a trainer battle, read the trainer's team entry rather than
guessing from the species: it names the aspects and the held item outright.

    zipfile rctmod .../data/rctmod/trainers/elite_four_lorelei_004e.json

## §152

**Colliding item ids: 42 of them, and the survivor is often the wrong one.** The source item
list keys on the bare id, so when two mods ship the same id only one row lives. Recovering
them needs the right comparison, and two wrong ones came first:

- Matching on display NAME recovered **2,121** rows and nearly doubled the page. Plenty of
  mods re-declare a name without being a different item.
- Matching on id but comparing raw mod strings recovered **920** - `cobbreeding` against
  `Cobbreeding`, `mega_showdown` against `MegaShowdown`. Normalise (lowercase, strip
  non-alphanumerics) and it drops to the real **43**.

The source rows carry `i` and `m` only; the namespaced `x` is derived later in build3.py, so
index on the bare id, not on `x` - keying on `x` silently finds nothing.

The recovered set is exactly the misleading kind: `blue_orb`, `red_orb`, `adamant_orb`,
`griseous_orb`, `dna_splicer`, `cornerstone_mask`, `hearthflame_mask` - Mega Showdown's
transformation item against Myths & Legends' summon item of the same name.

## §153

**Aspect names are more specific than they look, and grouping on the hyphen hides that.** An
audit that buckets aspects by their prefix reports `origin`, `therian`, `black`, `ultra`,
`complete`, `sky` - none of which exist. The real names are `origin-forme`, `therian-forme`,
`black-fusion`, `ultra-fusion`, `complete-percent`, `sky-forme`. Six wiki rows rendered no
sprite at all before this was spotted, and the failure is silent: the lookup just misses.

Read the actual keys before using them:

    python -c "import json;m=json.load(open('tools/wiki/dex-sprites.json'))['map'];\
      print(sorted(k.split('|',1)[1] for k in m if k.startswith('giratina|')))"

The wiki table skips any row whose sprite is missing rather than printing a broken tile, so a
wrong aspect name shows up as a row that quietly vanishes - check the printed count.
