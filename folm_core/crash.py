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

def start(m):
    """Begin a play session: snapshot the setup. Returns the session folder."""
    d = os.path.join(m.dir, "sessions", time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(d, exist_ok=True)
    try:
        rows, problems = m.plugin_order()
        loot = getattr(m, "last_loot_messages", [])
    except Exception as e:
        rows, problems, loot = [], [f"couldn't read load order: {e}"], []
    snap = {"started": time.time(), "edition": m.edition, "game": m.data.get("game"),
            "game_dir": m.data["game_dir"], "profile": m.active,
            "mods": [{"name": x["name"], "enabled": x["enabled"], "type": x.get("type")} for x in m.mods()],
            "plugins": [{"name": n, "active": on, "index": i} for n, on, i, _ in rows],
            "load_order_problems": problems, "loot": loot, "system": system_info()}
    with open(os.path.join(d, "session.json"), "w") as fh:
        json.dump(snap, fh, indent=1)
    return d


def watch(session, interval=5, wait_for_start=180, stop=None):
    """Log memory while the game runs. Returns when the game exits (or never started)."""
    log = os.path.join(session, "memory.log")
    seen, t0 = False, time.time()
    with open(log, "a") as fh:
        while True:
            if stop and stop():
                break
            pid = game_pid()
            m = _mem()
            fh.write(f"{time.strftime('%H:%M:%S')} avail={m['MemAvailable']} swapfree={m['SwapFree']} "
                     f"game={'up' if pid else 'down'}\n")
            fh.flush()
            os.fsync(fh.fileno())
            if pid:
                seen = True
            elif seen or time.time() - t0 > wait_for_start:
                break
            time.sleep(interval)
    return seen


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
        names = {re.split(r"\bfrom\b|:", x)[-1].strip() for x in re.findall(r"([\w .'-]+\.(?:dll|esp|esm))", body, re.I)}
        mods = sorted(names -
                      {"FalloutNV.exe", "ntdll.dll", "kernel32.dll", "kernelbase.dll"}, key=str.lower)
        findings.append("The game crashed (the crash logger wrote a report)" +
                        (f": {exc.group(1).strip()}" if exc else "."))
        if mods:
            findings.append("Files named in the crash log (often the cause or closely involved): "
                            + ", ".join(mods[:8]))

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
