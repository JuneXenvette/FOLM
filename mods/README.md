# FOLM Mods

Mods made by the FOLM Project. They also double as real-world test cases for
the Courier and Wanderer managers.

Rule for everything here: **original work only.** Our own models, textures,
scripts and writing. Nods and homages to other franchises are fine (that's what
Wild Wasteland is for); copies of their designs, names or logos are not.

## Categories

| Category | Goal | Examples |
|---|---|---|
| **Restore** | Bring back cut or unfinished content | Cut items, quests or dialogue found in the game files |
| **Flesh out** | Fill in thin or empty parts of the world | Minor zones to fill the empty space between locations (owner: user) |
| **Update** | Modernise how the game looks and plays | Mesh and texture rework, updated character models |
| **Patch** | Fix bugs and compatibility | Our bug-fix layer, TTW compatibility patches |
| **Add** | New content that fits the world | Wild Wasteland weapons, the choose-your-wasteland start menu |

## Mod list

| Mod | Category | Edition | Status | Notes |
|---|---|---|---|---|
| Choose Your Wasteland (start menu) | Add | Courier (TTW) | idea | Pick Capital Wasteland or Mojave at the start |
| Minor zones | Flesh out | Courier | planned | User builds these in GECK |
| Capital Factions (working name) | Flesh out | Courier (TTW) first, then Wanderer | idea | New Vegas-style reputation for Fallout 3 factions: per-faction fame/infamy, consequences (prices, dialogue, hostility, hit squads, work), faction disguises, rivalries, ranks/perks. TTW: extend the engine's reputation system (check what TTW already adds). Wanderer: our own scripted system via FOSE + Pip-Boy display. Design/dialogue/GECK: user; systems/scripts/compat checks: Claude |
| Heretic Absolver (working name) | Add | Courier + Wanderer | planned — **first mod** | Copy of the vanilla Gauss rifle with the scope removed (edited copy of its model + basic aim points), firing 25mm grenade rounds with the grenade machine gun's projectile and firing sound. Uses only vanilla game assets, so it's safe to release. Homage to 40k: no Games Workshop names or logos. **Found:** New Vegas: hidden deep in Vault 34 (to confirm) if the player has Wild Wasteland. Fallout 3: added to the Tenpenny Tower reward for siding with the residents, with a Wild Wasteland check in TTW. Wanderer (no Wild Wasteland in FO3): always given, or an on/off option. **To decide:** fire mode; whether the FO3 copy is a "Smite" variant |

## Layout

Each mod gets its own folder: `mods/<mod-name>/` with its plugin, assets
(`meshes/`, `textures/`), source files (Blender `.blend`, scripts) and a short README.
