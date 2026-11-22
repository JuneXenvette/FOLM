"""look - FOLM's personal look (Settings → Personalize…): colors and font, and the game's own colors.

Saved for all profiles in <FOLM home>/look.json. A color is either "#rrggbb" or "game:<name>", which
means "whatever that color is in the game right now" (the Pip-Boy or HUD color the player picked in the
game's settings, read from FalloutPrefs.ini), so FOLM follows when the player changes it in the game.
"""
import json
import os
import re

DEFAULTS = {
    "base": "system",          # system | dark | light
    "font": "",                # "" = the desktop's font
    "size": 0,                 # 0 = the desktop's size
    "text": "",                # "" = the base's own
    "background": "",
    "accent": "",              # selection highlight
    "headers": "#c9a227",      # the mod list's category names ("── Core ──")
    "tab": "",                 # the selected tab's name
}
PRESETS = {                    # one click: "Pip-Boy": the game's colors for headers and tabs
    "FOLM": dict(DEFAULTS),
    "Pip-Boy": dict(DEFAULTS, base="dark", headers="game:HUD", tab="game:Pip-Boy",
                    accent="game:Pip-Boy", background="#0c140f"),
}

# The game's color settings (FalloutPrefs.ini), in the order they are offered. New Vegas stores each
# as three numbers; Fallout 3 (and New Vegas, as a leftover) also as one packed RRGGBBAA number.
_RGB = {"Pip-Boy": "Pipboy", "HUD": "HUDMain", "HUD (alt)": "HUDAlt", "Terminal": "Terminal",
        "Main menu": "MainMenu", "System": "System"}
_PACKED = {"Pip-Boy": "uPipboyColor", "HUD": "uHUDColor"}


def path(home):
    return os.path.join(home, "look.json")


def load(home):
    try:
        with open(path(home)) as fh:
            saved = json.load(fh)
    except (OSError, ValueError):
        saved = {}
    return {k: saved.get(k, v) for k, v in DEFAULTS.items()}


def save(home, look):
    os.makedirs(home, exist_ok=True)
    with open(path(home), "w") as fh:
        json.dump({k: look.get(k, v) for k, v in DEFAULTS.items()}, fh, indent=1)


def _read_ini(p):
    vals = {}
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                k, sep, v = line.partition("=")
                if sep:
                    vals[k.strip().lower()] = v.strip()
    except OSError:
        pass
    return vals


def _hex(r, g, b):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(x))) for x in (r, g, b))


def game_colors(prefs_ini):
    """{name: "#rrggbb"} for the game's interface colors, from its FalloutPrefs.ini. {} if unreadable.
    New Vegas keeps the Pip-Boy and HUD colors twice (three numbers, and one packed number). They
    usually match; when they don't, both are offered: the packed one under the plain name, the other
    as "<name> (second setting)", and the player picks by the swatch."""
    v = _read_ini(prefs_ini)
    out = {}
    for name, key in _RGB.items():
        try:
            out[name] = _hex(*(v[f"isystemcolor{key}{c}".lower()] for c in ("red", "green", "blue")))
        except (KeyError, ValueError):
            pass
    for name, key in _PACKED.items():
        raw = v.get(key.lower())
        if raw and re.fullmatch(r"\d+", raw):
            n = int(raw)
            packed = _hex((n >> 24) & 255, (n >> 16) & 255, (n >> 8) & 255)
            if name in out and out[name] != packed:
                out[f"{name} (second setting)"] = out[name]
            out[name] = packed
    return out


def resolve(color, game):
    """A look color -> "#rrggbb" or "" (use the default). "game:HUD" without that color -> ""."""
    if color.startswith("game:"):
        return game.get(color[5:], "")
    return color if re.fullmatch(r"#[0-9a-fA-F]{6}", color or "") else ""
