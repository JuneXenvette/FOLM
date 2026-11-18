"""ini - change single keys in game INI files and undo exactly.

Edits only the named keys; comments, spacing and every other line stay as they
were. set_keys() returns what each key held before (None = wasn't there), and
restore_keys() puts that back, so FOLM's INI changes are reversible like
everything else it does.
"""

import os


def _read(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read().splitlines()


def _write(path, lines):
    """Write the file; a read-only INI (a common way to stop the game's launcher rewriting it) is
    unlocked for the edit and locked again afterwards, so the player's protection stays."""
    import stat
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = os.stat(path).st_mode if os.path.exists(path) else None
    locked = mode is not None and not (mode & stat.S_IWUSR)
    if locked:
        os.chmod(path, mode | stat.S_IWUSR)
    try:
        with open(path, "w", encoding="utf-8", newline="\r\n") as fh:   # the game's INIs use Windows line endings
            fh.write("\n".join(lines).rstrip("\n") + "\n")
    finally:
        if locked:
            os.chmod(path, mode)


def _section_bounds(lines, section):
    """(start, end) line indexes of [section]'s body, or None."""
    start = None
    for i, l in enumerate(lines):
        t = l.strip()
        if t.startswith("[") and t.endswith("]"):
            if start is not None:
                return start, i
            if t[1:-1].strip().lower() == section.lower():
                start = i + 1
    return (start, len(lines)) if start is not None else None


def _find_key(lines, bounds, key):
    for i in range(*bounds):
        t = lines[i].strip()
        if t and not t.startswith((";", "#")) and "=" in t and t.split("=", 1)[0].strip().lower() == key.lower():
            return i
    return None


def get(path, section, key):
    lines = _read(path)
    b = _section_bounds(lines, section)
    i = _find_key(lines, b, key) if b else None
    return lines[i].split("=", 1)[1].strip() if i is not None else None


def set_keys(path, section, values):
    """Set {key: value} in [section]. Returns {key: previous value or None}."""
    lines = _read(path)
    previous = {}
    b = _section_bounds(lines, section)
    if b is None:
        lines += ["", f"[{section}]"]
        b = (len(lines), len(lines))
    for key, value in values.items():
        i = _find_key(lines, b, key)
        if i is None:
            previous[key] = None
            at = b[1]
            while at > b[0] and not lines[at - 1].strip():      # keep new keys with the others, before blank lines
                at -= 1
            lines.insert(at, f"{key}={value}")
            b = (b[0], b[1] + 1)
        else:
            previous[key] = lines[i].split("=", 1)[1].strip()
            lines[i] = f"{key}={value}"
    _write(path, lines)
    return previous


def restore_keys(path, section, previous):
    """Undo set_keys: put old values back, remove keys that weren't there."""
    lines = _read(path)
    b = _section_bounds(lines, section)
    if b is None:
        return
    for key, old in previous.items():
        i = _find_key(lines, b, key)
        if i is None:
            continue
        if old is None:
            del lines[i]
            b = (b[0], b[1] - 1)
        else:
            lines[i] = f"{key}={old}"
    _write(path, lines)
