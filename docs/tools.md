# Modding tools (Tools tab)

The **Tools** tab lists GECK, FNVEdit / FO3Edit (xEdit) and xLODGen for the game you're on. Installed tools
have an **Open** button; missing ones are greyed out with a **Get it…** link to their official page.

- **GECK** installs from Steam (Library > Tools) into the game folder. FOLM starts it through xNVSE or FOSE
  (`-editor`), so scripts using their functions compile. What you save becomes a mod (see
  [Making mods on Linux](../MODDING-ON-LINUX.md)).
- **xEdit and xLODGen**: download them, then drop the file on FOLM. They're kept in FOLM's own `tools`
  folder (not the game folder) and run with Proton's Wine in the game's prefix, with your mods deployed.
  What xEdit saves becomes the mod **"xEdit output"**; what xLODGen builds becomes **"Generated LOD"**.

## Cleaning dirty plugins

When LOOT says a plugin "needs cleaning", right-click the message in the Plugins tab → **Clean it with
xEdit**. FOLM runs xEdit's Quick Auto Clean on that plugin (`-QAC -autoexit -autoload`); the window closes
by itself. The cleaned copy goes into "xEdit output". The main game file (FalloutNV.esm / Fallout3.esm) is
never cleaned.

## Why xEdit can't break your game or your mods

xEdit can save over any plugin it loads. FOLM makes sure that can never damage anything:

| Risk | What FOLM does |
|---|---|
| Saving over a **mod's** plugin | Deployed plugins are normally hard links to the mod's own file. Before xEdit starts, each one is swapped for a separate copy (same date, so Fallout 3's load order is unchanged). Whatever xEdit writes only reaches the copy; the mod's own file can't change. |
| Saving over a **game** file (cleaning a DLC ESM) | The game's own plugins are copied aside first. A changed one moves into "xEdit output"; the original goes back into the game folder. |
| Undoing it | Every change lives in "xEdit output". Turn that mod off (or remove it) and everything is as before. |
| **Earlier xEdit work** | Before each run, the current "xEdit output" is saved to `~/Games/FOLM/tools/earlier output/` (the last 10 runs; hard links, no extra space). |
| FOLM **closes or crashes** while xEdit is open | A journal on disk lists every protected file. The next Deploy, Undeploy or ▶ Play finishes the job, the same way as if the run had ended normally. |
| xEdit stops **in the middle of saving** | Half-written `*.esp.save.*` files are kept aside, never made part of a mod. |
| A mod is **updated later** | FOLM remembers which version each xEdit-made plugin was built from. If the original mod changes, the check before ▶ Play says so: redo the change in xEdit, or turn "xEdit output" off. |
| xEdit's own **backups and cache** | Moved to `~/Games/FOLM/tools/xedit/FOLM backups/`, not into a mod. |
| The **game is running** | FOLM won't start xEdit until it's closed. |
| Not enough **disk space** for the copies | FOLM says how much it needs and doesn't start. |

"xEdit output" is placed last in the mod list, so its plugins win over the ones they were made from. If you
move it higher, your xEdit changes lose to the originals.

Status: all of the above is covered by FOLM's tests with stand-in tools. xEdit and xLODGen themselves haven't
been run through FOLM on a real game yet; please note results in [compatibility.md](compatibility.md).
