"""memwatch - how full is the running game's 4 GB? (the memory gauge)

New Vegas and Fallout 3 are 32-bit: whatever RAM the PC has, the game has 4 GB of addresses, and it
crashes when it can't find room in them. Linux can't tell how much of that is really in use: Wine
reserves the whole area its Windows programs will grow into, so free and used space look alike from
outside. So FOLM asks Windows' own view: a tiny read-only helper (memwatch/memwatch.c,
folm-memwatch.exe) runs in the game's own Wine and reports every few seconds how much is used and
how big the largest free block is.

Safety: the helper is started only while the game runs, with the game's own Wine and settings, and
only when the game's Wine server is reachable (otherwise Wine would start a second server on the
game's prefix). It only reads; if anything doesn't fit, the gauge stays off and the game is untouched.
"""
import os
import re
import shutil
import subprocess
import threading

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(HERE, "memwatch", "memwatch.c")
SHIPPED = os.path.join(HERE, "memwatch", "folm-memwatch.exe")      # built into the AppImage
LINE = re.compile(r"^mem " + r" ".join(rf"{k}=(\d+)" for k in
                  ("used", "commit", "reserve", "free", "largest", "image", "mapped", "private")) + r"$")
FIELDS = ("used", "commit", "reserve", "free", "largest", "image", "mapped", "private")

# When to warn, by how much of the 4 GB is still not in use (4096 - committed MB). Not by "free": the
# New Vegas Heap Replacer reserves nearly all of the 4 GB at the start and fills it as the game needs, so
# "free" is near 0 in a healthy game (measured: used 4081, free 14, committed 1247, game running fine).
# The game runs out when what's committed reaches what's reserved. First guesses, to be tuned on real
# sessions (docs/tech-debt.md).
WARN_ROOM, CRITICAL_ROOM = 600, 300


def helper_exe(home):
    """The helper program: the one shipped with FOLM, else built from source with MinGW (developers).
    None if neither is possible."""
    if os.path.exists(SHIPPED):
        return SHIPPED
    built = os.path.join(home, "tools", "memwatch", "folm-memwatch.exe")
    if os.path.exists(built) and os.path.exists(SOURCE) and os.path.getmtime(built) >= os.path.getmtime(SOURCE):
        return built
    cc = shutil.which("i686-w64-mingw32-gcc")
    if not cc or not os.path.exists(SOURCE):
        return None
    os.makedirs(os.path.dirname(built), exist_ok=True)
    r = subprocess.run([cc, "-O2", "-s", "-o", built, SOURCE], capture_output=True, text=True)
    return built if r.returncode == 0 and os.path.exists(built) else None


def parse(line):
    """A helper line -> {"used": MB, ...}, or None."""
    m = LINE.match(line.strip())
    return dict(zip(FIELDS, (int(x) for x in m.groups()))) if m else None


def room(s):
    """MB of the game's 4 GB not in use yet (reserved-but-unused counts as room: the heap fills it)."""
    return 4096 - s["commit"]


def level(s):
    """'ok', 'warn' or 'critical' for one sample."""
    r = room(s)
    return "critical" if r < CRITICAL_ROOM else "warn" if r < WARN_ROOM else "ok"


def _environ(pid):
    try:
        raw = open(f"/proc/{pid}/environ", "rb").read()
    except OSError:
        return {}
    out = {}
    for item in raw.split(b"\0"):
        k, sep, v = item.partition(b"=")
        if sep:
            out[k.decode(errors="replace")] = v.decode(errors="replace")
    return out


def _server_socket(prefix):
    """Where the Wine server for this prefix listens (Wine names it after the prefix folder's device and
    inode). The helper may only start when it exists: then it joins the game's server, never a new one."""
    try:
        st = os.stat(prefix)
    except OSError:
        return None
    return os.path.join("/tmp", f".wine-{os.getuid()}", f"server-{st.st_dev:x}-{st.st_ino:x}", "socket")


def game_wine(pid):
    """(wine binary, environment) to run the helper exactly as the game runs: the game's Proton and its
    Wine settings. None when that can't be worked out or the game's Wine server isn't reachable."""
    env = _environ(pid)
    data = env.get("STEAM_COMPAT_DATA_PATH")
    prefix = env.get("WINEPREFIX") or (os.path.join(data, "pfx") if data else None)
    if prefix and not os.path.isdir(prefix) and data:
        prefix = os.path.join(data, "pfx")                  # the container's path differs from ours
    wine = None
    for tool in (env.get("STEAM_COMPAT_TOOL_PATHS") or "").split(":"):
        w = os.path.join(tool, "files", "bin", "wine")
        if os.access(w, os.X_OK):
            wine = w
            break
    if not wine:
        try:
            exe = os.readlink(f"/proc/{pid}/exe")              # .../files/bin/wine-preloader
            w = os.path.join(os.path.dirname(exe), "wine")
            wine = w if os.access(w, os.X_OK) else None
        except OSError:
            pass
    if not wine or not prefix or not os.path.isdir(prefix):
        return None
    sock = _server_socket(prefix)
    if not sock or not os.path.exists(sock):
        return None
    # The game's Wine settings, minus the ones that only make sense inside the game's own process: the
    # Wine server connection it inherited (WINESERVERSOCKET is a file number of the game's), and how its
    # loader was started. With those the helper quits at once.
    inproc = ("WINESERVERSOCKET", "WINEPRELOADRESERVE", "WINELOADERNOEXEC")
    keep = {k: v for k, v in env.items() if k.startswith(("WINE", "PROTON_", "STEAM_COMPAT")) and k not in inproc}
    run = dict(os.environ, **keep)
    run.update({"WINEPREFIX": prefix, "WINEDEBUG": "-all", "WINEDLLOVERRIDES": ""})
    return wine, run


class Gauge:
    """Runs the helper beside the game; .latest is the newest sample ({} until there is one),
    .peak the fullest one (most used), .smallest_block the smallest "largest free block" seen,
    .problem why it isn't running (or None)."""

    def __init__(self, home, exe_name, interval=5):
        self.home, self.exe_name, self.interval = home, exe_name, interval
        self.latest, self.peak, self.smallest_block, self.problem, self.proc = {}, {}, None, None, None

    def start(self, game_pid):
        exe = helper_exe(self.home)
        if not exe:
            self.problem = "the memory helper isn't available (FOLM was run from source without MinGW)"
            return False
        how = game_wine(game_pid)
        if not how:
            self.problem = "couldn't join the game's Wine (the gauge stays off; the game isn't affected)"
            return False
        wine, env = how
        try:
            self.proc = subprocess.Popen([wine, exe, self.exe_name, str(self.interval)], env=env,
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                         stdin=subprocess.DEVNULL, text=True, start_new_session=True)
        except OSError as e:
            self.problem = f"couldn't start the memory helper ({e})"
            return False
        threading.Thread(target=self._read, daemon=True).start()
        return True

    def _read(self):
        for line in self.proc.stdout:
            s = parse(line)
            if s:
                self.latest = s
                if not self.peak or s["used"] > self.peak["used"]:
                    self.peak = s
                if self.smallest_block is None or s["largest"] < self.smallest_block:
                    self.smallest_block = s["largest"]
            elif line.startswith("error"):
                self.problem = line.strip()

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def notify(title, text, critical=False):
    """A desktop notification (and a sound), for the warning before the game runs out of memory."""
    if shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "-a", "FOLM", "-u", "critical" if critical else "normal", title, text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for snd in ("/usr/share/sounds/freedesktop/stereo/dialog-warning.oga",
                "/usr/share/sounds/freedesktop/stereo/bell.oga"):
        if os.path.exists(snd) and shutil.which("paplay"):
            subprocess.Popen(["paplay", snd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            break
