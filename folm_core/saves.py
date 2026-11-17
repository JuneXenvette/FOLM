"""saves - read the plugin list stored in Fallout 3 / New Vegas save files.

Each .fos save records which plugins were loaded when it was made: a count byte,
'|', then for each plugin a 2-byte length, '|', the name, '|'. If a save needs a
plugin that's no longer active, loading it can break quests and scripts, so FOLM
warns before that happens.
"""

import os
import re
import struct

MAGIC = (b"FO3SAVEGAME", b"FO4_SAVEGAME")


def plugins_in_save(path, scan_limit=8_000_000):
    """Return the save's plugin list (in its load order), or None if it can't be read."""
    try:
        with open(path, "rb") as fh:
            b = fh.read(scan_limit)
    except OSError:
        return None
    if not b.startswith(MAGIC[0]):
        return None
    first = re.search(rb"\.es[mp]\|", b)
    if not first:
        return None
    # the list starts shortly before the first plugin name; try each candidate start
    for p in range(max(0, first.start() - 300), first.start()):
        if b[p + 1:p + 2] != b"|" or b[p + 4:p + 5] != b"|":
            continue
        count, q, names = b[p], p + 2, []
        for _ in range(count):
            if q + 3 > len(b):
                break
            (n,) = struct.unpack_from("<H", b, q)
            if b[q + 2:q + 3] != b"|":
                break
            name = b[q + 3:q + 3 + n]
            if not name.lower().endswith((b".esm", b".esp")) or b[q + 3 + n:q + 4 + n] != b"|":
                break
            names.append(name.decode("cp1252", "replace"))
            q += 4 + n
        if count and len(names) == count:
            return names
    return None


def list_saves(folder):
    """Saves in a folder, newest first: [(path, mtime)]."""
    if not os.path.isdir(folder):
        return []
    out = [(os.path.join(folder, f), os.path.getmtime(os.path.join(folder, f)))
           for f in os.listdir(folder) if f.lower().endswith(".fos")]
    return sorted(out, key=lambda x: -x[1])


def missing_for(save_plugins, active):
    """Plugins the save needs that won't be active."""
    act = {a.lower() for a in active}
    return [p for p in save_plugins if p.lower() not in act]


def check(folder, active, newest=3):
    """[(save name, [missing plugins])] for the newest saves that would lose plugins."""
    problems = []
    for path, _ in list_saves(folder)[:newest]:
        plugins = plugins_in_save(path)
        if plugins is None:
            continue
        miss = missing_for(plugins, active)
        if miss:
            problems.append((os.path.basename(path), miss))
    return problems
