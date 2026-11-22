"""essentials - the few mods nearly every setup of these games needs, and whether they're installed.

Shown in the 🩺 Health check ("Essentials") and explained in the FAQ. Information, not a gate: FOLM and
the game run without them, and the pre-Play checks only stop you when something you installed can't
work without one (NVSE plugins without xNVSE, say).
"""
import struct

from . import deploy as dep


def _game_file(m, *names):
    g = m.data["game_dir"]
    return any(dep.exists_ci(g, n) for n in names)


def _plugin(m, folder, name):
    return bool(dep.exists_ci(m.data_dir, f"{folder}/Plugins/{name}"))


def _decompressed(m):
    """The game's own archives are stored uncompressed (what the BSA Decompressor does). None if unknown."""
    p = dep.exists_ci(m.data_dir, "Fallout - Meshes.bsa")
    if not p:
        return None
    try:
        with open(p, "rb") as fh:
            magic, _v, _o, flags = struct.unpack("<4sIII", fh.read(16))
    except (OSError, struct.error):
        return None
    return magic == b"BSA\0" and not flags & 0x4


# id, name, why (plain words), where to get it, how FOLM tells, how much it matters ("needed": most mods
# don't work without it; "recommended": stability or speed), and which FOLM features use it.
LIST = {
    "courier": [
        ("xnvse", "xNVSE (New Vegas Script Extender)",
         "Lets mods add new abilities to the game. Nearly every modern mod needs it, and so do most of the "
         "others on this list.",
         "https://www.nexusmods.com/newvegas/mods/67883",
         lambda m: _game_file(m, "nvse_1_4.dll", "nvse_steam_loader.dll"), "needed",
         "the low-memory save"),
        ("4gb", "FNV 4GB Patcher",
         "Lets the game use 4 GB of memory instead of 2, and starts xNVSE with the game. Without it big "
         "setups crash early, and xNVSE's plugins don't load.",
         "https://www.nexusmods.com/newvegas/mods/62552",
         lambda m: m._exe_is_4gb(), "needed", ""),
        ("jip", "JIP LN NVSE Plugin",
         "Hundreds of fixes and new script commands; many mods need it.",
         "https://www.nexusmods.com/newvegas/mods/58277",
         lambda m: _plugin(m, "NVSE", "jip_nvse.dll"), "recommended", "the low-memory save"),
        ("nvtf", "New Vegas Tick Fix (NVTF)",
         "Fixes stutter and timing problems, and has the texture setting that saves memory.",
         "https://www.nexusmods.com/newvegas/mods/66537",
         lambda m: _plugin(m, "NVSE", "nvtf.dll"), "recommended", ""),
        ("bsa", "FNV BSA Decompressor",
         "Unpacks the game's archives once, so they load faster and stutter less.",
         "https://www.nexusmods.com/newvegas/mods/65854",
         _decompressed, "recommended", ""),
    ],
    "wanderer": [
        ("fose", "FOSE (Fallout Script Extender)",
         "Lets mods add new abilities to the game. Many mods need it.",
         "https://www.nexusmods.com/fallout3/mods/8606",
         lambda m: _game_file(m, "fose_loader.exe", "fose_1_7.dll", "fose_1_7ng.dll"), "needed", ""),
        ("fap", "Fallout Anniversary Patcher",
         "Makes the current Steam version of Fallout 3 work with FOSE, and lets the game use 4 GB of memory.",
         "https://www.nexusmods.com/fallout3/mods/24913",
         lambda m: m._exe_is_4gb(), "needed", ""),
        ("bsa", "FO3 BSA Decompressor",
         "Unpacks the game's archives once, so they load faster and stutter less.",
         "https://www.nexusmods.com/fallout3/mods/25720",
         _decompressed, "recommended", ""),
    ],
}


def check(m):
    """[{id, name, why, url, have (True/False/None = can't tell), level, used_by}] for this edition."""
    out = []
    for ident, name, why, url, test, level, used_by in LIST[m.edition]:
        try:
            have = test(m)
        except Exception:
            have = None
        out.append({"id": ident, "name": name, "why": why, "url": url, "have": have, "level": level,
                    "used_by": used_by})
    return out
