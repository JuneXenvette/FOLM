"""Mod lists: a file that says which mods to install, from which downloads, in what order.

A list is a small YAML file (.folmlist). Each entry is one downloaded file:

    folm_list: 1
    name: TTW LOD
    edition: courier
    about: What this list is for.
    mods:
      - file: High Priority Core - without NVMIM   # the file's name on Nexus (start of the download's name)
        nexus: 88898                               # the Nexus page (for the link, and to tell files apart)
        name: High Priority Core                   # what FOLM calls the mod (default: the file name)
        enabled: true                              # turned on after installing (default true)
        plugins_off: [HighPriorityLOD.esp]         # plugins it brings that should stay off
        remove: [meshes/effects]                   # paths to leave out of the installed copy
        note: Only needed while generating LOD.
        match: "*Overpass*"                        # optional: when one page has several files with the same name


Point FOLM at a folder (usually ~/Downloads): it finds each entry's download, says which are still
missing (with the Nexus link), and installs the ones it has, in the list's order. FOLM never contacts
Nexus for this: the player downloads the files in their own browser as usual.

save() writes the active profile out as a list, so a setup can be rebuilt or shared (the list holds
names, links and settings only, never mod files).
"""

import fnmatch
import os
import re
import shutil

from . import detect, fomod

try:
    import yaml
except ImportError:                    # PyYAML comes with the AppImage and requirements.txt
    yaml = None

VERSION = 1
EXT = ".folmlist"
DOMAIN = {"courier": "newvegas", "wanderer": "fallout3"}

# Nexus download names: old "Name-12345-1-0-1600000000.7z", new "Name 12345 1.0 2026-11-13T01-44Z ab12.7z".
# Browsers add " (1)" / "(1)" to a second copy.
_DUP = r"(?:\s?\(\d+\))?"
_NEW = re.compile(r"^(.+?) (\d{2,7}) \S+ \d{4}-\d\d-\d\dT\d\d-\d\dZ \w+" + _DUP + r"\.\w+$")
_OLD = re.compile(r"^(.+?)-(\d{2,7})(?:-[\w.]*)*" + _DUP + r"\.\w+$")


class ListError(Exception):
    pass


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def parse_download(path):
    """'Much Needed LOD - NMC Patch-64805-1-2.7z' -> ('Much Needed LOD - NMC Patch', 64805).
    Files that don't follow Nexus's naming -> (name without extension, None)."""
    base = os.path.basename(path)
    for rx in (_NEW, _OLD):
        mm = rx.match(base)
        if mm:
            return mm.group(1).strip(), int(mm.group(2))
    return re.sub(r"\.\w+$", "", base).strip(), None


def page(edition, nexus_id):
    return f"https://www.nexusmods.com/{DOMAIN.get(edition, 'newvegas')}/mods/{nexus_id}?tab=files"


# ------------------------------------------------------------------ reading and writing lists

def _check_entry(i, e):
    where = f"entry {i}"
    if not isinstance(e, dict):
        raise ListError(f"{where}: each mod needs to be a set of 'key: value' lines")
    if not str(e.get("file") or "").strip():
        raise ListError(f"{where}: needs a 'file:' (the file's name on Nexus)")
    where = f"entry {i} ({e['file']})"
    unknown = set(e) - {"file", "nexus", "name", "enabled", "plugins_off", "remove", "note", "tags", "match"}
    if unknown:
        raise ListError(f"{where}: FOLM doesn't know {', '.join(sorted(unknown))}")
    if e.get("nexus") is not None and not str(e["nexus"]).isdigit():
        raise ListError(f"{where}: 'nexus:' is the number in the mod page's address")
    for key in ("plugins_off", "remove", "tags"):
        if not isinstance(e.get(key, []), list):
            raise ListError(f"{where}: '{key}:' needs to be a list, like [A.esp, B.esp]")
    for p in e.get("remove", []):
        parts = str(p).replace("\\", "/").split("/")
        if ".." in parts or str(p).startswith(("/", "~")):
            raise ListError(f"{where}: 'remove:' paths are inside the mod (like meshes/effects)")
    return {"file": str(e["file"]).strip(),
            "nexus": int(e["nexus"]) if e.get("nexus") is not None else None,
            "name": str(e.get("name") or e["file"]).strip(),
            "enabled": bool(e.get("enabled", True)),
            "plugins_off": [str(p) for p in e.get("plugins_off", [])],
            "remove": [str(p).replace("\\", "/").strip("/") for p in e.get("remove", [])],
            "note": str(e.get("note") or ""),
            "tags": [str(t) for t in e.get("tags", [])],
            "match": str(e["match"]) if e.get("match") else None}


def parse(text):
    if yaml is None:
        raise ListError("PyYAML isn't installed (pip install pyyaml)")
    try:
        d = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ListError(f"not a readable list: {e}")
    if not isinstance(d, dict) or "mods" not in d:
        raise ListError("not a FOLM mod list (no 'mods:' section)")
    if int(d.get("folm_list", VERSION)) > VERSION:
        raise ListError("this list was made by a newer FOLM; update FOLM to use it")
    if not isinstance(d["mods"], list) or not d["mods"]:
        raise ListError("the list has no mods")
    mods = [_check_entry(i, e) for i, e in enumerate(d["mods"], 1)]
    names = [m["name"].lower() for m in mods]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ListError(f"two entries would both be called {dup[0]!r}; give one a different 'name:'")
    return {"name": str(d.get("name") or "Mod list"), "edition": d.get("edition"),
            "about": str(d.get("about") or ""), "mods": mods}


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return parse(fh.read())
    except OSError as e:
        raise ListError(f"can't read {path}: {e.strerror}")


def dump(lst):
    """The list as YAML text, keeping only what differs from the defaults."""
    out = []
    for e in lst["mods"]:
        d = {"file": e["file"]}
        if e.get("nexus"):
            d["nexus"] = e["nexus"]
        if e.get("name") and e["name"] != e["file"]:
            d["name"] = e["name"]
        if not e.get("enabled", True):
            d["enabled"] = False
        for key in ("plugins_off", "remove", "tags"):
            if e.get(key):
                d[key] = list(e[key])
        if e.get("note"):
            d["note"] = e["note"]
        if e.get("match"):
            d["match"] = e["match"]
        out.append(d)
    head = {"folm_list": VERSION, "name": lst.get("name") or "Mod list"}
    if lst.get("edition"):
        head["edition"] = lst["edition"]
    if lst.get("about"):
        head["about"] = lst["about"]
    head["mods"] = out
    return ("# FOLM mod list: open it in FOLM (Settings > Install a mod list) and point it at your downloads.\n"
            + yaml.safe_dump(head, sort_keys=False, allow_unicode=True, width=100))


# ------------------------------------------------------------------ matching downloads

def find(lst, folder):
    """For each entry, the newest matching download in `folder` (and its subfolders), or None."""
    files = detect.scan([folder]) if os.path.isdir(os.path.expanduser(folder)) else []
    parsed = [(p, *parse_download(p)) for p in files]
    found, claimed = [None] * len(lst["mods"]), set()
    # entries with a 'match:' pattern pick first, so a page's other file with the same name can't take theirs
    for i in sorted(range(len(lst["mods"])), key=lambda i: lst["mods"][i].get("match") is None):
        e = lst["mods"][i]
        want = _norm(e["file"])
        hits = [p for p, title, nid in parsed
                if p not in claimed and _norm(title) == want and (e["nexus"] is None or nid in (None, e["nexus"]))
                and (not e.get("match") or fnmatch.fnmatch(os.path.basename(p).lower(), e["match"].lower()))]
        # a file with the right Nexus id beats one without; then the newest download
        hits.sort(key=lambda p: (parse_download(p)[1] == e["nexus"], os.path.getmtime(p)), reverse=True)
        if hits:
            found[i] = hits[0]
            claimed.add(hits[0])
    return found


def status(m, lst, folder):
    """[{entry, file, state, installed_as, link}] where state is 'installed', 'ready' or 'missing'."""
    have = {x["name"].lower(): x for x in m.mods()}
    rows = []
    for e, path in zip(lst["mods"], find(lst, folder)):
        installed_as = e["name"] if e["name"].lower() in have else None
        if installed_as is None and path:
            same = [mod for kind, prof, mod in m.find_duplicates(path) if kind == "same" and prof == m.active]
            installed_as = same[0]["name"] if same else None
        state = "installed" if installed_as else "ready" if path else "missing"
        rows.append({"entry": e, "file": path, "state": state, "installed_as": installed_as,
                     "link": page(m.edition, e["nexus"]) if e["nexus"] else None})
    return rows


# ------------------------------------------------------------------ installing

def install(m, lst, folder, log=print, chooser=None):
    """Install every entry whose download is in `folder` and isn't installed yet, in the list's order.
    Returns (installed, skipped, missing, failed) lists of entry names."""
    if lst.get("edition") and lst["edition"] != m.edition:
        raise ListError(f"this list is for the {lst['edition']} edition, not {m.edition}")
    rows = status(m, lst, folder)
    installed, skipped, missing, failed = [], [], [], []
    previous = None                                  # keep the list's mods together, in its order
    for r in rows:
        e = r["entry"]
        if r["state"] == "installed":
            skipped.append(e["name"])
            previous = r["installed_as"]
            continue
        if r["state"] == "missing":
            missing.append(e["name"])
            continue
        log(f"Installing {e['name']}  ({os.path.basename(r['file'])})")
        try:
            name, _ = m.install(r["file"], name=e["name"], chooser=_list_chooser(chooser, e["name"]), log=log)
        except Exception as ex:                      # one bad file shouldn't stop the rest
            log(f"  ✖ {e['name']}: {ex}")
            failed.append(e["name"])
            continue
        _apply(m, name, e, log)
        if previous:
            m.move_after(name, previous)
        previous = name
        installed.append(name)
    return installed, skipped, missing, failed


def _list_chooser(chooser, entry_name):
    """FOLM asks before installing a file from a page it already has a mod from ("another version?").
    One Nexus page often has several files with the same name (a main file and its extras), and the
    list says each one is its own mod, so the answer is "keep both". FOMOD questions go to `chooser`."""
    def ask(step, group):
        if group.get("name") == "Another version of this mod is installed":
            names = [o["name"] for o in group["plugins"]]
            return [names.index("Keep both")]
        return chooser(step, group) if chooser else fomod.default_choice(group)
    return ask


def _apply(m, name, e, log):
    """The entry's settings on the freshly installed mod."""
    root = os.path.realpath(os.path.join(m.mods_dir, name))
    for rel in e["remove"]:
        hit = _find_ci(root, rel)
        if hit and os.path.realpath(hit).startswith(root + os.sep):
            (shutil.rmtree if os.path.isdir(hit) and not os.path.islink(hit) else os.remove)(hit)
            log(f"  left out {rel}")
        else:
            log(f"  (nothing called {rel} to leave out)")
    if e["plugins_off"]:
        theirs = {p.lower(): p for p in m.mod_plugins(name)}
        for p in e["plugins_off"]:
            m.set_plugin_active(theirs.get(p.lower(), p), False)
            log(f"  plugin {theirs.get(p.lower(), p)} stays off")
    if e["note"]:
        m.set_note(name, e["note"])
    if e["tags"]:
        m.add_tags(name, e["tags"])
    if not e["enabled"]:
        m.set_enabled(name, False)
        log("  left turned off")


def _find_ci(root, rel):
    """The path `rel` under `root`, matching each part without caring about upper/lower case."""
    cur = root
    for part in [p for p in rel.split("/") if p]:
        try:
            names = os.listdir(cur)
        except OSError:
            return None
        match = next((n for n in names if n.lower() == part.lower()), None)
        if match is None:
            return None
        cur = os.path.join(cur, match)
    return cur


# ------------------------------------------------------------------ saving a profile as a list

def from_profile(m, name=None, about=""):
    """The active profile as a list. Mods that didn't come from a downloaded file (TTW's output,
    tool output, folders) are left out and returned separately."""
    disabled = {d.lower() for d in m.cur["disabled_plugins"]}
    entries, left_out = [], []
    for mod in m.mods():
        src = mod.get("source") or ""
        if not src or os.path.isdir(src) or not src.lower().endswith(detect.MOD_FILE_EXTS):
            left_out.append(mod["name"])
            continue
        title, nid = parse_download(src)
        nid = nid or ((mod.get("nexus") or {}).get("mod_id"))
        off = [p for p in m.mod_plugins(mod["name"]) if p.lower() in disabled]
        entries.append({"file": title, "nexus": int(nid) if nid else None, "name": mod["name"],
                        "enabled": bool(mod.get("enabled", True)), "plugins_off": off, "remove": [],
                        "note": mod.get("notes") or "", "tags": list(mod.get("tags") or [])})
    if not entries:
        raise ListError("no mod in this profile was installed from a downloaded file")
    return {"name": name or f"{m.active}", "edition": m.edition, "about": about, "mods": entries}, left_out


def save(m, path, name=None, about=""):
    lst, left_out = from_profile(m, name, about)
    if not path.endswith(EXT):
        path += EXT
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(dump(lst))
    os.replace(tmp, path)
    return path, lst, left_out
