"""manager - the FOLM engine API shared by the command line (folm.py) and the app (folm_gui.py).

Everything here returns data or raises FolmError; nothing prints or exits, so a
GUI can call it directly and show results however it likes.
"""

import json
import os
import re
import shutil
import subprocess
import struct
import tempfile
import time

from . import archive as archive_mod, deploy as dep, detect, fomod, loadorder

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STEAM = os.path.expanduser("~/.local/share/Steam")
OVERWRITE = "Overwrite"
EDITIONS = ("courier", "wanderer")

# Mod list sections, in load order. "Sort mods" arranges by these. The order follows
# the community-standard New Vegas guide structure (Utilities, Bug Fixes, User Interface,
# Content, Gameplay, Visuals), with TTW / the base game first and our own mods after.
CATEGORIES = ["Base game & TTW", "Utilities & engine", "Bug fixes", "UI & menus",
              "Content", "Gameplay", "Visuals", "Our mods", "Other"]
TAG_CATEGORY = [("ours", "Our mods"), ("visuals", "Visuals"), ("gameplay", "Gameplay"),
                ("ui", "UI & menus"), ("fixes", "Bug fixes"), ("engine", "Utilities & engine"),
                ("ini", "Utilities & engine"), ("ttw", "Base game & TTW")]
BASE_PLUGINS = {"falloutnv.esm", "fallout3.esm", "taleoftwowastelands.esm"}


class FolmError(Exception):
    pass


def home():
    return os.path.expanduser(os.environ.get("FOLM_HOME", "~/Games/FOLM"))


def game_info(edition):
    with open(os.path.join(HERE, "games", edition, "game.json")) as fh:
        return json.load(fh)


def steam_libraries():
    libs = [os.path.join(STEAM, "steamapps")]
    vdf = os.path.join(STEAM, "steamapps", "libraryfolders.vdf")
    if os.path.exists(vdf):
        for m in re.finditer(r'"path"\s+"([^"]+)"', open(vdf).read()):
            p = os.path.join(m.group(1), "steamapps")
            if p not in libs:
                libs.append(p)
    return libs


def empty_profile():
    return {"mods": [], "plugin_order": [], "disabled_plugins": []}


def _quiet(*a):
    pass


class Manager:
    """One edition's setup: game paths, named profiles, staged mods."""

    def __init__(self, edition="courier"):
        if edition not in EDITIONS:
            raise FolmError(f"unknown edition {edition!r}")
        self.edition = edition
        self.dir = os.path.join(home(), edition)
        self.path = os.path.join(self.dir, "profile.json")
        self.data = {}
        self._mtime = None
        if os.path.exists(self.path):
            self._load()
            if "profiles" not in self.data:          # upgrade a v0.1 file
                self.data["profiles"] = {"Default": {k: self.data.pop(k, []) for k in empty_profile()}}
                self.data["active"] = "Default"
                self.save()
            old = os.path.join(self.mods_dir, OVERWRITE)  # early shared Overwrite -> Default's
            if os.path.isdir(old) and not os.path.exists(os.path.join(self.mods_dir, f"{OVERWRITE} [Default]")):
                os.rename(old, os.path.join(self.mods_dir, f"{OVERWRITE} [Default]"))

    # ------------------------------------------------------------ state
    def _load(self):
        with open(self.path) as fh:
            self.data = json.load(fh)
        self._mtime = os.stat(self.path).st_mtime_ns

    def sync(self):
        """Re-read profile.json if another FOLM (CLI or app) changed it since we last read/wrote it."""
        try:
            if os.stat(self.path).st_mtime_ns != self._mtime:
                self._load()
        except FileNotFoundError:
            pass

    @property
    def ready(self):
        return bool(self.data.get("game_dir"))

    def need(self):
        self.sync()
        if not self.ready:
            raise FolmError(f"No {self.edition} setup yet. Run init first.")
        return self

    @property
    def cur(self):
        self.sync()
        return self.data["profiles"][self.data["active"]]

    @property
    def active(self):
        return self.data.get("active")

    def save(self):
        os.makedirs(self.dir, exist_ok=True)
        with open(self.path, "w") as fh:
            json.dump(self.data, fh, indent=1)
        self._mtime = os.stat(self.path).st_mtime_ns

    mods_dir = property(lambda s: os.path.join(s.dir, "mods"))
    manifest = property(lambda s: os.path.join(s.dir, "deployed.json"))
    lo_state = property(lambda s: os.path.join(s.dir, "loadorder-state.json"))
    deploy_state = property(lambda s: os.path.join(s.dir, "deploy-state.json"))
    backups = property(lambda s: os.path.join(s.dir, "backups", "overwritten"))
    overwrite_name = property(lambda s: f"{OVERWRITE} [{s.data['active']}]")
    overwrite_dir = property(lambda s: os.path.join(s.mods_dir, s.overwrite_name))
    data_dir = property(lambda s: os.path.join(s.data["game_dir"], s.data["data_dir"]))
    plugins_txt = property(lambda s: os.path.join(s.data["prefix"], s.data["plugins_txt"]))

    @property
    def deployed(self):
        return os.path.exists(self.manifest)

    def mods(self):
        return self.cur["mods"]

    def mod(self, name):
        for m in self.cur["mods"]:
            if m["name"].lower() == name.lower():
                return m
        raise FolmError(f"No mod called {name!r} in profile {self.active!r}.")

    def overwrite_count(self):
        d = self.overwrite_dir
        return len(dep.walk_rel(d)) if os.path.isdir(d) else 0

    def enabled(self):
        names = [m["name"] for m in self.cur["mods"] if m["enabled"]]
        if self.overwrite_count():
            names.append(self.overwrite_name)
        return names

    # ------------------------------------------------------------ setup
    def init(self, game_dir=None, prefix=None):
        g = game_info(self.edition)
        lib = None
        if not game_dir:
            for lib in steam_libraries():
                cand = os.path.join(lib, "common", g["install_dir"])
                if os.path.isdir(cand):
                    game_dir = cand
                    break
        if not game_dir or not os.path.isdir(game_dir):
            raise FolmError(f"Couldn't find {g['game']}. Give its folder.")
        prefix = prefix or os.path.join(lib or os.path.dirname(os.path.dirname(game_dir)),
                                        "compatdata", str(g["steam_app_id"]))
        app = os.path.basename(g["prefix_appdata"])
        self.data.update({
            "edition": self.edition, "game": g["game"], "game_dir": game_dir,
            "data_dir": g["data_dir"], "prefix": prefix, "steam_app_id": g["steam_app_id"],
            "plugins_txt": f"pfx/drive_c/users/steamuser/AppData/Local/{app}/plugins.txt",
        })
        self.data.setdefault("profiles", {"Default": empty_profile()})
        self.data.setdefault("active", "Default")
        self.data.setdefault("library_folders", [])
        os.makedirs(self.mods_dir, exist_ok=True)
        self.save()
        return {"game_dir": game_dir, "prefix": prefix, "prefix_exists": os.path.isdir(prefix)}

    # ------------------------------------------------------------ mods
    @staticmethod
    def guess_name(archive):
        return re.sub(r"(-\d+)+.*$|\.(7z|zip|rar|fomod|exe)$", "", os.path.basename(archive)).strip() or "mod"

    def fomod_context(self):
        """What a FOMOD may check: files already in the game + in enabled mods, and active plugins."""
        files = set()
        if os.path.isdir(self.data_dir):
            files |= dep.walk_rel(self.data_dir)
        for name in self.enabled():
            d = os.path.join(self.mods_dir, name)
            if os.path.isdir(d):
                files |= {rel for rel, is_root in dep.mod_files(d) if not is_root}
        dis = {d.lower() for d in self.cur["disabled_plugins"]}
        active = [f for f in files if "/" not in f and f.lower().endswith((".esm", ".esp")) and f.lower() not in dis]
        return fomod.Context(files, active)

    @staticmethod
    def file_fingerprint(path):
        """Cheap identity of a download: size + hash of its first and last MB (fast even for TTW's 1.3 GB)."""
        import hashlib
        try:
            size = os.path.getsize(path)
            h = hashlib.sha1(str(size).encode())
            with open(path, "rb") as fh:
                h.update(fh.read(1 << 20))
                if size > 2 << 20:
                    fh.seek(-(1 << 20), os.SEEK_END)
                    h.update(fh.read())
            return h.hexdigest()
        except OSError:
            return None

    @staticmethod
    def _file_stem(path):
        """'Stewie Tweaks INI-23561-10-0-1700000000.7z' -> 'stewie tweaks ini' (same page, different files differ)."""
        base = os.path.basename(path or "")
        return re.sub(r"-\d{2,7}(-[\w.]*)*\.\w+$|\.\w+$", "", base).strip().lower()

    def find_duplicates(self, archive):
        """Mods (any profile) installed from this same file, or from another version of it.
        Returns [(kind, profile, mod)] with kind "same" or "version", this profile first."""
        from . import requires
        fp = self.file_fingerprint(archive)
        base = os.path.basename(archive).lower()
        nid = requires.nexus_id({"source": archive})
        stem = self._file_stem(archive)
        hits, learned = [], False
        profiles = sorted(self.data["profiles"].items(), key=lambda kv: kv[0] != self.active)
        for prof, p in profiles:
            for mod in p["mods"]:
                src = mod.get("source") or ""
                if not src:
                    continue
                known = mod.get("source_fp")
                if not known and os.path.exists(src):        # installed before fingerprints: learn it once
                    known = mod["source_fp"] = self.file_fingerprint(src)
                    learned = learned or bool(known)
                if fp and known:
                    same = known == fp                       # both known: the contents decide, not the name
                else:
                    same = os.path.basename(src).lower() == base
                if same:
                    hits.append(("same", prof, mod))
                elif nid and requires.nexus_id(mod) == nid and self._file_stem(src) == stem:
                    hits.append(("version", prof, mod))
        if learned:
            self.save()
        return hits

    def _free_name(self, name):
        n, i = name, 2
        while os.path.exists(os.path.join(self.mods_dir, n)):
            n, i = f"{name} ({i})", i + 1
        return n

    def install(self, archive, name=None, chooser=None, log=_quiet, detected=None):
        """Stage a mod (see _install), then say what it needs that isn't installed.

        If the same file (or another version of it) is already installed, asks first via the chooser:
        same file -> don't install again (or reinstall / second copy); other version -> update (or keep both)."""
        self.need()
        try:
            r = detected or detect.detect(archive)
        except (ValueError, OSError):
            r = {}
        if r.get("type") == "tool":
            return self.install_tool(archive, r["tool"], log)
        dups = self.find_duplicates(archive)
        replace = None
        if dups:
            kind, prof, old = dups[0]
            here = prof == self.active
            where = "" if here else f" in profile '{prof}'"
            if kind == "same":
                first = ("Don't install it again", f"It's already installed as '{old['name']}'{where}.") if here else \
                    ("Add the installed copy to this profile", f"'{old['name']}' is already installed{where}; "
                     "use the same files here (nothing is installed twice).")
                opts = [first, ("Replace it (reinstall)", "Install it again over the existing copy, keeping its "
                                "place in the list, on/off state, notes and tags."),
                        ("Install a second copy", "Keep both as separate mods.")]
                title = "This mod is already installed"
            else:
                opts = [("Update", f"Replace '{old['name']}'{where} with this version, keeping its place in the "
                         "list, on/off state, notes and tags."),
                        ("Keep both", "Install this version as a separate mod."),
                        ("Cancel", "Don't install it.")]
                title = "Another version of this mod is installed"
            group = {"name": title, "type": "SelectExactlyOne", "plugins": [
                {"name": n, "description": d, "image": None, "type": "Recommended" if i == 0 else "Optional"}
                for i, (n, d) in enumerate(opts)]}
            pick = (chooser or (lambda s, g: fomod.default_choice(g)))("Already installed", group)
            choice = opts[pick[0]][0] if pick else "Cancel"
            if choice == "Don't install it again" or choice == "Cancel":
                raise FolmError(f"Not installed: {os.path.basename(archive)} is already installed as "
                                f"'{old['name']}'{where}." if kind == "same" else "install cancelled")
            if choice == "Add the installed copy to this profile":
                if os.path.isdir(os.path.join(self.mods_dir, old["name"])):
                    entry = {k: v for k, v in old.items()}
                    entry["enabled"] = True
                    self.cur["mods"].append(entry)
                    self.save()
                    log(f"  added the installed copy '{old['name']}' to this profile")
                    return old["name"], {"type": old.get("type", "data"), "warnings": [], "reused": True}
            elif choice in ("Replace it (reinstall)", "Update"):
                replace = old
            else:                                             # second copy / keep both
                name = self._free_name(name or self.guess_name(archive))
        if replace is None:
            result = self._install(archive, name, chooser, log, detected=r or None)
        else:
            result = self._replace(replace, archive, chooser, log, detected=r or None)
        entry = next((x for x in self.cur["mods"] if x["name"] == result[0]), None)
        if entry is not None:
            entry["source_fp"] = self.file_fingerprint(archive)
            self.save()
        try:
            from . import requires
            for r in requires.check(self, only=result[0]):
                log(("  ✖ " if r["severity"] == "error" else "  ⚠ " if r["severity"] == "warn" else "  ℹ ")
                    + requires.describe(r))
        except Exception as e:                       # never let the check spoil an install
            log(f"  (couldn't check its requirements: {e})")
        return result

    def _replace(self, old, archive, chooser, log, detected=None):
        """Install `archive` in place of the staged mod `old` (update / reinstall). The old files are kept
        aside until the new install has worked; every profile that lists the mod gets the new files."""
        name = old["name"]
        dest = os.path.join(self.mods_dir, name)
        aside = os.path.join(self.dir, f".replacing-{int(time.time())}")
        if os.path.isdir(dest):
            os.rename(dest, aside)
        before = [dict(x) for x in self.cur["mods"]]
        pos = next((i for i, x in enumerate(self.cur["mods"]) if x["name"] == name), None)
        if pos is not None:
            self.cur["mods"].pop(pos)
        try:
            result = self._install(archive, name, chooser, log, detected=detected)
        except Exception:
            if os.path.isdir(aside):
                if os.path.isdir(dest):
                    shutil.rmtree(dest, ignore_errors=True)
                os.rename(aside, dest)
            self.cur["mods"][:] = before
            self.save()
            raise
        new = self.cur["mods"].pop(next(i for i, x in enumerate(self.cur["mods"]) if x["name"] == name))
        for k in ("enabled", "notes", "tags", "category"):
            if k in old:
                new[k] = old[k]
        self.cur["mods"].insert(pos if pos is not None else len(self.cur["mods"]), new)
        for p in self.data["profiles"].values():          # other profiles listing it: point at the new install
            for x in p["mods"]:
                if x is not new and x["name"] == name:
                    x.update({k: v for k, v in new.items() if k not in ("enabled", "notes", "tags", "category")})
        self.save()
        shutil.rmtree(aside, ignore_errors=True)
        log(f"  replaced '{name}' with {os.path.basename(archive)}")
        return result

    def _install(self, archive, name=None, chooser=None, log=_quiet, detected=None):
        """Stage a mod from an archive. Returns (name, detect_result).

        FOMOD (XML) mods need a chooser(step, group) -> [option indexes]; without one,
        the installer's defaults (required + recommended options) are used.
        """
        self.need()
        try:
            r = detected or detect.detect(archive)
        except ValueError:
            raise FolmError(f"{os.path.basename(archive)} isn't a mod archive FOLM can open "
                            "(mods come as .7z, .zip, .rar, .fomod or .exe files).")
        name = name or self.guess_name(archive)
        if r["type"] == "fomod-xml":
            return self._install_fomod(archive, name, r, chooser or (lambda s, g: fomod.default_choice(g)), log)
        if r["type"] == "fomod-csharp":
            return self._install_legacy(archive, name, r, log)
        if r["type"] == "nested":
            with tempfile.TemporaryDirectory(dir=self.dir) as tmp:
                try:
                    archive_mod.extract(archive, tmp)
                except archive_mod.ArchiveError as e:
                    raise FolmError(str(e))
                inner = os.path.join(tmp, r["inner"])
                log(f"  {os.path.basename(archive)} wraps {os.path.basename(inner)}: installing that")
                result = self._install(inner, name, chooser=chooser, log=log)
            self.mod(result[0])["source"] = os.path.abspath(archive)   # the download, not the temporary inner file
            self.save()
            return result
        if r["type"] == "source":
            raise FolmError(f"{os.path.basename(archive)} is the mod's source code (for programmers), not something "
                            "to install. Download the mod's main file instead.")
        if r["type"] in ("exe-installer", "ttw-installer"):
            return self._install_wintool(archive, name, r, chooser or (lambda s, g: fomod.default_choice(g)), log)
        if r["type"] == "bain":
            return self._install_bain(archive, name, r, chooser or (lambda s, g: fomod.default_choice(g)), log)
        if r["type"] == "unknown":
            raise FolmError(f"{os.path.basename(archive)} doesn't look like a {game_info(self.edition)['game']} mod: "
                            "no plugins, game folders, installer or script extender files in it. "
                            "Is it for another game?")
        if r["type"] not in ("data", "data+game-root", "game-root"):
            raise FolmError(f"FOLM doesn't recognise this kind of mod ({r['type']}).")
        dest = os.path.join(self.mods_dir, name)
        if os.path.exists(dest):
            raise FolmError(f"A mod called {name!r} is already staged.")
        with tempfile.TemporaryDirectory(dir=self.dir) as tmp:
            try:
                archive_mod.extract(archive, tmp)
            except archive_mod.ArchiveError as e:
                raise FolmError(str(e))
            os.makedirs(dest)
            if r["data_root"] is not None:
                src = os.path.join(tmp, r["data_root"]) if r["data_root"] else tmp
                for item in os.listdir(src):
                    if r["type"] == "data+game-root" and item in r["game_root_files"] and r["data_root"] == "":
                        continue
                    if item.lower() == "fomod":          # installer metadata, not game files
                        continue
                    shutil.move(os.path.join(src, item), dest)
            if r["game_root_files"]:
                base = os.path.join(tmp, detect.unwrap(*detect.list_folder(tmp))) if r["type"] == "game-root" else \
                    os.path.dirname(os.path.join(tmp, r["data_root"])) if r["data_root"] else tmp
                rootd = os.path.join(dest, dep.ROOT_DIR)
                os.makedirs(rootd, exist_ok=True)
                for item in r["game_root_files"]:
                    p = os.path.join(base, item)
                    if os.path.lexists(p):
                        shutil.move(p, rootd)
        self.cur["mods"].append({"name": name, "enabled": True, "type": r["type"],
                                 "source": os.path.abspath(archive), "notes": "", "tags": []})
        self.save()
        return name, r

    def _install_fomod(self, archive, name, r, chooser, log):
        dest = os.path.join(self.mods_dir, name)
        if os.path.exists(dest):
            raise FolmError(f"A mod called {name!r} is already staged.")
        with tempfile.TemporaryDirectory(dir=self.dir) as tmp:
            try:
                archive_mod.extract(archive, tmp)
            except archive_mod.ArchiveError as e:
                raise FolmError(str(e))
            root = os.path.join(tmp, r["data_root"]) if r["data_root"] else tmp
            try:
                entries, choices, info = fomod.run(root, chooser, self.fomod_context(), log=log)
            except fomod.FomodError as e:
                raise FolmError(f"FOMOD installer: {e}")
            os.makedirs(dest)
            try:
                res = fomod.install_files(root, entries, dest, log=log)
            except Exception:
                shutil.rmtree(dest, ignore_errors=True)
                raise
        for w in info["warnings"]:
            log(f"  ! {w}")
        log(f"  FOMOD '{info['name']}': installed {res['files']} file(s)")
        r = dict(r, warnings=r.get("warnings", []) + info["warnings"])
        self.cur["mods"].append({"name": name, "enabled": True, "type": "fomod-xml",
                                 "source": os.path.abspath(archive), "notes": "", "tags": [],
                                 "fomod_choices": choices})
        self.save()
        return name, r

    def _install_legacy(self, archive, name, r, log):
        """Old FOMM C# installer: compile + run it sandboxed (folm_core/legacy.py), then tidy staging."""
        from . import legacy, nvcase
        dest = os.path.join(self.mods_dir, name)
        if os.path.exists(dest):
            raise FolmError(f"A mod called {name!r} is already staged.")
        with tempfile.TemporaryDirectory(dir=self.dir) as tmp:
            try:
                archive_mod.extract(archive, tmp)
            except archive_mod.ArchiveError as e:
                raise FolmError(str(e))
            root = os.path.join(tmp, r["data_root"]) if r["data_root"] else tmp
            os.makedirs(dest)
            plugins, _ = loadorder.scan_plugins(self.data_dir) if os.path.isdir(self.data_dir) else ({}, [])
            ini_dir = os.path.join(self.data["prefix"], "pfx/drive_c/users/steamuser/Documents/My Games",
                                   os.path.basename(game_info(self.edition)["ini_dir"]))
            try:
                plan = legacy.run(root, self.data["game_dir"], dest, list(plugins), ini_dir=ini_dir, log=log)
            except legacy.LegacyError as e:
                shutil.rmtree(dest, ignore_errors=True)
                raise FolmError(f"old FOMM installer: {e}")
        if not plan.get("result"):
            shutil.rmtree(dest, ignore_errors=True)
            raise FolmError("the mod's installer was cancelled or reported failure")
        tidy = nvcase.Fixer(lowercase=False)
        tidy.fix_dir(dest)                       # merge Textures/textures-style twins from the archive
        requests = [a for a in plan["actions"] if a.get("op") in ("plugin", "ini")]
        log(f"  installed {plan['installed']} file(s); merged {sum(1 for o in tidy.ops if o['op'] == 'rmdir')} "
            f"duplicate-case folder(s); {len(requests)} plugin/INI request(s) kept for review")
        self.cur["mods"].append({"name": name, "enabled": True, "type": "fomod-csharp",
                                 "source": os.path.abspath(archive), "notes": "", "tags": [],
                                 "legacy_requests": requests})
        self.save()
        return name, r

    def _install_bain(self, archive, name, r, chooser, log):
        """BAIN package: numbered option folders ("00 Core", "10 Option"). Picked ones are merged in order."""
        from . import nvcase
        dest = os.path.join(self.mods_dir, name)
        if os.path.exists(dest):
            raise FolmError(f"A mod called {name!r} is already staged.")
        opts = r["options"]
        core = [o for o in opts if re.match(r"^0+\s", o) or re.search(r"\b(core|main|required|base)\b", o, re.I)]
        group = {"name": "Packages", "type": "SelectAny", "plugins": [
            {"name": o, "description": "Core files: install these." if o in core else "Optional package.",
             "image": None, "type": "Recommended" if o in (core or opts[:1]) else "Optional"} for o in opts]}
        picked = chooser("BAIN", group)
        if picked is None:
            raise FolmError("install cancelled")
        picked = sorted(set(picked))
        if not picked:
            raise FolmError("no packages chosen")
        names = [opts[i] for i in picked]
        with tempfile.TemporaryDirectory(dir=self.dir) as tmp:
            try:
                archive_mod.extract(archive, tmp)
            except archive_mod.ArchiveError as e:
                raise FolmError(str(e))
            root = os.path.join(tmp, r["data_root"]) if r["data_root"] else tmp
            os.makedirs(dest)
            for o in names:                                   # in number order: later packages win
                src = os.path.join(root, o)
                kids = {k.lower(): k for k in os.listdir(src)}
                if "data" in kids and os.path.isdir(os.path.join(src, kids["data"])):
                    src = os.path.join(src, kids["data"])     # a package that mirrors the game folder
                shutil.copytree(src, dest, dirs_exist_ok=True)
        tidy = nvcase.Fixer(lowercase=False)
        tidy.fix_dir(dest)
        log(f"  BAIN: installed {', '.join(names)}")
        self.cur["mods"].append({"name": name, "enabled": True, "type": "bain",
                                 "source": os.path.abspath(archive), "notes": "", "tags": [],
                                 "bain_choices": {"BAIN/Packages": names}})
        self.save()
        return name, r

    def other_game_dirs(self):
        """The other Fallout game's folder, if installed (TTW's installer needs both)."""
        out = {}
        for ed in EDITIONS:
            if ed == self.edition:
                continue
            for lib in steam_libraries():
                cand = os.path.join(lib, "common", game_info(ed)["install_dir"])
                if os.path.isdir(cand):
                    out[ed] = cand
                    break
        return out

    def _install_wintool(self, archive, name, r, chooser, log):
        """A Windows installer or patcher: run it like on Windows (folm_core/wintool.py); its output is the mod."""
        from . import wintool, wineprefix
        dest = os.path.join(self.mods_dir, name)
        if os.path.exists(dest):
            raise FolmError(f"A mod called {name!r} is already staged.")
        why = wintool.available()
        if why:
            raise FolmError(why)
        if wineprefix.prefix_busy(self.data["prefix"]):
            raise FolmError("Close the game first: FOLM takes your mods out of the game while the installer runs.")
        work = os.path.join(home(), "work")
        os.makedirs(work, exist_ok=True)
        job = tempfile.mkdtemp(prefix="tool-", dir=work)
        was_deployed, taken_out = self.deployed, False
        try:
            tool = os.path.join(job, "tool")
            os.makedirs(tool)
            if archive.lower().endswith(".exe"):
                shutil.copy2(archive, tool)
            else:
                try:
                    archive_mod.extract(archive, tool)
                except archive_mod.ArchiveError as e:
                    raise FolmError(str(e))
            exes = wintool.find_exes(tool)
            if not exes:
                raise FolmError("there's no installer .exe in this download")
            if len(exes) > 1:
                group = {"name": "Which program runs the install?", "type": "SelectExactlyOne", "plugins": [
                    {"name": os.path.relpath(e, tool), "description": "", "image": None,
                     "type": "Recommended" if i == 0 else "Optional"} for i, e in enumerate(exes)]}
                pick = chooser("Installer", group)
                if not pick:
                    raise FolmError("install cancelled")
                exe = exes[pick[0]]
            else:
                exe = exes[0]
            ttw = r["type"] == "ttw-installer"
            in_game = wintool.runs_in_game_folder(exe, r["type"])
            what = ("It runs from your game folder, as its instructions say." if in_game else
                    "It sees your game where Windows would.")
            confirm = {"name": f"Run {os.path.basename(exe)}?", "type": "SelectExactlyOne", "plugins": [
                {"name": "Run it", "type": "Recommended", "image": None, "description":
                 f"FOLM runs {os.path.basename(exe)} with Wine, like on Windows. {what}\n\n"
                 "Your real game folder is protected: whatever the program changes or adds is collected into a "
                 f"new mod, '{name}', which you can turn off or remove like any other.\n\n"
                 "If it asks where to put its files, choose drive O: (FOLM output)"
                 + (" as the TTW destination folder" if ttw else "") + ". Your mods are taken out of the game "
                 "while it runs, so it sees the plain game. No network access.\n\n"
                 "While it works, its window may look blank or frozen: that's normal (it draws again when it's "
                 "done). FOLM shows its progress in the status bar."
                 + ("\n\nTTW takes a while (about 20 minutes on a fast PC, longer on older ones)." if ttw else "")},
                {"name": "Cancel", "type": "Optional", "image": None, "description": "Don't run it."}]}
            pick = chooser("Windows installer", confirm)
            if pick != [0]:
                raise FolmError("install cancelled")
            try:
                wine, proton = wintool.find_wine([STEAM, os.path.expanduser("~/.steam/steam")], steam_libraries())
            except wintool.ToolError as e:
                raise FolmError(str(e))
            if was_deployed:
                log("  taking your mods out of the game while it runs")
                self.undeploy(log=_quiet)
                taken_out = True
            game_dir = self.data["game_dir"]
            others = self.other_game_dirs()
            reg = {"HKLM\\Software\\Bethesda Softworks\\" + ("FalloutNV" if self.edition == "courier" else "Fallout3"):
                   game_dir}
            for ed, d in others.items():
                reg["HKLM\\Software\\Bethesda Softworks\\" + ("FalloutNV" if ed == "courier" else "Fallout3")] = d
            try:
                cap = wintool.run(exe, tool, job, game_dir, list(others.values()),
                                  os.path.join(home(), "prefixes", "installer", "pfx"), wine, proton,
                                  args=["-NoOggEnc2"] if ttw else [], in_game_folder=in_game, registry=reg, log=log)
                os.makedirs(dest)
                res = wintool.collect(cap, game_dir, dest, log=log)
            except wintool.ToolError as e:
                raise FolmError(str(e))
        finally:
            wintool.remove_tree(job)
            if taken_out:
                try:
                    self.deploy(log=_quiet)
                except Exception as e:
                    log(f"  ! couldn't put your mods back in the game ({e}); press Deploy")
        if not res["files"]:
            shutil.rmtree(dest, ignore_errors=True)
            raise FolmError(f"{os.path.basename(exe)} finished without changing or adding any files "
                            "(cancelled, or it saved somewhere other than the game folder or drive O:).")
        log(f"  collected {res['files']} file(s) the installer made into '{name}'"
            + (f"; it also deleted {len(res['deleted'])} game file(s), which FOLM leaves in place" if res["deleted"]
               else ""))
        self.cur["mods"].append({"name": name, "enabled": True, "type": "windows-installer",
                                 "source": os.path.abspath(archive), "notes": "", "tags": [],
                                 "ran": os.path.basename(exe), "deleted_by_installer": res["deleted"]})
        self.save()
        return name, r

    def fomod_preview(self, archive):
        """Read a FOMOD installer without installing: returns (extract_dir_owner, module_root).

        The caller must clean up the TemporaryDirectory it gets back.
        """
        r = detect.detect(archive)
        if r["type"] != "fomod-xml":
            raise FolmError("not an XML FOMOD")
        tmp = tempfile.TemporaryDirectory(dir=self.dir)
        try:
            archive_mod.extract(archive, tmp.name)
        except archive_mod.ArchiveError as e:
            tmp.cleanup()
            raise FolmError(str(e))
        return tmp, (os.path.join(tmp.name, r["data_root"]) if r["data_root"] else tmp.name)

    def add_folder(self, name):
        self.need()
        if not os.path.isdir(os.path.join(self.mods_dir, name)):
            raise FolmError(f"{name!r} isn't in {self.mods_dir}")
        if any(m["name"].lower() == name.lower() for m in self.cur["mods"]):
            raise FolmError(f"{name!r} is already in this profile")
        self.cur["mods"].append({"name": name, "enabled": True, "type": "folder", "notes": "", "tags": []})
        self.save()

    def staged_not_in_profile(self):
        """Mods in the shared library that this profile doesn't list yet."""
        if not os.path.isdir(self.mods_dir):
            return []
        have = {m["name"].lower() for m in self.cur["mods"]}
        return sorted(n for n in os.listdir(self.mods_dir)
                      if os.path.isdir(os.path.join(self.mods_dir, n)) and n.lower() not in have
                      and not n.startswith(OVERWRITE + " ["))

    def set_enabled(self, name, on):
        self.mod(name)["enabled"] = bool(on)
        self.save()

    def reorder(self, names):
        """Set the mod order from a list of names (must be the same set)."""
        by = {m["name"]: m for m in self.cur["mods"]}
        if set(names) != set(by):
            raise FolmError("reorder: mod list changed")
        self.cur["mods"] = [by[n] for n in names]
        self.save()

    def move_after(self, name, other):
        m, o = self.mod(name), self.mod(other)
        mods = self.cur["mods"]
        mods.remove(m)
        mods.insert(mods.index(o) + 1, m)
        self.save()

    def set_note(self, name, text):
        self.mod(name)["notes"] = text
        self.save()

    def add_tags(self, name, tags):
        m = self.mod(name)
        m["tags"] = sorted(set(m.get("tags", [])) | {t.strip().lstrip("#").strip().lower() for t in tags if t.strip()})
        self.save()
        return m["tags"]

    def set_tags(self, name, tags):
        self.mod(name)["tags"] = sorted({t.strip().lstrip("#").strip().lower() for t in tags if t.strip()})
        self.save()

    def remove(self, name):
        """Remove a mod from this profile (its files stay in the shared library)."""
        self.cur["mods"].remove(self.mod(name))
        self.save()

    # ------------------------------------------------------------ categories + sorting
    def category_of(self, mod):
        """The mod's section: set by the player, else from its tags, else from its files."""
        if mod.get("category") in CATEGORIES:
            return mod["category"]
        tags = set(mod.get("tags", []))
        for tag, cat in TAG_CATEGORY:
            if tag in tags:
                return cat
        d = os.path.join(self.mods_dir, mod["name"])
        files = [(rel.lower(), root) for rel, root in dep.mod_files(d)] if os.path.isdir(d) else []
        tops = {f.split("/")[0] for f, root in files if not root}
        if any(f in BASE_PLUGINS for f, _ in files):
            return "Base game & TTW"
        if re.search(r"\b(fix|fixes|patch|bugfix|yup)\b", mod["name"].lower()):
            return "Bug fixes"
        if "menus" in tops or "uio" in tops:
            return "UI & menus"
        if any(root for _, root in files) or any(f.startswith("nvse/plugins/") for f, _ in files):
            return "Utilities & engine"
        if tops and tops <= {"textures", "meshes"}:
            return "Visuals"
        if any(f.endswith((".esp", ".esm")) and "/" not in f for f, _ in files):
            return "Content"
        return "Other"

    def set_category(self, name, category):
        if category not in CATEGORIES and category is not None:
            raise FolmError(f"unknown category {category!r}; choose from: {', '.join(CATEGORIES)}")
        m = self.mod(name)
        if category is None:
            m.pop("category", None)
        else:
            m["category"] = category
        self.save()

    def sorted_order(self):
        """Mod names ordered by category, never changing who wins a file conflict.

        Every pair of mods that share a file keeps its current relative order
        (loser before winner); otherwise mods go by category, then by their
        current position.
        """
        mods = self.cur["mods"]
        pos = {m["name"]: i for i, m in enumerate(mods)}
        names = set(pos)
        after = self._load_after(names)
        rank = self._effective_ranks(mods, after)
        out, done = [], set()
        while len(out) < len(names):
            ready = [n for n in names - done if after[n] <= done]
            if not ready:                                # shouldn't happen; keep the rest as-is
                ready = sorted(names - done, key=pos.get)[:1]
            n = min(ready, key=lambda x: (rank[x], pos[x]))
            out.append(n)
            done.add(n)
        return out

    def _load_after(self, names):
        """{mod: set of mods it must load after}, from who currently wins each shared file."""
        after = {n: set() for n in names}
        for provs in self.conflicts().values():
            ps = [p for p in provs if p in names]
            for a, b in zip(ps, ps[1:]):
                after[b].add(a)
        return after

    def _effective_ranks(self, mods, after):
        """A patch joins the section of the mod it patches: rank = max(own, everything it loads after)."""
        rank = {m["name"]: CATEGORIES.index(self.category_of(m)) for m in mods}
        changed = True
        while changed:
            changed = False
            for n, deps in after.items():
                r = max([rank[n]] + [rank[d] for d in deps])
                if r != rank[n]:
                    rank[n], changed = r, True
        return rank

    def sections(self):
        """{mod name: the section it's shown under} (a patch is shown with what it patches)."""
        mods = self.cur["mods"]
        names = {m["name"] for m in mods}
        return {n: CATEGORIES[r] for n, r in self._effective_ranks(mods, self._load_after(names)).items()}

    def sort_mods(self):
        """Apply sorted_order(). Returns (old_order, new_order)."""
        old = [m["name"] for m in self.cur["mods"]]
        new = self.sorted_order()
        self.reorder(new)
        return old, new

    # ------------------------------------------------------------ profiles
    def profiles(self):
        return list(self.data["profiles"])

    def create_profile(self, name, copy_from=None):
        ps = self.data["profiles"]
        if name in ps:
            raise FolmError(f"profile {name!r} already exists")
        if copy_from and copy_from not in ps:
            raise FolmError(f"no profile {copy_from!r}")
        ps[name] = json.loads(json.dumps(ps[copy_from])) if copy_from else empty_profile()
        self.save()

    def switch_profile(self, name, log=_quiet):
        if name not in self.data["profiles"]:
            raise FolmError(f"no profile {name!r}")
        was = self.deployed
        if was:
            self.undeploy(log)
        self.data["active"] = name
        self.save()
        if was:
            return self.deploy(log)

    def delete_profile(self, name):
        if name == self.active:
            raise FolmError("can't delete the active profile; switch first")
        if self.data["profiles"].pop(name, None) is None:
            raise FolmError(f"no profile {name!r}")
        self.save()

    # ------------------------------------------------------------ LOOT
    def loot_masterlist(self, log=_quiet, force=False):
        """LOOT's masterlist for this edition (downloaded from LOOT's GitHub, cached a week)."""
        from . import loot
        if getattr(self, "_loot", None) is None or force:
            self._loot = loot.load(loot.update(home(), self.edition, log=log, force=force))
        return self._loot

    def game_view(self):
        """What LOOT's conditions see: the game's Data folder (+ '../' root files) and active plugins."""
        from . import loot
        files = {rel: os.path.join(self.data_dir, rel) for rel in dep.walk_rel(self.data_dir)}
        g = self.data["game_dir"]
        for f in os.listdir(g):
            if os.path.isfile(os.path.join(g, f)):
                files["../" + f] = os.path.join(g, f)
        plugins, _ = loadorder.scan_plugins(self.data_dir)
        dis = {d.lower() for d in self.cur["disabled_plugins"]}
        return loot.GameView(files, [p for p in plugins if p.lower() not in dis], plugins), plugins

    def loot_check(self, log=_quiet):
        """(extra_after, group_rank, messages) for the plugins in the game folder, or None if LOOT is unavailable."""
        try:
            from . import loot
            ml = self.loot_masterlist(log=log)
        except Exception as e:                       # offline and no cache: sort without LOOT
            log(f"  ! LOOT unavailable ({e}); sorting by masters only")
            return None
        view, plugins = self.game_view()
        after, ranks, msgs = loot.evaluate(ml, list(plugins), view)
        return after, ranks, self._apply_handled(msgs)

    # ------------------------------------------------------------ "Marked as handled" LOOT messages
    def handled(self):
        return self.cur.setdefault("handled", [])

    def _handled_entry(self, plugin, text):
        key = ((plugin or "").lower(), text.strip())
        return next((h for h in self.handled() if ((h.get("plugin") or "").lower(), h["text"].strip()) == key), None)

    def _apply_handled(self, msgs):
        """Handled messages become severity 'handled' while the mod that handles them is enabled."""
        enabled = set(self.enabled())
        out = []
        for sev, plugin, text in msgs:
            h = self._handled_entry(plugin, text) if sev in ("error", "warn") else None
            if h and (not h.get("by") or h["by"] in enabled):
                why = f"handled by {h['by']}" if h.get("by") else "marked as handled"
                out.append(("handled", plugin, f"{text}  [{why}{': ' + h['note'] if h.get('note') else ''}]"))
            elif h and h.get("by"):
                out.append((sev, plugin, f"{text}  [was handled by {h['by']}, which is now off or removed]"))
            else:
                out.append((sev, plugin, text))
        return out

    def mark_handled(self, plugin, text, by=None, note=""):
        """Remember that a LOOT error/warning is dealt with (e.g. by a community patch mod)."""
        if by and by not in {x["name"] for x in self.mods()}:
            raise FolmError(f"no mod called {by!r} in this profile")
        text = re.sub(r"\s+\[(handled by|marked as handled|was handled by).*\]$", "", text).strip()
        self.cur["handled"] = [h for h in self.handled()
                               if ((h.get("plugin") or "").lower(), h["text"]) != ((plugin or "").lower(), text)]
        self.cur["handled"].append({"plugin": plugin or "", "text": text, "by": by or None, "note": note.strip(),
                                    "date": time.strftime("%Y-%m-%d")})
        self.save()

    def unmark_handled(self, plugin, text):
        text = re.sub(r"\s+\[(handled by|marked as handled|was handled by).*\]$", "", text).strip()
        before = len(self.handled())
        self.cur["handled"] = [h for h in self.handled()
                               if ((h.get("plugin") or "").lower(), h["text"]) != ((plugin or "").lower(), text)]
        self.save()
        return before != len(self.cur["handled"])

    # ------------------------------------------------------------ game
    def deploy(self, log=_quiet):
        self.need()
        self.finish_interrupted_tool(log)
        self._game_settings(apply=False)          # undo the last run's INI/dxvk changes first (never caught as strays)
        if os.path.exists(self.lo_state):
            loadorder.restore(self.plugins_txt, self.lo_state, log=_quiet)
        names = self.enabled()
        dep.deploy(self.data["game_dir"], self.data_dir, self.mods_dir, names,
                   self.manifest, self.backups, log=log, overwrite_dir=self.overwrite_dir)
        if self.overwrite_name not in names and self.overwrite_name in self.enabled():
            dep.deploy(self.data["game_dir"], self.data_dir, self.mods_dir, self.enabled(),
                       self.manifest, self.backups, log=log, overwrite_dir=self.overwrite_dir)
        lc = self.loot_check(log=log)
        rules = (lc[0], lc[1]) if lc else None
        invalidate = self.setting("archive_invalidation")
        order, active, problems = loadorder.apply(self.data_dir, self.plugins_txt, self.cur["plugin_order"],
                                                  self.cur["disabled_plugins"], self.edition, self.lo_state,
                                                  log=log, rules=rules, redate_bsas=invalidate)
        self._game_settings(apply=True, log=log)
        with open(self.deploy_state, "w") as fh:
            json.dump(self._fingerprint(), fh, indent=1)
        return {"order": order, "active": active, "problems": problems, "loot": lc[2] if lc else [],
                "save_warnings": self.save_warnings(active)}

    def undeploy(self, log=_quiet):
        self.need()
        self.finish_interrupted_tool(log)
        self._game_settings(apply=False, log=log)
        loadorder.restore(self.plugins_txt, self.lo_state, log=log)
        dep.undeploy(self.manifest, log=log, overwrite_dir=self.overwrite_dir)
        if os.path.exists(self.deploy_state):
            os.remove(self.deploy_state)

    # ------------------------------------------------------------ is the game up to date with FOLM?
    def _mod_signature(self, name):
        """Cheap fingerprint of a staged mod's files: count, total size, newest change."""
        n = size = newest = 0
        for dp, _, fn in os.walk(os.path.join(self.mods_dir, name)):
            for f in fn:
                try:
                    st = os.stat(os.path.join(dp, f))
                except OSError:
                    continue
                n, size, newest = n + 1, size + st.st_size, max(newest, st.st_mtime_ns)
        return f"{n}:{size}:{newest}"

    def _fingerprint(self):
        names = [n for n in self.enabled() if n != self.overwrite_name]
        return {"profile": self.active, "order": names, "mods": {n: self._mod_signature(n) for n in names},
                "disabled_plugins": sorted(d.lower() for d in self.cur["disabled_plugins"]),
                "plugin_order": list(self.cur["plugin_order"]), "settings": dict(self.data.get("settings", {}))}

    def pending_changes(self):
        """What the game doesn't have yet, in plain words ([] = the game matches FOLM)."""
        self.need()
        if not self.deployed:
            return ["Your mods aren't in the game yet."] if self.enabled() else []
        try:
            old = json.load(open(self.deploy_state))
        except (OSError, ValueError):
            return ["FOLM hasn't recorded what's in the game yet (deploy once to start tracking changes)."]
        new = self._fingerprint()
        out = []
        if old.get("profile") != new["profile"]:
            return [f"You switched to the profile '{new['profile']}'."]
        before, now = old.get("mods", {}), new["mods"]
        out += [f"New mod: {n}" for n in new["order"] if n not in before]
        out += [f"Turned off: {n}" for n in old.get("order", []) if n not in now]
        out += [f"Updated: {n} (its files changed)" for n in new["order"] if n in before and before[n] != now[n]]
        if [n for n in old.get("order", []) if n in now] != [n for n in new["order"] if n in before]:
            out.append("Mod order changed (which mod wins a file conflict)")
        if old.get("disabled_plugins") != new["disabled_plugins"] or old.get("plugin_order") != new["plugin_order"]:
            out.append("Plugins turned on/off or moved")
        if old.get("settings") != new["settings"]:
            out.append("Game settings changed (⚙ Settings)")
        return out

    # ------------------------------------------------------------ settings
    SETTINGS = {
        "archive_invalidation": (True, "Archive invalidation: loose mod files override the game's archives"),
        "profile_saves": (True, "Separate saves per profile (the Default profile keeps the normal Saves folder)"),
        "fps_cap": (120, "FPS cap through DXVK, keeps physics stable with V-Sync off (0 = off)"),
        "borderless": (True, "Borderless window: no title bar, so the whole picture fits the screen"),
    }

    def setting(self, key):
        return self.data.get("settings", {}).get(key, self.SETTINGS[key][0])

    def set_setting(self, key, value):
        if key not in self.SETTINGS:
            raise FolmError(f"unknown setting {key!r}; choose from: {', '.join(self.SETTINGS)}")
        default = self.SETTINGS[key][0]
        if isinstance(default, bool):
            value = bool(value)
        elif isinstance(default, int):
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise FolmError(f"{key} needs a number")
            if value < 0 or value > 1000:
                raise FolmError(f"{key} must be between 0 and 1000")
        self.data.setdefault("settings", {})[key] = value
        self.save()

    ARCHIVE_KEYS = {"bInvalidateOlderFiles": "1", "SInvalidationFile": ""}
    ini_state = property(lambda s: os.path.join(s.dir, "ini-state.json"))

    def ini_dir(self):
        return os.path.join(self.data["prefix"], "pfx/drive_c/users/steamuser/Documents/My Games",
                            os.path.basename(game_info(self.edition)["ini_dir"]))

    def _profile_save_folder(self):
        """Saves subfolder for this profile (None = the game's normal Saves folder)."""
        if not self.setting("profile_saves") or self.active == "Default":
            return None
        return re.sub(r'[\\/:*?"<>|]', "_", self.active)

    def save_dir(self):
        sub = self._profile_save_folder()
        base = os.path.join(self.ini_dir(), "Saves")
        return os.path.join(base, sub) if sub else base

    def _game_settings(self, apply, log=_quiet):
        """Write (apply) or undo FOLM's game settings, reversibly.

        - archive invalidation: [Archive] keys in FalloutCustom.ini (JIP LN) or Fallout.ini
        - per-profile saves:    [General] SLocalSavePath in Fallout.ini
        - FPS cap:              d3d9.maxFrameRate in the game folder's dxvk.conf
        Fallout.ini and an existing dxvk.conf are backed up before FOLM first touches them.
        """
        from . import ini
        if os.path.exists(self.ini_state):
            st = json.load(open(self.ini_state))
            entries = st.get("ini") or ([{"path": st["path"], "section": "Archive", "previous": st["previous"]}]
                                        if "path" in st else [])
            for e in reversed(entries):
                ini.restore_keys(e["path"], e["section"], e["previous"])
            for f in st.get("files", []):
                if f.get("backup") and os.path.exists(f["backup"]):
                    shutil.move(f["backup"], f["path"])
                elif os.path.exists(f["path"]):
                    os.remove(f["path"])
            if st.get("dll_overrides"):
                from . import wineprefix
                if wineprefix.prefix_busy(self.data["prefix"]):
                    raise FolmError("The game (or another Wine program) is still running in this game's prefix. "
                                    "Close it, then try again.")
                wineprefix.set_overrides(self.data["prefix"], st["dll_overrides"])
            os.remove(self.ini_state)
        if not apply:
            return
        st, done = {"ini": [], "files": []}, []
        jip = dep.exists_ci(self.data_dir, "NVSE/Plugins/jip_nvse.dll")
        custom = os.path.join(self.ini_dir(), "FalloutCustom.ini")
        game_ini = os.path.join(self.ini_dir(), "Fallout.ini")

        def save_state():                    # after every change, so a failure part-way can still be undone
            with open(self.ini_state, "w") as fh:
                json.dump(st, fh, indent=1)

        def edit(path, section, keys):
            if path == game_ini and os.path.exists(path):
                bak = os.path.join(self.dir, "backups", "Fallout.ini.folm-backup")
                if not os.path.exists(bak):
                    os.makedirs(os.path.dirname(bak), exist_ok=True)
                    shutil.copy2(path, bak)
            st["ini"].append({"path": path, "section": section, "previous": ini.set_keys(path, section, keys)})
            save_state()

        if self.setting("archive_invalidation"):
            edit(custom if jip else game_ini, "Archive", self.ARCHIVE_KEYS)
            done.append(f"archive invalidation ({'FalloutCustom.ini' if jip else 'Fallout.ini'})")
        sub = self._profile_save_folder()
        if sub:
            os.makedirs(self.save_dir(), exist_ok=True)
            edit(game_ini, "General", {"SLocalSavePath": f"Saves\\{sub}\\"})
            done.append(f"saves in Saves/{sub}")
        # Mods that ship a proxy DLL next to the exe (e.g. NVHR's d3dx9_38.dll): make Wine load it
        from . import wineprefix
        mf = json.load(open(self.manifest)) if os.path.exists(self.manifest) else {"files": []}
        proxies = {}
        for dll, mod in wineprefix.needed(self.data["game_dir"], mf):
            proxies.setdefault(dll, mod)
        if proxies and os.path.exists(wineprefix.user_reg(self.data["prefix"])):
            if wineprefix.prefix_busy(self.data["prefix"]):
                log("Wine DLL overrides skipped: the game's prefix is in use. Deploy again after closing the game.")
            else:
                todo = {d: wineprefix.NATIVE_FIRST for d in proxies
                        if (wineprefix.get(self.data["prefix"], d) or "").replace(" ", "") != wineprefix.NATIVE_FIRST}
                if todo:
                    st["dll_overrides"] = wineprefix.set_overrides(self.data["prefix"], todo)
                    save_state()
                done.append("Wine loads " + ", ".join(f"{d}.dll ({proxies[d]})" for d in sorted(proxies)))
        cap = int(self.setting("fps_cap") or 0)
        if cap > 0:
            conf = os.path.join(self.data["game_dir"], "dxvk.conf")
            bak = None
            lines = []
            if os.path.exists(conf):
                # Move it aside rather than editing it: a dxvk.conf deployed from a mod is a hard link to the
                # mod's own copy, and writing to it would change the mod. Moving keeps the link intact for restore.
                bak = os.path.join(self.dir, "backups", "dxvk.conf.folm-backup")
                os.makedirs(os.path.dirname(bak), exist_ok=True)
                with open(conf) as fh:
                    lines = [l for l in fh.read().splitlines() if not l.strip().startswith("d3d9.maxFrameRate")]
                if os.path.exists(bak):
                    os.remove(bak)
                shutil.move(conf, bak)
            lines.append(f"d3d9.maxFrameRate = {cap}")
            with open(conf, "w") as fh:
                fh.write("\n".join(lines) + "\n")
            st["files"].append({"path": conf, "backup": bak})
            save_state()
            done.append(f"FPS cap {cap}")
        with open(self.ini_state, "w") as fh:
            json.dump(st, fh, indent=1)
        if done:
            log("Game settings: " + ", ".join(done) + ".")

    # ------------------------------------------------------------ saves + pre-Play checks
    def save_warnings(self, active=None):
        """[(save, [plugins it needs that won't be active])] for this profile's newest saves."""
        from . import saves
        if active is None:
            rows, _ = self.plugin_order()
            active = [n for n, on, _, _ in rows if on]
        return saves.check(self.save_dir(), active)

    def saves_needing(self, plugins):
        """Newest saves (of this profile) that use any of these plugins: [(save, [plugins])]."""
        from . import saves
        want = {p.lower() for p in plugins}
        out = []
        for path, _ in saves.list_saves(self.save_dir())[:3]:
            used = [p for p in (saves.plugins_in_save(path) or []) if p.lower() in want]
            if used:
                out.append((os.path.basename(path), used))
        return out

    def mod_plugins(self, name):
        """Plugin files at the top of a staged mod's folder."""
        d = os.path.join(self.mods_dir, name)
        return sorted(f for f in os.listdir(d) if f.lower().endswith((".esm", ".esp"))) if os.path.isdir(d) else []

    def _exe_is_4gb(self):
        exe = os.path.join(self.data["game_dir"], game_info(self.edition)["exe"])
        try:
            with open(exe, "rb") as fh:
                d = fh.read(4096)
            pe = struct.unpack_from("<I", d, 0x3C)[0]
            return bool(struct.unpack_from("<H", d, pe + 22)[0] & 0x20)
        except (OSError, struct.error):
            return None

    def preflight(self):
        """Checks before Play: [(severity, message)], severity 'error' or 'warn'."""
        self.need()
        out = []
        if not self.deployed:
            out.append(("warn", "Your mods aren't deployed, so the game will start without them."))
        if subprocess.run(["pgrep", "-x", "steam"], capture_output=True).returncode != 0:
            out.append(("warn", "Steam isn't running. FOLM will try to start it, but the game may show "
                                "'Application load error 65434' if Steam isn't ready."))
        from . import requires
        for r in requires.check(self):
            if r["severity"] in ("error", "warn"):
                out.append((r["severity"], requires.describe(r)))
        if self._exe_is_4gb() is False and dep.exists_ci(self.data_dir, "NVSE/Plugins") is not None:
            out.append(("error", f"{game_info(self.edition)['exe']} isn't 4GB-patched any more (verifying files in "
                                 "Steam undoes it). Re-run the 4GB patcher, or xNVSE and its plugins won't load."))
        plugins_dir = dep.exists_ci(self.data_dir, "NVSE/Plugins")
        if plugins_dir and any(f.lower().endswith(".dll") for f in os.listdir(plugins_dir)) \
                and not dep.exists_ci(self.data["game_dir"], "nvse_steam_loader.dll"):
            out.append(("error", "NVSE plugins are installed but xNVSE isn't: they won't load."))
        if self.deployed:
            rows, problems = self.plugin_order()
            missing, other = {}, []
            for p in problems:
                mm = re.match(r"(.+?) needs missing master (.+)$", p)
                (missing.setdefault(mm.group(1), []).append(mm.group(2)) if mm else other.append(p))
            out += [("error", f"{pl} needs missing master{'s' if len(ms) > 1 else ''}: {', '.join(ms)}")
                    for pl, ms in missing.items()] + [("error", p) for p in other]
            out += [("error", f"LOOT: {pl + ': ' if pl else ''}{t}")
                    for sev, pl, t in getattr(self, "last_loot_messages", []) if sev == "error"]
            for save, miss in self.save_warnings([n for n, on, _, _ in rows if on]):
                out.append(("warn", f"Save '{save}' uses {', '.join(miss[:4])}{' …' if len(miss) > 4 else ''}, "
                                    "which won't be loaded. Loading it can break quests and scripts."))
        for mod, plugin, src in self.stale_tool_output():
            out.append(("warn", f"{plugin} in '{mod}' was made from an older version of '{src}' (it was updated "
                                f"since). Redo that change in xEdit, or turn '{mod}' off."))
        if not int(self.setting("fps_cap") or 0):
            from . import ini
            vsync = ini.get(os.path.join(self.ini_dir(), "FalloutCustom.ini"), "Display", "iPresentInterval") \
                or ini.get(os.path.join(self.ini_dir(), "FalloutPrefs.ini"), "Display", "iPresentInterval")
            if vsync == "0":
                out.append(("warn", "V-Sync is off and there's no FPS cap: above ~120 FPS physics can break "
                                    "(bouncing NPCs). Turn on the FPS cap in Settings."))
        return out

    def catch(self, log=_quiet):
        self.need()
        if not self.deployed:
            raise FolmError("Nothing is deployed, so there's nothing to catch.")
        return self._catch_into(self.overwrite_dir, log)

    def _catch_into(self, target, log=_quiet):
        """Collect stray game-folder files into `target`, leaving FOLM's own settings files (dxvk.conf
        for the FPS cap) out of it: they're undone first and written again afterwards."""
        self._game_settings(apply=False)
        try:
            return dep.catch(self.manifest, target, log)
        finally:
            self._game_settings(apply=True)

    def plugin_order(self):
        """[(name, active, load_index_or_None)], problems."""
        self.need()
        plugins, bad = loadorder.scan_plugins(self.data_dir)
        lc = self.loot_check()
        extra, ranks = (lc[0], lc[1]) if lc else ({}, {})
        order, problems = loadorder.sort_plugins(plugins, self.cur["plugin_order"], self.edition, extra, ranks)
        self.last_loot_messages = lc[2] if lc else []
        dis = {d.lower() for d in self.cur["disabled_plugins"]}
        rows, i = [], 0
        for n in order:
            on = n.lower() not in dis
            rows.append((n, on, i if on else None, plugins[n]["masters"]))
            i += on
        return rows, bad + problems

    def set_plugin_active(self, name, on):
        dis = [d for d in self.cur["disabled_plugins"] if d.lower() != name.lower()]
        if not on:
            dis.append(name)
        self.cur["disabled_plugins"] = dis
        self.save()

    def conflicts(self, only=None):
        self.need()
        baseline = None
        if self.deployed:
            with open(self.manifest) as fh:
                baseline = json.load(fh).get("baseline")
        c = dep.conflicts(self.data["game_dir"], self.data_dir, self.mods_dir, self.enabled(), baseline)
        if only:
            c = {p: v for p, v in c.items() if any(x.lower() == only.lower() for x in v)}
        return c

    def conflict_marks(self):
        """{mod_name: (files_won, files_lost)} for the mod list's conflict icons."""
        marks = {}
        for path, provs in self.conflicts().items():
            for i, m in enumerate(provs):
                w, l = marks.get(m, (0, 0))
                marks[m] = (w + 1, l) if i == len(provs) - 1 else (w, l + 1)
        return marks

    def overwrite_files(self):
        d = self.overwrite_dir
        return sorted(dep.walk_rel(d)) if os.path.isdir(d) else []

    # ------------------------------------------------------------ library + launch
    def library_folders(self):
        return self.data.setdefault("library_folders", [])

    def add_library_folder(self, folder):
        f = os.path.abspath(os.path.expanduser(folder))
        if f not in self.library_folders():
            self.library_folders().append(f)
            self.save()

    def remove_library_folder(self, folder):
        if folder in self.library_folders():
            self.library_folders().remove(folder)
            self.save()

    def scan_library(self):
        """Detect every mod file in the library folders; unreadable ones come back as type 'error'."""
        out = []
        for p in detect.scan(self.library_folders()):
            try:
                out.append(detect.detect(p))
            except (ValueError, OSError) as e:
                out.append({"source": p, "type": "error", "warnings": [str(e)], "plugins": []})
        return out

    # ------------------------------------------------------------ GECK (mod making)
    GECK_SETTINGS = {"General": {"bAllowMultipleMasterLoads": "1", "bUseMultibounds": "0"}}

    GECK_EXES = ("geck.exe", "fallout3 - garden of eden creation kit.exe")

    def geck_path(self):
        g = self.data["game_dir"]
        for f in sorted(os.listdir(g)):
            if f.lower() in self.GECK_EXES:
                return os.path.join(g, f)
        return None

    def _geck_ini(self):
        """Make GECK accept several master files (needed to build anything that uses a DLC or another mod's ESM)."""
        d = os.path.join(self.data["prefix"], "pfx/drive_c/users/steamuser/Documents/My Games",
                         os.path.basename(game_info(self.edition)["ini_dir"]))
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "GECKCustom.ini")
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines() if os.path.exists(path) else []
        for section, keys in self.GECK_SETTINGS.items():
            if f"[{section}]" not in [l.strip() for l in lines]:
                lines += ["", f"[{section}]"]
            at = [l.strip() for l in lines].index(f"[{section}]")
            for k, v in keys.items():
                if not any(l.split("=", 1)[0].strip().lower() == k.lower() for l in lines):
                    lines.insert(at + 1, f"{k}={v}")
        open(path, "w").write("\n".join(lines).strip() + "\n")
        return path

    def geck(self, edit_mod=None, log=_quiet, runner=None):
        """Open GECK with this profile's mods; when it closes, capture what was saved.

        edit_mod: put changes back into that mod. Otherwise new files go to this
        profile's Overwrite, and keep_as_mod() turns them into a new mod.
        Returns the list of captured files (game-relative).
        """
        self.need()
        if edit_mod:
            self.mod(edit_mod)
        exe = self.geck_path()
        if not exe and runner is None:
            raise FolmError("GECK isn't installed. In Steam: Library > Tools > " + (
                            "'Fallout 3 Garden of Eden Creation Kit'" if self.edition == "wanderer" else
                            "'Fallout New Vegas: Garden of Eden Creation Kit'") + " (it installs into the game folder).")
        if not self.deployed:
            self.deploy(log)
        self._geck_ini()
        before = set(self.overwrite_files())
        if runner:
            runner()
        else:
            g = self.data["game_dir"]
            from . import wintool
            try:
                wine, _ = wintool.find_wine([STEAM, os.path.expanduser("~/.steam/steam")], steam_libraries())
            except wintool.ToolError as e:
                raise FolmError(f"to run GECK, {e}")
            from .requires import LOADERS
            name = next((f for f in os.listdir(g) if f.lower() == LOADERS[self.edition]), None)
            cmd = [wine, name, "-editor"] if name else [wine, os.path.basename(exe)]   # with xNVSE / FOSE
            env = dict(os.environ, WINEPREFIX=os.path.join(self.data["prefix"], "pfx"), WINEDEBUG="-all")
            log("Opening GECK (close it when you're done; FOLM will collect what you saved)...")
            subprocess.Popen(cmd, cwd=g, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait()
            time.sleep(3)
            while subprocess.run(["pgrep", "-fi", "[g]eck.exe|[g]arden of eden creation kit.exe"],
                                 capture_output=True).returncode == 0:
                time.sleep(2)                       # nvse_loader returns early; wait for GECK itself
        target = os.path.join(self.mods_dir, edit_mod) if edit_mod else self.overwrite_dir
        self._catch_into(target, log)
        if edit_mod:
            got = sorted(dep.walk_rel(target))
            log(f"Changes saved into {edit_mod!r}. Deploy to put them in the game.")
            return got
        got = sorted(set(self.overwrite_files()) - before)
        log(f"GECK closed: {len(got)} new or changed file(s) collected." if got else "GECK closed: nothing new was saved.")
        return got

    def keep_as_mod(self, name):
        """Turn this profile's Overwrite (e.g. what you just saved in GECK) into a new mod."""
        src = self.overwrite_dir
        if not os.path.isdir(src) or not os.listdir(src):
            raise FolmError("there's nothing in Overwrite to keep")
        dest = os.path.join(self.mods_dir, name)
        if os.path.exists(dest):
            raise FolmError(f"a mod called {name!r} already exists")
        was = self.deployed
        if was:
            self.undeploy()
        os.rename(src, dest)
        self.cur["mods"].append({"name": name, "enabled": True, "type": "folder", "notes": "Made in GECK.",
                                 "tags": ["ours"], "category": "Our mods"})
        self.save()
        if was:
            self.deploy()
        return name

    # ------------------------------------------------------------ Tools tab (xEdit, xLODGen)
    def tools_status(self):
        """Every tool in the catalog with whether it's installed here: [{id, name, what, how, get, exe}]."""
        from . import tools
        out = []
        for t in tools.CATALOG:
            if t["id"] == "geck":
                exe = self.geck_path() if self.data.get("game_dir") and os.path.isdir(self.data["game_dir"]) else None
            else:
                exe = tools.find_exe(tools.tools_dir(home(), t["id"]), t["id"], self.edition)
            out.append({"id": t["id"], "name": t["names"][self.edition], "what": t["what"], "how": t["how"],
                        "get": t["get"][self.edition], "exe": exe})
        return out

    def install_tool(self, archive, tool_id, log=_quiet):
        """Unpack a tool download into FOLM's tools folder (replacing an older copy). Not deployed."""
        from . import tools
        dest = tools.tools_dir(home(), tool_id)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = tempfile.mkdtemp(prefix=f".{tool_id}-", dir=os.path.dirname(dest))
        try:
            if archive.lower().endswith(".exe"):
                shutil.copy2(archive, os.path.join(tmp, os.path.basename(archive)))
            else:
                archive_mod.extract(archive, tmp)
            if not tools.find_exe(tmp, tool_id, self.edition):
                raise FolmError(f"{os.path.basename(archive)} doesn't contain the tool's program")
            keep = os.path.join(dest, "FOLM backups")          # xEdit backups survive an update
            if os.path.isdir(keep):
                shutil.move(keep, os.path.join(tmp, "FOLM backups"))
            if os.path.isdir(dest):
                shutil.rmtree(dest)
            os.rename(tmp, dest)
        except archive_mod.ArchiveError as e:
            raise FolmError(str(e))
        finally:
            if os.path.isdir(tmp):
                shutil.rmtree(tmp, ignore_errors=True)
        name = tools.BY_ID[tool_id]["names"][self.edition]
        log(f"Installed the tool {name}. Open it from the Tools tab.")
        return name, {"type": "tool", "tool": tool_id, "warnings": []}

    # xEdit and xLODGen can save over any plugin they load. A "tool session" makes that safe:
    #  * the game's own plugins (Fallout3.esm, DLC ESMs) are copied aside first,
    #  * each deployed mod plugin (normally a hard link to the mod's own file) is swapped for a copy, so
    #    nothing a tool writes can reach the mod's original,
    #  * the tool's earlier output is snapshotted (hard links: no extra space),
    #  * a journal on disk lists all of it, so if FOLM is closed or crashes mid-run, the next deploy,
    #    undeploy or tool run finishes the job: changed plugins go into the tool's mod, originals go back.
    TOOL_PLUGINS = (".esm", ".esp", ".esl")

    def _tool_session_dir(self):
        return os.path.join(home(), "tools", f"session-{self.edition}")

    def _begin_tool_session(self, target, log=_quiet):
        sd = self._tool_session_dir()
        if os.path.exists(os.path.join(sd, "journal.json")):
            self._finish_tool_session(log)
        if os.path.isdir(sd):
            shutil.rmtree(sd)
        os.makedirs(os.path.join(sd, "game"))
        ours, mf = set(), {"files": []}
        if os.path.exists(self.manifest):
            with open(self.manifest) as fh:
                mf = json.load(fh)
            ours = {os.path.normpath(r["target"]) for r in mf.get("files", [])}
        game = [f for f in (os.listdir(self.data_dir) if os.path.isdir(self.data_dir) else [])
                if f.lower().endswith(self.TOOL_PLUGINS) and os.path.isfile(os.path.join(self.data_dir, f))
                and not os.path.islink(os.path.join(self.data_dir, f))
                and os.path.normpath(os.path.join(self.data_dir, f)) not in ours]
        linked = [r for r in mf.get("files", []) if r.get("how") == "link"
                  and r["target"].lower().endswith(self.TOOL_PLUGINS)
                  and os.path.exists(r["target"]) and os.path.exists(r["source"])
                  and os.path.samefile(r["target"], r["source"])]
        need = sum(os.path.getsize(os.path.join(self.data_dir, f)) for f in game) + \
            sum(os.path.getsize(r["source"]) for r in linked)
        free = min(shutil.disk_usage(sd).free, shutil.disk_usage(self.data_dir).free)
        if free < need + (512 << 20):
            shutil.rmtree(sd, ignore_errors=True)
            raise FolmError(f"Not enough free disk space to protect your plugins while the tool runs: it needs "
                            f"about {(need >> 20) + 512} MB free, there's {free >> 20} MB. Free some space and try again.")
        journal = {"target": target, "game": {}, "linked": [], "snapshot": None}
        if os.path.isdir(target) and os.listdir(target):          # the tool's earlier work, kept
            snap = os.path.join(self._tool_history_dir(target), time.strftime("%Y-%m-%d_%H%M%S"))
            for rel in dep.walk_rel(target):
                d = os.path.join(snap, rel)
                os.makedirs(os.path.dirname(d), exist_ok=True)
                try:
                    os.link(os.path.join(target, rel), d)
                except OSError:
                    shutil.copy2(os.path.join(target, rel), d)
            journal["snapshot"] = snap
            self._prune_history(target)
        jpath = os.path.join(sd, "journal.json")

        def write():
            with open(jpath + ".tmp", "w") as fh:
                json.dump(journal, fh, indent=1)
            os.replace(jpath + ".tmp", jpath)
        write()                                                    # before anything is changed
        if game or linked:
            log(f"  protecting {len(game) + len(linked)} plugin(s) while the tool runs "
                f"({(need >> 20)} MB copied; this takes a moment)")
        for f in game:
            p = os.path.join(self.data_dir, f)
            shutil.copy2(p, os.path.join(sd, "game", f))
            st = os.stat(p)
            journal["game"][f] = [st.st_ino, st.st_size, st.st_mtime_ns]
            write()
        for r in linked:
            t = r["target"]
            tmp = t + ".folm-copy"
            shutil.copy2(r["source"], tmp)                         # keeps the date (Fallout 3's load order)
            os.replace(tmp, t)                                     # the game folder now has a separate copy
            st = os.stat(t)
            journal["linked"].append({"target": t, "source": r["source"],
                                      "stat": [st.st_ino, st.st_size, st.st_mtime_ns]})
            write()
        return journal

    def _tool_history_dir(self, target):
        return os.path.join(home(), "tools", "earlier output", self.edition, os.path.basename(target))

    def _prune_history(self, target, keep=10):
        d = self._tool_history_dir(target)
        runs = sorted(os.listdir(d)) if os.path.isdir(d) else []
        for old in runs[:-keep]:
            shutil.rmtree(os.path.join(d, old), ignore_errors=True)

    def _finish_tool_session(self, log=_quiet):
        """Put the game folder back the way FOLM left it; what the tool changed goes into its mod.
        Returns {"changed": n, "made_from": {rel: {"from", "fp"}}}. Safe to run again after a crash."""
        sd = self._tool_session_dir()
        jpath = os.path.join(sd, "journal.json")
        if not os.path.exists(jpath):
            return {"changed": 0, "made_from": {}}
        with open(jpath) as fh:
            journal = json.load(fh)
        target = journal["target"]
        changed, made_from = 0, {}

        def into_mod(p, rel):
            d = os.path.join(target, rel)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            if os.path.lexists(d):
                os.remove(d)                     # (the earlier version is in the snapshot)
            shutil.move(p, d)

        for f, was in journal["game"].items():
            copy, p = os.path.join(sd, "game", f), os.path.join(self.data_dir, f)
            if not os.path.exists(copy):
                continue
            now = os.stat(p) if os.path.exists(p) else None
            if now and [now.st_ino, now.st_size, now.st_mtime_ns] == was:
                os.remove(copy)
                continue
            if now:
                made_from[f] = {"from": "game", "fp": self.file_fingerprint(copy)}
                into_mod(p, f)
                changed += 1
                log(f"  {f} (a game file) was changed: the new version is in {os.path.basename(target)!r}, "
                    "the original is back in the game folder")
            shutil.move(copy, p)
        for rec in journal["linked"]:
            t, s = rec["target"], rec["source"]
            if os.path.exists(t) and os.path.exists(s) and os.path.samefile(t, s):
                continue                          # never swapped (FOLM stopped before this one)
            if os.path.exists(t):
                st = os.stat(t)
                if [st.st_ino, st.st_size, st.st_mtime_ns] != rec["stat"]:
                    rel = os.path.relpath(t, self.data_dir)
                    if rel.startswith(".."):
                        rel = os.path.join(dep.ROOT_DIR, os.path.relpath(t, self.data["game_dir"]))
                    inside = os.path.commonpath([os.path.abspath(s), os.path.abspath(target)]) == \
                        os.path.abspath(target)
                    if not inside:
                        made_from[rel] = {"from": s, "fp": self.file_fingerprint(s)}
                    into_mod(t, rel)
                    changed += 1
                else:
                    os.remove(t)                  # unchanged copy
            if not os.path.lexists(t) and os.path.exists(s):
                os.link(s, t)                     # back to the normal hard link
        # half-written saves (xEdit stopped while saving) don't belong in a mod
        for f in os.listdir(self.data_dir) if os.path.isdir(self.data_dir) else []:
            if re.search(r"\.(esm|esp|esl)\.save(\.|$)", f, re.I) or f.lower().endswith(".folm-copy"):
                d = os.path.join(sd + "-unfinished", f)
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.move(os.path.join(self.data_dir, f), d)
                log(f"  {f} looks like an unfinished save; kept aside in {os.path.dirname(d)}")
        os.remove(jpath)
        shutil.rmtree(sd, ignore_errors=True)
        return {"changed": changed, "made_from": made_from}

    def finish_interrupted_tool(self, log=_quiet):
        """If a tool run was interrupted (FOLM closed or crashed), finish it now."""
        if not os.path.exists(os.path.join(self._tool_session_dir(), "journal.json")):
            return None
        log("Finishing an xEdit/xLODGen run that was interrupted...")
        with open(os.path.join(self._tool_session_dir(), "journal.json")) as fh:
            target = json.load(fh)["target"]
        res = self._finish_tool_session(log)
        if res["changed"]:
            self._register_tool_mod(os.path.basename(target), "a tool", res["made_from"])
        return res

    def _register_tool_mod(self, mod_name, tool_name, made_from):
        target = os.path.join(self.mods_dir, mod_name)
        if not os.path.isdir(target) or not os.listdir(target):
            return False
        entry = next((x for x in self.cur["mods"] if x["name"] == mod_name), None)
        if entry is None:
            entry = {"name": mod_name, "enabled": True, "type": "folder", "tags": ["ours"],
                     "notes": f"Made by {tool_name} in FOLM. Earlier versions: {self._tool_history_dir(target)}",
                     "category": "Our mods"}
        else:
            self.cur["mods"].remove(entry)
        entry["enabled"] = True
        entry.setdefault("made_from", {}).update(made_from)
        self.cur["mods"].append(entry)            # last, so its edits win over the plugins they came from
        self.save()
        return True

    def stale_tool_output(self):
        """[(mod, plugin, source mod)] for tool-made plugins whose original has changed since (mod updated)."""
        out = []
        for x in self.mods():
            if not x.get("enabled"):
                continue
            for rel, info in (x.get("made_from") or {}).items():
                src = info.get("from")
                if not src or src == "game" or not os.path.exists(os.path.join(self.mods_dir, x["name"], rel)):
                    continue
                now = self.file_fingerprint(src) if os.path.exists(src) else None
                if now and info.get("fp") and now != info["fp"]:
                    out.append((x["name"], os.path.basename(rel), os.path.relpath(src, self.mods_dir).split(os.sep)[0]))
        return out

    def run_tool(self, tool_id, log=_quiet, runner=None, extra_args=()):
        """Run xEdit or xLODGen on this profile's mods (deployed first). What it saves becomes a mod:
        "xEdit output" / "Generated LOD" (made, or added to, and enabled). Returns that mod's name or None.
        Your mods' files and the game's own plugins can't be changed by it (see _begin_tool_session)."""
        from . import tools, wintool, wineprefix
        self.need()
        if tool_id == "geck":
            return self.geck(log=log, runner=runner)
        info = next(t for t in self.tools_status() if t["id"] == tool_id)
        exe = info["exe"]
        if not exe and runner is None:
            raise FolmError(f"{info['name']} isn't installed. {tools.BY_ID[tool_id]['how']} ({info['get']})")
        if runner is None and wineprefix.prefix_busy(self.data["prefix"]):
            raise FolmError(f"Close the game first: {info['name']} can't work on files the game has open.")
        if runner is None:
            try:
                wine, _ = wintool.find_wine([STEAM, os.path.expanduser("~/.steam/steam")], steam_libraries())
            except wintool.ToolError as e:
                raise FolmError(f"to run {info['name']}, {e}")
        if not self.deployed:
            self.deploy(log)
        mod_name = tools.OUTPUT_MOD[tool_id]
        target = os.path.join(self.mods_dir, mod_name)
        os.makedirs(os.path.join(home(), "tools"), exist_ok=True)
        work = tempfile.mkdtemp(prefix=f".run-{tool_id}-", dir=os.path.join(home(), "tools"))
        out = os.path.join(work, "output")
        os.makedirs(out)
        self._begin_tool_session(target, log)
        try:
            if runner:
                runner(out)
            else:
                cmd = [wine, os.path.basename(exe)] + tools.args_for(tool_id, self.edition, self.data_dir, out) \
                    + list(extra_args)
                env = dict(os.environ, WINEPREFIX=os.path.join(self.data["prefix"], "pfx"), WINEDEBUG="-all")
                log(f"Opening {info['name']} (close it when you're done; FOLM collects what it saved)...")
                subprocess.Popen(cmd, cwd=os.path.dirname(exe), env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait()
                b = os.path.basename(exe)
                while subprocess.run(["pgrep", "-fi", f"[{b[0]}]{re.escape(b[1:])}"],
                                     capture_output=True).returncode == 0:
                    time.sleep(2)
        finally:
            res = self._finish_tool_session(log)        # always: even if the tool or FOLM failed
        try:
            got = res["changed"]
            # xEdit's backups and cache go with the tool, not into a mod
            keep = os.path.join(tools.tools_dir(home(), tool_id), "FOLM backups", self.edition)
            if os.path.isdir(self.data_dir):
                for d in os.listdir(self.data_dir):
                    if tools.is_tool_clutter(d) and os.path.isdir(os.path.join(self.data_dir, d)):
                        dest = os.path.join(keep, d)
                        os.makedirs(dest, exist_ok=True)
                        for rel in dep.walk_rel(os.path.join(self.data_dir, d)):
                            os.makedirs(os.path.dirname(os.path.join(dest, rel)), exist_ok=True)
                            shutil.move(os.path.join(self.data_dir, d, rel), os.path.join(dest, rel))
                        shutil.rmtree(os.path.join(self.data_dir, d), ignore_errors=True)
            got += self._catch_into(target, log)
            for rel in dep.walk_rel(out):
                d = os.path.join(target, rel)
                os.makedirs(os.path.dirname(d), exist_ok=True)
                if os.path.lexists(d):
                    os.remove(d)
                shutil.move(os.path.join(out, rel), d)
                got += 1
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if not self._register_tool_mod(mod_name, info["name"], res["made_from"]):
            if os.path.isdir(target):
                os.rmdir(target)
            log(f"{info['name']} closed: nothing was saved.")
            return None
        self.deploy(log)
        log(f"{info['name']} closed: {got} file(s) saved into the mod {mod_name!r} (enabled and deployed). "
            "Turn that mod off to undo it.")
        return mod_name

    def clean_plugin(self, plugin, log=_quiet, runner=None):
        """Clean a plugin LOOT says is dirty, with xEdit's Quick Auto Clean. The cleaned copy goes into
        'xEdit output' (turn it off to undo); the mod's own file and the game's files stay as they were."""
        if plugin.lower() in ("falloutnv.esm", "fallout3.esm"):
            raise FolmError(f"{plugin} is the game's main file: it should never be cleaned.")
        log(f"Cleaning {plugin} with xEdit (Quick Auto Clean). Its window closes by itself when it's done.")
        return self.run_tool("xedit", log=log, runner=runner,
                             extra_args=["-QAC", "-autoexit", "-autoload", plugin])

    def latest_session(self):
        d = os.path.join(self.dir, "sessions")
        runs = sorted(os.listdir(d)) if os.path.isdir(d) else []
        return os.path.join(d, runs[-1]) if runs else None

    def crash_report(self, session=None):
        """(Re)build the crash report for a play session (default: the latest). Returns (path, crashed, findings)."""
        from . import crash
        session = session or self.latest_session()
        if not session:
            raise FolmError("no play sessions recorded yet (launch with Play first)")
        return crash.write_report(session, self.data["game_dir"])

    def play_watched(self, log=_quiet, stop=None):
        """Launch through Steam, watch the session, write a report when the game exits."""
        from . import crash
        session = crash.start(self)
        self.launch()
        if self.setting("borderless"):
            from . import window
            window.borderless_when_ready(self.edition, log=log, stop=stop)
        log("Game launched; FOLM is watching for crashes...")
        seen = crash.watch(session, stop=stop)
        if not seen:
            log("The game didn't seem to start within 3 minutes.")
        path, crashed, findings = crash.write_report(session, self.data["game_dir"])
        log(("Crash detected. " if crashed else "Game closed normally. ") + f"Report: {path}")
        return {"report": path, "crashed": crashed, "findings": findings, "started": seen}

    def launch(self):
        """Start the game through Steam (Proton handles the rest)."""
        self.need()
        app = self.data.get("steam_app_id") or game_info(self.edition)["steam_app_id"]
        steam = shutil.which("steam")
        if not steam:
            raise FolmError("Steam isn't on PATH.")
        subprocess.Popen([steam, "-applaunch", str(app)], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return app
