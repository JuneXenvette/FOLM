"""fo3convert - check a Fallout 3 mod for what converting it to TTW will need.

Stage 1 of FOLM's own, Linux-native FO3 -> TTW converter: a report of what a
plugin needs before it will work in TTW. FOLM uses no TTW tools, scripts or
databases. The engine facts it checks for (FO3 vs FNV differences, TTW's rules)
were learned from the TTW team's public conversion guidelines; credit to them.

Later stages (see docs/fo3-converter.md): add + sort TTW masters with FormID
renumbering, FOLM's own remap table built from the player's FO3 and TTW files,
then a guided GECK pass (TTW requires plugins to be updated in GECK).
"""

import re
from collections import Counter, defaultdict

from .esp import Plugin

# The masters a converted plugin must have, in this order (from the guidelines).
TTW_MASTERS = [
    "FalloutNV.esm", "DeadMoney.esm", "HonestHearts.esm", "OldWorldBlues.esm",
    "LonesomeRoad.esm", "GunRunnersArsenal.esm", "Fallout3.esm", "Anchorage.esm",
    "ThePitt.esm", "BrokenSteel.esm", "PointLookout.esm", "Zeta.esm",
    "TaleOfTwoWastelands.esm",
]

# Record types whose layout changed between FO3 and FNV: open and update in GECK.
CHANGED_TYPES = {
    "FACT": "now has a Reputation field", "ASPC": "several new fields", "TACT": "new field",
    "PROJ": "several new fields", "PERK": "many new entry points",
    "DIAL": "follow-ups and other new fields", "LSCR": "new field", "MISC": "new field",
    "SCPT": "many new functions; recompile each script individually", "SOUN": "new flags",
    "STAT": "new field", "WEAP": "many new fields", "WTHR": "new fields", "AMMO": "new fields",
    "ALCH": "new fields", "ARMO": "new fields", "ARMA": "new fields", "CONT": "new field",
}

# Script source patterns that need attention, per the guidelines.
SCRIPT_CHECKS = [
    (re.compile(r"\baddachievement\b", re.I), "uses AddAchievement: FO3 achievements don't work; TTW uses challenges. Comment it out."),
    (re.compile(r"\bgetweaponammo\b", re.I), "uses GetWeaponAmmo: in FNV it can return an ammo OR a form list (check with GetType); 0 for no-ammo weapons."),
    (re.compile(r"\bTTWFunctions\b|\bTTWFN\w+|\bTTWHasNVSE\b|\bTTWNVSEVersion\w*", re.I),
     "uses deprecated TTWFunctions calls/variables; replace (e.g. SetGameHour for passing time)."),
    (re.compile(r"\bPCMiscStat\b|\bIncrementPCMiscStat\b|\bGetPCMiscStat\b", re.I),
     "uses misc stats: most exist in FNV; a few FO3-only ones were added by TTW. Check the names."),
    (re.compile(r"\b(SmallGuns|Throwing|DetectLifeRange)\b", re.I),
     "references an actor value that changed: Small Guns->Guns, Throwing->Survival, Detect Life Range->Turbo."),
    (re.compile(r"\bBigGuns\b", re.I), "references Big Guns: disabled in FNV but still works (can be re-enabled via JIP LN)."),
    (re.compile(r"\bSetStage\s+(StartupQuest|GenericHandler)\w*|\b(StartupQuest|TTWGeneric)\w*", re.I),
     "touches the startup / generic handler quests: TTW says never modify these."),
]

DELETED = 0x20


def _edid(rec):
    for s in rec.subrecords:
        if s.type == b"EDID":
            return s.data.split(b"\0", 1)[0].decode("cp1252", "replace")
    return f"{rec.form_id:08X}"


def check(path, has_meshes=False):
    """Return a report: {'summary': {...}, 'findings': [(severity, area, message), ...]}"""
    p = Plugin.load(path)
    masters = p.masters
    n = len(masters)
    is_esm = bool(p.header.flags & 0x1) or path.lower().endswith(".esm")
    types, new_types = Counter(), Counter()
    overrides = defaultdict(list)
    navm_deleted, scripts, findings = [], 0, []
    script_hits = defaultdict(set)

    for r in p.records():
        t = r.type.decode()
        types[t] += 1
        own = (r.form_id >> 24) >= n
        if own:
            new_types[t] += 1
        else:
            overrides[t].append(r)
        if t == "NAVM" and r.flags & DELETED:
            navm_deleted.append(r.form_id)
        if t in ("SCPT", "INFO", "QUST", "PACK", "TERM"):
            for s in r.subrecords:
                if s.type == b"SCTX":
                    scripts += 1
                    src = s.data.decode("cp1252", "replace")
                    for rx, msg in SCRIPT_CHECKS:
                        if rx.search(src):
                            script_hits[msg].add(_edid(r))

    add = lambda sev, area, msg: findings.append((sev, area, msg))

    # format / masters
    if p.version != 0.94:
        add("info", "format", f"header version {p.version}: this doesn't look like a Fallout 3 plugin (0.94).")
    missing = [m for m in TTW_MASTERS if m.lower() not in {x.lower() for x in masters}]
    add("auto", "masters", f"add {len(missing)} TTW master(s) and sort masters (FOLM stage 2 does this and renumbers every reference).")
    add("auto", "records", "re-point references to Fallout 3 records that TTW moved or replaced (FOLM stage 3: its own remap table, built from your FO3 and TTW files).")

    # navmesh rules (marked important in the guidelines)
    if types["NAVM"]:
        if not is_esm:
            add("must", "navmesh", f"{types['NAVM']} navmesh(es) in an ESP: navmeshes in ESPs break. Make it an ESM.")
        add("must", "navmesh", "navmeshes must be re-finalized in GECK for FNV.")
    if navm_deleted:
        add("must", "navmesh", f"{len(navm_deleted)} deleted navmesh(es): these crash. Undelete them in xEdit instead.")
    new_cells = new_types["CELL"] + new_types["WRLD"]
    if new_cells and not types["NAVM"]:
        add("must", "navmesh", f"{new_cells} new cell(s)/worldspace(s) but no navmesh: every cell must be navmeshed (companions crash otherwise).")

    # changed record types
    for t, why in CHANGED_TYPES.items():
        if types[t]:
            add("gecK", "records", f"{types[t]} {t} record(s): {why}.")

    # scripts
    if scripts:
        add("must", "scripts", f"{scripts} script(s) to recompile one by one in GECK (never 'recompile all'). FO3's compiler didn't check errors, so expect fixes.")
    for msg, where in sorted(script_hits.items()):
        add("must", "scripts", f"{msg}  [in: {', '.join(sorted(where)[:6])}{' ...' if len(where) > 6 else ''}]")

    # gameplay systems
    if overrides["QUST"]:
        names = ", ".join(sorted(_edid(r) for r in overrides["QUST"])[:8])
        add("check", "quests", f"edits {len(overrides['QUST'])} existing quest(s) ({names}): make sure none are the startup, generic handler or Followers quests.")
    if new_types["NPC_"]:
        add("check", "companions", f"{new_types['NPC_']} new NPC(s): companions need the companion wheel topics, their own quest, and the standard follower script variables.")
    if types["WEAP"] or types["ARMO"] or types["ALCH"]:
        add("check", "economy", "weapons/armor/ingestibles: rebalance values, durability and DR/DT; give food and healing Hardcore effects.")
    if types["LVLI"] or types["LVLN"] or types["LVLC"]:
        add("check", "leveled lists", "edits leveled lists: TTW greatly expanded these, so merge carefully.")
    if types["LSCR"] or new_cells:
        add("check", "loading screens", "TTW load screens are always location-specific: add your cells/worldspaces to your own load screens.")
    if new_types["CELL"] or new_types["WRLD"]:
        add("check", "music", "cell/worldspace music settings don't work in FNV: use an Audio Marker with a media set.")
    if types["CREA"] or types["STAT"]:
        add("check", "models", "TTW changed some creature/static model paths (look for 'dc' in TTW's BSAs, e.g. super mutants): re-point references if needed.")
    if has_meshes:
        add("check", "meshes", "custom meshes: update MOPP; weapons need sighting nodes/extra data for FNV.")

    add("must", "permission", "you need the original author's permission to convert their mod, and to share the conversion. Keep a record of it.")
    add("must", "geck", "TTW checks that converted plugins were updated in GECK: finish the conversion with a GECK pass, then clean in FNVEdit.")

    summary = {"plugin": p.name, "header_version": p.version, "esm": is_esm, "masters": masters,
               "records": sum(types.values()), "new": sum(new_types.values()),
               "overrides": sum(len(v) for v in overrides.values()), "scripts": scripts}
    return {"summary": summary, "findings": findings}


SEV_ORDER = {"must": 0, "gecK": 1, "check": 2, "auto": 3, "info": 4}
SEV_LABEL = {"must": "MUST FIX", "gecK": "IN GECK", "check": "CHECK", "auto": "FOLM AUTO", "info": "INFO"}


def format_report(rep):
    s = rep["summary"]
    out = [f"{s['plugin']}  (Fallout 3 format v{s['header_version']}, {'ESM' if s['esm'] else 'ESP'})",
           f"  {s['records']} records: {s['new']} new, {s['overrides']} edits of existing records; {s['scripts']} script(s)",
           f"  masters: {', '.join(s['masters']) or '(none)'}", ""]
    for sev, area, msg in sorted(rep["findings"], key=lambda f: SEV_ORDER[f[0]]):
        out.append(f"  [{SEV_LABEL[sev]:9}] {area}: {msg}")
    return "\n".join(out)
