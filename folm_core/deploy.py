"""deploy - put staged mods into the game folder with hard links, and take them out again.

Each mod lives in its own staging folder:
    <mods_dir>/<Mod Name>/            -> goes into the game's Data folder
    <mods_dir>/<Mod Name>/_root/      -> goes next to the game .exe
Mods later in the list win file conflicts.

Hard links make the file appear in both places while using the disk space once,
so deploying 17 GB of TTW is instant and free. Every change is recorded in a
manifest, so `undeploy` puts the game folder back exactly as it was.
"""

import json
import os
import shutil
import time

ROOT_DIR = "_root"


class CaseResolver:
    """Map a relative path onto existing folders case-insensitively.

    If the game already has 'Textures/' and a mod ships 'textures/', the mod's
    files go into the existing 'Textures/' instead of creating a twin folder.
    """

    def __init__(self, base):
        self.base = base
        self.cache = {}

    def _listing(self, d):
        if d not in self.cache:
            try:
                self.cache[d] = {n.lower(): n for n in os.listdir(d)}
            except FileNotFoundError:
                self.cache[d] = {}
        return self.cache[d]

    def resolve(self, rel):
        cur = self.base
        parts = rel.split("/")
        for i, part in enumerate(parts):
            existing = self._listing(cur).get(part.lower())
            name = existing or part
            nxt = os.path.join(cur, name)
            if existing is None and i < len(parts) - 1:
                os.makedirs(nxt, exist_ok=True)
                self._listing(cur)[part.lower()] = name
                self.cache[nxt] = {}
            elif existing is None:
                self._listing(cur)[part.lower()] = name
            cur = nxt
        return cur


def mod_files(mod_dir):
    """Yield (relative_path, is_root) for every file in a staged mod."""
    for dp, dn, fn in os.walk(mod_dir):
        rel_dir = os.path.relpath(dp, mod_dir).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir
        for f in fn:
            rel = f"{rel_dir}/{f}".strip("/")
            if rel.split("/")[0] == ROOT_DIR:
                yield rel.split("/", 1)[1], True
            else:
                yield rel, False


def place(src, dst):
    """Hard link src to dst; fall back to copying across drives."""
    try:
        os.link(src, dst)
        return "link"
    except OSError as e:
        if e.errno in (18, 1, 95):   # EXDEV, EPERM, EOPNOTSUPP
            shutil.copy2(src, dst)
            return "copy"
        raise


def walk_rel(base):
    """Every file under base, as '/'-separated relative paths."""
    out = set()
    for dp, dn, fn in os.walk(base):
        rel = os.path.relpath(dp, base).replace(os.sep, "/")
        for f in fn:
            out.add(f if rel == "." else f"{rel}/{f}")
    return out


def exists_ci(base, rel):
    """Find rel under base ignoring letter case; return the real path or None."""
    cur = base
    for part in rel.split("/"):
        try:
            names = {n.lower(): n for n in os.listdir(cur)}
        except (FileNotFoundError, NotADirectoryError):
            return None
        if part.lower() not in names:
            return None
        cur = os.path.join(cur, names[part.lower()])
    return cur


# ---------------------------------------------------------------- overwrite catcher

def find_strays(m):
    """Files the game or tools created/changed since deploy.

    new:     files that exist now but weren't there before deploy and weren't deployed by us
    changed: files we hard-linked that a tool replaced with its own version
    Root-folder *.log files are ignored (script extenders write them every launch).
    """
    game_dir = m["game_dir"]
    baseline = set(m.get("baseline", []))
    ours = {os.path.relpath(r["target"], game_dir).replace(os.sep, "/") for r in m["files"]}
    new = sorted(p for p in walk_rel(game_dir) - baseline - ours
                 if not ("/" not in p and p.lower().endswith(".log")))
    changed = []
    for r in m["files"]:
        t, s = r["target"], r["source"]
        if os.path.lexists(t) and os.path.exists(s) and r["how"] == "link" and not os.path.samefile(t, s):
            changed.append(r)
    return new, changed


def catch(manifest_path, overwrite_dir, log=print):
    """Move stray files into the Overwrite mod so the game folder stays clean."""
    if not os.path.exists(manifest_path):
        return 0
    with open(manifest_path) as fh:
        m = json.load(fh)
    new, changed = find_strays(m)
    game_dir, data_name = m["game_dir"], m.get("data_dir_name", "Data")

    def dest_for(rel):
        head, _, rest = rel.partition("/")
        if head.lower() == data_name.lower() and rest:
            return os.path.join(overwrite_dir, rest)
        return os.path.join(overwrite_dir, ROOT_DIR, rel)

    moved = 0
    for rel in new:
        d = dest_for(rel)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.move(os.path.join(game_dir, rel), d)
        moved += 1
    for r in changed:
        rel = os.path.relpath(r["target"], game_dir).replace(os.sep, "/")
        d = dest_for(rel)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        if os.path.lexists(d):
            os.remove(d)
        shutil.move(r["target"], d)
        m["files"].remove(r)
        moved += 1
    with open(manifest_path, "w") as fh:
        json.dump(m, fh, indent=1)
    if moved:
        log(f"Overwrite: caught {len(new)} new and {len(changed)} changed file(s) -> {overwrite_dir}")
    return moved


# ---------------------------------------------------------------- conflicts

def conflicts(game_dir, data_dir, mods_dir, enabled_mods, baseline=None):
    """Return {path: [providers in order]} for every file provided more than once.

    Providers are mod names, plus '(game)' when the file already exists in the
    game folder. The last provider wins. Files packed inside BSA archives aren't
    compared; loose files always beat BSA contents.
    """
    providers = {}
    shown = {}
    for mod in enabled_mods:
        mdir = os.path.join(mods_dir, mod)
        if not os.path.isdir(mdir):
            continue
        for rel, is_root in mod_files(mdir):
            key = ("<root>/" if is_root else "") + rel.lower()
            if key not in providers:
                shown[key] = ("(game folder) " if is_root else "") + rel
                base = game_dir if is_root else data_dir
                rel_game = os.path.relpath(os.path.join(base, rel), game_dir).replace(os.sep, "/")
                in_game = (rel_game.lower() in {b.lower() for b in baseline}) if baseline is not None \
                    else exists_ci(base, rel) is not None
                providers[key] = ["(game)"] if in_game else []
            providers[key].append(mod)
    return {shown[k]: v for k, v in sorted(providers.items()) if len(v) > 1}


# ---------------------------------------------------------------- deploy / undeploy

def deploy(game_dir, data_dir, mods_dir, enabled_mods, manifest_path, backup_dir, log=print,
           overwrite_dir=None):
    """Deploy enabled mods (in order). Undeploys any previous deployment first."""
    if os.path.exists(manifest_path):
        undeploy(manifest_path, log=lambda *a: None, overwrite_dir=overwrite_dir)

    manifest = {"created": time.ctime(), "game_dir": game_dir, "files": [], "backups": [],
                "data_dir_name": os.path.basename(data_dir), "baseline": sorted(walk_rel(game_dir))}
    data_res, root_res = CaseResolver(data_dir), CaseResolver(game_dir)
    ours = {}            # target -> index in manifest["files"]
    stats = {"link": 0, "copy": 0, "replaced": 0, "overrode_game": 0}
    try:
        for mod in enabled_mods:
            mdir = os.path.join(mods_dir, mod)
            if not os.path.isdir(mdir):
                log(f"  ! missing staged mod: {mod}")
                continue
            for rel, is_root in mod_files(mdir):
                src = os.path.join(mdir, ROOT_DIR, rel) if is_root else os.path.join(mdir, rel)
                dst = (root_res if is_root else data_res).resolve(rel)
                if dst in ours:                       # an earlier mod placed it: later mod wins
                    os.remove(dst)
                    stats["replaced"] += 1
                    entry = manifest["files"][ours[dst]]
                elif os.path.lexists(dst):            # a game file: back it up first
                    bak = os.path.join(backup_dir, os.path.relpath(dst, game_dir))
                    os.makedirs(os.path.dirname(bak), exist_ok=True)
                    os.rename(dst, bak)
                    manifest["backups"].append({"target": dst, "backup": bak})
                    stats["overrode_game"] += 1
                    entry = None
                else:
                    entry = None
                how = place(src, dst)
                stats[how] += 1
                rec = {"target": dst, "source": src, "mod": mod, "how": how}
                if entry is not None:
                    entry.update(rec)
                else:
                    ours[dst] = len(manifest["files"])
                    manifest["files"].append(rec)
    finally:
        os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
        with open(manifest_path, "w") as fh:
            json.dump(manifest, fh, indent=1)
    log(f"Deployed {len(manifest['files'])} files from {len(enabled_mods)} mod(s): "
        f"{stats['link']} hard-linked, {stats['copy']} copied, "
        f"{stats['replaced']} conflicts won by a later mod, {stats['overrode_game']} game files backed up.")
    return manifest


def undeploy(manifest_path, log=print, overwrite_dir=None):
    """Remove everything a deployment added and restore backed-up game files.

    With overwrite_dir, stray files are caught into the Overwrite mod first.
    """
    if not os.path.exists(manifest_path):
        log("Nothing is deployed.")
        return
    if overwrite_dir:
        catch(manifest_path, overwrite_dir, log)
    with open(manifest_path) as fh:
        m = json.load(fh)
    removed, kept = 0, []
    for rec in m["files"]:
        t = rec["target"]
        if not os.path.lexists(t):
            continue
        same = os.path.exists(rec["source"]) and (
            os.path.samefile(t, rec["source"]) if rec["how"] == "link"
            else os.path.getsize(t) == os.path.getsize(rec["source"]))
        if same:
            os.remove(t)
            removed += 1
        else:
            kept.append(t)               # changed since deploy: never delete the user's work
    for b in reversed(m["backups"]):
        if os.path.lexists(b["backup"]) and not os.path.lexists(b["target"]):
            os.makedirs(os.path.dirname(b["target"]), exist_ok=True)
            os.rename(b["backup"], b["target"])
    # tidy folders the deployment created and left empty
    for rec in sorted(m["files"], key=lambda r: -r["target"].count("/")):
        d = os.path.dirname(rec["target"])
        while d.startswith(m["game_dir"]) and d != m["game_dir"]:
            try:
                os.rmdir(d)
            except OSError:
                break
            d = os.path.dirname(d)
    os.remove(manifest_path)
    log(f"Undeployed: removed {removed} files, restored {len(m['backups'])} game files.")
    for t in kept[:10]:
        log(f"  ! left in place (changed since deploy): {t}")
