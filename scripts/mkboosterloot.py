"""Add a rare Booster Pack to every Cobblemon-Additions town chest.

Rate: the owner asked for 3x the Master Ball chance. Measured chain, bedroom chests only:
  bedroom -> poke_balls 8/79 -> normal_balls 2/5 -> master_ball 1/942
  = 0.0043% per roll, ~13 rolls per chest = 0.0559% per chest.
Tripled = 0.1677% per chest, and applied to ALL 12 room types rather than bedroom alone,
so it is actually reachable.

Implementation: a datapack OVERRIDE of each general/<room>.json - vanilla datapacks cannot
append to a loot table, so the original must be reproduced verbatim and one pool added.
That pool is self-contained: rolls 1, booster pack weight 1 against air weight 594, which
is 1/595 = 0.1681% per chest regardless of how the mod's own pool is shaped.

BCA's JSON carries a UTF-8 BOM - read with utf-8-sig or json.load raises.

STALENESS RISK: because this is a full override, a Cobblemon-Additions update that changes
these tables will be masked by this datapack. Re-run this script after any BCA update.
"""
import zipfile, json, os, shutil

JAR = "$COBBLEMON_DIR/mods/cobblemon-additions-4.3.0.jar"
OUT = "$COBBLEMON_DIR/world/datapacks/nifty-booster-loot"
PACK = "cobblemon-cards:booster_pack"
AIR_WEIGHT = 594          # 1/(1+594) = 0.1681% per chest

z = zipfile.ZipFile(JAR)
rooms = [n for n in z.namelist()
         if "/loot_table/general/" in n and n.endswith(".json")]

if os.path.isdir(OUT):
    shutil.rmtree(OUT)
os.makedirs(os.path.join(OUT, "data/bca/loot_table/general"), exist_ok=True)

with open(os.path.join(OUT, "pack.mcmeta"), "w", encoding="utf-8") as f:
    json.dump({"pack": {"pack_format": 48,
                        "description": "Rare Cobblemon Cards booster packs in BCA town chests"}},
              f, indent=2)

extra_pool = {
    "rolls": 1,
    "entries": [
        {"type": "minecraft:item", "name": PACK, "weight": 1},
        {"type": "minecraft:item", "name": "minecraft:air", "weight": AIR_WEIGHT},
    ],
}

made = 0
for n in sorted(rooms):
    d = json.loads(z.read(n).decode("utf-8-sig"))
    # guard against double-adding if this is ever re-run against its own output
    d.setdefault("pools", []).append(json.loads(json.dumps(extra_pool)))
    room = n.split("/")[-1]
    with open(os.path.join(OUT, "data/bca/loot_table/general", room), "w",
              encoding="utf-8") as f:
        json.dump(d, f, indent=2)
    made += 1
    print("  wrote %-20s (%d pools now)" % (room, len(d["pools"])))

print()
print("%d room tables overridden, booster pack at 1/%d = %.4f%% per chest"
      % (made, AIR_WEIGHT + 1, 100.0 / (AIR_WEIGHT + 1)))
