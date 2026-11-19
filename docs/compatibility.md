# FOLM compatibility list

Every mod tested with FOLM on Linux (Steam + Proton). "Installs" = FOLM staged it
with no manual steps. "In game" = confirmed working after launch.

Test setup: Linux Mint (Cinnamon, X11), Fallout: New Vegas (Steam, all DLC),
Fallout 3 GOTY, GE-Proton10-34, FOLM v0.3.

| Mod | Version | Source | FOLM type | Installs | In game | Notes |
|---|---|---|---|---|---|---|
| Tale of Two Wastelands | 3.4 | mod.pub | ttw-installer | ✅ (Wine sandbox, `-NoOggEnc2`, ~21 min) | ✅ loads | Installer needs game paths in the sandbox registry; `proton run` fails silently, Proton's wine works |
| YUPTTW | 13.9.1 | mod.pub | data | ✅ | ✅ loads | Load after TTW; wins 5 files over TTW |
| xNVSE | 6.4.9 | GitHub | data+game-root | ✅ | ✅ (nvse.log) | Root files placed next to FalloutNV.exe automatically |
| FNV 4GB Patcher (for Proton) | 1.5 | Nexus 62552 | tool | n/a (run manually) | ✅ flag set | Native Linux binary; drops the exe's executable bit (FOLM restores it). TTW still warned "not 4GB patched" before its required plugins were installed — recheck |
| TTW NVSE ("ROOGNVSE") | 3.3.3b | Nexus 77415 | data | ✅ | ✅ (nvse.log) | Runs TTW's startup dependency checks |
| MCM (XML FOMOD) | 1.5.1 | Nexus 42507 | fomod-xml | ✅ (FOLM FOMOD installer) | ⏳ DLL loads; menu button pending | Needed archive redating: TTW's `Fallout - Misc.bsa` has its own start_menu.xml and was newer |
| MCM BugFix 2 | 1.5.1 | Nexus 42507 | data | ✅ | ⏳ | Wins MCM's esp |
| JIP LN NVSE | 57.30 | Nexus 58277 | data | ✅ | ⏳ | Required for FalloutCustom.ini |
| JIP LN Settings INI | 56.24 | Nexus 58277 | data | ✅ | ⏳ | |
| JohnnyGuitar NVSE | 5.28 | Nexus 66927 | data | ✅ | ⏳ | TTW requires ≥ 5.01 |
| ShowOff xNVSE | 1.84 | Nexus 72541 | data | ✅ | ⏳ | TTW requires ≥ 1.80 |
| ShowOff INI | 1 | Nexus 72541 | data | ✅ | ⏳ | |
| UIO – User Interface Organizer | 2.30 | Nexus 57174 | data | ✅ | ⏳ | Lets menu mods share the game's menu files |
| lStewieAl's Tweaks | 10.05 | Nexus 66347 | data | ✅ | ⏳ | TTW requires ≥ 9.41. Capitalised `Menus/` + `NVSE/` merged by FOLM's case fixing |
| Stewie Tweaks INI | 2.1 | Nexus 66347 | data | ✅ | ⏳ | Empty starter file; the plugin fills in options on launch |
| Perk Per Level | 1.0 | Nexus 66347 | data | ✅ | ⏳ | Gameplay change (perk every level) |
| kNVSE Animation Plugin | 37 | Nexus 71336 | data | ✅ | ⏳ | TTW guide essential |
| NVTF – New Vegas Tick Fix | 10.61 (+ INI 1.06) | Nexus 66537 | data | ✅ | ⏳ | Needed with V-Sync off |
| Crash Logger (writes CobbCrashLogger.log) | 3.0 | Nexus 72317 | data | ✅ | ⏳ | Replacement for NVAC. The guides now recommend the newer Yvile's Crash Logger (Nexus 82540), not tested yet |
| GECK (New Vegas Edition) | 1.4 | user's zip (copied Geck.exe + ssce5432.dll into the game folder) | tool | ✅ | ✅ opens via FOLM's Tools tab | Launched through xNVSE's editor loader (`nvse_loader.exe -editor`) in the game's Proton prefix; FOLM sets bAllowMultipleMasterLoads=1. Capturing saved work not yet tested with the real GECK |
| Project Nevada | 2.5 | Nexus 40040 | fomod-csharp (old FOMM script) | ✅ (FOLM legacy installer: Mono + FOMM shim + bubblewrap sandbox) | ⏳ not deployed (Testing profile only; not for TTW) | The mod's own WinForms installer ran natively. Needed: `CreateCustomForm` in the shim; font-matched scaling (layout was stretched off-window). Patched the player's current start_menu.xml (+5 lines) like FOMM did. 756 files, 16 duplicate-case folders merged. Community Safe Modding list advises against using it in a modern setup |

## Problems found and fixed in FOLM while testing

- **Loose files losing to archives:** the engine only uses a loose file if it's newer than the
  archive. FOLM now redates every archive on deploy (undo restores exact dates).
- **Case-mismatched folders** (`Menus` vs `menus`, `NVSE/plugins` vs `nvse/plugins`): merged on deploy.
- **TTW installer under Wine:** 12+ hours with per-file `oggenc2.exe`; ~21 minutes with `-NoOggEnc2`.
- **Old FOMM C# installers:** now compiled with Mono against FOLM's FOMM shim and run in a bubblewrap sandbox (no network, no home folder, writes only to staging). Windows Forms layouts are font-matched so they aren't stretched off-window.
- **RAR archives 7-Zip can't unpack** ("Unsupported Method"): FOLM falls back to `unrar`.
- **`fomod/` with only info.xml** (OneTweak, Enhanced Blood): installed as plain mods, `fomod/` left out.
- **Archives wrapping an old `.fomod` package** (BOG): unwrapped, the inner package installed by its own installer.
- **TTW's required INI settings:** FalloutCustom.ini (read by JIP LN) with `SCharGenQuest=001FFFF8`.

### Pip-Boy Readius NV 1.1 with TTW 3.x: FOLM-built patch

LOOT flags Readius as incompatible with TTW 3.2+. The 2015 *Readius TTW Fix* is for TTW 2.x: it rewrites TTW's
Vault 101 quests (CG02–CG04, Tranquility Lane) with their old versions, and its own Readius scripts never compiled
(no Readius master). Don't use it with TTW 3.

`tools/make_readius_ttw_patch.py "<Readius_NV.esp>" "Readius TTW Patch.esp"` builds a patch from your copy of
Readius. It overrides only Readius's own quest script: Readius waits while the Vault 101 childhood quests run,
and if any script puts the arm Pip-Boy (or Pimp-Boy, glove) back on, Readius takes it off again. No TTW
record is changed. Load it after Readius_NV.esp (LOOT does). Compiled with FOLM's `scriptcode` module
(GECK's own bytecode patterns; see development-log.md). Not yet play-tested through a Vault 101 start.

### Vegas Shaders 1.1.0 (Nexus 100538) under Proton: ✅ works

Tested 2026-11-18, TTW 3.4, New Vegas start, i3-7100 + RX 580, 1920x1080, Proton 10 with the mod's own DXVK build
(`d3d9.dll` next to the exe, "Vegas Shaders DXVK extension 1.6 on DXVK v3.0.1": compute paths available).
Default settings: TAA + FSR 1 at RenderScale 0.67, about 35–40 FPS outdoors (frame time 25–29 ms).

- **Needs, though its page doesn't say:** LOD Flicker Fix - NVSE (91705) and Vanilla Plus Terrain (92519), which
  both need Shader Loader - NVSE (87814). Without them the plugin shows "… cannot be used without it" and turns off.
  FOLM's requirement scan reads this from the DLL.
- Optional and probably redundant: Parallax Shaders - Terrain (92708). Vegas Shaders has its own terrain parallax
  ([Shaders.Terrain.Parallax], on by default).
- Menu key **O**; settings are saved to `Data/NVSE/Plugins/VegasShaders.toml` only when you Save in the menu.
- Performance options for weaker PCs ([Main.Main.ReducedQuality]): AOLowRes, GodRaysLowRes, ParallaxLite,
  CachedDistantShadows; [Shaders.Terrain.Parallax] HighQuality = false; FSR RenderScale.
