# FO3 → TTW mod converter (Linux-native)

Goal: bring Fallout 3 mods to the New Vegas engine without Windows tools
(FNVEdit/xEdit under Wine), as far as conversion can be automated.

Two targets:

- **→ TTW** (optional, for players using Tale of Two Wastelands): the mod keeps its
  Fallout 3 world references, re-pointed at TTW's versions of them.
- **→ plain New Vegas**: ***<ins>only</ins>*** for item mods that don't depend on Fallout 3's
  world: **gear, weapons, items, clothes, armor and perks**. **<ins>Not</ins>** quests,
  player homes, companions, enemies/creatures/NPCs or new locations — those need TTW. Masters become New Vegas only; any leftover
  reference to a Fallout 3 record is reported so it can be replaced with a New Vegas one
  or removed. The report will say up front which target a mod can reach.

**FOLM's own converter.** It uses no TTW tools, scripts or databases: no TTW Conversion
Package, no xEdit script, no `TTWConversion.csv`. Everything is FOLM code working on the
player's own game files.

Credit: what to check for (engine differences between FO3 and FNV, and TTW's rules) was
learned from the TTW team's public *Mod Conversion Guidelines* (Roy Batty and team). This
document is our own summary of those facts; read the original for the full guidelines.

## Ground rules (from the guidelines)

- **Permission:** converting someone's mod — and especially sharing the result —
  needs the original author's permission. FOLM shows this on every report.
- **GECK pass is required:** TTW checks that converted plugins were updated in GECK.
  FOLM automates the mechanical steps and guides the GECK step; it can't replace it.
- **Never "recompile all"** scripts in GECK; recompile them one at a time.

## Stages

| # | Stage | How | Status |
|---|---|---|---|
| 0 | Plugin reader/writer | `folm_core/esp.py`, pure Python. Verified byte-identical round trips on all five FO3 DLC plugins (~213k records) | ✅ |
| 1 | **Report** (`folm.py convert-check`) | Flags everything the guidelines list: navmesh rules, scripts to recompile + risky functions in script source, record types whose layout changed, quest edits, companions, economy, leveled lists, load screens, music, model paths, meshes | ✅ |
| 2 | Masters | Add the 13 TTW masters (FalloutNV, DeadMoney, HonestHearts, OldWorldBlues, LonesomeRoad, GunRunnersArsenal, Fallout3, Anchorage, ThePitt, BrokenSteel, PointLookout, Zeta, TaleOfTwoWastelands) and sort them. Every FormID's top byte is a master index, so **every FormID field in every record must be renumbered**. Needs a map of which subrecord fields hold FormIDs per record type — planned source: xEdit's open-source definitions (MPL-2.0; credit and license terms kept) | planned |
| 3 | **FOLM remap table** (our own) | Build "FO3 record → TTW record" automatically from the player's own files: read the original `Fallout3.esm` + DLCs and TTW's versions, match by EditorID, record type and content, and work out what TTW moved, merged or replaced. Ambiguous matches are shown to the player instead of guessed. Rebuilds itself when TTW updates | planned |
| 4 | Header + validation | Mark the plugin as New Vegas format, re-read it with our parser, re-run the report | planned |
| 5 | Guided GECK pass | Checklist from the report, one item at a time; optional screen-driven help | planned |

## What the report checks (summary)

- **Navmesh:** must be in an ESM, re-finalized for FNV, never deleted; every new cell needs one.
- **Scripts:** recompile individually; flags AddAchievement, GetWeaponAmmo, deprecated TTWFunctions,
  misc stats, changed actor values (Small Guns→Guns, Throwing→Survival, Detect Life Range→Turbo, Big Guns),
  and anything touching TTW's startup/handler quests.
- **Changed record types:** FACT, ASPC, TACT, PROJ, PERK, DIAL, LSCR, MISC, SCPT, SOUN, STAT, WEAP,
  WTHR, AMMO, ALCH, ARMO, ARMA, CONT.
- **Systems:** quest edits (never the startup/handler/Followers quests), companions (companion wheel),
  economy and Hardcore, leveled lists, location-specific load screens, music via audio markers,
  TTW's "dc" model paths, MOPP and weapon sighting nodes on custom meshes.

Not automated yet (manual per guidelines): crafting → recipe system, companion rework,
weapon animations, sound/acoustic differences, collision materials.
