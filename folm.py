#!/usr/bin/env python3
"""folm - The FOLM Project command-line mod manager (v1.2.0).

Setup
  folm.py init                        find the game and its Proton prefix
Mods (in the active profile)
  folm.py install ARCHIVE [--name] [--auto]   stage a mod (FOMOD installers ask, or --auto for defaults)
  folm.py add NAME                    register a mod already in the mods folder (e.g. TTW output)
  folm.py list                        show mods in order (later mods win file conflicts)
  folm.py enable|disable NAME
  folm.py move NAME --after OTHER
  folm.py note NAME "text"            attach a note to a mod
  folm.py tag NAME TAG [TAG...]       tag a mod (e.g. fixes, weapons, ours)
  folm.py sort [--preview]            arrange mods by category (never changes who wins a conflict)
  folm.py category NAME "Category"    put a mod in a section ("auto" = let FOLM decide)
Profiles (separate setups sharing one mod library)
  folm.py profile list|create NAME [--copy-from P]|switch NAME|delete NAME
Game
  folm.py deploy                      put enabled mods into the game and set the load order
  folm.py undeploy                    take everything back out, exactly as it was
  folm.py order                       show the plugin load order (sorted with LOOT's rules)
  folm.py loot [--update]             LOOT's warnings for your setup (--update: refresh the masterlist)
  folm.py conflicts [NAME]            which mods overwrite which files, and who wins
  folm.py catch                       move files the game/tools created into the Overwrite mod
  folm.py settings                    show FOLM's settings
  folm.py set archive-invalidation on|off   loose mod files override the game's archives (default on)
  folm.py play [--no-watch]           launch through Steam; FOLM watches and writes a crash report
  folm.py crash-report                rebuild the report for the last play session (e.g. after a freeze)
Mod lists (.folmlist: which downloads to install, in what order)
  folm.py modlist check LIST [--from DIR]    which of the list's downloads are in DIR (default ~/Downloads)
  folm.py modlist install LIST [--from DIR]  install the ones that are there, in the list's order
  folm.py modlist save LIST [--name N]       save this profile as a list (names, links, settings; no files)
Making mods
  folm.py geck [--edit MOD]           open GECK with your mods; collect what you save when it closes
  folm.py keep NAME                   turn what you saved (Overwrite) into a new mod called NAME
Fallout 3 -> New Vegas converter
  folm.py convert-check PLUGIN        report everything converting this FO3 plugin needs

Edition: --edition courier (default, New Vegas/TTW) or wanderer (Fallout 3).
FOLM_HOME (default ~/Games/FOLM) holds profiles, staged mods and backups.
The app (folm_gui.py) uses the same engine: folm_core/manager.py.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from folm_core.manager import Manager, FolmError                      # noqa: E402


def cmd_init(a, m):
    r = m.init(a.game_dir, a.prefix)
    print(f"{m.edition} ready (profile {m.active!r})\n  game:   {r['game_dir']}\n"
          f"  prefix: {r['prefix']}\n  mods:   {m.mods_dir}")
    if not r["prefix_exists"]:
        print("  ! Proton prefix not found yet: launch the game once through Steam.")


def terminal_chooser(step, group):
    """Ask in the terminal. Enter = the installer's defaults."""
    from folm_core import fomod
    default = fomod.default_choice(group)
    print(f"\n[{step}] {group['name']}  ({group['type']})")
    for i, p in enumerate(group["plugins"], 1):
        mark = "*" if i - 1 in default else " "
        print(f"  {mark}{i}. {p['name']}  [{p['type']}]")
        if p["description"]:
            print("       " + p["description"].splitlines()[0][:110])
    while True:
        raw = input(f"  choose (e.g. 1 or 1,3; Enter = {','.join(str(d + 1) for d in default) or 'none'}): ").strip()
        if not raw:
            return default
        try:
            picked = [int(x) - 1 for x in raw.replace(" ", ",").split(",") if x]
            fomod.validate(group, picked)
            return picked
        except (ValueError, fomod.FomodError) as e:
            print(f"  ! {e}")


def cmd_install(a, m):
    chooser = None if a.auto else terminal_chooser
    name, r = m.install(a.archive, a.name, chooser=chooser, log=print)
    print(f"{os.path.basename(a.archive)}: {r['type']}")
    for w in r.get("warnings", []):
        print(f"  ! {w}")
    print(f"  staged as {name!r} (enabled in profile {m.active!r}). Run 'folm.py deploy'.")


def cmd_add(a, m):
    m.add_folder(a.name)
    print(f"Added {a.name!r} to profile {m.active!r} (enabled).")


def cmd_list(a, m):
    m.need()
    print(f"{m.data['game']} | profile {m.active!r} | {'deployed' if m.deployed else 'not deployed'}")
    pending = m.pending_changes()
    if pending and m.deployed:
        print("  Not in the game yet (run 'folm.py deploy', or just 'folm.py play'):")
        for p in pending:
            print(f"    • {p}")
    for i, mod in enumerate(m.mods(), 1):
        tags = f"  #{' #'.join(mod.get('tags', []))}" if mod.get("tags") else ""
        print(f"  {i:2}. [{'x' if mod['enabled'] else ' '}] {mod['name']}  ({mod.get('type', '?')}){tags}")
        if mod.get("notes"):
            print(f"        note: {mod['notes']}")
    if m.overwrite_count():
        print(f"   *. [x] {m.overwrite_name}  ({m.overwrite_count()} caught file(s), always last)")
    if not m.mods():
        print("  (no mods yet)")


def cmd_toggle(a, m, on):
    if not on:
        need = m.saves_needing(m.mod_plugins(a.name))
        if need and not a.force:
            for save, used in need:
                print(f"  ! Save '{save}' uses {', '.join(used)}")
            raise FolmError(f"{a.name!r} is used by your recent saves; removing it mid-playthrough can break "
                            "quests and scripts. Use --force to disable it anyway.")
    m.set_enabled(a.name, on)
    print(f"{'Enabled' if on else 'Disabled'} {a.name!r}. Run 'folm.py deploy' to apply.")


def cmd_move(a, m):
    m.move_after(a.name, a.after)
    cmd_list(a, m)


def cmd_note(a, m):
    m.set_note(a.name, a.text)
    print(f"Note saved for {a.name!r}.")


def cmd_tag(a, m):
    print(f"{a.name!r} tags: {', '.join(m.add_tags(a.name, a.tags))}")


def cmd_sort(a, m):
    old = [x["name"] for x in m.mods()]
    new = m.sorted_order() if a.preview else m.sort_mods()[1]
    sec = m.sections()
    last = None
    for i, n in enumerate(new, 1):
        cat = sec[n]
        if cat != last:
            print(f"  -- {cat} --")
            last = cat
        moved = "" if old.index(n) == i - 1 else f"   (was {old.index(n) + 1})"
        print(f"  {i:2}. {n}{moved}")
    print("\nPreview only; run 'folm.py sort' to apply." if a.preview else
          ("\nSorted. Run 'folm.py deploy' to apply." if new != old else "\nAlready sorted."))


def cmd_category(a, m):
    m.set_category(a.name, None if a.category.lower() == "auto" else a.category)
    print(f"{a.name!r} -> {m.category_of(m.mod(a.name))}")


def cmd_profile(a, m):
    m.need()
    if a.action == "list":
        for n in m.profiles():
            p = m.data["profiles"][n]
            on = sum(x["enabled"] for x in p["mods"])
            print(f"  {'*' if n == m.active else ' '} {n}  ({on}/{len(p['mods'])} mods enabled)")
        return
    if not a.name:
        raise FolmError("give a profile name")
    if a.action == "create":
        m.create_profile(a.name, a.copy_from)
        print(f"Created profile {a.name!r}" + (f" from {a.copy_from!r}." if a.copy_from else " (empty)."))
    elif a.action == "switch":
        r = m.switch_profile(a.name, log=print)
        print(f"Active profile: {a.name!r}")
        if r:
            print(f"Load order set: {len(r['active'])} active plugin(s) of {len(r['order'])}.")
    elif a.action == "rename":
        if not a.new_name:
            raise FolmError("give the new name: profile rename OLD NEW")
        m.rename_profile(a.name, a.new_name, log=print)
        print(f"Renamed profile {a.name!r} to {a.new_name!r}.")
    elif a.action == "delete":
        saves, kept = m.delete_profile(a.name)
        print(f"Deleted profile {a.name!r} (its mods stay in the shared library).")
        if saves:
            print(f"Its saves are still in {saves}")
        if kept:
            print(f"Files it caught are now the staged mod {kept!r}.")


def cmd_deploy(a, m):
    r = m.deploy(log=print)
    print(f"Load order set: {len(r['active'])} active plugin(s) of {len(r['order'])} (profile {m.active!r}), sorted with LOOT's rules.")
    errs = [x for x in r.get("loot", []) if x[0] in ("error", "warn")]
    if errs:
        print("LOOT says:")
        print_loot(errs)
    if r["problems"]:
        print("  Fix the problems above before playing.")
    for save, miss in r.get("save_warnings", []):
        print(f"  ! Save '{save}' needs {', '.join(miss)}, which isn't active now.")


def cmd_undeploy(a, m):
    m.undeploy(log=print)


def cmd_catch(a, m):
    n = m.catch(log=print)
    print(f"Caught {n} file(s)." if n else "Game folder is clean: nothing to catch.")


def print_loot(msgs):
    icon = {"error": "✖ ERROR", "warn": "⚠ WARN ", "handled": "✔ done ", "say": "ℹ note "}
    for sev in ("error", "warn", "handled", "say"):
        for s, plugin, text in msgs:
            if s == sev:
                print(f"  {icon[s]}  {plugin + ': ' if plugin else ''}{text}")


def cmd_order(a, m):
    rows, problems = m.plugin_order()
    for n, on, idx, _ in rows:
        print(f"  {f'{idx:02X}' if on else '--'}  {n}")
    for p in problems:
        print(f"  ! {p}")
    if m.last_loot_messages:
        print("\nLOOT says:")
        print_loot(m.last_loot_messages)


def cmd_loot(a, m):
    m.need()
    m.loot_masterlist(log=print, force=a.update)
    lc = m.loot_check()
    msgs = lc[2] if lc else []
    print(f"LOOT checked {len(m.game_view()[1])} plugins: "
          f"{sum(1 for x in msgs if x[0] == 'error')} error(s), {sum(1 for x in msgs if x[0] == 'warn')} warning(s), "
          f"{sum(1 for x in msgs if x[0] == 'say')} note(s)"
          + (f", {sum(1 for x in msgs if x[0] == 'handled')} marked as handled." if any(x[0] == 'handled' for x in msgs) else "."))
    print_loot(msgs)
    print("\nLoad-order data: LOOT masterlist (public domain, https://loot.github.io)")


def cmd_handled(a, m):
    m.need()
    if a.action == "list":
        if not m.handled():
            print(f"Nothing marked as handled in profile {m.active!r}.")
        enabled = set(m.enabled())
        for h in m.handled():
            state = "" if not h.get("by") or h["by"] in enabled else "  (that mod is off: warning is back)"
            print(f"  {h.get('plugin') or '(general)'}: {h['text']}\n      by: {h.get('by') or 'checked by you'}"
                  f"{' · ' + h['note'] if h.get('note') else ''}{state}")
        return
    if not a.plugin or not a.text:
        raise FolmError("give the plugin and (part of) the LOOT message, e.g. "
                        "handled add \"EVE FNV - ALL DLC.esp\" incompatible --by \"EVE TTW Patch\"")
    lc = m.loot_check()
    found = [(p, t.split("  [")[0]) for sev, p, t in (lc[2] if lc else [])
             if (p or "").lower() == a.plugin.lower() and a.text.lower() in t.lower()]
    if a.action == "remove":
        found = found or [(a.plugin, h["text"]) for h in m.handled()
                          if (h.get("plugin") or "").lower() == a.plugin.lower() and a.text.lower() in h["text"].lower()]
        for p, t in found:
            m.unmark_handled(p, t)
            print(f"Showing as a problem again: {p}: {t}")
        return
    if not found:
        raise FolmError("no current LOOT message matches that (see 'folm.py loot')")
    for p, t in found:
        m.mark_handled(p, t, a.by, a.note or "")
        print(f"Marked as handled: {p}: {t}" + (f" (by {a.by})" if a.by else ""))


def cmd_conflicts(a, m):
    c = m.conflicts(a.name)
    if not c:
        print("No file conflicts." + (f" ({a.name} doesn't overlap with anything)" if a.name else ""))
        return
    by_pair = {}
    for path, provs in c.items():
        by_pair.setdefault((tuple(provs[:-1]), provs[-1]), []).append(path)
    for (losers, winner), paths in sorted(by_pair.items(), key=lambda x: -len(x[1])):
        print(f"{winner}  wins over  {', '.join(losers)}  ({len(paths)} file(s))")
        for p in paths[:a.limit]:
            print(f"    {p}")
        if len(paths) > a.limit:
            print(f"    ... and {len(paths) - a.limit} more")
    print("\nLater mods win. Reorder with: folm.py move NAME --after OTHER")


def cmd_geck(a, m):
    got = m.geck(edit_mod=a.edit, log=print)
    for f in got[:20]:
        print(f"    {f}")
    if got and not a.edit:
        print("\nKeep it as a mod with:  folm.py keep \"My Mod Name\"")


def cmd_keep(a, m):
    print(f"Made mod {m.keep_as_mod(a.name)!r} (in 'Our mods'). It's enabled and deployed.")


def print_preflight(items):
    for sev, msg in items:
        print(f"  {'✖' if sev == 'error' else '!'} {msg}")


def cmd_doctor(a, m):
    from folm_core import setupcheck
    lines = setupcheck.report()
    if setupcheck.wayland():
        lines.append("ℹ Wayland session: the game runs fine, but window fixes (borderless) need X11 or XWayland.")
    print("\n".join(lines) if lines else "All the system tools FOLM uses are installed.")
    return 1 if any(i["required"] for i in setupcheck.missing()) else 0


def cmd_preflight(a, m):
    items = m.preflight()
    if not items:
        print("All checks passed. Ready to play.")
    print_preflight(items)


def cmd_health(a, m):
    from folm_core import health
    findings = health.check(m)
    icon = {"ok": "✔", "warn": "!", "error": "✖", "info": "i"}
    for area in health.AREAS:
        rows = [f for f in findings if f["area"] == area]
        if rows:
            print(area)
        for f in rows:
            print(f"  {icon[f['status']]} {f['text']}")
            if f["fix"] and f["status"] != "ok":
                print(f"      → {f['fix']}")
    print(health.summary(findings) + ".")
    return 1 if any(f["status"] == "error" for f in findings) else 0


def cmd_updates(a, m):
    from folm_core import updates
    updates.check(m, log=print)
    return 0


def cmd_requires(a, m):
    from folm_core import requires
    items = requires.check(m, online=not a.offline, only=a.mod)
    icon = {"error": "✖", "warn": "⚠", "info": "ℹ"}
    for r in items:
        print(f"  {icon[r['severity']]} {requires.describe(r)}")
    if not items:
        print("Every mod has what it needs.")
    else:
        print("✖ = the plugin itself won't run   ⚠ = its Nexus page lists it as required   ℹ = only for some setups")
    return 1 if any(r["severity"] == "error" for r in items) else 0


def cmd_play(a, m):
    pending = m.pending_changes()
    if pending and not a.no_deploy:
        print("Putting your changes in the game first:")
        for p in pending:
            print(f"  • {p}")
        cmd_deploy(a, m)
    items = m.preflight()
    if items:
        print("Before you play:")
        print_preflight(items)
        if any(sev == "error" for sev, _ in items) and not a.force:
            raise FolmError("fix the problems marked ✖, or use --force to play anyway")
    if a.no_watch:
        print(f"Launching Steam app {m.launch()}...")
        return
    r = m.play_watched(log=print)
    for f in r["findings"]:
        print(f"  * {f}")


def cmd_settings(a, m):
    m.need()
    for key, (default, label) in m.SETTINGS.items():
        v = m.setting(key)
        shown = ("on" if v else "off") if isinstance(v, bool) else (str(v) if v else "off")
        print(f"  {key.replace('_', '-'):24} {shown:4} {label}")


def cmd_set(a, m):
    m.need()
    key = a.key.replace("-", "_")
    if key not in m.SETTINGS:
        raise FolmError(f"unknown setting; choose from: {', '.join(k.replace('_', '-') for k in m.SETTINGS)}")
    v = a.value.lower()
    if isinstance(m.SETTINGS[key][0], bool):
        if v not in ("on", "off"):
            raise FolmError("use on or off")
        m.set_setting(key, v == "on")
    else:
        m.set_setting(key, 0 if v == "off" else v)
    print(f"{a.key} is now {a.value.lower()}.")
    if m.deployed:
        m.deploy(log=print)


def cmd_crash_report(a, m):
    path, crashed, findings = m.crash_report()
    print(f"{'Crash / abnormal exit' if crashed else 'No crash detected'} in the last session.")
    for f in findings:
        print(f"  * {f}")
    print(f"Report: {path}")


def cmd_convert_check(a, m):
    from folm_core import fo3convert
    rep = fo3convert.check(a.plugin)
    print(json.dumps(rep, indent=1) if a.json else fo3convert.format_report(rep))


def cmd_modlist(a, m):
    from folm_core import modlist
    m.need()
    try:
        if a.action == "save":
            path, lst, left_out = modlist.save(m, a.file, a.name)
            print(f"Saved {len(lst['mods'])} mod(s) from profile {m.active!r} to {path}")
            if left_out:
                print("  Not in the list (they didn't come from a downloaded file): " + ", ".join(left_out))
            return
        lst = modlist.load(a.file)
        folder = os.path.expanduser(a.source)
        if a.action == "check":
            rows = modlist.status(m, lst, folder)
            print(f"{lst['name']}: {len(rows)} mod(s), looking in {folder}")
            for i, r in enumerate(rows, 1):
                e = r["entry"]
                mark = {"installed": "✔ installed", "ready": "● ready", "missing": "✖ missing"}[r["state"]]
                extra = f"as {r['installed_as']!r}" if r["state"] == "installed" and r["installed_as"] != e["name"] \
                    else os.path.basename(r["file"]) if r["state"] == "ready" else (r["link"] or "")
                print(f"  {i:2}. {mark:12} {e['name']}  {extra}".rstrip())
            counts = {s: sum(r["state"] == s for r in rows) for s in ("installed", "ready", "missing")}
            print(f"{counts['ready']} ready to install, {counts['missing']} missing, {counts['installed']} already installed.")
            return 1 if counts["missing"] else 0
        chooser = None if a.auto else terminal_chooser
        done, skipped, missing, failed = modlist.install(m, lst, folder, log=print, chooser=chooser)
        print(f"Installed {len(done)}, already there {len(skipped)}, missing {len(missing)}, failed {len(failed)}.")
        for n in missing:
            print(f"  missing: {n}")
        if done:
            print("Run 'folm.py deploy' to put them in the game.")
        return 1 if failed else 0
    except modlist.ListError as e:
        raise FolmError(str(e))


def main(argv=None):
    from folm_core.version import VERSION
    p = argparse.ArgumentParser(prog="folm.py", description=f"The FOLM Project mod manager (v{VERSION})")
    p.add_argument("--edition", default="courier", choices=["courier", "wanderer"])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init"); s.add_argument("--game-dir"); s.add_argument("--prefix")
    s = sub.add_parser("install"); s.add_argument("archive"); s.add_argument("--name")
    s.add_argument("--auto", action="store_true", help="FOMOD: take the installer's default choices without asking")
    s = sub.add_parser("add"); s.add_argument("name")
    sub.add_parser("list")
    s = sub.add_parser("enable"); s.add_argument("name")
    s = sub.add_parser("disable"); s.add_argument("name")
    s.add_argument("--force", action="store_true", help="disable even if recent saves use it")
    s = sub.add_parser("move"); s.add_argument("name"); s.add_argument("--after", required=True)
    s = sub.add_parser("note"); s.add_argument("name"); s.add_argument("text")
    s = sub.add_parser("tag"); s.add_argument("name"); s.add_argument("tags", nargs="+")
    s = sub.add_parser("sort"); s.add_argument("--preview", action="store_true")
    s = sub.add_parser("category"); s.add_argument("name"); s.add_argument("category")
    s = sub.add_parser("profile"); s.add_argument("action", choices=["list", "create", "switch", "rename", "delete"])
    s.add_argument("name", nargs="?"); s.add_argument("new_name", nargs="?", help="rename: the new name")
    s.add_argument("--copy-from")
    for c in ("deploy", "undeploy", "order", "catch", "crash-report"):
        sub.add_parser(c)
    s = sub.add_parser("play"); s.add_argument("--no-watch", action="store_true")
    s.add_argument("--force", action="store_true", help="play even if the pre-Play checks find problems")
    s.add_argument("--no-deploy", action="store_true", help="don't deploy changes first")
    sub.add_parser("preflight", help="run the pre-Play checks")
    sub.add_parser("doctor", help="check this PC has the system tools FOLM uses")
    rq = sub.add_parser("requires", help="what mods need that isn't installed (plugin checks + Nexus requirement lists)")
    rq.add_argument("mod", nargs="?", help="only this mod")
    rq.add_argument("--offline", action="store_true", help="don't ask Nexus; use the saved lists")
    sub.add_parser("updates", help="check for a newer FOLM and newer files for your Nexus mods")
    sub.add_parser("settings")
    s = sub.add_parser("set"); s.add_argument("key"); s.add_argument("value")
    s = sub.add_parser("geck"); s.add_argument("--edit", metavar="MOD")
    s = sub.add_parser("keep"); s.add_argument("name")
    s = sub.add_parser("loot"); s.add_argument("--update", action="store_true")
    s = sub.add_parser("handled", help="LOOT messages you've dealt with (e.g. with a patch)")
    s.add_argument("action", choices=["list", "add", "remove"]); s.add_argument("plugin", nargs="?")
    s.add_argument("text", nargs="?", help="part of the LOOT message"); s.add_argument("--by", help="the mod that handles it")
    s.add_argument("--note")
    s = sub.add_parser("conflicts"); s.add_argument("name", nargs="?"); s.add_argument("--limit", type=int, default=5)
    s = sub.add_parser("convert-check"); s.add_argument("plugin"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("modlist", help="install a mod list from your downloads, or save this profile as one")
    s.add_argument("action", choices=["check", "install", "save"])
    s.add_argument("file", help="the .folmlist file")
    s.add_argument("--from", dest="source", default="~/Downloads", help="folder with the downloads (default ~/Downloads)")
    s.add_argument("--name", help="save: the list's name")
    s.add_argument("--auto", action="store_true", help="FOMOD: take the installer's default choices without asking")
    a = p.parse_args(argv)
    try:
        from folm_core import desktop
        from folm_core.manager import home
        desktop.retire_nexus_links(home())             # undo FOLM 1.0's Nexus sign-in (see desktop.py)
    except OSError:
        pass
    m = Manager(a.edition)
    cmds = {"init": cmd_init, "install": cmd_install, "add": cmd_add, "list": cmd_list,
            "enable": lambda a, m: cmd_toggle(a, m, True), "disable": lambda a, m: cmd_toggle(a, m, False),
            "move": cmd_move, "note": cmd_note, "tag": cmd_tag, "profile": cmd_profile,
            "sort": cmd_sort, "category": cmd_category,
            "deploy": cmd_deploy, "undeploy": cmd_undeploy, "order": cmd_order, "conflicts": cmd_conflicts,
            "catch": cmd_catch, "play": cmd_play, "preflight": cmd_preflight, "doctor": cmd_doctor, "health": cmd_health, "requires": cmd_requires, "updates": cmd_updates, "loot": cmd_loot, "handled": cmd_handled, "settings": cmd_settings, "set": cmd_set, "crash-report": cmd_crash_report, "geck": cmd_geck, "keep": cmd_keep, "convert-check": cmd_convert_check, "modlist": cmd_modlist}
    try:
        sys.exit(cmds[a.cmd](a, m) or 0)
    except FolmError as e:
        sys.exit(f"folm: {e}")


if __name__ == "__main__":
    main()
