"""crash - crash reports for games launched with FOLM, and for FOLM itself.

A play session:
  start(manager)  snapshot the setup (mods, load order, LOOT, system) into a session folder
  watch(session)  log memory every few seconds (fsync'd, survives a freeze) while the game runs
  finish(session) when the game exits: decide whether it crashed, diagnose, write report.txt

Reports stay on the player's PC. Usernames and home-folder paths are redacted.
"""

import getpass
import json
import os
import re
import subprocess
import time
import traceback

HOME = os.path.expanduser("~")
USER = getpass.getuser()


def redact(text):
    text = text.replace(HOME, "~")
    text = re.sub(rf"\b{re.escape(USER)}\b", "<user>", text) if len(USER) > 2 else text
    return text


def _read(path, limit=200_000):
    try:
        with open(path, errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def _mem():
    d = {}
    for l in open("/proc/meminfo"):
        k, v = l.split(":")
        d[k] = int(v.split()[0]) // 1024
    return d


def _proc_mem(pid):
    """{"VmRSS", "VmSize"} in MB for a process: the RAM it uses and how much of its address space is in
    use (for the 32-bit game, the number that runs out at 4 GB). {} if it's gone."""
    d = {}
    try:
        for l in open(f"/proc/{pid}/status"):
            k, _, v = l.partition(":")
            if k in ("VmRSS", "VmSize"):
                d[k] = int(v.split()[0]) // 1024
    except (OSError, ValueError):
        return {}
    return d if len(d) == 2 else {}


def game_pid(exe_name="falloutnv.exe"):
    """The running game's PID. Wine renames the process ('Main'), so match the command line."""
    out = subprocess.run(["ps", "-eo", "pid=,comm=,args="], capture_output=True, text=True).stdout
    for l in out.splitlines():
        parts = l.split(None, 2)
        if len(parts) == 3 and parts[2].rstrip().lower().endswith(exe_name) and "steam.exe" not in parts[1]:
            return int(parts[0])
    return None


def system_info():
    info = {}
    try:
        info["kernel"] = os.uname().release
        m = _mem()
        info["ram_mb"], info["swap_mb"] = m["MemTotal"], m["SwapTotal"]
        gpu = subprocess.run(["lspci"], capture_output=True, text=True).stdout
        info["gpu"] = [l.split(": ", 1)[-1] for l in gpu.splitlines() if re.search(r"VGA|3D|Display", l)]
        info["earlyoom"] = subprocess.run(["systemctl", "is-active", "earlyoom"], capture_output=True,
                                          text=True).stdout.strip()
    except Exception as e:
        info["error"] = str(e)
    return info


# ---------------------------------------------------------------- session

def _save_dir(m):
    try:
        return m.save_dir()
    except Exception:
        return None


def start(m):
    """Begin a play session: snapshot the setup. Returns the session folder."""
    d = os.path.join(m.dir, "sessions", time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(d, exist_ok=True)
    try:
        rows, problems = m.plugin_order()
        loot = getattr(m, "last_loot_messages", [])
    except Exception as e:
        rows, problems, loot = [], [f"couldn't read load order: {e}"], []
    from .manager import game_info, home
    snap = {"started": time.time(), "edition": m.edition, "game": m.data.get("game"),
            "exe": game_info(m.edition).get("exe", "FalloutNV.exe"), "home": home(),
            "game_dir": m.data["game_dir"], "profile": m.active,
            "data_dir": m.data_dir, "save_dir": _save_dir(m),
            "mods": [{"name": x["name"], "enabled": x["enabled"], "type": x.get("type")} for x in m.mods()],
            "plugins": [{"name": n, "active": on, "index": i} for n, on, i, _ in rows],
            "load_order_problems": problems, "loot": loot, "system": system_info()}
    with open(os.path.join(d, "session.json"), "w") as fh:
        json.dump(snap, fh, indent=1)
    return d


def watch(session, interval=5, wait_for_start=180, stop=None, gauge=True):
    """Log memory while the game runs. Returns when the game exits (or never started).

    Each line: the PC's free RAM and swap, and while the game runs its RAM use (game_ram) and, from the
    memory gauge (memwatch), how full its 4 GB is (used / free / largest free block, in MB). Warns on
    the desktop once when the 4 GB is nearly full, and again when it's about to run out."""
    from . import memwatch
    snap = json.load(open(os.path.join(session, "session.json")))
    exe = snap.get("exe") or "FalloutNV.exe"
    log = os.path.join(session, "memory.log")
    seen, t0, g, warned, saver = False, time.time(), None, "ok", None
    try:
        with open(log, "a") as fh:
            while True:
                if stop and stop():
                    break
                pid = game_pid(exe.lower())
                if pid and gauge and g is None:
                    g = memwatch.Gauge(snap.get("home") or os.path.dirname(os.path.dirname(os.path.dirname(session))),
                                       exe, interval)
                    if not g.start(pid):
                        fh.write(f"# memory gauge off: {g.problem}\n")
                m = _mem()
                r = _proc_mem(pid) if pid else {}
                line = (f"{time.strftime('%H:%M:%S')} avail={m['MemAvailable']} swapfree={m['SwapFree']} "
                        f"game={'up' if pid else 'down'}" + (f" game_ram={r['VmRSS']}" if r else ""))
                s = g.latest if (g and pid) else {}
                if s:
                    line += "".join(f" {k}={s[k]}" for k in memwatch.FIELDS)
                    lv = memwatch.level(s)
                    if lv != "ok" and (warned, lv) in (("ok", "warn"), ("ok", "critical"), ("warn", "critical")):
                        warned = lv
                        saver = saver or _ask_game_to_save(snap, fh)
                        memwatch.notify(
                            "Game memory nearly full" if lv == "warn" else "Game about to run out of memory",
                            f"{s['used']} of 4096 MB used, {s['free']} MB free. "
                            + (("FOLM is saving your game for you (a new save, your others stay as they are). "
                                if saver and lv == "warn" else "")
                               + ("Restart the game when it suits you." if saver and lv == "warn" else
                                  "Save soon, then restart the game when it suits you." if lv == "warn" else
                                  "Save NOW and restart the game.")), critical=lv == "critical")
                        line += f" warned={lv}"
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
                if pid:
                    seen = True
                elif seen or (time.time() - t0 > wait_for_start
                              and not (time.time() - t0 < 1800 and _launching(snap.get("game_dir")))):
                    break                       # the game ended, or never started (no launch on its way)
                time.sleep(interval)
    finally:
        if g:
            g.stop()
        if saver:
            saver.stop()
    return seen


def _launching(game_dir):
    """True while Steam is still starting this game: Proton's launch of something in the game's folder
    is running (its launcher, waiting for you to press Play there). The game itself starts later."""
    if not game_dir:
        return False
    out = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True).stdout
    for l in out.splitlines():
        pid, _, args = l.strip().partition(" ")
        if pid != str(os.getpid()) and re.search(r"/proton\s+waitforexitandrun\s+'?" + re.escape(game_dir), args):
            return True
    return False


def _ask_game_to_save(snap, log_fh):
    """The first memory warning: have the game save itself (see lowmemsave). None if it can't here."""
    from . import lowmemsave, memwatch
    data, saves = snap.get("data_dir"), snap.get("save_dir")
    if not data or not saves or not lowmemsave.installed(data):
        return None

    def note(text):
        try:
            log_fh.write(text + "\n")
        except ValueError:                                   # the session already ended
            pass

    def done(sv):
        if sv.result:
            note(f"# low-memory save: {sv.result}")
            memwatch.notify("FOLM saved your game", f"Saved as {sv.result}. Restart the game when it suits you.")
        elif sv.problem:
            note(f"# low-memory save: not made ({sv.problem})")
            memwatch.notify("Game memory nearly full", "FOLM couldn't save for you: please save now.",
                            critical=True)
    sv = lowmemsave.Saver(data, saves, on_done=done)
    try:
        sv.start()
    except OSError as e:
        log_fh.write(f"# low-memory save: couldn't ask the game ({e})\n")
        return None
    log_fh.write("# low-memory save: asked the game to save\n")
    return sv


# ---------------------------------------------------------------- diagnosis

def _crash_logger_text(game_dir, since):
    """Yvile's / Cobb crash logger output written during this session, if any."""
    found = []
    for root in (game_dir, os.path.join(game_dir, "Crash Logs"), os.path.join(game_dir, "crashlogs")):
        if not os.path.isdir(root):
            continue
        for f in os.listdir(root):
            p = os.path.join(root, f)
            if "crash" in f.lower() and os.path.isfile(p) and os.path.getmtime(p) >= since - 5:
                body = _read(p)
                lines = [l for l in body.splitlines() if l.strip()]
                # an untouched log is just its 2-line header ("If this file is empty...")
                if len(lines) > 2 or "exception" in body.lower():
                    found.append((p, body))
    return found


SYSTEM_DLL = re.compile(r"^(?:ntdll|kernel32|kernelbase|ucrtbase|msvcrt|msvcp\d+.*|vcruntime\d+.*|user32|gdi32|win32u)\.dll$", re.I)


def _named_in_crash(body):
    """Mod files the crash itself points at: the call trace and the "crashed in module" line, not the
    logger's list of every DLL that was loaded (that list is in every crash log and names nothing)."""
    crash = re.split(r"LISTING MODULE BASES", body)[0]
    crash += "\n".join(re.findall(r"CRASHED AT INSTRUCTION[^\n]*", body))
    names = set()
    for x in re.findall(r"([\w .'()-]+\.(?:dll|esp|esm))\b", crash, re.I):
        n = re.split(r"[\\/:]|\bfrom\b|\bin\b", x)[-1].strip()
        if n and not SYSTEM_DLL.match(n):
            names.add(n)
    return sorted(names, key=str.lower)


def _out_of_memory(game_dir, since, crash_bodies):
    """True when the game ran out of memory: NVHR (the game's memory manager) logged a failed allocation
    this session, or the crash logger says EXCEPTION_OUT_OF_MEMORY / "out of memory"."""
    hr = os.path.join(game_dir, "hr.log")
    if os.path.exists(hr) and os.path.getmtime(hr) >= since - 5 and re.search(r"returned NULL", _read(hr, 2_000_000)):
        return True
    return any(re.search(r"OUT_OF_MEMORY|out of memory", b, re.I) for b in crash_bodies)


def heap_log(game_dir, since):
    """What Second Wind's NVHR saw (secondwind-heap.log in the game folder), or (None, None).
    Returns (finding, evidence): finding names the request that failed, if one did (or, with v3, how many
    its reserve caught); evidence is the failed requests, the reserve's catches, the blocks v4 gave back,
    the last summary lines, v4's "game exited" line, the last per-pool breakdown and the last map of who
    holds the 4 GB."""
    path = os.path.join(game_dir, "secondwind-heap.log")
    if not os.path.exists(path) or os.path.getmtime(path) < since - 5:
        return None, None
    lines = _read(path, 4_000_000).splitlines()
    failed = [x for x in lines if " FAILED alloc " in x]
    reserve = [x for x in lines if " RESERVE: " in x]       # v3: big requests its reserve caught
    gave = [x for x in lines if " GAVE BACK: " in x]        # v4: empty dheap blocks handed back
    exited = [x for x in lines if " game exited after " in x]   # v4: the game quit (no hard crash)
    summary = [x for x in lines if " min=" in x]
    where, block = [], []
    for x in lines:                                      # v3: the last map of who holds the 4 GB
        if " map (" in x:
            block = [x]
        elif block and x[8:].startswith("  "):
            block.append(x)
        elif block:
            where, block = block, []
    where = block or where
    pools, block = [], []
    for x in lines:                                      # the last per-pool block (lines starting "  pool")
        if "   pool " in x or x[8:].startswith("  pool "):
            block.append(x)
        elif block:
            pools, block = block, []
    pools = block or pools
    finding = None
    m = re.search(r"FAILED alloc of ([\d.]+) MB .*?largest free gap ([\d.]+) MB, free in total ([\d.]+) MB",
                  failed[0]) if failed else None
    if m:
        finding = (f"The game asked for {m.group(1)} MB in one piece, and the largest free gap in its 4 GB was "
                   f"{m.group(2)} MB ({m.group(3)} MB free in all, but in small pieces). Measured by Second "
                   "Wind's measuring NVHR.")
    if reserve and not finding:
        finding = (f"Second Wind's reserve caught {len(reserve)} big memory request(s) that would have crashed "
                   "the game with NVHR 4.3 (no gap big enough left in its 4 GB)"
                   + (". The game then quit normally." if exited else ", so the crash was something else."))
    evidence = "\n".join(failed[:10] + (["..."] if len(failed) > 10 else []) + reserve[:5]
                         + (["..."] if len(reserve) > 5 else []) + gave[:5] + (["..."] if len(gave) > 5 else [])
                         + summary[-3:] + exited[-1:] + pools + where)
    return finding, evidence or None


def memory_gauge(mem_log):
    """The memory gauge's story of a session, from memory.log: {"summary": text, "last_used", "last_free"},
    or None when the gauge didn't run. The summary says how full the game's 4 GB got and how fast, with a
    line every 10 minutes, so a jump (entering DC, a big fight) shows."""
    rows = re.findall(r"^(\d\d:\d\d:\d\d) .*? used=(\d+) commit=(\d+) reserve=\d+ free=(\d+) largest=\d+ "
                      r"image=(\d+) mapped=(\d+) private=\d+", mem_log, re.M)
    if not rows:
        return None
    rows = [(t, *map(int, x)) for t, *x in rows]              # t, used, commit, free, image, mapped
    peak = max(rows, key=lambda r: r[2])
    lines = [f"Fullest: {peak[2]} of 4096 MB in use at {peak[0]}, so {4096 - peak[2]} MB of room left "
             f"(programs and DLLs {peak[4]} MB, graphics and mapped files {peak[5]} MB). Reserved in all, "
             f"in use or set aside by the game's heap: {peak[1]} MB.",
             "Over time (in use / room left, MB):"]
    last_min = None
    for t, _used, commit, *_ in rows:
        h, mnt, _s = (int(x) for x in t.split(":"))
        slot = (h * 60 + mnt) // 10
        if slot != last_min:
            last_min = slot
            lines.append(f"  {t}  {commit} / {4096 - commit}")
    t, used, commit, free, *_ = rows[-1]
    lines.append(f"  {t}  {commit} / {4096 - commit}  (last)")
    gauge_off = re.findall(r"^# memory gauge off: (.*)$", mem_log, re.M)
    return {"summary": "\n".join(lines), "last_used": commit, "last_room": 4096 - commit, "off": gauge_off}


def _earlyoom_kills(since):
    out = subprocess.run(["journalctl", "-u", "earlyoom", "--since", f"@{int(since)}", "--no-pager", "-q"],
                         capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if re.search(r"sending SIG(TERM|KILL) to process", l)]


def diagnose(session, game_dir):
    """Return (crashed: bool, findings: [str], evidence: {name: text})."""
    snap = json.load(open(os.path.join(session, "session.json")))
    since = snap["started"]
    findings, evidence, crashed = [], {}, False

    for path, body in _crash_logger_text(game_dir, since):
        crashed = True
        evidence[os.path.basename(path)] = body
        exc = re.search(r"(Exception[^\n]{0,120}|EXCEPTION_[A-Z_]+)", body)
        mods = _named_in_crash(body)
        findings.append("The game crashed (the crash logger wrote a report)" +
                        (f": {exc.group(1).strip()}" if exc else "."))
        if mods:
            findings.append("Files named in the crash log (often the cause or closely involved): "
                            + ", ".join(mods[:8]))

    bodies = [b for b in evidence.values()]
    if _out_of_memory(game_dir, since, bodies):
        crashed = True
        findings.insert(0, "The game ran out of memory. New Vegas and Fallout 3 are 32-bit programs: they can "
                        "use at most 4 GB, however much RAM your PC has, so this isn't fixed by closing other "
                        "apps. Use less: a smaller texture pack (e.g. MEDIUM instead of LARGE), LOD made with "
                        "smaller textures, fewer physics or shader mods.")
        hr = _read(os.path.join(game_dir, "hr.log"), 2_000_000)
        if hr:
            evidence["hr.log (end)"] = "\n".join(hr.splitlines()[-5:])
    sw_finding, sw_evidence = heap_log(game_dir, since)
    # v4 writes "game exited after N min" when the game quits through Windows' normal exit: then the
    # reserve catching requests is good news, not a crash (a crash logger's report still counts)
    quit_ok = bool(sw_evidence) and " game exited after " in sw_evidence and " FAILED alloc " not in sw_evidence
    if sw_finding and not quit_ok:
        crashed = True
        findings.insert(1 if findings and findings[0].startswith("The game ran out of memory") else 0, sw_finding)
    if sw_evidence:
        evidence["secondwind-heap.log"] = sw_evidence

    kills = _earlyoom_kills(since)
    if kills:
        crashed = True
        findings.append("Out of memory: earlyoom closed a program to keep the PC responsive. "
                        "Close other apps (browsers, chat) before playing, or add more swap.")
        evidence["earlyoom"] = "\n".join(kills)

    mem = _read(os.path.join(session, "memory.log"))
    rows = re.findall(r"avail=(\d+) swapfree=(\d+) game=(\w+)", mem)
    if rows:
        lo_avail = min(int(a) for a, _, g in rows)
        lo_swap = min(int(s) for _, s, g in rows)
        total = snap["system"].get("ram_mb") or 1
        if lo_avail < total * 0.06 and lo_swap < 200:
            findings.append(f"Memory got critically low ({lo_avail} MB free, {lo_swap} MB swap free): "
                            "a likely cause of freezes and crashes on this PC.")
        evidence["memory (lowest)"] = f"free RAM {lo_avail} MB, free swap {lo_swap} MB"
        ram = [int(r) for r in re.findall(r"game_ram=(\d+)", mem)]
        if ram:
            evidence["memory (lowest)"] += f"; the game used up to {max(ram)} MB of RAM"
        gauge = memory_gauge(mem)
        off = re.findall(r"^# memory gauge off: (.*)$", mem, re.M)
        if not gauge and off:
            evidence["game memory (its 4 GB)"] = "The memory gauge was off: " + off[0]
        saved = re.findall(r"^# low-memory save: (FOLM_LowMemory\S+)$", mem, re.M)
        if saved:
            findings.append(f"FOLM saved your game when memory ran low: load \"{saved[-1]}\" to go on from there.")
        if gauge:
            evidence["game memory (its 4 GB)"] = gauge["summary"]
            if gauge["last_room"] < 600 and not any(f.startswith("The game ran out of memory") for f in findings):
                findings.insert(0, f"The game's 4 GB was nearly full ({gauge['last_used']} MB in use, "
                                f"{gauge['last_room']} MB left) when the log ended: most likely it ran out of "
                                "memory. Use less: a smaller texture pack, LOD made with smaller textures, "
                                "fewer physics or shader mods.")
                crashed = crashed or rows[-1][2] == "up"
        last = rows[-1]
        if last[2] == "up":
            findings.append("The memory log ends while the game was still running: the PC may have "
                            "frozen or been restarted.")
            crashed = True

    nvse = _read(os.path.join(game_dir, "nvse.log"))
    if nvse:
        evidence["nvse.log"] = nvse[-6000:]
        bad = [l for l in nvse.splitlines() if re.search(r"(couldn't load|failed to load|reported as incompatible)", l, re.I)]
        if bad:
            findings.append("A script-extender plugin failed to load: " + "; ".join(b.strip()[:120] for b in bad[:3]))
    err = _read(os.path.join(game_dir, "falloutnv_error.log"))
    if err:
        evidence["falloutnv_error.log"] = err[-3000:]

    for p in snap.get("load_order_problems", []):
        findings.append(f"Load order problem at launch: {p}")
    for sev, plugin, text in snap.get("loot", []):
        if sev == "error":
            findings.append(f"LOOT error at launch: {plugin + ': ' if plugin else ''}{text}")
    return crashed, findings, evidence


def write_report(session, game_dir, kind="game"):
    """Write report.txt into the session folder. Returns (path, crashed, findings)."""
    snap = json.load(open(os.path.join(session, "session.json")))
    crashed, findings, evidence = diagnose(session, game_dir)
    L = ["FOLM crash report", "=" * 17,
         f"Game: {snap['game']} ({snap['edition']}) | profile: {snap['profile']}",
         f"Session started: {time.ctime(snap['started'])} | report: {time.ctime()}",
         f"Result: {'CRASH / ABNORMAL EXIT' if crashed else 'no crash detected'}", "",
         "What FOLM found", "-" * 15]
    L += [f"* {f}" for f in findings] or ["* Nothing suspicious found."]
    s = snap["system"]
    L += ["", "System", "-" * 6, f"Kernel {s.get('kernel')} | RAM {s.get('ram_mb')} MB | swap {s.get('swap_mb')} MB | "
          f"earlyoom {s.get('earlyoom')}", "GPU: " + "; ".join(s.get("gpu", []))]
    L += ["", "Mods (in order)", "-" * 15]
    L += [f"  [{'x' if x['enabled'] else ' '}] {x['name']} ({x['type']})" for x in snap["mods"]]
    L += ["", "Plugins (load order)", "-" * 20]
    L += [f"  {format(p['index'], '02X') if p['active'] else '--'} {p['name']}" for p in snap["plugins"]]
    for name, body in evidence.items():
        L += ["", f"--- {name} ---", body.strip()]
    path = os.path.join(session, "report.txt")
    with open(path, "w") as fh:
        fh.write(redact("\n".join(L)) + "\n")
    return path, crashed, findings


def app_error_report(home, exc_type, exc, tb):
    """Write a report for an error in FOLM itself. Returns the file path."""
    d = os.path.join(home, "folm-errors")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, time.strftime("folm-error-%Y%m%d-%H%M%S.txt"))
    body = "FOLM error report\n=================\n" + time.ctime() + "\n\n" + \
           "".join(traceback.format_exception(exc_type, exc, tb))
    with open(path, "w") as fh:
        fh.write(redact(body))
    return path
