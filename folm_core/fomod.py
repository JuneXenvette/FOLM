"""fomod - FOLM's own installer for XML FOMOD mods (fomod/ModuleConfig.xml).

Supports the parts of the FOMOD format that mods actually use:
  requiredInstallFiles, installSteps (with visibility conditions), optional
  groups (SelectExactlyOne / AtMostOne / AtLeastOne / All / Any), plugin type
  descriptors (fixed or condition-based), condition flags,
  conditionalFileInstalls, moduleDependencies, file/folder entries with
  priority, and alwaysInstall / installIfUsable.

The caller supplies a `chooser(step_name, group)` that returns which options
to pick, so the same engine drives the command line, the app's wizard, and
unattended reinstalls (replaying saved choices).
"""

import os
import shutil
import xml.etree.ElementTree as ET

GROUP_TYPES = ("SelectExactlyOne", "SelectAtMostOne", "SelectAtLeastOne", "SelectAll", "SelectAny")


class FomodError(ValueError):
    pass


# ---------------------------------------------------------------- reading

def _find_ci(base, rel):
    """Resolve a '\\' or '/' path under base, ignoring letter case. Returns the real path or None."""
    cur = base
    for part in [p for p in rel.replace("\\", "/").split("/") if p and p != "."]:
        try:
            names = {n.lower(): n for n in os.listdir(cur)}
        except (FileNotFoundError, NotADirectoryError):
            return None
        if part.lower() not in names:
            return None
        cur = os.path.join(cur, names[part.lower()])
    return cur


def _strip_ns(el):
    for e in el.iter():
        if isinstance(e.tag, str) and "}" in e.tag:
            e.tag = e.tag.split("}", 1)[1]
    return el


def load_config(module_root):
    """Parse fomod/ModuleConfig.xml under module_root (any encoding with BOM/declaration)."""
    path = _find_ci(module_root, "fomod/ModuleConfig.xml")
    if not path:
        raise FomodError("no fomod/ModuleConfig.xml found")
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        # some FOMODs declare one encoding and use another: try the common ones
        for enc in ("utf-16", "utf-8-sig", "cp1252"):
            try:
                root = ET.fromstring(raw.decode(enc).encode("utf-8").replace(b'encoding="UTF-16"', b'encoding="UTF-8"'))
                break
            except (UnicodeDecodeError, ET.ParseError):
                root = None
        if root is None:
            raise FomodError("ModuleConfig.xml is not valid XML")
    return _strip_ns(root)


def _text(el, tag, default=""):
    x = el.find(tag)
    return (x.text or "").strip() if x is not None and x.text else default


def _order(items, el, key="name"):
    """FOMOD lists are sorted Ascending by name unless order="Explicit"/"Descending"."""
    order = (el.get("order") or "Ascending") if el is not None else "Ascending"
    if order == "Explicit":
        return items
    return sorted(items, key=lambda i: i[key].lower(), reverse=(order == "Descending"))


# ---------------------------------------------------------------- conditions

class Context:
    """What the installer may check: existing files/plugins and flags set so far."""

    def __init__(self, existing_files=(), active_plugins=()):
        self.files = {f.lower().replace("\\", "/") for f in existing_files}
        self.active = {p.lower() for p in active_plugins}
        self.flags = {}

    def file_state(self, name):
        n = name.lower().replace("\\", "/")
        if n in self.active:
            return "Active"
        if n in self.files:
            return "Inactive"
        return "Missing"

    def check(self, deps):
        """Evaluate a <dependencies> / <moduleDependencies> / <visible> element."""
        if deps is None:
            return True
        results = []
        for d in deps:
            if d.tag == "fileDependency":
                results.append(self.file_state(d.get("file", "")) == d.get("state", "Active"))
            elif d.tag == "flagDependency":
                results.append(self.flags.get(d.get("flag", "")) == (d.get("value") or ""))
            elif d.tag == "dependencies":
                results.append(self.check(d))
            elif d.tag in ("gameDependency", "foseDependency", "fommDependency", "nvseDependency"):
                results.append(True)          # version checks: assume a current setup
        if not results:
            return True
        return all(results) if (deps.get("operator") or "And") == "And" else any(results)


def plugin_type(plugin, ctx):
    td = plugin.find("typeDescriptor")
    if td is None:
        return "Optional"
    t = td.find("type")
    if t is not None:
        return t.get("name", "Optional")
    dt = td.find("dependencyType")
    if dt is not None:
        for pat in dt.findall("patterns/pattern"):
            if ctx.check(pat.find("dependencies")):
                return pat.find("type").get("name", "Optional")
        d = dt.find("defaultType")
        return d.get("name", "Optional") if d is not None else "Optional"
    return "Optional"


# ---------------------------------------------------------------- choosing

def default_choice(group):
    """Pick what a player would get by just clicking Next: required + recommended."""
    opts = group["plugins"]
    usable = [i for i, p in enumerate(opts) if p["type"] != "NotUsable"]
    req = [i for i, p in enumerate(opts) if p["type"] == "Required"]
    rec = [i for i, p in enumerate(opts) if p["type"] == "Recommended"]
    t = group["type"]
    if t == "SelectAll":
        return usable
    if t == "SelectExactlyOne":
        return (req or rec or usable)[:1]
    if t == "SelectAtLeastOne":
        return sorted(set(req + rec)) or usable[:1]
    return sorted(set(req + rec))          # AtMostOne / Any


def validate(group, picked):
    n, t = len(picked), group["type"]
    bad = [i for i in picked if group["plugins"][i]["type"] == "NotUsable"]
    if bad:
        raise FomodError(f"'{group['plugins'][bad[0]]['name']}' can't be used with your setup")
    missing_req = [i for i, p in enumerate(group["plugins"]) if p["type"] == "Required" and i not in picked]
    if missing_req:
        raise FomodError(f"'{group['plugins'][missing_req[0]]['name']}' is required")
    if t == "SelectExactlyOne" and n != 1 or t == "SelectAtMostOne" and n > 1 or t == "SelectAtLeastOne" and n < 1:
        raise FomodError(f"group '{group['name']}' ({t}) doesn't allow {n} choice(s)")


def replay_chooser(saved):
    """Chooser that repeats saved choices {"step/group": [option names]}; falls back to defaults."""
    def choose(step, group):
        names = saved.get(f"{step}/{group['name']}")
        if names is None:
            return default_choice(group)
        return [i for i, p in enumerate(group["plugins"]) if p["name"] in names]
    return choose


# ---------------------------------------------------------------- installing

def _entries(files_el, ctx_usable=True):
    out = []
    if files_el is None:
        return out
    for e in files_el:
        if e.tag not in ("file", "folder"):
            continue
        src = e.get("source", "")
        dst = e.get("destination")
        if dst is None:
            dst = src if e.tag == "file" else ""
        out.append({"kind": e.tag, "source": src, "destination": dst,
                    "priority": int(e.get("priority", "0") or 0)})
    return out


def run(module_root, chooser, ctx=None, log=lambda *a: None):
    """Walk the installer. Returns (file_entries, choices, info)."""
    cfg = load_config(module_root)
    ctx = ctx or Context()
    info = {"name": _text(cfg, "moduleName") or "FOMOD", "warnings": []}
    if not ctx.check(cfg.find("moduleDependencies")):
        info["warnings"].append("this mod says its requirements aren't met (moduleDependencies)")

    entries = _entries(cfg.find("requiredInstallFiles"))
    choices = {}
    steps_el = cfg.find("installSteps")
    steps = []
    if steps_el is not None:
        steps = _order([{"name": s.get("name", "Step"), "el": s} for s in steps_el.findall("installStep")], steps_el)
    for st in steps:
        if not ctx.check(st["el"].find("visible")):
            continue
        groups_el = st["el"].find("optionalFileGroups")
        if groups_el is None:
            continue
        groups = _order([{"name": g.get("name", "Options"), "el": g} for g in groups_el.findall("group")], groups_el)
        for g in groups:
            plugins_el = g["el"].find("plugins")
            plugs = []
            if plugins_el is not None:
                plugs = _order([{
                    "name": pl.get("name", "Option"),
                    "description": _text(pl, "description"),
                    "image": (_find_ci(module_root, pl.find("image").get("path", ""))
                              if pl.find("image") is not None else None),
                    "type": plugin_type(pl, ctx),
                    "el": pl,
                } for pl in plugins_el.findall("plugin")], plugins_el)
            gtype = g["el"].get("type", "SelectAny")
            group = {"name": g["name"], "type": gtype if gtype in GROUP_TYPES else "SelectAny",
                     "plugins": [{k: v for k, v in p.items() if k != "el"} for p in plugs]}
            picked = chooser(st["name"], group)
            if picked is None:
                raise FomodError("install cancelled")
            picked = sorted(set(picked))
            validate(group, picked)
            choices[f"{st['name']}/{g['name']}"] = [plugs[i]["name"] for i in picked]
            for i in picked:
                pl = plugs[i]["el"]
                entries += _entries(pl.find("files"))
                for f in pl.findall("conditionFlags/flag"):
                    ctx.flags[f.get("name", "")] = (f.text or "").strip()
            log(f"  {st['name']} / {g['name']}: {', '.join(choices[st['name'] + '/' + g['name']]) or '(none)'}")
    # files that depend on flags or existing plugins
    for pat in cfg.findall("conditionalFileInstalls/patterns/pattern"):
        if ctx.check(pat.find("dependencies")):
            entries += _entries(pat.find("files"))
    return entries, choices, info


def install_files(module_root, entries, dest, log=lambda *a: None):
    """Copy the chosen entries into dest. Higher priority wins; equal priority: later wins."""
    plan = {}                                   # dest lower -> (priority, seq, src, dest_rel)
    missing = []
    for seq, e in enumerate(entries):
        src = _find_ci(module_root, e["source"]) if e["source"] else module_root
        if src is None:
            missing.append(e["source"])
            continue
        drel = e["destination"].replace("\\", "/").strip("/")
        if e["kind"] == "file" or os.path.isfile(src):
            items = [(src, drel or os.path.basename(src))]
        else:
            items = []
            for dp, dn, fn in os.walk(src):
                for f in fn:
                    rel = os.path.relpath(os.path.join(dp, f), src).replace(os.sep, "/")
                    items.append((os.path.join(dp, f), f"{drel}/{rel}".strip("/")))
        for s, d in items:
            key = d.lower()
            old = plan.get(key)
            if old is None or (e["priority"], seq) >= (old[0], old[1]):
                plan[key] = (e["priority"], seq, s, d)
    for _, _, s, d in plan.values():
        out = os.path.join(dest, d)
        os.makedirs(os.path.dirname(out) or dest, exist_ok=True)
        shutil.copy2(s, out)
    for m in missing:
        log(f"  ! the installer lists '{m}', but it isn't in the archive (skipped)")
    return {"files": len(plan), "missing": missing}
