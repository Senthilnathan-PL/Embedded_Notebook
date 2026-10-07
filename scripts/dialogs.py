"""
FindBar, SourceDialog, ToolchainManagerDialog, LibraryManagerDialog, and BoardsManagerDialog.
"""
from html import escape
import os
import re
import shutil
from pathlib import Path

from PySide6.QtCore import (
    QEvent, QPointF, QRect, QSettings, QSize, QThread, QTimer, Qt, Signal,
)
from PySide6.QtGui import (
    QAction, QColor, QFont, QIcon, QKeySequence, QPainter, QPalette, QPen, QPixmap, QShortcut,
    QTextCharFormat, QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QProgressBar, QScrollArea, QSplitter, QTabWidget,
    QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

import scripts.toolchain as tc
from scripts.common import qt_pos_fn
from scripts.editor import CodeEditor, CppHighlighter
from scripts.cells import replace_in_document, apply_find_highlights, CodeCell
from scripts.theme import (
    ACCENT_TEXT, BAR, BG, BORDER, CURRENT_THEME, DIS_BORDER, DIS_FG, DIS_ROUND,
    FAINT, FIND_ALL, FIND_CUR, FIND_FG, HOVER1, HOVER2, LOG_BG, LOG_FG, MUTED,
    ORANGE, RUN_ACCENT, RUN_GREEN, SCROLL, SEL, SURFACE, TEAL, TEAL_DARK, TEAL_HOVER,
    TEXT, THEMES, WARN, make_icon,
)

class FindBar(QWidget):
    """Find / Replace across every cell of the notebook (source text only - never titles,
    dependencies, metadata or outputs)."""

    def __init__(self, notebook):
        super().__init__()
        self.setObjectName("findbar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.nb = notebook
        self.matches = []            # [(cell, start, end)] in notebook order
        self.cur = -1
        self._lit = []               # cells that currently show highlights
        self._busy = False

        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Find")
        self.rep_edit = QLineEdit()
        self.rep_edit.setPlaceholderText("Replace with")
        self.count = QLabel("")
        self.count.setMinimumWidth(90)
        prev_b, next_b = QPushButton("\u25b2"), QPushButton("\u25bc")
        for b, tip in ((prev_b, "Previous match (Shift+F3)"), (next_b, "Next match (F3)")):
            b.setObjectName("move")
            b.setFixedWidth(28)
            b.setToolTip(tip)
        prev_b.clicked.connect(lambda: self.step(-1))
        next_b.clicked.connect(lambda: self.step(+1))
        self.case_cb = QCheckBox("Match case")
        self.word_cb = QCheckBox("Whole word")
        self.toggle_b = QPushButton("Replace \u25be")
        self.toggle_b.setObjectName("quiet")
        self.toggle_b.clicked.connect(lambda: self.rep_row.setVisible(not self.rep_row.isVisible()))
        close_b = QPushButton("\u2715")
        close_b.setObjectName("move")
        close_b.setFixedWidth(28)
        close_b.setToolTip("Close (Esc)")
        close_b.clicked.connect(self.close_bar)

        row1 = QHBoxLayout()
        row1.addWidget(self.find_edit, 1)
        row1.addWidget(prev_b)
        row1.addWidget(next_b)
        row1.addWidget(self.count)
        row1.addWidget(self.case_cb)
        row1.addWidget(self.word_cb)
        row1.addWidget(self.toggle_b)
        row1.addWidget(close_b)

        rep_b, all_b = QPushButton("Replace"), QPushButton("Replace All")
        rep_b.clicked.connect(self.replace_current)
        all_b.clicked.connect(self.replace_all)
        self.rep_row = QWidget()
        row2 = QHBoxLayout(self.rep_row)
        row2.setContentsMargins(0, 0, 0, 0)
        row2.addWidget(self.rep_edit, 1)
        row2.addWidget(rep_b)
        row2.addWidget(all_b)
        row2.addSpacing(120)
        self.rep_row.hide()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(4)
        lay.addLayout(row1)
        lay.addWidget(self.rep_row)

        self.find_edit.textChanged.connect(lambda _t: self.refresh(reveal="soft"))
        self.find_edit.returnPressed.connect(
            lambda: self.step(-1 if QApplication.keyboardModifiers() & Qt.ShiftModifier else 1))
        self.rep_edit.returnPressed.connect(self.replace_current)
        self.case_cb.toggled.connect(lambda _c: self.refresh())
        self.word_cb.toggled.connect(lambda _c: self.refresh())
        QShortcut(QKeySequence("Esc"), self, activated=self.close_bar,
                  context=Qt.WidgetWithChildrenShortcut)

        # keep matches current while the person edits cells with the bar open
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(lambda: self.refresh(anchor=self._key()))
        notebook.modified.connect(self._on_modified)
        self.hide()

    # ---- opening / closing -------------------------------------------------
    def open(self, replace=False):
        fw = QApplication.focusWidget()
        if isinstance(fw, (QPlainTextEdit, QTextEdit)) and fw.textCursor().hasSelection():
            sel = fw.textCursor().selectedText()
            if sel and "\u2029" not in sel and len(sel) < 200:
                self.find_edit.setText(sel)
        if replace:
            self.rep_row.show()
        self.show()
        self.find_edit.setFocus()
        self.find_edit.selectAll()
        self.refresh()

    def close_bar(self):
        self.hide()
        self._clear_highlights()
        self.matches, self.cur = [], -1
        if self.nb.current is not None:
            self.nb.current.editor.setFocus()

    # ---- searching -----------------------------------------------------------
    def _regex(self):
        q = self.find_edit.text()
        if not q:
            return None
        pat = re.escape(q)
        if self.word_cb.isChecked():
            pat = rf"(?<!\w){pat}(?!\w)"
        return re.compile(pat, 0 if self.case_cb.isChecked() else re.IGNORECASE)

    def collect(self):
        rx = self._regex()
        out = []
        if rx is None:
            return out
        for cell in self.nb.cells:
            for m in rx.finditer(cell.find_text()):
                if m.end() > m.start():
                    out.append((cell, m.start(), m.end()))
        return out

    def _key(self):
        if 0 <= self.cur < len(self.matches):
            return (self.matches[self.cur][0], self.matches[self.cur][1])
        return None

    def _index_from(self, anchor):
        """First match at/after anchor (cell, offset), wrapping to the first match."""
        if anchor is None or anchor[0] not in self.nb.cells:
            return 0
        order = {id(c): i for i, c in enumerate(self.nb.cells)}
        pos = (order[id(anchor[0])], anchor[1])
        for i, (cell, a, _b) in enumerate(self.matches):
            if (order[id(cell)], a) >= pos:
                return i
        return 0

    def _caret_anchor(self):
        cell = self.nb.current
        if cell is None:
            return None
        return (cell, cell.editor.textCursor().selectionStart())

    def refresh(self, anchor="caret", reveal=False):
        self.matches = self.collect()
        if not self.matches:
            self.cur = -1
        else:
            self.cur = self._index_from(self._caret_anchor() if anchor == "caret" else anchor)
        self._paint()
        if reveal:
            self._reveal(soft=(reveal == "soft"))

    def _on_modified(self):
        if self.isVisible() and not self._busy and self.find_edit.text():
            self._timer.start()

    def step(self, delta):
        if not self.isVisible():
            self.open()
            return
        self.matches = self.collect()
        if not self.matches:
            self.cur = -1
            self._paint()
            return
        base = self._key()
        idx = self._index_from(base) if base else 0
        if base is not None:               # _index_from lands on the current match again
            idx = (idx + delta) % len(self.matches)
        elif delta < 0:
            idx = len(self.matches) - 1
        self.cur = idx
        self._paint()
        self._reveal()

    # ---- display ---------------------------------------------------------------
    def _clear_highlights(self):
        for c in self._lit:
            if c in self.nb.cells:
                c.set_highlights([], None)
        self._lit = []

    def _paint(self):
        by_cell = {}
        for cell, a, b in self.matches:
            by_cell.setdefault(cell, []).append((a, b))
        cur_cell, cur_span = None, None
        if 0 <= self.cur < len(self.matches):
            cur_cell = self.matches[self.cur][0]
            cur_span = (self.matches[self.cur][1], self.matches[self.cur][2])
        for c in self._lit:
            if c in self.nb.cells and c not in by_cell:
                c.set_highlights([], None)
        for cell, spans in by_cell.items():
            cell.set_highlights(spans, cur_span if cell is cur_cell else None)
        self._lit = list(by_cell)
        if not self.find_edit.text():
            self.count.setText("")
            self.count.setStyleSheet("")
        elif not self.matches:
            self.count.setText("No results")
            self.count.setStyleSheet(f"color: {WARN};")
        else:
            self.count.setText(f"{self.cur + 1} of {len(self.matches)}")
            self.count.setStyleSheet("")

    def retheme(self):
        self._paint()

    def _reveal(self, soft=False):
        if not 0 <= self.cur < len(self.matches):
            return
        cell, a, b = self.matches[self.cur]
        if soft and cell.find_widget() is None:
            return                         # don't flip Markdown cells to edit mode mid-typing
        cell.prepare_find()                # may switch a Markdown cell into edit mode
        self._paint()
        w = cell.find_widget()
        if w is None:
            self.nb.ensureWidgetVisible(cell)
            return
        qp = qt_pos_fn(cell.find_text())
        c = QTextCursor(w.document())
        c.setPosition(qp(a))               # caret only: a real selection would paint over
        w.setTextCursor(c)                 # the "current match" highlight colour
        w.ensureCursorVisible()            # horizontal scroll for long lines
        pt = w.viewport().mapTo(self.nb.widget(), w.cursorRect(c).center())
        self.nb.ensureVisible(pt.x(), pt.y(), 40, 90)

    # ---- replacing ---------------------------------------------------------------
    def replace_current(self):
        self.matches = self.collect()
        if not self.matches:
            self._paint()
            return
        if self.cur < 0 or self.cur >= len(self.matches):
            self.cur = self._index_from(self._caret_anchor())
        cell, a, b = self.matches[self.cur]
        repl = self.rep_edit.text()
        self._busy = True
        try:
            cell.replace_spans([(a, b)], repl)
        finally:
            self._busy = False
        self.refresh(anchor=(cell, a + len(repl)), reveal=True)     # jump to the next match

    def replace_all(self):
        matches = self.collect()
        if not matches:
            self._paint()
            return
        by_cell = {}
        for cell, a, b in matches:
            by_cell.setdefault(cell, []).append((a, b))
        repl = self.rep_edit.text()
        self._busy = True
        try:
            for cell, spans in by_cell.items():
                cell.replace_spans(spans, repl)
        finally:
            self._busy = False
        self.refresh(anchor=None)
        self.count.setText(f"Replaced {len(matches)} in {len(by_cell)} cell"
                           f"{'s' if len(by_cell) != 1 else ''}")


class SourceDialog(QDialog):
    def __init__(self, parent, title, source, mono):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 620)
        ed = CodeEditor(source, mono)
        ed.setReadOnly(True)
        self.highlighter = CppHighlighter(ed.document())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(ed)


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------
class InstallWorker(QThread):
    """Runs a toolchain operation off the GUI thread. Errors never escape as exceptions."""
    progress = Signal(str)
    finished_ok = Signal(bool, str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            result = self.fn(self.progress.emit, lambda: self._cancel)
            failed = [f"{k}: {v}" for k, v in (result or {}).items() if v]
            self.finished_ok.emit(not failed, "\n".join(failed))
        except tc.ToolchainError as e:
            self.finished_ok.emit(False, str(e))
        except Exception as e:      # noqa: BLE001 - never crash the app from a worker
            self.finished_ok.emit(False, f"Unexpected error: {e}")


class ToolchainManagerDialog(QDialog):
    """Bootstrap setup shown only when the project-local Arduino CLI is missing."""

    def __init__(self, parent, env, cli, platforms, first_run=False):
        super().__init__(parent)
        self.env, self.cli, self.pm = env, cli, platforms
        self.setWindowTitle("Embedded Notebook Setup")
        self.resize(560, 620)
        self.worker = None
        lay = QVBoxLayout(self)
        intro = QLabel("Embedded Notebook needs an MCU development environment.\n"
                       "Everything is stored inside the environment folder below." if first_run
                       else "Toolchain, platforms and libraries managed by Embedded Notebook.")
        lay.addWidget(intro)
        lay.addWidget(QLabel(f"Environment location:\n{env.EMBEDDED_ROOT}"))
        self.cli_label = QLabel()
        lay.addWidget(self.cli_label)
        lay.addWidget(QLabel("MCU Platforms"))
        self.checks = {}                    # board name -> QCheckBox
        self.plat_labels = {}
        for plat in self.pm.registry.platforms.values():
            pl = QLabel(); pl.setStyleSheet("font-weight: bold;")
            self.plat_labels[plat.id] = pl
            lay.addWidget(pl)
            for b in plat.boards:
                cb = QCheckBox(b.name); cb.setChecked(True)
                self.checks[b.name] = cb
                lay.addWidget(cb)
        self.status_view = QPlainTextEdit(); self.status_view.setReadOnly(True)
        lay.addWidget(self.status_view, 1)
        self.progress = QProgressBar(); self.progress.setRange(0, 1)
        lay.addWidget(self.progress)
        row = QHBoxLayout()
        self.btn_install = QPushButton("Install Selected")
        self.btn_update = QPushButton("Update")
        self.btn_remove = QPushButton("Remove")
        self.btn_refresh = QPushButton("Refresh")
        self.btn_cancel = QPushButton("Cancel"); self.btn_cancel.setEnabled(False)
        self.btn_close = QPushButton("Close")
        for b in (self.btn_install, self.btn_update, self.btn_remove, self.btn_refresh,
                  self.btn_cancel, self.btn_close):
            row.addWidget(b)
        lay.addLayout(row)
        self.btn_install.clicked.connect(self.do_install)
        self.btn_update.clicked.connect(self.do_update)
        self.btn_remove.clicked.connect(self.do_remove)
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_cancel.clicked.connect(lambda: self.worker and self.worker.cancel())
        self.btn_close.clicked.connect(self.close)
        self.refresh()

    # ---- helpers
    def selected_platform_ids(self):
        names = [n for n, cb in self.checks.items() if cb.isChecked()]
        return [p.id for p in self.pm.registry.platforms_for_boards(names)]   # unique platforms

    def refresh(self):
        installed = self.pm.installed_platforms()
        ver = self.cli.version()
        self.cli_label.setText(f"Arduino CLI: Installed  |  Version: {ver}  |  "
                               f"Location: {self.env.relpath(self.cli.path())}" if ver
                               else "Arduino CLI: Not installed")
        lines = []
        for plat in self.pm.registry.platforms.values():
            v = installed.get(plat.id)
            self.plat_labels[plat.id].setText(
                f"{plat.name}  -  " + (f"Installed (version {v})" if plat.id in installed else "Not installed"))
        for name, ready in self.pm.board_status(installed).items():
            lines.append(f"{name:<24}{'Ready' if ready else 'Not Ready'}")
        self.status_view.setPlainText("Boards:\n" + "\n".join(lines))
        for b in (self.btn_update, self.btn_remove):
            b.setEnabled(bool(installed) and self.worker is None)

    def _busy(self, busy):
        for b in (self.btn_install, self.btn_update, self.btn_remove, self.btn_refresh, self.btn_close):
            b.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)
        self.progress.setRange(0, 0 if busy else 1)

    def _run(self, fn):
        self.worker = InstallWorker(fn)
        parent = self.parent()
        if parent is not None:
            parent.install_worker = self.worker
        self.worker.progress.connect(lambda m: self.status_view.appendPlainText(m))
        self.worker.finished_ok.connect(self._done)
        self._busy(True)
        self.status_view.clear()
        self.worker.start()

    def _done(self, ok, err):
        self.worker = None
        self._busy(False)
        self.refresh()
        if ok:
            self.status_view.appendPlainText("\nDone.")
        else:
            self.status_view.appendPlainText(
                "\nInstallation did not complete:\n" + err +
                "\n\nThe environment is unchanged where steps failed; press Install again to resume.")

    # ---- actions
    def do_install(self):
        ids = self.selected_platform_ids()
        if not ids:
            QMessageBox.information(self, "Nothing selected", "Select at least one board.")
            return
        self._run(lambda say, cancelled: self.pm.install(ids, say, cancelled))

    def do_update(self):
        self._run(lambda say, cancelled: self.pm.update(say))

    def do_remove(self):
        ids = [i for i in self.selected_platform_ids() if self.pm.is_platform_installed(i)]
        if not ids:
            QMessageBox.information(self, "Nothing to remove", "None of the selected platforms is installed.")
            return
        if QMessageBox.question(self, "Remove", f"Remove {', '.join(ids)}?") != QMessageBox.Yes:
            return
        def job(say, cancelled):
            for i in ids:
                say(f"Removing {i}...")
                self.pm.remove(i)
        self._run(job)

    def closeEvent(self, event):
        if self.worker is not None:
            self.worker.cancel()
            self.worker.wait(5000)
        super().closeEvent(event)


class LibraryWorker(QThread):
    output = Signal(str)

    def __init__(self, operation, stream_output=False):
        super().__init__()
        self.operation = operation
        self.stream_output = stream_output
        self.result_data = None
        self.error = ""

    def run(self):
        try:
            self.result_data = (self.operation(self.output.emit) if self.stream_output
                                else self.operation())
        except tc.ToolchainError as e:
            self.error = str(e)
        except Exception as e:      # noqa: BLE001 - keep CLI failures inside the dialog
            self.error = f"Library operation failed: {e}"


class PackageTaskPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("packageTaskPanel")
        self.status = QLabel("Ready")
        self.status.setObjectName("packageTaskStatus")
        self.current_file = QLabel("File: -")
        self.current_file.setObjectName("packageTaskFile")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.output = QPlainTextEdit()
        self.output.setObjectName("packageTaskOutput")
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(1000)
        self.output.setMinimumHeight(70)
        self.output.verticalScrollBar().setSingleStep(10)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.status)
        layout.addWidget(self.current_file)
        layout.addWidget(self.progress)
        layout.addWidget(self.output, 1)

    def begin(self, title):
        self.status.setText(title)
        self.current_file.setText("File: waiting for package manager...")
        self.progress.setRange(0, 0)
        self.output.clear()

    def append(self, line):
        if not line:
            return
        self.output.appendPlainText(line)
        percent = re.search(r"\b(\d{1,3})%", line)
        if percent:
            self.progress.setRange(0, 100)
            self.progress.setValue(min(100, int(percent.group(1))))
        filenames = re.findall(r"[\w.@+-]+\.(?:tar\.gz|tgz|zip|xz|gz|json|bin)",
                               line, re.IGNORECASE)
        if filenames:
            self.current_file.setText(f"File: {filenames[-1]}")
        elif re.search(r"download|install|extract|unpack", line, re.IGNORECASE):
            self.current_file.setText(f"File: {line.strip()[:180]}")

    def finish(self, error=""):
        if error:
            self.status.setText("Operation failed")
            self.output.appendPlainText(error)
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
        else:
            self.status.setText("Operation complete")
            self.progress.setRange(0, 1)
            self.progress.setValue(1)


def tune_manager_scroll(widget):
    widget.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    widget.verticalScrollBar().setSingleStep(10)


class LibraryManagerDialog(QDialog):
    def __init__(self, parent, platforms):
        super().__init__(parent)
        self.pm = platforms
        self.worker = None
        self.operation = None
        self.installed_versions = {}
        self.search_results = []
        self.installed_results = []
        self.result_controls = []
        self.installed_controls = []
        self.setWindowTitle("Library Manager")
        self.resize(760, 680)
        self.setMinimumSize(640, 480)
        self.setWindowFlags(self.windowFlags() | Qt.Window | Qt.WindowMinimizeButtonHint |
                    Qt.WindowMaximizeButtonHint)
        self.setWindowModality(Qt.NonModal)
        self.setSizeGripEnabled(True)

        self.tabs = QTabWidget()
        search_page = QWidget()
        search_layout = QVBoxLayout(search_page)
        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search libraries")
        self.search_button = QPushButton("Search")
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self.search_button)
        search_layout.addLayout(search_row)
        self.results = QListWidget()
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.results.setSpacing(0)
        tune_manager_scroll(self.results)
        search_layout.addWidget(self.results, 1)
        self.tabs.addTab(search_page, "Search")

        installed_page = QWidget()
        installed_layout = QVBoxLayout(installed_page)
        self.installed_list = QListWidget()
        self.installed_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.installed_list.setSpacing(0)
        tune_manager_scroll(self.installed_list)
        installed_layout.addWidget(self.installed_list, 1)
        self.refresh_installed_button = QPushButton("Refresh")
        installed_layout.addWidget(self.refresh_installed_button, 0, Qt.AlignRight)
        self.tabs.addTab(installed_page, "Installed")

        self.status_label = QLabel("Search the Arduino Library Registry")
        self.task_panel = PackageTaskPanel()
        self.task_active = False
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.addWidget(self.status_label, 1)
        buttons.addWidget(close_button)
        layout = QVBoxLayout(self)
        self.content_splitter = QSplitter(Qt.Vertical)
        self.content_splitter.setHandleWidth(8)
        self.content_splitter.addWidget(self.tabs)
        self.content_splitter.addWidget(self.task_panel)
        self.content_splitter.setStretchFactor(0, 4)
        self.content_splitter.setStretchFactor(1, 1)
        self.content_splitter.setSizes([450, 180])
        layout.addWidget(self.content_splitter, 1)
        layout.addLayout(buttons)

        self.search_button.clicked.connect(self.search)
        self.search_edit.returnPressed.connect(self.search)
        self.refresh_installed_button.clicked.connect(self.refresh_installed)
        self.refresh_installed()

    def _start(self, operation, fn, task_title=None):
        self.operation = operation
        self.task_active = task_title is not None
        if self.task_active:
            self.task_panel.begin(task_title)
        self._set_busy(True)
        self.worker = LibraryWorker(fn, self.task_active)
        self.worker.output.connect(self.task_panel.append)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def _set_busy(self, busy):
        self.search_button.setEnabled(not busy)
        self.search_edit.setEnabled(not busy)
        self.refresh_installed_button.setEnabled(not busy)
        for name, version_combo, action_button, remove_only in (
                self.result_controls + self.installed_controls):
            version_combo.setEnabled(not busy)
            installed = remove_only or name in self.installed_versions
            action_button.setText("Remove" if installed else "Install")
            action_button.setEnabled(not busy)

    def search(self):
        query = self.search_edit.text().strip()
        if not query:
            self.results.clear()
            self.result_controls = []
            self.status_label.setText("Enter a library name or search term")
            self._set_busy(False)
            return
        self.status_label.setText("Searching the Arduino Library Registry...")
        self._start("search", lambda: self.pm.search_libraries(query))

    def refresh_installed(self):
        self.status_label.setText("Loading installed libraries...")
        self._start("installed", self.pm.installed_libraries)

    def _activate_library(self, name, version, remove_only=False):
        if not name:
            return
        if remove_only or name in self.installed_versions:
            self.status_label.setText(f"Removing {name}...")
            self._start("remove", lambda output: self.pm.remove_library(name, output),
                        f"Removing library {name}...")
        elif version:
            self.status_label.setText(f"Installing {name} {version}...")
            self._start("install", lambda output: self.pm.install_library(name, version, output),
                        f"Installing library {name} {version}...")

    def _result_widget(self, library, installed_card=False):
        name = library.get("name", "")
        latest = library.get("latest", library)
        latest = latest if isinstance(latest, dict) else {}
        row = QWidget()
        row.setObjectName("libraryEntry")
        layout = QVBoxLayout(row)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(6)

        author = latest.get("author", "")
        title = QLabel(f"<b>{escape(name)}</b>"
                       + (f" <span style='color:{MUTED}'>by {escape(author)}</span>" if author else ""))
        title.setTextFormat(Qt.RichText)
        layout.addWidget(title)

        description = " ".join(part for part in (latest.get("sentence", ""),
                                                   latest.get("paragraph", "")) if part)
        if description:
            desc_label = QLabel(escape(description))
            desc_label.setTextFormat(Qt.RichText)
            desc_label.setWordWrap(True)
            layout.addWidget(desc_label)

        website = latest.get("website", "")
        if website:
            more = QLabel(f"<a href='{escape(website, quote=True)}' style='color:{TEAL_HOVER}'>More info</a>")
            more.setOpenExternalLinks(True)
            layout.addWidget(more)

        controls = QHBoxLayout()
        versions = library.get("available_versions", [])
        versions = [str(version) for version in versions if version]
        latest_version = str(library.get("version") or latest.get("version", ""))
        if latest_version and latest_version not in versions:
            versions.append(latest_version)
        if installed_card and latest_version:
            versions = [latest_version]
        elif latest_version:
            versions = [latest_version, *[version for version in reversed(versions)
                                          if version != latest_version]]
        if not versions:
            versions = ["latest"]
        version_combo = QComboBox()
        version_combo.addItems(versions)
        version_combo.setMinimumWidth(88)
        action_button = QPushButton()
        action_button.setObjectName("primary")
        action_button.clicked.connect(
            lambda _checked=False, n=name, combo=version_combo:
            self._activate_library(n, combo.currentText(), installed_card))
        controls.addWidget(version_combo)
        controls.addWidget(action_button)
        controls.addStretch()
        layout.addLayout(controls)
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFixedHeight(1)
        separator.setStyleSheet(f"color: {BORDER};")
        layout.addWidget(separator)

        target_controls = self.installed_controls if installed_card else self.result_controls
        target_controls.append((name, version_combo, action_button, installed_card))
        version_combo.currentTextChanged.connect(lambda _text: self._set_busy(
            self.worker is not None and self.worker.isRunning()))
        return row

    def _populate_list(self, widget, libraries, installed_card=False):
        widget.clear()
        controls = self.installed_controls if installed_card else self.result_controls
        controls.clear()
        for library in libraries:
            item = QListWidgetItem()
            widget.addItem(item)
            row = self._result_widget(library, installed_card)
            row.setMinimumHeight(145)
            item.setSizeHint(row.sizeHint())
            widget.setItemWidget(item, row)

    def _finished(self):
        operation, self.operation = self.operation, None
        data, error = self.worker.result_data, self.worker.error
        task_active, self.task_active = self.task_active, False
        self.worker = None
        self._set_busy(False)
        if task_active:
            self.task_panel.finish(error)
        if error:
            self.status_label.setText(error)
        elif operation == "search":
            self.search_results = data
            self._populate_list(self.results, self.search_results)
            self.status_label.setText(f"{len(data)} libraries found")
            self._set_busy(False)
        elif operation == "installed":
            self.installed_results = data
            self.installed_versions = {lib.get("name", ""): str(lib.get("version", ""))
                                       for lib in data if lib.get("name")}
            self._populate_list(self.installed_list, self.installed_results, installed_card=True)
            self.status_label.setText(f"{len(data)} installed libraries")
            self._set_busy(False)
        elif operation in ("install", "remove"):
            self.status_label.setText("Library installed" if operation == "install" else "Library removed")
            self.refresh_installed()

    def retheme(self):
        self._populate_list(self.results, self.search_results)
        self._populate_list(self.installed_list, self.installed_results, installed_card=True)
        self._set_busy(self.worker is not None and self.worker.isRunning())

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.status_label.setText("Please wait for the current library operation to finish")
            event.ignore()
            return
        super().closeEvent(event)


class BoardsManagerDialog(QDialog):
    def __init__(self, parent, platforms):
        super().__init__(parent)
        self.pm = platforms
        self.worker = None
        self.operation = None
        self.installed_versions = {}
        self.platforms_by_id = {}
        self.search_packages = []
        self.search_controls = []
        self.installed_controls = []
        self.task_active = False
        self.setWindowTitle("Boards Manager")
        self.resize(760, 720)
        self.setMinimumSize(640, 520)
        self.setWindowFlags(self.windowFlags() | Qt.Window | Qt.WindowMinimizeButtonHint |
                    Qt.WindowMaximizeButtonHint)
        self.setWindowModality(Qt.NonModal)
        self.setSizeGripEnabled(True)

        self.tabs = QTabWidget()
        search_page = QWidget()
        search_layout = QVBoxLayout(search_page)
        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter your search...")
        self.search_button = QPushButton("Search")
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self.search_button)
        search_layout.addLayout(search_row)
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Type:"))
        self.type_combo = QComboBox()
        self.type_combo.addItem("All")
        self.type_combo.setMinimumWidth(120)
        type_row.addWidget(self.type_combo)
        type_row.addStretch()
        search_layout.addLayout(type_row)
        self.results = QListWidget()
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.results.setSpacing(0)
        tune_manager_scroll(self.results)
        search_layout.addWidget(self.results, 1)
        self.tabs.addTab(search_page, "Search")

        installed_page = QWidget()
        installed_layout = QVBoxLayout(installed_page)
        self.installed_list = QListWidget()
        self.installed_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.installed_list.setSpacing(0)
        tune_manager_scroll(self.installed_list)
        installed_layout.addWidget(self.installed_list, 1)
        self.refresh_installed_button = QPushButton("Refresh")
        installed_layout.addWidget(self.refresh_installed_button, 0, Qt.AlignRight)
        self.tabs.addTab(installed_page, "Installed")

        urls_page = QWidget()
        urls_layout = QVBoxLayout(urls_page)
        url_row = QHBoxLayout()
        self.package_url_edit = QLineEdit()
        self.package_url_edit.setPlaceholderText("https://example.com/package_index.json")
        self.add_url_button = QPushButton("Add URL")
        url_row.addWidget(self.package_url_edit, 1)
        url_row.addWidget(self.add_url_button)
        urls_layout.addLayout(url_row)
        urls_layout.addWidget(QLabel("Additional package indexes are used by Search.\n"
                         "Removing a URL does not uninstall cores already installed from it."))
        self.package_url_list = QListWidget()
        tune_manager_scroll(self.package_url_list)
        urls_layout.addWidget(self.package_url_list, 1)
        self.tabs.addTab(urls_page, "Package URLs")

        self.status_label = QLabel("Loading board packages...")
        self.task_panel = PackageTaskPanel()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        footer = QHBoxLayout()
        footer.addWidget(self.status_label, 1)
        footer.addWidget(close_button)
        layout = QVBoxLayout(self)
        self.content_splitter = QSplitter(Qt.Vertical)
        self.content_splitter.setHandleWidth(8)
        self.content_splitter.addWidget(self.tabs)
        self.content_splitter.addWidget(self.task_panel)
        self.content_splitter.setStretchFactor(0, 4)
        self.content_splitter.setStretchFactor(1, 1)
        self.content_splitter.setSizes([480, 180])
        layout.addWidget(self.content_splitter, 1)
        layout.addLayout(footer)

        self.search_button.clicked.connect(self.search)
        self.search_edit.returnPressed.connect(self.search)
        self.type_combo.currentTextChanged.connect(self._filter_search)
        self.refresh_installed_button.clicked.connect(self.refresh_installed)
        self.add_url_button.clicked.connect(self.add_package_url)
        self.package_url_edit.returnPressed.connect(self.add_package_url)
        self._start("initial", self._load_initial)

    def _load_initial(self):
        packages = self.pm.search_platforms("")
        installed = self.pm.installed_platforms()
        return packages, installed, self.pm.additional_package_urls()

    def _start(self, operation, fn, task_title=None):
        self.operation = operation
        self.task_active = task_title is not None
        if self.task_active:
            self.task_panel.begin(task_title)
        self._set_busy(True)
        self.worker = LibraryWorker(fn, self.task_active)
        self.worker.output.connect(self.task_panel.append)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def _set_busy(self, busy):
        self.search_button.setEnabled(not busy)
        self.search_edit.setEnabled(not busy)
        self.refresh_installed_button.setEnabled(not busy)
        self.package_url_edit.setEnabled(not busy)
        self.add_url_button.setEnabled(not busy)
        self.package_url_list.setEnabled(not busy)
        for name, version_combo, action_button, remove_only in (
                self.search_controls + self.installed_controls):
            version_combo.setEnabled(not busy)
            installed = remove_only or name in self.installed_versions
            action_button.setText("Remove" if installed else "Install")
            action_button.setEnabled(not busy)

    def search(self):
        self.status_label.setText("Searching board packages...")
        self._start("search", lambda: self.pm.search_platforms(self.search_edit.text().strip()))

    def refresh_installed(self):
        self.status_label.setText("Loading installed boards...")
        self._start("installed", self.pm.installed_platforms)

    def add_package_url(self):
        url = self.package_url_edit.text().strip()
        if not url:
            self.status_label.setText("Enter a package index URL")
            return
        self._start("add_url", lambda output: self.pm.add_package_url(url, output),
                    f"Adding package index {url}...")

    def remove_package_url(self, url):
        self._start("remove_url", lambda output: self.pm.remove_package_url(url, output),
                    f"Removing package index {url}...")

    def _populate_package_urls(self, urls):
        self.package_url_list.clear()
        for url in urls:
            item = QListWidgetItem()
            self.package_url_list.addItem(item)
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(6, 4, 6, 4)
            label = QLabel(url)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            remove_button = QPushButton("Remove")
            remove_button.clicked.connect(lambda _checked=False, value=url:
                                          self.remove_package_url(value))
            layout.addWidget(label, 1)
            layout.addWidget(remove_button)
            item.setSizeHint(row.sizeHint())
            self.package_url_list.setItemWidget(item, row)

    def _fallback_package(self, platform_id, version):
        platform = self.pm.registry.platforms.get(platform_id)
        name = platform.name if platform else platform_id
        boards = platform.boards if platform else ()
        release = {"name": name, "version": version,
                   "boards": [{"name": board.name} for board in boards]}
        return {"id": platform_id, "latest_version": version,
                "installed_version": version, "releases": {version: release}}

    def _make_card(self, package, installed_card=False):
        platform_id = package.get("id", "")
        installed_version = self.installed_versions.get(platform_id, "")
        releases = package.get("releases", {})
        releases = releases if isinstance(releases, dict) else {}
        latest_version = str(package.get("latest_version", ""))
        versions = [str(version) for version in releases if version]
        if latest_version and latest_version not in versions:
            versions.append(latest_version)
        if latest_version:
            versions = [latest_version, *[version for version in reversed(versions)
                                          if version != latest_version]]
        if not versions:
            versions = [installed_version] if installed_version else ["latest"]
        release_version = installed_version if installed_card and installed_version else latest_version
        if release_version not in releases:
            release_version = versions[0]
        release = releases.get(release_version, {})
        release = release if isinstance(release, dict) else {}
        name = release.get("name", platform_id)
        maintainer = package.get("maintainer", "")

        row = QWidget()
        layout = QVBoxLayout(row)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(6)
        title = QLabel(f"<b>{escape(name)}</b>"
                       + (f" <span style='color:{MUTED}'>by {escape(maintainer)}</span>"
                          if maintainer else ""))
        title.setTextFormat(Qt.RichText)
        layout.addWidget(title)

        if installed_version:
            installed_label = QLabel(
                f"<span style='color:{TEAL_HOVER}'>{escape(installed_version)} installed</span>")
            installed_label.setTextFormat(Qt.RichText)
            layout.addWidget(installed_label)

        boards = release.get("boards", [])
        board_names = [board.get("name", "") for board in boards if isinstance(board, dict)]
        if board_names:
            summary = ", ".join(board_names[:4])
            if len(board_names) > 4:
                summary += f", and {len(board_names) - 4} more"
            description = QLabel(escape("Boards included in this package: " + summary))
            description.setTextFormat(Qt.RichText)
            description.setWordWrap(True)
            layout.addWidget(description)

        help_info = release.get("help", {})
        website = (help_info.get("online", "") if isinstance(help_info, dict) else "") or package.get("website", "")
        if website:
            more = QLabel(f"<a href='{escape(website, quote=True)}' style='color:{TEAL_HOVER}'>More info</a>")
            more.setOpenExternalLinks(True)
            layout.addWidget(more)

        controls = QHBoxLayout()
        version_combo = QComboBox()
        version_combo.addItems(versions)
        version_combo.setMinimumWidth(88)
        selected_version = installed_version if installed_card and installed_version else latest_version
        if selected_version:
            version_combo.setCurrentText(selected_version)
        action_button = QPushButton()
        action_button.setObjectName("primary")
        action_button.clicked.connect(
            lambda _checked=False, pid=platform_id, combo=version_combo,
            remove=installed_card: self._activate(pid, combo.currentText(), remove))
        controls.addWidget(version_combo)
        controls.addWidget(action_button)
        controls.addStretch()
        layout.addLayout(controls)
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFixedHeight(1)
        separator.setStyleSheet(f"color: {BORDER};")
        layout.addWidget(separator)

        controls_list = self.installed_controls if installed_card else self.search_controls
        controls_list.append((platform_id, version_combo, action_button, installed_card))
        return row

    def _populate(self, widget, packages, installed_card=False):
        widget.clear()
        controls = self.installed_controls if installed_card else self.search_controls
        controls.clear()
        for package in packages:
            item = QListWidgetItem()
            widget.addItem(item)
            row = self._make_card(package, installed_card)
            row.setMinimumHeight(120)
            row.setMaximumHeight(260)
            item.setSizeHint(QSize(widget.viewport().width(),
                                   min(max(row.sizeHint().height(), 120), 260)))
            widget.setItemWidget(item, row)

    def _set_types(self, packages):
        types = set()
        for package in packages:
            latest = package.get("releases", {}).get(package.get("latest_version"), {})
            types.update(latest.get("types", []) if isinstance(latest, dict) else [])
        current = self.type_combo.currentText()
        self.type_combo.blockSignals(True)
        self.type_combo.clear()
        self.type_combo.addItem("All")
        self.type_combo.addItems(sorted(str(value) for value in types))
        if current in [self.type_combo.itemText(i) for i in range(self.type_combo.count())]:
            self.type_combo.setCurrentText(current)
        self.type_combo.blockSignals(False)
        self._filter_search()

    def _filter_search(self, *_):
        selected = self.type_combo.currentText()
        if selected == "All":
            packages = self.search_packages
        else:
            packages = []
            for package in self.search_packages:
                latest = package.get("releases", {}).get(package.get("latest_version"), {})
                if isinstance(latest, dict) and selected in latest.get("types", []):
                    packages.append(package)
        self._populate(self.results, packages)
        self._set_busy(self.worker is not None and self.worker.isRunning())

    def _activate(self, platform_id, version, remove_only=False):
        if remove_only or platform_id in self.installed_versions:
            self.status_label.setText(f"Removing {platform_id}...")
            self._start("remove", lambda output: self.pm.remove(platform_id, output),
                        f"Removing board core {platform_id}...")
        elif version and version != "latest":
            self.status_label.setText(f"Installing {platform_id} {version}...")
            self._start("install", lambda output: self.pm.install_platform(platform_id, version, output),
                        f"Installing board core {platform_id} {version}...")

    def _finished(self):
        operation, self.operation = self.operation, None
        data, error = self.worker.result_data, self.worker.error
        task_active, self.task_active = self.task_active, False
        self.worker = None
        self._set_busy(False)
        if task_active:
            self.task_panel.finish(error)
        if error:
            self.status_label.setText(error)
            return
        if operation == "initial":
            packages, installed, urls = data
            self.platforms_by_id.update({package["id"]: package for package in packages})
            self.installed_versions = installed
            self.search_packages = packages
            self._set_types(packages)
            self._populate_installed()
            self._populate_package_urls(urls)
            self.status_label.setText(f"{len(packages)} board packages")
            self._set_busy(False)
        elif operation == "search":
            self.platforms_by_id.update({package["id"]: package for package in data})
            self.search_packages = data
            self._set_types(data)
            self.status_label.setText(f"{len(data)} board packages found")
            self._set_busy(False)
        elif operation == "installed":
            self.installed_versions = data
            self._populate_installed()
            self.status_label.setText(f"{len(self.installed_versions)} installed platforms")
            self._set_busy(False)
        elif operation in ("install", "remove"):
            self.status_label.setText("Board platform installed" if operation == "install"
                                      else "Board platform removed")
            self.refresh_installed()
        elif operation in ("add_url", "remove_url"):
            self.status_label.setText("Package index added" if operation == "add_url"
                                      else "Package index removed")
            self.package_url_edit.clear()
            self._start("initial", self._load_initial)
        

    def _populate_installed(self):
        packages = []
        for platform_id, version in self.installed_versions.items():
            packages.append(self.platforms_by_id.get(
                platform_id, self._fallback_package(platform_id, str(version))))
        self._populate(self.installed_list, packages, installed_card=True)

    def retheme(self):
        self._filter_search()
        self._populate_installed()
        self._populate_package_urls(self.pm.additional_package_urls())

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.status_label.setText("Please wait for the current board operation to finish")
            event.ignore()
            return
        super().closeEvent(event)

