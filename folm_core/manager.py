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
import glob

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
        return re.sub(r"(-\d+)+.*$|\.(7z|zip|rar)$", "", os.path.basename(archive)).strip() or "mod"

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

    def install(self, archive, name=None, chooser=None, log=_quiet):
        """Stage a mod from an archive. Returns (name, detect_result).

        FOMOD (XML) mods need a chooser(step, group) -> [option indexes]; without one,
        the installer's defaults (required + recommended options) are used.
        """
        self.need()
        r = detect.detect(archive)
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
                return self.install(inner, name, chooser=chooser, log=log)
        if r["type"] not in ("data", "data+game-root", "game-root"):
            raise FolmError(f"FOLM can't install '{r['type']}' mods yet.")
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
        return loot.evaluate(ml, list(plugins), view)

    # ------------------------------------------------------------ game
    def deploy(self, log=_quiet):
        self.need()
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
        return {"order": order, "active": active, "problems": problems, "loot": lc[2] if lc else [],
                "save_warnings": self.save_warnings(active)}

    def undeploy(self, log=_quiet):
        self.need()
        self._game_settings(apply=False, log=log)
        loadorder.restore(self.plugins_txt, self.lo_state, log=log)
        dep.undeploy(self.manifest, log=log, overwrite_dir=self.overwrite_dir)

    # ------------------------------------------------------------ settings
    SETTINGS = {
        "archive_invalidation": (True, "Archive invalidation: loose mod files override the game's archives"),
        "profile_saves": (True, "Separate saves per profile (the Default profile keeps the normal Saves folder)"),
        "fps_cap": (120, "FPS cap through DXVK, keeps physics stable with V-Sync off (0 = off)"),
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
            os.remove(self.ini_state)
        if not apply:
            return
        st, done = {"ini": [], "files": []}, []
        jip = dep.exists_ci(self.data_dir, "NVSE/Plugins/jip_nvse.dll")
        custom = os.path.join(self.ini_dir(), "FalloutCustom.ini")
        game_ini = os.path.join(self.ini_dir(), "Fallout.ini")

        def edit(path, section, keys):
            if path == game_ini and os.path.exists(path):
                bak = os.path.join(self.dir, "backups", "Fallout.ini.folm-backup")
                if not os.path.exists(bak):
                    os.makedirs(os.path.dirname(bak), exist_ok=True)
                    shutil.copy2(path, bak)
            st["ini"].append({"path": path, "section": section, "previous": ini.set_keys(path, section, keys)})

        if self.setting("archive_invalidation"):
            edit(custom if jip else game_ini, "Archive", self.ARCHIVE_KEYS)
            done.append(f"archive invalidation ({'FalloutCustom.ini' if jip else 'Fallout.ini'})")
        sub = self._profile_save_folder()
        if sub:
            os.makedirs(self.save_dir(), exist_ok=True)
            edit(game_ini, "General", {"SLocalSavePath": f"Saves\\{sub}\\"})
            done.append(f"saves in Saves/{sub}")
        cap = int(self.setting("fps_cap") or 0)
        if cap > 0:
            conf = os.path.join(self.data["game_dir"], "dxvk.conf")
            bak = None
            lines = []
            if os.path.exists(conf):
                bak = os.path.join(self.dir, "backups", "dxvk.conf.folm-backup")
                os.makedirs(os.path.dirname(bak), exist_ok=True)
                shutil.copy2(conf, bak)
                lines = [l for l in open(conf).read().splitlines() if not l.strip().startswith("d3d9.maxFrameRate")]
            lines.append(f"d3d9.maxFrameRate = {cap}")
            with open(conf, "w") as fh:
                fh.write("\n".join(lines) + "\n")
            st["files"].append({"path": conf, "backup": bak})
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
        return dep.catch(self.manifest, self.overwrite_dir, log)

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
    # ------------------------------------------------------------ Nexus downloads
    def nexus_download(self, url, log=_quiet):
        """Download a Nexus 'Mod Manager Download' link into the library. Returns (path, suggested name, source)."""
        from . import nexus
        self.need()
        link = nexus.parse(url)
        if link["edition"] != self.edition:
            raise FolmError(f"That link is for {game_info(link['edition'])['game']}; switch FOLM to that edition first.")
        key = nexus.load_key(home())
        if not key:
            raise FolmError("Add your Nexus API key first (⚙ Settings → Nexus account, or 'folm.py nexus-login').")
        try:
            info = nexus.file_info(link, key)
            log(f"Nexus: {info['mod_name']} {info['version'] or ''} ({info['file_name']})")
            dest = os.path.join(home(), "downloads", "nexus", link["game"])
            path = nexus.download(nexus.download_url(link, key), dest, info["file_name"] or f"{link['file_id']}.7z",
                                  info["size"], log=log, md5=info.get("md5"))
        except nexus.NexusError as e:
            raise FolmError(str(e))
        self.add_library_folder(dest)
        name = (info["mod_name"] or self.guess_name(path)).strip()
        if info.get("version") and info["version"] not in name:
            name = f"{name} {info['version']}"
        source = {"site": "nexus", "game": link["game"], "mod_id": link["mod_id"], "file_id": link["file_id"],
                  "version": info.get("version"), "file_name": info.get("file_name")}
        return path, re.sub(r'[\\/:*?"<>|]', "-", name), source

    def set_source(self, name, source):
        """Remember a mod's Nexus page and version (for update checks later); 'source' stays the archive path."""
        self.mod(name)["nexus"] = source
        self.save()

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

    def geck_path(self):
        g = self.data["game_dir"]
        for f in os.listdir(g):
            if f.lower() == "geck.exe":
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
            raise FolmError("GECK isn't installed. In Steam: Library > Tools > "
                            "'Fallout New Vegas: Garden of Eden Creation Kit' (it installs into the game folder).")
        if not self.deployed:
            self.deploy(log)
        self._geck_ini()
        before = set(self.overwrite_files())
        if runner:
            runner()
        else:
            g = self.data["game_dir"]
            proton = sorted(glob.glob(os.path.join(STEAM, "compatibilitytools.d", "*", "files", "bin", "wine")))
            wine = proton[0] if proton else shutil.which("wine")
            if not wine:
                raise FolmError("couldn't find Proton's wine to run GECK")
            loader = os.path.join(g, "nvse_loader.exe")
            cmd = [wine, "nvse_loader.exe", "-editor"] if os.path.exists(loader) else [wine, os.path.basename(exe)]
            env = dict(os.environ, WINEPREFIX=os.path.join(self.data["prefix"], "pfx"), WINEDEBUG="-all")
            log("Opening GECK (close it when you're done; FOLM will collect what you saved)...")
            subprocess.Popen(cmd, cwd=g, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait()
            time.sleep(3)
            while subprocess.run(["pgrep", "-fi", "[g]eck.exe"], capture_output=True).returncode == 0:
                time.sleep(2)                       # nvse_loader returns early; wait for GECK itself
        target = os.path.join(self.mods_dir, edit_mod) if edit_mod else self.overwrite_dir
        dep.catch(self.manifest, target, log)
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
