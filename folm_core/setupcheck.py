"""setupcheck - which system tools FOLM needs, which are missing, and how to install them.

Used by `folm.py doctor`, the app's first start, and ./setup.sh. Only reports; installs nothing.
"""

import os
import shutil

# (command(s) that must all exist, what it's for, required?, package per distro family)
TOOLS = [
    (("7z",), "unpacking mod archives (.7z, .zip, most .rar)", True,
     {"apt": "p7zip-full", "dnf": "p7zip p7zip-plugins", "pacman": "7zip", "zypper": "7zip"}),
    (("steam",), "launching the game", True,
     {"apt": "steam", "dnf": "steam", "pacman": "steam", "zypper": "steam"}),
    (("unrar",), "RAR files 7-Zip can't unpack (RAR5 with some settings)", False,
     {"apt": "unrar", "dnf": "unrar", "pacman": "unrar", "zypper": "unrar"}),
    (("mono", "mcs"), "old FOMM script installers (e.g. BOG)", False,
     {"apt": "mono-complete", "dnf": "mono-complete", "pacman": "mono", "zypper": "mono-complete"}),
    (("bwrap",), "running old FOMM installers and Windows installers in a sandbox", False,
     {"apt": "bubblewrap", "dnf": "bubblewrap", "pacman": "bubblewrap", "zypper": "bubblewrap"}),
    (("xdotool", "xprop"), "borderless window and window fixes (X11 only)", False,
     {"apt": "xdotool x11-utils", "dnf": "xdotool xprop", "pacman": "xdotool xorg-xprop",
      "zypper": "xdotool xprop"}),
    (("wmctrl",), "borderless fullscreen", False,
     {"apt": "wmctrl", "dnf": "wmctrl", "pacman": "wmctrl", "zypper": "wmctrl"}),
]

INSTALL = {"apt": "sudo apt install", "dnf": "sudo dnf install", "pacman": "sudo pacman -S",
           "zypper": "sudo zypper install"}


def family():
    """apt / dnf / pacman / zypper, or None if we can't tell."""
    for f in ("apt", "dnf", "pacman", "zypper"):
        if shutil.which(f):
            return f
    return None


def steam_present():
    """Steam can be installed as a Flatpak, which has no `steam` command on PATH."""
    if shutil.which("steam"):
        return True
    return any(os.path.isdir(os.path.expanduser(p)) for p in
               ("~/.steam/steam", "~/.local/share/Steam", "~/.var/app/com.valvesoftware.Steam/data/Steam"))


def missing():
    """[{tools, why, required, package}] for everything not found."""
    fam = family()
    out = []
    for cmds, why, required, pkgs in TOOLS:
        if cmds == ("steam",):
            ok = steam_present()
        elif cmds == ("7z",):
            from folm_core.archive import seven_zip       # the AppImage brings its own
            ok = bool(seven_zip())
        else:
            ok = all(shutil.which(c) for c in cmds)
        if not ok:
            out.append({"tools": cmds, "why": why, "required": required, "package": pkgs.get(fam)})
    return out


def wayland():
    return os.environ.get("XDG_SESSION_TYPE") == "wayland" or (
        os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"))


def report(items=None):
    """Plain-text lines for the terminal or a dialog. Empty list = all good."""
    items = missing() if items is None else items
    if not items:
        return []
    lines = []
    for it in items:
        tag = "needed" if it["required"] else "optional"
        lines.append(f"{'✖' if it['required'] else '•'} {' + '.join(it['tools'])} ({tag}): {it['why']}")
    pkgs = " ".join(it["package"] for it in items if it["package"])
    fam = family()
    if pkgs and fam:
        lines.append(f"Install with:  {INSTALL[fam]} {pkgs}")
    elif pkgs:
        lines.append("Install these with your distro's package manager.")
    return lines
