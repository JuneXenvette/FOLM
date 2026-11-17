#!/usr/bin/env python3
"""detect - work out what kind of mod a file is, without extracting it.

Reads the file list of an archive (zip / 7z / rar, via the 7z tool) or a folder
and classifies it, so FOLM knows which installer to use:

  exe-installer   a Windows .exe installer (run in the Wine sandbox)
  ttw-installer   the Tale of Two Wastelands installer package (.mpi + exe)
  fomod-xml       FOMOD with a ModuleConfig.xml (our native installer)
  fomod-csharp    FOMOD / FOMM package with a C# script (legacy script engine)
  bain            BAIN-style numbered option folders ("00 Core", "10 Option")
  data            files that go in the game's Data folder
  game-root       files that go next to the game .exe (script extender, DLLs)
  data+game-root  both of the above
  unknown         nothing recognisable as a Fallout mod
"""

import json
import os
import re
import subprocess
import sys
from collections import defaultdict

# Folder names that live directly inside Data/ (lowercase).
DATA_DIRS = {
    "meshes", "textures", "sound", "music", "menus", "materials", "shaders",
    "scripts", "strings", "video", "lodsettings", "trees", "facegen",
    "nvse", "fose", "config", "distantlod", "lsdata", "fonts", "grass",
    "landscape", "optionalmods", "characters",
}
PLUGIN_EXTS = (".esm", ".esp")
DATA_FILE_EXTS = PLUGIN_EXTS + (".bsa", ".override", ".ini", ".nam")
# Files that only make sense next to FalloutNV.exe / Fallout3.exe.
ROOT_FILE_RE = re.compile(r"^(nvse_|fose_|d3d9\.dll$|dinput8\.dll$|dxgi\.dll$|enb|.*_loader\.(exe|dll)$)", re.I)
DOC_EXTS = (".txt", ".md", ".pdf", ".html", ".htm", ".rtf", ".url", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".docx")
BAIN_DIR_RE = re.compile(r"^\d{2,3}\s")


# ---------------------------------------------------------------- reading file lists

def list_archive(path):
    """Return (files, dirs) inside an archive, as '/'-separated relative paths."""
    try:
        out = subprocess.run(["7z", "l", "-ba", "-slt", path], capture_output=True,
                             text=True, errors="replace", timeout=300)
    except FileNotFoundError:
        raise SystemExit("detect: the '7z' tool is required (package p7zip / 7zip)")
    if out.returncode != 0:
        raise ValueError(f"cannot read archive: {out.stderr.strip() or out.stdout.strip()[:200]}")
    files, dirs = [], set()
    cur = {}
    for line in out.stdout.splitlines() + [""]:
        if not line.strip():
            if "Path" in cur:
                p = cur["Path"].replace("\\", "/").strip("/")
                (dirs.add(p) if cur.get("Folder") == "+" or "D" in cur.get("Attributes", "")[:1] else files.append(p))
            cur = {}
            continue
        k, _, v = line.partition(" = ")
        cur[k.strip()] = v
    for f in files:  # implied parent folders
        parts = f.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:i]))
    return files, dirs


def list_folder(path):
    files, dirs = [], set()
    for dp, dn, fn in os.walk(path):
        rel = os.path.relpath(dp, path).replace(os.sep, "/")
        rel = "" if rel == "." else rel
        for d in dn:
            dirs.add(f"{rel}/{d}".strip("/"))
        for f in fn:
            files.append(f"{rel}/{f}".strip("/"))
    return files, dirs


# ---------------------------------------------------------------- classification

def children(files, dirs, prefix):
    """Immediate child names (lowercase -> actual) under prefix ('' = top)."""
    pre = prefix + "/" if prefix else ""
    kids = {}
    for p in list(dirs) + files:
        if p.lower().startswith(pre.lower()) and p != prefix:
            name = p[len(pre):].split("/")[0]
            if name:
                kids[name.lower()] = name
    return kids


def is_dir(dirs, prefix, name):
    full = f"{prefix}/{name}".strip("/").lower()
    return any(d.lower() == full for d in dirs)


def unwrap(files, dirs):
    """Skip single wrapper folders ('MyMod v1.2/...') that contain everything."""
    prefix = ""
    while True:
        kids = children(files, dirs, prefix)
        real = {k: v for k, v in kids.items() if not k.endswith(DOC_EXTS)}
        if len(real) == 1:
            (low, name), = real.items()
            if is_dir(dirs, prefix, name) and low != "data" and low not in DATA_DIRS and low != "fomod":
                prefix = f"{prefix}/{name}".strip("/")
                continue
        return prefix


def case_collisions(files, dirs=()):
    """Paths (files or folders) that differ only by letter case."""
    seen = defaultdict(set)
    for p in list(files) + list(dirs):
        seen[p.lower()].add(p)
    return sorted(v for v in (sorted(s) for s in seen.values()) if len(v) > 1)


def classify(files, dirs, source_name=""):
    r = {"type": "unknown", "data_root": None, "game_root_files": [], "plugins": [],
         "options": [], "warnings": [], "files": len(files)}
    low_files = [f.lower() for f in files]

    # Whole-file installers
    if source_name.lower().endswith(".exe"):
        r["type"] = "exe-installer"
        return r
    if any(f.endswith(".mpi") for f in low_files) and any(f.endswith(".exe") for f in low_files):
        r["type"] = "ttw-installer"
        r["notes"] = "Tale of Two Wastelands installer: run the .exe in the Wine sandbox with game paths in the registry"
        return r

    prefix = unwrap(files, dirs)
    pre = (prefix + "/") if prefix else ""
    kids = children(files, dirs, prefix)

    # FOMOD
    fomod = next((v for k, v in kids.items() if k == "fomod"), None)
    if fomod:
        fk = children(files, dirs, pre + fomod)
        if "moduleconfig.xml" in fk:
            r["type"] = "fomod-xml"
            r["data_root"] = prefix
        elif "script.cs" in fk:
            r["type"] = "fomod-csharp"
            r["data_root"] = prefix
        else:
            # only info.xml (mod name/author): no installer, so it's a plain mod
            r["notes"] = "fomod/ has only info.xml (no installer): installed as a plain mod"
    elif "script.cs" in kids:
        r["type"] = "fomod-csharp"
        r["data_root"] = prefix

    # BAIN: several numbered option folders
    bain = sorted(v for k, v in kids.items() if BAIN_DIR_RE.match(k) and is_dir(dirs, prefix, v))
    if r["type"] == "unknown" and len(bain) >= 2:
        r["type"] = "bain"
        r["options"] = bain
        r["data_root"] = prefix

    # Plain data / game-root
    if r["type"] == "unknown":
        data_root = None
        if "data" in kids and is_dir(dirs, prefix, kids["data"]):
            data_root = pre + kids["data"]                # archive mirrors the game folder
            root_level = [v for k, v in kids.items() if k != "data" and not k.endswith(DOC_EXTS)]
            r["game_root_files"] = sorted(root_level)
        elif any(k in DATA_DIRS for k in kids) or any(k.endswith(DATA_FILE_EXTS) for k in kids):
            data_root = prefix
        roots = sorted(v for k, v in kids.items() if ROOT_FILE_RE.match(k) and not is_dir(dirs, prefix, v))
        if data_root is None and roots:
            r["type"] = "game-root"
            r["game_root_files"] = sorted(v for k, v in kids.items() if not k.endswith(DOC_EXTS))
        elif data_root is not None:
            r["type"] = "data+game-root" if r["game_root_files"] or roots else "data"
            r["data_root"] = data_root
            r["game_root_files"] = sorted(set(r["game_root_files"]) | set(roots))

    # Plugins (top level of the data root, which is where the game looks)
    if r["data_root"] is not None:
        dk = children(files, dirs, r["data_root"])
        r["plugins"] = sorted(v for k, v in dk.items() if k.endswith(PLUGIN_EXTS))

    for group in case_collisions(files, dirs):
        r["warnings"].append("case collision: " + "  vs  ".join(group))
    if r["type"] == "unknown":
        r["warnings"].append("no Fallout Data files, FOMOD, BAIN or installer found; may be for another game")
    return r


def detect(path):
    name = os.path.basename(path.rstrip("/"))
    if os.path.isdir(path):
        files, dirs = list_folder(path)
    elif name.lower().endswith(".exe"):
        files, dirs = [name], set()
    else:
        files, dirs = list_archive(path)
    r = classify(files, dirs, name)
    # an archive that only wraps an old FOMM package (e.g. MyMod.rar -> MyMod.fomod)
    inner = [f for f in files if f.lower().endswith(".fomod")]
    rest = [f for f in files if not f.lower().endswith(".fomod") and not f.lower().endswith(DOC_EXTS)]
    if r["type"] == "unknown" and len(inner) == 1 and not rest:
        r = dict(r, type="nested", inner=inner[0], warnings=[],
                 notes=f"wraps the package {os.path.basename(inner[0])}: FOLM unpacks it and installs that")
    r["source"] = path
    return r


MOD_FILE_EXTS = (".zip", ".7z", ".rar", ".fomod", ".exe")


def scan(folders):
    """Find mod files in any number of folders, including all subfolders."""
    found = []
    for folder in folders:
        for dp, dn, fn in os.walk(os.path.expanduser(folder)):
            dn[:] = [d for d in dn if not d.startswith(".")]
            found += [os.path.join(dp, f) for f in fn if f.lower().endswith(MOD_FILE_EXTS)]
    return sorted(found)


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="Work out what kind of mod a file or folder is.")
    p.add_argument("paths", nargs="*", help="mod archives (.zip/.7z/.rar), .exe installers or unpacked mod folders")
    p.add_argument("--scan", metavar="FOLDER", action="append", default=[],
                   help="search this folder and all its subfolders for mod files (repeatable)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    a = p.parse_args(argv)
    paths = list(a.paths) + scan(a.scan)
    if not paths:
        p.error("give mod files/folders, or --scan FOLDER")
    results = []
    for path in paths:
        try:
            results.append(detect(path))
        except (ValueError, OSError) as e:
            results.append({"source": path, "type": "error", "warnings": [str(e)]})
    if a.json:
        print(json.dumps(results, indent=1))
        return 0
    for r in results:
        print(f"{os.path.basename(r['source'])}\n  type: {r['type']}")
        if r.get("data_root") is not None:
            print(f"  data root: {r['data_root'] or '(archive top)'}")
        for key, label in (("plugins", "plugins"), ("game_root_files", "game-root files"), ("options", "BAIN options")):
            if r.get(key):
                print(f"  {label}: {', '.join(r[key])}")
        if r.get("notes"):
            print(f"  note: {r['notes']}")
        for w in r.get("warnings", []):
            print(f"  ! {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
