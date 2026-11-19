# Contributing to FOLM

FOLM was finished and handed to the community. The original author doesn't maintain it, so whoever wants
to carry it on is welcome to: fork it, open pull requests, or become the new maintainer. These notes are
what a newcomer needs to find their way around.

## Getting set up

```bash
./setup.sh                                    # Python environment in .venv + system tool check
.venv/bin/python -m unittest discover tests   # core tests: no game, Steam or network needed
                                              # (GitHub runs these on every push and pull request)
./run-folm.sh                                 # the app
.venv/bin/python folm.py --help               # the command line (same engine)
```

Point FOLM at a throwaway data folder while developing, so your real setup stays untouched:
`FOLM_HOME=/tmp/folm-dev ./run-folm.sh`.

## Where things are

| File | What it does |
|---|---|
| `folm_core/manager.py` | The engine: profiles, install, deploy, Play, pre-Play checks. The app and the CLI both call it |
| `folm_gui.py` / `folm.py` | The Qt app / the command line. Keep logic out of these; put it in `folm_core` |
| `folm_core/detect.py` | What kind of mod an archive is (from its file list only) |
| `folm_core/fomod.py` | Native XML FOMOD installer |
| `folm_core/legacy.py`, `fomm_shim/FommShim.cs` | Old FOMM C# installers: Mono + FOLM's FOMM API shim, sandboxed with bubblewrap |
| `folm_core/wintool.py` | Windows `.exe` installers/patchers: Proton's Wine + bubblewrap, game folder mounted copy-on-write (overlayfs in a user namespace); writes become the mod |
| `folm_core/tools.py` | Tools tab catalog (GECK, xEdit, xLODGen); running them safely is `Manager.run_tool` / `_begin_tool_session` in manager.py |
| `folm_core/desktop.py` | App-menu entry and the Nexus link handler, written from the app (needed for the AppImage); entries follow a moved or newer AppImage |
| `packaging/` | AppImage build: `build-appimage.sh` (pinned, checksum-checked Python, PySide6 and 7-Zip), `AppRun`, licences. `.github/workflows/release.yml` runs it for `v*` tags and makes a draft release |
| `folm_core/deploy.py` | Hard-link deployment, case merging, game-file backups, exact undeploy |
| `folm_core/loadorder.py`, `plugins.py`, `loot.py` | Plugin order: masters, LOOT masterlist rules, plugins.txt + timestamps |
| `folm_core/health.py`, `requires.py` | Health check; requirement scan (DLL startup checks, known list, Nexus requirements) |
| `folm_core/wineprefix.py`, `ini.py`, `window.py` | Proton/Wine: DLL overrides, INI edits that undo cleanly, borderless window |
| `folm_core/crash.py`, `saves.py` | Crash reports; reading plugin lists from save files |
| `folm_core/esp.py`, `scriptcode.py`, `bsa.py` | Readers/writers for plugins, compiled scripts and BSA archives |
| `folm_core/version.py` | FOLM's version number; release tags must match it |
| `games/<edition>/game.json` | Per-game facts (exe names, Steam app ids, vanilla plugins) |

[docs/development-log.md](docs/development-log.md) is the diary of how all this was built and tested,
including many Proton and mod quirks. Search it before re-investigating something.

## House rules

These kept FOLM safe and pleasant to use; please keep them.

- **Everything is reversible.** Anything FOLM changes in the game folder, prefix or INIs is recorded and
  undone exactly by Undeploy. Back up before overwriting; never delete a player's files.
- **No noisy warnings.** A check only warns about clear problems the player can act on, and says what to do.
- **Plain language** in every message: say what happened and what to do, no jargon.
- **Never redistribute anyone's work.** FOLM installs what the player downloaded. Patches FOLM makes (like
  the Readius TTW patch) are built on the player's PC from their own copy of the mod. TTW's own installer
  (downloaded by the player) builds TTW; never ship or re-host TTW or its installer.
- **Only refuse what isn't for the game.** Every New Vegas / Fallout 3 mod format should install; a file
  is turned away only if it's for another game, with a plain reason.
- **Privacy.** Nothing leaves the PC except the LOOT masterlist download and Nexus requirement lookups
  (public data, mod ids only, no account). Crash reports stay local and redact home paths and usernames.
- **No Nexus API keys.** Nexus only lets apps it has registered use players' personal API keys, so FOLM
  doesn't ask for one (the 1.0 sign-in was removed in 1.1.1). Don't add it back without registering FOLM.
- **Sandbox untrusted installers.** Old installer scripts and Windows installers run under bubblewrap with
  no network and only the folders they need; Windows installers never write to the real game folder.
- **Original artwork only.** No Bethesda or other third-party logos or art.
- **Test before you claim it works.** Add a test in `tests/` for engine changes; note real-game results in
  `docs/compatibility.md`.

## Good first projects

- **BAIN wizard scripts** (`wizard.txt`): plain BAIN packages install; scripted wizards aren't read yet.
- **More Windows installers tested:** `folm_core/wintool.py` runs them; each new one tried and noted in
  `docs/compatibility.md` helps the next player.
- **Fallout 3 (Wanderer edition):** FOSE, the Windows patchers and UF3P are tested (docs/compatibility.md); more FO3 mods and a long play session would help.
- **Wayland:** the borderless-window fix uses X11 tools; under Wayland the game runs but that fix doesn't.
- **Update checks** for Nexus mods (installing a newer file already offers "Update").
- **xEdit and xLODGen on a real game:** the Tools tab and "Clean it with xEdit" are built and tested with
  stand-in tools only ([docs/tools.md](docs/tools.md)). Try them and note results in `docs/compatibility.md`.
- **Packaging:** AppImage or Flatpak so players don't need the Python setup.
- **The FO3 → New Vegas converter** ([docs/fo3-converter.md](docs/fo3-converter.md)): only the check report works.

## Reporting a problem

Include FOLM's crash report (the app offers one after a crash, or `folm.py crash-report`) or the output of
`folm.py health`, plus your distro, desktop (X11/Wayland), GPU and Proton version.
