#!/usr/bin/env python3
"""folm - The FOLM Project command-line mod manager (v0.3).

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


def cmd_nexus_login(a, m):
    import getpass
    from folm_core import nexus
    from folm_core.manager import home
    print("Get your personal API key at https://www.nexusmods.com/settings/api-keys (bottom of the page).")
    key = getpass.getpass("Paste it here (it won't show): ").strip()
    if not key:
        raise FolmError("no key given")
    try:
        acc = nexus.validate(key)
    except nexus.NexusError as e:
        raise FolmError(str(e))
    nexus.save_key(home(), key, acc)
    print(f"Signed in as {acc['name']} ({'Premium' if acc['premium'] else 'free account'}). "
          "The key is stored only on this PC.")


def cmd_nexus_logout(a, m):
    from folm_core import nexus
    from folm_core.manager import home
    nexus.forget_key(home())
    print("Nexus API key removed from this PC.")


def cmd_nxm(a, m):
    from folm_core import nexus
    from folm_core.manager import home
    if not a.here and nexus.send_to_running_app(home(), a.url):
        print("Sent to the open FOLM window.")
        return
    try:
        link = nexus.parse(a.url)
    except nexus.NexusError as e:
        raise FolmError(str(e))
    if link["edition"] != m.edition:
        m = Manager(link["edition"])
    path, name, source = m.nexus_download(a.url, log=print)
    name, r = m.install(path, name, chooser=None if a.auto else terminal_chooser, log=print)
    m.set_source(name, source)
    print(f"Installed {name!r} ({r['type']}) in profile {m.active!r}. Run 'folm.py deploy'.")


def cmd_add(a, m):
    m.add_folder(a.name)
    print(f"Added {a.name!r} to profile {m.active!r} (enabled).")


def cmd_list(a, m):
    m.need()
    print(f"{m.data['game']} | profile {m.active!r} | {'deployed' if m.deployed else 'not deployed'}")
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
    from folm_core.manager import CATEGORIES
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
    from folm_core.manager import CATEGORIES
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
    elif a.action == "delete":
        m.delete_profile(a.name)
        print(f"Deleted profile {a.name!r} (its mods stay in the shared library).")


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
    icon = {"error": "✖ ERROR", "warn": "⚠ WARN ", "say": "ℹ note "}
    for sev in ("error", "warn", "say"):
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
          f"{sum(1 for x in msgs if x[0] == 'say')} note(s).")
    print_loot(msgs)
    print("\nLoad-order data: LOOT masterlist (public domain, https://loot.github.io)")


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


def cmd_play(a, m):
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


def main(argv=None):
    p = argparse.ArgumentParser(prog="folm.py", description="The FOLM Project mod manager (v0.3)")
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
    s = sub.add_parser("profile"); s.add_argument("action", choices=["list", "create", "switch", "delete"])
    s.add_argument("name", nargs="?"); s.add_argument("--copy-from")
    for c in ("deploy", "undeploy", "order", "catch", "crash-report"):
        sub.add_parser(c)
    s = sub.add_parser("play"); s.add_argument("--no-watch", action="store_true")
    s.add_argument("--force", action="store_true", help="play even if the pre-Play checks find problems")
    sub.add_parser("preflight", help="run the pre-Play checks")
    sub.add_parser("nexus-login", help="store your Nexus personal API key on this PC")
    sub.add_parser("nexus-logout", help="remove the stored Nexus API key")
    s = sub.add_parser("nxm", help="download + install a Nexus 'Mod Manager Download' link")
    s.add_argument("url"); s.add_argument("--auto", action="store_true", help="FOMOD: take the defaults")
    s.add_argument("--here", action="store_true", help="don't hand the link to an open FOLM window")
    sub.add_parser("health", help="check that mods are really working (files, plugins, last launch)")
    sub.add_parser("settings")
    s = sub.add_parser("set"); s.add_argument("key"); s.add_argument("value")
    s = sub.add_parser("geck"); s.add_argument("--edit", metavar="MOD")
    s = sub.add_parser("keep"); s.add_argument("name")
    s = sub.add_parser("loot"); s.add_argument("--update", action="store_true")
    s = sub.add_parser("conflicts"); s.add_argument("name", nargs="?"); s.add_argument("--limit", type=int, default=5)
    s = sub.add_parser("convert-check"); s.add_argument("plugin"); s.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    m = Manager(a.edition)
    cmds = {"init": cmd_init, "install": cmd_install, "add": cmd_add, "list": cmd_list,
            "enable": lambda a, m: cmd_toggle(a, m, True), "disable": lambda a, m: cmd_toggle(a, m, False),
            "move": cmd_move, "note": cmd_note, "tag": cmd_tag, "profile": cmd_profile,
            "sort": cmd_sort, "category": cmd_category,
            "deploy": cmd_deploy, "undeploy": cmd_undeploy, "order": cmd_order, "conflicts": cmd_conflicts,
            "catch": cmd_catch, "play": cmd_play, "preflight": cmd_preflight, "health": cmd_health, "nexus-login": cmd_nexus_login, "nexus-logout": cmd_nexus_logout, "nxm": cmd_nxm, "loot": cmd_loot, "settings": cmd_settings, "set": cmd_set, "crash-report": cmd_crash_report, "geck": cmd_geck, "keep": cmd_keep, "convert-check": cmd_convert_check}
    try:
        sys.exit(cmds[a.cmd](a, m) or 0)
    except FolmError as e:
        sys.exit(f"folm: {e}")


if __name__ == "__main__":
    main()
