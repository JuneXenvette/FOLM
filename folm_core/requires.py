"""requires - what each installed mod needs, and whether you have it.

Three sources, strongest first:

1. The plugin's own startup check. Script extender plugins (.dll) that refuse to run without another
   plugin carry the message they show, e.g. Vegas Shaders: "LOD Flicker Fix not found. Vegas Shaders
   cannot be used without it" next to "LODFlickerFix.dll". FOLM reads those strings out of the DLL,
   so this works even when the mod page doesn't list the requirement (Vegas Shaders' doesn't).
2. FOLM's own list (KNOWN): requirements found by testing, with where to get them.
3. Nexus Mods' "Requirements" list for every mod that came from Nexus (the mod id is in the
   download's file name, or recorded by FOLM's Nexus download in versions before 1.1). Fetched from Nexus's public API
   (only mod ids are sent; no account or key), cached for a week, and used offline from the cache.

check(m) -> [{"severity", "mod", "needs", "how", "url", "notes"}]
  severity "error": the plugin itself says it won't run (sources 1 and 2)
  severity "warn":  the mod's Nexus page lists it as required
"""

import json
import os
import re
import time
import urllib.request

GRAPHQL = "https://api.nexusmods.com/v2/graphql"
CACHE_DAYS = 7
GAME_DOMAIN = {"courier": "newvegas", "wanderer": "fallout3"}

# Requirements found by testing: {plugin dll: [(required dll, mod name, url)]}
KNOWN = {
    "vegasshaders.dll": [("lodflickerfix.dll", "LOD Flicker Fix - NVSE", "https://www.nexusmods.com/newvegas/mods/91705"),
                         ("vanillaplusterrain.dll", "Vanilla Plus Terrain", "https://www.nexusmods.com/newvegas/mods/92519")],
    "lodflickerfix.dll": [("fallout shader loader.dll", "Shader Loader - NVSE",
                           "https://www.nexusmods.com/newvegas/mods/87814")],
    "vanillaplusterrain.dll": [("fallout shader loader.dll", "Shader Loader - NVSE",
                                "https://www.nexusmods.com/newvegas/mods/87814")],
}

# Nexus mods that aren't installed as ordinary mods: how to tell you have them anyway.
LOADERS = {"courier": "nvse_loader.exe", "wanderer": "fose_loader.exe"}


def _has_xnvse(m):
    """The game's script extender (xNVSE for New Vegas, FOSE for Fallout 3) is in the game folder,
    or in an enabled mod (not deployed yet)."""
    loader = LOADERS.get(m.edition, "nvse_loader.exe")
    if any(f.lower() == loader for f in os.listdir(m.data["game_dir"])):
        return True
    for mod in m.mods():
        d = os.path.join(m.mods_dir, mod["name"])
        if mod.get("enabled") and os.path.isdir(d):
            for _dp, _dn, fn in os.walk(d):
                if any(f.lower() == loader for f in fn):
                    return True
    return False


def _has_4gb(m):
    return m._exe_is_4gb() is not False


SPECIAL = {"newvegas": {67883: _has_xnvse, 62552: _has_4gb}, "fallout3": {8606: _has_xnvse}}

# Nexus requirement entries that don't apply on Linux, or that FOLM checks another way
WINDOWS_RUNTIME = re.compile(r"visual c\+\+|redistributable|vc_?redist|directx|\.net framework|xinput", re.I)
EXTENDER_WORDS = {"nvse", "xnvse", "fose", "new", "vegas", "fallout", "script", "extender", "latest", "version", "or",
                  "newer", "beta"}


def _is_extender(name):
    """'xNVSE 6', 'NVSE', 'New Vegas Script Extender (NVSE xNVSE)', 'FOSE', 'Fallout Script Extender' -> True;
    'JIP LN NVSE Plugin' -> False."""
    words = re.findall(r"[a-z]+|\d+", name.lower())
    return bool({"nvse", "xnvse", "fose"} & set(words) or {"script", "extender"} <= set(words)) and \
        all(w in EXTENDER_WORDS or w.isdigit() for w in words)
# "Only for X" / "optional" notes: the requirement applies only to some setups
CONDITIONAL = re.compile(r"\bonly (?:(?:required|needed|necessary|used) )?(?:for|if|when|with|in)\b|\bonly needed\b|\boptional\b|\bif you (?:use|want|have)\b|\bif using\b"
                         r"|\bsoft[ -]?req|\bnot (?:strictly )?required\b|\brecommended\b", re.I)
# Requirements that are modding tools, not something the game loads. The game never needs the GECK or
# xEdit (they're for making mods); a LOD generator is needed once, and its result is FOLM's Generated LOD.
AUTHORING_TOOL = re.compile(r"\bgeck\b|\b(?:x|fnv|fo3)edit\b", re.I)
LOD_TOOL = re.compile(r"lodgen", re.I)
# A guide is instructions to follow, not something to install
GUIDE = re.compile(r"\bguide\b", re.I)
# Nexus requirements found by testing not to be needed: {(game domain, mod id, required mod id)}
NOT_NEEDED = {
    ("newvegas", 88898, 74295),   # High Priority LOD only flags a mesh NVMIM uses; harmless without NVMIM
}

STOPWORDS = {"nvse", "xnvse", "fose", "plugin", "the", "a", "of", "for", "and", "mod", "new", "vegas", "fallout",
             "fnv", "fo3", "nv", "edition", "version", "by"}


# ------------------------------------------------------------------ Nexus ids from file names

_OLD = re.compile(r"^.+?-(\d{2,7})(?:-[\w.]*)*\.\w+$")                       # Name-12345-1-0-1600000000.7z
_NEW = re.compile(r" (\d{2,7}) \S+ \d{4}-\d\d-\d\dT\d\d-\d\dZ \w+\.\w+$")   # Name 12345 1.0 2026-11-13T01-44Z ab12.zip


def nexus_id(mod):
    """The mod's Nexus id, from FOLM's Nexus record or the downloaded file's name. None if unknown."""
    if (mod.get("nexus") or {}).get("mod_id"):
        return int(mod["nexus"]["mod_id"])
    src = os.path.basename(mod.get("source") or "")
    if not src or "[mod.pub]" in src:
        return None
    mm = _NEW.search(src) or _OLD.match(src)
    return int(mm.group(1)) if mm else None


# ------------------------------------------------------------------ source 1: the DLL's own check

def _strings(data, kind, n=4):
    if kind == "ascii":
        return [s.decode("ascii") for s in re.findall(rb"[\x20-\x7e]{%d,}" % n, data)]
    return [s.decode("utf-16-le") for s in re.findall(rb"(?:[\x20-\x7e]\x00){%d,}" % n, data)]


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


_NEED_MSG = re.compile(r"^(.{3,60}?) (?:not found|is not installed|is missing)[.!]?$", re.I)
_HARD = re.compile(r"cannot be used without|can't be used without|won't (?:run|work) without|please install|is required", re.I)
_INCOMPAT = re.compile(r"not compatible with|incompatible with", re.I)


def _clean(s):
    return re.sub(r"^[^A-Za-z0-9]+", "", s).strip()


def dll_checks(path, _cache={}):
    """What a plugin's own startup checks say: {"needs": [(dll, name)], "conflicts": [(dll, message)]}.

    A requirement counts only when the plugin pairs "X not found." with "... cannot be used without it"
    (or similar) and also names X.dll; an "X not found" that is only logged (e.g. Vegas Shaders' optional
    Vanilla Plus Skin) doesn't count. Conflicts: a "not compatible with ... Y.dll" message."""
    try:
        st = os.stat(path)
    except OSError:
        return {"needs": [], "conflicts": []}
    key = (path, st.st_size, st.st_mtime_ns)
    if key not in _cache:
        with open(path, "rb") as fh:
            data = fh.read()
        found, conflicts = set(), set()
        for strings in ([_clean(x) for x in _strings(data, "ascii")], [_clean(x) for x in _strings(data, "utf16")]):
            dlls = {_norm(x[:-4]): x for x in strings if x.lower().endswith(".dll") and not re.search(r"[\\/]", x)}
            for i, x in enumerate(strings):
                mm = _NEED_MSG.match(x)
                if mm and _norm(mm.group(1)) in dlls and i + 1 < len(strings) and _HARD.search(strings[i + 1]):
                    found.add((dlls[_norm(mm.group(1))].lower(), mm.group(1)))
                if _INCOMPAT.search(x):
                    for d in re.findall(r"\b([A-Za-z0-9_-]+\.dll)\b", x):
                        conflicts.add((d.strip().lower(), x))
        _cache[key] = {"needs": sorted(found), "conflicts": sorted(conflicts)}
    return _cache[key]


def dll_needs(path):
    return dll_checks(path)["needs"]


# ------------------------------------------------------------------ source 3: Nexus

def _cache_path(m):
    from .manager import home
    return os.path.join(home(), "nexus-requirements.json")


def _load_cache(m):
    try:
        with open(_cache_path(m)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _fetch(domain, ids, opener=urllib.request.urlopen):
    """{mod id: [{"mod_id", "name", "external", "url", "notes"}]} from Nexus's public API."""
    q = ("query($ids: [CompositeDomainWithIdInput!]!) { legacyModsByDomain(ids: $ids) { nodes { modId "
         "modRequirements { nexusRequirements { nodes { modId modName url externalRequirement notes } } } } } }")
    body = json.dumps({"query": q, "variables": {"ids": [{"gameDomain": domain, "modId": i} for i in ids]}}).encode()
    from .version import APP_NAME, VERSION as APP_VERSION
    req = urllib.request.Request(GRAPHQL, data=body, headers={
        "Content-Type": "application/json", "Application-Name": APP_NAME, "Application-Version": APP_VERSION,
        "User-Agent": f"{APP_NAME}/{APP_VERSION} (Linux)"})
    with opener(req, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8"))
    out = {i: [] for i in ids}
    for node in ((data.get("data") or {}).get("legacyModsByDomain") or {}).get("nodes") or []:
        reqs = (((node.get("modRequirements") or {}).get("nexusRequirements") or {}).get("nodes")) or []
        out[int(node["modId"])] = [{"mod_id": int(r["modId"]) if str(r.get("modId") or "").isdigit() else None,
                                    "name": r.get("modName") or "", "external": bool(r.get("externalRequirement")),
                                    "url": r.get("url") or "", "notes": (r.get("notes") or "").strip()}
                                   for r in reqs]
    return out


def nexus_requirements(m, ids, online=True, opener=urllib.request.urlopen):
    """{mod id: [requirement]} using the cache; fetches ids that are missing or older than a week."""
    domain = GAME_DOMAIN.get(m.edition, "newvegas")
    cache = _load_cache(m)
    now = time.time()
    stale = [i for i in ids if now - cache.get(f"{domain}/{i}", {}).get("fetched", 0) > CACHE_DAYS * 86400]
    if stale and online:
        try:
            for start in range(0, len(stale), 20):          # Nexus returns at most 20 mods per request
                for i, reqs in _fetch(domain, stale[start:start + 20], opener).items():
                    cache[f"{domain}/{i}"] = {"fetched": now, "requires": reqs}
            tmp = _cache_path(m) + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(cache, fh)
            os.replace(tmp, _cache_path(m))
        except Exception:                 # offline / Nexus down: use what we have
            pass
    return {i: cache.get(f"{domain}/{i}", {}).get("requires", []) for i in ids}


# ------------------------------------------------------------------ putting it together

def _tokens(s):
    return {t for t in re.findall(r"[a-z]+", s.lower()) if t not in STOPWORDS and len(t) > 1}


def _find_by_name(mods, name):
    want = _tokens(name)
    if not want:
        return None
    for x in mods:
        have = _tokens(x["name"])
        if want <= have or (have and have <= want and len(have) >= 2):
            return x
    return None


def _best_named(cands, name):
    """Of several installed files from one Nexus page, the ones whose names fit the requirement best
    (so "Vanilla Plus Terrain" means the plugin, not "Vanilla Plus Terrain Textures")."""
    if len(cands) < 2:
        return cands
    want = _tokens(name)
    extra = {id(x): len(_tokens(x["name"]) - want) for x in cands}
    best = min(extra.values())
    return [x for x in cands if extra[id(x)] == best]


def check(m, online=None, only=None):
    """Missing requirements for enabled mods (or just the mod named `only`).
    online=None: ask Nexus unless FOLM_OFFLINE is set (tests, or players who want no lookups)."""
    if online is None:
        online = not os.environ.get("FOLM_OFFLINE")
    from .health import EXTENDER
    from . import deploy as dep
    mods = m.mods()
    enabled = [x for x in mods if x.get("enabled")]
    out, seen = [], set()
    ext = []

    def has_extender():                     # looked up once per check (it may walk every mod's files)
        if not ext:
            ext.append(_has_xnvse(m))
        return ext[0]

    # 1 + 2: script extender plugins, from the deployed Plugins folder and each enabled mod's own files
    pdir = dep.exists_ci(m.data_dir, f"{EXTENDER[m.edition][0]}/Plugins")
    # plugins the game will have after the next Deploy: the enabled mods' (added below) plus any that
    # are in the game folder but not from a FOLM mod (installed by hand)
    from_mods = set()
    try:
        from_mods = {os.path.basename(r["target"]).lower() for r in json.load(open(m.manifest)).get("files", [])}
    except (OSError, ValueError):
        pass
    installed_dlls = {f.lower() for f in os.listdir(pdir) if f.lower() not in from_mods} if pdir else set()
    owner = {}
    for x in enabled:
        for root, _dirs, files in os.walk(os.path.join(m.mods_dir, x["name"])):
            for f in files:
                if f.lower().endswith(".dll") and os.path.basename(root).lower() == "plugins":
                    owner[f.lower()] = (x["name"], os.path.join(root, f))
                    installed_dlls.add(f.lower())
    for dll, (modname, path) in sorted(owner.items()):
        if only and modname != only:
            continue
        needs = {need: (label, "", "") for need, label in dll_needs(path)}
        for need, label, url in KNOWN.get(dll, []):
            needs[need] = (label, url, "")
        for bad, msg in dll_checks(path)["conflicts"]:
            if bad in installed_dlls and bad != dll and (dll, bad) not in seen:
                seen.add((dll, bad))
                out.append({"severity": "error", "mod": modname, "needs": f"{bad} turned off",
                            "how": f"{dll} says: {msg}", "url": "", "notes": ""})
        for need, (label, url, _n) in needs.items():
            if need in installed_dlls or (dll, need) in seen:
                continue
            seen.add((dll, need))
            out.append({"severity": "error", "mod": modname, "needs": label, "how": f"{dll} won't run without {need}",
                        "url": url, "notes": ""})

    # 3: Nexus requirement lists
    domain = GAME_DOMAIN.get(m.edition, "newvegas")
    ids = {x["name"]: nexus_id(x) for x in enabled if not only or x["name"] == only}
    by_id = {}
    for x in mods:
        i = nexus_id(x)
        if i:
            by_id.setdefault(i, []).append(x)
    reqs = nexus_requirements(m, sorted({i for i in ids.values() if i}), online=online)
    from .tools import OUTPUT_MOD
    has_generated_lod = any(x["name"] == OUTPUT_MOD["xlodgen"] for x in enabled)
    done_ids = set()
    for modname, i in ids.items():
        if not i or i in done_ids:          # several files from one Nexus page share its list: report it once
            continue
        done_ids.add(i)
        for r in reqs.get(i, []):
            rid = r["mod_id"]
            test = SPECIAL.get(domain, {}).get(rid) if rid else None
            if test and (has_extender() if test is _has_xnvse else test(m)):
                continue
            if WINDOWS_RUNTIME.search(r["name"]):
                continue                    # Visual C++ / DirectX runtimes: Proton provides them
            if _is_extender(r["name"]) and has_extender():
                continue
            if GUIDE.search(r["name"]) or (domain, i, rid) in NOT_NEEDED:
                continue
            if AUTHORING_TOOL.search(r["name"]):
                continue                    # GECK / xEdit: for making mods, the game never loads them
            if LOD_TOOL.search(r["name"]) and has_generated_lod:
                continue                    # the LOD generator already ran: its output is the Generated LOD mod
            have = _best_named(by_id.get(rid, []), r["name"]) if rid else []
            if not have:
                hit = _find_by_name(mods, r["name"])
                have = [hit] if hit else []
            if any(x.get("enabled") for x in have) or (modname, r["name"]) in seen:
                continue
            seen.add((modname, r["name"]))
            url = r["url"] or (f"https://www.nexusmods.com/{domain}/mods/{rid}" if rid else "")
            how = "installed but turned off" if have else "listed as required on its Nexus page"
            sev = "info" if CONDITIONAL.search(r["notes"]) else "warn"
            # a requirement the DLL check already reported (same mod, same name) isn't repeated
            if any(o["mod"] == modname and _norm(o["needs"]) == _norm(r["name"]) for o in out):
                continue
            out.append({"severity": sev, "mod": modname, "needs": r["name"], "how": how, "url": url,
                        "notes": r["notes"]})
    return out


def describe(item):
    if item["severity"] == "info":
        s = f"{item['mod']} may need {item['needs']}: its Nexus page lists it for some setups only."
        if item["notes"]:
            s += f" Author's note: \"{item['notes'][:200]}\""
        return s + (f" ({item['url']})" if item["url"] else "")
    s = f"{item['mod']} needs {item['needs']} ({item['how']})."
    if item["notes"]:
        s += f" Note from the author: {item['notes'][:200]}"
    if item["url"]:
        s += f" Get it: {item['url']}"
    return s
