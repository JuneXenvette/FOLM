"""optimize - the fixes for problems that happen to (nearly) everyone playing these games on Linux.

Behind the ⚡ Optimize button. Each fix is one of FOLM's settings, so it's applied the same way as from
⚙ Settings, and turning it off undoes it. Only fixes for problems that are known to happen on Linux and
that FOLM can apply safely are here; what Proton or DXVK already fix by themselves is left out:
- Proton already lets every 32-bit game use 4 GB (its "forcelgadd" is on by default);
- DXVK already has its own fixes for New Vegas (an app profile for FalloutNV.exe).
"""
from . import steamopts

# key, name, the problem it fixes (plain words), the value "on" means, recommended
FIXES = [
    ("sound_fix", "Fix crackling sound",
     "The game's sound buffer is tiny under Linux, so the sound crackles or stutters when the PC is busy "
     "(big fights, loading new areas). FOLM gives it a bigger one in Steam's launch options.", True, True),
    ("borderless", "Borderless window",
     "Fullscreen under Proton can leave a black screen or a frozen picture after alt-tab, and the window "
     "can come out the wrong size. FOLM runs the game in a window without a title bar that fills the "
     "screen.", True, True),
    ("fps_cap", "FPS cap at 120",
     "Above about 120 FPS the game's physics break: things fly around, the game speeds up. FOLM caps it "
     "through DXVK. (Not at your screen's refresh rate: without V-Sync a cap right at the refresh rate "
     "makes the picture stutter.)", 120, True),
    ("nvtf_texture_pool", "One copy of each texture (NVTF)",
     "By default the game keeps every texture twice, once inside its 4 GB, so texture packs fill it fast. "
     "NVTF can keep just one copy, which frees memory for everything else. NVTF's own notes say it's "
     "needed with texture mods. Only when the game runs in a window: in exclusive fullscreen it breaks "
     "alt-tab.", True, True),
    ("gamemode", "GameMode (full CPU speed while you play)",
     "Linux slows the CPU down to save power, and these games lean on one CPU core, so they stutter in "
     "busy places, worst on PCs with 2-4 cores. GameMode keeps the CPU at full speed while the game runs "
     "and goes back afterwards.", True, True),
]


def check(m):
    """[{key, name, why, on (bool), state, available, recommended, value}] for the Optimize window.
    state: a short line saying where the fix stands."""
    from .manager import game_info
    app = m.data.get("steam_app_id") or game_info(m.edition)["steam_app_id"]
    opts = steamopts.current(app)
    ours = set(m.data.get("steam_fixes", []))
    out = []
    for key, name, why, value, rec in FIXES:
        cur = m.setting(key)
        on = bool(cur)
        available, state = True, "on" if on else "off"
        if key == "fps_cap" and on:
            state = f"on ({cur} FPS)"
        if key == "nvtf_texture_pool":
            why_not = m.nvtf_pool_why_not() if hasattr(m, "nvtf_pool_why_not") else None
            if why_not:
                available, state = (False, why_not) if "needs" in why_not or "only" in why_not \
                    else (True, f"waiting: {why_not}")
        var = next((v for v, (_x, k) in steamopts.FIXES.items() if k == key), None)
        gm_why = steamopts.gamemode_why_not() if key == "gamemode" else None
        if gm_why:
            available, state = False, gm_why[0].upper() + gm_why[1:]
        elif var and on:
            if opts is None:
                state = "on (FOLM couldn't find Steam's settings for this game yet)"
            elif not steamopts.has(opts, var):
                state = "on: goes into Steam the next time Steam is closed when you open FOLM or press ▶ Play"
            elif var not in ours:
                state = "on (already in your Steam launch options)"
        out.append({"key": key, "name": name, "why": why, "on": on, "state": state, "available": available,
                    "recommended": rec, "value": value})
    return out


def apply(m, choices, log=lambda *_: None):
    """choices: {key: bool}. Turns each fix on or off (only the ones that change). Returns the keys changed."""
    changed = []
    for key, name, _why, value, _rec in FIXES:
        if key not in choices:
            continue
        want = bool(choices[key])
        cur = m.setting(key)
        target = value if want else (False if isinstance(value, bool) else 0)
        if want == bool(cur) and not (want and key == "fps_cap" and cur > target):
            continue
        m.set_setting(key, target)
        changed.append(key)
        log(f"{name}: {'on' if want else 'off'}")
    return changed
