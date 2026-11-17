"""window - make the game's window borderless on Linux desktops.

Windowed mode at your screen's size is the safe choice under Proton (fullscreen can vanish
on alt-tab), but the desktop's title bar then pushes the bottom of the picture off screen.
The game has no borderless option, so FOLM does it from outside: it waits for the game
window, sets the "no decorations" hint, moves it to the corner and asks the desktop to show
it fullscreen (_NET_WM_STATE_FULLSCREEN, via wmctrl). Nothing in the game or its files changes.

Works on X11 desktops (Cinnamon, MATE, Xfce, KDE/GNOME on X11) and for Proton's XWayland
windows on most Wayland desktops. Needs xdotool and xprop (wmctrl for the fullscreen step).
"""

import os
import shutil
import subprocess
import threading
import time

TITLES = {"courier": "Fallout: New Vegas", "wanderer": "Fallout3"}


def available():
    return bool(os.environ.get("DISPLAY")) and all(shutil.which(t) for t in ("xdotool", "xprop"))


def _find(title):
    r = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", f"^{title}$"],
                       capture_output=True, text=True)
    ids = r.stdout.split()
    return ids[0] if ids else None


def make_borderless(win):
    """No title bar + cover the screen. The game stays in its own windowed mode (no exclusive fullscreen,
    which is what vanishes on alt-tab under Wine); the desktop just shows the window fullscreen."""
    subprocess.run(["xprop", "-id", win, "-f", "_MOTIF_WM_HINTS", "32c", "-set", "_MOTIF_WM_HINTS", "2, 0, 0, 0, 0"],
                   capture_output=True)
    subprocess.run(["xdotool", "windowmove", win, "0", "0"], capture_output=True)
    if shutil.which("wmctrl"):
        subprocess.run(["wmctrl", "-i", "-r", win, "-b", "add,fullscreen"], capture_output=True)


def borderless_when_ready(edition, log=lambda *a: None, timeout=240, stop=None):
    """Background thread: wait for the game window, then make it borderless (twice, as the game
    can reset its window once the main menu loads)."""
    if not available():
        log("Borderless window: needs xdotool and xprop (install them from your package manager).")
        return None
    title = TITLES.get(edition, "Fallout: New Vegas")

    def run():
        end = time.time() + timeout
        while time.time() < end and not (stop and stop()):
            win = _find(title)
            if win:
                make_borderless(win)
                time.sleep(8)
                win = _find(title) or win
                make_borderless(win)
                log("Borderless window applied.")
                return
            time.sleep(2)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t
