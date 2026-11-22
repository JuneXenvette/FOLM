"""appprefs - FOLM's own preferences (not the game's): <FOLM home>/app.json, shared by all profiles.

Game settings live in each edition's profile.json (Manager.SETTINGS) and are put into the game on deploy;
these only change how FOLM itself behaves, so changing one never needs a deploy.
"""

import json
import os

DEFAULTS = {
    "watch_downloads": True,      # offer to install new mod files that appear in the download folders
}


def _path(home):
    return os.path.join(home, "app.json")


def load(home):
    try:
        with open(_path(home)) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    return {k: data.get(k, v) for k, v in DEFAULTS.items()}


def get(home, key):
    return load(home)[key]


def set(home, key, value):          # noqa: A001 - mirrors get()
    if key not in DEFAULTS:
        raise KeyError(key)
    data = load(home)
    data[key] = value
    os.makedirs(home, exist_ok=True)
    tmp = _path(home) + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=1)
    os.replace(tmp, _path(home))


def download_folders(library_folders=()):
    """Where new mod files land: the desktop's download folder (XDG), plus FOLM's library folders."""
    folders = []
    try:
        with open(os.path.expanduser("~/.config/user-dirs.dirs")) as fh:
            for line in fh:
                if line.startswith("XDG_DOWNLOAD_DIR="):
                    folders.append(os.path.expandvars(line.split("=", 1)[1].strip().strip('"')))
    except OSError:
        pass
    folders.append(os.path.expanduser("~/Downloads"))
    out = []
    for f in [*folders, *library_folders]:
        f = os.path.abspath(f)
        if os.path.isdir(f) and f not in out:
            out.append(f)
    return out


MOD_FILES = (".7z", ".zip", ".rar", ".fomod")
UNFINISHED = (".part", ".crdownload", ".download", ".tmp", ".partial")


def new_mod_files(folders, seen):
    """Mod files in `folders` that aren't in `seen` (a set of paths, updated). Downloads still being
    written (browser temp names) are skipped until they're finished."""
    out = []
    for folder in folders:
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for n in names:
            p = os.path.join(folder, n)
            low = n.lower()
            if p in seen or low.endswith(UNFINISHED) or not low.endswith(MOD_FILES):
                continue
            seen.add(p)
            out.append(p)
    return out
