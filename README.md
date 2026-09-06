# nifty-cobblemon

Odds and ends built for a five-player private [Cobblemon](https://cobblemon.com) server:
two small sidemods, some datapacks that wire mods together, and the scripts that run it all.

Public domain (CC0). Take anything, change anything, no credit needed, no need to ask.

Built on other people's work — go give them a look:
[Cobblemon](https://cobblemon.com) ·
[Cobblemon Cards](https://github.com/Howlite-UI/CobblemonCards) (CC0, by Howlite) ·
[Mega Showdown](https://github.com/yajatkaul/CobblemonMegaShowdown) (by YajatKaul) ·
[Radical Cobblemon Trainers](https://modrinth.com/mod/radical-cobblemon-trainers) ·
[Cobblemon Additions](https://modrinth.com/mod/cobblemon-additions) ·
[Legendary Monuments](https://modrinth.com/mod/legendary-monuments)

Nothing here is a polished product. It's what actually runs on one server, cleaned of
hostnames and player names. Paths default to `$COBBLEMON_DIR` (or `/srv/cobblemon`), so
expect to adjust things.

## Sidemods

**`sidemods/niftygmax`** — client-only. Adds a Gigantamax button to Cobblemon's interaction
wheel, next to Mega Evolve.

[Mega Showdown](https://modrinth.com/mod/mega-showdown) has `outSideMega` and
`outSideUltraBurst` config flags that put Mega and Ultra Burst on the wheel, but no equivalent
for Gigantamax — a G-max form is only visible mid-battle beside a Power Spot. This subscribes
to Cobblemon's public `POKEMON_INTERACTION_GUI_CREATION` event and adds an option that sends
`/trigger gmax set <slot>`; a server-side script does the rest. Contains no Mega Showdown code.

**`sidemods/niftygmaxserver`** — server-only companion to the above. Adds
`/niftygmax revert <player> <slot>`, the only way to turn a Gigantamax display back off
without `/msd hard_reset` nuking the player's whole party and PC. Separate from `niftygmax` so
the client jar never needs reissuing.

**`sidemods/niftycards`** — server-only. Two changes to
[Cobblemon Cards](https://modrinth.com/mod/cobblemon-cards) 1.0.4's Binder:

- a converted Pokémon **keeps its shiny**. `transformPokemon` rebuilds it with
  `Species.create(level)`, so shiny is dropped and re-rolled at base rate — a shiny converted
  that way is gone, and the log records only what it became
- the player whose Binder did it is told, so the mechanic is visible to the person causing it

Upstream has since rewritten that system as a `SpawningInfluence` that biases spawn weights
instead of replacing a spawned Pokémon, which removes the problem properly — but that is
unreleased as of 1.0.4. The mixin is `required: false`, so on a build without
`transformPokemon` it simply doesn't apply. **Delete this mod once Cards updates.**

## Datapacks

**`datapacks/nifty-card-rewards`** — booster packs as rewards for progression in *other* mods.
An advancement using another mod's trigger, rewarding a loot table that grants a Cards item:

```json
"criteria": { "champion": {
    "trigger": "rctmod:defeat_count",
    "conditions": { "count": 1, "trainer_ids": ["champion_terry_01b6"] } } },
"rewards": { "loot": ["nifty:rewards/booster_pack_gen1"] }
```

Beat a gym leader or champion in [Radical Cobblemon
Trainers](https://modrinth.com/mod/radical-cobblemon-trainers), get that generation's pack.
Anything with an advancement trigger works the same way.

**`datapacks/nifty-booster-loot`** — a rare booster pack in Cobblemon Additions village
chests: an extra loot pool, pack at weight 1 against `minecraft:air` at 594, so about 1 chest
in 600. Note this **replaces** the mod's loot tables, so it goes stale when they change theirs;
`scripts/mkboosterloot.py` regenerates it.

## Scripts

Python, no dependencies, driven by RCON and by reading the server's own save files.

| script | what it does |
| --- | --- |
| `gmaxwatch.py` | polls a vanilla `trigger` objective so players can toggle their own G-max display with no client mod |
| `gmaxdisplay.py` | the eligibility rules — species has a G-max model, and `GmaxFactor` is set |
| `gmaxassets.py` | lists which species can actually render a G-max form, checked across every jar |
| `mkgmaxfixes.py` | resource pack fixing Mega Showdown posers that ignore animation clips they ship |
| `mkseatpack.py` | regenerates a 2-seat mount pack against the installed jars |
| `mkboosterloot.py` | injects booster packs into another mod's loot tables |
| `arcphone-rewards.py` | booster packs for Legendary Monuments quest lines |
| `babylegends-rewards.py` | a reward for registering every Baby Legends species |
| `rewardutil.py` | shared delivery — confirms an item actually arrived before marking it granted |

The two reward scripts read another mod's save data on a timer because those mods expose no
advancement trigger. That's server plumbing rather than a clean integration, included because
it works rather than because it's pretty.

## A note on the G-max display

The display follows the **`gmax` aspect**, which comes from Cobblemon's `dynamax_form` species
feature. `FormId` is a *different field*, and changing it does nothing visible. That distinction
is the whole story here — verifying against `FormId` gives false successes in both directions.

```
apply   pokeedit <slot> dynamax_form=gmax     works: gmax IS one of the feature's choices
revert  /niftygmax revert <player> <slot>     needs the sidemod, see below
no-op   pokeedit form=gmax / form=normal      sets FormId only; model unchanged
no-op   pokeedit dynamax_form=none            "none" is the DEFAULT but NOT among the choices,
                                              so the validator rejects it
no-op   pokeedit unaspect=gmax / gmax=false   nothing
avoid   /msd hard_reset                       works, but walks the whole party AND PC and
                                              wipes GmaxFactor
```

The feature is a choice type:

```json
{"type":"choice","keys":["dynamax_form"],"default":"none",
 "choices":["gmax","eternamax"],"isAspect":true,"aspectFormat":"{{choice}}"}
```

`none` being the default but not a choice is why the obvious revert silently fails while
`pokeedit` still prints "Edited ...". `sidemods/niftygmaxserver` works around it by making the
same call `hard_reset` makes internally, for one Pokémon:

```java
Effect.getEffect("mega_showdown:dynamax")
      .revertEffects(pokemon, List.of("dynamax_form=none"), Optional.empty(), null);
```

Gate it on `GmaxFactor` so the form stays something a player earned with a Max Soup — reverting
preserves it, so toggling costs nothing.

**Setting the feature updates the model live.** No recall, no resummon. The form is also
rideable, and stays normal-sized because the 4× comes from `startGradualScaling` on the battle
path rather than from the form.

Two things that will waste your time. Cobblemon's party store persists on its own schedule, not
on `save-all` — a successful change can take a minute to reach the `.dat`, so trust the command
rather than the file. And do not test on a Pokémon that is already in the target state: every
G-max test here ran on Pokémon that were already G-max, which hid a completely broken apply for
months.

## What is deliberately not here

**The 2-seat mount resource pack.** `scripts/mkseatpack.py` builds it, but the pack itself is
515 Cobblemon and Mega Showdown geometry files with a `locator_seat_2` bone added. Mega
Showdown licenses its assets CC BY-NC-SA 4.0, which is ShareAlike — those files cannot be
redistributed under CC0. Run the script against your own installed jars instead; it only ever
touches files you already have.

The same goes for `mkgmaxfixes.py`, which patches Mega Showdown posers. The tool is here; the
output is not.

## Building the sidemods

JDK 21 and the Gradle wrapper. Cobblemon resolves from
`https://artefacts.cobblemon.com/releases`. `niftycards` also needs the Cards jar — extract the
nested `META-INF/jars/common-1.0.0.jar` from it into `libs/`, since the distributed jar is only
shims and the class it mixes into lives in there.

Two traps: the Kotlin plugin must be 2.2.x or Loom can't remap Cobblemon, and use
`dev.architectury.loom` rather than plain `fabric-loom`.
