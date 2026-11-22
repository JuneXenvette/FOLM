# The 4 GB project: step-by-step guide

Why each step is here: [report.md](report.md). Tick a box when the step is done, and move the
**▶ We are here** marker. Each stage ends with a check; we only start the next stage when the check says
it's worth it. Every change can be switched back.

**▶ We are here: Stage 4, step 13 (v4 built: true largest gap, lighter map, quit line, optional dheap give-back; ready to test)**

**Tomorrow (2026-11-22): test the measuring NVHR**
1. **Install:** drag `~/Downloads/Second Wind - Measuring NVHR.zip` onto FOLM. It must sit **below**
   "NVHR 4.3" in the mod list (a new mod goes to the bottom, so that's automatic). Leave NVHR 4.3 on:
   its loader (`d3dx9_38.dll`) is still needed. Deploy.
2. **Smoke test (5 minutes):** ▶ Play, load your save, walk a bit, quit to desktop. Tell Claude "check the
   heap log". Claude checks `secondwind-heap.log` appeared in the game folder with a line a minute, and
   that `hr.log` looks like before. If the game won't start or crashes at once: turn the mod off (you're
   back on NVHR 4.3) and tell Claude.
3. **The real test:** play as usual, an hour or more, until it crashes or you stop. Then "collect the
   logs". The crash report will say how big the request was that failed and how big the largest gap was.
4. Undo any time: turn "Second Wind - Measuring NVHR" off and deploy.

## The road ahead (decided 2026-11-21)

**Second Wind** is the name for everything that helps the game breathe. Its parts run inside the game or
next to it in the game's Wine, so they are Windows programs already and work on Windows and Linux alike.
Only FOLM, the manager window, needs a real port. The order:

1. **FOLM on Linux collects the data** (Stages 0-3): measure, the free settings, the texture budget.
   Linux is the test lab.
2. **Second Wind as a standalone mod** (Stage 4): an open xNVSE plugin anyone can install with any mod
   manager. Distance first, then the low-memory save and the memory gauge moved out of FOLM into it,
   and commands other mods can use, and **Second Wind Heap**, our own heap replacer built for the 4 GB
   problem. FOLM sets it up by itself on Linux.
3. **Second Wind Helper, then "breathing memory"** (Stages 5-6): work moved out of the game's 4 GB.
4. **FOLM: Windows edition** (Stage 7): the manager itself, ported, arriving where Second Wind already
   has Windows players.

---

## Stage 0: Measure (one evening of play)

Goal: find out who really takes the 4 GB, before we change anything.

- [ ] 1. Play a normal session (an hour or more, walking around the Mojave, a few doors and
      fast travels) with FOLM's crash watcher on. The memory gauge starts by itself.
- [ ] 2. Tell Claude "collect the logs". Claude reads the session's `memory.log` and writes down:
      the most used, the smallest largest-free-block, and the `image` / `mapped` / `private` split.
- [ ] 3. If the gauge says "couldn't join the game's Wine", Claude fixes the gauge first (tech debt item).

**Check:** we have a baseline number for "used" and "largest free block" at the fullest point.

## Stage 1: Free settings (one evening)

Test one change per session so we know which one helped. Write each result in the table at the bottom.

- [x] 4. **NVTF texture pool.** (On since 2026-11-21: FOLM sets it on deploy, ⚡ Optimize → *One copy of each texture*.) In `Data/NVSE/plugins/NVTF.ini`, set `bUseDefaultPoolForTextures = 1`.
      (Safe: you play windowed under DXVK.) Play, collect the logs, compare.
      *Undo:* set it back to `0`.
- [ ] 5. **Proton WoW64.** In Steam → New Vegas → Properties → Launch Options, put
      `PROTON_USE_WOW64=1` in front of what's there (Claude gives the exact line). Play, collect the logs, compare.
      Watch for: the game not starting, black screen, sound problems.
      *Undo:* remove it from Launch Options.
- [ ] 6. Keep whatever helped; switch back whatever didn't or caused trouble.

**Check:** how many MB did we gain? If the game now stays well clear of the warning levels in long
sessions, the crash problem is solved for your setup, and the rest is improvement, not rescue.

## Stage 2: FOLM learns from it (a day of coding)

- [ ] 7. FOLM's health check offers the settings that worked (NVTF texture pool; WoW64 if it proved
      safe), for every user, with an undo. Only shown when it applies (no noisy warnings).
- [ ] 8. Tune the gauge's warning levels from real data (tech debt item).

## Stage 3: Texture budget (a few days)

- [ ] 9. FOLM lists the heaviest textures per mod (we have the scan: 502 files, 1.26 GB uncompressed).
- [ ] 10. A "fit textures" tool: compress huge uncompressed files and pick a smaller size per mod
      (Lite for far-away LOD, Performance up close), into a separate generated mod, so the
      originals are never touched. Turning that mod off undoes it.
- [ ] 11. Look at the results in game (LOD shouldn't look worse at a distance), play, collect the logs.

**Check:** loading faster? Fewer big blocks needed? If the game looks worse, adjust or drop it.

Findings, 2026-11-21 (scan of the deployed game, 39,737 textures):
- **Object LOD atlases are the heaviest files**: xLODGen's `Buildings` atlases are 85 MB each (8K),
  plus an 85 MB normal map each; the Mojave alone has two pairs (about 340 MB), always in view. Built at
  4K they'd be about a quarter of that. Whether they still count against the 4 GB now that NVTF's
  texture pool setting is on is what the next session's memory log shows: measure first.
- **Identical textures under different names**: 28,739 extra copies, about 2 GB on disk, but 1.3 GB of
  that is blank terrain-LOD tiles that are never on screen together, so the saving in memory is small.
  Sharing them would need an NVSE plugin hooking the texture loader (a table FOLM writes on deploy:
  path → the one copy to use). Possible later; low value for now.
- Two identical 85 MB rock LOD normal maps (`nv_rockformations_01_lod_n` and its `_frosted_` twin).

## Stage 4: Second Wind, the standalone mod

An open xNVSE plugin (GPL-3.0, like FOLM) that works without FOLM, on Windows and Linux.

- [ ] 12. **Second Wind: Distance.** Out of combat, full draw distances; when a fight starts, clutter
      and props (`fLODFadeOutMultItems`/`Objects`) pull in; a few seconds after it ends, they open up
      again. People stay at full distance (a sniper must stay visible). First test: does the engine
      apply a changed fade distance right away?

      *The test (5 minutes, in game, console with `~`):* stand somewhere with clutter in view (Goodsprings,
      looking down the street), then:
      1. `GetNumericINISetting "fLODFadeOutMultItems:LOD"` shows 15 (your setting now).
      2. `SetNumericINISetting "fLODFadeOutMultItems:LOD" 1`: do far bottles, cans and tools vanish
         **at once**? Then `SetNumericINISetting "fLODFadeOutMultObjects:LOD" 1` for props (crates, barrels).
      3. If nothing changed: type `RefreshINI`, then look again. If still nothing, walk through a door
         and back.
      4. Put them back: the same commands with `15`.

      What it tells us: changes at once → Distance is a small plugin. After `RefreshINI` → still fine,
      slightly heavier. Only after a door → Distance has to hook the engine, a bigger job.
- [ ] 13. **Measuring NVHR.** A build of NVHR (GPL-2.0, source on GitHub) that changes nothing but logs,
      every minute, how full each of its pools and its big-object heap are. One long session (an hour or
      more, until it crashes or you quit) shows where its fixed 1.2 GB of pools is wasted and what the
      crash really asked for. First check the public source matches the 4.3 we run.
- [ ] 14. **Second Wind Heap.** Our own heap replacer, designed from step 13's data: pools that grow only
      when needed instead of fixed reservations, a clean region kept aside at start-up for big requests,
      and its fill levels handed to the gauge and the low-memory save (so they warn about what really
      crashes). Built on a proven allocator core (e.g. mimalloc, MIT) with our 4 GB strategy around it.
      Tested side by side with NVHR, many long sessions. It's also the base for breathing memory
      (Stage 6): that needs control of where the game's memory comes from.
      *Go/no-go:* sessions past the hour mark NVHR crashes at, no new crashes, no worse stutter.
- [ ] 15. **Move the low-memory save and the memory gauge's warnings** into Second Wind, so players on
      Windows get them too. FOLM on Linux keeps setting it up.
- [ ] 16. **For other mods:** `GetMemoryRoom`, an "OnMemoryLow" event, a way to mark what Distance must
      always show. Documented, so modders can design big again.
- [ ] 17. Windows testers (built and tested on GitHub's Windows machines too), then post it on Nexus and
      GitHub.

**Check:** smoother fights, long sessions without the NVHR crash, Windows testers happy. Then it goes public.

## Stage 5: Second Wind Helper (weeks)

A separate 64-bit program that does work for the game outside its 4 GB. Start with a simple,
self-contained job (music and radio decoding, save compression, preparing data before an area loads) to
learn how game and helper talk; physics later.

- [ ] 18. **The link.** A tiny test pair (32-bit "game" + 64-bit helper) in the game's Wine, swapping data
      through shared memory every frame. Measure the delay. Go/no-go: under 2 ms.
- [ ] 19. **A first job** moved to the helper. If the helper is missing or dies, the game goes on.
- [ ] 20. **Physics:** build NV SMP's simulation (`tools/systemtest.cpp`) as a 64-bit program, measure one
      step on your CPU, then a plugin that sends the pose and applies the bones it gets back one frame
      later (credit NV SMP's authors).
- [ ] 21. Loading screens: the helper does its big setup while the game loads.

**Check:** smoother than doing it in the game, nothing broken.

## Stage 6: Breathing memory

Keep data the game rarely touches (areas you just left, caches) in a big pool outside its 4 GB, and map
in only the part it needs right now, the way DXVK already does for textures.

- [ ] 22. Find what the game keeps but rarely uses (from the gauge's logs and the helper's view).
- [ ] 23. A prototype for one kind of data, then measure.

## Stage 7: FOLM, Windows edition

- [ ] 24. Port the manager: finding Steam and starting the game without Proton; deploy works the same.
- [ ] 25. Windows testers, then a release beside the Linux one.

## Watching

- [ ] Look in on [nv-rs](https://github.com/slaterain/nv-rs) now and then. If its 64-bit engine
      arrives with plugin support, Stage 4 may not be needed there.

---

## Results

| Date | Change | Most used (MB) | Smallest free block (MB) | Crashes | Notes |
| --- | --- | --- | --- | --- | --- |
| | Baseline (Stage 0) | | | | |
| 2026-11-21 | NVTF texture pool on, FPS cap 120 → 60, GameMode on | 1202 committed | 15 | 0 | 8 min only. Felt stuttery: the 60 cap without V-Sync (back to 120: "so much better"). GameMode did nothing (account not in the `gamemode` group). ~1.4 GB went to swap: close Discord while playing |
| 2026-11-21 19:05 | NVTF texture pool on, cap 120 | 1413 committed | 0-15 | 1 | Crashed after 59 min: NVHR `hr_malloc returned NULL`. Same as the 2026-11-20 23:23 crash (after 66 min). See "NVHR finding" below |
| 2026-11-22 04:12 | Measuring NVHR (step 13) | 1439 committed | 0.9-5.3 | 1 | Crashed after 55 min, 7 s after an autosave: the game asked for **85.3 MB in one piece**; largest gap 0.9 MB, 18.5 MB free in all. Pools used ~260 of their 1184 MB. See "Measured (2026-11-22)" below |
| 2026-11-22 07:24 | Measuring NVHR v2 (pools right-sized: 736 MB) | 1431 committed | 16-20 (0.9-5 in v1) | 0 | 52 min, quit normally. Largest gap 3-4x bigger than v1, but still under 85 MB after minute 5: the 450 MB the pools gave back was taken by something else (`va_reserved` stayed ~2780). The 85 MB request came only once, at load; a later loading screen asking for it would still have failed |
| 2026-11-22 11:51 | Second Wind NVHR v3 (176 MB reserve, map) | 1485 committed | logged 15.9, but see notes | 0 | **81 min, longest yet**, quit normally (swappiness 10). Reserve never needed: 8 requests of 85.3 MB (2 loading screens, 11:25 and 11:35) and 12 of 42.7 MB all came from Windows, one at 0x80000000, while `largest=` said 15.9. So under Wine the 1864 MB 'reserved' region at 0x80000000 is really free space handed out on demand, and `largest=` undercounts: v4 should probe VirtualAlloc instead |
| 2026-11-22 15:08 | Second Wind NVHR v4, GiveBackHeap=0 (+ DNW weathers, Engine Optimizations) | 1612 committed | **414-446 (asked)**; the map said 22-78 free | 0 | 49 min, quit (FOLM: no crash). The 85 MB pair came at 15:56 and went to 0x80000000 again; reserve unused. `bigtotal=17/0/8`. dheap held 384 MB of blocks, ~110 used: ~270 MB idle, what GiveBackHeap=1 would hand back. Minute line took 5-8 ms, the 30-min map 5.8 ms (both on Second Wind's own thread). No "game exited" line: NVTF's `bFastExit=1` ends the game with TerminateProcess, which skips DllMain |
| next | v4 with GiveBackHeap=1 | | | | Does `dheap=` drop from ~384 toward ~150 and `largest=` grow? Any stutter when blocks go back? |
| next | Without NVHR (untick "NVHR 4.3"), all else the same | | | | Does the game get past an hour? Watch for new stutter |

## Measuring NVHR: how it was built (2026-11-21)

`secondwind/` in FOLM's source. NVHR 4.3's public source (GitHub iranrmrf/Heap-Replacer, commit 4e1ec8b,
GPL-2.0; same date and log messages as the 4.3 release) rebuilt on Linux with MinGW, plus counters
(`main/sw_measure.h`, `main/sw_stats.h`; every change marked "Second Wind"). `secondwind/build/build.sh`
builds the mod; `build.sh test 60` runs the stress test in Wine.

Getting MinGW to produce what MSVC did, checked one by one:
- NVHR is compiled with **__fastcall as the default** (MSVC /Gr); the game calls its hooks as C++ methods.
  GCC has no such default, so each function the game calls is marked; checked in the built DLL (each
  cleans its stack arguments: `ret 4` / `ret 8` as expected).
- **Thread-local storage**: GCC ignores MSVC's `__declspec(thread)` silently, which would have made all
  threads share one scrap heap. Replaced with `__thread`; the test checks each thread gets its own.
- **Aliasing**: built with `-fno-strict-aliasing` (MSVC never assumes it; allocator code relies on that).
- Stress test: 4 threads, millions of random allocations/frees/reallocs incl. scrap heaps, every block's
  contents checked, counters back to 0 at the end: 0 errors.

Found in NVHR's code on the way (for Second Wind Heap, not changed in the measuring build):
- **Realloc of a block over 16 MB loses its contents**: those go straight to Windows and NVHR reports
  their size as 0, so realloc copies nothing.
- **The dheap never gives a 16 MB block back**: after a busy stretch it keeps them all, even empty.
- When a pool is full, requests quietly spill into the dheap.

## Measured (2026-11-22)

From `secondwind-heap.log`, a 55-minute TTW session with heavy LOD that crashed:
- **What failed:** one request for 85.3 MB (89,478,640 bytes; the crash log shows it as 0xAAAAB items of
  128 bytes plus a header, so a computed table, not a texture). The game makes it in pairs on loading
  (04:14, after loading the save; 04:37; 05:07, just after a door autosave), frees it within seconds, and
  makes a quarter-size one (21.3 MB) at other times. Each time it needs 85 MB of the 4 GB in one piece.
- **Why it failed:** the 4 GB were full of *reservations*, not data. Only ~1.3 GB was committed; the free
  gaps had been under 16 MB since minute 1. NVHR's pools held 1184 MB but used ~260 MB (the 80 and 96 byte
  pools reserve 128 MB each and used 22 and 27). The dheap held 400 MB of blocks with 83-150 MB in use.
- **Pools never filled** (`poolsfull=0` all session). Shrinking them is safe: a full pool passes
  requests on to the next pool, then the dheap.
- **v2** (step 13b): pools reserve about twice their peak in 16 MB steps (736 MB in all), giving back
  ~450 MB. Stress test: 28.6M operations, 0 errors. Smaller steps than 16 MB need NVHR's `POOL_ALIGN`
  changed; that and returning empty dheap blocks belong to Second Wind Heap (step 14).
- **v3** (step 13c): a 176 MB reserve, set aside at start-up (top-down, address space only), for
  requests over 16 MB that Windows has no gap for; decommitted when freed so it's ready for the next
  loading screen. Also fixes two NVHR 4.3 bugs: `hr_mem_size` said 0 for blocks over 16 MB (realloc lost
  their contents), and a failed realloc copied into NULL. Adds a map of who holds the 4 GB (pools, dheap,
  reserve, images, mapped files, private by size, the ten biggest outside NVHR). Stress test: 22.5M
  operations, 0 errors, and a full-address-space test: the 85 MB pair came from the reserve both rounds,
  a third failed cleanly, calloc from the reserve was zeroed.
- **v3 in the game** (2026-11-22 10:30-11:51): 81 min, no crash, reserve never used. The 85 MB pair came
  twice and Windows gave it each time, once at 0x80000000, while `largest=` said 15.9 MB: under Wine the
  1864 MB region at 0x80000000 looks reserved to VirtualQuery but is handed out on demand.
- **v4** (step 13d): `largest=` found by asking (reserve, release, halve: 16 tries, ~1 ms for the whole
  minute line); running totals of requests over 16 MB by size (`bigtotal=`); the map only at start and
  every 30 min, with its time in ms (rules the map in or out as the FPS dip); a "game exited after N
  min" line from DllMain on a normal exit (written with WriteFile, no CRT locks, so quitting can't hang);
  and, behind `GiveBackHeap=1` in `Data/NVHR/secondwind.ini` (off by default), empty dheap blocks go back
  to Windows after a minute empty, or at once when a big request finds no gap. A block counts as empty
  only when all 16 MB of it is in its free list (NVHR doesn't always merge free neighbours). Stress
  test: the give-back running flat out against four workers, 1807 blocks handed back, 13.3M operations,
  0 errors; the probe found 1689 MB at start where the map said 359.
- The memory gauge stayed quiet (it goes by committed memory), so the low-memory save never fired:
  step 14's gauge must read the largest free gap.

## NVHR finding (2026-11-21)

Both crashes in long sessions were NVHR's heap returning NULL, after about an hour; every shorter
session survived. NVHR (the heap replacer) splits the 4 GB at start-up:
- fixed **pools** for small objects (sizes 8 to 3584 bytes), reserved up front at 0x04000000-0x53000000
  (about 1.2 GB of address space, much of it reserved but never used);
- a **dheap** for bigger objects, grown in 16 MB blocks. It took 23 blocks (~370 MB) in the first minute
  and never got another: from 19:10 on, the largest free block in the game's 4 GB was under 16 MB
  (0-15 MB), so there was no room for a new block.

So the game didn't run out of memory (only ~1.4 GB committed at the crash): NVHR ran out of **places to
grow**. That also means FOLM's gauge (warns by committed memory) stayed silent and the low-memory save
never fired. The signal that matters with NVHR: the dheap's 23 blocks filling up, with no room for a 24th.

