# Legacy FOMM script installers (C# `fomod/script.cs`)

Roadmap item 6, and FOLM's headline promise: run the old FOMM-era installers that
other Linux tools skip. First test case: **Project Nevada 2.5** (Nexus 40040).

## How old FOMM installers work

The archive ships `fomod/script.cs`: a C# class `Script : FalloutNewVegasBaseScript`
(or `FalloutBaseScript` for Fallout 3) with `public static bool OnActivate()`.
FOMM compiled it at install time and called `OnActivate()`. The script calls FOMM's
static helper functions to install files, and often builds its own Windows Forms UI.

Project Nevada uses: `InstallFileFromFomod`, `GetFileFromFomod`, `GetExistingDataFile`,
`GenerateDataFile`, `DataFileExists`, `MessageBox`, and a custom `Form` with 22
`PictureBox` buttons. It reads the player's existing menu XML files, patches them, and
writes patched copies.

## FOLM's design

1. **Native C#, not an imitation.** FOLM compiles the script with Mono's `mcs` together
   with FOLM's own **FOMM-compatible shim** (`folm_core/fomm_shim/`): a
   `fomm.Scripting` namespace providing the base classes and helper functions.
2. **Nothing touches the game directly.** The shim writes every installed or generated
   file into the mod's **FOLM staging folder**. `GetExistingDataFile` reads from a
   read-only snapshot of the files the game currently sees. Plugin activation and INI
   edits are recorded in a plan file, which FOLM applies itself (and can undo).
3. **Sandboxed.** The compiled script runs under **bubblewrap**: no network, a
   read-only view of the extracted archive and the game snapshot, one writable staging
   folder, and no access to the player's home folder. Old scripts are real programs,
   so this matters.
4. **Windows Forms works.** Mono's WinForms draws the script's own installer window on
   X11, so players see the mod's original installer.
5. **Choices are replayable** where possible (recorded in the plan), like XML FOMODs.

## Shim API (first pass, grows with the compatibility list)

| Function | Behaviour in FOLM |
|---|---|
| `PerformBasicInstall()` | copy every archive file except `fomod/` to staging |
| `InstallFileFromFomod(path)` / `InstallFolderFromFomod(path[, recurse])` | copy into staging |
| `CopyDataFile(from, to)` | copy within staging |
| `GetFileFromFomod(path)` → `byte[]` | read from the extracted archive |
| `GetFomodFileList()` → `string[]` | archive file list |
| `GenerateDataFile(path, bytes)` | write into staging |
| `GetExistingDataFile(path)` / `DataFileExists(path)` / `GetExistingDataFileList(...)` | read the game snapshot |
| `GetActivePlugins()` / `GetAllPlugins()` / `IsPluginActive` | from FOLM's load order |
| `SetPluginActivation(name, on)` | recorded in the plan |
| `EditINI` / `EditFalloutINI` / `EditPrefsINI` | recorded in the plan (not applied silently) |
| `GetFalloutIniString/Int`, `GetPrefsIniString/Int` | read the player's INIs |
| `ScriptExtenderPresent`, `GetNvseVersion`, `GetFalloutVersion`, `GetFommVersion` | real values / a FOMM 0.14-compatible version |
| `MessageBox(...)`, `Select(...)` | real dialogs (WinForms) |

Unknown functions fail to compile: FOLM reports which one so it can be added, and
logs the mod on the compatibility list.
