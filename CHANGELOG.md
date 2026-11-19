# Changelog

What changed in each FOLM release. The newest is on top.

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
