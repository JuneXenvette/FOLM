"""plugins - read Fallout 3 / New Vegas plugin headers and build a load order.

Plugins (.esm/.esp) start with a TES4 record. Its MAST subrecords list the
plugins it depends on ("masters"), which must load before it. FO3 and FNV both
use a 24-byte record header followed by subrecords (4-byte type, 2-byte size).
"""

import os
import struct

# Base-game load order, which never changes. Anything not listed comes after.
VANILLA_ORDER = {
    "courier": [
        "FalloutNV.esm", "DeadMoney.esm", "HonestHearts.esm", "OldWorldBlues.esm",
        "LonesomeRoad.esm", "GunRunnersArsenal.esm",
        # Tale of Two Wastelands builds these from Fallout 3; with TTW the courier packs
        # load after the Fallout 3 DLC (LOOT's masterlist rule, TTW's official order):
        "Fallout3.esm", "Anchorage.esm", "ThePitt.esm", "BrokenSteel.esm",
        "PointLookout.esm", "Zeta.esm",
        "CaravanPack.esm", "ClassicPack.esm", "MercenaryPack.esm", "TribalPack.esm",
        "TaleOfTwoWastelands.esm",
    ],
    "wanderer": [
        "Fallout3.esm", "Anchorage.esm", "ThePitt.esm", "BrokenSteel.esm",
        "PointLookout.esm", "Zeta.esm",
    ],
}

FLAG_MASTER = 0x1


class PluginError(ValueError):
    pass


def read_header(path):
    """Return {'masters': [...], 'is_master': bool, 'author': str, 'description': str}."""
    with open(path, "rb") as f:
        head = f.read(24)
        if len(head) < 24 or head[:4] != b"TES4":
            raise PluginError(f"{os.path.basename(path)}: not a Fallout 3/New Vegas plugin")
        size, flags = struct.unpack_from("<II", head, 4)
        data = f.read(size)
    if len(data) < size:
        raise PluginError(f"{os.path.basename(path)}: header is cut short")
    info = {"masters": [], "is_master": bool(flags & FLAG_MASTER), "author": "", "description": ""}
    pos = 0
    while pos + 6 <= len(data):
        typ = data[pos:pos + 4]
        (sz,) = struct.unpack_from("<H", data, pos + 4)
        body = data[pos + 6:pos + 6 + sz]
        text = body.split(b"\0", 1)[0].decode("cp1252", "replace")
        if typ == b"MAST":
            info["masters"].append(text)
        elif typ == b"CNAM":
            info["author"] = text
        elif typ == b"SNAM":
            info["description"] = text
        pos += 6 + sz
    return info


def sort_plugins(plugins, preferred, edition="courier", extra_after=None, group_rank=None):
    """Order plugin names for loading. Returns (ordered_names, problems).

    Hard rules, never broken: a plugin loads after its masters; ESMs (master-flagged)
    load before ESPs; extra_after[p] (e.g. LOOT load-after/requirement rules) loads p
    after those plugins. Among plugins that are free to go next, the lowest
    group_rank goes first (LOOT groups), then the vanilla order, then `preferred`
    (the player's order), then name.
    """
    import heapq
    extra_after = extra_after or {}
    group_rank = group_rank or {}
    lower = {n.lower(): n for n in plugins}
    vanilla = [lower[v.lower()] for v in VANILLA_ORDER.get(edition, []) if v.lower() in lower]
    pref = [lower[p.lower()] for p in preferred if p.lower() in lower]
    rest = sorted(n for n in plugins if n not in vanilla and n not in pref)
    wish = vanilla + [p for p in pref if p not in vanilla] + rest
    pos = {n: i for i, n in enumerate(wish)}
    is_m = lambda n: n.lower().endswith(".esm") or bool(plugins[n].get("is_master"))
    van = set(vanilla)

    problems = set()
    need = {n: set() for n in plugins}
    for n in plugins:
        for m in plugins[n]["masters"]:
            if m.lower() in lower:
                need[n].add(lower[m.lower()])
            else:
                problems.add(f"{n} needs missing master {m}")
        for d in extra_after.get(n, ()):
            d = lower.get(d.lower())
            if d and d != n and not (is_m(d) is False and is_m(n)):   # an ESM can't wait for an ESP
                need[n].add(d)
    esps_wait = [n for n in plugins if is_m(n)]        # every ESP waits for every ESM
    key = lambda n: (0 if n in van else 1, not is_m(n), 0 if n in van else group_rank.get(n, 0), pos[n])
    done, order = set(), []
    remaining = set(plugins)
    while remaining:
        ready = [n for n in remaining if need[n] <= done and (is_m(n) or set(esps_wait) <= done)]
        if not ready:                                   # a cycle: break it at the best candidate
            n = min(remaining, key=key)
            problems.add("circular load-order rules around " + n)
        else:
            n = min(ready, key=key)
        order.append(n)
        done.add(n)
        remaining.discard(n)
    return order, sorted(problems)


def write_test_plugin(path, masters=(), esm=None, author="FOLM test"):
    """Write a minimal valid plugin (for tests)."""
    esm = path.lower().endswith(".esm") if esm is None else esm
    subs = b""
    def sub(t, payload):
        return t + struct.pack("<H", len(payload)) + payload
    subs += sub(b"HEDR", struct.pack("<fIi", 1.34, 0, 0x800))
    subs += sub(b"CNAM", author.encode() + b"\0")
    for m in masters:
        subs += sub(b"MAST", m.encode() + b"\0") + sub(b"DATA", b"\0" * 8)
    head = b"TES4" + struct.pack("<IIIIHH", len(subs), FLAG_MASTER if esm else 0, 0, 0, 15, 0)
    with open(path, "wb") as f:
        f.write(head + subs)
