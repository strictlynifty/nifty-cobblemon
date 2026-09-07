#!/usr/bin/env bash
# Build mc-wiki.html. Run from anywhere; operates on the Cobblemon server.
#
# ORDER MATTERS. wikiindex.py must run before build3.py: without /tmp/wiki_recipes.json
# the build still SUCCEEDS and merely prints "recipe index missing", silently dropping
# every one of the ~92 Pokedex tutorials. That failure is invisible in the output, so
# this script enforces the order and verifies the result.
#
# The template is versioned here (tools/wiki/wiki_tpl3.html), not left mutated in /tmp.
# Four one-shot patch scripts (wiki_uipatch / modbadge / gridpatch / stepspatch) were
# used to build it originally; wiki_tpl3.base.html is the pre-tutorial original kept for
# reference. Do not re-run those patches against the current template - it is the source
# of truth now, edit it directly.
set -euo pipefail

# Personal settings (WIKI_HOST, COBBLEMON_DIR, WIKI_SERVER_ADDR) live here and
# are gitignored, so nobody publishes their host by accident.
[ -f "$(dirname "${BASH_SOURCE[0]}")/local.env" ] && . "$(dirname "${BASH_SOURCE[0]}")/local.env"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# ssh alias or user@host of the server. Override: WIKI_HOST=myserver ./build-wiki.sh
HOST="${WIKI_HOST:?set WIKI_HOST to the ssh alias of your server}"
# The tools resolve the server directory from $COBBLEMON_DIR (default /srv/cobblemon). An ssh
# command inherits neither the crontab nor a login shell's environment, so pass it explicitly
# on every remote call, and it must be an `export` followed by `;` - passing it as a
# bare VAR=value prefix binds it only to the first command, so `cd /tmp && python3`
# runs the python without it and the build silently reads /srv/cobblemon instead.
REMOTE_DIR="${COBBLEMON_DIR:-/srv/cobblemon}"
# build3.py runs on the SERVER, so anything the page needs must cross the ssh
# boundary too - passing only COBBLEMON_DIR left the address as a placeholder.


# build3.py reads three inputs that NOTHING here regenerates - wiki_parts.json,
# wiki_data2.json and wiki_data3.json. They were produced once by one-off scripts and
# had been living only in /tmp, where `D /tmp` in tmpfiles.d wipes them on every boot.
# The box happened to have 20 days of uptime; one reboot would have made the wiki
# permanently unbuildable while the deployed page carried on looking fine.
# They now live in wiki-inputs/ on the server. Restore any that are missing before
# building, and fail loudly rather than building a half-empty page.
echo "==> restoring build inputs if /tmp was cleared"
ssh "$HOST" "export COBBLEMON_DIR=$REMOTE_DIR WIKI_SERVER_ADDR='${WIKI_SERVER_ADDR:-your server}';" 'set -e
  SRC=${COBBLEMON_DIR:-/srv/cobblemon}/wiki-inputs
  for f in wiki_parts.json wiki_data2.json wiki_data3.json; do
    if [ ! -s "/tmp/$f" ]; then
      if [ -s "$SRC/$f" ]; then cp -p "$SRC/$f" "/tmp/$f"; echo "    restored $f from wiki-inputs/";
      else echo "    FATAL: /tmp/$f missing and no copy in $SRC" >&2; exit 1; fi
    fi
  done'

echo "==> shipping template + scripts to $HOST"
scp -q "$HERE/wiki_tpl3.html" "$HOST:/tmp/wiki_tpl3.html"
scp -q "$HERE/wikiindex.py"   "$HOST:/tmp/wikiindex.py"
scp -q "$HERE/wikiclientpkg.py" "$HOST:/tmp/wikiclientpkg.py"
scp -q "$HERE/build3.py"      "$HOST:/tmp/build3.py"
# Sprite atlases are rendered locally (Pillow) and served from /mc-wiki-img/; only the
# manifest is needed at build time, to inline the lookup table.
scp -q "$HERE/dex-sprites.json" "$HOST:/tmp/dex-sprites.json" || echo "    (no dex-sprites.json - dex will build without pictures)"

echo "==> 0/2 describing the client package from the package itself"
ssh "$HOST" "export COBBLEMON_DIR=$REMOTE_DIR WIKI_SERVER_ADDR='${WIKI_SERVER_ADDR:-your server}';" 'python3 /tmp/wikiclientpkg.py'

echo "==> 1/2 building the recipe + acquisition index"
ssh "$HOST" "export COBBLEMON_DIR=$REMOTE_DIR WIKI_SERVER_ADDR='${WIKI_SERVER_ADDR:-your server}';" 'python3 /tmp/wikiindex.py'

echo "==> verifying the index landed"
ssh "$HOST" "export COBBLEMON_DIR=$REMOTE_DIR WIKI_SERVER_ADDR='${WIKI_SERVER_ADDR:-your server}';" 'test -s /tmp/wiki_recipes.json' || {
  echo "FATAL: /tmp/wiki_recipes.json missing or empty - refusing to build a wiki with no tutorials" >&2
  exit 1
}

echo "==> 2/2 building the page"
ssh "$HOST" "export COBBLEMON_DIR=$REMOTE_DIR WIKI_SERVER_ADDR='${WIKI_SERVER_ADDR:-your server}';" 'cd /tmp && python3 build3.py'

echo "==> verifying tutorials actually rendered"
ssh "$HOST" "export COBBLEMON_DIR=$REMOTE_DIR WIKI_SERVER_ADDR='${WIKI_SERVER_ADDR:-your server}';" 'python3 - <<PY
import io, re, sys, json
s = io.open("/tmp/mc-wiki.html", encoding="utf-8").read()
bad = []
if "function tutHtml" not in s:  bad.append("tutorial renderer missing from template")
if "mbadge" not in s:            bad.append("mod badges missing")
if "tgrid" not in s:             bad.append("crafting grids missing")
m = re.search(r"const DEX\s*=\s*\{", s)
st = m.start() + s[m.start():].index("{"); d = 0; j = st
while j < len(s):
    c = s[j]
    if c in "[{": d += 1
    elif c in "]}":
        d -= 1
        if d == 0: break
    elif c == chr(34):
        j += 1
        while j < len(s) and s[j] != chr(34):
            if s[j] == chr(92): j += 1
            j += 1
    j += 1
try:
    dex = json.loads(s[st:j+1])["dex"]
except Exception as e:
    bad.append("DEX payload does not parse: %s" % e); dex = []
n = sum(1 for p in dex if p.get("tut"))
# Counting tutorials is NOT enough: without the index 79 still attach from guide data
# alone, and only the resolved recipe CHAINS disappear. Check what actually breaks.
def _haschain(t):
    for node in [t.get("key")] + list(t.get("ki") or []) + list(t.get("it") or []):
        if isinstance(node, dict) and (node.get("r") or node.get("src")):
            return True
    return False
c = sum(1 for p in dex if p.get("tut") and _haschain(p["tut"]))
if n < 50: bad.append("only %d tutorials attached" % n)
if c < 40: bad.append("only %d tutorials have a resolved recipe/source chain - "
                      "wiki_recipes.json almost certainly did not load" % c)
for b in bad: print("FAIL:", b)
print("tutorials attached: %d, with a resolved chain: %d" % (n, c))
sys.exit(1 if bad else 0)
PY'

echo "==> fetching the build"
scp -q "$HOST:/tmp/mc-wiki.html" "$HERE/../../mc-wiki.html"
cd "$HERE/../.."
echo "sha256: $(sha256sum mc-wiki.html | cut -c1-16)  bytes: $(wc -c < mc-wiki.html)"
echo "OK - review, then copy to nifty-portfolio2/public/mc-wiki.html and commit that file ONLY"
