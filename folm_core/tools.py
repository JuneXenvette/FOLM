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


# ------------------------------------------------------------------ versions (Tools tab)
VERSION_FILE = ".folm-tool.json"          # written at install: the download's name and the version in it
_VER = re.compile(r"(?<![\w.])v?(\d+(?:\.\d+){1,3}[a-z]?)(?![\w.])", re.I)
_BETA = re.compile(r"\bbeta[ _.-]?(\d+)\b", re.I)


def version_in_name(name):
    """'xLODGen beta 128' or 'xLODGen.132.7z' -> 'beta 128' / 'beta 132', 'FNVEdit 4.1.5f.7z' -> '4.1.5f'; Nexus names keep their
    version in the middle ('FNVEdit 4.1.5f-34703-4-1-5f-1700000000.7z'). None if there's none."""
    base = re.sub(r"\.(7z|zip|rar|exe)$", "", os.path.basename(name), flags=re.I)
    base = re.sub(r"-\d+-[\w-]*-\d{10}(?:\(\d+\))?$", "", base)        # Nexus's id-version-time tail
    base = base.replace("_", " ")
    m = _BETA.search(base) or re.search(r"lodgen\W*(\d{2,4})$", base, re.I)   # 'xLODGen.132' is beta 132
    if m:
        return f"beta {m.group(1)}"
    m = _VER.search(base)
    return m.group(1) if m else None


def pe_version(path):
    """The version a Windows program states about itself (its version resource), e.g. '4.1.5.0'."""
    import struct
    try:
        with open(path, "rb") as fh:
            b = fh.read()
    except OSError:
        return None
    for m in re.finditer("VS_VERSION_INFO".encode("utf-16-le"), b):
        j = (m.end() + 2 + 3) & ~3
        k = b.find(struct.pack("<I", 0xFEEF04BD), j, j + 16)
        if k >= 0:
            ms, ls = struct.unpack_from("<II", b, k + 8)
            v = [ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF]
            while len(v) > 2 and v[-1] == 0:
                v.pop()
            return ".".join(map(str, v))
    return None


def tool_version(folder, exe):
    """The installed tool's version, as exactly as it can be told: the version in the download's name
    (saved at install), else the one the tool writes in its own log ('FNVLODGen 4.1.5o ...'), else
    the folder's name, else the program's version resource. None if nothing says."""
    import json
    try:
        with open(os.path.join(folder, VERSION_FILE)) as fh:
            v = json.load(fh).get("version")
        if v:
            return v
    except (OSError, ValueError):
        pass
    if exe:
        logs = [os.path.join(os.path.dirname(exe), f) for f in os.listdir(os.path.dirname(exe))
                if f.lower().endswith("_log.txt")]
        for log in sorted(logs, key=os.path.getmtime, reverse=True):
            try:
                with open(log, errors="replace") as fh:
                    first = fh.readline()
            except OSError:
                continue
            m = re.match(r"^\S+ (\d+\.\d+\.\d+[a-z]?)\b", first)
            if m:
                return m.group(1)
        d = os.path.dirname(exe)
        while d.startswith(folder) and d != folder:
            v = version_in_name(os.path.basename(d))
            if v:
                return v
            d = os.path.dirname(d)
        return pe_version(exe)
    return None


def save_version(folder, archive):
    """Remember the download's name and its version next to the installed tool."""
    import json
    with open(os.path.join(folder, VERSION_FILE), "w") as fh:
        json.dump({"download": os.path.basename(archive), "version": version_in_name(archive)}, fh)
