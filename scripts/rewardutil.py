# -*- coding: utf-8 -*-
"""Shared reward delivery for the cron-driven card rewards.

Two problems this solves, both reported from real play:

1. `/give` silently drops the item at the player's feet when their inventory is full. A
   player who earned something while flying would never know, and the item despawns. So we
   check for a free main-inventory slot FIRST and simply do not grant until there is one --
   the reward stays pending and the player is told exactly what is waiting and why.

2. The old messages were private and vague ("Generation 4 complete"). Rewards are now
   announced to everyone and name the exact item, so the four of us can react to each
   other's milestones.

Free-slot detection uses `data get entity <player> Inventory`, whose response lists every
occupied slot as `Slot: Nb`. Main inventory is slots 0-35; armour (100-103) and offhand
(-106) are excluded because /give never targets them.
"""
import re

MAIN_SLOTS = 36
EXTRA_SLOTS = (100, 101, 102, 103, -106)   # armour + offhand; /give never targets these
OBJECTIVE = "niftytmp"
HOLDER = "#inv"

# Reward sounds, keyed by the announcement colour so the rare rewards sound rare.
# Nothing is pitched ABOVE 1.0 -- pitched-up vanilla sounds read as wrong rather than special.
# The default levelup only fires every 5th XP level in vanilla, so it is unfamiliar on purpose.
SOUNDS = {
    "light_purple": ("minecraft:ui.toast.challenge_complete", "1"),    # God Pack Tickets
    "gold":         ("minecraft:entity.player.levelup", "0.8"),        # booster packs
}


def article(word):
    """"an Ice Booster Pack", "a God Pack Ticket"."""
    return "an" if word[:1].upper() in "AEIOU" else "a"


def free_main_slot(rcon, name):
    """True if a /give will land in the inventory, False if full, None if unknown.

    Do NOT parse `data get entity <player> Inventory` directly: RCON caps a response at 4096
    bytes and a single Cobblemon Cards binder carries enough component NBT to blow past that
    on its own. The truncated list silently loses slots, so the count reads far too low and a
    full inventory looks like it has room -- the exact failure this guard exists to prevent.
    (Measured live: real inventory 27/36, truncated parse reported 7.)

    Instead let the server do the counting. `execute store result` on a `data get` of a list
    stores the LIST LENGTH, which comes back as one small number. That length covers armour
    (100-103) and offhand (-106) as well, and /give never targets those, so query them
    individually -- `.id` keeps each response tiny -- and subtract.
    """
    rcon("scoreboard objectives add %s dummy" % OBJECTIVE)      # no-op if it exists
    rcon("scoreboard players set %s %s 0" % (HOLDER, OBJECTIVE))
    probe = rcon("execute store result score %s %s run data get entity %s Inventory"
                 % (HOLDER, OBJECTIVE, name))
    if "entity data" not in probe:
        return None                                             # offline, or unreadable

    got = rcon("scoreboard players get %s %s" % (HOLDER, OBJECTIVE))
    m = re.search(r"has (\d+) ", got)
    if not m:
        return None
    total = int(m.group(1))

    outside = 0
    for slot in EXTRA_SLOTS:
        r = rcon("data get entity %s Inventory[{Slot:%db}].id" % (name, slot))
        if "entity data" in r:
            outside += 1

    return (total - outside) < MAIN_SLOTS


def deliver(rcon, log, name, item, pretty, deed, colour="gold", dry=False):
    """Give `item` to `name`, announcing it by name to everyone.

    Returns True only when the item is confirmed in hand -- callers persist their state on
    True and leave the reward pending on False, so a full inventory just means "later".
    """
    if dry:
        log("[dry-run] would give %s -> %s (%s)" % (name, item, pretty))
        return False

    room = free_main_slot(rcon, name)
    if room is False:
        log("%s earned %s but inventory is FULL - holding" % (name, pretty))
        rcon('tellraw %s [{"text":"You earned %s ","color":"red"},'
             '{"text":"%s","color":"%s","bold":true},'
             '{"text":" but your inventory is full. Free a slot and it will be delivered '
             'within a few minutes.","color":"red"}]'
             % (name, article(pretty), pretty, colour))
        return False

    res = rcon("give %s %s 1" % (name, item))
    if "Gave" not in res:
        log("give FAILED for %s (%s): %s" % (name, item, res[:120]))
        return False

    # CONFIRM IT LANDED. "Gave" only means the command was ACCEPTED. On 2026-09-01
    # a player's Generation 4 pack logged GRANTED with "Gave" in the response and was
    # simply not in his inventory afterwards - he was online, had 30/36 slots used, did
    # not die and did not open it. Because the caller persisted state on True, the cron
    # never retried and the reward was silently lost. He had an Arc Phone Ender Chest
    # screen open ~49s earlier, which is the best lead but is not proven.
    #
    # `clear <player> <item> 0` is a READ-ONLY probe - it reports how many match and
    # removes nothing (verified against items the player demonstrably had). If the item
    # is not actually there, do not return True: leave the reward pending so the next
    # pass retries it, and make the failure loud instead of silent.
    check = rcon("clear %s %s 0" % (name, item))
    if "Found" not in check:
        log("give SAID OK BUT ITEM IS NOT PRESENT for %s (%s): %s - left pending"
            % (name, pretty, check[:80]))
        rcon('tellraw %s [{"text":"Your %s could not be delivered - it will retry in a'
             ' few minutes. Close any chest or menu you have open.","color":"red"}]'
             % (name, pretty))
        return False

    rcon('tellraw @a [{"text":"%s","color":"white","bold":true},'
         '{"text":" earned %s ","color":"%s"},'
         '{"text":"%s","color":"%s","bold":true},'
         '{"text":" for %s!","color":"%s"}]'
         % (name, article(pretty), colour, pretty, colour, deed, colour))
    # `execute at` is essential: this runs from the CONSOLE, where a bare `~ ~ ~` resolves to
    # world origin (0,0,0). The sound then plays thousands of blocks away -- faint, oddly
    # timbred and panned to one ear. Anchor it to the player instead.
    sound, pitch = SOUNDS.get(colour, SOUNDS["gold"])
    rcon("execute at %s run playsound %s player %s ~ ~ ~ 1 %s" % (name, sound, name, pitch))
    if room is None:
        # could not verify space; make sure they look down rather than fly on
        rcon('tellraw %s [{"text":"-> If your inventory was full, it dropped at your feet - '
             'stop and pick it up.","color":"yellow"}]' % name)
    log("GRANTED %s -> %s (%s)" % (name, item, pretty))
    return True
