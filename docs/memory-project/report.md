# The 4 GB project: research report

November 2026. Written after the out-of-memory crash of 20 November and a long research pass. The
step-by-step plan is in [guide.md](guide.md).

## Verdict

**Worth attempting, in stages, measuring as we go.** The one change to the plan: this does **not** have
to be a point of no return, and we should keep it that way. Every step below is either a setting that
can be switched back, or a separate plugin or helper that can be turned off. Your save and your mod
setup never depend on it. If a stage doesn't pay off, we stop there and keep everything before it.

What the research changed:

1. **Part of the problem is already solved, by DXVK.** Your game's `d3d9.dll` is DXVK 3.0.1. Since DXVK
   2.0 (2022), DXVK keeps texture copies in memory it can map in and out of the game's 4 GB as needed,
   with a budget of about 100 MB inside them. So textures, which we assumed were the big tenant,
   mostly live outside the 4 GB already. Concept 3 (texture streaming) gains less than we hoped.
2. **One cheap fix is still off.** NVTF's `bUseDefaultPoolForTextures` is `0` on your setup. The
   performance guide everyone follows says to set it to `1`. It stops the game keeping its own second copy
   of every texture. Its only drawback (Alt-Tab breaks in exclusive full screen) doesn't apply to you:
   you play windowed (`bFull Screen=0`), and the guide says it doesn't happen under DXVK either.
3. **Proton can move Linux's own parts out of the 4 GB.** Under the old way Proton runs 32-bit games,
   the Linux side (graphics driver, Vulkan, sound) loads inside the game's 4 GB too. Proton
   Experimental has the new way (`PROTON_USE_WOW64=1`), which keeps those parts in 64-bit memory
   outside it. Users report it fixing out-of-memory crashes in other 32-bit games. We can test it with
   one launch option, and remove it the same way.
4. **We don't yet know who the big tenants are.** That's what the memory gauge is for. NVHR (the heap
   replacer) alone reserves about 1.6 GB up front for its pools. We need one real play session with
   the gauge before we spend weeks on a helper that might move the wrong thing.
5. **Concept 1 has a precedent, and a good first candidate.** ENBoost has done "a helper process holds
   the game's data" on Windows for years (it holds video memory in `enbhost.exe` processes). It works but
   is known to be touchy, and it doesn't work with DXVK, which is why we would build our own. The best
   first chore is **SMP physics**: NV SMP Physics is open source (GPL-3.0, like FOLM), does one clear
   job each frame (read the pose, simulate, write back the bones), and comes with a test tool that runs
   its simulation outside the game. Be honest about the gain, though: physics probably uses tens of MB,
   so its main win is **frame time** (it cost 25–29 ms per frame on your PC), not memory.
6. **Someone is rebuilding the whole engine as 64-bit.** [nv-rs](https://github.com/slaterain/nv-rs)
   (GPL-3.0, Windows preview out now) translates the game's code into Rust. It runs the whole game
   today, but still inside a model of the old 4 GB; the 64-bit move has started (textures, buffers
   and sound are already kept outside the 4 GB). Script-extender plugins don't work there yet,
   and it's slower than the original in busy places. If it succeeds, the 4 GB problem disappears for
   everyone who switches. That doesn't make our work pointless: FOLM, the gauge and the texture work help
   people on the original game today, and that's most players for years to come. It is a reason
   to build **small, separate pieces**, not one giant engine plugin.

## What each concept became

| Concept | What we found | Status in the plan |
| --- | --- | --- |
| **1. Helper process takes chores out of the 4 GB** | Possible. Precedent: ENBoost. Under Wine, a 64-bit helper can run next to the 32-bit game in the same prefix; shared memory between them is ordinary Windows API. | Stage 4, physics first. Memory gain small, frame-time gain big. |
| **2. Heavy work at loading screens and saves** | Sound idea, but forcing the game to unload things (`pcb`, auto-purge mods) has a history of breaking scripts and saves. | Used inside Concept 1 (the helper does its big transfers at loading screens), never as forced purging. |
| **3. Tiered textures by distance and direction** | DXVK already keeps textures out of the 4 GB. Swapping textures live inside the engine is very hard and fragile. Distance tiers exist already: that's what LOD is. | Becomes a **texture budget tool**: the best size per mod (Lite for far-away LOD, Performance up close) and compressing the huge uncompressed files. Stage 3. |

### "Behind the camera"
The game already doesn't *draw* what's behind you; it keeps it *loaded* so turning around is instant.
Unloading what's behind you would mean reloading it every time you turn, which the old engine can't do
fast enough without hitches. Not worth it on this engine. (nv-rs could do it one day.)

## What's taking the 4 GB (what we know)

- **NVHR pools**: about 1.2 GB reserved for small blocks, plus 16 MB blocks as the game grows
  (25 of them at the time of the crash, about 400 MB). Reserved isn't the same as used, but
  reserved space can't be given to anything else.
- **Linux libraries and the graphics driver** under old-style Proton: unknown, probably several hundred MB.
  The gauge's `image=` column will show it, and WoW64 should shrink it.
- **Scrap heaps**: nv-rs measured the game's 8 MB scrap-heap reservations at about 128–144 MB,
  99% never used.
- **Textures**: under DXVK, mostly outside. But your setup has **502 uncompressed textures over 1 MB
  (1.26 GB)**, the biggest an 85 MB rock LOD normal map. Each one passes through the 4 GB while it
  loads and needs one free block its own size: exactly what runs out when memory is fragmented.
  They also cost video memory (your RX 580 has 8 GB, so that's less urgent).
- **Mods, scripts, cells, actors**: the rest. Unknown until measured.

## Potential (you asked)

If every stage works:

- **Stages 1–2 (settings):** realistically several hundred MB more room and fewer crashes from
  fragmentation. For many players that alone ends out-of-memory crashes. It costs nothing, and FOLM can
  check and offer these settings for every user.
- **Stage 3 (texture budget):** faster loading, less video memory, no huge textures fighting for space.
  It becomes a FOLM feature anyone can use: "fit my textures to my PC".
- **Stage 4 (physics helper):** SMP hair and cloth on a weak CPU without the 25 ms hit, and a working
  template for moving other chores out. If it's solid, it's the first 64-bit helper for New Vegas that
  works with DXVK. That's new for the community.
- **Longer term:** the same pattern (gauge → settings → assets → helper) applies to any 32-bit game.
  You're right that 32-bit limits will keep coming back in new forms. The part that carries over is the
  method: **measure the space, then move the biggest tenant out.**

What it won't do: make New Vegas itself 64-bit. Only a rebuilt engine (like nv-rs) can do that.

## Risks

- **The physics helper adds a frame of delay** (the bones are one frame behind). For hair and cloth at
  60 fps that's normally invisible; we test it before building on it.
- **Your CPU has 2 cores (4 threads).** A helper still needs CPU time; it moves the work off the game's
  main thread but doesn't make it free. Gains are smaller than they would be on a 6-core PC.
- **WoW64 is newer** in Proton. It may have its own bugs with this game; that's why it's a test with
  the gauge running, not a permanent switch.
- **ENBoost's history** shows helpers can be touchy (crashes when the helper or the link misbehaves). We
  design ours to fail safe: if the helper dies, physics stops, the game keeps going.
- **Our time.** Stage 4 is weeks of work. Stages 1–3 are days.

## Windows

You don't have Windows, and most New Vegas players do. How each piece fares:

| Piece | On Windows |
| --- | --- |
| NVTF setting, texture budget | Same files, same effect. |
| WoW64 | Linux only. Windows already runs 32-bit games this way: its 32-bit graphics driver still sits inside the 4 GB. |
| Memory gauge helper (`folm-memwatch.exe`) | It's already a Windows program; it runs natively. |
| Physics helper | Written as a Windows program from day one (it runs in Wine on Linux), so it's the same code. |
| FOLM itself | Python and Qt run on Windows, but the Proton and Steam parts need a Windows counterpart. A separate, later project. |

**Testing without Windows:** Wine on your PC for the helper programs; GitHub's free Windows build
machines (for public projects) to build and run the tests on a real Windows; and Windows players from the
community for the real game. We ship Windows pieces only after someone has run them on real Windows.

## Sources

- DXVK, D3D9 texture memory moved to unmappable files: [DXVK pull request 2663](https://github.com/doitsujin/dxvk/pull/2663)
- NVTF settings, `bUseDefaultPoolForTextures`: [FNV Performance Guide](https://performance.moddinglinked.com/falloutnv.html)
- nv-rs: [repository](https://github.com/slaterain/nv-rs), [status](https://github.com/slaterain/nv-rs/blob/HEAD/docs/STATUS.md)
- New Vegas Heap Replacer: [Nexus page](https://www.nexusmods.com/newvegas/mods/69779)
- NV SMP Physics: [source](https://github.com/Balebandro/NV-SMP-Physics), [Nexus 100482](https://www.nexusmods.com/newvegas/mods/100482)
- Wine synchronization (for helper timing): [Wine 10.16 and ntsync](https://www.gamingonlinux.com/2025/10/wine-10-16-released-with-fast-synchronization-support-using-ntsync/)
- Measured on your PC: the crash's `hr.log`, the texture scan, `d3d9.dll` (DXVK v3.0.1), `NVTF.ini`,
  `FalloutPrefs.ini`.
