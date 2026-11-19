"""wintool - run a mod's Windows installer or patcher (.exe) the way it would run on Windows, and turn
what it produced into a normal FOLM mod.

Covers installers and tools such as Tale of Two Wastelands, FNV BSA Decompressor, Ultimate Edition ESM
Fixes, the Fallout 3 Anniversary Patcher and the Unofficial Fallout 3 ESM Patcher. The player downloads
them; FOLM only runs them.

How it stays safe and reversible:
  * The game folder is mounted copy-on-write (overlayfs in an unprivileged user namespace). The tool sees
    the real game and may change, add or delete files, but every write lands in a separate folder; the
    real game folder is never touched. Those writes become the mod (Data/... -> data, the rest -> files
    next to the game's exe), so Undeploy takes them back out.
  * The tool runs in bubblewrap with no network, only the folders it needs, and its own Wine prefix
    (not the game's), using Proton's Wine.
  * Drive O: in the tool's file dialogs is "FOLM output": anything saved there also becomes the mod
    (e.g. TTW's destination folder).
"""

import filecmp
import glob
import os
import re
import shlex
import shutil
import stat
import subprocess
import time

from . import deploy as dep

SKIP_EXE = re.compile(r"unins\d*|uninstall|vc_?redist|dotnet|ndp\d|directx|dxsetup|xdelta|oggenc|7za?\.exe|"
                      r"crashpad|helper|updater", re.I)
GOOD_EXE = re.compile(r"install|setup|patch|decompress|fix|convert", re.I)
DOCS = (".txt", ".md", ".pdf", ".html", ".htm", ".rtf", ".url", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".docx")


class ToolError(Exception):
    pass


# ---------------------------------------------------------------- Wine

def find_wine(steam_roots, libraries):
    """Proton's wine: GE-Proton first (newest), then Steam's Proton (newest), then the system's wine.
    Returns (wine, proton_dir or None)."""
    def ver(p):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(p))] or [0]
    ge = []
    for root in steam_roots:
        ge += glob.glob(os.path.join(root, "compatibilitytools.d", "*", "files", "bin", "wine"))
    ge.sort(key=lambda w: ver(os.path.dirname(os.path.dirname(os.path.dirname(w)))), reverse=True)
    valve = []
    for lib in libraries:
        valve += glob.glob(os.path.join(lib, "common", "Proton*", "files", "bin", "wine"))
    numbered = [w for w in valve if re.search(r"Proton \d", w)]
    numbered.sort(key=lambda w: ver(os.path.dirname(os.path.dirname(os.path.dirname(w)))), reverse=True)
    others = [w for w in valve if w not in numbered]
    for w in ge + numbered + others:
        if os.access(w, os.X_OK):
            return os.path.realpath(w), os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(w))))
    sys_wine = shutil.which("wine")
    if sys_wine:
        return sys_wine, None
    raise ToolError("couldn't find Wine: install Proton in Steam (any game's Properties > Compatibility), "
                    "or your distro's wine package")


def win_path(p):
    return "Z:" + p.replace("/", "\\") + ("\\" if os.path.isdir(p) else "")


def seed_prefix(seed, prefix):
    """Copy Proton's ready-made prefix like Proton does: its relative links into Proton's DLLs become
    absolute (the sandbox mounts Proton at the same path), and the C: and Z: drives are added."""
    shutil.copytree(seed, prefix, symlinks=True, dirs_exist_ok=True)
    seed_real = os.path.realpath(seed)
    for dp, dn, fn in os.walk(prefix):
        for f in dn + fn:
            p = os.path.join(dp, f)
            if not os.path.islink(p):
                continue
            t = os.readlink(p)
            if os.path.isabs(t):
                continue
            src = os.path.join(seed_real, os.path.relpath(dp, prefix))
            real = os.path.normpath(os.path.join(src, t))
            if not real.startswith(seed_real + os.sep):          # one of Proton's DLLs: absolute link
                os.remove(p)                                     # (Proton does the same)
                os.symlink(real, p)
    dosdev = os.path.join(prefix, "dosdevices")
    os.makedirs(dosdev, exist_ok=True)
    for drive, target in (("c:", "../drive_c"), ("z:", "/")):  # Proton's script adds these at launch
        if not os.path.lexists(os.path.join(dosdev, drive)):
            os.symlink(target, os.path.join(dosdev, drive))


def ready_prefix(wine, prefix, log=lambda *a: None):
    """FOLM's installer prefix, up to date for this Wine. Wine rebuilds a prefix whose .update-timestamp
    doesn't match its wine.inf (10+ minutes on a slow PC); Proton ships an already-built one, so copy that
    and stamp it instead. The prefix holds nothing of the player's: re-making it loses nothing."""
    files = os.path.dirname(os.path.dirname(wine))
    seed = os.path.join(files, "share", "default_pfx")
    inf = os.path.join(files, "share", "wine", "wine.inf")
    if not (os.path.isdir(seed) and os.path.exists(inf)):
        os.makedirs(prefix, exist_ok=True)                   # system wine: let it build its own
        return
    want = str(int(os.stat(inf).st_mtime))
    stamp = os.path.join(prefix, ".update-timestamp")
    try:
        with open(stamp) as fh:
            have = fh.read().strip()
    except OSError:
        have = None
    if have == want and os.path.isdir(os.path.join(prefix, "drive_c")):
        return
    log("  preparing FOLM's Wine setup for installers" + (" (Proton was updated)" if have else ""))
    if os.path.isdir(prefix):
        shutil.rmtree(prefix)
    seed_prefix(seed, prefix)
    with open(stamp, "w") as fh:
        fh.write(want + "\n")


# ---------------------------------------------------------------- choosing what to run

def find_exes(folder):
    """Runnable .exe files in an unpacked download, best guess first."""
    found = []
    for dp, dn, fn in os.walk(folder):
        depth = os.path.relpath(dp, folder).count(os.sep) + (0 if dp == folder else 1)
        if depth > 2:
            dn[:] = []
            continue
        for f in fn:
            if f.lower().endswith(".exe") and not SKIP_EXE.search(f):
                score = (2 if GOOD_EXE.search(f) else 0) - depth
                found.append((score, os.path.join(dp, f)))
    found.sort(key=lambda x: (-x[0], x[1].lower()))
    return [p for _, p in found]


def runs_in_game_folder(exe, kind):
    """Patchers are made to sit in the game folder ("extract to the main game folder and run Patcher.exe");
    installers with their own path fields (TTW, decompressors, ESM fixers) run from their own folder."""
    return kind != "ttw-installer" and bool(re.search(r"patch", os.path.basename(exe), re.I)) \
        and not re.search(r"esm", os.path.basename(exe), re.I)


# ---------------------------------------------------------------- sandbox

def _esc(p):
    return p.replace("\\", "\\\\").replace(",", "\\,").replace(":", "\\:")


def sandbox_cmd(script, game_dir, upper, work, binds_rw, binds_ro):
    """unshare (user + mount namespace) mounts the game folder copy-on-write, then bubblewrap runs `script`."""
    bw = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session",
          "--ro-bind", "/usr", "/usr", "--ro-bind", "/etc", "/etc",
          "--proc", "/proc", "--dev", "/dev", "--dev-bind-try", "/dev/dri", "/dev/dri",
          "--tmpfs", "/tmp", "--tmpfs", "/home", "--tmpfs", "/run"]
    for d in ("/bin", "/sbin", "/lib", "/lib64", "/lib32", "/libx32"):
        if os.path.islink(d):
            bw += ["--symlink", os.readlink(d), d]
        elif os.path.isdir(d):
            bw += ["--ro-bind", d, d]
    for d in ("/opt", "/var/lib/flatpak"):
        if os.path.isdir(d):
            bw += ["--ro-bind", d, d]
    if os.path.isdir("/tmp/.X11-unix"):
        bw += ["--ro-bind", "/tmp/.X11-unix", "/tmp/.X11-unix"]
    xauth = os.environ.get("XAUTHORITY") or os.path.expanduser("~/.Xauthority")
    if os.path.exists(xauth):
        bw += ["--ro-bind", xauth, "/tmp/.Xauthority", "--setenv", "XAUTHORITY", "/tmp/.Xauthority"]
    for p in binds_ro:
        bw += ["--ro-bind", p, p]
    for p in binds_rw + [game_dir]:
        bw += ["--bind", p, p]
    bw += ["--setenv", "HOME", "/tmp", "--setenv", "DISPLAY", os.environ.get("DISPLAY", ":0"),
           "--setenv", "WINEDEBUG", "-all,err+module", "sh", script]
    opts = f"lowerdir={_esc(game_dir)},upperdir={_esc(upper)},workdir={_esc(work)}"
    mount = 'mount -t overlay overlay -o "$1" "$2" && shift 2 && exec "$@"'
    return ["unshare", "-rm", "--", "sh", "-c", mount, "sh", opts, game_dir] + bw


def available():
    """None if the sandbox can run here, else why not."""
    for t in ("unshare", "bwrap"):
        if not shutil.which(t):
            return f"{t} is needed to run Windows installers safely (packages: util-linux, bubblewrap)"
    return None


# ---------------------------------------------------------------- run + collect

def run(exe, tool_dir, job, game_dir, other_games, prefix, wine, proton_dir, args=(), in_game_folder=False,
        registry=None, log=lambda *a: None):
    """Run `exe` sandboxed. Returns the job's capture dirs: {"upper", "output", "tool_files"}."""
    why = available()
    if why:
        raise ToolError(why)
    upper, work, output = (os.path.join(job, d) for d in ("upper", "work", "output"))
    for d in (upper, work, output):
        os.makedirs(d, exist_ok=True)
    ready_prefix(wine, prefix, log)

    tool_files = set()
    run_dir = os.path.dirname(exe)
    if in_game_folder:                       # place the tool in the game folder (its upper layer) by hard link
        for dp, _, fn in os.walk(tool_dir):
            for f in fn:
                src = os.path.join(dp, f)
                rel = os.path.relpath(src, tool_dir)
                dst = os.path.join(upper, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                try:
                    os.link(src, dst)
                except OSError:
                    shutil.copy2(src, dst)
                tool_files.add(rel)
        run_dir = os.path.join(game_dir, os.path.relpath(os.path.dirname(exe), tool_dir))
        exe = os.path.join(game_dir, os.path.relpath(exe, tool_dir))

    # drive O: = FOLM output
    dosdev = os.path.join(prefix, "dosdevices")
    os.makedirs(dosdev, exist_ok=True)
    o_drive = os.path.join(dosdev, "o:")
    if os.path.lexists(o_drive):
        os.remove(o_drive)
    os.symlink(output, o_drive)

    wineserver = os.path.join(os.path.dirname(wine), "wineserver")
    lines = ["#!/bin/sh", f"export WINEPREFIX={shlex.quote(prefix)}", f"cd {shlex.quote(run_dir)}"]
    for key, path in (registry or {}).items():
        lines.append(f"{shlex.quote(wine)} reg add {shlex.quote(key)} /v 'Installed Path' /d "
                     f"{shlex.quote(win_path(path))} /f /reg:32 >/dev/null 2>&1")
    lines.append(" ".join(shlex.quote(x) for x in [wine, exe, *args]))
    lines.append("rc=$?")
    if os.path.exists(wineserver):
        lines.append(f"{shlex.quote(wineserver)} -w")       # an installer that hands off to a child process
    lines.append("exit $rc")
    script = os.path.join(job, "run.sh")
    with open(script, "w") as fh:
        fh.write("\n".join(lines) + "\n")

    ro = [p for p in other_games if os.path.isdir(p)] + ([proton_dir] if proton_dir else [])
    rw = [prefix, job] + ([tool_dir] if not in_game_folder else [])
    cmd = sandbox_cmd(script, game_dir, upper, work, rw, ro)
    log(f"  running {os.path.basename(exe)} with Wine (sandboxed: no network; your game folder is protected)")
    started = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    try:
        os.remove(o_drive)
    except OSError:
        pass
    shutil.rmtree(work, ignore_errors=True)
    err = (r.stderr or "").strip()
    if r.returncode != 0 and ("mount" in err.lower() or "bwrap:" in err):
        raise ToolError("couldn't set up the sandbox: " + err.splitlines()[-1][:300])
    log(f"  {os.path.basename(exe)} finished after {int(time.time() - started)} s (exit code {r.returncode})")
    tail = [l for l in (r.stderr or "").splitlines() + (r.stdout or "").splitlines() if l.strip()][-8:]
    if r.returncode not in (0,) and tail:
        log("  Wine said: " + " | ".join(tail)[:600])
    return {"upper": upper, "output": output, "tool_files": tool_files, "exit": r.returncode, "messages": tail}


def _is_whiteout(path):
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISCHR(st.st_mode) and st.st_rdev == 0


def collect(cap, game_dir, dest, log=lambda *a: None):
    """Turn what the tool wrote into a mod folder at `dest`. Returns {"files", "deleted", "unchanged"}."""
    files, deleted, unchanged = 0, [], 0
    root_dir = os.path.join(dest, dep.ROOT_DIR)

    def put(src, rel_data=None, rel_root=None):
        nonlocal files
        target = os.path.join(dest, rel_data) if rel_data is not None else os.path.join(root_dir, rel_root)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.move(src, target)
        files += 1

    upper = cap["upper"]
    for dp, _, fn in os.walk(upper):
        for f in fn:
            src = os.path.join(dp, f)
            rel = os.path.relpath(src, upper)
            if _is_whiteout(src):
                deleted.append(rel)
                continue
            if rel in cap["tool_files"]:
                continue                                 # the tool's own files, placed there to run it
            orig = os.path.join(game_dir, rel)
            if os.path.isfile(orig) and os.path.getsize(orig) == os.path.getsize(src) \
                    and filecmp.cmp(orig, src, shallow=False):
                unchanged += 1                           # rewritten with the same contents
                continue
            parts = rel.split(os.sep, 1)
            if parts[0].lower() == "data" and len(parts) == 2:
                put(src, rel_data=parts[1])
            elif not f.lower().endswith((".log",)) or os.sep in rel:
                put(src, rel_root=rel)

    out = cap["output"]
    if os.path.isdir(out) and os.listdir(out):
        top = {e.lower(): e for e in os.listdir(out)}
        mirror = "data" in top and os.path.isdir(os.path.join(out, top["data"]))
        for dp, _, fn in os.walk(out):
            for f in fn:
                src = os.path.join(dp, f)
                rel = os.path.relpath(src, out)
                parts = rel.split(os.sep, 1)
                if mirror and parts[0].lower() == "data" and len(parts) == 2:
                    put(src, rel_data=parts[1])
                elif mirror:
                    put(src, rel_root=rel)
                else:
                    put(src, rel_data=rel)
    return {"files": files, "deleted": sorted(deleted), "unchanged": unchanged}
