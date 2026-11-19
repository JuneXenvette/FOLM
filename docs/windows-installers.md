# Windows installers and patchers

Some New Vegas and Fallout 3 mods are Windows programs rather than plain files: you download an `.exe`
(or an archive with one inside) and run it. On Windows that just works. FOLM makes it work the same way on
Linux, and keeps the result reversible.

Examples that the community guides tell everyone to run:

| Program | Game | What it does |
|---|---|---|
| Tale of Two Wastelands installer | New Vegas + Fallout 3 | Builds TTW from your two games |
| FNV BSA Decompressor | New Vegas | Rewrites the game's archives uncompressed (performance, some sound fixes) |
| Ultimate Edition ESM Fixes Remastered | New Vegas | Builds fixed copies of the game's ESM files |
| Fallout 3 Anniversary Patcher | Fallout 3 | Patches Fallout3.exe so FOSE works (removes Games for Windows Live) |
| Unofficial Fallout 3 ESM Patcher | Fallout 3 | Patches the game's ESM files with fixes |
| FNV 4GB Patcher (Windows version) | New Vegas | Lets the game use 4 GB of memory (FOLM also handles the Linux version) |

## What happens when you install one

1. FOLM unpacks the download and finds the program to run (if there are several, it asks).
2. A screen explains what will happen; choose **Run it**.
3. FOLM takes your mods out of the game, so the program sees the plain game, like a fresh Windows install.
4. The program runs with **Proton's Wine** (the same Wine Steam uses), in its own Wine setup, not the game's:
   - **Your game folder is protected.** It's mounted copy-on-write: the program sees the real game and may
     change, add or delete files, but every change lands in a separate folder. The real game folder isn't
     touched.
   - **No network**, and only the folders it needs (bubblewrap sandbox).
   - It finds the games the way it would on Windows (FOLM sets the registry paths for New Vegas and Fallout 3).
   - **Drive O: is "FOLM output".** If the program asks where to save, pick O: (for TTW: the destination folder).
5. When it closes, everything it changed in the game folder or saved to O: becomes **a normal mod**: game
   `Data` files go to the mod's data, other files (like a patched `Fallout3.exe`) go next to the game's exe.
   The program's own files are left out.
6. Your mods go back into the game. Tick the new mod and Deploy (or just ▶ Play).

Turning the mod off or removing it puts the original files back, exactly. If Steam's "verify files" restores
the game's exe, the 🩺 health check notices; Deploy puts the patched one back.

Patchers whose name says "patcher" run from inside the game folder, as their instructions usually say
("extract to the main game folder and run Patcher.exe"). Installers with their own path fields (TTW, BSA
Decompressor, ESM fixers) run from their own folder.

## Notes

- **TTW:** FOLM runs TTW's installer with `-NoOggEnc2`, which is about 35 times faster under Wine (see the
  development log). Allow around 20 minutes on a fast PC, longer on older ones, and ~20 GB of free space.
  Pick drive O: as the destination.
- **First use** sets up FOLM's installer Wine (copied from Proton in a few seconds). After a Proton update it's
  set up again, also in seconds; it holds nothing of yours.
- **Needs:** Steam's Proton (or GE-Proton, or a system Wine), `bubblewrap`, and `unshare` (util-linux, on every
  distro). Linux 5.11 or newer for copy-on-write mounts without root.
- **Files a program deletes** from the game folder are reported but left in place (a mod can't remove a game
  file); none of the programs above do this.
- Under the hood: `folm_core/wintool.py`.
