# Recommended mods for smooth play on Linux

These are stability and performance mods, not content. They fix the engine's crashes, stutter and slow
loading, and most of them are needed by other mods anyway. The lists follow the community guides
[Viva New Vegas](https://vivanewvegas.moddinglinked.com/) and
[The Best of Times](https://thebestoftimes.moddinglinked.com/) (ModdingLinked), checked November 2026,
plus what we learned running the games under Proton.

✅ = tested with FOLM on Linux (see [compatibility.md](compatibility.md)). Install each one by dragging its
archive onto FOLM (or `folm.py install`). FOLM puts root files next to the game's exe automatically.

## Linux first: what FOLM already handles

- **FPS cap at 120.** Above ~120 FPS the physics break. FOLM caps frames through DXVK (⚙ Settings → FPS cap),
  so you can turn V-Sync off without a separate limiter.
- **Windowed mode at your screen's resolution.** Fullscreen can make the game vanish on alt-tab under
  Proton. Set `bFull Screen=0` (the guides' INI uses fullscreen; that's written for Windows).
- **Archive invalidation** and **case-sensitive file names**: handled on deploy.
- **The 4GB patch**: FOLM's pre-Play check warns if verifying files in Steam has undone it.
- **Low RAM** (8 GB or less): close Firefox and other big apps before playing, skip 4K texture packs, and
  consider [earlyoom](https://github.com/rfjakob/earlyoom) so the PC doesn't freeze when memory runs out.

## Fallout: New Vegas (Courier), and TTW

Install in this order. The first group goes next to `FalloutNV.exe`.

| Mod | Nexus | Why | |
|---|---|---|---|
| **xNVSE** | [67883](https://www.nexusmods.com/newvegas/mods/67883) | Script extender. Almost everything below needs it | ✅ |
| **4GB Patcher** | [62552](https://www.nexusmods.com/newvegas/mods/62552) | Lets the game use 4 GB of RAM and starts xNVSE. Run it once; re-run after a Steam "verify files" | ✅ |
| **JIP LN NVSE** + Settings INI | [58277](https://www.nexusmods.com/newvegas/mods/58277) | Engine fixes; enables `FalloutCustom.ini`, which FOLM uses | ✅ |
| **JohnnyGuitar NVSE** (+ INI presets [86200](https://www.nexusmods.com/newvegas/mods/86200)) | [66927](https://www.nexusmods.com/newvegas/mods/66927) | Engine fixes and functions | ✅ |
| **ShowOff xNVSE** + INI | [72541](https://www.nexusmods.com/newvegas/mods/72541) | Engine fixes and functions | ✅ |
| **NVTF – New Vegas Tick Fix** + INI | [66537](https://www.nexusmods.com/newvegas/mods/66537) | Smooth frame pacing, stable physics up to ~120 FPS | ✅ |
| **lStewieAl's Tweaks and Engine Fixes** | [66347](https://www.nexusmods.com/newvegas/mods/66347) | Hundreds of engine fixes, Tweaks menu | ✅ |
| **lStewieAl's Engine Optimizations** | [80993](https://www.nexusmods.com/newvegas/mods/80993) | Faster loading and saving | |
| **Combat Lag Fix** | [71973](https://www.nexusmods.com/newvegas/mods/71973) | Frame drops in combat | |
| **VATS Lag Fix** | [84823](https://www.nexusmods.com/newvegas/mods/84823) | Frame drops in VATS | |
| **ActorCause Save Bloat Fix** | [80666](https://www.nexusmods.com/newvegas/mods/80666) | Smaller saves, faster save/load | |
| **FNV Mod Limit Fix** | [68714](https://www.nexusmods.com/newvegas/mods/68714) | Raises the open-file limit; needed for big mod lists | |
| **kNVSE Animation Plugin** | [71336](https://www.nexusmods.com/newvegas/mods/71336) | Animation framework many mods need | ✅ |
| **UIO – User Interface Organizer** | [57174](https://www.nexusmods.com/newvegas/mods/57174) | Lets menu mods share the game's menu files | ✅ |
| **Yvile's Crash Logger** | [82540](https://www.nexusmods.com/newvegas/mods/82540) | Writes crash logs for crash reports. The guides' current pick; we've tested the older Crash Logger ([72317](https://www.nexusmods.com/newvegas/mods/72317)) | |
| **Yukichigai Unofficial Patch (YUP)** | [51664](https://www.nexusmods.com/newvegas/mods/51664) | Thousands of game bug fixes. TTW players: use **YUPTTW** from mod.pub instead | ✅ (YUPTTW) |

**Tale of Two Wastelands** also needs the **TTW NVSE plugin** ([77415](https://www.nexusmods.com/newvegas/mods/77415)) ✅.
Install TTW itself with the TTW team's installer from [mod.pub](https://mod.pub/ttw/133). FOLM manages the result.

Nice to have: **MCM** ([42507](https://www.nexusmods.com/newvegas/mods/42507)) with its BugFix file, for mods that
have settings menus ✅; Improved Console ([70801](https://www.nexusmods.com/newvegas/mods/70801)).

## Fallout 3 (Wanderer), without TTW

Not tested with FOLM yet (Wanderer testing is on the roadmap). The first group goes next to `Fallout3.exe`.

| Mod | Nexus | Why |
|---|---|---|
| **FOSE** | [8606](https://www.nexusmods.com/fallout3/mods/8606) | Script extender |
| **Fallout Anniversary Patcher** | [24913](https://www.nexusmods.com/fallout3/mods/24913) | Patches the Steam exe so FOSE works |
| **Unofficial Fallout 3 ESM Patcher** | [25717](https://www.nexusmods.com/fallout3/mods/25717) | Fixes base-game records for stability |
| **Command Extender** | [23682](https://www.nexusmods.com/fallout3/mods/23682) | JIP LN's fixes ported to FO3; enables `FalloutCustom.ini` |
| **High FPS Physics Fix** | [27036](https://www.nexusmods.com/fallout3/mods/27036) | FO3's tick fix: stable physics up to ~120 FPS |
| **lStewieAl's Tweaks** (FO3) | [23561](https://www.nexusmods.com/fallout3/mods/23561) | Engine fixes. Leave `bTickFix` off; the physics fix covers it |
| **Combat Lag Fix (FOSE)** | [24647](https://www.nexusmods.com/fallout3/mods/24647) | Frame drops in combat |
| **ActorCause Save Bloat Fix (FOSE)** | [25601](https://www.nexusmods.com/fallout3/mods/25601) | Smaller saves |
| **zlib Updated – FOSE** | [26126](https://www.nexusmods.com/fallout3/mods/26126) | Faster loading |
| **Updated Unofficial Fallout 3 Patch** | [19122](https://www.nexusmods.com/fallout3/mods/19122) | Game bug fixes |

## Avoid

- **Old crash/memory fixes** like NVAC and the old Heap Replacer: replaced by the plugins above. Yvile's
  Crash Logger is the modern crash tool.
- **INI "optimizer" tools** (BethINI and similar): the guides advise against them. FOLM changes only the
  settings it needs and undoes them exactly.
- **Script-heavy overhauls** (e.g. Project Nevada) in a modern setup: they bloat saves; the community's
  Safe Modding list advises against them.
- **Removing mods mid-playthrough**: FOLM warns you when your saves use a mod you're turning off.

## Credits

Mod lists from ModdingLinked's Viva New Vegas and The Best of Times guides, and the authors of every mod
above. Download from the official pages. FOLM doesn't redistribute any of them.
