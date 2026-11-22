# Changelog

What changed in each FOLM release. The newest is on top.

## 1.2.0

The start of the memory project: FOLM now watches the game's 4 GB, warns before it's full and saves
the game for you. The plan is in `docs/memory-project/`.

### New
- **Updates window.** **Check for updates** now opens a window with every mod in your profile in three
  branches: needs an update, up to date, and can't be checked (with why). Every row has a link you can
  click: the mod's Nexus files page; for mods that didn't come from Nexus, their home page, LOOT's link
  for one of their plugins, or a Nexus search. Mods FOLM made on your PC (Generated LOD, Overwrite) are
  marked as nothing to download.
- **Move plugins in the load order.** Right-click a plugin in the Plugins tab: load it earlier or later,
  or keep it at the end of the load order (for mods that must load last, like a weather overhaul). It
  stays last after you add more plugins; undo works for it too.
- **Crash reports read Second Wind's heap log.** With the measuring build of NVHR (the first piece of
  Second Wind, built from NVHR's open source), the report says how big the memory request was that failed
  and how big the largest free gap in the game's 4 GB was, with how full each of NVHR's pools got.
  With Second Wind's v3 build it also says how many big requests its reserve caught, and shows who
  held the 4 GB (NVHR, DLLs, mapped files, the rest). With v4 it knows when the game quit normally, so a
  session where the reserve caught requests and the game then closed isn't reported as a crash.
- **Mod lists.** Settings tab → **Install a mod list…** reads a `.folmlist` file, finds its mods in your
  downloads folder, shows what's missing (with links to the Nexus pages) and installs the rest in order,
  including the list's clean-up steps (removing files, turning plugins off, notes). **Save this profile as
  a mod list…** writes your own. Command line: `folm.py modlist check|install|save`.
- `lists/ttw-lod.folmlist`: the LOD resources from the Viva New Vegas guide, for Tale of Two Wastelands.
- **Memory gauge.** New Vegas and Fallout 3 are 32-bit: they get 4 GB, however much RAM your PC has,
  and crash when it's full. While you play, FOLM now measures how full those 4 GB really are (a tiny
  read-only helper asks the game's own Wine) and warns you on the desktop before they run out: once
  when it's nearly full ("save soon"), again just before ("save now"). The crash report shows how the
  memory filled up, with a line every 10 minutes.
- **FAQ and Resources tabs.** Questions and answers about FOLM and modding, and links to the community's
  guides for New Vegas and Fallout 3 (Viva New Vegas, The Best of Times, TTW…), the tools mods need
  (xNVSE, FOSE, the 4GB and Anniversary patchers, the BSA decompressors) and modding tools (GECK Extender,
  BSArch, Wrye Flash, NifSkope, Blender's NIF addon, GIMP…), plus the GECK Wiki and xEdit's docs. Click a
  category to open it, then a topic to read it; the search box finds topics by any word.
- **Personalize** (Settings tab → Personalize…): FOLM's colors (text, background, highlight, category
  names, the selected tab) and font, shown live as you change them. Any color can be one of your game's
  own: FOLM reads the Pip-Boy and HUD colors you picked in the game. The **Pip-Boy** look uses your HUD
  color for the mod list's categories and your Pip-Boy color for the selected tab, and follows when you
  change them in the game.
- **Rename and delete profiles in the window** (the new **Profiles** menu, next to the profile list). A
  renamed profile takes its caught files along. Deleting a profile never deletes its
  saves or mods, and files it caught become a staged mod ("Caught files from …") instead of being lost.
  Command line: `folm.py profile rename OLD NEW`.
- **Tool versions** in the Tools tab (like FNVEdit 4.1.5f, xLODGen 4.1.5o), with a link to each tool's
  page to compare with the newest. xLODGen shows its beta number (like beta 132) when the download's name has it.
- **Fix for crackling sound** (Settings tab, on by default). Under Linux the game's sound can crackle when
  the PC is busy, like in a big gunfight. FOLM gives the game a bigger sound buffer
  (`PULSE_LATENCY_MSEC=60` in its Steam launch options), quietly, the next time Steam is closed when you
  press ▶ Play or open FOLM. Launch options you typed yourself are kept; turn the setting off and FOLM
  takes out only what it added.
- **⚡ Optimize** (toolbar): the fixes for problems nearly everyone has playing on Linux, in one window,
  each explained in plain words, with **Turn on all recommended**: crackling sound, borderless window
  (alt-tab under Proton), the 120 FPS cap (physics) and **GameMode** (new: full CPU speed while the game
  runs, when GameMode is installed and allowed to change the CPU speed; added to the game's Steam launch
  options like the sound fix). Left
  out on purpose: what Proton and DXVK already fix by themselves (Proton lets every 32-bit game use 4 GB).
  The FPS cap stays at 120, not your screen's refresh rate: tested on a 60 Hz screen without V-Sync, a
  60 cap made the game stutter. **One copy of each texture** (New Vegas, with NVTF, in a window) turns on NVTF's
  `bUseDefaultPoolForTextures`, which NVTF's own notes say texture mods need: the game stops keeping a
  second copy of every texture inside its 4 GB. FOLM writes its own copy of NVTF.ini on deploy, so the
  mod's file is never changed, and Undeploy puts the mod's back.
- **The game saves itself when its memory runs low** (New Vegas, with JIP LN and xNVSE 6.2.1 or newer).
  At the memory gauge's first warning, FOLM asks the game to save and gives the save its own name, like
  `FOLM_LowMemory_2026-11-21_21-04`. If a crash follows, you lose minutes, not an hour, and a crash in
  the middle of that save can only hit that one file, never your other saves. It never saves in menus
  (dialogue, the Pip-Boy); if it can't save within ten minutes, FOLM tells you to save yourself. It works
  through a small script FOLM adds on deploy and removes on undeploy. On by default; the Settings tab to turn
  it off.
- **Essentials in the 🩺 Health check:** xNVSE, the 4GB Patcher, JIP LN, NVTF and the BSA Decompressor
  (FOSE, the Anniversary Patcher and the FO3 BSA Decompressor for Fallout 3), each shown as installed or
  with a link to get it (double-click). The FAQ's new **Essentials** section says why each matters and
  which FOLM features use them. The low-memory save setting now says when it can't work here and why
  (e.g. "needs JIP LN") instead of being skipped silently.
- **FAQ: why start the game from FOLM.** ▶ Play is what runs the checks, the memory gauge, the
  low-memory save and crash reports; starting from Steam skips them.
- **FOLM's logo** at the left of the toolbar (hover it for the version). The window has always had the
  logo as its icon; on Cinnamon, add "Menu" to the left of the title bar buttons (System Settings →
  Windows → Titlebar) to see it in the title bar too.
- **Check for updates** (Tools tab, or `folm.py updates`): tells you when a newer FOLM is out, and which
  of your Nexus mods have a newer file on their page, with a link to it. FOLM reads which file you
  installed from the download's name, so it compares against that exact file. It only goes online when
  you press the button.

- **Search the mod list** (Ctrl+F): type any words and only mods with all of them in their name, type,
  tags or notes stay, under their category headings. Esc clears it. Dragging waits until the search is
  cleared, so a drop always lands where it looks.
- **Undo (Ctrl+Z) and redo (Ctrl+Y)** for the mod list: turning mods and plugins on or off, moving,
  sorting, removing, categories and notes, up to 50 steps.
- **Saves tab, with the profile as the selector:** every save, checked against the profile you've
  picked: green when all its plugins are on there, red when some are missing, with the profile it does
  fit. It follows along as you switch profiles or turn mods on and off, before you deploy. Double-click a
  save for its own window: every plugin in the order the save was made with, whether it's on now, off
  but installed (and as which mod) or not installed, and a link to get it: the Nexus page of the mod you
  installed it from, LOOT's link for that plugin, or a Nexus search for its name.
- **No more separate save folders per profile.** Every profile saves in the game's one Saves folder (the
  setting never reached the game here anyway, and copies of one playthrough spread over folders only
  take space); the Saves tab does the job instead. A profile's old saves folder is left where it is.
- **New downloads:** when a mod file lands in your Downloads folder (or a library folder), FOLM offers
  to install it at the bottom of the window. It only asks; turn it off in the Settings tab.
- **A newer version of a mod updates it in place** for mods not from Nexus too: installing "My Mod v3"
  over "My Mod v2" offers Update, keeping its place, on/off state, notes and tags. Versions like v3, 1.2
  or 10.05b count; plain numbers don't, so "Part 1 of 2" and "Part 2 of 2" stay two mods.
- **Shortcuts:** F9 ▶ Play, F5 refresh, Ctrl+F search, Ctrl+Z / Ctrl+Y undo and redo, Delete removes the
  selected mod (it asks first, and Ctrl+Z brings it back), Space turns it on or off.
- **Right-click a mod** for its Nexus page and the file you installed it from.
- **Settings is a tab now**, next to Tools, instead of a drop-down on the toolbar: every setting is
  shown at once, with the FPS cap as a list to pick from, and the mod list and Personalize buttons below.

### Fixed
- **Fewer false "needs" notes before Play.** A requirement whose author note says it's "only required for"
  some setups (like "Only required for FNV version" on a TTW install) no longer stops you at ▶ Play.
- **Updating a deployed mod no longer keeps the old version in the game.** The old version's files were
  still linked into the game folder; the next deploy took them for your own edits and kept them in
  Overwrite, where they won over the update. An update now takes the old files out of the game first.
- **FOLM looked for saves in the wrong folder.** With "separate saves per profile" on, it looked in
  `Saves\<profile>`, but the game kept saving in `Saves\`, so the "your saves use this mod" question and
  the save checks before ▶ Play saw no saves. FOLM now reads the saves folder the way the game does.
- **Ticking a mod with the keyboard (Space) could crash the window**: the list was rebuilt while Qt was
  still handling the key. It's rebuilt right after instead.
- **FOLM froze ("Wait or Force Close") when you clicked back into its window.** Every click rescanned all
  your mods' files, which takes seconds on a slow PC and longer while Steam starts. It now only refreshes
  when something really changed.
- An error box ("FOLM hit an error") when the command line changed a setting while the FOLM window was
  open: the window could read the profile file while it was half written. FOLM now writes it in one step.
- **Fewer false "needs" warnings before Play.** Requirements that aren't something the game loads are
  no longer reported: the GECK and xEdit (for making mods), guides (instructions, not downloads), and
  FNVLODGen/xLODGen once you've made a Generated LOD. "Soft requirement" and "recommended" notes count as
  optional. On a full TTW LOD setup this took the list from ten warnings to none.
- **Fallout 3 crash watching.** The crash watcher only ever looked for New Vegas's program, so it never
  saw Fallout 3 start; it now looks for the right game.
- **Crash reports spot out-of-memory crashes.** When the game runs out of its 32-bit memory (4 GB, however
  much RAM the PC has), the report now says so first, with what to cut down. It no longer lists every DLL
  the game had loaded as "files named in the crash log", and the memory log now records the game's own
  memory use too.
- **The crash watcher waits for Steam's game launcher.** It gave up three minutes after ▶ Play, so when
  you took longer in New Vegas's launcher, the session had no memory gauge, warnings or crash report.
  It now waits as long as Steam is still starting the game.
- **The memory gauge works beside the real game.** It took over a setting that only works inside the
  game's own process, and quit at once. Its warnings now go by how much of the 4 GB is really in use:
  the Heap Replacer sets aside nearly all of the 4 GB at the start, so "free" was near zero in a
  perfectly healthy game and would have warned straight away.
- **Deploy notices new settings.** A setting that's new in an update (like the low-memory save) now
  makes Deploy show "Game settings changed", so it's put into the game on the next ▶ Play instead of
  waiting until you change something else.
- **The window is much faster with big mod setups.** The conflict scan rebuilt its list of the game's
  files once for every mod file, so it slowed down as mods grew (17 seconds per refresh with TTW and
  generated LOD). It now scans once per refresh, and the LOOT masterlist is read once instead of every
  time: about 1.3 seconds for the same setup.

### Project
- **A new goal: let New Vegas breathe** instead of crashing when its 4 GB are full. The research report
  and the step-by-step plan are in `docs/memory-project/`. A Windows edition is planned.
- FOLM is actively developed again (the README said it wasn't maintained).
- Credits now include the tools and projects FOLM runs on or builds on.

## 1.1.1

### New
- **AppImage: FOLM is now one file.** Download `FOLM-1.1.1-x86_64.AppImage`, make it runnable and
  double-click it. It brings its own Python, Qt and 7-Zip, so there's no setup script, no Python
  environment and no 7-Zip to install. Only Steam and the game are needed. The command-line tool is
  inside too: `FOLM-1.1.1-x86_64.AppImage --cli doctor`.
- **⚙ Settings → Add FOLM to the app menu.** If you move the AppImage or download a newer one, the
  menu entry follows the one you opened last.
- **7-Zip 26.05 comes with the AppImage** and is used first. It opens RAR files that Ubuntu's older
  p7zip build can't.
- **Release builds on GitHub:** tagging a version builds the AppImage, with a `.sha256` file to check
  the download, from pinned and checksum-checked parts.

### Removed
- **Nexus sign-in and "Mod Manager Download" links.** Nexus only allows apps it has registered to use
  players' personal API keys, and FOLM isn't registered. Download mods with Nexus's normal **Manual
  download** button and drag the file onto FOLM, as before. The requirement check still reads each
  mod's Nexus page (public data, no account needed).
- **Updating from 1.0:** FOLM gives Nexus links back to the app that had them before you set up FOLM,
  removes its link handler, and deletes the API key it had stored. Nothing else changes: your
  profiles, mods and game setup stay exactly as they were.
- The `nexus-login`, `nexus-logout` and `nxm` commands, and `make-shortcut.sh --nexus`.

### Notes
- 1.1.0 was never released. Its AppImage work is part of 1.1.1.

## 1.0.0

First public release: a Linux mod manager for Fallout: New Vegas (with Tale of Two Wastelands) and
Fallout 3, covering installers of every kind, hard-link deployment that undoes exactly, LOOT sorting,
the health check, crash reports and the Tools tab (GECK, xEdit, xLODGen). See the README.
