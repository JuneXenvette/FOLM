"""updates - is there a newer FOLM, or a newer file for an installed Nexus mod?

Runs only when the player asks (Tools tab > Check for updates, or `folm.py updates`); nothing is checked
in the background. What's sent: FOLM's version in the request headers, and the Nexus ids of installed
mods (public data, no account or key), the same as the requirement lookup.

How a mod update is found: a Nexus download's name carries the moment its file was uploaded
("Name-12345-1-0-1700000000.7z", or "... 2026-11-13T01-44Z ..." for newer downloads). Nexus's public
file list for that mod has each file's upload time, so FOLM can tell exactly which file you installed,
and whether the page has a newer file with the same name (an update of it).
"""
import calendar
import json
import os
import re
import urllib.request

from . import requires
from .version import APP_NAME, VERSION

RELEASES = "https://api.github.com/repos/JuneXenvette/FOLM/releases/latest"
RELEASE_PAGE = "https://github.com/JuneXenvette/FOLM/releases/latest"
GAME_ID = {"courier": 130, "wanderer": 120}           # Nexus game ids: New Vegas, Fallout 3
OLD_CATEGORIES = {"OLD_VERSION", "ARCHIVED", "DELETED", "REMOVED"}


def _get(url, data=None, opener=urllib.request.urlopen):
    headers = {"User-Agent": f"{APP_NAME}/{VERSION} (Linux)", "Application-Name": APP_NAME,
               "Application-Version": VERSION}
    if data is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(data).encode()
    with opener(urllib.request.Request(url, data=data, headers=headers), timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def _version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:4])


# ------------------------------------------------------------------ FOLM itself

def folm_update(opener=urllib.request.urlopen):
    """(newer version, release page) if GitHub has a newer FOLM release, else None."""
    rel = _get(RELEASES, opener=opener)
    tag = rel.get("tag_name") or ""
    if _version_tuple(tag) > _version_tuple(VERSION):
        return tag.lstrip("v"), rel.get("html_url") or RELEASE_PAGE
    return None


# ------------------------------------------------------------------ mods

_OLD_TIME = re.compile(r"-(\d{10})(?:\(\d+\))?\.\w+$")                       # ...-1-0-1700000000.7z
_NEW_TIME = re.compile(r" (\d{4})-(\d\d)-(\d\d)T(\d\d)-(\d\d)Z ")           # ... 2026-11-13T01-44Z ab12.zip


def upload_time(source):
    """When the downloaded file was uploaded to Nexus (unix time), and how exact that is in seconds;
    (None, 0) if the name doesn't say."""
    name = os.path.basename(source or "")
    m = _OLD_TIME.search(name)
    if m:
        return int(m.group(1)), 2
    m = _NEW_TIME.search(name)
    if m:
        y, mo, d, h, mi = (int(x) for x in m.groups())
        return calendar.timegm((y, mo, d, h, mi, 0)), 60
    return None, 0


def _norm(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _file_lists(game_id, mod_ids, opener):
    """{mod id: [{"name", "version", "category", "date"}]} from Nexus, 20 mods per request."""
    out = {}
    ids = sorted(mod_ids)
    for start in range(0, len(ids), 20):
        chunk = ids[start:start + 20]
        q = "query { " + " ".join(f"m{i}: modFiles(modId: {i}, gameId: {int(game_id)}) "
                                  "{ name version category date }" for i in chunk) + " }"
        data = (_get(requires.GRAPHQL, {"query": q}, opener=opener).get("data") or {})
        for i in chunk:
            out[i] = data.get(f"m{i}") or []
    return out


def mod_updates(m, opener=urllib.request.urlopen):
    """Installed Nexus mods with a newer file on their page:
    [{"mod", "have", "new", "url", "kind"}], kind "update" (a newer file with the same name) or
    "old" (Nexus moved your file to old versions and there's no same-named newer one)."""
    domain = requires.GAME_DOMAIN.get(m.edition, "newvegas")
    mods = []
    for x in m.mods():
        i = requires.nexus_id(x)
        t, slack = upload_time(x.get("source"))
        if i and t:
            mods.append((x, i, t, slack))
    if not mods:
        return []
    files = _file_lists(GAME_ID.get(m.edition, 130), {i for _, i, _, _ in mods}, opener)
    out = []
    for x, i, t, slack in mods:
        mine = [f for f in files.get(i, []) if abs(int(f.get("date") or 0) - t) <= slack]
        if not mine:
            continue                       # can't tell which file it was (renamed download, removed file)
        f = mine[0]
        newer = [g for g in files[i] if _norm(g.get("name")) == _norm(f.get("name"))
                 and int(g.get("date") or 0) > t + slack and g.get("category") not in OLD_CATEGORIES]
        url = f"https://www.nexusmods.com/{domain}/mods/{i}?tab=files"
        have = f"{f.get('name')} {f.get('version') or ''}".strip()
        if newer:
            g = max(newer, key=lambda g: int(g.get("date") or 0))
            out.append({"mod": x["name"], "have": have, "new": f"{g.get('name')} {g.get('version') or ''}".strip(),
                        "url": url, "kind": "update"})
        elif f.get("category") in OLD_CATEGORIES:
            out.append({"mod": x["name"], "have": have, "new": "", "url": url, "kind": "old"})
    return out


# Mods that don't come from Nexus, and the page that has their downloads (by the mod's name in FOLM)
KNOWN_PAGES = [
    (re.compile(r"^xnvse\b", re.I), "https://github.com/xNVSE/NVSE/releases", "xNVSE releases (GitHub)"),
    (re.compile(r"^(?:tale of two wastelands|yupttw)\b", re.I), "https://taleoftwowastelands.com", "TTW's site"),
    (re.compile(r"^second wind nvhr\b", re.I), "https://github.com/JuneXenvette/FOLM", "FOLM's page (Second Wind)"),
]


def _search_url(domain, words):
    from urllib.parse import quote
    return f"https://www.nexusmods.com/games/{domain}/search?keyword={quote(words)}"


def _page_for_unknown(m, x, domain):
    """(url, label) for a mod FOLM can't check: its known home, LOOT's link for one of its plugins, or a
    Nexus search for its name."""
    clean = re.sub(r"\s+v?\d+(?:\.\d+)*[a-z]?\b.*$", "", x["name"]).strip() or x["name"]
    for pat, url, label in KNOWN_PAGES:
        if pat.search(x["name"]):
            return url, label
    plugins = getattr(m, "mod_plugins", lambda n: [])(x["name"])
    if plugins and hasattr(m, "plugin_sources"):
        try:
            for p, src in m.plugin_sources(plugins).items():
                if src.get("url") and src.get("link") not in ("Search Nexus", "comes with the game"):
                    return src["url"], "LOOT: " + src["link"]
        except Exception:                      # no LOOT masterlist (offline, never downloaded)
            pass
    return _search_url(domain, clean), "Search Nexus"


def mod_status(m, opener=urllib.request.urlopen):
    """Every mod in the active profile, sorted into what Nexus can tell:
    [{"mod", "state", "have", "new", "url", "link", "why"}], state one of
      "update"  - a newer file with the same name is on its Nexus page,
      "old"     - Nexus moved your file to old versions (see the page for what replaced it),
      "current" - your file is the newest of its name,
      "unknown" - FOLM can't tell ("why" says why); url is still where to look, by hand.
    Links: the mod's Nexus files page; for mods FOLM can't place on Nexus, their known home (xNVSE on
    GitHub, TTW's site), LOOT's link for one of their plugins, or a Nexus search for the name."""
    domain = requires.GAME_DOMAIN.get(m.edition, "newvegas")
    from .tools import OUTPUT_MOD
    ours = set(OUTPUT_MOD.values())
    rows, todo = [], []
    for x in m.mods():
        i = requires.nexus_id(x)
        t, slack = upload_time(x.get("source"))
        row = {"mod": x["name"], "state": "unknown", "have": "", "new": "", "url": "", "link": "", "why": ""}
        if x["name"] in ours or x["name"].startswith("Overwrite") or x["name"].endswith("(FOLM)") or "ours" in x.get("tags", []):
            row.update(why="made on this PC by FOLM or a tool: nothing to download")
        elif i:
            row.update(url=f"https://www.nexusmods.com/{domain}/mods/{i}?tab=files", link="Files page")
            if t:
                todo.append((row, i, t, slack))
            else:
                row["why"] = "the download's name has no upload time (renamed?), so FOLM can't tell which file you have"
        else:
            url, label = _page_for_unknown(m, x, domain)
            row.update(url=url, link=label, why="not a Nexus download FOLM can recognise")
        rows.append(row)
    if todo:
        files = _file_lists(GAME_ID.get(m.edition, 130), {i for _, i, _, _ in todo}, opener)
        for row, i, t, slack in todo:
            mine = [f for f in files.get(i, []) if abs(int(f.get("date") or 0) - t) <= slack]
            if not mine:
                row["why"] = "your file isn't on its Nexus page any more (removed, or the download was renamed)"
                continue
            f = mine[0]
            row["have"] = f"{f.get('name')} {f.get('version') or ''}".strip()
            newer = [g for g in files[i] if _norm(g.get("name")) == _norm(f.get("name"))
                     and int(g.get("date") or 0) > t + slack and g.get("category") not in OLD_CATEGORIES]
            if newer:
                g = max(newer, key=lambda g: int(g.get("date") or 0))
                row.update(state="update", new=f"{g.get('name')} {g.get('version') or ''}".strip())
            elif f.get("category") in OLD_CATEGORIES:
                row["state"] = "old"
            else:
                row["state"] = "current"
    return rows


def check_all(m, opener=urllib.request.urlopen):
    """(FOLM update or None, FOLM error text or None, mod_status rows or None, Nexus error text or None)."""
    try:
        folm, ferr = folm_update(opener), None
    except Exception as e:
        folm, ferr = None, str(e)
    try:
        rows, merr = mod_status(m, opener), None
    except Exception as e:
        rows, merr = None, str(e)
    return folm, ferr, rows, merr


def describe(u):
    if u["kind"] == "update":
        return f"{u['mod']}: newer file on Nexus ({u['new']}; you have {u['have']}). {u['url']}"
    return f"{u['mod']}: Nexus moved your file ({u['have']}) to old versions; see the page for its replacement. {u['url']}"


def check(m, log=print, opener=urllib.request.urlopen):
    """Check FOLM and the active profile's Nexus mods. Returns (folm update or None, [mod updates])."""
    try:
        folm = folm_update(opener)
    except Exception as e:
        folm = None
        log(f"  ! Couldn't check for a newer FOLM ({e}).")
    log(f"FOLM {VERSION}: " + (f"version {folm[0]} is out: {folm[1]}" if folm else "up to date."))
    try:
        mods = mod_updates(m, opener)
    except Exception as e:
        log(f"  ! Couldn't reach Nexus to check mods ({e}).")
        return folm, []
    for u in mods:
        log("  " + describe(u))
    if not mods:
        log("Mods: no newer files found for your Nexus mods.")
    return folm, mods
