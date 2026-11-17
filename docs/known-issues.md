# Known problems with other mod managers (and how FOLM handles them)

Research notes, November 2026. Summarised from community guides, Nexus/STEP forums and
Linux gaming communities (sources at the bottom). Most sources are forum posts, so details
may be dated; each item is something FOLM should handle, test, or warn about.

## Mod managers on Linux

| Problem | Seen with | FOLM |
|---|---|---|
| MO2's virtual file system (USVFS) is a Windows hooking trick; under Wine/Proton it's fragile, version-sensitive, and some MO2 releases didn't work in Proton at all | MO2 | ✅ Native Linux, no VFS: hard links into the real Data folder |
| MO2 on Linux may not see games installed after MO2; you must start the game through MO2 | MO2 (Linux installer) | ✅ FOLM finds Steam libraries each time; Play goes through Steam |
| Tools like GECK only see mods when launched "inside" MO2's VFS | MO2 | ✅ Mods are really deployed, so GECK/FNVEdit see them with no special launch |
| "Mod Manager Download" (`nxm://`) links fail on Linux: browser hands the link to the wrong app, or "unknown protocol" | Vortex, MO2 | ⏳ Planned. Register a proper `x-scheme-handler/nxm` desktop entry and test Firefox + Chrome |
| Case-sensitive file system: `Textures/` vs `textures/` creates duplicates that the game ignores | All on Linux | ✅ Case merging on install and deploy |
| Vortex isn't officially supported on Linux | Vortex | ✅ Built for Linux |

## Deployment problems

| Problem | Seen with | FOLM |
|---|---|---|
| Hard links only work when mods and game are on the same drive; otherwise deploy fails or silently changes method | Vortex | ⚠️ FOLM falls back to copying. **To do:** warn up front and show the extra disk space it will use |
| Symlink deployment doesn't work for New Vegas | Vortex | ✅ FOLM uses hard links, not symlinks |
| Switching deployment methods deleted deployed mods | Vortex | ✅ One method; every deploy is recorded and undone exactly |
| Editing a mod's files in place breaks the manager's tracking | Vortex | ✅ The Overwrite catcher detects changed files and keeps them |
| Using two managers at once leaves the Data folder full of files neither manages | Vortex + MO2 + manual | ⏳ **To do:** on first setup, find loose files that aren't vanilla and offer to adopt them into a FOLM mod ("leftovers from another manager") |
| Loose files lose to archives unless archive invalidation is set up | All | ✅ Archive invalidation setting (on by default) |

## Installers

| Problem | Seen with | FOLM |
|---|---|---|
| Old FOMM C# script installers fail or need special builds | MO2 (some versions), Vortex | ✅ Native Mono + FOMM shim, sandboxed |
| FOMOD installers broke between MO2 versions | MO2 | ✅ FOLM's own FOMOD engine, tested on real mods |
| RAR archives with newer compression fail to unpack | 7-Zip-based tools on Linux | ✅ Falls back to `unrar` |

## Game setup problems managers should catch

| Problem | FOLM |
|---|---|
| **Verifying game files in Steam undoes the 4GB patch** (and other exe/BSA patches) | ⏳ **To do:** pre-Play check that the exe is still patched; offer to re-patch |
| The game launcher rewrites `Fallout.ini` with defaults | ✅ FOLM writes its settings to `FalloutCustom.ini` when JIP LN is present |
| **Alt-tab crashes / the window vanishes**: caused by an NVTF setting that keeps textures out of RAM; fixed by windowed mode or DXVK | ✅ Matches what happened on this PC; windowed mode fixed it. **To do:** setup wizard should default Linux players to windowed |
| **Bouncing NPCs / sped-up game**: frame rate above ~120 breaks the physics | ⏳ **To do:** with V-Sync off, set an FPS cap (NVTF supports one) in the setup wizard |
| "Application load error 65434": Steam wasn't running | ⏳ **To do:** pre-Play check that Steam is running |
| "Plugin reported as incompatible during query" in logs | ✅ Harmless (a game plugin seen by GECK or the other way round); crash reports shouldn't flag it |

## Mod-vs-mod problems

| Problem | FOLM |
|---|---|
| **Removing mods mid-playthrough** breaks saves (quests and scripts stay in the save) | ⏳ **To do:** read the plugin list stored in each save and warn before disabling a mod a save depends on |
| Old saves don't work with a big new mod list | ⏳ **To do:** per-profile saves, so each setup keeps its own saves |
| Script-heavy mods cause save bloat (e.g. Project Nevada, spawn mods using PlaceAtMe) | ✅ LOOT warnings; compatibility list. Could add a "known heavy" note |
| Blindly cleaning plugins with FNVEdit can remove edits a mod needs and *cause* crashes | ✅ FOLM shows LOOT's cleaning notes but never cleans automatically |
| Missing masters, wrong load order, incompatible mods | ✅ Master checks, LOOT sorting and warnings, crash reports |

## Sources

- Viva New Vegas FAQ, Safe Modding and Mods to Avoid: https://vivanewvegas.moddinglinked.com/faq.html ,
  https://vivanewvegas.moddinglinked.com/safe-modding.html , https://vivanewvegas.moddinglinked.com/avoid-mods.html
- Modding Dogmas (removing mods mid-game): https://moddinglinked.com/dogmas.html
- MO2 on Linux: https://forums.nexusmods.com/topic/13512108-using-mod-organizer-2-on-linux-the-right-way ,
  https://www.nexusmods.com/fallout4/mods/105285 , https://gamingonlinux.com/forum/topic/6083
- Vortex hard links / drives / symlinks: https://forums.nexusmods.com/topic/13509186-hardlink-deployment-not-an-option ,
  https://forums.nexusmods.com/topic/9062283-mods-cant-be-deployed-only-symlink-available ,
  https://forums.nexusmods.com/topic/7743488-how-to-transfer-mod-data-to-new-hard-drive-and-get-hardlink-deployment-to-work
- Mixing managers: https://forums.nexusmods.com/topic/9292228-another-thread-about-switching-from-vortex-to-mo2
- C# FOMOD installers: https://stepmodifications.org/forum/topic/13074-new-vegas-cant-install-project-nevada-with-mo2 ,
  https://stepmodifications.org/forum/topic/11902-fomod-based-mods-not-installing-through-most-recent-version-of-mod-organizer-v2083/
- nxm links on Linux: https://forum.manjaro.org/t/unable-to-create-io-slave-for-mod-organizer-2/85735 ,
  https://forums.nexusmods.com/topic/13010712-fix-nexus-mods-links-in-chrome-for-steam-deck-linux
- FNVEdit cleaning caution: https://forums.nexusmods.com/topic/943197-can-this-be-correct-massive-dirty-edits
