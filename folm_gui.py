#!/usr/bin/env python3
"""FOLM - the app. A Qt window over the same engine the command line uses (folm_core/manager.py).

Run:  .venv/bin/python folm_gui.py            (FOLM_HOME env var picks another data folder)
"""

import html
import os
import re
import sys
import threading
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from PySide6.QtCore import QFileSystemWatcher, QObject, Qt, QThread, QTimer, Signal, Slot, QUrl, qVersion                  # noqa: E402
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPalette, QPixmap,  # noqa: E402
                           QShortcut)
from PySide6.QtWidgets import (                                         # noqa: E402
    QAbstractButton, QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFontComboBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QRadioButton,
    QScrollArea, QSpinBox, QTextBrowser,
    QInputDialog, QLabel, QLineEdit, QListWidget, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QSplitter, QTabWidget, QToolBar, QToolButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from folm_core.manager import CATEGORIES, EDITIONS, FolmError, Manager  # noqa: E402
from folm_core import appprefs, helpdocs, look as look_mod, version                        # noqa: E402

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


class OptimizeDialog(QDialog):
    """⚡ Optimize: the fixes for problems nearly everyone has playing these games on Linux."""

    def __init__(self, win):
        super().__init__(win)
        from folm_core import optimize
        self.win, self.optimize = win, optimize
        self.setWindowTitle("Optimize for Linux")
        self.resize(640, 480)
        lay = QVBoxLayout(self)
        intro = QLabel("Fixes for problems that happen to nearly everyone playing on Linux. Each one can be "
                       "turned off again here or in the Settings tab, and turning it off undoes it.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.boxes = {}
        for fx in optimize.check(win.m):
            box = QCheckBox(fx["name"])
            f = box.font()
            f.setBold(True)
            box.setFont(f)
            box.setChecked(fx["on"])
            box.setEnabled(fx["available"])
            why = QLabel(f"{fx['why']}<br><i>Now: {fx['state']}</i>")
            why.setWordWrap(True)
            why.setContentsMargins(24, 0, 0, 8)
            lay.addWidget(box)
            lay.addWidget(why)
            self.boxes[fx["key"]] = (box, fx)
        lay.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        rec = bb.addButton("Turn on all recommended", QDialogButtonBox.ActionRole)
        rec.clicked.connect(self.recommended)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def recommended(self):
        for box, fx in self.boxes.values():
            if fx["available"] and fx["recommended"]:
                box.setChecked(True)

    def choices(self):
        return {k: box.isChecked() for k, (box, fx) in self.boxes.items() if fx["available"]}


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
                    url = re.search(r"https?://\S+", r["fix"])
                    if url:
                        fx.setData(1, Qt.UserRole, url.group(0))
                        fx.setToolTip(1, "Double-click to open the page")
                        fx.setForeground(1, QApplication.palette().color(QPalette.Link))
                    else:
                        fx.setForeground(1, QColor("#8a8a8a"))
                    top.addChild(fx)
            top.setExpanded(worst != "ok")
        tree.itemDoubleClicked.connect(
            lambda it, _c: it.data(1, Qt.UserRole) and QDesktopServices.openUrl(QUrl(it.data(1, Qt.UserRole))))
        lay.addWidget(tree)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class ModListDialog(QDialog):
    """A mod list: which downloads are there (ticks off as they arrive), which are missing, install the rest."""
    ICON = {"installed": "✔", "ready": "●", "missing": "✖"}
    TEXT = {"installed": "Installed", "ready": "Ready", "missing": "Missing"}

    def __init__(self, win, lst, folder):
        super().__init__(win)
        self.win, self.lst, self.folder = win, lst, folder
        self.setWindowTitle(f"Mod list: {lst['name']}")
        self.resize(980, 600)
        lay = QVBoxLayout(self)
        if lst.get("about"):
            about = QLabel(lst["about"])
            about.setWordWrap(True)
            lay.addWidget(about)
        row = QHBoxLayout()
        self.where = QLabel()
        row.addWidget(self.where, 1)
        change = QPushButton("Change folder…")
        change.clicked.connect(self.change_folder)
        row.addWidget(change)
        lay.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["#", "Mod", "Status", "Download / where to get it"])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 40)
        self.tree.setColumnWidth(1, 330)
        self.tree.setColumnWidth(2, 110)
        self.tree.itemDoubleClicked.connect(self.open_row)
        lay.addWidget(self.tree)
        self.summary = QLabel()
        lay.addWidget(self.summary)
        bb = QDialogButtonBox()
        self.open_btn = bb.addButton("Open missing pages", QDialogButtonBox.ActionRole)
        self.open_btn.clicked.connect(self.open_missing)
        self.install_btn = bb.addButton("Install", QDialogButtonBox.AcceptRole)
        self.install_btn.clicked.connect(self.accept)
        bb.addButton(QDialogButtonBox.Close).clicked.connect(self.reject)
        lay.addWidget(bb)
        self.watch = QFileSystemWatcher(self)                 # tick files off as downloads finish
        self.watch.directoryChanged.connect(lambda _p: self.fill())
        self.set_folder(folder)

    def set_folder(self, folder):
        if self.watch.directories():
            self.watch.removePaths(self.watch.directories())
        self.folder = folder
        if os.path.isdir(folder):
            self.watch.addPath(folder)
        self.where.setText(f"Looking for the downloads in <b>{folder}</b> (and its subfolders). "
                           "Download with Nexus's <b>Manual download</b> button; this list updates by itself.")
        self.fill()

    def change_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Where are the downloads?", self.folder)
        if d:
            self.set_folder(d)

    def fill(self):
        from folm_core import modlist
        self.rows = modlist.status(self.win.m, self.lst, self.folder)
        self.tree.clear()
        for i, r in enumerate(self.rows, 1):
            e = r["entry"]
            where = os.path.basename(r["file"]) if r["state"] == "ready" else \
                (f"already installed as '{r['installed_as']}'" if r["state"] == "installed" else
                 f"{e['file']}  —  double-click to open {r['link']}" if r["link"] else f"{e['file']} (no link)")
            it = QTreeWidgetItem([str(i), e["name"], f"{self.ICON[r['state']]} {self.TEXT[r['state']]}", where])
            it.setForeground(2, WIN if r["state"] != "missing" else LOSE)
            tip = e["note"] or ""
            if e["remove"]:
                tip += ("\n" if tip else "") + "Left out of the install: " + ", ".join(e["remove"])
            if tip:
                for c in range(4):
                    it.setToolTip(c, tip)
            self.tree.addTopLevelItem(it)
        n = {k: sum(r["state"] == k for r in self.rows) for k in self.TEXT}
        self.summary.setText(f"{len(self.rows)} mods: {n['ready']} ready to install, {n['missing']} missing, "
                             f"{n['installed']} already installed.")
        self.install_btn.setText(f"Install {n['ready']} ready mod{'s' if n['ready'] != 1 else ''}")
        self.install_btn.setEnabled(bool(n["ready"]))
        self.open_btn.setEnabled(any(r["state"] == "missing" and r["link"] for r in self.rows))

    def open_row(self, it, _col):
        r = self.rows[int(it.text(0)) - 1]
        if r["state"] == "missing" and r["link"]:
            QDesktopServices.openUrl(QUrl(r["link"]))

    def open_missing(self):
        links = list(dict.fromkeys(r["link"] for r in self.rows if r["state"] == "missing" and r["link"]))
        for u in links[:15]:                                   # one tab per page, not a hundred at once
            QDesktopServices.openUrl(QUrl(u))


class HelpPane(QWidget):
    """A help tab: categories that open into topics on the left, the chosen topic on the right,
    and a search box that keeps only the topics mentioning every word typed."""

    def __init__(self, name, intro):
        super().__init__()
        v = QVBoxLayout(self)
        v.addWidget(QLabel(intro))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter)
        v.addWidget(self.search)
        split = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(self.show_topic)
        self.tree.itemClicked.connect(lambda it, _c: it.setExpanded(not it.isExpanded()) if it.childCount() else None)
        self.text = QTextBrowser()
        self.text.setOpenExternalLinks(True)
        split.addWidget(self.tree)
        split.addWidget(self.text)
        split.setSizes([260, 460])
        v.addWidget(split, 1)
        bold = QFont()
        bold.setBold(True)
        for cat, topics in helpdocs.read(name):
            c = QTreeWidgetItem([cat])
            c.setFont(0, bold)
            self.tree.addTopLevelItem(c)
            for title, body in topics:
                t = QTreeWidgetItem([title])
                t.setData(0, Qt.UserRole, f"## {title}\n\n{body}")
                c.addChild(t)
        self.text.setMarkdown("Pick a topic on the left.")

    def show_topic(self, it, _prev=None):
        if it is None:
            return
        md = it.data(0, Qt.UserRole)
        if md is None:                                    # a category: list what's in it
            md = f"## {it.text(0)}\n\n" + "\n".join(f"- {it.child(i).text(0)}" for i in range(it.childCount()))
        self.text.setMarkdown(md)

    def filter(self, words):
        words = words.lower().split()
        for i in range(self.tree.topLevelItemCount()):
            c = self.tree.topLevelItem(i)
            shown = 0
            for j in range(c.childCount()):
                t = c.child(j)
                hit = all(w in t.data(0, Qt.UserRole).lower() for w in words)
                t.setHidden(not hit)
                shown += hit
            c.setHidden(not shown)
            c.setExpanded(bool(words) and shown > 0)


class SaveDialog(QDialog):
    """A save's plugins, in the order it was made with: on now, installed but off, or not installed, each
    with a link to where to get it (the mod's Nexus page, LOOT's link, or a Nexus search)."""

    def __init__(self, win, r):
        super().__init__(win)
        import time
        self.setWindowTitle(os.path.splitext(r["name"])[0])
        self.resize(980, 720)
        m = win.m
        active = {p.lower() for p in r["plugins"]} - {p.lower() for p in r["missing"]}
        src = m.plugin_sources(r["plugins"])
        v = QVBoxLayout(self)
        made = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["time"]))
        n_miss = len(r["missing"])
        fits = ("It fits profile " + ", ".join(f"“{html.escape(n)}”" for n in r["fits"]) + ". ") if r["fits"] else ""
        head = QLabel(f"<b>{html.escape(os.path.splitext(r['name'])[0])}</b> — made {made}, with "
                      f"{len(r['plugins'])} plugins. Checked against profile “{html.escape(m.active)}”: "
                      + (f"<span style='color:#d9534f'><b>{n_miss} missing</b></span>. {fits}"
                         if n_miss else "<span style='color:#3fa34d'><b>all on</b></span>. ")
                      + "Click a link to open the mod's page in your browser.")
        head.setWordWrap(True)
        v.addWidget(head)
        self.only = QCheckBox(f"Show only the {n_miss} missing")
        self.only.setChecked(bool(n_miss))
        self.only.setVisible(bool(n_miss))
        self.only.toggled.connect(self.filter)
        v.addWidget(self.only)
        t = self.tree = QTreeWidget()
        t.setHeaderLabels(["#", "Plugin", "Now", "Installed as", "Where to get it"])
        t.setRootIsDecorated(False)
        t.setAlternatingRowColors(True)
        t.itemDoubleClicked.connect(lambda it, _c: it.data(4, Qt.UserRole)
                                    and QDesktopServices.openUrl(QUrl(it.data(4, Qt.UserRole))))
        red, orange = QColor("#d9534f"), LOSE
        for i, p in enumerate(r["plugins"]):
            info = src.get(p, {})
            if p.lower() in active:
                now, color = "✔ on", WIN
            elif info.get("mod"):
                now, color = "✖ off (installed)", orange
            else:
                now, color = "✖ not installed", red
            it = QTreeWidgetItem([f"{i:02X}", p, now, info.get("mod") or "", ""])
            it.setForeground(2, color)
            if p.lower() not in active:
                it.setForeground(1, color)
            it.setData(0, Qt.UserRole, p.lower() in active)
            it.setData(4, Qt.UserRole, info.get("url"))
            t.addTopLevelItem(it)
            if info.get("url"):
                lab = QLabel(f"<a href='{html.escape(info['url'], quote=True)}'>{html.escape(info['link'])}</a>")
                lab.setOpenExternalLinks(True)
                lab.setToolTip(info["url"])
                t.setItemWidget(it, 4, lab)
            elif info.get("link"):
                it.setText(4, info["link"])
                it.setForeground(4, QColor("#888"))
        for c in (0, 2, 3):
            t.resizeColumnToContents(c)
        t.header().setSectionResizeMode(1, QHeaderView.Stretch)
        v.addWidget(t, 1)
        v.addWidget(QLabel("<small>Links: the Nexus page of the mod you installed it from; otherwise LOOT's link "
                           "for that plugin; otherwise a Nexus search for its name. Double-click a row to open "
                           "its link too.</small>"))
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.filter(self.only.isChecked())

    def filter(self, only):
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            it.setHidden(bool(only) and bool(it.data(0, Qt.UserRole)))


class UpdatesDialog(QDialog):
    """Every mod in the profile, in three branches: needs an update, up to date, can't be checked; each
    with a link (its Nexus files page; otherwise a known home page, LOOT's link or a Nexus search)."""

    def __init__(self, win, r):
        super().__init__(win)
        from folm_core import updates
        folm, ferr, rows, merr = r
        self.setWindowTitle("Updates")
        self.resize(1000, 680)
        v = QVBoxLayout(self)
        if folm:
            top = (f"<b>FOLM {html.escape(folm[0])} is out</b> (you have {updates.VERSION}): "
                   f"<a href='{html.escape(folm[1], quote=True)}'>download it</a>.")
        elif ferr:
            top = f"Couldn't check for a newer FOLM ({html.escape(ferr)})."
        else:
            top = f"FOLM {updates.VERSION} is up to date."
        if merr:
            top += f"<br><span style='color:#d9534f'>Couldn't check the mods ({html.escape(merr)}).</span>"
        head = QLabel(top + "<br>Click a link to open it in your browser. To update a mod, download the newer "
                      "file and drop it on FOLM: it offers to replace the old one.")
        head.setWordWrap(True)
        head.setOpenExternalLinks(True)
        v.addWidget(head)
        t = self.tree = QTreeWidget()
        t.setHeaderLabels(["Mod", "You have", "Newer / why", "Link"])
        t.setAlternatingRowColors(True)
        t.itemDoubleClicked.connect(lambda it, _c: it.data(3, Qt.UserRole)
                                    and QDesktopServices.openUrl(QUrl(it.data(3, Qt.UserRole))))
        rows = rows or []
        groups = [("Needs an update", ("update", "old"), LOSE),
                  ("Up to date", ("current",), WIN),
                  ("Can't be checked", ("unknown",), QColor("#888"))]
        bold = QFont()
        bold.setBold(True)
        self.branches = {}
        for title, states, color in groups:
            mine = [x for x in rows if x["state"] in states]
            b = QTreeWidgetItem([f"{title} ({len(mine)})"])
            b.setFont(0, bold)
            b.setForeground(0, color)
            b.setFirstColumnSpanned(True)
            t.addTopLevelItem(b)
            self.branches[states[0]] = b
            for x in sorted(mine, key=lambda x: x["mod"].lower()):
                if x["state"] == "update":
                    what = x["new"]
                elif x["state"] == "old":
                    what = "your file is an old version on Nexus now; see the page for its replacement"
                else:
                    what = x.get("why", "")
                it = QTreeWidgetItem([x["mod"], x.get("have", ""), what, ""])
                it.setToolTip(2, what)
                it.setData(3, Qt.UserRole, x.get("url") or None)
                b.addChild(it)
                if x.get("url"):
                    lab = QLabel(f"<a href='{html.escape(x['url'], quote=True)}'>"
                                 f"{html.escape(x.get('link') or 'Open')}</a>")
                    lab.setOpenExternalLinks(True)
                    lab.setToolTip(x["url"])
                    t.setItemWidget(it, 3, lab)
            b.setExpanded(states[0] != "current" or not any(x["state"] in ("update", "old") for x in rows))
        t.header().setSectionResizeMode(0, QHeaderView.Stretch)
        t.setColumnWidth(1, 220)
        t.setColumnWidth(2, 320)
        v.addWidget(t, 1)
        v.addWidget(QLabel("<small>Nexus mods are checked by their files page (no sign-in needed). A mod can't be "
                           "checked when it didn't come from Nexus, or its download was renamed: its link still "
                           "takes you to where to look. Double-click a row to open its link too.</small>"))
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)


def _swatch(color, size=14):
    pm = QPixmap(size, size)
    pm.fill(QColor(color) if color else Qt.transparent)
    return QIcon(pm)


def _readable_on(color):
    """Black or white, whichever reads better on this color."""
    c = QColor(color)
    return QColor("#000000") if (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) > 140 else QColor("#ffffff")


def build_palette(base_palette, look, game):
    """A palette from the look: the dark or light base, then the player's own colors on top."""
    if look["base"] == "dark":
        p = QPalette()
        for role, c in ((QPalette.Window, "#2b2b2b"), (QPalette.WindowText, "#e6e6e6"), (QPalette.Base, "#1e1e1e"),
                        (QPalette.AlternateBase, "#272727"), (QPalette.Text, "#e6e6e6"), (QPalette.Button, "#353535"),
                        (QPalette.ButtonText, "#e6e6e6"), (QPalette.ToolTipBase, "#353535"),
                        (QPalette.ToolTipText, "#e6e6e6"), (QPalette.Highlight, "#3d6fb4"),
                        (QPalette.HighlightedText, "#ffffff"), (QPalette.Link, "#6ab0ff"),
                        (QPalette.PlaceholderText, "#8a8a8a"), (QPalette.BrightText, "#ff5555")):
            p.setColor(role, QColor(c))
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            p.setColor(QPalette.Disabled, role, QColor("#7a7a7a"))
    elif look["base"] == "light":
        p = QApplication.style().standardPalette()
    else:
        p = QPalette(base_palette)
    bg = look_mod.resolve(look["background"], game)
    if bg:
        c = QColor(bg)
        dark = c.lightness() < 128
        p.setColor(QPalette.Window, c)
        p.setColor(QPalette.Base, c.darker(125) if dark else c.lighter(110))
        p.setColor(QPalette.AlternateBase, c.lighter(115) if dark else c.darker(105))
        p.setColor(QPalette.Button, c.lighter(135) if dark else c.darker(108))
        p.setColor(QPalette.ToolTipBase, c.lighter(135) if dark else c.darker(108))
    text = look_mod.resolve(look["text"], game)
    if text:
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText, QPalette.ToolTipText):
            p.setColor(QPalette.Active, role, QColor(text))
            p.setColor(QPalette.Inactive, role, QColor(text))
        dim = QColor(text)
        dim.setAlpha(110)
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            p.setColor(QPalette.Disabled, role, dim)
        p.setColor(QPalette.PlaceholderText, dim)
    accent = look_mod.resolve(look["accent"], game)
    if accent:
        p.setColor(QPalette.Highlight, QColor(accent))
        p.setColor(QPalette.HighlightedText, _readable_on(accent))
        p.setColor(QPalette.Link, QColor(accent))
    return p


class PersonalizeDialog(QDialog):
    """Settings → Personalize…: FOLM's colors and font, shown live; Cancel puts the old look back.
    Every color can be a fixed one or one of the game's own (Pip-Boy, HUD…), which then follows the
    game when the player changes it there."""

    COLORS = (("text", "Text"), ("background", "Background"), ("accent", "Highlight (selected rows)"),
              ("headers", "Category names in the mod list"), ("tab", "The selected tab's name"))

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Personalize FOLM")
        self.old = dict(main.look)
        self.look = dict(main.look)
        self.game = main.game_colors()
        v = QVBoxLayout(self)
        if self.game:
            names = ", ".join(f"<span style='color:{c}'>■</span> {html.escape(n)}" for n, c in self.game.items())
            info = QLabel(f"Your game's colors (from its settings): {names}")
        else:
            info = QLabel("<small>Your game's own colors show up here once the game has been started once.</small>")
        info.setWordWrap(True)
        v.addWidget(info)
        presets = QHBoxLayout()
        presets.addWidget(QLabel("Start from:"))
        for name in look_mod.PRESETS:
            b = QPushButton(name if name != "FOLM" else "FOLM's own look")
            b.clicked.connect(lambda _=False, n=name: self.use(dict(look_mod.PRESETS[n])))
            presets.addWidget(b)
        presets.addStretch(1)
        v.addLayout(presets)
        form = QFormLayout()
        self.base = QComboBox()
        for key, label in (("system", "Like my desktop"), ("dark", "Dark"), ("light", "Light")):
            self.base.addItem(label, key)
        self.base.currentIndexChanged.connect(lambda _i: self.set("base", self.base.currentData()))
        form.addRow("Base", self.base)
        row = QHBoxLayout()
        self.font = QFontComboBox()
        self.font.currentFontChanged.connect(lambda f: self.set("font", f.family()))
        self.size = QSpinBox()
        self.size.setRange(0, 24)
        self.size.setSpecialValueText("Desktop's size")
        self.size.valueChanged.connect(lambda n: self.set("size", n))
        self.font_default = QPushButton("Desktop's font")
        self.font_default.clicked.connect(lambda: self.set("font", "", refill=True))
        row.addWidget(self.font, 1)
        row.addWidget(self.size)
        row.addWidget(self.font_default)
        form.addRow("Font", row)
        self.pickers = {}
        for key, label in self.COLORS:
            c = QComboBox()
            c.activated.connect(lambda _i, k=key: self.picked(k))
            self.pickers[key] = c
            form.addRow(label, c)
        v.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)
        self.fill()

    def fill(self):
        """Show self.look in the controls (without triggering changes)."""
        for w in [self.base, self.font, self.size] + list(self.pickers.values()):
            w.blockSignals(True)
        self.base.setCurrentIndex(max(0, self.base.findData(self.look["base"])))
        self.font.setCurrentFont(QFont(self.look["font"]) if self.look["font"] else QApplication.font())
        self.size.setValue(int(self.look["size"] or 0))
        for key, c in self.pickers.items():
            c.clear()
            c.addItem("Default", "")
            for name, color in self.game.items():
                c.addItem(_swatch(color), f"Game: {name}", f"game:{name}")
            value = self.look[key]
            if value and not value.startswith("game:"):
                c.addItem(_swatch(value), value, value)
            elif value.startswith("game:") and c.findData(value) < 0:
                c.addItem(f"Game: {value[5:]} (not set in the game)", value)
            c.addItem("Choose a color…", "pick")
            c.setCurrentIndex(max(0, c.findData(value)))
        for w in [self.base, self.font, self.size] + list(self.pickers.values()):
            w.blockSignals(False)

    def picked(self, key):
        c = self.pickers[key]
        value = c.currentData()
        if value == "pick":
            now = look_mod.resolve(self.look[key], self.game) or "#ffffff"
            chosen = QColorDialog.getColor(QColor(now), self, "Choose a color")
            if not chosen.isValid():
                self.fill()
                return
            value = chosen.name()
        self.set(key, value, refill=True)

    def set(self, key, value, refill=False):
        self.look[key] = value
        self.main.apply_look(self.look)
        if refill:
            self.fill()

    def use(self, look):
        self.look = look
        self.main.apply_look(self.look)
        self.fill()

    def reject(self):
        self.main.apply_look(self.old)
        super().reject()

    def accept(self):
        self.main.look = self.look
        look_mod.save(self.main.m_home(), self.look)
        super().accept()


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {version.VERSION} — Fallout Linux Manager")
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
        self.look = look_mod.load(self.m_home())
        self.base_palette, self.base_font = QApplication.palette(), QApplication.font()
        self.header_color, self.tab_color, self._look_now = QColor("#c9a227"), None, None
        self.undo_stack, self.redo_stack = [], []     # Ctrl+Z / Ctrl+Y: (what, Manager.snapshot())
        self.saves_cache = {}
        self._build()
        self.apply_look()
        self.refresh()
        self._start_download_watch()
        if self.m:
            self.m.steam_fixes()                     # quiet: only while Steam is closed

    # ---------------------------------------------------------------- layout
    def _build(self):
        tb = QToolBar("Main")
        self.toolbar = tb
        tb.setMovable(False)
        self.addToolBar(tb)
        logo = QLabel()
        logo.setPixmap(QPixmap(os.path.join(HERE, "assets", "folm-icon-64.png")).scaledToHeight(
            26, Qt.SmoothTransformation))
        logo.setToolTip(f"{APP_NAME} {version.VERSION}")
        logo.setContentsMargins(4, 0, 4, 0)
        tb.addWidget(logo)
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
        b = QToolButton()
        b.setText("Profiles")
        b.setToolTip("New, rename or delete a profile")
        b.setPopupMode(QToolButton.InstantPopup)
        pm = QMenu(self)
        pm.addAction("New profile…").triggered.connect(self.new_profile)
        self.rename_action = pm.addAction("Rename this profile…")
        self.rename_action.triggered.connect(self.rename_profile)
        pm.addAction("Delete a profile…").triggered.connect(self.delete_profile)
        pm.aboutToShow.connect(lambda: (self.rename_action.setText(f"Rename “{self.m.active}”…"),
                                        self.rename_action.setEnabled(self.m.active != "Default")))
        b.setMenu(pm)
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
        self.btn_play.setToolTip("Deploy if needed, run the checks, and start the game (F9)")
        self.btn_health = QPushButton("🩺 Health check")
        self.btn_health.setToolTip("Check that your mods are really working: files, plugins, and what loaded last launch")
        self.btn_health.clicked.connect(self.health_check)
        self.btn_optimize = QPushButton("⚡ Optimize")
        self.btn_optimize.setToolTip("Fixes for problems nearly everyone has playing on Linux: crackling sound, "
                                     "alt-tab, physics, CPU speed")
        self.btn_optimize.clicked.connect(self.optimize)
        for w in (self.btn_deploy, self.btn_undeploy, self.btn_play, self.btn_health, self.btn_optimize):
            tb.addWidget(w)
        tb.addSeparator()
        b = QPushButton("⟳ Refresh")
        b.setToolTip("Reload the mod list and game state (F5)")
        b.clicked.connect(self.reload)
        tb.addWidget(b)
        QShortcut(QKeySequence("F5"), self, activated=self.reload)
        QShortcut(QKeySequence("F9"), self, activated=self.play)
        QShortcut(QKeySequence.Undo, self, activated=self.undo_change)
        for keys in (QKeySequence.Redo, QKeySequence("Ctrl+Y")):
            QShortcut(keys, self, activated=self.redo_change)
        QShortcut(QKeySequence.Find, self, activated=lambda: (self.mod_filter.setFocus(),
                                                               self.mod_filter.selectAll()))

        split = QSplitter()
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(4, 4, 4, 4)
        lv.addWidget(QLabel("<b>Mods</b> — drag to reorder; lower mods win file conflicts"))
        self.mod_filter = QLineEdit()
        self.mod_filter.setPlaceholderText("Search mods (Ctrl+F): name, type, tag or note")
        self.mod_filter.setClearButtonEnabled(True)
        self.mod_filter.textChanged.connect(self.apply_mod_filter)
        lv.addWidget(self.mod_filter)
        self.mods = ModList()
        self.mods.itemChanged.connect(self.on_mod_checked)
        self.mods.order_changed.connect(self.on_reorder)
        self.mods.currentItemChanged.connect(self.on_select)
        self.mods.setContextMenuPolicy(Qt.CustomContextMenu)
        self.mods.customContextMenuRequested.connect(self.mod_menu)
        QShortcut(QKeySequence.Delete, self.mods, activated=self.remove_selected_mod,
                  context=Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Escape"), self.mod_filter, activated=self.mod_filter.clear,
                  context=Qt.WidgetShortcut)
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
        self.tabs.addTab(self._saves_tab(), "Saves")
        self.tabs.addTab(self._tools_tab(), "Tools")
        self.tabs.addTab(self._settings_tab(), "Settings")
        self.tabs.addTab(HelpPane("faq", "<b>Questions and answers</b> — open a category, then pick a question."),
                         "FAQ")
        self.tabs.addTab(HelpPane("resources", "<b>Modder resources</b> — guides, documentation and tools. "
                                  "Links open in your browser."), "Resources")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("monospace"))
        self.tabs.addTab(self.log, "Log")
        self.tabs.currentChanged.connect(lambda _i: self.color_tabs())
        self.tabs.currentChanged.connect(lambda _i: self.tabs.currentWidget() is self.saves_tab
                                         and self.refresh_saves())
        split.addWidget(self.tabs)
        split.setSizes([560, 720])
        self.setCentralWidget(split)
        self.status = QLabel()
        self.statusBar().addWidget(self.status, 1)
        self.dl_notice = QWidget()
        dh = QHBoxLayout(self.dl_notice)
        dh.setContentsMargins(0, 0, 0, 0)
        self.dl_label = QLabel()
        dh.addWidget(self.dl_label)
        self.dl_install = QPushButton("Install")
        self.dl_install.clicked.connect(self.install_new_download)
        dh.addWidget(self.dl_install)
        b = QPushButton("Not now")
        b.clicked.connect(self.dismiss_new_download)
        dh.addWidget(b)
        self.dl_notice.hide()
        self.dl_queue = []
        self.statusBar().addPermanentWidget(self.dl_notice)
        self.statusBar().addPermanentWidget(QLabel("Drop a mod file anywhere on this window to install it "))

    # ---------------------------------------------------------------- look (Settings → Personalize…)
    def m_home(self):
        from folm_core.manager import home
        return home()

    def game_colors(self):
        """The game's interface colors ({name: "#rrggbb"}), for the edition shown. {} before the game
        has made its settings file."""
        try:
            return look_mod.game_colors(os.path.join(self.m.ini_dir(), "FalloutPrefs.ini"))
        except (KeyError, OSError, TypeError):
            return {}

    def apply_look(self, look=None):
        """Put a look on the window: palette, font, category names, selected tab. Cheap when nothing
        changed, so every refresh calls it (the game's colors may have changed, or the edition)."""
        look = look or self.look
        game = self.game_colors() if any(str(v).startswith("game:") for v in look.values()) else {}
        now = (tuple(sorted(look.items())), tuple(sorted(game.items())))
        if now == self._look_now:
            return
        self._look_now = now
        app = QApplication.instance()
        app.setPalette(build_palette(self.base_palette, look, game))
        f = QFont(self.base_font)
        if look["font"]:
            f.setFamily(look["font"])
        if look["size"]:
            f.setPointSize(int(look["size"]))
        app.setFont(f)
        self.log.setFont(QFont("monospace", f.pointSize()))
        self.header_color = QColor(look_mod.resolve(look["headers"], game) or "#c9a227")
        tab = look_mod.resolve(look["tab"], game)
        self.tab_color = QColor(tab) if tab else None
        for i in range(self.mods.topLevelItemCount()):
            it = self.mods.topLevelItem(i)
            if it.data(0, Qt.UserRole) == HEADER:
                it.setForeground(0, self.header_color)
        self.color_tabs()

    def color_tabs(self):
        bar = self.tabs.tabBar()
        normal = QApplication.palette().color(QPalette.WindowText)
        for i in range(bar.count()):
            bar.setTabTextColor(i, self.tab_color if self.tab_color and i == bar.currentIndex() else normal)

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
        row = QHBoxLayout()
        row.addWidget(QLabel("<b>Updates</b> — is there a newer FOLM, or newer files for your Nexus mods?<br>"
                             "<small>Asks GitHub and Nexus only when you press the button (mod ids only, "
                             "no account).</small>"), 1)
        b = QPushButton("Check for updates")
        b.clicked.connect(self.check_updates)
        row.addWidget(b)
        v.addLayout(row)
        names = QLabel("<small>FOLM can only check a mod if its download kept the name Nexus gave it, like "
                       "<code>Example Mod-12345-1-0-1700000000.7z</code>: that name says which file you have. Mods that "
                       "were renamed or didn't come from Nexus go under <i>Can't be checked</i>, with a link to "
                       "where to look.</small>")
        names.setWordWrap(True)
        v.addWidget(names)
        self.tools_tab = w
        v.addStretch(1)
        return w

    def _settings_tab(self):
        """Settings as a tab (it was a drop-down menu on the toolbar). The checkboxes are kept in
        self.setting_actions under the same keys, so refresh() and Optimize update them as before."""
        w = QWidget()
        v = QVBoxLayout(w)
        game = QGroupBox("Game settings (this profile) — FOLM puts them into the game on Deploy")
        gv = QVBoxLayout(game)
        self.setting_actions = {}
        for key, (default, label) in Manager.SETTINGS.items():
            if key == "fps_cap":
                row = QHBoxLayout()
                row.addWidget(QLabel("FPS cap (keeps physics stable with V-Sync off):"))
                self.fps_combo = QComboBox()
                for val in (0, 60, 90, 120, 144):
                    self.fps_combo.addItem("Off" if not val else f"{val} FPS" + ("  (recommended)" if val == 120
                                                                                 else ""), val)
                self.fps_combo.setToolTip("120 is safe. Not your screen's refresh rate: with V-Sync off a cap "
                                          "at 60 on a 60 Hz screen stutters. See FAQ → Optimize.")
                self.fps_combo.activated.connect(
                    lambda i: self.change_setting("fps_cap", self.fps_combo.itemData(i)))
                row.addWidget(self.fps_combo)
                row.addStretch(1)
                gv.addLayout(row)
                continue
            box = QCheckBox(label)
            box.toggled.connect(lambda on, k=key: self.change_setting(k, on))
            gv.addWidget(box)
            self.setting_actions[key] = box
        v.addWidget(game)
        lists = QGroupBox("Mod lists")
        lh = QHBoxLayout(lists)
        for text, fn in (("Install a mod list…", self.open_mod_list),
                         ("Save this profile as a mod list…", self.save_mod_list)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            lh.addWidget(b)
        lh.addStretch(1)
        v.addWidget(lists)
        app = QGroupBox("FOLM")
        ah = QHBoxLayout(app)
        b = QPushButton("Personalize… (colors and font)")
        b.clicked.connect(lambda: PersonalizeDialog(self).exec())
        ah.addWidget(b)
        self.menu_action = QPushButton("Add FOLM to the app menu")
        self.menu_action.clicked.connect(self.add_to_app_menu)
        ah.addWidget(self.menu_action)
        ah.addStretch(1)
        v.addWidget(app)
        self.watch_box = QCheckBox("Offer to install new mod files when they appear in Downloads "
                                   "(or a library folder)")
        self.watch_box.setToolTip("FOLM only asks, at the bottom of the window; nothing is installed until "
                                  "you press Install.")
        self.watch_box.setChecked(bool(appprefs.get(self.m_home(), "watch_downloads")))
        self.watch_box.toggled.connect(self.set_watch_downloads)
        v.addWidget(self.watch_box)
        v.addStretch(1)
        self.refresh_desktop_actions()
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
            ver = f" · version {html.escape(t['version'])}" if have and t.get("version") else ""
            text = QLabel(f"<b>{t['name']}</b> — {'✅ installed' + ver if have else 'not installed'}<br>"
                          f"<small>{t['what']}" + ("" if have else f" {t['how']}")
                          + (f" <a href='{t['get']}'>Newest version</a>" if have and t["get"].startswith("http") else "")
                          + "</small>")
            text.setWordWrap(True)
            text.setOpenExternalLinks(True)
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

    def check_updates(self):
        from folm_core import updates
        self.run(updates.check_all, self.m, then=lambda r: UpdatesDialog(self, r).exec())

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
            self.undo_stack.clear()                    # changed outside this window: old steps don't fit
            self.redo_stack.clear()
            self.reload()
        self.watch()                                   # some editors replace files; re-arm the watch

    def reload(self):
        if self.jobs:
            return
        self.m.sync()
        self.refresh()

    def refresh(self):
        self.apply_look()
        with self.m.reusing_conflicts():               # one scan of the mods' files per refresh
            self._refresh()

    def _refresh(self):
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
        lms = self.setting_actions.get("low_memory_save")
        if lms:
            from folm_core import lowmemsave
            try:
                why = lowmemsave.why_not(m.edition, m.data["game_dir"], m.data_dir)
            except (KeyError, OSError):
                why = None
            label = Manager.SETTINGS["low_memory_save"][1]
            lms.setText(f"{label}  — off: {why}" if why else label)
            lms.setToolTip("At the first memory warning, the game saves itself as a new save (FOLM_LowMemory_…). "
                           + (f"Not available here: {why}. See FAQ → Essentials." if why else
                              "Start the game with ▶ Play in FOLM for this to work."))
        cap = int(m.setting("fps_cap") or 0)
        if self.fps_combo.findData(cap) < 0:            # a custom value set from the CLI
            self.fps_combo.addItem(f"{cap} FPS", cap)
        self.fps_combo.setCurrentIndex(self.fps_combo.findData(cap))
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
                h.setForeground(0, self.header_color)
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
        self.apply_mod_filter()
        if self.tabs.currentWidget() is self.saves_tab:
            QTimer.singleShot(0, self.refresh_saves)       # the profile or its plugins may have changed

        if os.path.isdir(m.data_dir):
            rows, problems = m.plugin_order()
            at_end = {p.lower() for p in m.cur.get("plugin_last", [])}
            for name, on, idx, masters in rows:
                it = QTreeWidgetItem([f"{idx:02X}" if on else "--", name + ("  ⤓" if name.lower() in at_end else ""),
                                      ", ".join(masters)])
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(1, Qt.Checked if on else Qt.Unchecked)
                it.setData(1, Qt.UserRole, name)
                it.setToolTip(1, ("⤓ kept at the end of the load order, after plugins you add later too.\n"
                                  if name.lower() in at_end else "")
                              + "Right-click to load it earlier, later or at the end.")
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
        self.rewatch_downloads()

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

    def rename_profile(self):
        old = self.m.active
        name, ok = QInputDialog.getText(self, "Rename profile", f"New name for “{old}”:", text=old)
        if not ok or not name.strip() or name.strip() == old:
            return
        self.run(self.m.rename_profile, old, name.strip(),
                 then=lambda _r: self.say(f"Renamed the profile “{old}” to “{name.strip()}”."))

    def delete_profile(self):
        names = self.m.profiles()
        if len(names) < 2:
            QMessageBox.information(self, "Delete a profile", "This is your only profile, so there's nothing to "
                                    "switch to. Make another profile first.")
            return
        name, ok = QInputDialog.getItem(self, "Delete a profile", "Which profile?", names,
                                        names.index(self.m.active), False)
        if not ok:
            return
        other = "Default" if name != "Default" and "Default" in names else next(n for n in names if n != name)
        switch = f"\n\nIt's the profile you're using, so FOLM switches to “{other}” first." if name == self.m.active else ""
        if QMessageBox.question(
                self, "Delete a profile",
                f"Delete the profile “{name}”?\n\nIts mods stay installed (other profiles can use them), its saves "
                f"stay where they are, and files it caught become the mod “Caught files from {name}”. Only its "
                f"list of mods and their order is deleted, and that can't be undone.{switch}",
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) != QMessageBox.Yes:
            return

        def deleted(r):
            saves, kept = r
            msg = f"Deleted the profile “{name}”."
            if saves:
                msg += f" Its saves are still in {saves}."
            if kept:
                msg += f" Its caught files are the mod “{kept}” (Add staged mod… to use it)."
            self.say(msg)
            QMessageBox.information(self, "Delete a profile", msg)

        def after_switch(_r=None):
            self.run(self.m.delete_profile, name, then=deleted)
        if name == self.m.active:
            self.run(self.m.switch_profile, other, then=after_switch)
        else:
            after_switch()

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
        self.remember(f"{'turning on' if on else 'turning off'} {name}")
        self.m.set_enabled(name, on)
        QTimer.singleShot(0, self.refresh)      # not inside the click/keypress: it rebuilds this very item

    def on_reorder(self):
        items = [self.mods.topLevelItem(i) for i in range(self.mods.topLevelItemCount())]
        names = [it.text(0) for it in items if not is_header(it) and it.text(0) != self.m.overwrite_name]
        self.remember("moving a mod")
        try:
            self.m.reorder(names)
        except FolmError as e:
            self.say(str(e))
        self.refresh()

    def on_plugin_checked(self, it, col):
        if self.loading or col != 1 or it.data(0, Qt.UserRole) or not (it.flags() & Qt.ItemIsUserCheckable):
            return
        name = it.data(1, Qt.UserRole) or it.text(1)
        self.remember(f"turning {'on' if it.checkState(1) == Qt.Checked else 'off'} {name}")
        self.m.set_plugin_active(name, it.checkState(1) == Qt.Checked)
        self.say(f"{'Activated' if it.checkState(1) == Qt.Checked else 'Deactivated'} {name} "
                 "(Deploy to apply).")
        QTimer.singleShot(0, self.refresh)      # not inside the click/keypress: it rebuilds this very item

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
        self.remember(f"the notes of {it.text(0)}")
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
            page = self.nexus_page(self.m.mod(name))
            if page:
                menu.addAction("Open its Nexus page", lambda: QDesktopServices.openUrl(QUrl(page)))
            src = self.m.mod(name).get("source") or ""
            if src and os.path.exists(src):
                menu.addAction("Show the downloaded file", lambda: self.open_folder(os.path.dirname(src)))
            menu.addSeparator()
            menu.addAction("Remove from this profile\tDel", lambda: self.remove_mod(name))
        menu.exec(self.mods.viewport().mapToGlobal(pos))

    # ---------------------------------------------------------------- search, undo, links
    def apply_mod_filter(self, _text=None):
        """Show only mods matching every word typed (in name, type, tags or notes). A category heading
        stays while any of its mods show. Dragging is off while searching: with mods hidden, a drop
        could land somewhere other than where it looks."""
        words = self.mod_filter.text().lower().split()
        header, any_shown = None, False
        for i in range(self.mods.topLevelItemCount()):
            it = self.mods.topLevelItem(i)
            if is_header(it):
                if header is not None:
                    header.setHidden(not any_shown)
                header, any_shown = it, False
                continue
            mod = self.m.mod(it.text(0)) if self.m.ready and it.text(0) != self.m.overwrite_name else None
            hay = " ".join([it.text(0), it.text(1), it.text(2), (mod or {}).get("notes", "")]).lower()
            show = all(w in hay for w in words)
            it.setHidden(not show)
            any_shown = any_shown or show
        if header is not None:
            header.setHidden(not any_shown)
        self.mods.setDragDropMode(QAbstractItemView.NoDragDrop if words else QAbstractItemView.InternalMove)

    def remember(self, what):
        """Call before changing the mod list: Ctrl+Z puts this state back."""
        if not self.m.ready:
            return
        self.undo_stack.append((what, self.m.snapshot()))
        del self.undo_stack[:-50]
        self.redo_stack.clear()

    def undo_change(self):
        self._step(self.undo_stack, self.redo_stack, "Undid")

    def redo_change(self):
        self._step(self.redo_stack, self.undo_stack, "Redid")

    def _step(self, source, target, verb):
        if self.jobs:
            return
        while source:
            what, snap = source.pop()
            if snap.get("profile") != self.m.active:
                continue                                # made in another profile: skip it
            try:
                before = self.m.restore(snap)
            except FolmError as e:
                self.say(str(e))
                return
            target.append((what, before))
            self.refresh()
            self.tell(f"{verb} {what}." + (" Deploy to put it in the game." if self.m.deployed else ""))
            return
        self.tell("Nothing to undo." if verb == "Undid" else "Nothing to redo.")

    def tell(self, text):
        """A short note at the bottom of the window for a few seconds (and in the Log tab)."""
        self.say(text)
        self.statusBar().showMessage(text, 6000)

    def remove_selected_mod(self):
        it = self.mods.currentItem()
        if it and not is_header(it) and it.text(0) != self.m.overwrite_name:
            self.remove_mod(it.text(0))

    def nexus_page(self, mod):
        from folm_core import requires
        i = requires.nexus_id(mod)
        if not i:
            return None
        domain = (mod.get("nexus") or {}).get("domain") or requires.GAME_DOMAIN.get(self.m.edition, "newvegas")
        return f"https://www.nexusmods.com/{domain}/mods/{i}"

    # ---------------------------------------------------------------- saves
    def _saves_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.saves_label = QLabel()
        self.saves_label.setWordWrap(True)
        v.addWidget(self.saves_label)
        self.saves_list = QTreeWidget()
        self.saves_list.setHeaderLabels(["Save", "Made", "Plugins"])
        self.saves_list.setRootIsDecorated(False)
        self.saves_list.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.saves_list.itemDoubleClicked.connect(self.show_save)
        v.addWidget(self.saves_list)
        row = QHBoxLayout()
        b = QPushButton("Open the saves folder")
        b.clicked.connect(lambda: self.open_folder(self.m.save_dir()))
        row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        self.saves_tab = w
        return w

    def refresh_saves(self):
        import time
        self.saves_list.clear()
        if not self.m.ready:
            self.saves_label.setText("Set up the game first.")
            return
        try:
            rows = self.m.saves_overview(cache=self.saves_cache)
        except (OSError, KeyError) as e:
            self.saves_label.setText(f"Couldn't read the saves: {e}")
            return
        bad = 0
        for r in rows:
            if r["plugins"] is None:
                status, color = "couldn't read it", QColor("#888")
            elif r["missing"]:
                bad += 1
                fits = (" — fits profile " + ", ".join(f"“{n}”" for n in r["fits"])) if r["fits"] else ""
                status, color = (f"✖ missing {len(r['missing'])}{fits}: {', '.join(r['missing'])}",
                                 QColor("#d9534f"))
            else:
                status, color = f"✔ all {len(r['plugins'])} plugins are on", WIN
            it = QTreeWidgetItem([os.path.splitext(r["name"])[0],
                                  time.strftime("%Y-%m-%d %H:%M", time.localtime(r["time"])), status])
            it.setForeground(2, color)
            it.setData(0, Qt.UserRole, r)
            self.saves_list.addTopLevelItem(it)
        self.saves_list.resizeColumnToContents(1)
        self.saves_label.setText(
            f"<b>Your saves, checked against profile “{html.escape(self.m.active)}”</b> — {len(rows)} save(s); "
            "every profile shares the game's Saves folder. <span style='color:#3fa34d'>Green</span>: all its "
            "plugins are on in this profile. <span style='color:#d9534f'>Red</span>: it's missing some, and "
            "loading it can break quests and scripts; pick the profile it fits, or turn those plugins on. "
            + (f"<b>{bad}</b> don't fit this profile. " if bad else "")
            + "Switching profiles or turning mods on and off updates this list. "
            "Double-click a save to see its plugins.")

    def show_save(self, it, _col=None):
        r = it.data(0, Qt.UserRole)
        if r and r["plugins"] is not None:
            SaveDialog(self, r).exec()

    # ---------------------------------------------------------------- new downloads
    def _start_download_watch(self):
        self.dl_watcher = QFileSystemWatcher(self)
        self.dl_watcher.directoryChanged.connect(lambda _p: self.dl_timer.start())
        self.dl_timer = QTimer(self)
        self.dl_timer.setSingleShot(True)
        self.dl_timer.setInterval(3000)              # let the browser finish renaming the file
        self.dl_timer.timeout.connect(self.check_new_downloads)
        self.dl_seen = set()
        self.dl_folders = []
        self.rewatch_downloads()

    def rewatch_downloads(self):
        if self.dl_watcher.directories():
            self.dl_watcher.removePaths(self.dl_watcher.directories())
        if not appprefs.get(self.m_home(), "watch_downloads"):
            self.dl_folders = []
            return
        lib = self.m.library_folders() if self.m.ready else []
        self.dl_folders = appprefs.download_folders(lib)
        appprefs.new_mod_files(self.dl_folders, self.dl_seen)  # what's there now isn't new
        if self.dl_folders:
            self.dl_watcher.addPaths(self.dl_folders)

    def set_watch_downloads(self, on):
        appprefs.set(self.m_home(), "watch_downloads", bool(on))
        self.rewatch_downloads()
        if not on:
            self.dl_queue.clear()
            self.dl_notice.hide()
        self.say("FOLM will offer to install new mod files." if on else "FOLM won't watch for new downloads.")

    def check_new_downloads(self):
        import time
        for p in appprefs.new_mod_files(self.dl_folders, self.dl_seen):
            try:
                if time.time() - os.path.getmtime(p) < 2:   # still being written: look again shortly
                    self.dl_seen.discard(p)
                    self.dl_timer.start()
                    continue
                if self.m.ready and any(k == "same" and prof == self.m.active
                                        for k, prof, _ in self.m.find_duplicates(p)):
                    continue                                  # already installed here
            except OSError:
                continue
            self.dl_queue.append(p)
        self.show_new_download()

    def show_new_download(self):
        if not self.dl_queue:
            self.dl_notice.hide()
            return
        name = os.path.basename(self.dl_queue[0])
        more = f" (+{len(self.dl_queue) - 1} more)" if len(self.dl_queue) > 1 else ""
        self.dl_label.setText(f"New download: <b>{html.escape(name)}</b>{more}")
        self.dl_notice.show()

    def install_new_download(self):
        if self.dl_queue:
            self.install(self.dl_queue.pop(0))
        self.show_new_download()

    def dismiss_new_download(self):
        if self.dl_queue:
            self.dl_queue.pop(0)
        self.show_new_download()

    def set_category(self, name, cat):
        self.remember(f"the category of {name}")
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
        self.remember("sorting the mods")
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
            self.remember(f"removing {name}")
            self.m.remove(name)
            self.refresh()
            self.tell(f"Removed {name} from this profile (Ctrl+Z puts it back).")

    def open_folder(self, path):
        if os.path.isdir(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ---------------------------------------------------------------- mod lists
    def open_mod_list(self):
        from folm_core import modlist
        start = os.path.join(HERE, "lists") if os.path.isdir(os.path.join(HERE, "lists")) else os.path.expanduser("~")
        f, _ = QFileDialog.getOpenFileName(self, "Install a mod list", start,
                                           f"FOLM mod lists (*{modlist.EXT});;All files (*)")
        if not f:
            return
        try:
            self.m.need()
            lst = modlist.load(f)
            if lst.get("edition") and lst["edition"] != self.m.edition:
                raise modlist.ListError(f"This list is for {EDITION_LABELS.get(lst['edition'], lst['edition'])}. "
                                        "Switch the edition at the top first.")
        except (modlist.ListError, FolmError) as e:
            QMessageBox.warning(self, APP_NAME, f"Can't use that list: {e}")
            return
        d = ModListDialog(self, lst, os.path.expanduser("~/Downloads"))
        if d.exec() != QDialog.Accepted:
            return

        def go(lst, folder, chooser, log=None):
            return modlist.install(self.m, lst, folder, log=log or (lambda *a: None), chooser=chooser)

        def done(r):
            installed, skipped, missing, failed = r
            self.say(f"Mod list {lst['name']}: installed {len(installed)}, already there {len(skipped)}, "
                     f"missing {len(missing)}, failed {len(failed)}.")
            msg = f"Installed {len(installed)} mod(s) from '{lst['name']}'."
            if failed:
                msg += "\n\nThese didn't install (the log says why):\n• " + "\n• ".join(failed)
            if missing:
                msg += f"\n\n{len(missing)} download(s) still missing: open the list again once you have them."
            if installed:
                msg += "\n\nDeploy to put them in the game."
            QMessageBox.information(self, APP_NAME, msg)
        self.run(go, lst, d.folder, self.bridge.chooser, then=done)

    def save_mod_list(self):
        from folm_core import modlist
        try:
            self.m.need()
        except FolmError as e:
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        f, _ = QFileDialog.getSaveFileName(self, "Save this profile as a mod list",
                                           os.path.expanduser(f"~/{self.m.active}{modlist.EXT}"),
                                           f"FOLM mod lists (*{modlist.EXT})")
        if not f:
            return
        try:
            path, lst, left_out = modlist.save(self.m, f)
        except (modlist.ListError, OSError) as e:
            QMessageBox.warning(self, APP_NAME, f"Couldn't save the list: {e}")
            return
        msg = (f"Saved {len(lst['mods'])} mods to {path}.\n\nThe list holds names, Nexus links and settings, "
               "not the mod files: whoever uses it downloads the files themselves.")
        if left_out:
            msg += "\n\nNot in the list (they didn't come from a downloaded file):\n• " + "\n• ".join(left_out)
        QMessageBox.information(self, APP_NAME, msg)

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
            self.rewatch_downloads()
            self.tabs.setCurrentIndex(3)

    def remove_lib_folder(self):
        it = self.lib_folders.currentItem()
        if it:
            self.m.remove_library_folder(it.text())
            self.refresh()
            self.rewatch_downloads()
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
        """When the window is focused, show changes made elsewhere (CLI, another window). Only if the setup
        really changed: a full refresh rescans every mod's files, which takes seconds on a slow PC, and
        doing it on every click back into the window froze FOLM ("Wait or Force Close")."""
        super().changeEvent(e)
        if e.type() == e.Type.ActivationChange and self.isActiveWindow() and not self.jobs and not self.loading:
            if self.m.sync():
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

    def optimize(self):
        if not self.m:
            return
        d = OptimizeDialog(self)
        if not d.exec():
            return
        from folm_core import optimize
        changed = optimize.apply(self.m, d.choices())
        if not changed:
            self.say("Optimize: nothing to change.")
            return
        self.say("Optimize: " + ", ".join(f"{n} {'on' if self.m.setting(k) else 'off'}"
                                         for k, n, *_ in optimize.FIXES if k in changed) + ".")
        self.loading = True
        try:
            for k, act in self.setting_actions.items():
                if k in changed and act.isCheckable():
                    act.setChecked(bool(self.m.setting(k)))
        finally:
            self.loading = False
        self.refresh()
        if self.m.deployed:
            self.run(self.m.deploy)

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
        name = it.data(1, Qt.UserRole) if it else None
        if name:                                           # a plugin row: move it in the load order
            at_end = any(p.lower() == name.lower() for p in self.m.cur.get("plugin_last", []))
            menu = QMenu(self)
            menu.addAction("Load earlier").triggered.connect(lambda: self.move_plugin(name, "earlier"))
            menu.addAction("Load later").triggered.connect(lambda: self.move_plugin(name, "later"))
            menu.addSeparator()
            if at_end:
                menu.addAction("Don't keep at the end").triggered.connect(lambda: self.move_plugin(name, "auto"))
            else:
                menu.addAction("Keep at the end of the load order").triggered.connect(
                    lambda: self.move_plugin(name, "end"))
            menu.addAction("Back to FOLM's order").triggered.connect(lambda: self.move_plugin(name, "auto"))
            menu.exec(self.plugins.viewport().mapToGlobal(pos))
            return
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

    def move_plugin(self, name, where):
        self.remember(f"move {name}")
        self.m.move_plugin(name, where)
        self.tell({"earlier": f"{name} loads earlier", "later": f"{name} loads later",
                   "end": f"{name} is kept at the end of the load order",
                   "auto": f"{name} is back in FOLM's order"}[where] + " (deploy to put it in the game).")
        self.refresh()
        for i in range(self.plugins.topLevelItemCount()):   # keep it selected, so it can be moved again
            x = self.plugins.topLevelItem(i)
            if x.data(1, Qt.UserRole) == name:
                self.plugins.setCurrentItem(x)
                break

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
    from folm_core import archive
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
