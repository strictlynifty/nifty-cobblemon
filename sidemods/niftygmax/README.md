# Nifty Gigantamax Wheel

A client-only Fabric sidemod adding a Gigantamax button to Cobblemon's interaction wheel,
next to Mega Evolve.

## Why a sidemod rather than a patched Mega Showdown

Mega Showdown's licence (v2.1 §1.3) permits sidemods — addons that interact with the mod but
contain no substantial portion of its code — to be built and shared without asking. A modified
build of the mod itself would need written permission from the author before being given to
anyone, including friends on a private server. This project contains no Mega Showdown code:
`unzip -l` the output and there is one class, a lang file and a manifest.

It is also the more durable choice. A fork needs rebuilding against every Mega Showdown
release; this talks only to Cobblemon's public interaction-wheel API, so it survives updates.

## How it works

`CobblemonEvents.POKEMON_INTERACTION_GUI_CREATION` → add an `InteractWheelOption` → on press,
send `/trigger gmax set <slot>`. The server's `gmaxwatch.py` does the rest.

All eligibility stays server-side, because the gate is `GmaxFactor`, which lives in the
party-store NBT. The button is always offered and the server refuses with a reason if the
Pokémon has not been fed a Max Soup or has no G-max model.

Mega Showdown's own icon is referenced by `ResourceLocation`, so it is read from its jar at
runtime and never copied into ours.

## Building

    JAVA_HOME=/path/to/jdk-21 ./gradlew build

Output: `build/libs/niftygmax-1.0.0.jar`. Drop it in `.minecraft/mods`.

Three things that cost time and are easy to hit again:

- **Kotlin plugin must be 2.2.x.** Loom takes its kotlinx-metadata support from the Kotlin
  plugin on the classpath. With 2.0.20 it cannot remap Cobblemon and fails with "cannot write
  metadata for future compiler versions. Requested 2.2.0, but highest known version is 2.1.0".
- **Use architectury loom, not plain fabric-loom.** Loom 1.7 is too old for Gradle 8.12 and
  1.9 still could not remap Cobblemon.
- **Do not depend on fabric-api or fabric-language-kotlin.** Neither is needed to compile;
  fabric-api's 52 modules failed to remap on a duplicate `package-info`, and FLK is a runtime
  language adapter that Cobblemon already bundles.
