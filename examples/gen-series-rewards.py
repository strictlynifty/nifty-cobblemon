# -*- coding: utf-8 -*-
"""Generate the `nifty-card-rewards` datapack: booster packs for RCT battle series milestones.

Why it is built this way (all verified against rctmod-fabric-1.21.1-0.18.1-beta.jar):

  * `rctmod:defeat_count` conditions are {count, entity, trainer_ids, trainer_type}.

  * With a NON-EMPTY `trainer_ids`, DefeatCountTriggerInstance.matches() checks whether the
    trainer just defeated is in the list and then whether the player's defeat count *for that
    one trainer* is >= count. It is NOT "N distinct trainers from the list". So a milestone
    like "any 4 of these 8 leaders" cannot be a single criterion -- it is 8 criteria plus a
    CNF `requirements` block.

  * The `trainer_type` branch DOES count distinct trainers, but it calls getAllData() with an
    empty varargs array, which returns every trainer in every series. So trainer_type is
    unusable for a per-series milestone. Hence: explicit trainer_ids, always.

  * Criteria pinned to trainer_ids only evaluate when that exact trainer is defeated, so past
    defeats never back-fill. Catch-up is handled separately by catchup-series-rewards.py.
"""
import itertools, json, os, sys

OUT = sys.argv[1] if len(sys.argv) > 1 else "build/nifty-card-rewards"
NS = "nifty"

SERIES = {
    "radicalred": {
        "region": "Kanto",
        "leaders": ["leader_brock_019e", "leader_misty_019f", "leader_lt_surge_01a0",
                    "leader_erika_01a1", "leader_koga_01a2", "leader_sabrina_01a4",
                    "leader_blaine_01a3", "leader_clair_004a"],
        "champs": ["champion_terry_01b6", "champion_terry_01b7", "champion_terry_01b8"],
        "pack4": "poison", "pack8": "psychic", "champ_pack": "gen1",
        "why4": "Koga", "why8": "Sabrina",
        "deed4": "taking four Kanto Gym Badges",
        "deed8": "sweeping all eight Kanto Gym Badges",
        "deedc": "becoming Kanto Champion",
    },
    "bdsp": {
        "region": "Sinnoh",
        "leaders": ["gym_leader_roark_0395", "gym_leader_gardenia_03d6", "gym_leader_maylene_03d8",
                    "gym_leader_wake_03d7", "gym_leader_fantina_03d9", "gym_leader_byron_0399",
                    "gym_leader_candice_03da", "gym_leader_volkner_03db"],
        "champs": ["champion_cynthia_03a5"],
        "pack4": "ice", "pack8": "steel", "champ_pack": "gen4",
        "why4": "Candice", "why8": "Byron",
        "deed4": "taking four Sinnoh Gym Badges",
        "deed8": "sweeping all eight Sinnoh Gym Badges",
        "deedc": "becoming Sinnoh Champion",
    },
    "unbound": {
        "region": "Hoenn",
        "leaders": ["leader_mirskle_05aa", "leader_vega_05ab", "leader_alice_05ac",
                    "leader_mel_05ad", "leader_galavan_05af", "leader_big_mo_05b0",
                    "leader_tessy_05b1", "leader_benjamin_05b2"],
        "champs": ["champion_jax_05b7"],
        "pack4": "flying", "pack8": "dark", "champ_pack": "gen3",
        "why4": "Alice", "why8": "Vega",
        "deed4": "taking four Hoenn Gym Badges",
        "deed8": "sweeping all eight Hoenn Gym Badges",
        "deedc": "becoming Hoenn Champion",
    },
}

def w(relpath, obj):
    p = os.path.join(OUT, relpath)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")

def defeat(trainer_ids, count=1):
    return {"trigger": "rctmod:defeat_count",
            "conditions": {"count": count, "entity": {"type": None},
                           "trainer_ids": list(trainer_ids), "trainer_type": None}}

def loot(item):
    """One loot table per reward item, granted straight into the player's inventory."""
    w("data/%s/loot_table/rewards/%s.json" % (NS, item),
      {"type": "minecraft:advancement_reward",
       "pools": [{"rolls": 1, "entries": [{"type": "minecraft:item",
                                           "name": "cobblemon-cards:" + item}]}]})
    return "%s:rewards/%s" % (NS, item)

PRETTY = {
    "booster_pack_poison": "Poison Booster Pack", "booster_pack_psychic": "Psychic Booster Pack",
    "booster_pack_ice": "Ice Booster Pack", "booster_pack_steel": "Steel Booster Pack",
    "booster_pack_flying": "Flying Booster Pack", "booster_pack_dark": "Dark Booster Pack",
    "booster_pack_gen1": "Generation 1 Booster Pack", "booster_pack_gen3": "Generation 3 Booster Pack",
    "booster_pack_gen4": "Generation 4 Booster Pack", "god_pack_ticket": "God Pack Ticket",
}


def announce_fn(name, reward_item, deed):
    """Runs as the player the instant the advancement completes.

    Names the exact reward publicly so everyone can react to it, and tells the earner to look
    at their feet -- an advancement loot reward drops on the ground when the inventory is
    full, and someone flying at the time would otherwise never know it happened.
    """
    pretty = PRETTY[reward_item]
    art = "an" if pretty[:1].upper() in "AEIOU" else "a"
    colour = "light_purple" if reward_item == "god_pack_ticket" else "gold"
    # keep in step with rewardutil.SOUNDS so a ticket sounds identical however it is earned
    sound, pitch = (("minecraft:ui.toast.challenge_complete", "1")
                    if reward_item == "god_pack_ticket"
                    else ("minecraft:entity.player.levelup", "0.8"))
    lines = [
        'tellraw @a [{"selector":"@s","color":"white","bold":true},'
        '{"text":" earned %s ","color":"%s"},'
        '{"text":"%s","color":"%s","bold":true},'
        '{"text":" for %s!","color":"%s"}]' % (art, colour, pretty, colour, deed, colour),
        'tellraw @s [{"text":"-> The %s is in your inventory. If your inventory was full, '
        'it dropped at your feet - stop and pick it up.","color":"yellow"}]' % pretty,
        "playsound %s player @s ~ ~ ~ 1 %s" % (sound, pitch),
    ]
    p = os.path.join(OUT, "data/%s/function/reward/%s.mcfunction" % (NS, name))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(chr(10).join(lines) + chr(10))
    return "%s:reward/%s" % (NS, name)


def adv(path, parent, title, desc, icon, frame, criteria, requirements, reward_item, deed):
    body = {
        "display": {"icon": {"id": icon}, "title": title, "description": desc,
                    "frame": frame, "show_toast": True, "announce_to_chat": True,
                    "hidden": False},
        "criteria": criteria,
        "requirements": requirements,
        "rewards": {"loot": [loot(reward_item)],
                    "function": announce_fn(path.replace("/", "_"), reward_item, deed)},
    }
    if parent:
        body["parent"] = parent
    else:
        body["display"]["background"] = "minecraft:textures/block/amethyst_block.png"
    w("data/%s/advancement/%s.json" % (NS, path), body)
    return "%s:%s" % (NS, path)


def at_least_4_of_8(keys):
    """CNF for 'at least 4 of these 8 are satisfied'.

    Minecraft `requirements` is an AND of ORs. "At least 4 of 8 hold" is equivalent to
    "every 5-element subset contains at least one that holds" -- if only 3 held, the 5
    that did not would form an all-false group. C(8,5) = 56 groups.
    """
    return [list(c) for c in itertools.combinations(keys, 5)]


# --- root -----------------------------------------------------------------
w("pack.mcmeta", {"pack": {"pack_format": 48,
                           "supported_formats": {"min_inclusive": 34, "max_inclusive": 48},
                           "description": "Booster pack rewards for RCT battle series milestones"}})
w("data/%s/advancement/root.json" % NS, {
    "display": {"icon": {"id": "cobblemon-cards:booster_pack"},
                "title": "Trainer Card Rewards", "description": "Booster packs for beating battle series.",
                "frame": "task", "show_toast": False, "announce_to_chat": False, "hidden": False,
                "background": "minecraft:textures/block/amethyst_block.png"},
    "criteria": {"tick": {"trigger": "minecraft:tick"}},
    "requirements": [["tick"]],
})

champ_criteria, champ_reqs = {}, []
made = []

for sid, s in SERIES.items():
    leaders, region = s["leaders"], s["region"]
    crit = {("leader_%d" % i): defeat([t]) for i, t in enumerate(leaders)}
    keys = sorted(crit)

    made.append(adv("series/%s_4" % sid, "%s:root" % NS,
        "Four Badges: %s" % region,
        "Defeat four Gym Leaders in the %s series." % sid,
        "cobblemon-cards:booster_pack_" + s["pack4"], "goal",
        crit, at_least_4_of_8(keys), "booster_pack_" + s["pack4"], s["deed4"]))

    made.append(adv("series/%s_8" % sid, "%s:series/%s_4" % (NS, sid),
        "Eight Badges: %s" % region,
        "Defeat every Gym Leader in the %s series." % sid,
        "cobblemon-cards:booster_pack_" + s["pack8"], "goal",
        crit, [[k] for k in keys], "booster_pack_" + s["pack8"], s["deed8"]))

    made.append(adv("series/%s_champ" % sid, "%s:series/%s_8" % (NS, sid),
        "%s Champion" % region,
        "Defeat the Champion of the %s series." % sid,
        "cobblemon-cards:booster_pack_" + s["champ_pack"], "challenge",
        {"champion": defeat(s["champs"])}, [["champion"]], "booster_pack_" + s["champ_pack"],
        s["deedc"]))

    champ_criteria["champion_%s" % sid] = defeat(s["champs"])
    champ_reqs.append(["champion_%s" % sid])

made.append(adv("series/all_champions", "%s:root" % NS,
    "Triple Crown", "Defeat the Champion of all three battle series.",
    "cobblemon-cards:god_pack_ticket", "challenge",
    champ_criteria, champ_reqs, "god_pack_ticket",
    "conquering all three battle series"))

print("wrote %d advancements + root into %s" % (len(made), OUT))
for m in made:
    print("   ", m)
