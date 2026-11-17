"""health - check that installed mods are really working, not just installed.

Before launch (from files):
  * every deployed file is still in place and still the mod's file (a game update,
    Steam's "verify files" or another tool can quietly replace it)
  * no empty or damaged plugins, archives or DLLs
  * every plugin's masters are present
  * script extender plugins (DLLs) are where the extender looks for them
  * no Windows graphics DLL (ENB/ReShade d3d9.dll...) is replacing DXVK, Proton's Direct3D
  * no folders that differ only by letter case (Linux would keep both; the game sees one)

After launch (from the script extender's own log):
  * each script extender plugin was found and "loaded correctly", or why it didn't

check(manager) returns a list of findings: {"status": ok|warn|error|info, "area", "text", "fix"}.
"""

import os
import re
from collections import defaultdict

from . import deploy as dep
from . import plugins as plg

AREAS = ("Deployed files", "Plugins", "Script extender plugins", "Last launch", "Graphics (Proton)", "Folders")
EXTENDER = {"courier": ("NVSE", "nvse.log", "xNVSE"), "wanderer": ("FOSE", "fose.log", "FOSE")}
GRAPHICS_DLLS = ("d3d9.dll", "d3d11.dll", "dxgi.dll", "d3d8.dll", "opengl32.dll")
NEVER_EMPTY = (".esm", ".esp", ".bsa", ".dll", ".nif", ".dds", ".exe")


def _f(status, area, text, fix=""):
    return {"status": status, "area": area, "text": text, "fix": fix}


def _deployed_files(m, manifest):
    out, changed, gone, empty = [], [], [], []
    for rec in manifest.get("files", []):
        t, s = rec["target"], rec["source"]
        rel = os.path.relpath(t, m.data["game_dir"])
        try:
            ts = os.stat(t)
        except FileNotFoundError:
            gone.append((rel, rec["mod"]))
            continue
        if rec.get("how") == "link":
            try:
                same = os.stat(s).st_ino == ts.st_ino
            except FileNotFoundError:
                same = False
            if not same:
                changed.append((rel, rec["mod"]))
        if ts.st_size == 0 and t.lower().endswith(NEVER_EMPTY):
            empty.append((rel, rec["mod"]))
    total = len(manifest.get("files", []))
    if gone:
        out.append(_f("error", "Deployed files", f"{len(gone)} deployed file(s) are missing from the game folder, e.g. "
                      + ", ".join(f"{r} ({mod})" for r, mod in gone[:3]),
                      "Deploy again. If a game update removed them, Deploy puts them back."))
    if changed:
        out.append(_f("warn", "Deployed files", f"{len(changed)} file(s) were replaced after deploy (by a game update, "
                      "Steam 'verify files' or another tool), e.g. "
                      + ", ".join(f"{r} ({mod})" for r, mod in changed[:3]),
                      "Use 'Catch new files' first if you changed them on purpose, then Deploy again."))
    if empty:
        out.append(_f("error", "Deployed files", "Empty files that should have content (damaged download?): "
                      + ", ".join(f"{r} ({mod})" for r, mod in empty[:5]),
                      "Re-download and reinstall those mods."))
    if not (gone or changed or empty):
        out.append(_f("ok", "Deployed files", f"All {total} deployed files are in place and unchanged."))
    return out


def _plugins(m):
    out, bad = [], []
    names = sorted(f for f in os.listdir(m.data_dir) if f.lower().endswith((".esm", ".esp")))
    for n in names:
        try:
            plg.read_header(os.path.join(m.data_dir, n))
        except (plg.PluginError, OSError, ValueError) as e:
            bad.append(f"{n} ({e})")
    if bad:
        out.append(_f("error", "Plugins", "Plugins that can't be read (damaged, or not a Fallout plugin): " + "; ".join(bad[:5]),
                      "Reinstall the mod they came from."))
    rows, problems = m.plugin_order()
    missing = defaultdict(list)
    for p in problems:
        mm = re.match(r"(.+?) needs missing master (.+)$", p)
        if mm:
            missing[mm.group(1)].append(mm.group(2))
    for pl, ms in missing.items():
        out.append(_f("error", "Plugins", f"{pl} needs {', '.join(ms)}, which isn't installed or is turned off.",
                      "Install or enable the missing master, or turn the plugin off."))
    bsas = [f for f in os.listdir(m.data_dir) if f.lower().endswith(".bsa")]
    from . import bsa
    broken = []
    for b in bsas:
        try:
            bsa.list_files(os.path.join(m.data_dir, b))
        except Exception as e:                       # any failure to read the archive header
            broken.append(f"{b} ({e})")
    if broken:
        out.append(_f("error", "Plugins", "Archives (.bsa) that can't be read: " + "; ".join(broken[:5]),
                      "Reinstall the mod they came from (or verify the game files in Steam for the game's own)."))
    if not bad and not missing and not broken:
        active = sum(1 for r in rows if r[1])
        out.append(_f("ok", "Plugins", f"{len(names)} plugins and {len(bsas)} archives read fine; every active "
                      f"plugin ({active}) has its masters."))
    return out


def _is_pe(path):
    try:
        with open(path, "rb") as fh:
            return fh.read(2) == b"MZ"
    except OSError:
        return False


def _extender_plugins(m):
    """(findings, {dll lowercase: name}) for DLLs where the extender looks, plus misplaced DLLs."""
    folder_name, _, ext_name = EXTENDER[m.edition]
    out, dlls = [], {}
    pdir = dep.exists_ci(m.data_dir, f"{folder_name}/Plugins")
    if pdir:
        for f in sorted(os.listdir(pdir)):
            p = os.path.join(pdir, f)
            if f.lower().endswith(".dll") and os.path.isfile(p):
                dlls[f.lower()] = f
                if not _is_pe(p):
                    out.append(_f("error", "Script extender plugins", f"{f} isn't a valid Windows DLL (damaged download?).",
                                  "Reinstall the mod it came from."))
    # DLLs that won't load because they're in the wrong place
    misplaced = []
    ext_root = dep.exists_ci(m.data_dir, folder_name)
    for base in [m.data_dir] + ([pdir] if pdir else []):
        for f in os.listdir(base):
            p = os.path.join(base, f)
            if os.path.isdir(p) and base == pdir:
                misplaced += [os.path.relpath(os.path.join(dp, x), m.data["game_dir"])
                              for dp, _, fn in os.walk(p) for x in fn if x.lower().endswith(".dll")]
            elif base == m.data_dir and f.lower().endswith(".dll"):
                misplaced.append(os.path.relpath(p, m.data["game_dir"]))
    if ext_root:
        misplaced += [os.path.relpath(os.path.join(ext_root, f), m.data["game_dir"])
                      for f in os.listdir(ext_root) if f.lower().endswith(".dll")]
    if misplaced:
        out.append(_f("warn", "Script extender plugins", f"DLLs in a folder {ext_name} doesn't load from: "
                      + ", ".join(misplaced[:5]),
                      f"They belong in Data/{folder_name}/Plugins/. Check how the mod was packaged, or reinstall it."))
    if dlls and not any(x["status"] == "error" for x in out):
        out.append(_f("ok", "Script extender plugins", f"{len(dlls)} plugin DLL(s) in Data/{folder_name}/Plugins."))
    return out, dlls


def _last_launch(m, dlls):
    _, log_name, ext_name = EXTENDER[m.edition]
    log = dep.exists_ci(m.data["game_dir"], log_name)
    if not dlls:
        return []
    if not log:
        return [_f("info", "Last launch", f"No {ext_name} log yet, so FOLM can't tell whether the plugins load.",
                   "Play once (to the main menu is enough), then run the health check again.")]
    log_time = os.path.getmtime(log)
    deployed_time = os.path.getmtime(m.manifest) if os.path.exists(m.manifest) else 0
    text = open(log, encoding="utf-8", errors="replace").read()
    checked, loaded, failed = set(), {}, {}
    for line in text.splitlines():
        mm = re.match(r"\s*checking plugin (.+\.dll)\s*$", line, re.I)
        if mm:
            checked.add(re.split(r"[\\/]", mm.group(1))[-1].lower())
            continue
        mm = re.match(r"\s*plugin (.+?\.dll)\s*(\((.*?)\))?\s*(.*)$", line, re.I)
        if mm:
            dll = re.split(r"[\\/]", mm.group(1))[-1].lower()
            rest = mm.group(4).strip()
            if "loaded correctly" in rest:
                loaded[dll] = (mm.group(3) or "").split(";")[0]
            elif rest:
                failed[dll] = rest
            continue
        mm = re.search(r"([\w .\-]+\.dll).*?(couldn't load|could not load|incompatible|failed|error)(.*)", line, re.I)
        if mm and mm.group(1).strip().lower() in dlls:
            failed.setdefault(mm.group(1).strip().lower(), (mm.group(2) + mm.group(3)).strip())
    out = []
    stale = log_time < deployed_time
    when = "the last launch" + (" (before your latest deploy)" if stale else "")
    for low, name in sorted(dlls.items()):
        if low in loaded:
            continue
        if low in failed:
            out.append(_f("error", "Last launch", f"{name} didn't load in {when}: {failed[low]}",
                          "Usually a newer/older version is needed, or a plugin it depends on is missing. "
                          "Check the mod's page for requirements."))
        elif low in checked:
            out.append(_f("error", "Last launch", f"{ext_name} found {name} but didn't report it loaded in {when}.",
                          "Check the mod's requirements."))
        elif not stale:
            out.append(_f("warn", "Last launch", f"{name} wasn't seen by {ext_name} in {when}.",
                          f"Make sure the game starts through {ext_name} (FOLM's Play does)."))
    ok = [f"{loaded[d] or dlls[d]}" for d in sorted(loaded) if d in dlls]
    if ok:
        out.insert(0, _f("ok", "Last launch", f"Loaded correctly in {when}: " + ", ".join(ok)))
    if stale:
        new = [n for low, n in dlls.items() if low not in loaded and low not in failed and low not in checked]
        if new:
            out.append(_f("info", "Last launch", "Not launched since you deployed: " + ", ".join(sorted(new)),
                          "Play once, then run the health check again to confirm they load."))
    return out


def _graphics(m, manifest):
    ours = {os.path.basename(r["target"]).lower(): r["mod"] for r in manifest.get("files", [])
            if os.path.dirname(r["target"]) == m.data["game_dir"]}
    out = []
    for f in os.listdir(m.data["game_dir"]):
        if f.lower() in GRAPHICS_DLLS:
            src = f"from {ours[f.lower()]}" if f.lower() in ours else "not from a FOLM mod"
            out.append(_f("warn", "Graphics (Proton)", f"{f} in the game folder ({src}) replaces DXVK, the Direct3D "
                          "layer Proton uses. ENB/ReShade builds made for Windows often crash or run slowly this way.",
                          "Turn off the mod it came from, or use a Linux-friendly alternative (e.g. vkBasalt)."))
    if not out:
        out.append(_f("ok", "Graphics (Proton)", "No Windows graphics DLLs in the game folder; DXVK handles Direct3D."))
    return out


def _case_twins(m, depth=3):
    twins = []

    def walk(d, level):
        try:
            entries = [e for e in os.scandir(d) if e.is_dir()]
        except OSError:
            return
        seen = defaultdict(list)
        for e in entries:
            seen[e.name.lower()].append(e.name)
        twins.extend(os.path.relpath(os.path.join(d, " / ".join(v)), m.data_dir) for v in seen.values() if len(v) > 1)
        if level < depth:
            for e in entries:
                walk(e.path, level + 1)
    walk(m.data_dir, 1)
    if twins:
        return [_f("warn", "Folders", "Folders that differ only by letter case (the game only sees one): "
                   + "; ".join(twins[:5]), "Undeploy, then Deploy again; FOLM merges them.")]
    return [_f("ok", "Folders", "No case-duplicate folders.")]


def check(m):
    m.need()
    import json
    manifest = json.load(open(m.manifest)) if m.deployed else {"files": []}
    out = []
    if not m.deployed:
        out.append(_f("warn", "Deployed files", "Mods aren't deployed, so only the game's own files were checked.",
                      "Deploy, then run the health check again."))
    else:
        out += _deployed_files(m, manifest)
    out += _plugins(m)
    ext, dlls = _extender_plugins(m)
    out += ext
    out += _last_launch(m, dlls)
    out += _graphics(m, manifest)
    out += _case_twins(m)
    return out


def summary(findings):
    n = defaultdict(int)
    for f in findings:
        n[f["status"]] += 1
    if n["error"]:
        return f"{n['error']} problem(s) need fixing" + (f", {n['warn']} warning(s)" if n["warn"] else "")
    if n["warn"]:
        return f"No errors, {n['warn']} warning(s)"
    return "Everything checks out"
