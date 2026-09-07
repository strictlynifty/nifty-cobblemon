# -*- coding: utf-8 -*-
"""Track whether the mods blocking a Cobblemon 1.8 update have shipped 1.8 builds.

Cobblemon 1.8 landed 2026-09-06. Three installed mods pin `cobblemon: 1.7.3+1.21.1` EXACTLY
and would refuse to load on it - tim_core, and capture_xp and spawn_notification which both
depend on tim_core. Mega Showdown's 1.8 build was beta-only on release day. Until those clear,
updating breaks the server, so this answers "is it ready yet" without a research session.

Identifies each jar by SHA1 through Modrinth's bulk hash lookup rather than guessing slugs, so
it keeps working when a file is renamed, and reports the newest published version of every
Cobblemon-dependent mod installed. Most of these embed the Cobblemon version they target in
their own version string (`1.7.3-fabric-2.3.0`, `1.9.9+1.7.3+1.21.1`), which is the signal to
read: when those flip to 1.8, the blocker is gone.

Runs on the server, stdlib only:
    python3 modwatch.py [--json /path/to/report.json]
"""
import glob
import hashlib
import json
import os
import re
import sys
import urllib.request

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")

MODS = COBBLEMON_DIR + "/mods"
API = "https://api.modrinth.com/v2"
UA = "nifty-modwatch/1.0 (private server maintenance)"

# Mods that pin an exact Cobblemon version, so a 1.8 update cannot even start with them
# installed. tim_core is the root: capture_xp and spawn_notification both depend on it.
BLOCKERS = ("tim_core", "capture_xp", "spawn_notification")


def api(path, data=None):
    req = urllib.request.Request(API + path, data=data,
                                 headers={"User-Agent": UA,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def mod_meta(p):
    """(id, version, cobblemon dependency) from the jar's own manifest."""
    import zipfile
    try:
        raw = zipfile.ZipFile(p).read("fabric.mod.json").decode("utf-8-sig")
    except Exception:
        return (os.path.basename(p), "?", "")
    def g(k):
        m = re.search(r'"%s"\s*:\s*"([^"]*)"' % k, raw)
        return m.group(1) if m else ""
    dep = re.search(r'"depends"\s*:\s*\{(.*?)\}', raw, re.S)
    cob = ""
    if dep:
        m = re.search(r'"cobblemon"\s*:\s*"([^"]*)"', dep.group(1))
        cob = (m.group(1) if m else "").replace("\\u003e", ">").replace("\\u003d", "=")
    return (g("id"), g("version"), cob)


def targets_18(installed, newest):
    """Does `newest` name Cobblemon 1.8 where `installed` names 1.7?

    A bare "1.8" substring is not enough: cobblemon_party_extras is on its OWN version
    1.8.15 and has nothing to do with Cobblemon 1.8. These version strings embed the
    Cobblemon version as one dot-separated token among several - "1.7.3-fabric-2.3.0",
    "1.9.5+1.7.3+1.21.1" - so find which token carries 1.7 in the installed string and read
    the same slot in the new one. A mod that does not encode it at all is left unflagged
    rather than guessed at.
    """
    a = re.split(r"[-+]", installed or "")
    b = re.split(r"[-+]", newest or "")
    for i, tok in enumerate(a):
        if tok.startswith("1.7"):
            return i < len(b) and b[i].startswith("1.8")
    return False


def main():
    jars = sorted(glob.glob(os.path.join(MODS, "*.jar")))
    meta, hashes = {}, {}
    for p in jars:
        mid, ver, cob = mod_meta(p)
        if not cob:
            continue                    # not a Cobblemon addon; an update cannot block on it
        h = hashlib.sha1(open(p, "rb").read()).hexdigest()
        meta[h] = (mid, ver, cob, os.path.basename(p))
        hashes[h] = p

    found = {}
    if hashes:
        body = json.dumps({"hashes": list(hashes), "algorithm": "sha1"}).encode()
        try:
            found = api("/version_files", body)
        except Exception as e:
            print("modrinth lookup failed: %s" % e, file=sys.stderr)

    # Resolve what Cobblemon version each candidate actually depends on, rather than reading
    # it off the version string. rctmod 0.19.0-beta is the case that matters: its name says
    # nothing about 1.8 but it REQUIRES it, so listing it as a safe in-line update would
    # break the server.
    cobver = {}
    try:
        cid = api("/project/cobblemon")["id"]
        for cv in api("/project/%s/version" % cid):
            cobver[cv["id"]] = cv.get("version_number", "")
    except Exception:
        cid = None

    def needs_cobblemon(v):
        """What Cobblemon version this release wants, or '' if it does not say.

        Two sources, because neither is reliable alone. A dependency entry only names a
        Cobblemon version when the author pinned one - rctmod 0.19.0-beta depends on the
        project with no version_id, yet its changelog says "Update min required version of
        Cobblemon to 1.8". Recommending that as a safe in-line update would stop the server
        booting, so read the changelog too, and treat anything unresolved as UNKNOWN rather
        than safe.
        """
        for d in (v.get("dependencies") or []):
            if d.get("project_id") == cid and d.get("version_id"):
                return cobver.get(d["version_id"], "")
        log = (v.get("changelog") or "")
        m = re.search(r"[Cc]obblemon\D{0,40}?(\d+\.\d+(?:\.\d+)?)", log)
        if m:
            return m.group(1)
        for d in (v.get("dependencies") or []):
            if d.get("project_id") == cid:
                return "?"          # depends on Cobblemon but does not say which version
        return ""

    rows = []
    for h, (mid, ver, cob, fn) in sorted(meta.items(), key=lambda kv: kv[1][0]):
        newest, when, proj, newer, wants = "", "", "", False, ""
        compat, compat_at = "", ""
        v = found.get(h)
        if v:
            proj = v.get("project_id", "")
            mine = v.get("date_published") or ""
            try:
                vs = api("/project/%s/version" % proj)
                vs.sort(key=lambda x: x.get("date_published", ""), reverse=True)
                vs = [x for x in vs if "fabric" in (x.get("loaders") or ["fabric"])] or vs
                if vs:
                    newest = vs[0].get("version_number", "")
                    when = (vs[0].get("date_published") or "")[:10]
                    newer = bool(mine) and (vs[0].get("date_published") or "") > mine
                    wants = needs_cobblemon(vs[0])
                    # When the newest release has moved to 1.8, the useful answer is the
                    # newest one that has NOT - Mega Showdown's newest is a 1.8 beta, but
                    # 1.9.9 on the 1.7.3 line is a real update we can take today.
                    if wants.startswith("1.8") or targets_18(ver, newest):
                        for x in vs:
                            xn = x.get("version_number", "")
                            if targets_18(ver, xn) or needs_cobblemon(x).startswith("1.8"):
                                continue
                            if (x.get("date_published") or "") > mine:
                                compat = xn
                                compat_at = (x.get("date_published") or "")[:10]
                            break
            except Exception:
                pass
        exact = bool(re.match(r"^\d+\.\d+", cob.strip()))     # a pin, not a range
        ready = targets_18(ver, newest)
        rows.append(dict(id=mid, installed=ver, needs=cob, newest=newest, published=when,
                         blocker=mid in BLOCKERS, exact_pin=exact, looks_18=ready,
                         newer=newer, wants=wants, compat=compat,
                         compat_at=compat_at, file=fn, project=proj))

    print("%-26s %-24s %-16s %-26s %-10s" %
          ("mod", "installed", "needs cobblemon", "newest published", "date"))
    for r in rows:
        mark = "!" if r["blocker"] else (" " if not r["exact_pin"] else "?")
        star = " <-- 1.8?" if r["looks_18"] else ""
        print("%s %-24s %-24s %-16s %-26s %-10s%s"
              % (mark, r["id"][:24], r["installed"][:24], r["needs"][:16],
                 r["newest"][:26] or "-", r["published"] or "-", star))

    # genuinely newer by publish date, and not one that has moved to 1.8
    behind = [r for r in rows
              if r["newer"] and not r["looks_18"] and r["wants"] not in ("?",)
              and not r["wants"].startswith("1.8")]
    needs18 = [r for r in rows if r["newer"] and r["wants"].startswith("1.8")]
    unsure = [r for r in rows if r["newer"] and r["wants"] == "?"]
    if behind:
        print()
        print("safe updates on the CURRENT Cobblemon line:")
        for r in behind:
            print("   %-24s %-24s -> %-26s %s"
                  % (r["id"], r["installed"][:24], r["newest"], r["published"]))
    if needs18:
        print()
        print("newer, but REQUIRES Cobblemon 1.8 - do not install yet:")
        for r in needs18:
            print("   %-24s -> %-26s (needs cobblemon %s)"
                  % (r["id"], r["newest"], r["wants"]))
            if r["compat"]:
                print("      but %s (%s) is newer than yours and still on 1.7"
                      % (r["compat"], r["compat_at"]))
    if unsure:
        print()
        print("newer, but the Cobblemon requirement is not stated - CHECK before installing:")
        for r in unsure:
            print("   %-24s -> %-26s https://modrinth.com/project/%s/version/%s"
                  % (r["id"], r["newest"], r["project"], r["newest"]))
            if r["compat"]:
                print("      but %s (%s) is newer than yours and still on 1.7"
                      % (r["compat"], r["compat_at"]))

    still = [r for r in rows if r["blocker"] and not r["looks_18"]]
    print()
    if still:
        print("STILL BLOCKING a Cobblemon 1.8 update: %s"
              % ", ".join(r["id"] for r in still))
        print("These pin an exact Cobblemon version; the server will not start with them "
              "installed once Cobblemon is 1.8.")
    else:
        print("No hard blockers left - every exact-pin mod has published something naming 1.8.")
        print("Check Mega Showdown is out of beta before committing.")

    if "--json" in sys.argv:
        out = sys.argv[sys.argv.index("--json") + 1]
        with open(out, "w") as f:
            json.dump(rows, f, indent=1)
        print("wrote %s" % out)


if __name__ == "__main__":
    main()
