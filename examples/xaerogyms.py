"""Write the Kanto gym waypoints straight into Xaero's own files, in the default set.

The server_waypoint mod did push them, but into a separate set ("Gyms") with visibility_type 1
- so they only appear if you switch sets in the Xaero menu. Every one of the owner's own 346
waypoints uses set `gui.xaero_default` and visibility_type 0, so match that exactly and they
show up with everything else.

Format, from the header comment in the file itself:
  waypoint:name:initials:x:y:z:color:disabled:type:set:rotate_on_tp:tp_yaw:visibility_type:destination

Xaero holds waypoints in memory and rewrites these files when it saves, so this must be run
with Minecraft CLOSED or the edit is lost on exit.
"""
import io, os, shutil, sys

# Xaero stores waypoints per server, in a folder named after the address you connect to.
# Set MC_SERVER_ADDR, or point XAERO_DIR straight at the folder.
BASE = os.environ.get("XAERO_DIR") or os.path.join(
    os.path.expanduser("~"), "AppData", "Roaming", ".minecraft", "xaero", "minimap",
    "Multiplayer_" + os.environ.get("MC_SERVER_ADDR", "example.com"))

# dim folder -> waypoints (name, initials, x, y, z, colour)
GYMS = {
    "dim%0": [
        ("Pewter Gym (Rock - 1st)",      "1P", 10240, 70, 688,   6),
        ("Cerulean Gym (Water - 2nd)",   "2C", 10096, 70, -8464, 1),
        ("Vermilion Gym (Electric - 3rd)", "3V", 10048, 70, -8672, 4),
        ("Celadon Gym (Grass - 4th)",    "4C", 10048, 70, 6464,  10),
        ("Saffron Gym (Psychic - 5th)",  "5S", 10016, 70, -5360, 13),
        ("Fuchsia Gym (Poison - 6th)",   "6F", 9968,  70, 5968,  5),
    ],
    "dim%-1": [
        ("Cinnabar Gym (Fire - 7th)",    "7C", -496,  70, 688,   14),
    ],
    "dim%1": [
        ("Blackthorn Gym (Dragon)",      "BD", -880,  60, -800,  12),
        ("Kanto League (Champion)",      "KL", -816,  60, -1520, 4),
    ],
}


def line(name, initials, x, y, z, colour):
    # matches the owner's existing entries: enabled, default set, visibility 0
    return ("waypoint:%s:%s:%d:%d:%d:%d:false:0:gui.xaero_default:false:0:0:false"
            % (name, initials, x, y, z, colour))


def main():
    for dim, wps in GYMS.items():
        path = os.path.join(BASE, dim, "mw$0_1.txt")
        if not os.path.exists(path):
            print("  MISSING %s" % path)
            continue
        if not os.path.exists(path + ".bak-pregyms"):
            shutil.copy2(path, path + ".bak-pregyms")
        text = io.open(path, encoding="utf-8", newline="").read()
        nl = "\r\n" if text.count("\r\n") > text.count("\n") / 2 else "\n"

        # drop any previous copy of ours, by name, in either set
        keep = [ln for ln in text.split(nl)
                if not any((":%s:" % w[0]) in ln for w in wps)]
        added = 0
        for w in wps:
            keep.append(line(*w))
            added += 1
        out = nl.join(ln for ln in keep if ln.strip() != "") + nl
        io.open(path, "w", encoding="utf-8", newline="").write(out)
        total = sum(1 for ln in out.split(nl) if ln.startswith("waypoint:"))
        print("  %-8s +%d gym waypoints  (%d total in file)" % (dim, added, total))


if __name__ == "__main__":
    main()
