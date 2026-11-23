# Tech debt

Known weak spots in FOLM's own code: things that work today but will bite later. Fix one, then move it
to "Paid off" with a line on what changed. (Problems *other* managers have are in
[known-issues.md](known-issues.md).)

## Open

### Speed with big mod setups
Found November 2026: with TTW plus a full generated LOD (about 120,000 mod files), every refresh of the
window took about 17 seconds. The worst part is fixed (see "Paid off"), but the design that caused it is still there:

- **Every refresh re-reads every mod's files.** The conflict scan, `pending_changes` (`_mod_signature`
  walks each mod) and `game_view` all walk the disk from scratch. Together about 1.3 s on that setup, and
  it grows with every mod. Better: remember each mod's file list (mods only change through FOLM, or
  through Catch new files) and rescan only a mod whose folder changed.
- **The refresh runs on the window's own thread**, so the window freezes while it works. Move the scans
  to a background job (like Deploy already is) and fill the lists in when they're done.
- **No speed test.** The tests use tiny fake mods, so a slow-down like the one above can't show up in
  them. Add a test that builds a few thousand dummy files and fails if a conflict scan takes too long.
- **`Manager.reusing_conflicts()` is only used by the window's refresh.** The health check, pre-Play
  checks and the CLI each still scan on their own; anything that calls `conflicts()` more than once
  should use it.

### Requirement checks are guesses from names
`folm_core/requires.py` decides what to ignore on a mod's Nexus "Requirements" list by matching words:
GECK/xEdit (modding tools), "lodgen" (LOD generators), "guide", "soft requirement", "recommended". A
requirement with an unusual name slips through as a false warning, or a real one could be skipped.
`NOT_NEEDED` is a hand-kept list of tested exceptions (one entry so far). Better: let the player mark
a requirement "not needed" in the app, saved per mod, like "handled" messages already are.

### Smaller items
- **Second Wind's "game exited" line never appears with NVTF's fast exit.** NVTF's `bFastExit = 1`
  ends the game with TerminateProcess, which skips DllMain, so v4's clean-quit line isn't written and
  FOLM falls back to guessing (crash logger, memory log). Fix: hook the game's exit (its call to
  TerminateProcess / ExitProcess, or NVTF's) in v5, or have FOLM count "crash logger empty and the game
  closed" as a clean quit.
- **The memory gauge's warning levels are first guesses.** It now runs beside the real game (first
  reading: 1247 MB in use, with the Heap Replacer holding nearly all of the 4 GB in reserve). Warnings go
  by room left (4096 − in use): 600 MB "save soon", 300 MB "save now". Tune them on a session that gets
  close to a crash.
- **Update check needs the download's original name.** It finds which file you installed from the upload
  time in the name; renamed or hand-made archives (20 of 97 mods on the test setup) can't be checked.
- **Mod list installs print every Nexus requirement note**, many of them noise (e.g. "needs FNVLODGen"
  for every LOD resource). Hide requirement notes during a list install, or show them once at the end.
- **Which game color is "the" HUD color isn't confirmed.** New Vegas keeps the Pip-Boy and HUD colors
  twice in `FalloutPrefs.ini` (three numbers, and one packed number); on the test setup they differ for
  the HUD (green and blue). `look.game_colors` offers both, the packed one under the plain name. Check
  in game which one the HUD really shows, and name them after that.
- **The low-memory save hasn't run in the real game yet.** Tested with a fake game; the script uses
  JIP LN's `SetGameMainLoopCallback` and `FileExists`, and xNVSE's `con_Save`, in a `gr_` text script
  with a lambda. Confirm in game that it saves (and only once), and that the renamed save loads. Also find out which folder JIP's `FileExists` starts from (the script asks for both `Data\FOLM\…` and `FOLM\…` until then), and whether the memory warning can fire at all with NVHR (see the gauge item below).
- **The help text is written by hand.** The FAQ describes buttons and menus by name; when one is
  renamed, `folm_core/help/faq.md` must change too. No test catches a stale answer.
- **Mod lists can pick a browser's duplicate download** ("file (1).7z") when the original is also there.
  Prefer the name without the "(1)".
- **The sound fix's value (60 ms) is a first guess, and only helps the PulseAudio path.** One player's
  crackle on a 2-core PC; not yet confirmed it's gone. It only reaches the game through Steam's launch
  options, which FOLM can only edit while Steam is closed, so with Steam always open it waits. The
  Windows edition won't need it.
- **A deployed file whose mod copy disappears is taken for a game file.** If a mod's file is removed or
  replaced (an editor that saves to a new file, `sed -i`) while deployed, the next deploy catches the game's
  copy into Overwrite (which then wins), or backs it up as an original game file that Undeploy puts back.
  Fix: remember each link's inode on deploy and treat a link FOLM made as FOLM's even when its source is
  gone. Found 2026-11-21 editing NVTF.ini by hand.
- **Archives with "Optional …" folders next to the real files get them installed into Data.** Vegas
  Shaders ships `Optional - Author's settings/` and `Optional - macintroll's settings (D3D9)/`; they're
  harmless there (the game never reads them) but shouldn't be deployed. Fix: ask, or skip folders whose
  name starts with "Optional" when the archive also has real game folders.
- **The memory gauge is blind with NVHR.** It warns by committed memory (4096 − commit), but with NVHR the
  game crashes when NVHR's dheap can't get another 16 MB block, at ~1.4 GB committed. Fix: read the dheap
  block addresses from `hr.log`, measure how full those blocks are (committed pages, via the helper), and
  warn by that; or warn when the largest free block stays under 16 MB and the dheap is nearly full.
- **`secondwind/nvhr-src` is a git clone inside FOLM's repo.** Before committing, turn it into plain files
  (upstream commit 4e1ec8b noted, our changes kept as `second-wind-changes.diff`) or a submodule, so git
  doesn't record it as an empty link.
- **Updating a mod to a new version keeps its old name** ("My Mod v2" holding v3's files). Renaming the
  mod's folder would leave the deploy record pointing at files that are gone, and undeploy then keeps
  them in the game as the user's own. Fix: rename and rewrite `deployed.json`'s sources in one step (also
  check `_replace` while deployed: the old files it removes are the deployed sources). Found 2026-11-22.

## Paid off

- **Per-profile saves didn't reach the game** (`SLocalSavePath` in Fallout.ini, overridden by
  FalloutPrefs.ini). Dropped in 1.2.0: all profiles share the game's Saves folder, and the Saves tab checks
  each save against the selected profile. `save_dir` reads the folder the way the game does. (1.2.0)
- **Conflict scan rebuilt the game-file list once per mod file** (`deploy.conflicts`), so its time grew
  with mod files × game files. Now built once per scan; one refresh shares one scan
  (`Manager.reusing_conflicts`); the LOOT masterlist is parsed with libyaml and kept in memory until the
  file changes. 17 s → 1.3 s per refresh on TTW + generated LOD, same results. (1.2.0)
