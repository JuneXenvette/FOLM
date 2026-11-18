"""loot - FOLM's native support for LOOT's load-order database (no Windows LOOT needed).

LOOT (https://loot.github.io) is the community-standard load-order tool. Its game
masterlists and shared "prelude" are public domain (CC0) and maintained by the
LOOT team and community on GitHub. FOLM downloads them from LOOT's official repos
and applies:
  - groups (ordered buckets like "Unofficial Patches", "Late Loaders")
  - load-after and requirement rules
  - messages (say / warn / error) with their conditions
  - missing requirements, incompatibilities, and dirty-plugin (needs cleaning) notices

Conditions supported: file, active, many, many_active, checksum, version,
product_version, is_master, readable, with not / and / or and parentheses.
"""

import json
import os
import re
import struct
import time
import urllib.request
import zlib

import yaml

REPOS = {"courier": "falloutnv", "wanderer": "fallout3"}
FALLBACK_BRANCH = "v0.29"
REGEX_CHARS = set(":\\*?|")


# ---------------------------------------------------------------- download + load

def cache_dir(home, edition):
    return os.path.join(home, "loot", REPOS[edition])


def update(home, edition, log=lambda *a: None, max_age_days=7, force=False):
    """Fetch the masterlist + prelude from LOOT's GitHub (cached). Returns the folder."""
    d = cache_dir(home, edition)
    stamp = os.path.join(d, "fetched.json")
    if not force and os.path.exists(stamp):
        info = json.load(open(stamp))
        if time.time() - info["time"] < max_age_days * 86400:
            return d
    os.makedirs(d, exist_ok=True)
    repo = REPOS[edition]
    branch = FALLBACK_BRANCH
    try:
        with urllib.request.urlopen(f"https://api.github.com/repos/loot/{repo}", timeout=20) as r:
            branch = json.load(r).get("default_branch") or branch
    except OSError:
        pass
    for name, url in (("masterlist.yaml", f"https://raw.githubusercontent.com/loot/{repo}/{branch}/masterlist.yaml"),
                      ("prelude.yaml", f"https://raw.githubusercontent.com/loot/prelude/{branch}/prelude.yaml")):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = r.read()
            open(os.path.join(d, name + ".tmp"), "wb").write(data)
            os.replace(os.path.join(d, name + ".tmp"), os.path.join(d, name))
        except OSError as e:
            if not os.path.exists(os.path.join(d, name)):
                raise RuntimeError(f"couldn't download LOOT {name}: {e}")
            log(f"  ! couldn't refresh LOOT {name} ({e}); using the cached copy")
    json.dump({"time": time.time(), "branch": branch, "repo": repo}, open(stamp, "w"))
    log(f"LOOT masterlist updated (loot/{repo} {branch})")
    return d


def load(folder):
    """Parse masterlist.yaml with the prelude spliced in, as LOOT does."""
    ml = open(os.path.join(folder, "masterlist.yaml"), encoding="utf-8").read()
    pre_path = os.path.join(folder, "prelude.yaml")
    if os.path.exists(pre_path):
        pre = open(pre_path, encoding="utf-8").read()
        m = re.search(r"^prelude:.*?(?=^\S)", ml, re.S | re.M)
        if m:
            ml = ml[:m.start()] + "prelude:\n" + "\n".join("  " + l for l in pre.splitlines()) + "\n" + ml[m.end():]
    data = yaml.safe_load(ml) or {}
    return Masterlist(data)


def _as_list(x):
    return x if isinstance(x, list) else ([] if x is None else [x])


def _file_ref(x):
    """req/inc/after entries are either a string or {name, display, condition}."""
    if isinstance(x, dict):
        return x.get("name", ""), x.get("display"), x.get("condition")
    return str(x), None, None


class Masterlist:
    def __init__(self, data):
        self.groups = data.get("groups") or []
        self.globals = data.get("globals") or []
        self.entries = data.get("plugins") or []
        self.exact, self.regex = {}, []
        for e in self.entries:
            name = str(e.get("name", ""))
            if any(c in name for c in REGEX_CHARS):
                try:
                    self.regex.append((re.compile(name, re.I), e))
                except re.error:
                    pass
            else:
                self.exact.setdefault(name.lower(), []).append(e)
        self.group_rank = self._rank_groups()

    def _rank_groups(self):
        after = {g["name"]: _as_list(g.get("after")) for g in self.groups}
        after.setdefault("default", [])
        rank = {}

        def depth(n, seen=()):
            if n in rank:
                return rank[n]
            if n in seen:
                return 0
            rank[n] = 1 + max([depth(a, seen + (n,)) for a in after.get(n, [])] or [-1])
            return rank[n]
        for n in after:
            depth(n)
        return rank

    def entries_for(self, plugin):
        """All masterlist entries matching a plugin (exact first, then regex), merged."""
        hits = list(self.exact.get(plugin.lower(), []))
        hits += [e for rx, e in self.regex if rx.fullmatch(plugin)]
        merged = {"group": None, "after": [], "req": [], "inc": [], "msg": [], "dirty": [], "url": []}
        for e in hits:
            if e.get("group") and not merged["group"]:
                merged["group"] = e["group"]
            for k in ("after", "req", "inc", "msg", "dirty", "url"):
                merged[k] += _as_list(e.get(k)) + (_as_list(e.get(k + ":")) if k == "inc" else [])
        return merged


# ---------------------------------------------------------------- what the conditions can see

class GameView:
    """Files the game will see (Data-relative, lowercase -> real path), plus active plugins.

    Paths starting with '../' refer to the game folder (e.g. ../nvse_1_4.dll).
    """

    def __init__(self, files, active_plugins, plugin_info):
        self.files = {k.lower(): v for k, v in files.items()}
        self.active = [p for p in active_plugins]
        self.active_l = {p.lower() for p in active_plugins}
        self.info = {k.lower(): v for k, v in plugin_info.items()}
        self._crc = {}

    def path(self, rel):
        return self.files.get(rel.replace("\\", "/").lower())

    def matches(self, rel):
        # LOOT paths use '/'; a backslash in the file-name part belongs to a regex, so keep it.
        d, _, pat = rel.rpartition("/")
        if not any(c in pat for c in "*?|()[]^$+\\"):
            rel = rel.replace("\\", "/")
            return [rel.lower()] if self.path(rel) else []
        d = d.replace("\\", "/")
        try:
            rx = re.compile(pat, re.I)
        except re.error:
            return []
        pre = (d.lower() + "/") if d else ""
        return [f for f in self.files if f.startswith(pre) and "/" not in f[len(pre):] and rx.fullmatch(f[len(pre):])]

    def crc(self, rel):
        p = self.path(rel)
        if not p:
            return None
        if p not in self._crc:
            c = 0
            with open(p, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    c = zlib.crc32(chunk, c)
            self._crc[p] = c & 0xFFFFFFFF
        return self._crc[p]


def _pe_version(path, product=False):
    """FileVersion / ProductVersion from a Windows DLL or EXE's version resource."""
    try:
        data = open(path, "rb").read()
    except OSError:
        return None
    i = data.find(b"\xbd\x04\xef\xfe")
    if i < 0:
        return None
    ms, ls, pms, pls = struct.unpack_from("<IIII", data, i + 8)
    a, b = (pms, pls) if product else (ms, ls)
    return (a >> 16, a & 0xFFFF, b >> 16, b & 0xFFFF)


def _plugin_version(info):
    """Version from a plugin's description: "Version: 1.2", "v1.2", or a description that is only "3.4" (TTW)."""
    desc = (info or {}).get("description", "") or ""
    m = re.search(r"version:?\s*v?([0-9][0-9.]*)", desc, re.I) \
        or re.match(r"\s*v?([0-9]+(?:\.[0-9]+)+)\s*$", desc, re.I) \
        or re.match(r"\s*v([0-9]+(?:\.[0-9]+)*)\b", desc, re.I)
    if not m:
        return None
    nums = [x for x in m.group(1).strip(".").split(".") if x.isdigit()]
    return tuple(int(x) for x in nums) if nums else None


def _vtuple(s):
    return tuple(int(x) for x in re.findall(r"\d+", s))


def _cmp(a, op, b):
    n = max(len(a), len(b))
    a, b = a + (0,) * (n - len(a)), b + (0,) * (n - len(b))
    return {"==": a == b, "!=": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]


# ---------------------------------------------------------------- condition evaluator

TOKEN = re.compile(r'\s*(?:(\()|(\))|(,)|"((?:[^"\\]|\\.)*)"|(==|!=|<=|>=|<|>)|([A-Za-z_][A-Za-z0-9_]*)|([0-9A-Fa-f.]+))')


def _tokens(s):
    pos, out = 0, []
    while pos < len(s):
        m = TOKEN.match(s, pos)
        if not m or m.end() == pos:
            if s[pos:].strip() == "":
                break
            raise ValueError(f"can't read condition near: {s[pos:pos + 20]!r}")
        lp, rp, comma, string, op, word, num = m.groups()
        out.append(("(" if lp else ")" if rp else "," if comma else
                    "str" if string is not None else "op" if op else "word" if word else "num",
                    string if string is not None else (op or word or num or lp or rp or comma)))
        pos = m.end()
    return out


class Conditions:
    def __init__(self, view):
        self.view = view
        self.unknown = set()

    def eval(self, cond):
        if not cond:
            return True
        try:
            toks = _tokens(cond)
            val, i = self._or(toks, 0)
            return val
        except (ValueError, IndexError, KeyError):
            self.unknown.add(cond)
            return False

    def _or(self, t, i):
        v, i = self._and(t, i)
        while i < len(t) and t[i] == ("word", "or"):
            w, i = self._and(t, i + 1)
            v = v or w
        return v, i

    def _and(self, t, i):
        v, i = self._not(t, i)
        while i < len(t) and t[i] == ("word", "and"):
            w, i = self._not(t, i + 1)
            v = v and w
        return v, i

    def _not(self, t, i):
        if t[i] == ("word", "not"):
            v, i = self._not(t, i + 1)
            return not v, i
        if t[i][0] == "(":
            v, i = self._or(t, i + 1)
            return v, i + 1
        return self._call(t, i)

    def _call(self, t, i):
        name = t[i][1]
        if t[i + 1][0] != "(":
            raise ValueError("expected (")
        i += 2
        args = []
        while t[i][0] != ")":
            if t[i][0] != ",":
                args.append(t[i][1])
            i += 1
        return self._fn(name, args), i + 1

    def _fn(self, name, a):
        v = self.view
        if name == "file":
            return bool(v.matches(a[0]))
        if name == "readable":
            return v.path(a[0]) is not None
        if name == "active":
            if any(c in a[0] for c in "*?|()[]^$+\\"):
                rx = re.compile(a[0], re.I)
                return any(rx.fullmatch(p) for p in v.active)
            return a[0].lower() in v.active_l
        if name == "many":
            return len(v.matches(a[0])) > 1
        if name == "many_active":
            rx = re.compile(a[0], re.I)
            return sum(1 for p in v.active if rx.fullmatch(p)) > 1
        if name == "is_master":
            return bool(v.info.get(a[0].lower(), {}).get("is_master"))
        if name == "checksum":
            c = v.crc(a[0])
            return c is not None and c == int(a[1], 16)
        if name in ("version", "product_version"):
            path, op, want = a[0], a[1], _vtuple(a[2])
            p = v.path(path)
            have = None
            if p and path.lower().endswith((".esp", ".esm")):
                have = _plugin_version(v.info.get(os.path.basename(path).lower()))
            elif p:
                have = _pe_version(p, product=(name == "product_version"))
            if have is None:                 # LOOT: a missing file counts as "no version"
                return op in ("!=", "<", "<=") if p is None else False
            return _cmp(have, op, want)
        raise KeyError(name)


# ---------------------------------------------------------------- applying it

def _plain(s):
    """LOOT text uses markdown: turn links into 'text (url)' and drop bold/italic markers."""
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", str(s))
    return re.sub(r"\*\*([^*]+)\*\*|\*([^*]+)\*", lambda m: m.group(1) or m.group(2), s)


def _text(msg, subs_fmt=True):
    content = msg.get("content", "")
    if isinstance(content, list):
        en = [c for c in content if c.get("lang") == "en"] or content[:1]
        content = en[0].get("text", "") if en else ""
    for k, s in enumerate(_as_list(msg.get("subs"))):
        content = content.replace("{" + str(k) + "}", str(s))
    content = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", content)     # markdown links -> plain
    return re.sub(r"\*\*([^*]+)\*\*|\*([^*]+)\*", lambda m: m.group(1) or m.group(2), content)


def evaluate(ml, plugins, view):
    """Return (after_rules, group_ranks, messages).

    after_rules:  {plugin: set(plugins it must load after)} from groups' members are applied by rank
    group_ranks:  {plugin: int}
    messages:     [(severity, plugin_or_None, text)]
    """
    cond = Conditions(view)
    after, ranks, msgs = {}, {}, []
    present = {p.lower(): p for p in plugins}
    default_rank = ml.group_rank.get("default", 0)
    for g in ml.globals:
        if cond.eval(g.get("condition")):
            msgs.append((g.get("type", "say"), None, _text(g)))
    for p in plugins:
        e = ml.entries_for(p)
        ranks[p] = ml.group_rank.get(e["group"] or "default", default_rank)
        deps = set()
        for x in e["after"] + e["req"]:
            name, _, c = _file_ref(x)
            if name.lower() in present and cond.eval(c):
                deps.add(present[name.lower()])
        if deps:
            after[p] = deps
        if p.lower() not in view.active_l:
            continue                          # messages only for active plugins
        for x in e["req"]:
            name, display, c = _file_ref(x)
            if cond.eval(c) and not view.matches(name):
                msgs.append(("error", p, f"requires {_plain(display or name)}, which is missing"))
        for x in e["inc"]:
            name, display, c = _file_ref(x)
            if cond.eval(c) and view.matches(name):
                msgs.append(("error", p, f"is incompatible with {_plain(display or name)}"))
        for m in e["msg"]:
            if isinstance(m, dict) and cond.eval(m.get("condition")):
                msgs.append((m.get("type", "say"), p, _text(m)))
        for d in e["dirty"]:
            if isinstance(d, dict) and d.get("crc") is not None and view.crc(p) == int(d["crc"]):
                n = d.get("itm", 0), d.get("udr", 0), d.get("nav", 0)
                msgs.append(("warn", p, f"needs cleaning with {d.get('util', 'FNVEdit')}: "
                                        f"{n[0]} ITM, {n[1]} deleted references, {n[2]} deleted navmeshes"))
    if cond.unknown:
        msgs.append(("say", None, f"FOLM skipped {len(cond.unknown)} LOOT condition(s) it can't evaluate yet"))
    return after, ranks, msgs
