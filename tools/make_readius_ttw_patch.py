#!/usr/bin/env python3
"""Build "Readius TTW Patch.esp": Pip-Boy Readius (Readius_NV.esp 1.1) working with TTW 3.x.

Built on the player's PC from their own copy of Readius_NV.esp (nothing from the mod is shipped).

Why it's needed: in a TTW Fallout 3 start, the Vault 101 scenes (CG02 birthday, CG03 G.O.A.T.,
CG04 escape) and Tranquility Lane (MQ04) take, give and equip the Pip-Boy themselves. Readius swaps
the Pip-Boy for its handheld once, so later re-equips put the arm Pip-Boy back, and its armor
refresh (unequip + re-add) runs in the middle of TTW's scripted scenes.

The old "Readius TTW Fix" (2015, TTW 2.x) rewrote those TTW quests with their TTW 2.x versions,
which would roll back TTW 3's changes. This patch edits no TTW record. It overrides only Readius's
own quest script, adding two checks near the top of its GameMode block:

    if GetQuestRunning CG02 || GetQuestRunning CG03 || GetQuestRunning CG04 || (GetStage CG02 > 0 && GetQuestCompleted CG04 == 0)
        return                      ; Vault 101 childhood, including the gaps between its scenes
    endif
    if Init == 2                    ; Readius already active, and a script put the Pip-Boy back on
        if player.GetEquipped PipBoy == 1 || player.GetEquipped PimpBoy == 1 || player.GetEquipped PipBoyGlove == 1
            player.UnequipItem PipBoy 1 1
            player.UnequipItem PimpBoy 1 1
            player.UnequipItem PipBoyGlove 1 1
            set Strip to 1          ; Readius's own armor refresh, next frames
            return
        endif
    endif

Usage: make_readius_ttw_patch.py READIUS_NV_ESP OUTPUT_ESP
"""

import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from folm_core.esp import Group, Plugin, Record, Subrecord, build_subrecords  # noqa: E402
from folm_core import scriptcode as sc  # noqa: E402

SCRIPT_ID = 0x01000ADD                     # BIDEpipRemoverNVSCRIPT in Readius_NV.esp
MASTERS = ["FalloutNV.esm", "Fallout3.esm", "Readius_NV.esp"]
CG02, CG03, CG04 = 0x00014E84, 0x01014E85, 0x01014E86      # in the patch's master numbering
GET_QUEST_RUNNING, GET_EQUIPPED, UNEQUIP_ITEM = 0x1038, 0x10B6, 0x10EF
GET_STAGE, GET_QUEST_COMPLETED = 0x103A, 0x1222       # both checked against TTW's compiled scripts
SOURCE_ANCHOR = "\t; Initialize the player by removing the Pipboy and glove,"
SOURCE_ADD = """\t; --- Readius TTW Patch (FOLM) ---
\t; Vault 101 childhood (TTW Fallout 3 start): leave TTW's scripted scenes alone until the escape is done,
\t; including the moments between the birthday, the G.O.A.T. and the escape
\tif GetQuestRunning CG02 || GetQuestRunning CG03 || GetQuestRunning CG04 || (GetStage CG02 > 0 && GetQuestCompleted CG04 == 0)
\t\treturn
\tendif
\t; Already active and a script put the Pip-Boy back on (e.g. leaving Tranquility Lane): take it off again
\tif Init == 2
\t\tif player.GetEquipped PipBoy == 1 || player.GetEquipped PimpBoy == 1 || player.GetEquipped PipBoyGlove == 1
\t\t\tplayer.UnequipItem PipBoy 1 1
\t\t\tplayer.UnequipItem PimpBoy 1 1
\t\t\tplayer.UnequipItem PipBoyGlove 1 1
\t\t\tset Strip to 1
\t\t\treturn
\t\tendif
\tendif
\t; --- end of patch ---

"""


def remap(fid):
    """Readius_NV.esp numbering (0 FalloutNV, 1 itself) -> the patch's (0 FalloutNV, 1 Fallout3, 2 Readius)."""
    return (fid & 0xFFFFFF) | (2 << 24) if fid >> 24 == 1 else fid


def patched_script(rec):
    subs = rec.subrecords
    get = lambda t: next(s for s in subs if s.type == t)              # noqa: E731
    stmts = sc.parse(get(b"SCDA").data)
    sc.check(stmts)

    # references: 1-based list of SCRO (form) / SCRV (local ref var) in record order
    refs = [s for s in subs if s.type in (b"SCRO", b"SCRV")]
    def ref_index(fid):
        for i, s in enumerate(refs, 1):
            if s.type == b"SCRO" and struct.unpack("<I", s.data)[0] == fid:
                return i
        raise SystemExit(f"Readius script doesn't reference {fid:08X}; is this Readius NV 1.1?")
    player, pipboy, pimpboy, glove = (ref_index(f) for f in (0x14, 0x15038, 0x11BACB, 0x25B83))
    new_refs = [Subrecord(b"SCRO", struct.pack("<I", f)) for f in (CG02, CG03, CG04)]
    cg02, cg03, cg04 = len(refs) + 1, len(refs) + 2, len(refs) + 3

    # local variable indexes come from the script's own SLSD records
    names = {}
    for i, s in enumerate(subs):
        if s.type == b"SLSD":
            names[subs[i + 1].data.rstrip(b"\0").decode()] = struct.unpack_from("<I", s.data)[0]
    init, strip = names["Init"], names["Strip"]

    # where: right after the opening "if player has no Pip-Boy: return / endif"
    begin = next(i for i, s in enumerate(stmts) if s.op == sc.BEGIN)
    assert [s.op for s in stmts[begin + 1:begin + 4]] == [sc.IF, sc.RETURN, sc.ENDIF], "unexpected script layout"
    at = begin + 4

    running = lambda q: sc.call(GET_QUEST_RUNNING, sc.ref(q))                      # noqa: E731
    equipped = lambda item: (sc.call(GET_EQUIPPED, sc.ref(item), on=player), "1", "==")  # noqa: E731
    unequip = lambda item: sc.Statement(UNEQUIP_ITEM, struct.pack("<H", 3)                         # noqa: E731
                                         + sc.ref(item) + sc.int_param(1) + sc.int_param(1),
                                        ref=player)
    set_strip = sc.Statement(sc.SET, sc.local("s", strip) + struct.pack("<H", 2) + b" 1")
    add = [
        # Readius used to swap in the gaps between the Vault 101 scenes (birthday -> G.O.A.T. -> escape),
        # so the arm Pip-Boy went missing in the vault: wait until the escape is completed.
        sc.if_(sc.IF, sc.expr(running(cg02), running(cg03), "||", running(cg04), "||",
                              sc.call(GET_STAGE, sc.ref(cg02)), "0", ">",
                              sc.call(GET_QUEST_COMPLETED, sc.ref(cg04)), "0", "==", "&&", "||")),
        sc.Statement(sc.RETURN),
        sc.Statement(sc.ENDIF),
        sc.if_(sc.IF, sc.expr(sc.local("s", init), "2", "==")),
        sc.if_(sc.IF, sc.expr(*equipped(pipboy), *equipped(pimpboy), "||", *equipped(glove), "||")),
        unequip(pipboy), unequip(pimpboy), unequip(glove),
        set_strip,
        sc.Statement(sc.RETURN),
        sc.Statement(sc.ENDIF),
        sc.Statement(sc.ENDIF),
    ]
    code = sc.build(stmts[:at] + add + stmts[at:])

    src = get(b"SCTX").data.decode("cp1252")
    if SOURCE_ANCHOR not in src:
        raise SystemExit("Readius script source differs from 1.1; not patching.")
    src = src.replace(SOURCE_ANCHOR, SOURCE_ADD.replace("\n", "\r\n") + SOURCE_ANCHOR, 1)

    schr = bytearray(get(b"SCHR").data)
    struct.pack_into("<II", schr, 4, len(refs) + len(new_refs), len(code))

    out = []
    for s in subs:
        if s.type == b"SCHR":
            out.append(Subrecord(b"SCHR", bytes(schr)))
        elif s.type == b"SCDA":
            out.append(Subrecord(b"SCDA", code))
        elif s.type == b"SCTX":
            out.append(Subrecord(b"SCTX", src.encode("cp1252")))
        elif s.type == b"SCRO":
            out.append(Subrecord(b"SCRO", struct.pack("<I", remap(struct.unpack("<I", s.data)[0]))))
        else:
            out.append(s)
    last_ref = max(i for i, s in enumerate(out) if s.type in (b"SCRO", b"SCRV"))
    out[last_ref + 1:last_ref + 1] = new_refs
    return Record(b"SCPT", rec.flags & ~0x00040000, remap(rec.form_id), rec.vc1, rec.form_version, rec.vc2,
                  build_subrecords(out))


def header(readius):
    subs = [Subrecord(b"HEDR", struct.pack("<fII", 1.34, 1, 0x800)),
            Subrecord(b"CNAM", b"FOLM\0"),
            Subrecord(b"SNAM", b"Pip-Boy Readius for Tale of Two Wastelands 3.x. Overrides only Readius's own "
                               b"script: waits until the Vault 101 escape is done and takes the arm Pip-Boy off again "
                               b"when a TTW script puts it back on. Made on your PC by FOLM from your Readius_NV.esp.\0")]
    for m in MASTERS:
        subs += [Subrecord(b"MAST", m.encode() + b"\0"), Subrecord(b"DATA", b"\0" * 8)]
    h = readius.header
    return Record(b"TES4", 0, 0, h.vc1, h.form_version, h.vc2, build_subrecords(subs))


def main(src, dst):
    readius = Plugin.load(src)
    if readius.masters != ["FalloutNV.esm"]:
        raise SystemExit("That isn't Readius NV 1.1's Readius_NV.esp.")
    rec = next((r for r in readius.records() if r.form_id == SCRIPT_ID and r.type == b"SCPT"), None)
    if rec is None:
        raise SystemExit("BIDEpipRemoverNVSCRIPT not found.")
    new = patched_script(rec)
    g = Group(b"SCPT", 0, 0, 0, 0, 0)
    g.children.append(new)
    Plugin(header(readius), [g], name=os.path.basename(dst)).save(dst)
    # read it back and check it
    p = Plugin.load(dst)
    r = next(p.records())
    sc.check(sc.parse(next(s.data for s in r.subrecords if s.type == b"SCDA")))
    print(f"Wrote {dst}: masters {p.masters}, 1 record (Readius's script, {len(sc.parse(next(s.data for s in r.subrecords if s.type == b'SCDA')))} statements).")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])
