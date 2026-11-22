"""steamopts - quiet fixes FOLM puts in the game's Steam launch options (Linux only).

FOLM starts the game through Steam, so the game gets Steam's environment, not FOLM's. The only way to
hand it a setting like PULSE_LATENCY_MSEC is the game's launch options in Steam
(userdata/<user>/config/localconfig.vdf). Steam keeps that file in memory and writes it back when it
closes, so FOLM only edits it while Steam isn't running; otherwise it tries again next time.

What FOLM adds, it marks as its own (in the edition's data) and removes again when the setting is turned
off. Launch options the player typed are kept as they are, and a variable they set themselves is left
alone.
"""
import os
import re
import shutil
import subprocess

# variable -> (value, why). PULSE_LATENCY_MSEC: a bigger sound buffer for the game (Wine's PulseAudio
# driver), so the sound doesn't crackle when the CPU is busy (gunfights on 2-4 core PCs).
# gamemoderun: Feral's GameMode (when installed) sets the CPU to full speed while the game runs, which
# helps the game's one busy thread on PCs with few cores. Each fix belongs to a FOLM setting.
FIXES = {"PULSE_LATENCY_MSEC": ("60", "sound_fix"),
         "gamemoderun": (None, "gamemode")}


def gamemode_installed():
    return bool(shutil.which("gamemoderun"))


def gamemode_why_not():
    """None if GameMode can do its job here, else why not (plain words). GameMode's rules only let members
    of the "gamemode" group change the CPU speed (where the distribution has that group); for anyone else
    it starts, fails with "Not authorized" and changes nothing."""
    if not gamemode_installed():
        return "GameMode isn't installed (it's in every distribution: package \"gamemode\")"
    import grp
    try:
        gid = grp.getgrnam("gamemode").gr_gid
    except KeyError:
        return None
    if gid not in os.getgroups() and gid != os.getgid():
        return ("your account isn't in the \"gamemode\" group, so GameMode isn't allowed to change the CPU "
                "speed (to allow it: sudo usermod -aG gamemode $USER, then log out and back in)")
    return None

ROOTS = ("~/.local/share/Steam", "~/.steam/steam", "~/.var/app/com.valvesoftware.Steam/data/Steam",
         "~/.var/app/com.valvesoftware.Steam/.local/share/Steam")
STEAM64_BASE = 76561197960265728


def steam_running():
    return subprocess.run(["pgrep", "-x", "steam"], capture_output=True).returncode == 0


def config_files(roots=ROOTS):
    """localconfig.vdf of the Steam user who last signed in (all users if that's unknown), no duplicates."""
    out, seen = [], set()
    for root in roots:
        root = os.path.expanduser(root)
        ud = os.path.join(root, "userdata")
        if not os.path.isdir(ud) or os.path.realpath(root) in seen:
            continue
        seen.add(os.path.realpath(root))
        users = [u for u in os.listdir(ud) if u.isdigit()]
        recent = _recent_user(root)
        if recent in users:
            users = [recent]
        for u in users:
            p = os.path.join(ud, u, "config", "localconfig.vdf")
            if os.path.isfile(p):
                out.append(p)
    return out


def _recent_user(root):
    try:
        text = open(os.path.join(root, "config", "loginusers.vdf"), encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    for m in re.finditer(r'"(\d{17})"\s*\{([^{}]*)\}', text):
        if re.search(r'"MostRecent"\s*"1"', m.group(2), re.I):
            return str(int(m.group(1)) - STEAM64_BASE)
    return None


# --- a minimal VDF reader that keeps the text as it is ----------------------------------------------

_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])|//[^\n]*|\s+')


def _tokens(text):
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise ValueError(f"can't read Steam's config near character {pos}")
        if m.group(1) is not None:
            yield "str", m.group(1), m.start(), m.end()
        elif m.group(2):
            yield m.group(2), None, m.start(), m.end()
        pos = m.end()


def _find_app(text, app):
    """(block start, block end, LaunchOptions value span or None, indent) of apps/<app>, or None."""
    want = ["userlocalconfigstore", "software", "valve", "steam", "apps", str(app)]
    path, key = [], None
    toks = list(_tokens(text))
    i = 0
    while i < len(toks):
        kind, val, s, e = toks[i]
        if kind == "str":
            if key is None:
                key = (val, s)
            else:                                           # key "value" pair
                key = None
        elif kind == "{":
            name = key[0].lower() if key else ""
            path.append(name)
            if path == want:
                open_end, j, depth, lo = e, i + 1, 1, None
                while j < len(toks) and depth:
                    k2, v2, s2, e2 = toks[j]
                    if k2 == "{":
                        depth += 1
                    elif k2 == "}":
                        depth -= 1
                    elif depth == 1 and k2 == "str" and v2.lower() == "launchoptions" \
                            and j + 1 < len(toks) and toks[j + 1][0] == "str":
                        lo = (toks[j + 1][2] + 1, toks[j + 1][3] - 1)
                        j += 1
                    j += 1
                line_start = text.rfind("\n", 0, key[1]) + 1
                indent = text[line_start:key[1]]
                return open_end, toks[j - 1][2], lo, indent
            key = None
        elif kind == "}":
            if path:
                path.pop()
            key = None
        i += 1
    return None


def _unescape(v):
    return v.replace('\\"', '"').replace("\\\\", "\\")


def _escape(v):
    return v.replace("\\", "\\\\").replace('"', '\\"')


def launch_options(text, app):
    found = _find_app(text, app)
    if not found or not found[2]:
        return "" if found else None
    a, b = found[2]
    return _unescape(text[a:b])


def set_launch_options(text, app, value):
    """text with apps/<app>'s LaunchOptions set to value (added if missing). None if the app isn't there."""
    found = _find_app(text, app)
    if not found:
        return None
    open_end, _close, lo, indent = found
    if lo:
        return text[:lo[0]] + _escape(value) + text[lo[1]:]
    line = f'\n{indent}\t"LaunchOptions"\t\t"{_escape(value)}"'
    return text[:open_end] + line + text[open_end:]


# --- what FOLM adds ---------------------------------------------------------------------------------

def _var_re(var):
    """A variable (VAR=…) or, for a command word like gamemoderun, the word itself."""
    if var.islower():
        return re.compile(rf"(?:^|(?<=\s)){re.escape(var)}\s+")
    return re.compile(rf"(?:^|(?<=\s)){re.escape(var)}=\S*\s*")


def with_fix(opts, var, value):
    """opts with var=value in front of %command% (a command word, value None, goes right before it).
    Unchanged if it's already there (whoever put it there)."""
    if _var_re(var).search(opts):
        return opts
    item = var if value is None else f"{var}={value}"
    if not opts.strip():
        return f"{item} %command%"
    if "%command%" not in opts:                              # plain arguments: Steam adds them after the game
        return f"{item} %command% {opts.strip()}"
    if value is None:
        return opts.replace("%command%", f"{var} %command%", 1).strip()
    return f"{item} {opts.lstrip()}"


def without_fix(opts, var):
    out = _var_re(var).sub("", opts, count=1).strip()
    return "" if out == "%command%" else out


def sync(app, wanted, ours, files=None, running=None):
    """Make the launch options of `app` match: add each var in `wanted` ({var: value}) that isn't set,
    remove each var in `ours` (the ones FOLM added) that's no longer wanted.
    Returns (ours afterwards, note): note is None when nothing was needed or done, else a short line
    for the log. Does nothing while Steam runs (it would overwrite the file when it closes)."""
    files = config_files() if files is None else files
    ours = set(ours)
    todo_add = {v: x for v, x in wanted.items() if v not in ours}
    todo_remove = ours - set(wanted)
    if not files or not (todo_add or todo_remove):
        return ours, None
    if steam_running() if running is None else running:
        return ours, None
    changed = []
    for path in files:
        try:
            text = open(path, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        opts = launch_options(text, app)
        if opts is None:                                     # this user never had the game
            continue
        new = opts
        for var in todo_remove:
            new = without_fix(new, var)
        for var, value in todo_add.items():
            if _var_re(var).search(new):                     # the player set it already: theirs, not ours
                continue
            new = with_fix(new, var, value)
            changed.append(var)
        if new == opts:
            continue
        out = set_launch_options(text, app, new)
        backup = f"{path}.folm-backup"
        if not os.path.exists(backup):
            shutil.copy2(path, backup)
        tmp = f"{path}.folm-tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(out)
        os.replace(tmp, path)
    ours = (ours - todo_remove) | set(changed)
    if not changed and not todo_remove:
        return ours, None
    parts = [f"added {v}" + ("" if wanted[v] is None else f"={wanted[v]}") for v in sorted(set(changed))] + \
            [f"removed {v}" for v in sorted(todo_remove)]
    return ours, f"Steam launch options: {', '.join(parts)}"


def current(app, files=None):
    """The game's launch options as Steam has them on disk ("" if none), or None if unknown."""
    for path in config_files() if files is None else files:
        try:
            opts = launch_options(open(path, encoding="utf-8").read(), app)
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if opts is not None:
            return opts
    return None


def has(opts, var):
    return bool(opts) and bool(_var_re(var).search(opts))
