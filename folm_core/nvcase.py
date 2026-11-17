#!/usr/bin/env python3
"""nvcase - find and fix letter-case collisions in a game's Data folder on Linux.

Windows treats "Textures" and "textures" as the same folder; Linux does not.
When mods disagree on capitalisation you end up with duplicate folders and the
game (via Wine/Proton) only sees one of them. This tool reports those
collisions and, with --fix, merges them safely with an undo log.
"""

import argparse
import json
import os
import shutil
import sys
import time
from collections import defaultdict


# ---------------------------------------------------------------- helpers

def is_real_dir(path):
    return os.path.isdir(path) and not os.path.islink(path)


def case_groups(directory):
    """Return {lowercase_name: [actual names]} for names that collide by case."""
    groups = defaultdict(list)
    try:
        names = os.listdir(directory)
    except OSError as e:
        print(f"  ! cannot read {directory}: {e}", file=sys.stderr)
        return {}
    for name in names:
        groups[name.lower()].append(name)
    return {k: sorted(v) for k, v in groups.items() if len(v) > 1}


def files_ci(root):
    """Map lowercase relative path -> actual relative path for every file under root."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for f in filenames:
            rel = os.path.relpath(os.path.join(dirpath, f), root)
            out[rel.lower()] = rel
    return out


def count_files(root):
    return sum(len(f) for _, _, f in os.walk(root))


def pick_canonical(directory, names, lowercase):
    """Choose which spelling survives a merge."""
    if lowercase:
        return names[0].lower()
    # keep the folder holding the most files; ties go to the all-lowercase spelling
    return max(names, key=lambda n: (count_files(os.path.join(directory, n)), n == n.lower()))


# ---------------------------------------------------------------- report mode

def report(root, lowercase):
    problems = 0
    would_rename = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for key, names in case_groups(dirpath).items():
            problems += 1
            paths = [os.path.join(dirpath, n) for n in names]
            rel = os.path.relpath(dirpath, root)
            where = "./" if rel == "." else rel + "/"
            if all(is_real_dir(p) for p in paths):
                counts = ", ".join(f"{n}/ ({count_files(p)} files)" for n, p in zip(names, paths))
                print(f"[folders] {where}: {counts}")
                maps = [files_ci(p) for p in paths]
                seen = defaultdict(list)
                for n, m in zip(names, maps):
                    for low, actual in m.items():
                        seen[low].append(f"{n}/{actual}")
                clashes = [v for v in seen.values() if len(v) > 1]
                for c in clashes[:10]:
                    print(f"    conflict: {'  vs  '.join(c)}")
                if len(clashes) > 10:
                    print(f"    ... and {len(clashes) - 10} more conflicts")
            else:
                print(f"[files]   {where}: {', '.join(names)}  (needs a manual choice)")
        if lowercase:
            would_rename += sum(1 for n in dirnames + filenames if n != n.lower())
    print()
    if problems:
        print(f"Found {problems} case collision(s). Run with --fix to merge folder collisions.")
    else:
        print("No case collisions found.")
    if lowercase:
        print(f"--lowercase would rename {would_rename} item(s).")
    return problems


# ---------------------------------------------------------------- fix mode

class Fixer:
    def __init__(self, lowercase):
        self.lowercase = lowercase
        self.ops = []          # undo log, in the order performed
        self.conflicts = []    # things left for the user

    def move(self, src, dst):
        os.rename(src, dst)
        self.ops.append({"op": "move", "src": src, "dst": dst})

    def rmdir(self, path):
        os.rmdir(path)
        self.ops.append({"op": "rmdir", "path": path})

    def merge_into(self, src, dst):
        """Move everything in src into dst. Never overwrites."""
        for name in sorted(os.listdir(src)):
            s, d = os.path.join(src, name), os.path.join(dst, name)
            if not os.path.lexists(d):
                self.move(s, d)
            elif is_real_dir(s) and is_real_dir(d):
                self.merge_into(s, d)
            else:
                self.conflicts.append((s, d))
        if not os.listdir(src):
            self.rmdir(src)

    def fix_dir(self, directory):
        for key, names in case_groups(directory).items():
            paths = [os.path.join(directory, n) for n in names]
            if not all(is_real_dir(p) for p in paths):
                self.conflicts.append(tuple(paths))
                continue
            canon = pick_canonical(directory, names, self.lowercase)
            canon_path = os.path.join(directory, canon)
            if not os.path.lexists(canon_path):
                # lowercase target doesn't exist yet: rename the biggest one onto it
                biggest = pick_canonical(directory, names, False)
                self.move(os.path.join(directory, biggest), canon_path)
                names = [n for n in names if n != biggest]
            for n in names:
                if n != canon:
                    self.merge_into(os.path.join(directory, n), canon_path)
        if self.lowercase:
            for name in sorted(os.listdir(directory)):
                low = name.lower()
                if name != low and not os.path.lexists(os.path.join(directory, low)):
                    self.move(os.path.join(directory, name), os.path.join(directory, low))
        for name in sorted(os.listdir(directory)):
            p = os.path.join(directory, name)
            if is_real_dir(p):
                self.fix_dir(p)


def fix(root, lowercase, log_path):
    f = Fixer(lowercase)
    try:
        f.fix_dir(root)
    finally:
        if f.ops:
            with open(log_path, "w") as fh:
                json.dump({"root": root, "created": time.ctime(), "ops": f.ops}, fh, indent=1)
    moves = sum(1 for o in f.ops if o["op"] == "move")
    print(f"Done: {moves} move(s), {len(f.ops) - moves} empty folder(s) removed.")
    if f.ops:
        print(f"Undo log: {log_path}")
    if f.conflicts:
        print(f"\n{len(f.conflicts)} item(s) left alone because they would overwrite something:")
        for c in f.conflicts[:20]:
            print("   " + "  vs  ".join(os.path.relpath(x, root) for x in c))
        if len(f.conflicts) > 20:
            print(f"   ... and {len(f.conflicts) - 20} more")
    return 1 if f.conflicts else 0


def undo(log_path):
    with open(log_path) as fh:
        ops = json.load(fh)["ops"]
    for op in reversed(ops):
        if op["op"] == "rmdir":
            os.makedirs(op["path"], exist_ok=True)
        else:
            os.makedirs(os.path.dirname(op["src"]), exist_ok=True)
            if os.path.lexists(op["src"]):
                print(f"  ! skip, already exists: {op['src']}", file=sys.stderr)
                continue
            os.rename(op["dst"], op["src"])
    print(f"Reverted {len(ops)} operation(s).")
    return 0


# ---------------------------------------------------------------- main

def main(argv=None):
    p = argparse.ArgumentParser(description="Find and fix letter-case collisions in a game Data folder.")
    p.add_argument("folder", nargs="?", help="folder to scan, usually .../Fallout New Vegas/Data")
    p.add_argument("--fix", action="store_true", help="merge colliding folders (default: report only)")
    p.add_argument("--lowercase", action="store_true", help="also rename everything to lowercase")
    p.add_argument("--log", help="where to write the undo log (default: ./nvcase-undo-<time>.json)")
    p.add_argument("--undo", metavar="LOG", help="reverse a previous --fix run")
    a = p.parse_args(argv)

    if a.undo:
        return undo(a.undo)
    if not a.folder:
        p.error("give a folder to scan, or --undo LOG")
    root = os.path.abspath(a.folder)
    if not is_real_dir(root):
        p.error(f"not a folder: {root}")
    if a.fix:
        log = a.log or os.path.abspath(time.strftime("nvcase-undo-%Y%m%d-%H%M%S.json"))
        return fix(root, a.lowercase, log)
    return 1 if report(root, a.lowercase) else 0


if __name__ == "__main__":
    sys.exit(main())
