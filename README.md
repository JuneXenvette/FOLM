<p align="center"><img src="assets/folm-logo.png" alt="FOLM logo" width="480"></p>

# FOLM — Fallout Linux Manager

[![Tests](https://github.com/JuneXenvette/FOLM/actions/workflows/tests.yml/badge.svg)](https://github.com/JuneXenvette/FOLM/actions/workflows/tests.yml)

> Unofficial fan-made tool. Not affiliated with or endorsed by Bethesda Softworks, Obsidian Entertainment,
> Nexus Mods, LOOT or the Tale of Two Wastelands team.

**A mod manager for Fallout: New Vegas (with optional Tale of Two Wastelands) and Fallout 3, built for Linux.**
The game runs through Steam and Proton as usual. FOLM installs mods, puts them into the game, sorts the
load order, applies the Proton-specific fixes these games need, and tells you in plain words when something
is wrong. No Wine knowledge needed.

Proven on real setups: TTW 3.4 with about 50 mods (31 plugins, 18 script extender plugins, Vegas Shaders
with its DXVK build, NV SMP, BOG, EVE Lite), and Fallout 3 with FOSE, the Anniversary Patcher, the BSA
Decompressor, the ESM Patcher and the Unofficial Patch, all installed and launched from FOLM on Linux.

## The goal: let New Vegas breathe

New Vegas and Fallout 3 are old 32-bit games. However much memory your PC has, they can only use
4 GB, and a big mod setup fills that up until the game crashes. For years the answer has been "use
fewer mods".

FOLM's new goal is to change that answer. Instead of crashing when the 4 GB get full, the game should
**breathe**: FOLM measures how full the game really is, warns you and saves your game before it's too
late, trims what doesn't need to be there, and, step by step, moves work out of the game's 4 GB
altogether. The aim is bigger mod setups that stay stable, and a reason for modders to come back to
New Vegas. The plan, with what's done and what's next, is in
[docs/memory-project/](docs/memory-project/guide.md).

The memory work will become **Second Wind**: a free, open mod for everyone, on Windows too and with
any mod manager. It saves your game when memory runs low, pulls in far-away clutter during fights, and
lets other mods ask how much room is left. A Windows edition of FOLM comes after that. Most New Vegas
players are on Windows, and Second Wind's parts are Windows programs already, so they get those first.

> I'm a fan of the series, and I hope this helps revive the modding scene for this wonderful game.
> — the FOLM maintainer

## Status

FOLM is actively developed again. It's open source (GPL-3.0): issues and pull requests are welcome;
see [CONTRIBUTING.md](CONTRIBUTING.md).

| | |
|---|---|
| ✅ Tested | Linux Mint 22 (Cinnamon, X11), Steam + Proton 10 / GE-Proton, New Vegas + TTW 3.4, Fallout 3 GOTY + FOSE, AMD GPU (RADV) |
| ❓ Not tested | Wayland, other distros (should work), NVIDIA, Steam Deck, Flatpak Steam |
| ⚠️ Lightly tested | Fallout 3 beyond the start of the game (no long playthrough yet); xEdit and xLODGen from the Tools tab (built and unit-tested, not yet tried on a real game) |
| ❌ Not supported yet | BAIN wizard scripts (`wizard.txt`; plain BAIN packages work), Nexus Collections, the FO3 → NV converter (only its check report works), Windows (planned) |

## What it does

- **Installs mods of every common kind:** plain archives (.7z/.zip/.rar), **FOMOD** wizards (its own
  native installer, with descriptions and images), **old FOMM script installers** (C# installers like BOG
  and Project Nevada, which most Linux setups can't run; FOLM runs them in a sandbox), mods inside archives
  inside archives, **BAIN** packages (numbered option folders, picked with tick boxes), and script extender
  plugins that go next to the game's exe.
- **Windows installers and patchers (.exe) run like on Windows:** Tale of Two Wastelands' installer,
  FNV BSA Decompressor, Ultimate Edition ESM Fixes, the Fallout 3 Anniversary Patcher, the FO3 ESM Patcher
  and the like. FOLM runs them with Proton's Wine in a sandbox, with your game folder protected
  (copy-on-write): whatever the program changes or creates becomes a normal mod you can turn off.
  [How it works](docs/windows-installers.md).
- **Deploys without a virtual file system:** mods are hard-linked into the game folder (no extra disk space,
  instant), case problems (`Textures` vs `textures`) are merged away, and **Undeploy** puts the game folder
  back exactly as it was.
- **Load order:** plugins are always sorted after their masters, with **LOOT's** community rules built in.
  LOOT warnings you've already dealt with can be **marked as handled**; links in LOOT's messages (like a missing
  mod's page) open or copy with a right-click.
- **Profiles:** separate mod setups sharing one library and the game's one Saves folder. The **Saves** tab
  shows which saves fit the profile you picked (green) and which are missing its plugins (red, with the
  profile they fit). The **Profiles** menu makes a new one (empty or a copy), renames one or deletes one
  (its mods, saves and caught files are kept).
- **Already installed?** Installing the same file twice (or another version of an installed mod) asks first:
  skip it, update/replace it keeping its place and notes, or keep both.
- **Checks before ▶ Play:** mods deployed, 4GB patch still applied, xNVSE / FOSE present, missing masters,
  LOOT errors, saves that need mods you turned off.
- **🩺 Health check and requirement scan:** confirms mods actually loaded (from xNVSE's or FOSE's log), and finds
  hidden requirements by reading each plugin's own startup checks plus the mod's Nexus requirement list.
- **Proton fixes, automatic:** Wine DLL overrides for "proxy DLL" mods (NVHR and friends), DXVK builds,
  an FPS cap in `dxvk.conf`, borderless window, read-only INIs kept read-only, archive invalidation.
- **Crash reports:** when the game crashes, FOLM gathers the logs, mod list and system info into one
  report with a plain-language diagnosis. Local only, personal paths removed.
- **Memory gauge:** New Vegas and Fallout 3 are 32-bit, so they can use 4 GB however much RAM the PC has.
  While you play, FOLM watches how full those 4 GB are and warns you on the desktop before they run out
  ("save now"), so a long session doesn't end in a crash and a lost save. On New Vegas (with JIP LN) the
  first warning also **makes the game save by itself**, under its own name (`FOLM_LowMemory_<date>`), so
  your other saves are never at risk. The crash report shows how the memory filled up over the session.
- **TTW support (optional):** download TTW from its official page and install it in FOLM like any mod: FOLM
  runs TTW's own installer (with the Linux speed fix `-NoOggEnc2`), and the result becomes a mod sorted in TTW's
  official order. FOLM can also build a Readius patch for TTW 3 from your own copy of Readius. FOLM never
  bundles or re-hosts TTW.
- **GECK under Proton** for mod makers (Tools tab): opens with your mods loaded and turns what you save into a mod.
- **FAQ and Resources tabs:** questions and answers by topic, and the community's guides, documentation
  and tools, each a click away. Categories open into topics; a search box finds the right one.
- **⚡ Optimize**: one window with the fixes for problems nearly everyone has on Linux (crackling sound,
  alt-tab, physics above 120 FPS, CPU speed with GameMode), explained in plain words.
- **Personalize** (Settings tab): FOLM's colors and font. Colors can follow your game's own: with the
  Pip-Boy look, category names take your HUD color and the selected tab your Pip-Boy color, read from
  the game's settings, so they change when you change them in the game.
- **Check for updates** (Tools tab): a newer FOLM, and every mod sorted into needs an update / up to date /
  can't be checked, each with a link (its Nexus files page, its home page, LOOT's link or a Nexus search).
  Only goes online when you press it.
- **Tools tab:** GECK, FNVEdit/FO3Edit (xEdit) and xLODGen. Installed tools open with your mods loaded; missing
  ones are greyed out with a link to get them. Each shows its version (like xLODGen 4.1.5o) and a link to
  its page, so you can tell when a newer one is out. Drop a tool's download on FOLM to add it. What xEdit saves becomes
  the mod "xEdit output", what xLODGen builds becomes "Generated LOD". LOOT's "needs cleaning" warnings get a
  **Clean it with xEdit** option. xEdit can't change your mods' files or the game's: everything it saves is a
  mod you can turn off ([how](docs/tools.md)).

## Install

You need Steam with the game installed (run it once to the main menu first). What's new: [CHANGELOG.md](CHANGELOG.md).

### The easy way: AppImage (one file, nothing else to install)

1. **Download** `FOLM-<version>-x86_64.AppImage` from the [Releases page](https://github.com/JuneXenvette/FOLM/releases).
   It carries its own Python, Qt and 7-Zip.
2. **Make it runnable** (right-click → Properties → Permissions → "Allow executing", or):
   ```bash
   chmod +x FOLM-*-x86_64.AppImage
   ```
3. **Double-click it.** On first start FOLM finds the game in your Steam libraries (or you pick the folder).
   **Settings tab → Add FOLM to the app menu** puts it in your menu; if you later move the file or download a
   newer one, the menu entry follows the one you last opened.

The command-line tool is inside too: `./FOLM-*-x86_64.AppImage --cli doctor` (any `folm.py` command after `--cli`).
To check a download: `sha256sum -c FOLM-*-x86_64.AppImage.sha256` (the `.sha256` file is on the same release).

Optional extras switch on features the AppImage can't bring along: `unrar` (rare RAR files 7-Zip can't open),
`mono-complete` and `bubblewrap` (old FOMM script installers, sandboxed Windows installers), `xdotool x11-utils wmctrl`
(borderless window). If the AppImage won't start with a "FUSE" message, install `fuse3` (or run it with
`--appimage-extract-and-run`).

### From source (for development)

1. `git clone https://github.com/JuneXenvette/FOLM.git` (or the "Source code (zip)" on a release).
2. **Install the system tools.** On Debian / Ubuntu / Mint:
   ```bash
   sudo apt install p7zip-full unrar mono-complete bubblewrap xdotool x11-utils wmctrl python3-venv
   ```
   Fedora: `sudo dnf install p7zip p7zip-plugins unrar mono-complete bubblewrap xdotool xprop wmctrl` ·
   Arch: `sudo pacman -S 7zip unrar mono bubblewrap xdotool xorg-xprop wmctrl`.
   Only 7-Zip is strictly needed; the rest switch on features (RAR files, old FOMM installers, borderless window).
3. **Run setup** (makes FOLM's own Python environment and checks the tools): `./setup.sh`
4. **Start FOLM:** `./run-folm.sh`. *Optional:* `./make-shortcut.sh` adds it to your app menu.

To build the AppImage yourself: `packaging/build-appimage.sh` (pinned, checksum-checked downloads; output in `dist/`).
Pushing a `v*` tag builds it on GitHub and attaches it to a draft release.

`python3 folm.py doctor` re-checks the system tools at any time. FOLM keeps its data (profiles, staged mods,
backups) in `~/Games/FOLM` (set `FOLM_HOME` to use another folder). It changes nothing else on your PC
except the game folder while mods are deployed, and the game's INI files (backed up, restored on undeploy).

## First steps

1. **Add mods:** drag a downloaded mod file onto the window, use **Install mod…**, or add your mods folder in the
   **Library** tab and double-click.
2. **Tick** the mods you want and press **▶ Play**. FOLM deploys, sorts, checks and starts the game.
   Always start the game from FOLM's ▶ Play, not from Steam or the launcher: the checks, the memory gauge,
   the low-memory save and crash reports only work then.
3. Something wrong? Run **🩺 Health check**. After a crash, FOLM offers a crash report.
4. Modding tools (GECK, xEdit, xLODGen) are in the **Tools** tab.

Start with the essentials in [docs/recommended-mods.md](docs/recommended-mods.md) (xNVSE, 4GB patch,
JIP LN, NVTF and friends). The 🩺 Health check shows which of them you have, with links, and the FAQ tab
explains why each matters.

## How it works

```
mod file → DETECT its type → INSTALL into its own staging folder (case-fixed)
         → DEPLOY (hard links into the game folder, reversible) → LOAD ORDER → LAUNCH through Steam
```

| Mod type | How it's handled |
|---|---|
| Plain Data folder / loose files | Straight install |
| FOMOD with XML installer | FOLM's own native installer (wizard in the app, prompts or `--auto` on the CLI) |
| FOMOD/FOMM with C# script | Compiled with Mono against FOLM's FOMM shim, run sandboxed with bubblewrap; the mod's own window appears ([details](docs/legacy-installers.md)) |
| Root-level files (script extender, DLLs, DXVK builds) | Placed next to the game's exe |
| Archive inside an archive | Unpacked and installed |
| BAIN (numbered option folders) | Packages shown as tick boxes; "00"/core packages ticked by default; later packages win |
| Windows `.exe` installer or patcher | Run with Proton's Wine, sandboxed, game folder copy-on-write; what it changed or saved to drive O: becomes the mod ([details](docs/windows-installers.md)) |
| Anything else | FOLM refuses only files that aren't for this game (e.g. a Starfield mod), and says why |

## Making mods

Mod makers: FOLM opens the GECK (Tools tab) with your mods loaded and turns what you save into a managed mod. See **[Making mods on Linux](MODDING-ON-LINUX.md)**.

## Archive invalidation

On by default (the **Settings** tab in the app). On deploy FOLM redates the game's archives and writes
`bInvalidateOlderFiles=1` and `SInvalidationFile=` under `[Archive]` — into `FalloutCustom.ini` when JIP LN
is installed, otherwise into the game's `Fallout.ini` (backed up first). Undeploy restores the exact previous
values. No dummy archive needed.

## Mods from Nexus

Download the mod with Nexus's normal **Manual download** button, then drag the file onto FOLM's window (or use
**Install mod…**, or add your downloads folder in the **Library** tab). FOLM needs no Nexus account or API key.
Keep Nexus's file name (like `JIP LN NVSE-58277-57-40-1700000000.7z`): the number in it tells FOLM which
Nexus page the mod came from, for the requirement check and the duplicate check.

FOLM 1.0 could also sign in to Nexus and take "Mod Manager Download" links. That was removed in 1.1.1:
Nexus only allows apps it has registered to use players' personal API keys. When you update, FOLM gives
those links back to the app that had them before and deletes the API key it had stored.

## Mod lists

A mod list is a small text file (`.folmlist`) naming mods in order, where to get each one, and what to
do after installing it (remove a file, turn a plugin off, add a note). Download the files yourself with
Nexus's **Manual download** button, then **Settings tab → Install a mod list…**: FOLM looks in your
downloads folder (and its subfolders), shows which files it found and which are missing (double-click a
missing one to open its Nexus page; the list updates as downloads arrive), and installs the ready ones
in the list's order. Mods already installed are skipped, so you can run a list again after getting the
rest.

**Settings tab → Save this profile as a mod list…** writes your own profile as a list to share. Lists that
come with FOLM are in `lists/` (for example `ttw-lod.folmlist`, the Viva New Vegas guide's LOD resources
for TTW). The format:

```yaml
folm_list: 1
name: My list
edition: courier          # courier (New Vegas / TTW) or wanderer (Fallout 3)
mods:
  - file: Much Needed LOD # the download's title, as Nexus names the file
    nexus: 64805          # the Nexus page (optional, but makes matching exact)
    remove: [MuchNeededLOD.esp]   # paths inside the mod to delete after installing
    plugins_off: []       # plugins to turn off; also: name, note, tags, enabled, match
```

## Mod health check

**🩺 Health check** (or `python3 folm.py health`) checks that mods are really working, not just installed:

- every deployed file is still in place and still the mod's (a game update or Steam's "verify files" can
  quietly replace them)
- no damaged plugins, archives or DLLs, and every plugin has its masters
- script extender plugins are in the folder xNVSE/FOSE loads from
- **after you play:** each one actually *loaded correctly*, read from xNVSE's own log (or why it didn't)
- no Windows graphics DLL (ENB/ReShade `d3d9.dll`…) replacing DXVK, Proton's Direct3D layer
- no folders that differ only by letter case

Each problem comes with what to do about it.

## Requirements check ("what does this mod need?")

Mod pages don't always list everything. Vegas Shaders' Nexus page lists xNVSE, JIP and the 4GB patcher, but the
plugin refuses to run without **LOD Flicker Fix** and **Vanilla Plus Terrain**, and you only find out from a box
at game start. FOLM checks three things, after every install, in the 🩺 health check and before Play:

| Source | Shown as | What it means |
|---|---|---|
| The plugin's own startup check | ✖ error | FOLM reads the script extender plugin (.dll) for messages like "LOD Flicker Fix not found … cannot be used without it" next to `LODFlickerFix.dll`. It also catches "not compatible with X.dll" clashes. Only messages that say the plugin won't run count; optional extras it just logs don't. |
| FOLM's own list | ✖ error | Requirements found by testing, with download links. |
| The mod's Nexus "Requirements" list | ⚠ warning | For mods downloaded from Nexus (the mod id is in the file name). Fetched from Nexus's public API (only mod ids are sent, no account needed), saved for a week, used offline. |

Linux-aware: Windows runtimes that Nexus pages list (Visual C++, DirectX) are skipped, because Proton provides them.
xNVSE and the 4GB patch are recognised however you installed them. Entries the author marks "only for …" or "optional"
show as ℹ notes, not warnings. CLI: `folm.py requires [MOD] [--offline]`.

## Recommended mods

For a smooth game on Linux, start with the engine and stability mods in
**[docs/recommended-mods.md](docs/recommended-mods.md)**: xNVSE, the 4GB Patcher, JIP LN, JohnnyGuitar,
ShowOff, NVTF, lStewieAl's Tweaks and Engine Optimizations, the lag and save-bloat fixes, Mod Limit Fix,
kNVSE, UIO, a crash logger and YUP (YUPTTW for TTW). Fallout 3 has its own list (FOSE, Anniversary
Patcher, Command Extender, High FPS Physics Fix…). The page also covers the Linux-only part (FPS cap,
windowed mode, low RAM) and what to avoid. Lists follow ModdingLinked's community guides.

## Deploy, explained (and why Play handles it for you)

Ticking a mod in FOLM doesn't change the game yet. **Deploy** is the step that puts your ticked mods into
the game folder and sets the load order. It takes a moment, and **Undeploy** takes it all back out exactly.

You don't have to remember it: when something isn't in the game yet, the **Deploy** button turns gold and
says how many changes are waiting (hover it for the list: new mods, mods turned off, updated mods, order or
settings changes). **▶ Play** checks too and offers **Deploy and Play**, so new mods are always in the game
before it starts. On the command line, `folm.py play` deploys first (`--no-deploy` skips that) and
`folm.py list` shows what's waiting.

## Saves, FPS cap and pre-Play checks

- **Save safety:** FOLM reads the plugin list stored in each save. Untick a mod your recent saves use and it
  warns you first (removing mods mid-playthrough breaks quests and scripts). Deploy and Play warn too.
- **One Saves folder, checked per profile:** every profile saves in the game's normal `Saves` folder (no
  copies of a playthrough spread over folders). The **Saves** tab checks each save against the profile
  you've picked, and updates as you switch profiles or turn mods on and off.
- **FPS cap** (default 120): above ~120 FPS these engines' physics break (bouncing NPCs, sped-up game).
  NVTF and Stewie's Tweaks don't include a limiter, so FOLM sets one in DXVK, the Direct3D layer Proton uses:
  `d3d9.maxFrameRate` in the game folder's `dxvk.conf`. Any existing `dxvk.conf` is backed up and restored on undeploy.
- **Borderless window** (on by default): windowed mode is safest under Proton, but the desktop's title bar
  pushes the bottom of the picture off screen. After ▶ Play starts the game, FOLM removes the title bar and
  has the desktop show the window fullscreen. The game stays in windowed mode, so alt-tab is safe. Needs
  `xdotool`, `xprop` and `wmctrl`.
- **Before ▶ Play** FOLM checks: mods deployed, Steam running, the exe still 4GB-patched (verifying files in
  Steam undoes it), xNVSE present when NVSE plugins are, missing masters, LOOT errors, saves that need
  plugins that are now off, and V-Sync off with no FPS cap. Problems show in one box: Play anyway or Cancel.

- **Mods with "proxy" DLLs** (e.g. NVHR's `d3dx9_38.dll`, or hooks shipped as `dinput8.dll`/`dsound.dll`):
  Windows loads the copy in the game folder, but Wine uses its own built-in copy, so under Proton such mods
  silently do nothing. FOLM sets a per-game Wine override for exactly those DLLs while they're deployed
  (no Steam launch options needed). The health check flags any that Wine is still ignoring.
- **Read-only INIs** (a common way to stop the launcher rewriting `Fallout.ini`) stay read-only: FOLM
  unlocks the file for its one edit and locks it again.

All of these are in the app's **Settings** tab; every change is undone exactly on undeploy.

## Load order & LOOT

FOLM keeps two separate orders:

- **Mod order** (the left-hand list): decides which mod wins when two mods ship the same file.
  Lower in the list wins. **Sort mods** arranges it into sections without changing any winner.
- **Plugin load order** (the Plugins tab): the order the game loads `.esm`/`.esp` files.
  FOLM sorts it automatically every time you deploy, using:
  1. **Hard rules:** a plugin always loads after its masters, ESMs before ESPs, vanilla files first.
  2. **LOOT's rules:** LOOT's community masterlist (groups, "load after" rules), downloaded from
     LOOT's official GitHub and refreshed weekly. With TTW, for example, LOOT places the courier
     packs (Caravan, Classic, Mercenary, Tribal) after the Fallout 3 DLC and before
     `TaleOfTwoWastelands.esm`, which is TTW's official order.
  3. **Your own order** only breaks ties.

  Offline? FOLM sorts with the hard rules and its built-in vanilla/TTW order instead.

**LOOT messages** appear at the bottom of the Plugins tab, in the status bar, and in `folm.py loot`:

| Mark | Meaning |
|---|---|
| ℹ (blue) | A note: version checks ("Your New Vegas Script Extender is up-to-date"), links to a mod's docs. Nothing to fix |
| ⚠ (orange) | A warning: e.g. a plugin needs cleaning, or an outdated file |
| ✖ (red) | An error: e.g. a required mod is missing or two mods are incompatible. Fix before playing |
| ✔ (grey) | **Marked as handled**: you told FOLM a patch fixes it, or you checked it yourself |

**Mark as handled.** LOOT doesn't know every community patch. EVE 1.19, for example, is flagged as
incompatible with TTW 3.2+, but *EVE Lite TTW* fixes it. Right-click the message in the Plugins tab and pick
**Mark as handled…**, then choose the patch (FOLM guesses it) or "I checked it myself", and add a note if you like.
It stops counting as an error before Play. If you named a patch and later turn it off or remove it,
the error comes back with a note saying so. Right-click again and pick **Show as a problem again** to undo.
Each profile keeps its own list. CLI: `folm.py handled list|add|remove`.

Before marking, make sure the patch fits the TTW version you're using. For example, *Readius TTW Fix* (2015, for TTW 2.x)
rewrites TTW's Vault 101 quests and scripts (MQ04, CG02–CG04) with their old versions, and TTW 3.4 has since changed
all four. It would roll back TTW's fixes, so leave it off.
FOLM can build a proper one instead, from your own copy of Readius (see `tools/make_readius_ttw_patch.py` and
[compatibility notes](docs/compatibility.md)).

## Compatibility

Problems other mod managers have, and how FOLM handles each: [docs/known-issues.md](docs/known-issues.md).

Every mod tested with FOLM, and what happened: [docs/compatibility.md](docs/compatibility.md).

## Project layout

```
folm.py             command line
folm_gui.py         the app (Qt 6)
folm_core/          shared engine: detect, install, FOMOD, legacy installers, deploy, load order, LOOT,
                    health, requirements, Nexus, crash reports, plugin + compiled-script reader/writer
games/courier/      New Vegas / TTW edition settings
games/wanderer/     Fallout 3 edition settings
tools/              one-off builders (Readius TTW patch)
lists/              mod lists that come with FOLM (.folmlist)
tests/              core tests: .venv/bin/python -m unittest discover tests
docs/               compatibility notes, known issues, recommended mods, development log
mods/               a home for original mods made for FOLM (none released)
```

Both editions share one engine; each edition is a thin game layer, so a fix in the core helps both.
How FOLM came together, and everything learned about modding these games on Linux:
[docs/development-log.md](docs/development-log.md).

## License

FOLM's code is licensed under the **GNU General Public License v3.0** ([LICENSE](LICENSE)): use it, change it,
share it; shared changes stay open source under the same license.

The FOLM logo and icons in `assets/` are the original author's own artwork and are **not** under the GPL; see
[assets/README.md](assets/README.md). Forks may keep them to refer to FOLM, but please use your own artwork if
you release under a different name.

## folm.py (command line)

```bash
python3 folm.py doctor                        # which system tools are missing, and how to install them
python3 folm.py init                          # finds New Vegas and its Proton prefix
python3 folm.py add "Tale of Two Wastelands"  # register a mod already in the mods folder
python3 folm.py install SomeMod.7z            # install a mod from an archive (FOMOD: add --auto for defaults)
python3 folm.py list                          # mods in order; later mods win file conflicts
python3 folm.py move "Some Mod" --after "Other Mod"
python3 folm.py disable "Some Mod"
python3 folm.py deploy                        # hard-link mods into the game + set the load order
python3 folm.py order                         # show the plugin load order and any missing masters
python3 folm.py undeploy                      # put the game folder back exactly as it was
python3 folm.py conflicts                     # which mods overwrite which files, and who wins
python3 folm.py catch                         # move files the game/tools created into this profile's Overwrite
python3 folm.py profile create "Vanilla"      # profiles: create / switch / list / rename OLD NEW / delete (--copy-from P)
python3 folm.py note NAME "text"; python3 folm.py tag NAME fixes ttw
python3 folm.py sort --preview              # arrange mods into sections (then 'sort' to apply)
python3 folm.py category NAME "Visuals"      # override a mod's section ('auto' to reset)
python3 folm.py convert-check SomeFO3Mod.esp  # what converting a Fallout 3 plugin to TTW needs
python3 folm.py settings                      # e.g. archive invalidation (app: Settings tab)
python3 folm.py set archive-invalidation on   # loose mod files override the game's archives (default on)
python3 folm.py set fps-cap 120                # or off; written to dxvk.conf on deploy
python3 folm.py preflight                     # the pre-Play checks (play runs them too; --force to skip)
python3 folm.py health                        # are mods really working? (files, plugins, what loaded)
python3 folm.py requires                      # what mods need that isn't installed (plugin checks + Nexus lists)
python3 folm.py updates                       # a newer FOLM, or newer files for your Nexus mods?
python3 folm.py modlist check lists/ttw-lod.folmlist   # which downloads are found (--from DIR)
python3 folm.py modlist install LIST.folmlist  # install the found ones in order (--auto for FOMOD defaults)
python3 folm.py modlist save my.folmlist       # write this profile as a mod list
python3 folm.py handled add PLUGIN TEXT --by MOD --note ...   # mark a LOOT message as handled (list / remove)
./backup.sh                                   # back up the project, FOLM data, saves and INIs
```

Add `--edition wanderer` for Fallout 3. Profiles, staged mods and backups live in `~/Games/FOLM` (override with `FOLM_HOME`).

- **Hard links:** mods appear in the game folder without using extra disk space; deploy/undeploy is near-instant.
- **Case fixing:** a mod's `textures/` merges into the game's existing `Textures/` instead of creating a twin.
- **Load order:** plugins are sorted so masters always load first (read from each plugin's header), then the
  file timestamps are set (that's how these engines order plugins) and `plugins.txt` is written.
- **Safe:** game files a mod overrides are backed up; undeploy restores files, sizes, contents and timestamps exactly.

## detect

```bash
python3 folm_core/detect.py SomeMod.7z AnotherMod.zip   # files anywhere on disk; add --json for machine-readable output
python3 folm_core/detect.py --scan ~/Mods --scan /media/usb/Fallout   # search folders + all subfolders
```

Reads the archive's file list only (via `7z`; zip, 7z and rar supported), never extracts.

## nvcase

Requires Python 3.8+. No other dependencies.

```bash
# Report problems (changes nothing)
python3 folm_core/nvcase.py "/path/to/Fallout New Vegas/Data"

# Merge case-duplicate folders and write an undo log
python3 folm_core/nvcase.py "/path/to/Data" --fix

# Also rename everything to lowercase, so future mods can't collide
python3 folm_core/nvcase.py "/path/to/Data" --fix --lowercase

# Undo a previous --fix run
python3 folm_core/nvcase.py --undo nvcase-undo-YYYYmmdd-HHMMSS.json
```

Safety: report-only by default, never overwrites (collisions are reported for
you to decide), and every move is recorded so `--undo` reverses it.

## Credits

FOLM stands on the shoulders of a community that has kept these games alive for over fifteen years.

- **The Tale of Two Wastelands team** — the project that inspired FOLM. TTW showed what a
  dedicated community can build: two games joined into one. FOLM is our attempt to carry that
  spirit to another operating system, so more people can experience what the modding community
  has created. FOLM supports TTW, but TTW is entirely their work: players download it from
  TTW's official page, and FOLM never bundles or re-hosts it.
- **LOOT** ([loot.github.io](https://loot.github.io)) — the load-order standard for years. FOLM reads
  LOOT's public-domain masterlists, maintained by the LOOT team and community, from LOOT's
  official GitHub, to sort plugins and warn about missing requirements, incompatibilities and
  dirty plugins.
- **ModdingLinked** — authors of *The Best of Times* (TTW) and *Viva New Vegas* guides. FOLM's
  section order and the TTW settings it writes follow their guides.
- **xNVSE team** and the authors of **JIP LN, JohnnyGuitar, ShowOff, lStewieAl's Tweaks, UIO,
  MCM, YUP/YUPTTW**, the **4GB patchers**, and every mod author whose work FOLM installs. FOLM's
  low-memory save runs on JIP LN's script runner and xNVSE's commands.
- **xEdit** (ElminsterAU and the xEdit team) and **xLODGen** (Sheson), which the Tools tab runs.
- **New Vegas Tick Fix (NVTF)**, **New Vegas Heap Replacer** and the **FNV Performance Guide**, whose
  work on the game's memory and speed the memory project builds on.
- **DXVK** (Philip Rebohle and contributors), **Wine** and Valve's **Proton**, which make these games run
  on Linux at all; DXVK's work on keeping textures out of 32-bit games' memory is part of why the 4 GB
  goal is within reach.
- **NV SMP Physics** (GPL-3.0), studied for the plan to move physics out of the game's memory.
- **7-Zip** (Igor Pavlov), which the AppImage includes.
- The **GECK Wiki** editors and every guide and tool author linked in the Resources tab.
- **Bethesda Softworks and Obsidian Entertainment** for the games themselves.

FOLM is an unofficial fan project. Each mod belongs to its authors and keeps its own license;
FOLM installs mods the player downloaded and doesn't redistribute anyone's work.

**How it's made:** FOLM is written with an AI coding assistant (Claude, by Anthropic). The maintainer
decides what it should do, tests it on a real game, and decides what goes in.
