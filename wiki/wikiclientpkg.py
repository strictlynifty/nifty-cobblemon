# -*- coding: utf-8 -*-
"""Describe the download packages from the packages themselves.

This used to be a hand-written /tmp/wiki_clientpkg.json. That is how the page came to
advertise a LinguaChat build the package did not actually contain, and how it would have
kept claiming two resource packs after a third was added. Read the files people actually
download, so the page cannot drift from them.

Also emits a short content hash per package. The wiki appends it to the download link as
?v=<hash>, which gives Cloudflare a fresh cache key whenever the bytes change - otherwise
a replaced package keeps serving stale from the edge for a full day.

Writes /tmp/wiki_clientpkg.json.
"""
import zipfile, json, os, sys, hashlib

DL = sys.argv[1] if len(sys.argv) > 1 else "/var/www/dl"
CLIENT = os.path.join(DL, "cobblemon-client-package.zip")
SERVER = os.path.join(DL, "cobblemon-server-package.zip")


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


if not os.path.exists(CLIENT):
    sys.exit("client package not found at %s" % CLIENT)

z = zipfile.ZipFile(CLIENT)
names = z.namelist()
mods = sorted(n.split("/", 1)[1] for n in names
              if n.startswith("mods/") and n.endswith(".jar"))
packs = sorted(n.split("/", 1)[1] for n in names
               if n.startswith("resourcepacks/") and n.endswith(".zip"))

out = {
    "client_mods": mods,
    "resourcepacks": packs,
    "package": "cobblemon-client-package.zip",
    "package_mb": int(round(os.path.getsize(CLIENT) / 1048576.0)),
    "package_sha": digest(CLIENT),
    "docs": sorted(n for n in names if n.endswith(".txt") and "/" not in n),
}

# the small delta for players who already have the big pack
import glob as _glob
# Prefer a content-hashed filename. Reusing one name across rebuilds is how people ended
# up downloading a stale copy from the CDN cache: the bare URL kept serving an older build
# for its full 24h TTL. A name that changes with the bytes cannot be served stale.
import re as _re
_upd = [u for u in _glob.glob(os.path.join(DL, "NiftySMP-update-*.zip"))
        if not u.endswith(".sha256")]
_hashed = [u for u in _upd if _re.search(r"-[0-9a-f]{8}\.zip$", os.path.basename(u))]
_upd = sorted(_hashed or _upd, key=os.path.getmtime)
if _upd:
    _u = _upd[-1]
    _uz = zipfile.ZipFile(_u)
    out["update_package"] = os.path.basename(_u)
    out["update_mb"] = int(round(os.path.getsize(_u) / 1048576.0))
    out["update_sha"] = digest(_u)
    out["update_mods"] = sum(1 for n in _uz.namelist()
                             if n.startswith("mods/") and n.endswith(".jar"))

if os.path.exists(SERVER):
    sz = zipfile.ZipFile(SERVER)
    out["server_package"] = "cobblemon-server-package.zip"
    out["server_mb"] = int(round(os.path.getsize(SERVER) / 1048576.0))
    out["server_sha"] = digest(SERVER)
    out["server_mods"] = sum(1 for n in sz.namelist() if n.endswith(".jar"))

json.dump(out, open("/tmp/wiki_clientpkg.json", "w"), separators=(",", ":"))
if out.get("update_package"):
    print("update: %s, %d mods, %d MB" % (out["update_package"], out["update_mods"], out["update_mb"]))
print("client: %d mods, %d resource packs, %d MB (%s)"
      % (len(mods), len(packs), out["package_mb"], out["package_sha"][:8]))
for p in packs:
    print("   pack:", p)
if "server_package" in out:
    print("server: %d jars, %d MB (%s)"
          % (out["server_mods"], out["server_mb"], out["server_sha"][:8]))
