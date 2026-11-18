"""Core tests for FOLM's engine. No game, Steam or network needed.

Run from the project folder:  .venv/bin/python -m unittest discover tests
"""

import os
import shutil
import struct
import subprocess
import sys
import tempfile
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
        self.assertTrue(requires.CONDITIONAL.search("Only for the TTW version"))


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


class CommandLine(unittest.TestCase):
    def test_help_runs(self):
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        r = subprocess.run([sys.executable, os.path.join(here, "folm.py"), "--help"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("doctor", r.stdout)


if __name__ == "__main__":
    unittest.main()
