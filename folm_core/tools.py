"""Modding tools FOLM knows about (Tools tab): what each is, where to get it, how to find and run it.

GECK comes from Steam and installs into the game folder. The others are dropped on FOLM like a mod:
FOLM keeps them in <FOLM home>/tools/<id> (they're not deployed into the game) and runs them with
Proton's Wine in the game's own prefix, pointed at the game's Data folder with your mods deployed.
"""
import os
import re

# per edition: (game switch xEdit/xLODGen understand, name the tool is known by)
GAME_ARG = {"courier": "-fnv", "wanderer": "-fo3"}

CATALOG = [
    {"id": "geck", "what": "Bethesda's editor: make new mods or change existing ones.",
     "names": {"courier": "GECK", "wanderer": "GECK"},
     "get": {"courier": "steam://open/tools", "wanderer": "steam://open/tools"},
     "how": "Installs from Steam (Library > Tools) into the game folder."},
    {"id": "xedit", "what": "Inspect, clean and fix plugins; see and resolve record conflicts.",
     "names": {"courier": "FNVEdit (xEdit)", "wanderer": "FO3Edit (xEdit)"},
     "exe": re.compile(r"^(xedit|fnvedit|fo3edit|tes5edit|sseedit)(64)?\.exe$", re.I),
     "get": {"courier": "https://www.nexusmods.com/newvegas/mods/34703",
             "wanderer": "https://www.nexusmods.com/fallout3/mods/637"},
     "how": "Download it, then drop the file on FOLM. Your edits become a mod (\"xEdit output\")."},
    {"id": "xlodgen", "what": "Builds distant terrain LOD (what the world looks like far away).",
     "names": {"courier": "xLODGen", "wanderer": "xLODGen"},
     "exe": re.compile(r"^(xlodgen|fnvlodgen|fo3lodgen)(x64)?\.exe$", re.I),
     "get": {"courier": "https://stepmodifications.org/forum/topic/13451-xlodgen-terrain-lod-beta-for-fnv-fo3-fo4-fo4vr-tes5-sse-tes5vr-enderal/",
             "wanderer": "https://stepmodifications.org/forum/topic/13451-xlodgen-terrain-lod-beta-for-fnv-fo3-fo4-fo4vr-tes5-sse-tes5vr-enderal/"},
     "how": "Download it, then drop the file on FOLM. The LOD it builds becomes a mod (\"Generated LOD\")."},
]
BY_ID = {t["id"]: t for t in CATALOG}
OUTPUT_MOD = {"xedit": "xEdit output", "xlodgen": "Generated LOD"}


def tool_for_files(files):
    """Which catalogued tool a download is (from its file list), or None."""
    names = {os.path.basename(f.replace("\\", "/")) for f in files}
    for t in CATALOG:
        if "exe" in t and any(t["exe"].match(n) for n in names):
            return t["id"]
    return None


def tools_dir(home, tool_id):
    return os.path.join(home, "tools", tool_id)


def find_exe(folder, tool_id, edition):
    """The tool's program inside its folder. Prefers this game's own name (FNVEdit for New Vegas),
    then the 64-bit build, then any match."""
    t = BY_ID[tool_id]
    if not os.path.isdir(folder):
        return None
    found = []
    for dp, dn, fn in os.walk(folder):
        found += [os.path.join(dp, f) for f in fn if t["exe"].match(f)]
    if not found:
        return None
    own = "fnv" if edition == "courier" else "fo3"

    def score(p):
        b = os.path.basename(p).lower()
        return (not b.startswith(own), "64" not in b, p.count(os.sep), b)
    return sorted(found, key=score)[0]


def win_path(p, trailing=False):
    """A Linux path as Wine sees it (drive Z: is /)."""
    w = "Z:" + os.path.abspath(p).replace("/", "\\")
    return w + "\\" if trailing and not w.endswith("\\") else w


def args_for(tool_id, edition, data_dir, output_dir=None):
    """Command-line switches: which game, where its Data is, and where to write output."""
    if tool_id == "xedit":
        return [GAME_ARG[edition], f"-D:{win_path(data_dir, True)}"]
    if tool_id == "xlodgen":
        return [GAME_ARG[edition], f"-D:{win_path(data_dir, True)}", f"-o:{win_path(output_dir, True)}"]
    return []


def is_tool_clutter(rel):
    """xEdit's own backups/cache saved inside Data: kept with the tool, not made part of a mod."""
    head = rel.replace("\\", "/").split("/")
    return any(re.match(r"^\w*edit (backups|cache)$", h, re.I) for h in head[:2])
