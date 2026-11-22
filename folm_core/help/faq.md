# Getting started

## What does FOLM do?
FOLM installs mods for **Fallout: New Vegas** (the *Courier* edition, with or without Tale of Two
Wastelands) and **Fallout 3** (the *Wanderer* edition) on Linux, puts them into the game, sorts the
load order and starts the game through Steam.

It runs the game with Steam's Proton like any other Linux setup. Windows installers and patchers run in
a sandbox, and nothing it does is permanent: **Undeploy** puts the game folder back exactly as it was.

## My first mod: where do I start?
1. Download the mod with Nexus's normal **Manual download** button.
2. Drag the file onto FOLM's window (or press **Install mod…**).
3. Tick it in the mod list and press **▶ Play**.

FOLM puts the mod into the game, sorts the plugins and starts the game. Start with the essentials:
xNVSE, the 4GB Patcher, JIP LN and NVTF (see *Resources → Guides*).

## What are Courier and Wanderer?
The two editions FOLM manages. **Courier** is New Vegas (and Tale of Two Wastelands, which runs inside
New Vegas). **Wanderer** is Fallout 3 on its own. Switch between them with **Edition** in the toolbar;
each has its own mods and profiles.

## What is a profile?
A separate mod setup: which mods are ticked and in what order. All profiles share one library of
installed mods, so a test profile costs no extra space. All profiles share the game's Saves folder;
the **Saves** tab shows which saves fit the profile you've picked.

## How do I make, rename or delete a profile?
Use the **Profiles** menu in the toolbar. **New profile…** starts one empty or as a copy of the one
you're using. **Rename** changes its name. **Delete a profile…** removes only its
list of mods: the mods stay installed, its saves stay where they are, and files it caught become the
mod "Caught files from …". The Default profile keeps its name. Switch between profiles with the **Profile** list next to the menu.

# Essentials

## Does FOLM need any mods to work?
No. FOLM and the game both run without mods. But almost every mod setup needs a few "essentials"
underneath it, and two of FOLM's own features use them too:

- the **low-memory save** needs **xNVSE** (6.2.1 or newer) and **JIP LN**: the save itself is done by a
  small script that runs inside the game, and only those two can run it;
- the **memory gauge's** warnings are made for a game that can use 4 GB, which needs the **4GB Patcher**.

The **🩺 Health check** shows each essential as installed or not, with a link to get it (double-click
the link). FOLM only stops you before ▶ Play when something you installed can't work without one, like
xNVSE plugins without xNVSE.

## xNVSE (New Vegas Script Extender)
Lets mods add new abilities to the game. Nearly every modern mod needs it, and so do JIP LN, NVTF and
the rest. FOLM's low-memory save uses it.

<https://www.nexusmods.com/newvegas/mods/67883>

## FNV 4GB Patcher
Lets New Vegas use 4 GB of memory instead of 2, and starts xNVSE with the game. Without it big setups
crash early and xNVSE's plugins don't load. Verifying the game's files in Steam undoes it; FOLM checks
before every ▶ Play.

<https://www.nexusmods.com/newvegas/mods/62552>

## JIP LN NVSE Plugin
Hundreds of fixes and new script commands that many mods need. FOLM's low-memory save runs on it: JIP
LN starts the small check that saves your game when FOLM asks.

<https://www.nexusmods.com/newvegas/mods/58277>

## New Vegas Tick Fix (NVTF)
Fixes stutter and timing problems. Its texture setting (`bUseDefaultPoolForTextures`) also saves memory.

<https://www.nexusmods.com/newvegas/mods/66537>

## FNV BSA Decompressor
Unpacks the game's archives once, so they load faster and stutter less.

<https://www.nexusmods.com/newvegas/mods/65854>

## Fallout 3: FOSE, the Anniversary Patcher and the BSA Decompressor
**FOSE** lets mods add new abilities, like xNVSE does for New Vegas. The **Anniversary Patcher** makes
the current Steam version of Fallout 3 work with FOSE and lets it use 4 GB. The **FO3 BSA Decompressor**
unpacks the archives. (The low-memory save is New Vegas only: FOSE can't run its check.)

- FOSE: <https://www.nexusmods.com/fallout3/mods/8606>
- Anniversary Patcher: <https://www.nexusmods.com/fallout3/mods/24913>
- FO3 BSA Decompressor: <https://www.nexusmods.com/fallout3/mods/25720>

## Keyboard shortcuts

- **F9**: ▶ Play. **F5**: refresh.
- **Ctrl+F**: search the mod list (Esc clears it).
- **Ctrl+Z** / **Ctrl+Y**: undo / redo a change to the mod list (on/off, order, sorting, removing,
  categories, notes).
- **Space**: turn the selected mod on or off. **Delete**: remove it from this profile (FOLM asks first,
  and Ctrl+Z brings it back; its files stay in the library).

# Installing mods

## Which kinds of mods can FOLM install?
Plain archives (.7z, .zip, .rar), FOMOD installers (with their pictures and choices), old FOMM script
installers, BAIN packages, archives inside archives, script extender plugins and Windows installers or
patchers (.exe). If a file isn't for this game at all, FOLM says so instead of installing it.

## I installed a mod twice by accident
FOLM asks when you install a file you already have, or another version of an installed mod: skip it,
replace it (keeping its place and notes) or keep both.

## FOLM offered to install a file I just downloaded

When a mod file (.7z, .zip, .rar, .fomod) appears in your Downloads folder or a library folder, FOLM
offers to install it at the bottom of its window. Nothing is installed until you press **Install**; **Not
now** skips it. Files still downloading are left alone until they're finished. Turn it off in the Settings
tab.

## I installed a newer version of a mod

FOLM offers **Update**: the new files replace the old ones, in the same place in your list, with its
on/off state, notes and tags. It knows it's the same mod from the Nexus file, or from the name once the
version is taken off ("My Mod v2" and "My Mod v3"). The mod keeps its old name for now.

## Should I keep Nexus's file names?
Yes. A name like `JIP LN NVSE-58277-57-40-1700000000.7z` tells FOLM which Nexus page the mod came from
and which file you got. That's how the requirement check and **Check for updates** work.

## What is a mod list?
A small `.folmlist` file naming mods in order, with what to do after each one. Settings tab →
**Install a mod list…** finds the files in your downloads, shows what's missing (with links) and installs
the rest. Settings tab → **Save this profile as a mod list…** makes your own to share.

## Which of my saves will load safely?

All profiles save in the game's one Saves folder, and the profile you pick is what each save is checked
against. The **Saves** tab lists your saves, newest first: **green** when all the plugins it was made with
are on in this profile, **red** when some are missing, with the profile it does fit if there is one. A red
save can still load, but quests and scripts from the missing plugins can break, so switch to the profile
it fits (or turn those plugins on). The list follows along as you switch profiles or turn mods on and
off, before you even deploy. Double-click a save to see all its plugins: which are on, which are installed but off, and which you don't have, each with a link to the mod's page (or a Nexus search when FOLM doesn't know the page).

# Load order and conflicts

## What's the difference between mod order and load order?
- **Mod order** (the list on the left) decides which mod wins when two mods have the same file.
  Lower wins.
- **Load order** (the Plugins tab) is the order the game loads `.esm` and `.esp` files. FOLM sorts it
  every time you deploy, with LOOT's community rules.

## A mod says its plugin must load last. How?
Right-click the plugin in the **Plugins** tab → **Keep at the end of the load order**. It gets a ⤓
mark and stays last, even after you add more plugins. Put several there and the last one you add
loads last. **Load earlier** and **Load later** move a plugin one place; a plugin always loads after
its masters, so some moves aren't possible. **Back to FOLM's order** undoes it. Deploy to apply.

## What does "wins 12 · loses 3" mean?
The mod has 12 files that beat other mods' copies and 3 that another mod lower in the list replaces.
The **Conflicts** tab shows exactly which files. Losing files is often fine and intended, like a
patch replacing the original's files.

## What are the blue, orange and red marks in the Plugins tab?
LOOT's messages. ℹ blue is a note, ⚠ orange a warning (like "needs cleaning"), ✖ red an error to fix
before playing. If a patch already fixes one, right-click it → **Mark as handled…**.

## What is the Overwrite folder?
Files the game or a tool created while playing (configs, logs) that belong to no mod. **Catch new
files** collects them. They always win conflicts.

# Playing

## Do I have to start the game from FOLM?
Yes, start it with **▶ Play** in FOLM, not from Steam or the game's launcher. Your mods are in the
game either way, but only ▶ Play gives you:

- the **checks** before the game starts (mods deployed, 4GB patch still on, nothing missing);
- the **memory gauge**, its warnings, and the **low-memory save** (FOLM asks the game to save; started
  from Steam, nobody asks);
- **crash reports** when the game crashes;
- the **borderless window** fix.

Steam still runs the game: FOLM starts it through Steam for you. Steam must be open.

## Why does Deploy turn gold?
Something you changed isn't in the game yet (a new mod, a mod turned off, a new order). **▶ Play** checks
too and offers to deploy first, so you never start the game with an old setup.

## What does FOLM check before the game starts?
That mods are deployed, Steam is running, the game is still 4GB-patched, xNVSE is there when its plugins
are, no plugin is missing a master, no LOOT errors, and no recent save needs a mod you turned off. You
only see the box when something is wrong.

## What does ⚡ Optimize do?
It gathers the fixes for problems nearly everyone has playing these games on Linux, explains each in a
sentence, and turns them on or off: **crackling sound**, **borderless window** (alt-tab and fullscreen
trouble under Proton), the **FPS cap** at 120 (physics break above that),
**one copy of each texture** (NVTF; frees memory in the 4 GB) and **GameMode** (keeps the CPU at full
speed while you play; needs the `gamemode` package, and on most distributions your account in the
`gamemode` group, or GameMode isn't allowed to change anything). **Turn on all recommended** ticks them all.
Each is also in the Settings tab, and turning one off undoes it. Problems Proton already fixes by itself (like
letting the game use 4 GB) aren't listed.

## The sound crackles in big fights
A Linux thing: the game's sound buffer is small, so when the CPU is busy the sound breaks up. FOLM fixes
it by itself (Settings tab → *Fix crackling sound*, on by default): it adds `PULSE_LATENCY_MSEC=60` to the
game's launch options in Steam. Steam only takes that while it's closed, so FOLM does it the next time
you press ▶ Play or open FOLM with Steam closed. If it still crackles, close big programs (browsers,
Discord) while you play: on a PC with little RAM they slow the game down too.

## Why an FPS cap?
Above about 120 FPS these games' physics break: things bounce, the game speeds up. FOLM sets a cap through
DXVK (Settings tab → FPS cap). 120 is a safe choice. Don't set it to your screen's refresh rate (60 on most
screens) with V-Sync off: the frames land unevenly against the screen and the game feels stuttery.

## Why does the game run in a window?
Windowed mode is the most reliable under Proton. With *Borderless window* on, FOLM removes the title bar
so the game fills the screen, and alt-tab stays safe.

# Crashes and memory

## The game crashed. What now?
FOLM notices and offers a **crash report**: the logs, your mod list and a plain-language guess at the
cause, all in one file. Nothing is sent anywhere; it's saved on your PC (personal paths removed).

## What is the 4 GB limit?
New Vegas and Fallout 3 are 32-bit programs: they can use about 4 GB, however much RAM your PC has.
Big mod setups (TTW, high-resolution textures, LOD) can fill that, and the game crashes when it's
full. Your PC's RAM isn't the problem; the game's own space is.

## What does the memory gauge do?
While you play, FOLM measures how full the game's 4 GB are. When they're nearly full you get a desktop
warning ("save soon"), and again just before they run out ("save now"). The crash report shows how
memory filled up over the session.

## Does FOLM save my game when memory runs low?
On New Vegas, yes (it needs JIP LN, which most setups have). At the first warning FOLM asks the game
to save, as a new save named like `FOLM_LowMemory_2026-11-21_21-04`, and tells you when it's done. If
the game crashes soon after, load that save. A save made with little memory left can itself be cut off
by a crash, which is why it's always a separate file: your own saves are never touched. It waits while
you're in a menu (dialogue, the Pip-Boy). Turn it off in the Settings tab.

## How can I make room in the 4 GB?
Use smaller texture packs (a "Performance" or "Lite" size instead of "Large"), especially for LOD, and
fewer heavy script mods. In NVTF's settings, `bUseDefaultPoolForTextures = 1` stops the game keeping a
second copy of textures; it's safe when you play windowed.

# Tools

## How do GECK, xEdit and xLODGen work with FOLM?
Open them from the **Tools** tab: they start with your mods loaded. What they save becomes a mod of its
own ("xEdit output", "Generated LOD"), so your other mods and the game's files are never changed. Turn
the mod off to undo it.

## How do I add a tool?
Download it and drop the file on FOLM, like a mod. FOLM keeps tools apart from your mods. The Tools tab
shows each tool's version and a link to its page, so you can see when a newer one is out.

## How do I check for updates?
**Tools → Check for updates** tells you when a newer FOLM is out, and opens a window with every mod in
your profile in three branches: **Needs an update**, **Up to date** and **Can't be checked**. Each row has
a link: the mod's Nexus files page; for mods that didn't come from Nexus, their home page (xNVSE's GitHub,
TTW's site), LOOT's link for one of their plugins, or a Nexus search. A mod can't be checked when its
download was renamed (keep Nexus's file names) or it didn't come from Nexus; the row says which. FOLM
only goes online when you press it, and needs no Nexus account.

# Troubleshooting

## A mod doesn't seem to do anything
Run **🩺 Health check**. It checks the files are in place, plugins have their masters, script extender
plugins actually loaded (from xNVSE's log), and that Wine isn't ignoring a mod's DLL.

## The game won't start after I added a mod
Most often a missing master or requirement: the Plugins tab and the pre-Play check show it. Otherwise
turn the newest mod off and try again. If it crashes, read the crash report FOLM offers.

## How do I undo everything?
**Undeploy** takes every mod out of the game folder and restores the game's settings exactly. Your mods
stay installed in FOLM; deploy again whenever you like.

## Where does FOLM keep its files?
In `~/Games/FOLM`: your mods, profiles, downloads list, backups and crash reports. The game folder only
holds links to your mods while they're deployed.
