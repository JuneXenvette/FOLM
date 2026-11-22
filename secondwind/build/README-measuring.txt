Second Wind NVHR v4
===================

What it is
  New Vegas Heap Replacer 4.3 (by iranrmrf, GPL-2.0), rebuilt from its public source by FOLM's Second
  Wind project, to stop big setups (TTW, heavy LOD) crashing with "hr_malloc returned NULL" after
  about an hour. It writes what it sees to secondwind-heap.log in the game folder.

  What we measured: on loading screens the game asks for 85.3 MB in one piece (two at once), and frees
  it again seconds later. With NVHR 4.3, after about an hour no gap that big was left in the game's
  4 GB, although only about 1.3 GB was really in use, so the request failed and the game crashed.

  What's changed from NVHR 4.3:
  - Right-sized pools (v2): NVHR 4.3 reserves 1184 MB for its small-object pools; a measured TTW
    session used about 260 MB. They now reserve about twice what was used (736 MB). A pool that fills
    up passes its requests on to the next pool and then the dheap, as in NVHR 4.3.
  - A reserve for big requests (v3): at start-up, while the 4 GB is still in one piece, 176 MB of it
    is set aside (address space only: no RAM). Requests over 16 MB still go to Windows first. Only when
    there's no gap big enough do they get a piece of the reserve, which is given back when the game
    frees it, ready for the next loading screen.
  - Fixed (v3): NVHR 4.3 said a block over 16 MB had size 0, so growing one lost its contents; and
    when a resize failed it copied into nothing instead of keeping the old block.
  - The real largest gap (v4): under Wine/Proton, reading the memory map shows a big region as taken
    when Wine really hands it out on demand, so v3's log said 15.9 MB while the game got 85 MB. v4
    finds the largest gap by asking for it (and giving it straight back).
  - Giving empty heap blocks back (v4, off unless you turn it on): NVHR 4.3 keeps every 16 MB block of
    its big-object heap (dheap) for good; a measured session ended with 272 MB taken and 115 MB used.
    With GiveBackHeap=1 in Data/NVHR/secondwind.ini, a block that has been empty for a minute goes
    back to Windows, and when a big request finds no gap every empty block goes back at once before
    it asks again. NVHR makes a new block whenever it needs one.
  - Lighter on the game (v4): the full memory map is written at start and every 30 minutes (v3:
    every 5), and the log says how long it took.

Needs
  NVHR 4.3 installed (its d3dx9_38.dll loader in the game folder). This mod only replaces the
  Data/NVHR/nvhr_*.dll files, so it must win over NVHR 4.3 (put it below NVHR in the mod list).
  Undo: turn this mod off; NVHR 4.3's own files come back.

Settings (Data/NVHR/secondwind.ini, read when the game starts)
  GiveBackHeap=0   1 hands empty dheap blocks back to Windows (see above). 0 keeps them, like NVHR 4.3.

What it writes (secondwind-heap.log, game folder)
  One line a minute:
    min=       minutes since the game started
    pools=     small-object pools: in use / committed / reserved (MB)
    dheap=     big-object heap: in use / blocks taken (MB); it grows in 16 MB blocks
    big=       allocations over 16 MB that went straight to Windows and are held right now: MB (count)
    bigfail=   allocations that failed (the crash)
    poolsfull= pools that are completely full
    largest=   the largest piece Windows will really give (MB), found by asking
    va_free=   free address space as the memory map shows it (undercounts under Wine)
    reserve=   the reserve: in use / size MB (times used)
    bigtotal=  requests over 16 MB so far this session: 16-32 / 32-64 / 64+ MB
    gaveback=  empty dheap blocks handed back so far
    took=      how long writing this line took (ms)
  RESERVE:   a big request the reserve caught (one NVHR 4.3 would have crashed on).
  GAVE BACK: empty dheap blocks handed back, and why.
  Every 5 minutes, each pool on its own line. At start, every 30 minutes, the first time the reserve
  is used and when an allocation fails, a map of who holds the 4 GB: NVHR's pools and dheap, the
  reserve, DLLs (image), mapped files and everything else (private), with the ten biggest pieces
  outside NVHR, and how long the map took.
  "game exited after N min" when the game quits normally (a hard crash never writes it).

Built on Linux with MinGW (secondwind/build/build.sh in FOLM's source). The changes to NVHR's source
are in NVHR/second-wind-changes.diff. License: GPL-2.0, like NVHR.
