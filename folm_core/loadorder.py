"""loadorder - apply a plugin load order the way FO3/FNV read it.

These old engines decide load order from each plugin file's *modified time*
(oldest first), and read plugins.txt only to know which plugins are active.
So FOLM sets the timestamps itself and writes plugins.txt, remembering the
original times so undo can restore them.
"""

import json
import os
import shutil
import time

from .plugins import PluginError, read_header, sort_plugins

BASE_TIME = time.mktime((2008, 10, 1, 12, 0, 0, 0, 0, -1))   # a fixed, old start date
STEP = 60                                                    # one minute apart
# Archives are redated to this, so any loose file counts as newer and wins
# (the engine only lets a loose file replace an archive's copy if it's newer).
BSA_TIME = int(time.mktime((2006, 1, 1, 12, 0, 0, 0, 0, -1)) * 1e9)


def scan_plugins(data_dir):
    out, bad = {}, []
    for f in os.listdir(data_dir):
        if f.lower().endswith((".esm", ".esp")):
            try:
                out[f] = read_header(os.path.join(data_dir, f))
            except (PluginError, OSError) as e:
                bad.append(str(e))
    return out, bad


def apply(data_dir, plugins_txt, preferred, disabled, edition, state_path, log=print, rules=None):
    """rules: optional (extra_after, group_rank) from LOOT."""
    plugins, bad = scan_plugins(data_dir)
    extra_after, group_rank = rules or ({}, {})
    order, problems = sort_plugins(plugins, preferred, edition, extra_after, group_rank)
    state = {"mtimes": {}, "plugins_txt_backup": None}
    if os.path.exists(state_path):
        with open(state_path) as fh:
            state = json.load(fh)

    for i, name in enumerate(order):
        p = os.path.join(data_dir, name)
        state["mtimes"].setdefault(p, os.stat(p).st_mtime_ns)   # exact, in nanoseconds
        t = int((BASE_TIME + i * STEP) * 1e9)
        os.utime(p, ns=(t, t))

    bsas = [f for f in os.listdir(data_dir) if f.lower().endswith(".bsa")]
    for f in bsas:
        p = os.path.join(data_dir, f)
        state["mtimes"].setdefault(p, os.stat(p).st_mtime_ns)
        os.utime(p, ns=(BSA_TIME, BSA_TIME))

    os.makedirs(os.path.dirname(plugins_txt), exist_ok=True)
    if os.path.exists(plugins_txt) and not state.get("plugins_txt_backup"):
        bak = plugins_txt + ".folm-backup"
        shutil.copy2(plugins_txt, bak)
        state["plugins_txt_backup"] = bak
    dis = {d.lower() for d in disabled}
    active = [n for n in order if n.lower() not in dis]
    with open(plugins_txt, "w", newline="\r\n") as fh:
        fh.write("\n".join(active) + "\n")

    with open(state_path, "w") as fh:
        json.dump(state, fh, indent=1)
    for msg in bad + problems:
        log(f"  ! {msg}")
    return order, active, problems


def restore(plugins_txt, state_path, log=print):
    if not os.path.exists(state_path):
        return
    with open(state_path) as fh:
        state = json.load(fh)
    n = 0
    for p, t in state["mtimes"].items():
        if os.path.exists(p):
            os.utime(p, ns=(t, t))
            n += 1
    bak = state.get("plugins_txt_backup")
    if bak and os.path.exists(bak):
        shutil.move(bak, plugins_txt)
    elif os.path.exists(plugins_txt):
        os.remove(plugins_txt)
    os.remove(state_path)
    log(f"Load order restored: {n} plugin/archive timestamps reset, plugins.txt put back.")
