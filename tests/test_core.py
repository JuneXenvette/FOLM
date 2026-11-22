"""Core tests for FOLM's engine. No game, Steam or network needed.

Run from the project folder:  .venv/bin/python -m unittest discover tests
"""

import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from folm_core import deploy, fomod, requires, scriptcode as sc, setupcheck  # noqa: E402
from folm_core.esp import Group, Plugin, Record, Subrecord, build_subrecords  # noqa: E402


class Temp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="folm-test-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, data=b"x"):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb" if isinstance(data, bytes) else "w") as fh:
            fh.write(data)
        return p


# ------------------------------------------------------------------ compiled scripts

def _script():
    """scn  begin GameMode  if s1 == 1  set s1 to 2  else  return  endif  end"""
    return [
        sc.Statement(sc.BEGIN, struct.pack("<HI", 0, 0)),
        sc.if_(sc.IF, sc.expr(sc.local("s", 1), "1", "==")),
        sc.Statement(sc.SET, sc.local("s", 1) + struct.pack("<H", 2) + b" 2"),
        sc.Statement(sc.ELSE, struct.pack("<H", 0)),
        sc.Statement(sc.RETURN),
        sc.Statement(sc.ENDIF),
        sc.Statement(sc.END),
    ]


class ScriptCode(unittest.TestCase):
    def test_build_sets_jumps_and_block_length(self):
        code = sc.build(_script())
        stmts = sc.parse(code)
        sc.check(stmts)                                       # raises if anything disagrees
        self.assertEqual(struct.unpack_from("<H", stmts[1].data)[0], 1)   # If -> Else: skips the Set
        self.assertEqual(struct.unpack_from("<H", stmts[3].data)[0], 1)   # Else -> EndIf: skips the Return
        self.assertEqual(sc.parse(code)[0].op, sc.BEGIN)

    def test_round_trip_is_byte_exact(self):
        code = sc.build(_script())
        self.assertEqual(b"".join(s.to_bytes() for s in sc.parse(code)), code)

    def test_insert_recomputes(self):
        stmts = sc.parse(sc.build(_script()))
        extra = [sc.if_(sc.IF, sc.expr("1")), sc.Statement(sc.RETURN), sc.Statement(sc.ENDIF)]
        code = sc.build(stmts[:1] + extra + stmts[1:])
        sc.check(sc.parse(code))

    def test_reference_call(self):
        s = sc.Statement(0x10EF, b"\x01\x00", ref=3)
        (back,) = sc.parse(s.to_bytes())
        self.assertEqual((back.op, back.ref, back.data), (0x10EF, 3, b"\x01\x00"))

    def test_bad_structure_raises(self):
        with self.assertRaises(ValueError):
            sc.build(_script()[:-2] + [sc.Statement(sc.END)])        # If without EndIf


# ------------------------------------------------------------------ plugin files

class Plugins(Temp):
    def test_keep_at_the_end(self):
        """A plugin kept at the end stays last after plugins added later; masters still load first."""
        from folm_core.plugins import sort_plugins
        pl = lambda *m: {"masters": list(m), "is_master": False}
        plugins = {"FalloutNV.esm": {"masters": [], "is_master": True}, "A.esp": pl("FalloutNV.esm"),
                   "DNWeathers.esp": pl("FalloutNV.esm"), "ALT.esp": pl("FalloutNV.esm"),
                   "Zeta Late.esp": pl("FalloutNV.esm"), "NeedsDNW.esp": pl("DNWeathers.esp")}
        order, problems = sort_plugins(plugins, [], last=["ALT.esp", "DNWeathers.esp"])
        self.assertEqual(problems, [])
        self.assertLess(order.index("Zeta Late.esp"), order.index("ALT.esp"))        # added later: still before
        self.assertLess(order.index("ALT.esp"), order.index("DNWeathers.esp"))       # in the order kept
        self.assertGreater(order.index("NeedsDNW.esp"), order.index("DNWeathers.esp"))   # its master first

    def test_save_and_load(self):
        hdr = Record(b"TES4", 0, 0, 0, 15, 0, build_subrecords([
            Subrecord(b"HEDR", struct.pack("<fII", 1.34, 1, 0x800)),
            Subrecord(b"MAST", b"FalloutNV.esm\0"), Subrecord(b"DATA", b"\0" * 8)]))
        rec = Record(b"GLOB", 0, 0x01000800, 0, 15, 0,
                     build_subrecords([Subrecord(b"EDID", b"FolmTest\0"), Subrecord(b"FNAM", b"s")]))
        g = Group(b"GLOB", 0, 0, 0, 0, 0)
        g.children.append(rec)
        path = os.path.join(self.tmp, "Test.esp")
        Plugin(hdr, [g], name="Test.esp").save(path)

        p = Plugin.load(path)
        self.assertEqual(p.masters, ["FalloutNV.esm"])
        self.assertEqual(p.version, 1.34)
        (r,) = list(p.records())
        self.assertEqual((r.type, r.form_id), (b"GLOB", 0x01000800))
        self.assertEqual(r.subrecords[0].data, b"FolmTest\0")
        with open(path, "rb") as fh:
            self.assertEqual(Plugin.load(path).to_bytes(), fh.read())

    def test_not_a_plugin(self):
        with self.assertRaises(ValueError):
            Plugin.load(self.write("junk.esp", b"PK\x03\x04 not a plugin"))


# ------------------------------------------------------------------ FOMOD

CONFIG = """<?xml version="1.0" encoding="utf-8"?>
<config xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <moduleName>Test Mod</moduleName>
  <requiredInstallFiles><file source="core/Core.esp" destination="Core.esp"/></requiredInstallFiles>
  <installSteps order="Explicit">
    <installStep name="Main">
      <optionalFileGroups order="Explicit">
        <group name="Textures" type="SelectExactlyOne">
          <plugins order="Explicit">
            <plugin name="2K"><description>big</description>
              <files><folder source="tex2k" destination="textures"/></files>
              <typeDescriptor><type name="Optional"/></typeDescriptor></plugin>
            <plugin name="1K"><description>small</description>
              <files><folder source="tex1k" destination="textures"/></files>
              <conditionFlags><flag name="lowres">On</flag></conditionFlags>
              <typeDescriptor><type name="Recommended"/></typeDescriptor></plugin>
          </plugins>
        </group>
      </optionalFileGroups>
    </installStep>
  </installSteps>
  <conditionalFileInstalls><patterns><pattern>
    <dependencies><flagDependency flag="lowres" value="On"/></dependencies>
    <files><file source="extra/Low.ini" destination="Low.ini"/></files>
  </pattern></patterns></conditionalFileInstalls>
</config>"""


class Fomod(Temp):
    def setUp(self):
        super().setUp()
        self.write("fomod/ModuleConfig.xml", CONFIG)
        self.write("core/Core.esp")
        self.write("tex2k/a.dds", b"2k")
        self.write("tex1k/a.dds", b"1k")
        self.write("extra/Low.ini")

    def test_defaults_pick_recommended_and_flags(self):
        entries, choices, info = fomod.run(self.tmp, lambda step, group: fomod.default_choice(group))
        self.assertEqual(info["name"], "Test Mod")
        self.assertEqual(choices, {"Main/Textures": ["1K"]})
        self.assertEqual({e["source"] for e in entries}, {"core/Core.esp", "tex1k", "extra/Low.ini"})

    def test_install_files(self):
        entries, _, _ = fomod.run(self.tmp, fomod.replay_chooser({"Main/Textures": ["2K"]}))
        dest = os.path.join(self.tmp, "out")
        fomod.install_files(self.tmp, entries, dest)
        with open(os.path.join(dest, "textures", "a.dds"), "rb") as fh:
            self.assertEqual(fh.read(), b"2k")
        self.assertTrue(os.path.exists(os.path.join(dest, "Core.esp")))
        self.assertFalse(os.path.exists(os.path.join(dest, "Low.ini")))   # flag not set with 2K

    def test_rules_enforced(self):
        with self.assertRaises(fomod.FomodError):
            fomod.run(self.tmp, lambda step, group: [0, 1])        # two picks in SelectExactlyOne


# ------------------------------------------------------------------ deploy / undeploy

class Deploy(Temp):
    def setUp(self):
        super().setUp()
        self.game = os.path.join(self.tmp, "game")
        self.data = os.path.join(self.game, "Data")
        self.mods = os.path.join(self.tmp, "mods")
        self.write("game/Data/Meshes/Rock.nif", b"vanilla")      # a game file, different case
        self.write("mods/A/meshes/rock.nif", b"mod A")
        self.write("mods/A/A.esp", b"A")
        self.write("mods/B/meshes/rock.nif", b"mod B")
        self.manifest = os.path.join(self.tmp, "state", "manifest.json")
        self.backup = os.path.join(self.tmp, "state", "backup")

    def run_deploy(self, order):
        return deploy.deploy(self.game, self.data, self.mods, order, self.manifest, self.backup, log=lambda *a: None)

    def read(self, rel):
        with open(os.path.join(self.data, rel), "rb") as fh:
            return fh.read()

    def test_later_mod_wins_and_undeploy_restores(self):
        self.run_deploy(["A", "B"])
        self.assertEqual(self.read("Meshes/Rock.nif"), b"mod B")       # case-insensitive match, B wins
        self.assertFalse(os.path.exists(os.path.join(self.data, "meshes")))  # no duplicate folder
        self.assertTrue(os.path.exists(os.path.join(self.data, "A.esp")))
        deploy.undeploy(self.manifest, log=lambda *a: None)
        self.assertEqual(self.read("Meshes/Rock.nif"), b"vanilla")
        self.assertFalse(os.path.exists(os.path.join(self.data, "A.esp")))

    def test_redeploy_changes_order(self):
        self.run_deploy(["A", "B"])
        self.run_deploy(["B", "A"])
        self.assertEqual(self.read("Meshes/Rock.nif"), b"mod A")
        deploy.undeploy(self.manifest, log=lambda *a: None)
        self.assertEqual(self.read("Meshes/Rock.nif"), b"vanilla")


# ------------------------------------------------------------------ requirement detection

class Requirements(Temp):
    def test_dll_hard_requirement(self):
        blob = (b"\0\0junk\0Fallout Shader Loader.dll\0\0\0LOD Flicker Fix not found.\0"
                b"LOD Flicker Fix cannot be used without it\0\0LODFlickerFix.dll\0")
        self.write("needs.dll", blob)
        needs = requires.dll_needs(os.path.join(self.tmp, "needs.dll"))
        self.assertEqual([d for d, _ in needs], ["lodflickerfix.dll"])

    def test_logged_only_message_is_not_a_requirement(self):
        self.write("soft.dll", b"\0Vanilla Plus Skin not found.\0Skipping skin shaders\0VanillaPlusSkin.dll\0")
        self.assertEqual(requires.dll_needs(os.path.join(self.tmp, "soft.dll")), [])

    def test_conflict_message(self):
        self.write("clash.dll", b"\0This plugin is not compatible with OldThing.dll, remove it\0")
        c = requires.dll_checks(os.path.join(self.tmp, "clash.dll"))["conflicts"]
        self.assertEqual([d for d, _ in c], ["oldthing.dll"])

    def test_nexus_id_from_download_names(self):
        self.assertEqual(requires.nexus_id({"source": "/dl/JIP LN NVSE-58277-57-40-1700000000.7z"}), 58277)

    def test_filters(self):
        self.assertTrue(requires.WINDOWS_RUNTIME.search("Microsoft Visual C++ 2019 Redistributable"))
        self.assertTrue(requires._is_extender("xNVSE 6"))
        self.assertTrue(requires._is_extender("Fallout Script Extender"))
        self.assertTrue(requires._is_extender("FOSE"))
        self.assertFalse(requires._is_extender("Fallout 3 Patch"))
        self.assertTrue(requires.CONDITIONAL.search("Only for the TTW version"))
        self.assertTrue(requires.CONDITIONAL.search("Soft requirement due to new normal texture being used"))
        self.assertTrue(requires.CONDITIONAL.search("Only required for FNV version."))   # Atmospheric Lighting Tweaks
        self.assertTrue(requires.CONDITIONAL.search("Only needed in Dead Money"))
        self.assertFalse(requires.CONDITIONAL.search("Required for the updated star rotation."))
        self.assertFalse(requires.CONDITIONAL.search("The only fix for the crash"))

    def test_update_check(self):
        import io
        import types
        from folm_core import updates
        self.assertEqual(updates.upload_time("/dl/JIP LN NVSE-58277-57-40-1700000000.7z"), (1700000000, 2))
        self.assertEqual(updates.upload_time("/dl/Mod 123 1.0 2023-11-14T22-13Z ab12.zip"), (1699999980, 60))
        self.assertEqual(updates.upload_time("/dl/my own mod.zip"), (None, 0))

        files = {"m100": [{"name": "Main File", "version": "1.0", "category": "OLD_VERSION", "date": 1700000000},
                          {"name": "Main File", "version": "1.1", "category": "MAIN", "date": 1700500000},
                          {"name": "A Patch", "version": "2.0", "category": "OPTIONAL", "date": 1700600000}],
                 "m200": [{"name": "Gone", "version": "1", "category": "ARCHIVED", "date": 1600000000}],
                 "m300": [{"name": "Current", "version": "3", "category": "MAIN", "date": 1650000000}]}

        def opener(req, timeout=0):
            if "github" in req.full_url:
                return io.BytesIO(b'{"tag_name": "v99.0.0", "html_url": "https://example.invalid"}')
            return io.BytesIO(json.dumps({"data": files}).encode())
        mods = [{"name": "Old one", "source": "/dl/Main File-100-1-0-1700000000.7z"},
                {"name": "Archived", "source": "/dl/Gone-200-1-1600000000.zip"},
                {"name": "Up to date", "source": "/dl/Current-300-3-1650000000.7z"},
                {"name": "Hand made", "source": "/dl/mine.zip"}]
        m = types.SimpleNamespace(edition="courier", mods=lambda: mods)
        folm, ups = updates.check(m, log=lambda *a: None, opener=opener)
        self.assertEqual(folm[0], "99.0.0")
        self.assertEqual([(u["mod"], u["kind"], u["new"]) for u in ups],
                         [("Old one", "update", "Main File 1.1"), ("Archived", "old", "")])

        # the Updates window: every mod in a branch, each with a link
        mods += [{"name": "Renamed", "source": "/dl/Renamed-100.7z"},
                 {"name": "xNVSE 6.4.9", "source": "/dl/xnvse_6_4_9.7z"},
                 {"name": "TTW NVSE 3.3.3b", "source": "/dl/ttw nvse.7z"},
                 {"name": "Some Mod 2.1", "source": "/dl/somemod.zip"},
                 {"name": "Readius TTW Patch (FOLM)", "source": ""},
                 {"name": "Overwrite [Default]", "source": ""}]
        m.mod_plugins = lambda n: ["SomeMod.esp"] if n == "Some Mod 2.1" else []
        m.plugin_sources = lambda ps: {p: {"url": "https://example.invalid/somemod", "link": "Some page"}
                                       for p in ps}
        rows = {r["mod"]: r for r in updates.mod_status(m, opener=opener)}
        self.assertEqual({n: r["state"] for n, r in rows.items() if r["state"] != "unknown"},
                         {"Old one": "update", "Archived": "old", "Up to date": "current"})
        self.assertTrue(rows["Old one"]["url"].endswith("/mods/100?tab=files"))
        self.assertEqual(rows["Renamed"]["link"], "Files page")             # can't tell, still a link
        self.assertIn("no upload time", rows["Renamed"]["why"])
        self.assertIn("github.com/xNVSE", rows["xNVSE 6.4.9"]["url"])
        self.assertIn("search?keyword=TTW%20NVSE", rows["TTW NVSE 3.3.3b"]["url"])   # not xNVSE's page
        self.assertEqual(rows["Some Mod 2.1"]["link"], "LOOT: Some page")
        self.assertEqual(rows["Hand made"]["link"], "Search Nexus")
        for n in ("Readius TTW Patch (FOLM)", "Overwrite [Default]"):
            self.assertEqual((rows[n]["url"], rows[n]["why"][:12]), ("", "made on this"))
        folm, ferr, rows2, merr = updates.check_all(m, opener=opener)
        self.assertEqual((folm[0], ferr, len(rows2), merr), ("99.0.0", None, len(rows), None))

    def test_memory_gauge(self):
        from folm_core import crash, memwatch
        s = memwatch.parse("mem used=4081 commit=3600 reserve=481 free=14 largest=0 image=115 mapped=99 private=3866")
        self.assertEqual((s["used"], s["commit"], s["free"]), (4081, 3600, 14))
        self.assertIsNone(memwatch.parse("waiting"))
        self.assertEqual(memwatch.level(s), "warn")                       # 496 MB of room left
        self.assertEqual(memwatch.level(dict(s, commit=3900)), "critical")
        # measured on a healthy game: the heap reserves nearly everything up front, little is in use
        self.assertEqual(memwatch.level(dict(s, commit=1247, free=14, largest=0)), "ok")
        log = ("23:30:00 avail=2500 swapfree=10000 game=up game_ram=1500 used=4081 commit=1247 reserve=2834 "
               "free=14 largest=0 image=115 mapped=99 private=3866\n"
               "23:45:00 avail=2500 swapfree=10000 game=up game_ram=1900 used=4090 commit=3650 reserve=440 "
               "free=6 largest=0 image=115 mapped=300 private=3675\n")
        g = crash.memory_gauge(log)
        self.assertEqual((g["last_used"], g["last_room"]), (3650, 446))
        self.assertIn("Fullest: 3650 of 4096 MB in use", g["summary"])
        self.assertIsNone(crash.memory_gauge("23:30:00 avail=2500 swapfree=10000 game=up\n"))

    def test_crash_report_reads_the_crash_not_the_module_list(self):
        from folm_core import crash
        body = ("Exception C0000005 caught!\nCalltrace:\n0x00ED2C9E ==> EntryPoint+0x0 in falloutnv\n"
                "0x1234 ==> SomeMod.dll+0x10\nLISTING MODULE BASES ...\n"
                " - 0x7BF10000: C:\\windows\\system32\\ntdll.dll\n - 0x3BC80000: S:\\Data\\NVSE\\Plugins\\MCM.dll\n"
                "GAME CRASHED AT INSTRUCTION Base+0x00AD2C9E IN MODULE: S:\\Fallout New Vegas\\FalloutNV.exe\n")
        self.assertEqual(crash._named_in_crash(body), ["SomeMod.dll"])     # not MCM.dll from the listing

    def test_out_of_memory_from_nvhr_log(self):
        from folm_core import crash
        self.write("game/hr.log", "[23:25:20] - <sheap_get_thread_local> new sheap\n")
        self.assertFalse(crash._out_of_memory(os.path.join(self.tmp, "game"), 0, []))
        self.write("game/hr.log", "[23:25:20] - new sheap\n[00:29:33] - <hr_malloc> returned NULL\n")
        self.assertTrue(crash._out_of_memory(os.path.join(self.tmp, "game"), 0, []))
        self.assertFalse(crash._out_of_memory(os.path.join(self.tmp, "game"), time.time() + 60, []))  # older log
        self.assertTrue(crash._out_of_memory(self.tmp, 0, ["EXCEPTION_OUT_OF_MEMORY"]))

    def test_second_wind_heap_log(self):
        from folm_core import crash
        game = os.path.join(self.tmp, "game")
        self.assertEqual(crash.heap_log(game, 0), (None, None))
        self.write("game/secondwind-heap.log", "\n".join([
            "19:05:09 Second Wind measuring NVHR (NVHR 4.3 + counters). One line a minute:",
            "19:06:09 min=1 pools=300/320/1184 dheap=200/368 big=40(2) bigfail=0 poolsfull=0 va_free=60 largest=15.0",
            "19:10:09   pool    8 B: in use     1.0 MB, committed    2.0 of   32 MB (full 0 times)",
            "20:04:00 min=59 pools=900/950/1184 dheap=360/368 big=85(1) bigfail=0 poolsfull=1 va_free=40 largest=3.0",
            "20:04:44 FAILED alloc of 85.3 MB (89443584 bytes): largest free gap 3.0 MB, free in total 40.0 MB",
        ]) + "\n")
        finding, evidence = crash.heap_log(game, 0)
        self.assertIn("85.3 MB in one piece", finding)
        self.assertIn("3.0 MB", finding)
        self.assertIn("FAILED alloc", evidence)
        self.assertIn("pool    8 B", evidence)
        self.assertIn("min=59", evidence)
        self.assertEqual(crash.heap_log(game, time.time() + 60), (None, None))    # an older log: not this session
        # v3: the reserve caught the big requests; the map of who holds the 4 GB is evidence
        self.write("game/secondwind-heap.log", "\n".join([
            "07:24:55 Second Wind NVHR v3 (NVHR 4.3 + counters, right-sized pools, reserve for big requests).",
            "08:20:00 RESERVE: no 85.3 MB gap left in the 4 GB (largest 2.0 MB), so it came from Second Wind's reserve",
            "08:20:00 map (first use of the reserve): who holds the 4 GB, MB held (committed) in how many allocations:",
            "08:20:00   pools       736 (  252) in 34",
            "08:20:00   big: 0x12340000   64.0 MB (  10.0 committed) mapped d3d9.dll",
            "08:21:00 min=56 pools=200/252/736 dheap=110/320 big=0(0) bigfail=0 poolsfull=0 va_free=20 largest=2.0",
        ]) + "\n")
        finding, evidence = crash.heap_log(game, 0)
        self.assertIn("reserve caught 1", finding)
        self.assertIn("RESERVE:", evidence)
        self.assertIn("mapped d3d9.dll", evidence)
        self.assertNotIn("  pools       736", evidence.split("map (")[0])             # not taken for a pool line
        # v4: blocks given back, the map's timing, and the game quitting normally
        self.write("game/secondwind-heap.log", "\n".join([
            "10:30:46 Second Wind NVHR v4 (NVHR 4.3 + counters, right-sized pools, reserve for big requests).",
            "11:25:11 RESERVE: no 85.3 MB gap left in the 4 GB (largest 40.0 MB), so it came from Second Wind's reserve",
            "11:26:00 GAVE BACK: 3 empty dheap block(s), 48 MB, to Windows (empty for a minute)",
            "11:30:00 map (every 30 minutes): who holds the 4 GB, MB held (committed) in how many allocations:",
            "11:30:00   pools       736 (  252) in 34",
            "11:30:00   (the map took 4.2 ms)",
            "11:51:51 min=81 pools=206/266/736 dheap=115/272 big=0(0) bigfail=0 largest=410.3 bigtotal=14/12/8 "
            "gaveback=3 took=1.1ms",
            "11:52:10 game exited after 81 min",
        ]) + "\n")
        finding, evidence = crash.heap_log(game, 0)
        self.assertIn("quit normally", finding)
        self.assertIn("GAVE BACK", evidence)
        self.assertIn("map took", evidence)
        self.assertIn("game exited after 81 min", evidence)

    def _nexus_check(self, reqs, extra_mods=()):
        """requires.check for one Nexus mod (id 88898) whose page lists `reqs`; returns what's needed."""
        import types
        from unittest import mock
        os.makedirs(os.path.join(self.tmp, "game", "Data"), exist_ok=True)
        mods = [{"name": "High Priority LOD", "enabled": True, "source": "/dl/High Priority LOD-88898-1-0-1700000000.7z"},
                *extra_mods]
        m = types.SimpleNamespace(edition="courier", mods=lambda: mods, mods_dir=os.path.join(self.tmp, "mods"),
                                  data_dir=os.path.join(self.tmp, "game", "Data"), manifest=os.path.join(self.tmp, "none"),
                                  data={"game_dir": os.path.join(self.tmp, "game")})
        reqs = [{"mod_id": r[0], "name": r[1], "external": r[0] is None, "url": "", "notes": r[2]} for r in reqs]
        with mock.patch.object(requires, "nexus_requirements", return_value={88898: reqs}):
            return [r["needs"] for r in requires.check(m, online=False) if r["severity"] in ("error", "warn")]

    def test_tools_and_guides_are_not_play_requirements(self):
        reqs = [(58562, "FNVLODGen", ""), (None, "xLODGen", ""), (78835, "Global Imposter Region - GECK addons", ""),
                (None, "LOD install via the Viva New Vegas LOD Guide", ""), (74295, "NVMIM", "Flags a mesh"),
                (97376, "Curated Rock LOD", "Soft requirement"), (12345, "Real Requirement", "")]
        self.assertEqual(self._nexus_check(reqs), ["FNVLODGen", "xLODGen", "Real Requirement"])   # no LOD made yet
        self.assertEqual(self._nexus_check(reqs, [{"name": "Generated LOD", "enabled": True}]), ["Real Requirement"])


# ------------------------------------------------------------------ setup check and archives

class SetupAndArchives(Temp):
    def test_report_shape(self):
        items = [{"tools": ("7z",), "why": "unpacking", "required": True, "package": "p7zip-full"}]
        lines = setupcheck.report(items)
        self.assertTrue(lines[0].startswith("✖ 7z (needed)"))
        self.assertEqual(setupcheck.report([]), [])

    @unittest.skipUnless(shutil.which("7z"), "7z not installed")
    def test_extract_zip(self):
        from folm_core import archive
        z = os.path.join(self.tmp, "m.zip")
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("Data/Test.esp", b"hi")
        out = os.path.join(self.tmp, "out")
        archive.extract(z, out)
        self.assertTrue(os.path.exists(os.path.join(out, "Data", "Test.esp")))


class InstallerKinds(Temp):
    """BAIN, Windows tools and other games' mods, through the Manager with a fake game."""

    def setUp(self):
        super().setUp()
        os.environ["FOLM_HOME"] = os.path.join(self.tmp, "home")
        os.environ["FOLM_OFFLINE"] = "1"                          # no Nexus lookups from tests
        from folm_core.manager import Manager
        self.game = os.path.join(self.tmp, "game")
        os.makedirs(os.path.join(self.game, "Data"))
        self.m = Manager("wanderer")
        self.m.init(game_dir=self.game, prefix=os.path.join(self.tmp, "pfx"))

    def tearDown(self):
        os.environ.pop("FOLM_HOME", None)
        os.environ.pop("FOLM_OFFLINE", None)
        super().tearDown()

    def zip(self, name, files):
        z = os.path.join(self.tmp, name)
        with zipfile.ZipFile(z, "w") as zf:
            for rel, data in files.items():
                zf.writestr(rel, data)
        return z

    @unittest.skipUnless(shutil.which("7z"), "7z not installed")
    def test_detect_kinds(self):
        from folm_core import detect
        self.assertEqual(detect.detect(self.zip("t.zip", {"Patcher.exe": "MZ", "patch/a.xd3": "x"}))["type"],
                         "exe-installer")
        bain = self.zip("b.zip", {"00 Core/A.esp": "a", "10 Extra/B.esp": "b"})
        self.assertEqual(detect.detect(bain)["type"], "bain")

    def test_fose_counts_as_installed(self):
        from folm_core import requires
        self.assertFalse(requires._has_xnvse(self.m))
        os.makedirs(os.path.join(self.m.mods_dir, "FOSE", "_root"))
        open(os.path.join(self.m.mods_dir, "FOSE", "_root", "fose_loader.exe"), "w").close()
        self.m.add_folder("FOSE")
        self.assertTrue(requires._has_xnvse(self.m))                 # enabled, not deployed yet

    def test_new_version_by_name_updates_in_place(self):
        from folm_core.manager import Manager
        self.assertEqual(Manager.version_stem("Second Wind NVHR v3.zip"), "second wind nvhr")
        self.assertEqual(Manager.version_stem("Stewie Tweaks 10.05b"), "stewie tweaks")
        self.assertEqual(Manager.version_stem("Stewie Tweaks INI-23561-10-0-1700000000.7z"), "stewie tweaks ini")
        self.assertNotEqual(Manager.version_stem("Pack Part 1 of 2"), Manager.version_stem("Pack Part 2 of 2"))
        self.m.install(self.zip("Other.zip", {"Data/o.esp": "o"}), "Other")
        self.m.install(self.zip("My Mod v2.zip", {"Data/a.esp": "v2"}), "My Mod v2")
        self.m.install(self.zip("Last.zip", {"Data/z.esp": "z"}), "Last")
        self.m.set_enabled("My Mod v2", False)
        v3 = self.zip("My Mod v3.zip", {"Data/a.esp": "v3"})
        self.assertEqual([(k, x["name"]) for k, _, x in self.m.find_duplicates(v3, "My Mod v3")],
                         [("version", "My Mod v2")])
        self.m.install(v3, "My Mod v3")                   # default choice: Update, in place
        names = [x["name"] for x in self.m.mods()]
        self.assertEqual(names, ["Other", "My Mod v2", "Last"])
        self.assertFalse(self.m.mod("My Mod v2")["enabled"])
        with open(os.path.join(self.m.mods_dir, "My Mod v2", "a.esp")) as fh:
            self.assertEqual(fh.read(), "v3")
        self.assertEqual(self.m.find_duplicates(self.zip("Unrelated 2.0.zip", {"Data/u.esp": "u"}), "Unrelated"), [])

    def test_update_of_a_deployed_mod_reaches_the_game(self):
        """Updating a deployed mod, then deploying: the game gets the new files, and the old version's
        hard links aren't caught into Overwrite (where they'd win over the update)."""
        self.m.install(self.zip("Heap v3.zip", {"Data/NVHR/x.dll": "v3", "Data/NVHR/old.txt": "o"}), "Heap v3")
        self.m.deploy(log=lambda *a: None)
        game_dll = os.path.join(self.game, "Data", "NVHR", "x.dll")
        with open(game_dll) as fh:
            self.assertEqual(fh.read(), "v3")
        self.m.install(self.zip("Heap v4.zip", {"Data/NVHR/x.dll": "v4", "Data/NVHR/new.ini": "n"}), "Heap v4")
        self.assertFalse(os.path.exists(game_dll))           # the old version's link is out of the game
        self.m.deploy(log=lambda *a: None)
        with open(game_dll) as fh:
            self.assertEqual(fh.read(), "v4")
        self.assertTrue(os.path.exists(os.path.join(self.game, "Data", "NVHR", "new.ini")))
        self.assertFalse(os.path.exists(os.path.join(self.game, "Data", "NVHR", "old.txt")))
        ow = self.m.overwrite_dir
        caught = [f for _, _, fs in os.walk(ow) for f in fs] if os.path.isdir(ow) else []
        self.assertEqual(caught, [])

    def test_move_plugin(self):
        from folm_core.plugins import write_test_plugin
        data = self.m.data_dir
        os.makedirs(data, exist_ok=True)
        for n in ("FalloutNV.esm", "A.esp", "B.esp", "C.esp", "W.esp"):
            write_test_plugin(os.path.join(data, n), masters=[] if n.endswith(".esm") else ["FalloutNV.esm"])
        names = lambda: [r[0] for r in self.m.plugin_order()[0] if r[0] != "FalloutNV.esm"]
        self.assertEqual(names(), ["A.esp", "B.esp", "C.esp", "W.esp"])
        self.m.move_plugin("W.esp", "end")
        self.m.move_plugin("A.esp", "end")
        self.assertEqual(names(), ["B.esp", "C.esp", "W.esp", "A.esp"])
        self.m.move_plugin("A.esp", "earlier")                # among the end ones: A before W
        self.assertEqual(names(), ["B.esp", "C.esp", "A.esp", "W.esp"])
        self.m.move_plugin("C.esp", "earlier")
        self.assertEqual(names(), ["C.esp", "B.esp", "A.esp", "W.esp"])
        write_test_plugin(os.path.join(data, "AA New.esp"), masters=["FalloutNV.esm"])
        self.assertEqual(names()[-2:], ["A.esp", "W.esp"])     # a new plugin doesn't go after the end ones
        snap = self.m.snapshot()
        self.m.move_plugin("W.esp", "auto")
        self.assertNotIn("W.esp", self.m.cur["plugin_last"])
        self.m.restore(snap)                                   # undo puts it back at the end
        self.assertEqual(names()[-1], "W.esp")

    def test_undo_snapshot_and_restore(self):
        for n in ("A", "B", "C"):
            self.m.install(self.zip(f"{n}.zip", {f"Data/{n}.esp": n}), n)
        snap = self.m.snapshot()
        self.m.set_enabled("B", False)
        self.m.reorder(["C", "A", "B"])
        self.m.remove("A")
        after = self.m.restore(snap)
        self.assertEqual([(x["name"], x["enabled"]) for x in self.m.mods()], [("A", True), ("B", True), ("C", True)])
        self.m.restore(after)                              # redo
        self.assertEqual([x["name"] for x in self.m.mods()], ["C", "B"])
        self.m.create_profile("Other")
        self.m.switch_profile("Other")
        from folm_core.manager import FolmError
        with self.assertRaises(FolmError):
            self.m.restore(snap)                          # made in another profile

    def test_saves_follow_the_games_ini(self):
        ini_dir = self.m.ini_dir()
        os.makedirs(ini_dir, exist_ok=True)
        with open(os.path.join(ini_dir, "Fallout.ini"), "w") as fh:
            fh.write("[General]\r\nSLocalSavePath=Saves\\Profile A\\\r\n")
        self.assertTrue(self.m.save_dir().endswith(os.path.join("Saves", "Profile A")))
        with open(os.path.join(ini_dir, "FalloutPrefs.ini"), "w") as fh:     # read after Fallout.ini: wins
            fh.write("[General]\r\nSLocalSavePath=Saves\\\r\n")
        self.assertEqual(self.m.save_dir(), os.path.join(ini_dir, "Saves"))
        saves = os.path.join(ini_dir, "Saves")
        os.makedirs(saves, exist_ok=True)
        plugins = [b"FalloutNV.esm", b"Gone.esp"]
        body = bytes([len(plugins)]) + b"|" + b"".join(len(p).to_bytes(2, "little") + b"|" + p + b"|" for p in plugins)
        with open(os.path.join(saves, "Save 1.fos"), "wb") as fh:
            fh.write(b"FO3SAVEGAME" + b"\0" * 400 + body + b"\0" * 100)
        rows = self.m.saves_overview(active=["FalloutNV.esm"])
        self.assertEqual([(r["name"], r["missing"]) for r in rows], [("Save 1.fos", ["Gone.esp"])])

    def test_saves_are_checked_against_the_selected_profile(self):
        for n in ("Big", "Small"):
            self.m.install(self.zip(f"{n}.zip", {f"Data/{n}.esp": n}), n)
        self.m.create_profile("Lean", copy_from="Default")
        self.m.switch_profile("Lean")
        self.m.set_enabled("Big", False)
        self.m.set_enabled("Small", True)
        ini_dir = self.m.ini_dir()
        saves = os.path.join(ini_dir, "Saves")
        os.makedirs(saves, exist_ok=True)
        plugins = [b"Big.esp", b"Small.esp"]
        body = bytes([len(plugins)]) + b"|" + b"".join(len(p).to_bytes(2, "little") + b"|" + p + b"|" for p in plugins)
        with open(os.path.join(saves, "Save 2.fos"), "wb") as fh:
            fh.write(b"FO3SAVEGAME" + b"\0" * 400 + body)
        self.assertEqual(self.m.save_dir(), saves)                   # one Saves folder for every profile
        r = self.m.saves_overview()[0]
        self.assertEqual((r["missing"], r["fits"]), (["Big.esp"], ["Default"]))   # red here, fits Default
        self.m.set_enabled("Big", True)                              # not deployed yet: already green
        r = self.m.saves_overview()[0]
        self.assertEqual((r["missing"], r["fits"]), ([], []))
        self.assertNotIn("profile_saves", self.m.SETTINGS)

    def test_plugin_sources(self):
        os.environ["FOLM_OFFLINE"] = "1"
        self.m.install(self.zip("Cool Mod-12345-1-0-1700000000.zip", {"Data/Cool.esp": "c"}), "Cool Mod")
        hdr = Record(b"TES4", 1, 0, 0, 15, 0, build_subrecords([                   # the game's own master
            Subrecord(b"HEDR", struct.pack("<fII", 0.94, 0, 0x800))]))
        Plugin(hdr, [], name="Fallout3.esm").save(os.path.join(self.m.data_dir, "Fallout3.esm"))
        r = self.m.plugin_sources(["Fallout3.esm", "Cool.esp", "NevadaSkies.esm"])
        self.assertEqual((r["Fallout3.esm"]["url"], r["Fallout3.esm"]["link"]), (None, "comes with the game"))
        self.assertEqual(r["Cool.esp"]["mod"], "Cool Mod")
        self.assertTrue(r["Cool.esp"]["url"].endswith("/mods/12345"))
        self.assertIsNone(r["NevadaSkies.esm"]["mod"])
        self.assertIn("search?keyword=Nevada%20Skies", r["NevadaSkies.esm"]["url"])

    def test_new_downloads(self):
        from folm_core import appprefs
        dl = os.path.join(self.tmp, "dl")
        os.makedirs(dl)
        for n in ("Old.7z", "notes.txt"):
            open(os.path.join(dl, n), "w").close()
        seen = set()
        self.assertEqual(appprefs.new_mod_files([dl], seen), [os.path.join(dl, "Old.7z")])
        for n in ("New Mod-1-0.zip", "Big.7z.part", "Half.zip.crdownload"):
            open(os.path.join(dl, n), "w").close()
        self.assertEqual(appprefs.new_mod_files([dl], seen), [os.path.join(dl, "New Mod-1-0.zip")])
        self.assertEqual(appprefs.new_mod_files([dl], seen), [])
        home = os.environ["FOLM_HOME"]
        self.assertTrue(appprefs.get(home, "watch_downloads"))
        appprefs.set(home, "watch_downloads", False)
        self.assertFalse(appprefs.get(home, "watch_downloads"))

    def _xedit_setup(self):
        os.makedirs(os.path.join(self.m.mods_dir, "Cool Mod"))
        self.src = os.path.join(self.m.mods_dir, "Cool Mod", "Cool.esp")
        with open(self.src, "w") as fh:
            fh.write("original mod plugin")
        os.utime(self.src, (1500000000, 1500000000))                       # a Fallout 3 load-order date
        self.m.add_folder("Cool Mod")
        self.esm = os.path.join(self.game, "Data", "Anchorage.esm")
        with open(self.esm, "w") as fh:
            fh.write("vanilla")
        self.m.deploy()
        self.dep = os.path.join(self.game, "Data", "Cool.esp")
        self.assertTrue(os.path.samefile(self.dep, self.src))                 # deployed as a hard link

    def test_xedit_cannot_touch_mods_or_game(self):
        self._xedit_setup()

        def bad_xedit(out):
            self.assertFalse(os.path.samefile(self.dep, self.src))            # it only sees a copy
            self.assertEqual(int(os.path.getmtime(self.dep)), 1500000000)      # with the same date
            with open(self.dep, "r+") as fh:                                  # writes INTO the file
                fh.write("EDITED")
            with open(self.esm, "w") as fh:                                   # and into a game file
                fh.write("cleaned")
            open(os.path.join(self.game, "Data", "Cool.esp.save.2026_11_18"), "w").close()   # half-saved
        got = self.m.run_tool("xedit", runner=bad_xedit)
        with open(self.src) as fh:
            self.assertEqual(fh.read(), "original mod plugin")                # the mod's own file: untouched
        d = os.path.join(self.m.mods_dir, got)
        self.assertEqual(sorted(os.listdir(d)), ["Anchorage.esm", "Cool.esp"])  # no half-saved file
        with open(os.path.join(d, "Cool.esp")) as fh:
            self.assertTrue(fh.read().startswith("EDITED"))
        self.assertEqual(self.m.cur["mods"][-1]["name"], got)                   # last: its edits win
        self.m.undeploy()
        with open(self.esm) as fh:
            self.assertEqual(fh.read(), "vanilla")                             # game file back
        self.m.deploy()
        self.m.set_enabled(got, False)
        self.m.deploy()
        with open(self.dep) as fh:
            self.assertEqual(fh.read(), "original mod plugin")                # turning it off undoes it
        self.assertEqual(self.m.stale_tool_output(), [])
        self.m.set_enabled(got, True)
        with open(self.src, "w") as fh:                                       # the mod gets updated
            fh.write("version 2 of the mod")
        self.assertEqual(self.m.stale_tool_output(), [(got, "Cool.esp", "Cool Mod")])
        self.assertTrue(any("older version of 'Cool Mod'" in t for _s, t in self.m.preflight()))

    def test_xedit_interrupted_is_finished_later(self):
        from folm_core.manager import Manager
        self._xedit_setup()
        target = os.path.join(self.m.mods_dir, "xEdit output")
        self.m._begin_tool_session(target)                                   # FOLM crashes mid-run:
        with open(self.dep, "r+") as fh:
            fh.write("EDITED")
        tmp = self.esm + ".tmp"
        with open(tmp, "w") as fh:
            fh.write("cleaned")
        os.replace(tmp, self.esm)
        m2 = Manager("wanderer")                                              # next start
        m2.deploy()
        with open(self.src) as fh:
            self.assertEqual(fh.read(), "original mod plugin")
        self.assertIn("xEdit output", [x["name"] for x in m2.mods()])
        with open(os.path.join(target, "Anchorage.esm")) as fh:
            self.assertEqual(fh.read(), "cleaned")
        m2.undeploy()
        with open(self.esm) as fh:
            self.assertEqual(fh.read(), "vanilla")

    def test_xedit_keeps_earlier_work_and_cleans(self):
        self._xedit_setup()

        def edit(text):
            def run(out):
                with open(self.dep, "w") as fh:
                    fh.write(text)
            return run
        self.m.run_tool("xedit", runner=edit("first edit"))
        self.m.run_tool("xedit", runner=edit("second edit"))
        hist = self.m._tool_history_dir(os.path.join(self.m.mods_dir, "xEdit output"))
        runs = sorted(os.listdir(hist))
        with open(os.path.join(hist, runs[-1], "Cool.esp")) as fh:
            self.assertEqual(fh.read(), "first edit")                          # the earlier version is kept
        from folm_core.manager import FolmError
        with self.assertRaises(FolmError):
            self.m.clean_plugin("Fallout3.esm", runner=lambda out: None)       # never the main file
        self.assertIsNone(self.m.clean_plugin("Cool.esp", runner=lambda out: None) and None)

    @unittest.skipUnless(shutil.which("7z"), "7z not installed")
    def test_tools_tab(self):
        from folm_core import detect, tools
        st = {t["id"]: t for t in self.m.tools_status()}
        self.assertEqual(set(st), {"geck", "xedit", "xlodgen"})
        self.assertFalse(any(t["exe"] for t in st.values()))                       # all greyed out
        geck = os.path.join(self.game, "Fallout3 - Garden of Eden Creation Kit.exe")
        open(geck, "w").close()
        self.assertTrue(self.m.tools_status()[0]["exe"])                            # FO3's GECK name
        os.remove(geck)                                                             # (not part of the fake game)
        z = self.zip("xEdit 4.1.5-164-4-1-5.7z.zip", {"xEdit/xEdit.exe": "MZ", "xEdit/FO3Edit.exe": "MZ",
                                                      "xEdit/Edit Scripts/a.pas": "x"})
        self.assertEqual(detect.detect(z)["type"], "tool")
        name, r = self.m.install(z, "ignored")
        self.assertEqual(r["type"], "tool")
        exe = {t["id"]: t for t in self.m.tools_status()}["xedit"]["exe"]
        self.assertEqual(os.path.basename(exe), "FO3Edit.exe")                      # this game's own name first
        self.assertEqual(self.m.mods(), [])                                         # not a mod
        self.assertEqual(tools.args_for("xedit", "wanderer", "/g/Data")[0], "-fo3")
        self.assertEqual(tools.args_for("xlodgen", "courier", "/g/Data", "/o")[2], "-o:Z:\\o\\")

        def fake_xedit(out):                                                        # saves a plugin + a backup
            with open(os.path.join(self.game, "Data", "Fixed.esp"), "w") as fh:
                fh.write("fixed")
            os.makedirs(os.path.join(self.game, "Data", "FO3Edit Backups"))
            open(os.path.join(self.game, "Data", "FO3Edit Backups", "Fixed.esp.bak"), "w").close()
        esm = os.path.join(self.game, "Data", "Anchorage.esm")            # a game file xEdit will "clean"
        with open(esm, "w") as fh:
            fh.write("vanilla")
        self.m.undeploy()
        self.m.deploy()                                                       # (part of the game, not a mod)

        def fake_xedit2(out):
            fake_xedit(out)
            tmp = esm + ".save"
            with open(tmp, "w") as fh:
                fh.write("cleaned")
            os.replace(tmp, esm)                                              # xEdit saves by renaming over
        got = self.m.run_tool("xedit", runner=fake_xedit2)
        self.assertEqual(got, "xEdit output")
        d = os.path.join(self.m.mods_dir, got)
        self.assertEqual(sorted(os.listdir(d)), ["Anchorage.esm", "Fixed.esp"])     # backups kept aside
        with open(os.path.join(d, "Anchorage.esm")) as fh:
            self.assertEqual(fh.read(), "cleaned")
        self.m.undeploy()
        with open(esm) as fh:
            self.assertEqual(fh.read(), "vanilla")                                   # the game file is back
        self.assertTrue(self.m.mod(got)["enabled"])
        self.assertTrue(os.path.exists(os.path.join(tools.tools_dir(os.environ["FOLM_HOME"], "xedit"),
                                                    "FOLM backups", "wanderer", "FO3Edit Backups", "Fixed.esp.bak")))

    @unittest.skipUnless(shutil.which("7z"), "7z not installed")
    def test_bain_install_order(self):
        z = self.zip("Bain-1-0.zip", {"00 Core/Core.esp": "core", "10 A/Opt.esp": "A",
                                      "20 B/Data/Opt.esp": "B", "20 B/Data/Textures/x.dds": "t",
                                      "00 Core/textures/y.dds": "t"})
        name, _ = self.m.install(z, "Bain", chooser=fomod.replay_chooser({"BAIN/Packages": ["00 Core", "10 A", "20 B"]}))
        d = os.path.join(self.m.mods_dir, name)
        with open(os.path.join(d, "Opt.esp")) as fh:
            self.assertEqual(fh.read(), "B")                              # later package wins
        self.assertEqual(len([x for x in os.listdir(d) if x.lower() == "textures"]), 1)   # case twins merged
        self.assertEqual(self.m.mod(name)["bain_choices"], {"BAIN/Packages": ["00 Core", "10 A", "20 B"]})

    @unittest.skipUnless(shutil.which("7z"), "7z not installed")
    def test_other_game_refused(self):
        from folm_core.manager import FolmError
        z = self.zip("starfield.zip", {"SFSE/Plugins/thing.toml": "x", "readme.txt": "for Starfield"})
        with self.assertRaises(FolmError) as e:
            self.m.install(z, "SF")
        self.assertIn("another game", str(e.exception))

    @unittest.skipUnless(shutil.which("7z"), "7z not installed")
    def test_duplicates(self):
        from folm_core.manager import FolmError
        pick = lambda answer: (lambda step, g: [next(i for i, p in enumerate(g["plugins"]) if p["name"] == answer)]
                               if step == "Already installed" else fomod.default_choice(g))   # noqa: E731
        v1 = self.zip("Cool Mod-1234-1-0-1700000000.zip", {"Cool.esp": "v1"})
        name, _ = self.m.install(v1, "Cool Mod")
        self.m.mod(name)["notes"] = "mine"
        with self.assertRaises(FolmError) as e:                       # same file again, under another name
            self.m.install(v1, "Cool Mod - ENG")
        self.assertIn("already installed as 'Cool Mod'", str(e.exception))
        other = os.path.join(self.tmp, "elsewhere")                    # same file name, different contents
        os.makedirs(other)
        with zipfile.ZipFile(os.path.join(other, os.path.basename(v1)), "w") as zf:
            zf.writestr("Other.esp", "not the same mod")
        kinds = [k for k, _p, _m in self.m.find_duplicates(os.path.join(other, os.path.basename(v1)))]
        self.assertNotIn("same", kinds)                                 # the contents decide, not the name
        name2, _ = self.m.install(v1, "Cool Mod", chooser=pick("Install a second copy"))
        self.assertEqual(name2, "Cool Mod (2)")
        self.m.remove(name2)
        self.m.mod(name)["enabled"] = False
        v2 = self.zip("Cool Mod-1234-1-1-1710000000.zip", {"Cool.esp": "v2"})
        self.assertEqual(self.m.find_duplicates(v2)[0][0], "version")
        self.m.install(v2)                                            # default answer: Update
        self.assertEqual([x["name"] for x in self.m.mods()], ["Cool Mod"])
        mod = self.m.mod("Cool Mod")
        self.assertEqual((mod["notes"], mod["enabled"]), ("mine", False))   # kept through the update
        with open(os.path.join(self.m.mods_dir, "Cool Mod", "Cool.esp")) as fh:
            self.assertEqual(fh.read(), "v2")
        ini = self.zip("Cool Mod INI-1234-1-0-1700000001.zip", {"Cool.ini": "x"})   # other file, same page
        self.assertEqual(self.m.find_duplicates(ini), [])

    def test_collect_tool_output(self):
        from folm_core import wintool
        self.write("game/Fallout3.exe", b"vanilla")
        self.write("game/Data/Same.esm", b"same")
        up = os.path.join(self.tmp, "job", "upper")
        self.write("job/upper/Fallout3.exe", b"patched")                   # changed game exe -> game-root file
        self.write("job/upper/Data/Same.esm", b"same")                     # rewritten unchanged -> skipped
        self.write("job/upper/Data/New.esp", b"new")
        self.write("job/upper/Patcher.exe", b"tool")                       # the tool itself -> skipped
        self.write("job/upper/patch.log", b"log")                          # its log -> skipped
        self.write("job/output/Extra.esp", b"out")                         # drive O: -> data
        dest = os.path.join(self.tmp, "mod")
        res = wintool.collect({"upper": up, "output": os.path.join(self.tmp, "job", "output"),
                               "tool_files": {"Patcher.exe"}}, self.game, dest)
        got = sorted(os.path.relpath(os.path.join(dp, f), dest) for dp, _, fn in os.walk(dest) for f in fn)
        self.assertEqual(got, sorted(["New.esp", "Extra.esp", os.path.join(deploy.ROOT_DIR, "Fallout3.exe")]))
        self.assertEqual(res["unchanged"], 1)

    def test_exe_choice(self):
        from folm_core import wintool
        for f in ("Setup.exe", "unins000.exe", "tools/xdelta3.exe", "vcredist_x86.exe", "Readme.exe"):
            self.write("tool/" + f, b"MZ")
        exes = [os.path.relpath(e, os.path.join(self.tmp, "tool")) for e in wintool.find_exes(os.path.join(self.tmp, "tool"))]
        self.assertEqual(exes, ["Setup.exe", "Readme.exe"])
        self.assertTrue(wintool.runs_in_game_folder("/x/Patcher.exe", "exe-installer"))
        self.assertFalse(wintool.runs_in_game_folder("/x/TTW Install.exe", "ttw-installer"))
        self.assertFalse(wintool.runs_in_game_folder("/x/ESM Patcher.exe", "exe-installer"))


class ModLists(Temp):
    """Mod lists: find the downloads, install them in the list's order with the list's settings."""

    def setUp(self):
        super().setUp()
        os.environ["FOLM_HOME"] = os.path.join(self.tmp, "home")
        os.environ["FOLM_OFFLINE"] = "1"
        from folm_core.manager import Manager
        os.makedirs(os.path.join(self.tmp, "game", "Data"))
        self.m = Manager("wanderer")
        self.m.init(game_dir=os.path.join(self.tmp, "game"), prefix=os.path.join(self.tmp, "pfx"))

    def tearDown(self):
        os.environ.pop("FOLM_HOME", None)
        os.environ.pop("FOLM_OFFLINE", None)
        super().tearDown()

    def test_rename_and_delete_profiles(self):
        from folm_core.manager import FolmError
        m = self.m
        saves = os.path.join(m.ini_dir(), "Saves")
        m.create_profile("Test", copy_from="Default")
        self.write(os.path.relpath(os.path.join(saves, "Test", "Save 1.fos"), self.tmp), b"save")
        self.write(os.path.relpath(os.path.join(m.mods_dir, "Overwrite [Test]", "caught.ini"), self.tmp), b"x")
        for bad, why in (("Default", "Default"), ("Test", "already"), ("A [b]", "can't contain")):
            with self.assertRaisesRegex(FolmError, why):
                m.rename_profile("Default" if bad == "Default" else "Test", bad if bad != "Default" else "Other")
        m.switch_profile("Test")
        m.rename_profile("Test", "Run 2")                               # the active one, not deployed
        self.assertEqual(m.active, "Run 2")
        self.assertIn("Run 2", m.profiles())
        self.assertNotIn("Test", m.profiles())
        self.assertTrue(os.path.exists(os.path.join(saves, "Run 2", "Save 1.fos")))      # saves moved along
        self.assertTrue(os.path.exists(os.path.join(m.mods_dir, "Overwrite [Run 2]", "caught.ini")))
        with self.assertRaisesRegex(FolmError, "switch first"):
            m.delete_profile("Run 2")
        m.switch_profile("Default")
        kept_saves, kept = m.delete_profile("Run 2")
        self.assertNotIn("Run 2", m.profiles())
        self.assertEqual(kept_saves, os.path.join(saves, "Run 2"))
        self.assertTrue(os.path.exists(os.path.join(saves, "Run 2", "Save 1.fos")))      # never deleted
        self.assertEqual(kept, "Caught files from Run 2")
        self.assertTrue(os.path.exists(os.path.join(m.mods_dir, kept, "caught.ini")))
        m.create_profile("Empty")
        os.makedirs(os.path.join(m.mods_dir, "Overwrite [Empty]"))
        self.assertEqual(m.delete_profile("Empty"), (None, None))
        self.assertFalse(os.path.exists(os.path.join(m.mods_dir, "Overwrite [Empty]")))

    def test_essentials(self):
        from folm_core import essentials, health
        game = os.path.join(self.tmp, "game")
        by = {e["id"]: e for e in essentials.check(self.m)}
        self.assertEqual(set(by), {"fose", "fap", "bsa"})
        self.assertFalse(by["fose"]["have"])
        self.assertIsNone(by["bsa"]["have"])                                   # no game archives: can't tell
        self.write("game/fose_loader.exe", b"MZ")
        bsa = struct.pack("<4sIIIIIIII", b"BSA\0", 104, 36, 0x83, 0, 0, 0, 0, 0)
        self.write("game/Data/Fallout - Meshes.bsa", bsa)
        by = {e["id"]: e for e in essentials.check(self.m)}
        self.assertTrue(by["fose"]["have"])
        self.assertTrue(by["bsa"]["have"])                                    # stored uncompressed
        self.write("game/Data/Fallout - Meshes.bsa", struct.pack("<4sIIIIIIII", b"BSA\0", 104, 36, 0x87, 0, 0, 0, 0, 0))
        found = {f["text"].split(":")[0]: f for f in health._essentials(self.m)}
        self.assertEqual(found["FO3 BSA Decompressor"]["status"], "info")       # recommended: a note
        self.assertIn("nexusmods.com/fallout3/mods/25720", found["FO3 BSA Decompressor"]["fix"])
        self.assertEqual(found["FOSE (Fallout Script Extender)"]["status"], "ok")
        self.assertTrue(os.path.isdir(game))

    LIST = """
folm_list: 1
name: Test list
edition: wanderer
mods:
  - file: Big Pack
    nexus: 100
  - file: Big Pack
    nexus: 100
    name: Big Pack - Extras
    match: "*Extras*"
  - file: Patch
    nexus: 200
    remove: [Patch.esp, meshes/effects]
    note: only for generating
  - file: Quiet Mod
    nexus: 300
    enabled: false
    plugins_off: [Quiet.esp]
  - file: Not Downloaded
    nexus: 400
"""

    def downloads(self):
        d = os.path.join(self.tmp, "dl")
        os.makedirs(d, exist_ok=True)
        for name, files in {
                "Big Pack-100-1-0-1600000000.zip": {"textures/a.dds": "a"},
                "Big Pack-100-Extras1-0-1600000001.zip": {"textures/b.dds": "b"},
                "Patch 200 1.2 2026-01-01T00-00Z abCD12(1).zip": {"Patch.esp": "p", "meshes/Effects/x.nif": "x",
                                                                  "meshes/keep.nif": "k"},
                "Quiet Mod-300-1-0.zip": {"Quiet.esp": "q"},
                "Unrelated-999-1-0.zip": {"textures/z.dds": "z"}}.items():
            with zipfile.ZipFile(os.path.join(d, name), "w") as zf:
                for rel, data in files.items():
                    zf.writestr(rel, data)
        return d

    def test_download_names(self):
        from folm_core import modlist
        self.assertEqual(modlist.parse_download("Much Needed LOD - NMC Patch-64805-1-2.7z"),
                         ("Much Needed LOD - NMC Patch", 64805))
        self.assertEqual(modlist.parse_download("TTW Fallout 3 LOD 90327 1.7.3 2026-07-21T13-55Z CzdhDYBt(1).7z"),
                         ("TTW Fallout 3 LOD", 90327))
        self.assertEqual(modlist.parse_download("Loose.zip"), ("Loose", None))

    def test_bad_lists_say_why(self):
        from folm_core import modlist
        for text, words in (("name: x", "no 'mods:'"), ("mods:\n  - nexus: 5", "needs a 'file:'"),
                            ("mods:\n  - file: A\n    remove: [../../etc]", "inside the mod"),
                            ("mods:\n  - file: A\n  - file: A", "both be called"),
                            ("mods:\n  - file: A\n    colour: red", "doesn't know colour")):
            with self.assertRaises(modlist.ListError) as cm:
                modlist.parse(text)
            self.assertIn(words, str(cm.exception))

    @unittest.skipUnless(shutil.which("7z") or shutil.which("7zz"), "7-Zip not installed")
    def test_check_install_and_save(self):
        from folm_core import modlist
        lst, dl = modlist.parse(self.LIST), self.downloads()
        rows = modlist.status(self.m, lst, dl)
        self.assertEqual([r["state"] for r in rows], ["ready", "ready", "ready", "ready", "missing"])
        self.assertTrue(rows[0]["file"].endswith("1-0-1600000000.zip"))      # the Extras file went to its entry
        self.assertTrue(rows[1]["file"].endswith("Extras1-0-1600000001.zip"))
        self.assertIn("fallout3/mods/400", rows[4]["link"])

        os.makedirs(os.path.join(self.m.mods_dir, "Earlier"))      # a mod already in the profile, at the end
        self.m.add_folder("Earlier")
        done, skipped, missing, failed = modlist.install(self.m, lst, dl, log=lambda *a: None)
        self.assertEqual((done, skipped, missing, failed),
                         (["Big Pack", "Big Pack - Extras", "Patch", "Quiet Mod"], [], ["Not Downloaded"], []))
        self.assertEqual([x["name"] for x in self.m.mods()],
                         ["Earlier", "Big Pack", "Big Pack - Extras", "Patch", "Quiet Mod"])
        patch = os.path.join(self.m.mods_dir, "Patch")
        self.assertFalse(os.path.exists(os.path.join(patch, "Patch.esp")))
        self.assertFalse(os.path.exists(os.path.join(patch, "meshes", "Effects")))   # case didn't matter
        self.assertTrue(os.path.exists(os.path.join(patch, "meshes", "keep.nif")))
        self.assertEqual(self.m.mod("Patch")["notes"], "only for generating")
        self.assertFalse(self.m.mod("Quiet Mod")["enabled"])
        self.assertIn("Quiet.esp", self.m.cur["disabled_plugins"])

        again = modlist.install(self.m, lst, dl, log=lambda *a: None)        # nothing twice
        self.assertEqual(again[0], [])
        self.assertEqual(len(again[1]), 4)

        path, saved, left_out = modlist.save(self.m, os.path.join(self.tmp, "mine"))
        self.assertTrue(path.endswith(".folmlist"))
        self.assertEqual(left_out, ["Earlier"])
        back = modlist.load(path)
        self.assertEqual([e["name"] for e in back["mods"]], ["Big Pack", "Big Pack - Extras", "Patch", "Quiet Mod"])
        self.assertEqual(back["mods"][3]["plugins_off"], ["Quiet.esp"])
        self.assertFalse(back["mods"][3]["enabled"])
        self.assertEqual(back["edition"], "wanderer")

    def test_list_for_the_other_game_is_refused(self):
        from folm_core import modlist
        lst = modlist.parse(self.LIST.replace("edition: wanderer", "edition: courier"))
        with self.assertRaises(modlist.ListError):
            modlist.install(self.m, lst, self.tmp, log=lambda *a: None)

    def test_shipped_lists_load(self):
        from folm_core import modlist
        lists = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lists")
        for f in os.listdir(lists):
            if f.endswith(modlist.EXT):
                self.assertTrue(modlist.load(os.path.join(lists, f))["mods"])


class AppImage(Temp):
    """What changes when FOLM runs from its AppImage: bundled 7-Zip, app-menu entries."""

    def env(self, **kw):
        old = {k: os.environ.get(k) for k in kw}
        os.environ.update({k: v for k, v in kw.items() if v is not None})
        for k, v in kw.items():
            if v is None:
                os.environ.pop(k, None)
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
                                 for k, v in old.items()])

    def test_bundled_7zip_comes_first(self):
        from folm_core import archive
        fake = self.write("bin/7zz", b"#!/bin/sh\n")
        os.chmod(fake, 0o755)
        self.env(FOLM_7Z=fake)
        self.assertEqual(archive.seven_zip(), fake)
        self.env(FOLM_7Z=os.path.join(self.tmp, "gone"))          # missing: fall back to the system's
        self.assertNotEqual(archive.seven_zip(), os.path.join(self.tmp, "gone"))

    def test_menu_entries_follow_the_appimage(self):
        from folm_core import desktop
        old = self.write("Apps/FOLM-1.0.AppImage", b"")
        new = self.write("Apps/FOLM 1.1 $test.AppImage", b"")
        self.env(XDG_DATA_HOME=os.path.join(self.tmp, "share"), APPIMAGE=old)
        desktop.write_entries()
        self.assertEqual(desktop.recorded_launcher(), old)
        self.assertFalse(os.path.exists(os.path.join(desktop.apps_dir(), desktop.NXM)))   # no Nexus handler any more
        self.assertFalse(desktop.refresh())                       # same file: nothing to do
        self.env(APPIMAGE=new)
        self.assertTrue(desktop.refresh())                        # newer AppImage run: entries move to it
        self.assertEqual(desktop.recorded_launcher(), new)
        with open(os.path.join(desktop.apps_dir(), desktop.MAIN)) as fh:
            self.assertIn('Exec="%s"' % new.replace("$", "\\$"), fh.read())

    def test_folm_1_0_nexus_setup_is_undone(self):
        from folm_core import desktop
        self.env(XDG_DATA_HOME=os.path.join(self.tmp, "share"))
        home = os.path.join(self.tmp, "home")
        key = self.write("home/nexus.json", b'{"key": "secret"}')
        handler = self.write("share/applications/folm-nxm.desktop", b"[Desktop Entry]\n")
        other = self.write("home/profiles.json", b"{}")
        done = desktop.retire_nexus_links(home)
        self.assertFalse(os.path.exists(key))
        self.assertFalse(os.path.exists(handler))
        self.assertTrue(os.path.exists(other))                    # nothing else of FOLM's is touched
        self.assertIn("deleted the stored Nexus API key", done)
        self.assertEqual(desktop.retire_nexus_links(home), [])   # second start: nothing left to do

    def test_source_checkout_entries_are_left_alone(self):
        from folm_core import desktop
        self.env(XDG_DATA_HOME=os.path.join(self.tmp, "share"), APPIMAGE=None)
        desktop.write_entries()                                   # points at run-folm.sh, which exists
        self.env(APPIMAGE=self.write("FOLM.AppImage", b""))
        self.assertFalse(desktop.refresh())
        self.assertTrue(desktop.recorded_launcher().endswith("run-folm.sh"))


class CommandLine(unittest.TestCase):
    def test_help_runs(self):
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        r = subprocess.run([sys.executable, os.path.join(here, "folm.py"), "--help"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("doctor", r.stdout)


class SteamLaunchOptions(Temp):
    VDF = ('"UserLocalConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n'
           '\t\t\t\t"apps"\n\t\t\t\t{\n\t\t\t\t\t"22380"\n\t\t\t\t\t{\n'
           '\t\t\t\t\t\t"LastPlayed"\t\t"1"\n\t\t\t\t\t\t"cloud"\n\t\t\t\t\t\t{\n\t\t\t\t\t\t}\n'
           '\t\t\t\t\t}\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n')

    def test_sound_fix(self):
        from folm_core import steamopts as so
        self.assertEqual(so.launch_options(self.VDF, 22380), "")
        self.assertIsNone(so.launch_options(self.VDF, 22370))
        t = so.set_launch_options(self.VDF, 22380, 'A="b c" %command%')
        self.assertEqual(so.launch_options(t, 22380), 'A="b c" %command%')
        self.assertIn('\t\t\t\t\t\t"LaunchOptions"', t)
        self.assertEqual(so.launch_options(so.set_launch_options(t, 22380, "x"), 22380), "x")
        self.assertEqual(so.with_fix("", "V", "60"), "V=60 %command%")
        self.assertEqual(so.with_fix("-nosplash", "V", "60"), "V=60 %command% -nosplash")
        self.assertEqual(so.with_fix("DXVK_HUD=1 %command%", "V", "60"), "V=60 DXVK_HUD=1 %command%")
        self.assertEqual(so.with_fix("V=30 %command%", "V", "60"), "V=30 %command%")
        self.assertEqual(so.without_fix("V=60 %command%", "V"), "")
        self.assertEqual(so.without_fix("V=60 DXVK_HUD=1 %command%", "V"), "DXVK_HUD=1 %command%")

        cfg = os.path.join(self.tmp, "localconfig.vdf")
        open(cfg, "w").write(self.VDF)
        want = {"PULSE_LATENCY_MSEC": "60"}
        ours, note = so.sync(22380, want, set(), files=[cfg], running=True)       # Steam open: wait
        self.assertEqual((ours, note), (set(), None))
        ours, note = so.sync(22380, want, set(), files=[cfg], running=False)
        self.assertEqual(ours, {"PULSE_LATENCY_MSEC"})
        self.assertEqual(so.launch_options(open(cfg).read(), 22380), "PULSE_LATENCY_MSEC=60 %command%")
        self.assertTrue(os.path.exists(cfg + ".folm-backup"))
        self.assertEqual(so.sync(22380, want, ours, files=[cfg], running=False), (ours, None))
        ours, note = so.sync(22380, {}, ours, files=[cfg], running=False)           # turned off
        self.assertEqual(ours, set())
        self.assertEqual(so.launch_options(open(cfg).read(), 22380), "")
        open(cfg, "w").write(so.set_launch_options(self.VDF, 22380, "PULSE_LATENCY_MSEC=30 %command%"))
        ours, _ = so.sync(22380, want, set(), files=[cfg], running=False)           # the player's own: kept
        self.assertEqual(ours, set())
        self.assertEqual(so.launch_options(open(cfg).read(), 22380), "PULSE_LATENCY_MSEC=30 %command%")


    def test_gamemode_word_and_optimize(self):
        from unittest import mock
        from folm_core import optimize, steamopts as so
        self.assertEqual(so.with_fix("", "gamemoderun", None), "gamemoderun %command%")
        self.assertEqual(so.with_fix("V=60 %command% -x", "gamemoderun", None), "V=60 gamemoderun %command% -x")
        self.assertEqual(so.with_fix("gamemoderun %command%", "V", "60"), "V=60 gamemoderun %command%")
        self.assertEqual(so.without_fix("V=60 gamemoderun %command%", "gamemoderun"), "V=60 %command%")
        self.assertTrue(so.has("V=60 gamemoderun %command%", "gamemoderun"))
        self.assertFalse(so.has("V=60 %command%", "gamemoderun"))

        class Fake:
            edition, data = "courier", {"steam_fixes": []}
            SETTINGS = {k: (v if not isinstance(v, bool) else False, "") for k, _n, _w, v, _r in optimize.FIXES}
            vals = {}
            def setting(self, k):
                return self.vals.get(k, self.SETTINGS[k][0])
            def set_setting(self, k, v):
                self.vals[k] = v
        m = Fake()
        m.SETTINGS["fps_cap"] = (0, "")
        cfg = os.path.join(self.tmp, "localconfig.vdf")
        open(cfg, "w").write(self.VDF)
        with mock.patch.object(so, "config_files", lambda: [cfg]), \
                mock.patch.object(so, "gamemode_installed", lambda: False):
            rows = {r["key"]: r for r in optimize.check(m)}
            self.assertFalse(rows["gamemode"]["available"])
            self.assertEqual(rows["sound_fix"]["state"], "off")
            changed = optimize.apply(m, {"sound_fix": True, "fps_cap": True, "borderless": False})
            self.assertEqual(sorted(changed), ["fps_cap", "sound_fix"])
            self.assertEqual(m.setting("fps_cap"), 120)
            rows = {r["key"]: r for r in optimize.check(m)}
            self.assertIn("next time Steam is closed", rows["sound_fix"]["state"])
            self.assertTrue(rows["fps_cap"]["state"].startswith("on (120 FPS)"))
            optimize.apply(m, {"fps_cap": False})
            self.assertEqual(m.setting("fps_cap"), 0)
        # GameMode installed, but the account isn't in the "gamemode" group: it can't work, so not offered
        import grp
        fake_grp = type("G", (), {"gr_gid": 4242})()
        with mock.patch.object(so, "gamemode_installed", lambda: True), \
                mock.patch.object(grp, "getgrnam", lambda _n: fake_grp), \
                mock.patch.object(os, "getgroups", lambda: [1000]), mock.patch.object(os, "getgid", lambda: 1000):
            self.assertIn("gamemode", so.gamemode_why_not())
        with mock.patch.object(so, "gamemode_installed", lambda: True), \
                mock.patch.object(grp, "getgrnam", lambda _n: fake_grp), \
                mock.patch.object(os, "getgroups", lambda: [1000, 4242]):
            self.assertIsNone(so.gamemode_why_not())


class LookToolsHelp(Temp):
    def test_tool_versions(self):
        from folm_core import tools
        self.assertEqual(tools.version_in_name("xLODGen_beta_128.7z"), "beta 128")
        self.assertEqual(tools.version_in_name("FNVEdit 4.1.5f-34703-4-1-5f-1700000000.7z"), "4.1.5f")
        self.assertIsNone(tools.version_in_name("xLODGen.7z"))
        self.assertEqual(tools.version_in_name("xLODGen.132.7z"), "beta 132")
        d = os.path.join(self.tmp, "xlodgen", "xLODGen")
        os.makedirs(d)
        exe = os.path.join(d, "xLODGenx64.exe")
        open(exe, "wb").write(b"MZ")
        self.assertIsNone(tools.tool_version(os.path.dirname(d), exe))
        with open(os.path.join(d, "FNVLODGen_log.txt"), "w") as fh:
            fh.write("FNVLODGen 4.1.5o EXTREMELY EXPERIMENTAL Terrain LOD Beta x64 starting\n")
        self.assertEqual(tools.tool_version(os.path.dirname(d), exe), "4.1.5o")
        tools.save_version(os.path.dirname(d), "/dl/xLODGen beta 130.7z")       # the download's name wins
        self.assertEqual(tools.tool_version(os.path.dirname(d), exe), "beta 130")

    def test_game_colors_and_look(self):
        from folm_core import look
        ini = os.path.join(self.tmp, "FalloutPrefs.ini")
        with open(ini, "w") as fh:
            fh.write("[Interface]\niSystemColorPipboyRed=26\niSystemColorPipboyGreen=255\n"
                     "iSystemColorPipboyBlue=128\niSystemColorHUDMainRed=26\niSystemColorHUDMainGreen=255\n"
                     "iSystemColorHUDMainBlue=128\nuPipboyColor=452952319\nuHUDColor=785383423\n")
        c = look.game_colors(ini)
        self.assertEqual(c["Pip-Boy"], "#1aff80")
        self.assertEqual(c["HUD"], "#2ecfff")                          # the packed setting differs: both offered
        self.assertEqual(c["HUD (second setting)"], "#1aff80")
        self.assertNotIn("Pip-Boy (second setting)", c)                  # same color twice: offered once
        self.assertEqual(look.game_colors(os.path.join(self.tmp, "nope.ini")), {})
        self.assertEqual(look.resolve("game:HUD", c), "#2ecfff")
        self.assertEqual(look.resolve("game:Terminal", c), "")
        self.assertEqual(look.resolve("#C9A227", c), "#C9A227")
        self.assertEqual(look.load(self.tmp), look.DEFAULTS)
        look.save(self.tmp, dict(look.PRESETS["Pip-Boy"], junk=1))
        self.assertEqual(look.load(self.tmp)["tab"], "game:Pip-Boy")

    def test_low_memory_save(self):
        from folm_core import lowmemsave
        game = os.path.join(self.tmp, "game")
        data = os.path.join(game, "Data")
        saves = os.path.join(self.tmp, "Saves")
        os.makedirs(saves)
        self.assertIn("New Vegas", lowmemsave.why_not("wanderer", game, data))
        self.write("game/Data/NVSE/Plugins/jip_nvse.dll", b"MZ")
        self.assertEqual(lowmemsave.why_not("courier", game, data), "needs xNVSE")
        ver = ("VS_VERSION_INFO".encode("utf-16-le") + b"\0\0").ljust(36, b"\0")
        def dll(a, b, c):
            return b"MZ" + b"\0\0" + ver + struct.pack("<IIII", 0xFEEF04BD, 0x10000, a, (b << 16) | c)
        self.write("game/nvse_1_4.dll", dll(6, 1, 0))                      # 0.6.1.0
        self.assertIn("6.2.1 or newer", lowmemsave.why_not("courier", game, data))
        self.write("game/nvse_1_4.dll", dll(6, 4, 9))
        self.assertIsNone(lowmemsave.why_not("courier", game, data))
        script = lowmemsave.install(data)
        self.assertEqual(os.path.dirname(script), os.path.join(data, "NVSE", "Plugins", "scripts"))
        self.assertIn('con_Save "FOLM_LowMemory"', open(script).read())
        self.assertTrue(lowmemsave.installed(data))

        def game_saves():                                   # what the game does when it sees the request
            req = os.path.join(data, "FOLM", "save-now.txt")
            for _ in range(100):
                if os.path.exists(req):
                    break
                time.sleep(0.05)
            for ext in (".fos", ".nvse"):
                with open(os.path.join(saves, "FOLM_LowMemory" + ext), "wb") as fh:
                    fh.write(b"save")
        done = []
        sv = lowmemsave.Saver(data, saves, on_done=done.append, quiet=0.3)
        sv.start()
        threading.Thread(target=game_saves).start()
        for _ in range(100):
            if done:
                break
            time.sleep(0.1)
        self.assertTrue(done and sv.result and sv.result.startswith("FOLM_LowMemory_"), sv.problem)
        self.assertEqual(sorted(os.listdir(saves)), [sv.result + ".fos", sv.result + ".nvse"])
        self.assertFalse(os.path.exists(os.path.join(data, "FOLM")))     # the request is gone

    def test_help_files(self):
        from folm_core import helpdocs
        for name in ("faq", "resources"):
            cats = helpdocs.read(name)
            self.assertGreater(len(cats), 3, name)
            for cat, topics in cats:
                self.assertTrue(topics, f"{name}: {cat} has no topics")
                for title, body in topics:
                    self.assertTrue(body, f"{name}: {title} is empty")
        self.assertEqual(helpdocs.read("missing"), [])


if __name__ == "__main__":
    unittest.main()
