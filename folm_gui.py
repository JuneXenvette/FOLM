#!/usr/bin/env python3
"""FOLM - the app. A Qt window over the same engine the command line uses (folm_core/manager.py).

Run:  .venv/bin/python folm_gui.py            (FOLM_HOME env var picks another data folder)
"""

import os
import re
import sys
import threading
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from PySide6.QtCore import QFileSystemWatcher, QObject, Qt, QThread, Signal, Slot, QUrl, qVersion                  # noqa: E402
from PySide6.QtGui import QActionGroup, QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPixmap, QShortcut      # noqa: E402
from PySide6.QtWidgets import (                                         # noqa: E402
    QAbstractButton, QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QHBoxLayout, QHeaderView, QRadioButton, QScrollArea,
    QInputDialog, QLabel, QLineEdit, QListWidget, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QSplitter, QTabWidget, QToolBar, QToolButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from folm_core.manager import CATEGORIES, EDITIONS, FolmError, Manager  # noqa: E402

APP_NAME = "FOLM"
EDITION_LABELS = {"courier": "Courier — New Vegas", "wanderer": "Wanderer — Fallout 3"}
WIN, LOSE = QColor("#3fa34d"), QColor("#d08a2b")
HEADER = "folm-section-header"


def is_header(it):
    return it is not None and it.data(0, Qt.UserRole) == HEADER


class Job(QThread):
    """Run one engine call off the UI thread; stream its log lines back."""
    line = Signal(str)
    done = Signal(object, object)          # result, error text

    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args = fn, args

    def run(self):
        try:
            wants = self._wants_log()
            self.done.emit(self.fn(*self.args, log=self.line.emit) if wants else self.fn(*self.args), None)
        except FolmError as e:
            self.done.emit(None, str(e))
        except Exception:
            self.done.emit(None, traceback.format_exc())

    def _wants_log(self):
        return "log" in getattr(self.fn, "__code__", type("x", (), {"co_varnames": ()})).co_varnames


class FomodDialog(QDialog):
    """One FOMOD choice group: radio buttons or checkboxes, with description and image."""
    TYPE_HINT = {"SelectExactlyOne": "Pick one.", "SelectAtMostOne": "Pick one, or none.",
                 "SelectAtLeastOne": "Pick at least one.", "SelectAll": "All of these are installed.",
                 "SelectAny": "Pick any you want."}

    def __init__(self, parent, step, group):
        super().__init__(parent)
        from folm_core import fomod
        self.group, self.fomod = group, fomod
        self.setWindowTitle(f"Install: {step}")
        self.resize(820, 520)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"<h3>{group['name']}</h3>{self.TYPE_HINT.get(group['type'], '')}"))
        body = QHBoxLayout()
        left = QVBoxLayout()
        self.buttons = QButtonGroup(self)
        self.buttons.setExclusive(group["type"] == "SelectExactlyOne")
        default = set(fomod.default_choice(group))
        for i, p in enumerate(group["plugins"]):
            label = p["name"] + ("" if p["type"] in ("Optional",) else f"   ({p['type']})")
            b = QRadioButton(label) if group["type"] == "SelectExactlyOne" else QCheckBox(label)
            b.setChecked(i in default)
            b.setEnabled(p["type"] != "NotUsable" and group["type"] != "SelectAll" and p["type"] != "Required")
            b.installEventFilter(self)
            b.setProperty("idx", i)
            self.buttons.addButton(b, i)
            left.addWidget(b)
        if group["type"] == "SelectAtMostOne":
            self.buttons.buttonToggled.connect(self._at_most_one)
        left.addStretch(1)
        body.addLayout(left, 1)
        right = QVBoxLayout()
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumHeight(200)
        right.addWidget(self.image)
        self.desc = QLabel()
        self.desc.setWordWrap(True)
        self.desc.setTextFormat(Qt.PlainText)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.desc)
        right.addWidget(sc, 1)
        body.addLayout(right, 2)
        v.addLayout(body, 1)
        self.error = QLabel()
        self.error.setStyleSheet("color: #d9534f")
        v.addWidget(self.error)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Next")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        first = next(iter(sorted(default)), 0)
        self._show(first)

    def eventFilter(self, obj, ev):
        if isinstance(obj, QAbstractButton) and ev.type() in (ev.Type.Enter, ev.Type.FocusIn):
            self._show(obj.property("idx"))
        return False

    def _show(self, i):
        if not self.group["plugins"]:
            return
        p = self.group["plugins"][i]
        self.desc.setText(p["description"] or "(no description)")
        pix = QPixmap(p["image"]) if p.get("image") else QPixmap()
        self.image.setPixmap(pix.scaled(420, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation) if not pix.isNull() else QPixmap())

    def _at_most_one(self, btn, on):
        if on:
            for b in self.buttons.buttons():
                if b is not btn and b.isChecked():
                    b.setChecked(False)

    def picked(self):
        return [self.buttons.id(b) for b in self.buttons.buttons() if b.isChecked()]

    def _ok(self):
        try:
            self.fomod.validate(self.group, self.picked())
        except self.fomod.FomodError as e:
            self.error.setText(str(e))
            return
        self.accept()


class ChoiceBridge(QObject):
    """Lets a background install job ask FOMOD questions on the UI thread and wait for the answer."""
    ask = Signal(str, object, object)

    def __init__(self, parent_window):
        super().__init__()
        self.win = parent_window
        self.ask.connect(self._ask, Qt.QueuedConnection)

    @Slot(str, object, object)
    def _ask(self, step, group, box):
        d = FomodDialog(self.win, step, group)
        box["answer"] = d.picked() if d.exec() == QDialog.Accepted else None
        box["event"].set()

    def chooser(self, step, group):              # called from the worker thread
        box = {"event": threading.Event()}
        self.ask.emit(step, group, box)
        box["event"].wait()
        return box["answer"]


class ModList(QTreeWidget):
    """Mod list: checkboxes, drag to reorder (never nests), Overwrite pinned last."""
    order_changed = Signal()

    def __init__(self):
        super().__init__()
        self.setHeaderLabels(["Mod", "Type", "Tags", "Conflicts"])
        self.setRootIsDecorated(False)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(True)
        self.header().setSectionResizeMode(0, QHeaderView.Stretch)

    def dropEvent(self, e):
        super().dropEvent(e)
        self.order_changed.emit()


class HealthDialog(QDialog):
    """Mod health check results, grouped by area."""
    ICON = {"ok": "✅", "warn": "⚠️", "error": "✖", "info": "ℹ️"}

    def __init__(self, parent, findings, summary):
        super().__init__(parent)
        from folm_core import health
        self.setWindowTitle("Mod health check")
        self.resize(900, 520)
        lay = QVBoxLayout(self)
        head = QLabel(f"<b>{summary}</b>")
        lay.addWidget(head)
        tree = QTreeWidget()
        tree.setHeaderLabels(["", "What FOLM found"])
        tree.setColumnWidth(0, 210)
        tree.setWordWrap(True)
        tree.setUniformRowHeights(False)
        for area in health.AREAS:
            rows = [f for f in findings if f["area"] == area]
            if not rows:
                continue
            worst = next((st for st in ("error", "warn", "info", "ok") if any(r["status"] == st for r in rows)), "ok")
            top = QTreeWidgetItem([f"{self.ICON[worst]}  {area}", ""])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            tree.addTopLevelItem(top)
            for r in rows:
                it = QTreeWidgetItem([self.ICON[r["status"]], r["text"]])
                it.setToolTip(1, r["text"])
                top.addChild(it)
                if r["fix"] and r["status"] != "ok":
                    fx = QTreeWidgetItem(["", "→ " + r["fix"]])
                    fx.setForeground(1, QColor("#8a8a8a"))
                    top.addChild(fx)
            top.setExpanded(worst != "ok")
        lay.addWidget(tree)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — Fallout Linux Manager")
        self.resize(1280, 780)
        self.setAcceptDrops(True)
        self.jobs = []
        self.loading = False
        self.setup_asked = set()            # editions already offered setup this session
        self.tools_told = False
        self.m = Manager("courier")
        self.bridge = ChoiceBridge(self)
        self.watcher = QFileSystemWatcher(self)       # refresh when the CLI (or anything) changes the setup
        self.watcher.fileChanged.connect(self.on_profile_file_changed)
        self.watcher.directoryChanged.connect(self.on_profile_file_changed)
        self._build()
        self.refresh()

    # ---------------------------------------------------------------- layout
    def _build(self):
        tb = QToolBar("Main")
        self.toolbar = tb
        tb.setMovable(False)
        self.addToolBar(tb)
        tb.addWidget(QLabel(" Edition "))
        self.edition = QComboBox()
        for e in EDITIONS:
            self.edition.addItem(EDITION_LABELS[e], e)
        self.edition.currentIndexChanged.connect(self.on_edition)
        tb.addWidget(self.edition)
        tb.addSeparator()
        tb.addWidget(QLabel(" Profile "))
        self.profile = QComboBox()
        self.profile.setMinimumWidth(170)
        self.profile.activated.connect(self.on_profile)
        tb.addWidget(self.profile)
        b = QPushButton("New profile…")
        b.clicked.connect(self.new_profile)
        tb.addWidget(b)
        tb.addSeparator()
        self.btn_deploy = QPushButton("Deploy")
        self.btn_deploy.setToolTip("Put enabled mods into the game and set the load order")
        self.btn_deploy.clicked.connect(lambda: self.run(self.m.deploy, then=self.after_deploy))
        self.btn_undeploy = QPushButton("Undeploy")
        self.btn_undeploy.setToolTip("Take everything back out of the game folder, exactly as it was")
        self.btn_undeploy.clicked.connect(lambda: self.run(self.m.undeploy))
        self.btn_play = QPushButton("▶  Play")
        self.btn_play.setStyleSheet("font-weight: bold; padding: 4px 16px;")
        self.btn_play.clicked.connect(self.play)
        self.btn_health = QPushButton("🩺 Health check")
        self.btn_health.setToolTip("Check that your mods are really working: files, plugins, and what loaded last launch")
        self.btn_health.clicked.connect(self.health_check)
        for w in (self.btn_deploy, self.btn_undeploy, self.btn_play, self.btn_health):
            tb.addWidget(w)
        tb.addSeparator()
        b = QPushButton("⟳ Refresh")
        b.setToolTip("Reload the mod list and game state (F5)")
        b.clicked.connect(self.reload)
        tb.addWidget(b)
        QShortcut(QKeySequence("F5"), self, activated=self.reload)
        self.settings_btn = QToolButton()
        self.settings_btn.setText("⚙ Settings")
        self.settings_btn.setPopupMode(QToolButton.InstantPopup)
        self.settings_menu = QMenu(self)
        self.setting_actions = {}
        self.fps_actions = {}
        for key, (default, label) in Manager.SETTINGS.items():
            if key == "fps_cap":
                sub = self.fps_menu = self.settings_menu.addMenu("FPS cap (keeps physics stable with V-Sync off)")
                group = self.fps_group = QActionGroup(self)
                for val in (0, 60, 90, 120, 144):
                    a = sub.addAction("Off" if not val else f"{val} FPS" + ("  (recommended)" if val == 120 else ""))
                    a.setCheckable(True)
                    group.addAction(a)
                    a.triggered.connect(lambda _c=False, v=val: self.change_setting("fps_cap", v))
                    self.fps_actions[val] = a
                continue
            act = self.settings_menu.addAction(label)
            act.setCheckable(True)
            act.toggled.connect(lambda on, k=key: self.change_setting(k, on))
            self.setting_actions[key] = act
        self.settings_menu.addSeparator()
        self.menu_action = self.settings_menu.addAction("Add FOLM to the app menu")
        self.menu_action.triggered.connect(self.add_to_app_menu)
        self.settings_menu.aboutToShow.connect(self.refresh_desktop_actions)
        self.settings_btn.setMenu(self.settings_menu)
        tb.addWidget(self.settings_btn)

        split = QSplitter()
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(4, 4, 4, 4)
        lv.addWidget(QLabel("<b>Mods</b> — drag to reorder; lower mods win file conflicts"))
        self.mods = ModList()
        self.mods.itemChanged.connect(self.on_mod_checked)
        self.mods.order_changed.connect(self.on_reorder)
        self.mods.currentItemChanged.connect(self.on_select)
        self.mods.setContextMenuPolicy(Qt.CustomContextMenu)
        self.mods.customContextMenuRequested.connect(self.mod_menu)
        lv.addWidget(self.mods)
        row = QHBoxLayout()
        for label, fn in (("Sort mods", self.sort_mods), ("Install mod…", self.pick_install),
                          ("Add staged mod…", self.add_staged), ("Catch new files", lambda: self.run(self.m.catch))):
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
        lv.addLayout(row)
        split.addWidget(left)

        self.tabs = QTabWidget()
        self.plugins = QTreeWidget()
        self.plugins.setHeaderLabels(["#", "Plugin (sorted with LOOT's rules)", "Masters"])
        self.plugins.setRootIsDecorated(False)
        self.plugins.itemChanged.connect(self.on_plugin_checked)
        self.plugins.setContextMenuPolicy(Qt.CustomContextMenu)
        self.plugins.customContextMenuRequested.connect(self.plugin_menu)
        self.plugins.itemDoubleClicked.connect(self.plugin_double_clicked)
        self.tabs.addTab(self.plugins, "Plugins")
        self.conflicts = QTreeWidget()
        self.conflicts.setHeaderLabels(["Winner  ⟵  losers", "Files"])
        self.tabs.addTab(self.conflicts, "Conflicts")
        ow = QWidget()
        ov = QVBoxLayout(ow)
        self.ow_label = QLabel()
        ov.addWidget(self.ow_label)
        self.ow_list = QListWidget()
        ov.addWidget(self.ow_list)
        b = QPushButton("Open Overwrite folder")
        b.clicked.connect(lambda: self.open_folder(self.m.overwrite_dir))
        ov.addWidget(b)
        self.tabs.addTab(ow, "Overwrite")
        self.tabs.addTab(self._library_tab(), "Library")
        self.tabs.addTab(self._notes_tab(), "Notes")
        self.tabs.addTab(self._tools_tab(), "Tools")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("monospace"))
        self.tabs.addTab(self.log, "Log")
        split.addWidget(self.tabs)
        split.setSizes([560, 720])
        self.setCentralWidget(split)
        self.status = QLabel()
        self.statusBar().addWidget(self.status, 1)
        self.statusBar().addPermanentWidget(QLabel("Drop a mod file anywhere on this window to install it "))

    def _library_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("<b>Library folders</b> — FOLM scans these and all their subfolders for mod files"))
        self.lib_folders = QListWidget()
        self.lib_folders.setMaximumHeight(90)
        v.addWidget(self.lib_folders)
        row = QHBoxLayout()
        for label, fn in (("Add folder…", self.add_lib_folder), ("Remove folder", self.remove_lib_folder),
                          ("Scan", self.scan_library)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
        v.addLayout(row)
        self.lib = QTreeWidget()
        self.lib.setHeaderLabels(["Mod file", "Type", "Plugins", "Notes"])
        self.lib.setRootIsDecorated(False)
        self.lib.itemDoubleClicked.connect(lambda it, _c: self.install(it.data(0, Qt.UserRole)))
        v.addWidget(self.lib)
        v.addWidget(QLabel("Double-click a mod file to install it."))
        return w

    def _tools_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("<b>Modding tools</b> — installed ones open with your mods loaded. "
                           "To add one, download it and drop the file on this window."))
        self.tools_box = QVBoxLayout()
        v.addLayout(self.tools_box)
        self.tools_tab = w
        v.addStretch(1)
        return w

    def refresh_tools(self):
        while self.tools_box.count():
            item = self.tools_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        try:
            status = self.m.tools_status() if self.m.ready else []
        except Exception:
            status = []
        for t in status:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(4, 6, 4, 6)
            have = bool(t["exe"])
            text = QLabel(f"<b>{t['name']}</b> — {'✅ installed' if have else 'not installed'}<br>"
                          f"<small>{t['what']}" + ("" if have else f" {t['how']}") + "</small>")
            text.setWordWrap(True)
            text.setEnabled(have)                        # greyed out when it isn't installed
            if have:
                text.setToolTip(t["exe"])
            h.addWidget(text, 1)
            if have:
                b = QPushButton("Open")
                b.clicked.connect(self.open_geck if t["id"] == "geck" else (lambda _=False, i=t["id"]: self.open_tool(i)))
            else:
                b = QPushButton("Get it…")
                b.clicked.connect(lambda _=False, u=t["get"]: QDesktopServices.openUrl(QUrl(u)))
            h.addWidget(b)
            self.tools_box.addWidget(row)

    def open_tool(self, tool_id):
        self.run(self.m.run_tool, tool_id,
                 then=lambda r: (self.say(f"Saved into the mod {r!r}." if r else "Nothing was saved."), self.refresh()))

    def _notes_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.note_title = QLabel("Select a mod to see its notes.")
        v.addWidget(self.note_title)
        v.addWidget(QLabel("Tags (comma separated)"))
        self.tags = QLineEdit()
        v.addWidget(self.tags)
        v.addWidget(QLabel("Notes"))
        self.notes = QPlainTextEdit()
        v.addWidget(self.notes)
        b = QPushButton("Save notes and tags")
        b.clicked.connect(self.save_notes)
        v.addWidget(b)
        return w

    # ---------------------------------------------------------------- refresh
    def watch(self):
        for path in (self.m.path, self.m.dir):
            if os.path.exists(path) and path not in self.watcher.files() + self.watcher.directories():
                self.watcher.addPath(path)

    def on_profile_file_changed(self, _path):
        if self.loading or self.jobs:
            return
        try:
            changed = os.stat(self.m.path).st_mtime_ns != self.m._mtime
        except FileNotFoundError:
            changed = False
        if changed:
            self.reload()
        self.watch()                                   # some editors replace files; re-arm the watch

    def reload(self):
        if self.jobs:
            return
        self.m.sync()
        self.refresh()

    def refresh(self):
        self.loading = True
        m = self.m
        self.watch()
        idx = self.edition.findData(m.edition)
        if idx != self.edition.currentIndex():
            self.edition.setCurrentIndex(idx)
        self.profile.clear()
        self.mods.clear()
        self.plugins.clear()
        self.conflicts.clear()
        self.ow_list.clear()
        self.lib_folders.clear()
        ready = m.ready
        self.refresh_tools()
        for w in (self.btn_deploy, self.btn_undeploy, self.profile):
            w.setEnabled(ready)
        self.btn_play.setEnabled(True)                      # not set up yet: Play offers the setup
        if not ready:
            self.status.setText(f"{EDITION_LABELS[m.edition]} isn't set up yet. Press ▶ Play to set it up.")
            self.loading = False
            if m.edition not in self.setup_asked:          # ask once; refocusing the window doesn't re-ask
                self.setup_asked.add(m.edition)
                self.offer_setup()
            return
        for key, act in self.setting_actions.items():
            act.blockSignals(True)
            act.setChecked(bool(m.setting(key)))
            act.blockSignals(False)
        cap = int(m.setting("fps_cap") or 0)
        if cap not in self.fps_actions:                 # a custom value set from the CLI
            a = self.fps_actions[cap] = self.fps_menu.addAction(f"{cap} FPS")
            a.setCheckable(True)
            self.fps_group.addAction(a)
            a.triggered.connect(lambda _c=False, v=cap: self.change_setting("fps_cap", v))
        for v, a in self.fps_actions.items():
            a.blockSignals(True)
            a.setChecked(v == cap)
            a.blockSignals(False)
        for p in m.profiles():
            self.profile.addItem(p)
        self.profile.setCurrentText(m.active)

        marks = m.conflict_marks()
        sections, last = m.sections(), None
        bold = QFont()
        bold.setBold(True)
        for mod in m.mods():
            if sections.get(mod["name"]) != last:
                last = sections.get(mod["name"])
                h = QTreeWidgetItem([f"── {last} ──", "", "", ""])
                h.setData(0, Qt.UserRole, HEADER)
                h.setFlags(Qt.ItemIsEnabled)
                h.setFont(0, bold)
                h.setForeground(0, QColor("#c9a227"))
                self.mods.addTopLevelItem(h)
                h.setFirstColumnSpanned(True)
            it = QTreeWidgetItem([mod["name"], mod.get("type", ""), ", ".join(mod.get("tags", [])), ""])
            it.setFlags((it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled) & ~Qt.ItemIsDropEnabled)
            it.setCheckState(0, Qt.Checked if mod["enabled"] else Qt.Unchecked)
            won, lost = marks.get(mod["name"], (0, 0))
            if won or lost:
                it.setText(3, f"wins {won} · loses {lost}")
                it.setForeground(3, WIN if lost == 0 else LOSE)
            if mod.get("notes"):
                it.setToolTip(0, mod["notes"])
            self.mods.addTopLevelItem(it)
        n_ow = m.overwrite_count()
        if n_ow:
            it = QTreeWidgetItem([m.overwrite_name, "caught files", "", f"{n_ow} file(s), always last"])
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            it.setForeground(0, QColor("#888"))
            self.mods.addTopLevelItem(it)
        for i in range(4):
            if i:
                self.mods.resizeColumnToContents(i)

        if os.path.isdir(m.data_dir):
            rows, problems = m.plugin_order()
            for name, on, idx, masters in rows:
                it = QTreeWidgetItem([f"{idx:02X}" if on else "--", name, ", ".join(masters)])
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(1, Qt.Checked if on else Qt.Unchecked)
                self.plugins.addTopLevelItem(it)
            for p in problems:
                it = QTreeWidgetItem(["⚠", p, ""])
                it.setForeground(1, QColor("#d9534f"))
                self.plugins.addTopLevelItem(it)
            loot_msgs = getattr(m, "last_loot_messages", [])
            colors = {"error": QColor("#d9534f"), "warn": QColor("#d08a2b"), "say": QColor("#8aa4c8"),
                      "handled": QColor("#7f8c7f")}
            icons = {"error": "✖", "warn": "⚠", "say": "ℹ", "handled": "✔"}
            for sev in ("error", "warn", "handled", "say"):
                for s_, plugin, text in loot_msgs:
                    if s_ != sev:
                        continue
                    it = QTreeWidgetItem([icons[sev], f"LOOT: {plugin + ' — ' if plugin else ''}{text}", ""])
                    it.setForeground(1, colors[sev])
                    it.setData(0, Qt.UserRole, (s_, plugin, text))
                    tip = text
                    if sev in ("error", "warn"):
                        tip += "\n\nRight-click → Mark as handled, if a patch or your own check has dealt with it."
                    if text.startswith("needs cleaning"):
                        tip += "\n\nRight-click → Clean it with xEdit (reversible: the original isn't changed)."
                    elif sev == "handled":
                        tip += "\n\nRight-click → Show as a problem again."
                    if self.links_in(text):
                        tip += "\n\nDouble-click to open the link; right-click to copy it."
                    it.setToolTip(1, tip)
                    if sev == "handled":
                        f = it.font(1)
                        f.setItalic(True)
                        it.setFont(1, f)
                    self.plugins.addTopLevelItem(it)
            self.loot_summary = (f" · LOOT: {sum(1 for x in loot_msgs if x[0] == 'error')} error(s), "
                                 f"{sum(1 for x in loot_msgs if x[0] == 'warn')} warning(s)") if loot_msgs else ""
            self.plugins.resizeColumnToContents(0)
            self.plugins.resizeColumnToContents(1)
        else:
            problems = []
            self.loot_summary = ""

        by_pair = {}
        for path, provs in m.conflicts().items():
            by_pair.setdefault((provs[-1], tuple(provs[:-1])), []).append(path)
        for (winner, losers), paths in sorted(by_pair.items(), key=lambda x: -len(x[1])):
            top = QTreeWidgetItem([f"{winner}  ⟵  {', '.join(losers)}", str(len(paths))])
            top.setForeground(0, WIN)
            for p in paths[:500]:
                top.addChild(QTreeWidgetItem([p, ""]))
            self.conflicts.addTopLevelItem(top)
        self.conflicts.resizeColumnToContents(0)

        files = m.overwrite_files()
        self.ow_label.setText(f"<b>{m.overwrite_name}</b>: {len(files)} file(s) the game or tools created "
                              "while this profile was deployed.")
        self.ow_list.addItems(files[:2000])
        self.lib_folders.addItems(m.library_folders())

        pending = m.pending_changes()
        if pending:
            self.btn_deploy.setText(f"Deploy  ({len(pending)} waiting)")
            self.btn_deploy.setStyleSheet("background: #b8860b; color: black; font-weight: bold; padding: 4px 10px;")
            self.btn_deploy.setToolTip("These changes aren't in the game yet:\n" + "\n".join(f"• {p}" for p in pending)
                                       + "\n\nClick to put them in the game (▶ Play also offers to).")
        else:
            self.btn_deploy.setText("Deploy")
            self.btn_deploy.setStyleSheet("")
            self.btn_deploy.setToolTip("Everything in FOLM is in the game. Deploy again any time; it's safe.")
        state = ("deployed" if m.deployed else "not deployed") + (f" · {len(pending)} change(s) not in the game yet"
                                                                   if pending and m.deployed else "")
        warn = f" · ⚠ {len(problems)} load-order problem(s)" if problems else ""
        self.status.setText(f"{m.data['game']} · profile '{m.active}' · {len(m.mods())} mod(s) · "
                            f"{state} · {len(by_pair)} conflict group(s){warn}{self.loot_summary}")
        self.btn_play.setEnabled(True)                      # Play offers to deploy first if needed
        self.loading = False
        self.on_select(self.mods.currentItem(), None)

    def offer_setup(self):
        g = EDITION_LABELS[self.m.edition]
        from folm_core import setupcheck
        lines = [] if self.tools_told else setupcheck.report()
        self.tools_told = True
        if lines:                                        # first start: say once what this PC is missing
            QMessageBox.information(self, "Before you start",
                                    "FOLM uses a few system tools. Missing on this PC:\n\n" + "\n".join(lines) +
                                    "\n\nYou can carry on; FOLM tells you again only when a mod needs one.")
        r = QMessageBox.question(self, "Set up FOLM", f"Set up {g} now?\n\nFOLM will look for the game in "
                                 "your Steam libraries. Choose No to pick the game folder yourself.",
                                 QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        try:
            if r == QMessageBox.Yes:
                self.m.init()
            elif r == QMessageBox.No:
                d = QFileDialog.getExistingDirectory(self, f"Choose the {g} game folder")
                if not d:
                    return
                self.m.init(game_dir=d)
            else:
                return
        except FolmError as e:
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        self.say(f"Set up {g}: {self.m.data['game_dir']}")
        self.refresh()

    # ---------------------------------------------------------------- jobs
    def run(self, fn, *args, then=None):
        """Run an engine call in the background with buttons locked."""
        self._busy(True)
        self.status.setText("Working…")
        job = Job(fn, *args)
        job.line.connect(self.say)

        def finished(result, err):
            self._busy(False)
            self.jobs.remove(job)
            if err:
                self.say("ERROR: " + err)
                QMessageBox.warning(self, APP_NAME, err.splitlines()[-1] if "Traceback" in err else err)
            elif then:
                then(result)
            self.refresh()
        job.done.connect(finished)
        self.jobs.append(job)
        job.start()

    def _busy(self, on):
        """Lock the main window's controls during a job, but not dialogs it opens (FOMOD questions)."""
        self.centralWidget().setEnabled(not on)
        self.toolbar.setEnabled(not on)

    def say(self, text):
        self.log.appendPlainText(text)
        if self.jobs and text.strip():
            self.status.setText(text.strip()[:220])          # progress where people look

    def after_deploy(self, r):
        if r and r["problems"]:
            self.tabs.setCurrentWidget(self.plugins)
            QMessageBox.warning(self, APP_NAME, "Deployed, but the load order has problems:\n\n" +
                                "\n".join(r["problems"][:10]))
        elif r:
            self.say(f"Ready to play: {len(r['active'])} active plugin(s).")
        for save, miss in (r or {}).get("save_warnings", []):
            self.say(f"⚠ Save '{save}' needs {', '.join(miss)}, which isn't active now.")

    # ---------------------------------------------------------------- handlers
    def on_edition(self, i):
        if self.loading:
            return
        self.m = Manager(self.edition.itemData(i))
        self.setup_asked.discard(self.m.edition)       # choosing an edition is a request to set it up
        self.refresh()

    def on_profile(self, _i):
        name = self.profile.currentText()
        if name and name != self.m.active:
            self.run(self.m.switch_profile, name)

    def new_profile(self):
        name, ok = QInputDialog.getText(self, "New profile", "Name for the new profile:")
        if not ok or not name.strip():
            return
        copy = QMessageBox.question(self, "New profile", f"Start '{name}' as a copy of '{self.m.active}'?\n\n"
                                    "No = start empty.") == QMessageBox.Yes
        try:
            self.m.create_profile(name.strip(), self.m.active if copy else None)
        except FolmError as e:
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        self.run(self.m.switch_profile, name.strip())

    def on_mod_checked(self, it, col):
        if self.loading or col != 0 or is_header(it) or it.text(0) == self.m.overwrite_name:
            return
        name, on = it.text(0), it.checkState(0) == Qt.Checked
        if not on:
            need = self.m.saves_needing(self.m.mod_plugins(name))
            if need:
                lines = "\n".join(f"• {save}: {', '.join(used)}" for save, used in need)
                ans = QMessageBox.warning(
                    self, "Your saves use this mod",
                    f"Your recent saves use {name}:\n\n{lines}\n\nRemoving a mod mid-playthrough can break "
                    "quests and scripts in those saves. Start a new game (or a new profile) to play without it.\n\n"
                    "Disable it anyway?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if ans != QMessageBox.Yes:
                    self.loading = True
                    it.setCheckState(0, Qt.Checked)
                    self.loading = False
                    return
        self.m.set_enabled(name, on)
        self.refresh()

    def on_reorder(self):
        items = [self.mods.topLevelItem(i) for i in range(self.mods.topLevelItemCount())]
        names = [it.text(0) for it in items if not is_header(it) and it.text(0) != self.m.overwrite_name]
        try:
            self.m.reorder(names)
        except FolmError as e:
            self.say(str(e))
        self.refresh()

    def on_plugin_checked(self, it, col):
        if self.loading or col != 1 or it.data(0, Qt.UserRole) or not (it.flags() & Qt.ItemIsUserCheckable):
            return
        self.m.set_plugin_active(it.text(1), it.checkState(1) == Qt.Checked)
        self.say(f"{'Activated' if it.checkState(1) == Qt.Checked else 'Deactivated'} {it.text(1)} "
                 "(Deploy to apply).")
        self.refresh()

    def on_select(self, it, _prev):
        if not it or is_header(it) or it.text(0) == self.m.overwrite_name:
            self.note_title.setText("Select a mod to see its notes.")
            self.tags.clear()
            self.notes.clear()
            return
        mod = self.m.mod(it.text(0))
        self.note_title.setText(f"<b>{mod['name']}</b>  ({mod.get('type', '?')})")
        self.tags.setText(", ".join(mod.get("tags", [])))
        self.notes.setPlainText(mod.get("notes", ""))

    def save_notes(self):
        it = self.mods.currentItem()
        if not it or is_header(it) or it.text(0) == self.m.overwrite_name:
            return
        self.m.set_note(it.text(0), self.notes.toPlainText())
        self.m.set_tags(it.text(0), self.tags.text().split(","))
        self.say(f"Saved notes for {it.text(0)}.")
        self.refresh()

    def mod_menu(self, pos):
        it = self.mods.itemAt(pos)
        if not it or is_header(it):
            return
        name = it.text(0)
        menu = QMenu(self)
        if name == self.m.overwrite_name:
            menu.addAction("Open folder", lambda: self.open_folder(self.m.overwrite_dir))
        else:
            menu.addAction("Show conflicts", lambda: self.show_conflicts_for(name))
            cats = menu.addMenu("Category")
            current = self.m.mod(name).get("category")
            auto = cats.addAction(f"Auto ({self.m.category_of(dict(self.m.mod(name), category=None))})",
                                  lambda: self.set_category(name, None))
            auto.setCheckable(True)
            auto.setChecked(current is None)
            cats.addSeparator()
            for c in CATEGORIES:
                act = cats.addAction(c, lambda c=c: self.set_category(name, c))
                act.setCheckable(True)
                act.setChecked(current == c)
            menu.addAction("Open folder", lambda: self.open_folder(os.path.join(self.m.mods_dir, name)))
            menu.addSeparator()
            menu.addAction("Remove from this profile", lambda: self.remove_mod(name))
        menu.exec(self.mods.viewport().mapToGlobal(pos))

    def set_category(self, name, cat):
        self.m.set_category(name, cat)
        self.say(f"{name}: category {cat or 'auto'}. Use Sort mods to rearrange.")
        self.refresh()

    def sort_mods(self):
        old = [x["name"] for x in self.m.mods()]
        new = self.m.sorted_order()
        if new == old:
            QMessageBox.information(self, APP_NAME, "Your mods are already sorted.")
            return
        moved = sum(1 for i, n in enumerate(new) if old[i] != n)
        if QMessageBox.question(self, "Sort mods",
                                f"Arrange your mods by category? {moved} mod(s) will move.\n\n"
                                "Sorting never changes which mod wins a file conflict.") != QMessageBox.Yes:
            return
        self.m.sort_mods()
        self.say(f"Sorted mods: {moved} moved." + (" Deploy to apply." if self.m.deployed else ""))
        self.refresh()

    def show_conflicts_for(self, name):
        self.tabs.setCurrentWidget(self.conflicts)
        for i in range(self.conflicts.topLevelItemCount()):
            it = self.conflicts.topLevelItem(i)
            it.setHidden(name not in it.text(0))

    def remove_mod(self, name):
        if QMessageBox.question(self, APP_NAME, f"Remove '{name}' from profile '{self.m.active}'?\n\n"
                                "Its files stay in the shared library; you can add it back later.") \
                == QMessageBox.Yes:
            self.m.remove(name)
            self.refresh()

    def open_folder(self, path):
        if os.path.isdir(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ---------------------------------------------------------------- install + library
    def pick_install(self):
        f, _ = QFileDialog.getOpenFileName(self, "Install a mod", os.path.expanduser("~"),
                                           "Mod files (*.7z *.zip *.rar *.fomod *.exe);;All files (*)")
        if f:
            self.install(f)

    def install(self, path):
        if not path:
            return
        from folm_core import detect
        try:
            found = detect.detect(path)                # once: the install reuses it
        except Exception:
            found = None

        def go(path, name, chooser, log=None):
            return self.m.install(path, name, chooser, log=log or (lambda *a: None), detected=found)
        if found and found.get("type") == "tool":      # xEdit / xLODGen: no mod name to ask for
            self.run(go, path, None, self.bridge.chooser, then=self._installed)
            return
        name, ok = QInputDialog.getText(self, "Install mod", "Name for this mod:", text=Manager.guess_name(path))
        if ok and name.strip():
            self.run(go, path, name.strip(), self.bridge.chooser, then=self._installed)

    def _installed(self, r):
        if r[1].get("type") == "tool":
            self.say(f"Installed the tool {r[0]}. Open it from the Tools tab.")
            self.refresh()
            self.tabs.setCurrentIndex(self.tabs.indexOf(self.tools_tab))
        else:
            self.say(f"Installed {r[0]} ({r[1]['type']}). Deploy to put it in the game.")

    def add_staged(self):
        names = self.m.staged_not_in_profile()
        if not names:
            QMessageBox.information(self, APP_NAME, "Every mod in the library is already in this profile.")
            return
        name, ok = QInputDialog.getItem(self, "Add staged mod", "Mods in the library but not in this profile:",
                                        names, 0, False)
        if ok:
            self.m.add_folder(name)
            self.refresh()

    def add_lib_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Add a library folder", os.path.expanduser("~"))
        if d:
            self.m.add_library_folder(d)
            self.refresh()
            self.tabs.setCurrentIndex(3)

    def remove_lib_folder(self):
        it = self.lib_folders.currentItem()
        if it:
            self.m.remove_library_folder(it.text())
            self.refresh()
            self.tabs.setCurrentIndex(3)

    def scan_library(self):
        def show(results):
            self.lib.clear()
            for r in results:
                it = QTreeWidgetItem([os.path.basename(r["source"]), r["type"], ", ".join(r.get("plugins", [])),
                                      "; ".join(r.get("warnings", []))[:200]])
                it.setData(0, Qt.UserRole, r["source"])
                it.setToolTip(0, r["source"])
                if r["type"] in ("unknown", "error"):
                    it.setForeground(1, QColor("#888"))
                self.lib.addTopLevelItem(it)
            for i in range(3):
                self.lib.resizeColumnToContents(i)
            self.say(f"Library scan: {len(results)} mod file(s).")
            self.tabs.setCurrentIndex(3)
        self.run(self.m.scan_library, then=show)

    def changeEvent(self, e):
        """Refresh when the window is focused, so changes made elsewhere (CLI, another window) show up."""
        super().changeEvent(e)
        if e.type() == e.Type.ActivationChange and self.isActiveWindow() and not self.jobs and not self.loading:
            self.m.sync()
            self.refresh()

    # drag & drop archives onto the window
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if p.lower().endswith((".7z", ".zip", ".rar", ".fomod", ".exe")):
                self.install(p)
                break

    def change_setting(self, key, on):
        if self.loading:
            return
        self.m.set_setting(key, on)
        shown = ("on" if on else "off") if isinstance(on, bool) else (f"{on}" if on else "off")
        self.say(f"{Manager.SETTINGS[key][1]}: {shown}.")
        if self.m.deployed:
            self.run(self.m.deploy)            # apply it right away (deploy is quick)

    def open_geck(self):
        names = [x["name"] for x in self.m.mods()]
        choice, ok = QInputDialog.getItem(self, "GECK", "What are you working on?",
                                          ["A new mod"] + [f"Edit: {n}" for n in names], 0, False)
        if not ok:
            return
        edit = choice[6:] if choice.startswith("Edit: ") else None

        def done(files):
            if edit or not files:
                return
            name, ok = QInputDialog.getText(self, "Keep your mod",
                                            f"GECK saved {len(files)} file(s). Name your new mod:", text="My Mod")
            if ok and name.strip():
                try:
                    self.m.keep_as_mod(name.strip())
                    self.say(f"Made mod {name.strip()!r}. It's enabled and deployed.")
                except FolmError as e:
                    QMessageBox.warning(self, APP_NAME, str(e))
                self.refresh()
        self.run(self.m.geck, edit, then=done)

    # ---------------------------------------------------------------- app menu
    def refresh_desktop_actions(self):
        from folm_core import desktop
        self.menu_action.setText("Update FOLM in the app menu" if desktop.in_menu() else "Add FOLM to the app menu")

    def add_to_app_menu(self):
        from folm_core import desktop
        try:
            exe = desktop.write_entries()
        except OSError as e:
            return QMessageBox.warning(self, APP_NAME, f"Couldn't add FOLM to the app menu: {e}")
        self.say(f"FOLM is in your app menu (it starts {exe}).")

    # ---------------------------------------------------------------- "Mark as handled" (LOOT messages)
    def plugin_menu(self, pos):
        it = self.plugins.itemAt(pos)
        msg = it.data(0, Qt.UserRole) if it else None
        if not msg:
            return
        sev, plugin, text = msg
        menu = QMenu(self)
        for url in self.links_in(text):                   # e.g. the page of a mod that's missing
            short = re.sub(r"^https?://(www\.)?", "", url).rstrip("/")
            menu.addAction(f"Open {short}").triggered.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            menu.addAction("Copy link").triggered.connect(lambda _=False, u=url: self.copy_link(u))
        if plugin and text.startswith("needs cleaning"):
            menu.addSeparator()
            have = any(t["id"] == "xedit" and t["exe"] for t in self.m.tools_status())
            if have:
                menu.addAction(f"Clean {plugin} with xEdit").triggered.connect(lambda: self.clean_plugin(plugin))
            else:
                menu.addAction("Get xEdit to clean it…").triggered.connect(
                    lambda: self.tabs.setCurrentIndex(self.tabs.indexOf(self.tools_tab)))
        if sev in ("error", "warn"):
            menu.addSeparator()
            menu.addAction("Mark as handled…").triggered.connect(lambda: self.mark_handled(plugin, text))
        elif sev == "handled":
            menu.addSeparator()
            menu.addAction("Show as a problem again").triggered.connect(lambda: self.unmark_handled(plugin, text))
        if menu.isEmpty():
            return
        menu.exec(self.plugins.viewport().mapToGlobal(pos))

    def clean_plugin(self, plugin):
        if QMessageBox.question(self, "Clean plugin",
                                f"Clean {plugin} with xEdit's Quick Auto Clean?\n\n"
                                "The cleaned copy becomes part of the mod 'xEdit output'. The original file "
                                "(the mod's or the game's) isn't changed, so turning 'xEdit output' off undoes it.") \
                != QMessageBox.Yes:
            return
        self.run(self.m.clean_plugin, plugin,
                 then=lambda r: (self.say(f"Cleaned {plugin}." if r else f"xEdit didn't change {plugin}."),
                                 self.refresh()))

    @staticmethod
    def links_in(text):
        seen = []
        for u in re.findall(r"https?://[^\s)\]>\"']+", text or ""):
            u = u.rstrip(".,;")
            if u not in seen:
                seen.append(u)
        return seen

    def copy_link(self, url):
        QApplication.clipboard().setText(url)
        self.say(f"Copied {url}")

    def plugin_double_clicked(self, it, _col):
        links = self.links_in((it.data(0, Qt.UserRole) or (None, None, ""))[2]) if it.data(0, Qt.UserRole) else []
        if links:
            QDesktopServices.openUrl(QUrl(links[0]))

    def mark_handled(self, plugin, text):
        d = QDialog(self)
        d.setWindowTitle("Mark as handled")
        lay = QVBoxLayout(d)
        lab = QLabel(f"<b>LOOT says:</b> {plugin + ' — ' if plugin else ''}{text}<br><br>"
                     "If a patch fixes this (or you've checked it yourself), FOLM stops treating it as a problem. "
                     "If you pick the patch here and it's ever turned off or removed, the warning comes back.")
        lab.setWordWrap(True)
        lay.addWidget(lab)
        lay.addWidget(QLabel("What handles it?"))
        by = QComboBox()
        by.addItem("Nothing specific (I checked it myself)", None)
        names = [x["name"] for x in self.m.mods() if x.get("enabled")]
        filler = {"esp", "esm", "esl", "all", "dlc", "fnv", "the", "and", "mod", "version"}
        words = set(re.findall(r"[a-z]{3,}", (plugin or "").lower())) - filler
        guess = 0
        for i, n in enumerate(names, 1):
            by.addItem(n, n)
            name_words = set(re.findall(r"[a-z0-9]+", n.lower()))
            if name_words & {"patch", "fix", "compat", "compatible", "ttw", "lite"} and name_words & words:
                guess = i
        by.setCurrentIndex(guess)
        lay.addWidget(by)
        lay.addWidget(QLabel("Note (optional):"))
        note = QLineEdit()
        note.setPlaceholderText("e.g. EVE - TTW patch from the TTW Discord")
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Mark as handled")
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)
        d.resize(560, 0)
        if d.exec() != QDialog.Accepted:
            return
        try:
            self.m.mark_handled(plugin, text, by.currentData(), note.text())
        except FolmError as e:
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        self.say(f"Marked as handled: {plugin} — {text.split('  [')[0]}"
                 + (f" (by {by.currentData()})" if by.currentData() else ""))
        self.refresh()

    def unmark_handled(self, plugin, text):
        self.m.unmark_handled(plugin, text)
        self.say(f"Showing as a problem again: {plugin} — {text.split('  [')[0]}")
        self.refresh()

    def health_check(self):
        from folm_core import health

        def done(findings):
            if findings is None:
                return
            summ = health.summary(findings)
            self.say(f"Health check: {summ}.")
            HealthDialog(self, findings, summ).exec()
        self.run(lambda: health.check(self.m), then=done)

    def play(self):
        """Play: first make sure the game has everything ticked in FOLM (deploy if not), then check, then launch."""
        if not self.m.ready:
            self.offer_setup()
            return
        try:
            pending = self.m.pending_changes()
        except FolmError as e:
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        if not pending:
            return self._play_checked()
        box = QMessageBox(self)
        box.setWindowTitle("Put your changes in the game?")
        box.setIcon(QMessageBox.Question)
        box.setText("Some changes in FOLM aren't in the game yet:\n\n" +
                    "\n".join(f"• {p}" for p in pending[:8]) + (f"\n• …and {len(pending) - 8} more" if len(pending) > 8 else ""))
        box.setInformativeText("FOLM can deploy them now (copy your mods into the game and set the load order). "
                               "It only takes a moment and can be undone with Undeploy.")
        go = box.addButton("Deploy and Play", QMessageBox.AcceptRole)
        without = box.addButton("Play without them", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(go)
        box.exec()
        if box.clickedButton() is go:
            def deployed(r):
                if r is None:
                    return
                for save, miss in r.get("save_warnings", []):
                    self.say(f"⚠ Save '{save}' needs {', '.join(miss)}, which isn't active now.")
                self.say(f"Deployed: {len(r['active'])} active plugin(s). Starting the game…")
                self._play_checked()
            self.run(self.m.deploy, then=deployed)
        elif box.clickedButton() is without:
            self._play_checked(skip_deploy_note=True)

    def _play_checked(self, skip_deploy_note=False):
        try:
            items = self.m.preflight()
        except FolmError as e:
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        if skip_deploy_note:
            items = [i for i in items if "aren't deployed" not in i[1]]
        if items:
            errors = any(sev == "error" for sev, _ in items)
            box = QMessageBox(self)
            box.setWindowTitle("Before you play")
            box.setIcon(QMessageBox.Warning if errors else QMessageBox.Information)
            box.setText(("FOLM found problems that will probably stop the game working:"
                         if errors else "A few things to know before you play:") + "\n\n" +
                        "\n".join(f"{'✖' if sev == 'error' else '•'} {msg}" for sev, msg in items[:8]))
            go = box.addButton("Play anyway", QMessageBox.AcceptRole)
            box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(QMessageBox.Cancel if errors else go)
            box.exec()
            if box.clickedButton() is not go:
                return

        def done(r):
            if not r or not r["crashed"]:
                return
            box = QMessageBox(self)
            box.setWindowTitle("The game crashed")
            box.setIcon(QMessageBox.Warning)
            box.setText("FOLM detected a crash or abnormal exit. What it found:\n\n" +
                        "\n".join(f"• {f}" for f in r["findings"][:6]))
            box.setInformativeText("The full report is saved on your PC (nothing is uploaded).")
            open_btn = box.addButton("Open report", QMessageBox.ActionRole)
            box.addButton(QMessageBox.Close)
            box.exec()
            if box.clickedButton() is open_btn:
                QDesktopServices.openUrl(QUrl.fromLocalFile(r["report"]))
        self.run(self.m.play_watched, then=done)


def install_error_reporter():
    """Errors in FOLM itself become a saved report instead of vanishing."""
    from folm_core import crash
    from folm_core.manager import home as folm_home

    def hook(t, e, tb):
        path = crash.app_error_report(folm_home(), t, e, tb)
        sys.__excepthook__(t, e, tb)
        try:
            QMessageBox.critical(None, APP_NAME, f"FOLM hit an error. A report was saved:\n{path}")
        except Exception:
            pass
    sys.excepthook = hook


def self_test():
    """For the AppImage build: Qt starts, FOLM's code loads, the bundled 7-Zip runs. Prints and exits."""
    import importlib
    import subprocess
    for mod in ("manager", "desktop", "detect", "fomod", "wintool", "tools"):
        importlib.import_module("folm_core." + mod)
    from folm_core import archive, version
    app = QApplication(sys.argv[:1])
    sz = archive.seven_zip()
    if not sz:
        raise SystemExit("self-test: no 7-Zip")
    ver = subprocess.run([sz, "i"], capture_output=True, text=True).stdout.splitlines()
    print(f"FOLM {version.VERSION}: Qt {qVersion()} ({app.platformName()}), Python {sys.version.split()[0]}, "
          f"{next((v.strip() for v in ver if v.strip().startswith('7-Zip')), sz)}")


def main():
    if "--self-test" in sys.argv:
        return self_test()
    install_error_reporter()
    try:
        from folm_core import desktop
        from folm_core.manager import home as folm_home
        desktop.refresh()                  # a moved or newer AppImage: keep the app menu entry pointing here
        desktop.retire_nexus_links(folm_home())
    except OSError:
        pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    icon = QIcon()
    for size in (48, 64, 128, 256, 512):                                   # FOLM's own logo (assets/)
        icon.addFile(os.path.join(HERE, "assets", f"folm-icon-{size}.png"))
    app.setWindowIcon(icon)
    app.setDesktopFileName("folm")
    w = Main()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
