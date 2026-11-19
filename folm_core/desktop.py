"""desktop - FOLM in the app menu.

The same job as make-shortcut.sh, done from inside the app so it also works for the AppImage
(a single file has no script beside it to run). Entries FOLM writes remember which program they
start; when the AppImage has moved or a newer one is run, they are quietly pointed at it.
"""

import os
import shutil
import subprocess

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARK = "X-FOLM-Launcher"
MAIN, NXM = "folm.desktop", "folm-nxm.desktop"      # NXM: the Nexus link handler of FOLM 1.0
ICON_SIZES = (48, 64, 128, 256, 512)


def _data_home():
    return os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


def apps_dir():
    return os.path.join(_data_home(), "applications")


def appimage():
    """The AppImage file FOLM is running from, or None."""
    a = os.environ.get("APPIMAGE")
    return a if a and os.path.isfile(a) else None


def launcher():
    """The program that starts this FOLM: the AppImage, or run-folm.sh in a source checkout."""
    return appimage() or os.path.join(HERE, "run-folm.sh")


def _exec_arg(path):
    """A path as one quoted argument of a desktop entry's Exec line."""
    for ch in ("\\", '"', "`", "$"):
        path = path.replace(ch, "\\" + ch)
    return '"' + path.replace("%", "%%") + '"'


def _entries(exe):
    q = _exec_arg(exe)
    common = f"Icon=folm\nTerminal=false\n{MARK}={exe}\n"
    main = ("[Desktop Entry]\nType=Application\nName=FOLM\nGenericName=Fallout Linux Manager\n"
            "Comment=Mod manager for Fallout: New Vegas and Fallout 3 on Linux\n"
            f"Exec={q}\nCategories=Game;Utility;\n" + common)
    return {MAIN: main}


def _quiet(cmd):
    if shutil.which(cmd[0]):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return ""


def recorded_launcher():
    """What FOLM's app-menu entry starts, if FOLM wrote it (None otherwise)."""
    try:
        with open(os.path.join(apps_dir(), MAIN)) as fh:
            for line in fh:
                if line.startswith(MARK + "="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return None


def in_menu():
    return os.path.isfile(os.path.join(apps_dir(), MAIN))


def write_entries(exe=None):
    """Put FOLM in the app menu, with its icon."""
    exe = exe or launcher()
    icons = os.path.join(_data_home(), "icons", "hicolor")
    for s in ICON_SIZES:
        src = os.path.join(HERE, "assets", f"folm-icon-{s}.png")
        if os.path.isfile(src):
            d = os.path.join(icons, f"{s}x{s}", "apps")
            os.makedirs(d, exist_ok=True)
            shutil.copyfile(src, os.path.join(d, "folm.png"))
    os.makedirs(apps_dir(), exist_ok=True)
    for name, text in _entries(exe).items():
        path = os.path.join(apps_dir(), name)
        with open(path + ".tmp", "w") as fh:
            fh.write(text)
        os.chmod(path + ".tmp", 0o755)
        os.replace(path + ".tmp", path)
    _quiet(["gtk-update-icon-cache", "-q", "-t", icons])
    _quiet(["update-desktop-database", apps_dir()])
    return exe


def retire_nexus_links(home):
    """FOLM 1.0 could sign in to Nexus and open 'Mod Manager Download' links. 1.1.1 dropped that
    (Nexus only allows personal API keys in apps it has registered). Undo what 1.0 set up: give the
    links back to the app that had them before, remove FOLM's link handler, and delete the stored
    API key, which nothing uses any more. Quiet; returns what it did, for the log."""
    done = []
    handler = os.path.join(apps_dir(), NXM)
    if _quiet(["xdg-mime", "query", "default", "x-scheme-handler/nxm"]) == NXM:
        try:
            with open(os.path.join(home, "nxm-previous-handler.txt")) as fh:
                old = fh.read().strip()
        except OSError:
            old = ""
        if old and old != NXM:
            _quiet(["xdg-mime", "default", old, "x-scheme-handler/nxm"])
            done.append(f"Nexus links open in {old} again")
    if os.path.isfile(handler):
        os.remove(handler)
        _quiet(["update-desktop-database", apps_dir()])
        done.append("removed FOLM's Nexus link handler")
    for f in ("nexus.json", "nxm-previous-handler.txt"):
        p = os.path.join(home, f)
        if os.path.isfile(p):
            os.remove(p)
            done.append("deleted the stored Nexus API key" if f == "nexus.json" else None)
    return [d for d in done if d]


def refresh():
    """Running as an AppImage whose menu entry points at another AppImage, or at one that's gone:
    point the entries here. Entries FOLM didn't write, or that start a source checkout that
    still exists, are left alone. Returns True if it changed something."""
    me = appimage()
    old = recorded_launcher()
    if not me or not old or old == me:
        return False
    if os.path.exists(old) and os.path.basename(old) == "run-folm.sh":
        return False
    write_entries(me)
    return True
