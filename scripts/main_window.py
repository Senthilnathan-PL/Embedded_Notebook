"""
MainWindow: primary window, menu, toolbar, compilers, uploaders, and serial monitor.
"""
import copy
import os
import shutil
import sys
import time
from pathlib import Path

import serial
from serial.tools import list_ports

from PySide6.QtCore import (
    QProcessEnvironment, QProcess, QSettings, QSize, QTimer, Qt,
)
from PySide6.QtGui import (
    QAction, QFont, QKeySequence, QActionGroup, QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QProgressBar, QSplitter, QTabWidget, QTextEdit,
    QToolButton, QVBoxLayout, QWidget,
)

import scripts.toolchain as tc
from scripts.cells import Notebook, CodeCell, MarkdownCell
from scripts.sketch_builder import build_sketch
from scripts.notebook_format import (
    parse_notebook, serialize_notebook, ensure_notebook_suffix,
    new_notebook_metadata, NotebookFormatError, NB_EXT, NB_KEY, NB_MINOR,
)
from scripts.serial_worker import SerialWorker
from scripts.dialogs import (
    FindBar, SourceDialog, ToolchainManagerDialog, LibraryManagerDialog,
    BoardsManagerDialog,
)
from scripts.theme import (
    apply_theme, resolve_theme, make_icon, THEME_MODES,
    BORDER, MUTED,
)

REGISTRY = tc.BoardRegistry()
BOARDS = {b.name: (b.fqbn, b.platform_id, REGISTRY.platform(b.platform_id).package_url)
          for b in REGISTRY.boards.values()}

class MainWindow(QMainWindow):
    def __init__(self, app_root=None, prompt_setup=False, theme_mode=None):
        super().__init__()
        settings = QSettings("EmbeddedNotebook", "EmbeddedNotebook")
        self.theme_mode = theme_mode or settings.value("theme", "Auto")
        if self.theme_mode not in THEME_MODES:
            self.theme_mode = "Auto"
        self._style_hints = QApplication.instance().styleHints()
        apply_theme(QApplication.instance(), resolve_theme(
            self.theme_mode, self._style_hints.colorScheme()))
        self._style_hints.colorSchemeChanged.connect(self._on_system_color_scheme_changed)
        self.setWindowTitle("Embedded Notebook")
        self.resize(1150, 900)

        # Project-local toolchain: never the global arduino-cli / Arduino15 / temp dirs.
        self.env = tc.EnvironmentManager(app_root)
        self.cli_mgr = tc.ArduinoCLIManager(self.env)
        self.platforms = tc.PlatformManager(self.env, self.cli_mgr, REGISTRY)
        self.cli = str(self.cli_mgr.path()) if self.cli_mgr.is_installed() else None
        self.workdir = self.platforms.sketch_dir().parent
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.install_worker = None
        self.boards_manager_dialog = None
        self.library_manager_dialog = None
        self.proc = None
        self.queue = []
        self.on_done = None
        self.serial = None
        self._known_ports = []

        self.mono = QFont("Consolas" if sys.platform == "win32" else "Monospace", 11)
        self.mono.setStyleHint(QFont.Monospace)
        self.editor_font_size = self.mono.pointSize()

        # --- toolbar: verify / upload / board / port / serial monitor --------
        self.verify_btn = self.round_button("verify", "Verify (Ctrl+R)", self.verify_current)
        self.upload_btn = self.round_button("upload", "Upload (Ctrl+U)", self.upload_current)
        self.board_combo = QComboBox()
        self.board_combo.setPlaceholderText("No installed boards")
        self.board_combo.setMinimumWidth(190)
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(260)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["9600", "57600", "115200", "230400", "921600"])
        self.baud_combo.setCurrentText("115200")
        refresh = QPushButton("Refresh")
        refresh.setObjectName("quiet")
        refresh.setToolTip("Rescan serial ports")
        refresh.clicked.connect(self.refresh_ports)
        self.monitor_btn = QToolButton()
        self.monitor_btn.setObjectName("flat")
        self.monitor_btn.setIcon(make_icon("monitor", ACCENT_TEXT))
        self.monitor_btn.setIconSize(QSize(30, 30))
        self.monitor_btn.setFixedSize(34, 34)
        self.monitor_btn.setToolTip("Serial Monitor (Ctrl+Shift+M)")
        self.monitor_btn.clicked.connect(self.show_serial_tab)

        toolbar = QWidget()
        toolbar.setObjectName("toolbar")
        toolbar.setAttribute(Qt.WA_StyledBackground, True)
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(12, 8, 12, 8)
        tl.setSpacing(8)
        tl.addWidget(self.verify_btn)
        tl.addWidget(self.upload_btn)
        tl.addSpacing(8)
        tl.addWidget(self.board_combo)
        tl.addWidget(self.port_combo)
        tl.addWidget(refresh)
        tl.addStretch()
        tl.addWidget(self.monitor_btn)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)

        # --- menu bar (same names and shortcuts as Arduino IDE) --------------
        m_file = self.menuBar().addMenu("&File")
        self.add_action(m_file, "&New", self.new_file, "Ctrl+N")
        self.add_action(m_file, "&Open...", self.open_file, "Ctrl+O")
        self.examples_menu = m_file.addMenu("&Examples")
        self.examples_menu.aboutToShow.connect(self.populate_examples_menu)
        m_file.addSeparator()
        self.add_action(m_file, "&Save", self.save_file, "Ctrl+S")
        self.add_action(m_file, "Save &As...", self.save_file_as, "Ctrl+Shift+S")
        m_file.addSeparator()
        self.add_action(m_file, "&Quit", self.close, "Ctrl+Q")
        m_edit = self.menuBar().addMenu("&Edit")
        self.undo_act = self.add_action(m_edit, "&Undo", self.undo, "Ctrl+Z")
        self.redo_act = self.add_action(m_edit, "&Redo", self.redo, ["Ctrl+Y", "Ctrl+Shift+Z"])
        m_edit.addSeparator()
        self.comment_act = self.add_action(m_edit, "Comment / Uncomment", self.toggle_comment, "Ctrl+/")
        m_edit.addSeparator()
        self.add_action(m_edit, "&Find...", lambda: self.find_bar.open(), "Ctrl+F")
        self.add_action(m_edit, "Find &Next", lambda: self.find_bar.step(+1), "F3")
        self.add_action(m_edit, "Find &Previous", lambda: self.find_bar.step(-1), "Shift+F3")
        self.add_action(m_edit, "&Replace...", lambda: self.find_bar.open(replace=True), "Ctrl+H")
        m_view = self.menuBar().addMenu("&View")
        m_theme = m_view.addMenu("&Theme")
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        for name in THEME_MODES:
            act = QAction(name, self)
            act.setCheckable(True)
            act.setChecked(name == self.theme_mode)
            act.triggered.connect(lambda _c=False, n=name: self.set_theme(n))
            theme_group.addAction(act)
            m_theme.addAction(act)
        m_view.addSeparator()
        self.add_action(m_view, "Increase Code Font Size", self.increase_code_font_size, "Ctrl+=")
        self.add_action(m_view, "Decrease Code Font Size", self.decrease_code_font_size, "Ctrl+-")
        self.add_action(m_view, "Reset Code Font Size", self.reset_code_font_size, "Ctrl+0")
        m_sketch = self.menuBar().addMenu("&Sketch")
        self.verify_act = self.add_action(m_sketch, "&Verify / Compile", self.verify_current, "Ctrl+R")
        self.upload_act = self.add_action(m_sketch, "&Upload", self.upload_current, "Ctrl+U")
        self.add_action(m_sketch, "Show &Generated Code", self.show_current, "Ctrl+Shift+G")
        m_sketch.addSeparator()
        self.add_action(m_sketch, "Add &Code Cell", lambda: self.notebook.add_code())
        self.add_action(m_sketch, "Add &Markdown Cell", lambda: self.notebook.add_markdown())
        m_tools = self.menuBar().addMenu("&Tools")
        self.add_action(m_tools, "&Boards Manager...", self.open_boards_manager)
        self.add_action(m_tools, "&Library Manager...", self.open_library_manager)
        self.add_action(m_tools, "&Refresh Ports", self.refresh_ports)
        m_tools.addSeparator()
        self.add_action(m_tools, "&Serial Monitor", self.show_serial_tab, "Ctrl+Shift+M")

        # --- notebook, with a tab-strip showing which cell the toolbar targets --
        self.notebook = Notebook(self.mono)
        self.notebook.compile_req.connect(self.compile_cell)
        self.notebook.upload_req.connect(self.upload_cell)
        self.notebook.show_req.connect(self.show_generated)
        self.notebook.selection_changed.connect(self.on_selection)
        self.notebook.modified.connect(lambda: self.set_dirty(True))
        self.find_bar = FindBar(self.notebook)

        self.target_label = QLabel("No code cell selected")
        hint = self.hint = QLabel("Toolbar acts on:")
        add_code = QPushButton("+ Code cell")
        add_md = QPushButton("+ Markdown cell")
        for b in (add_code, add_md):
            b.setObjectName("quiet")
        add_code.clicked.connect(lambda: self.notebook.add_code())
        add_md.clicked.connect(lambda: self.notebook.add_markdown())
        strip = QWidget()
        strip.setObjectName("strip")
        strip.setAttribute(Qt.WA_StyledBackground, True)
        sl0 = QHBoxLayout(strip)
        sl0.setContentsMargins(12, 4, 12, 4)
        sl0.addWidget(hint)
        sl0.addWidget(self.target_label)
        sl0.addStretch()
        sl0.addWidget(add_code)
        sl0.addWidget(add_md)
        nb_panel = QWidget()
        nl = QVBoxLayout(nb_panel)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(0)
        nl.addWidget(strip)
        nl.addWidget(self.find_bar)
        nl.addWidget(self.notebook)

        # --- bottom panel: Output | Serial Monitor -----------------------------
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(self.mono)
        self.log_view.setMaximumBlockCount(5000)

        self.ser_view = QPlainTextEdit()
        self.ser_view.setReadOnly(True)
        self.ser_view.setFont(self.mono)
        self.ser_view.setMaximumBlockCount(5000)
        self.ser_btn = QPushButton("Connect")
        self.ser_btn.clicked.connect(self.toggle_serial)
        self.ser_input = QLineEdit()
        self.ser_input.setPlaceholderText("Message (Enter to send)")
        self.ser_input.returnPressed.connect(self.send_serial)
        ser_tab = QWidget()
        st = QVBoxLayout(ser_tab)
        st.setContentsMargins(8, 8, 8, 6)
        st.setSpacing(6)
        st.addWidget(self.ser_input)
        st.addWidget(self.ser_view, 1)
        ser_row = QHBoxLayout()
        ser_row.addWidget(self.ser_btn)
        ser_row.addStretch()
        ser_row.addWidget(QLabel("Baud rate:"))
        ser_row.addWidget(self.baud_combo)
        st.addLayout(ser_row)

        self.bottom_tabs = QTabWidget()
        self.bottom_tabs.addTab(self.log_view, "Output")
        self.bottom_tabs.addTab(ser_tab, "Serial Monitor")
        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("quiet")
        clear_btn.clicked.connect(
            lambda: (self.log_view, self.ser_view)[self.bottom_tabs.currentIndex()].clear())
        bottom_actions = QWidget()
        bottom_actions_layout = QHBoxLayout(bottom_actions)
        bottom_actions_layout.setContentsMargins(0, 0, 4, 0)
        bottom_actions_layout.setSpacing(2)
        bottom_actions_layout.addWidget(clear_btn)
        self.hide_bottom_btn = QToolButton()
        self.hide_bottom_btn.setObjectName("move")
        self.hide_bottom_btn.setText("×")
        self.hide_bottom_btn.setFixedSize(28, 28)
        self.hide_bottom_btn.setToolTip("Hide output and serial monitor")
        self.hide_bottom_btn.setAccessibleName("Hide output and serial monitor")
        self.hide_bottom_btn.clicked.connect(self.hide_bottom_panel)
        bottom_actions_layout.addWidget(self.hide_bottom_btn)
        self.bottom_tabs.setCornerWidget(bottom_actions, Qt.TopRightCorner)

        self.main_splitter = QSplitter(Qt.Vertical)
        self.main_splitter.setChildrenCollapsible(True)
        self.main_splitter.addWidget(nb_panel)
        self.main_splitter.addWidget(self.bottom_tabs)
        self.main_splitter.setCollapsible(1, True)
        self.main_splitter.setSizes([600, 260])
        self._bottom_panel_size = 260

        root = QWidget()
        rl = QVBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(toolbar)
        rl.addWidget(self.progress)
        rl.addWidget(self.main_splitter, 1)
        self.setCentralWidget(root)

        # --- status bar: state on the left, board + port on the right ----------
        self.status = QLabel("Ready")
        self.target_status = QLabel()
        self.statusBar().addWidget(self.status)
        self.statusBar().addPermanentWidget(self.target_status)
        self.busy_widgets = [self.verify_btn, self.upload_btn, self.verify_act,
                     self.upload_act]
        self.board_combo.currentTextChanged.connect(self._on_board_changed)
        self.port_combo.currentIndexChanged.connect(self.update_target_status)
        self.refresh_boards()

        self.apply_inline_styles()
        self.path = None                    # file the document was loaded from / saved to
        self.save_ok = False                # True if plain Save may write to self.path
        self.dirty = False
        self.new_document()                 # one empty code cell

        self.refresh_ports()
        self.update_target_status()
        self.on_selection(self.notebook.current)
        self.update_title()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_ports)
        self.timer.start(3000)

        if not self.cli:
            self.log("Local Arduino CLI not found in "
                     f"{self.env.relpath(self.env.CLI_DIR)}. Open Tools > Boards Manager to set it up.")
            if prompt_setup:
                QTimer.singleShot(0, self.first_run_setup)
        else:
            self.log(f"Using local {self.cli}")

    # ------------------------------------------------------------- theme
    def apply_inline_styles(self):
        """Widgets whose colours are set individually (the rest follows the app stylesheet)."""
        self.target_label.setStyleSheet(f"color: {ACCENT_TEXT}; font-weight: bold;")
        self.hint.setStyleSheet(f"color: {MUTED};")
        self.log_view.setStyleSheet(
            f"QPlainTextEdit {{ background: {LOG_BG}; color: {LOG_FG}; padding: 4px; }}")
        self.ser_view.setStyleSheet(f"QPlainTextEdit {{ border: 1px solid {BORDER}; padding: 4px; }}")
        self.monitor_btn.setIcon(make_icon("monitor", ACCENT_TEXT))

    def _apply_theme_mode(self, color_scheme=None):
        scheme = self._style_hints.colorScheme() if color_scheme is None else color_scheme
        apply_theme(QApplication.instance(), resolve_theme(self.theme_mode, scheme))
        self.apply_inline_styles()
        self.notebook.retheme()
        self.find_bar.retheme()
        for dialog in (self.boards_manager_dialog, self.library_manager_dialog):
            if dialog is not None:
                dialog.retheme()

    def _on_system_color_scheme_changed(self, color_scheme):
        if self.theme_mode == "Auto":
            self._apply_theme_mode(color_scheme)

    def set_theme(self, mode):
        if mode not in THEME_MODES:
            return
        self.theme_mode = mode
        QSettings("EmbeddedNotebook", "EmbeddedNotebook").setValue("theme", mode)
        self._apply_theme_mode()

    def set_code_font_size(self, size):
        self.editor_font_size = max(8, min(24, int(size)))
        font = QFont(self.mono)
        font.setPointSize(self.editor_font_size)
        self.notebook.mono = QFont(font)
        for cell in self.notebook.cells:
            if isinstance(cell, CodeCell):
                cell.editor.setFont(font)
                cell.editor.setTabStopDistance(2 * cell.editor.fontMetrics().horizontalAdvance(" "))
                cell.editor._update_gutter_width()
                cell.editor._fit()
                cell.editor._update_bracket_highlights()
            elif isinstance(cell, MarkdownCell):
                cell.view.setFont(font)
                cell._fit()

    def increase_code_font_size(self):
        self.set_code_font_size(self.editor_font_size + 1)

    def decrease_code_font_size(self):
        self.set_code_font_size(self.editor_font_size - 1)

    def reset_code_font_size(self):
        self.set_code_font_size(11)

    # ------------------------------------------------------------- documents
    def doc_name(self):
        return self.path.name if self.path else "Untitled" + NB_EXT

    def update_title(self):
        self.setWindowTitle(f"{self.doc_name()}[*] - Embedded Notebook")
        self.setWindowModified(self.dirty)

    def set_dirty(self, on):
        if on != self.dirty:
            self.dirty = on
            self.update_title()

    def new_document(self):
        """Empty document: a single empty code cell, valid nbformat metadata."""
        self.notebook.load_cells([{"type": "code", "source": "", "title": "", "deps": "",
                                   "extra": {}}])
        self.nb_meta = new_notebook_metadata()
        self.nb_minor = NB_MINOR
        self.path = None
        self.save_ok = False
        self.set_dirty(False)
        self.update_title()
        if self.find_bar.isVisible():
            self.find_bar.refresh()

    def ask_unsaved(self):
        """-> "save" | "discard" | "cancel"  (separate method so it can be replaced in tests)."""
        box = QMessageBox(QMessageBox.Warning, "Unsaved changes",
                          f'Save changes to "{self.doc_name()}" before continuing?',
                          QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, self)
        box.setDefaultButton(QMessageBox.Save)
        return {QMessageBox.Save: "save", QMessageBox.Discard: "discard"}.get(box.exec(), "cancel")

    def maybe_save(self):
        """True if it is OK to discard the current document."""
        if not self.dirty:
            return True
        choice = self.ask_unsaved()
        if choice == "save":
            return self.save_file()
        return choice == "discard"

    def new_file(self):
        if self.maybe_save():
            self.new_document()
            self.log("New notebook")

    def pick_open_path(self):
        start = str(self.path.parent if self.path else Path.home())
        name, _ = QFileDialog.getOpenFileName(
            self, "Open Notebook", start,
            "Notebooks (*.icpnb *.ipynb);;Embedded Notebook (*.icpnb);;"
            "Jupyter Notebook (*.ipynb);;All files (*)")
        return Path(name) if name else None

    def pick_save_path(self, suggested):
        dlg = QFileDialog(self, "Save Notebook As", str(suggested))
        dlg.setAcceptMode(QFileDialog.AcceptSave)
        dlg.setFileMode(QFileDialog.AnyFile)
        dlg.setNameFilters(["Embedded Notebook (*.icpnb)", "All files (*)"])
        dlg.setDefaultSuffix("icpnb")
        dlg.selectFile(str(suggested))
        if dlg.exec() != QDialog.Accepted or not dlg.selectedFiles():
            return None
        typed = Path(dlg.selectedFiles()[0])
        path = ensure_notebook_suffix(typed)
        # The dialog only checks for overwrites of the name as typed
        if path != typed and path.exists() and QMessageBox.question(
                self, "Replace file?", f"{path.name} already exists. Replace it?") != QMessageBox.Yes:
            return None
        return path

    def open_file(self):
        if not self.maybe_save():
            return
        path = self.pick_open_path()
        if path is not None:
            self.load_path(path)

    def load_path(self, path):
        """Read a .icpnb / .ipynb file. On any problem the current document is left untouched."""
        path = Path(path)
        try:
            text = path.read_bytes().decode("utf-8-sig")
        except OSError as e:
            QMessageBox.critical(self, "Cannot open notebook", f"Could not read {path}:\n\n{e}")
            return False
        except UnicodeDecodeError:
            QMessageBox.critical(self, "Cannot open notebook",
                                 f"{path.name} is not a UTF-8 text file, so it cannot be a notebook.")
            return False
        try:
            cells, meta, minor = parse_notebook(text)
        except NotebookFormatError as e:
            QMessageBox.critical(self, "Invalid notebook",
                                 f"{path.name} could not be opened.\n\n{e}")
            return False
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.notebook.notebook_dir = path.parent
            self.notebook.load_cells(cells)
        finally:
            QApplication.restoreOverrideCursor()
        self.nb_meta, self.nb_minor = meta, minor
        board = (meta.get(NB_KEY) or {}).get("board") if isinstance(meta.get(NB_KEY), dict) else None
        if board in BOARDS:
            self.board_combo.setCurrentText(board)
        self.path = path
        self.save_ok = path.suffix.lower() == NB_EXT     # never overwrite an imported .ipynb
        self.set_dirty(False)
        self.update_title()
        if self.find_bar.isVisible():
            self.find_bar.refresh()
        self.log(f"Opened {path} ({len(cells)} cells)")
        return True

    def serialize(self):
        meta = copy.deepcopy(self.nb_meta)
        ours = meta.get(NB_KEY) if isinstance(meta.get(NB_KEY), dict) else {}
        ours["board"] = self.board_combo.currentText()
        meta[NB_KEY] = ours
        return serialize_notebook(self.notebook.export_cells(), meta, self.nb_minor)

    def write_path(self, path):
        tmp = path.with_name(path.name + ".tmp")
        try:
            text = self.serialize()
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            os.replace(tmp, path)          # a failed save never leaves a half-written notebook
        except OSError as e:
            try:
                tmp.unlink()
            except OSError:
                pass
            QMessageBox.critical(self, "Cannot save notebook", f"Could not write {path}:\n\n{e}")
            return False
        self.path = path
        self.save_ok = True
        self.set_dirty(False)
        self.update_title()
        self.log(f"Saved {path}")
        return True

    def save_file(self):
        if self.path is None or not self.save_ok:
            return self.save_file_as()
        return self.write_path(self.path)

    def save_file_as(self):
        default_name = getattr(self, "_suggested_name", "Untitled") or "Untitled"
        suggested = (self.path.with_suffix(NB_EXT) if self.path
                     else Path.home() / (default_name + NB_EXT))
        path = self.pick_save_path(suggested)
        return path is not None and self.write_path(path)

    def open_sketch_path(self, path):
        path = Path(path)
        if path.is_dir():
            candidates = [
                path / f"{path.name}.ino",
                *sorted(path.glob("*.ino")),
                *sorted(path.glob("*.pde")),
                *sorted(path.glob("*.ipynb")),
                *sorted(path.glob(f"*{NB_EXT}")),
            ]
            for c in candidates:
                if c.is_file():
                    path = c
                    break
        if not path.is_file():
            QMessageBox.critical(self, "Cannot open example", f"Could not find example file in {path}")
            return False

        is_initial_empty = (
            len(self.notebook.cells) == 1
            and isinstance(self.notebook.cells[0], CodeCell)
            and not self.notebook.cells[0].editor.toPlainText().strip()
            and not self.notebook.cells[0].title_edit.text().strip()
            and not self.dirty
            and self.path is None
        )

        if path.suffix.lower() in (NB_EXT, ".ipynb"):
            if is_initial_empty:
                return self.load_path(path)
            try:
                text = path.read_bytes().decode("utf-8-sig")
                cells, meta, minor = parse_notebook(text)
            except Exception as e:
                QMessageBox.critical(self, "Cannot open example", f"Could not read {path}:\n\n{e}")
                return False
            for c in cells:
                ctype = c.get("type", "code")
                if ctype == "code":
                    self.notebook.add_code(
                        title=c.get("title", ""),
                        deps=c.get("deps", ""),
                        code=c.get("source", ""),
                        extra=c.get("extra"),
                    )
                else:
                    self.notebook.add_markdown(
                        text=c.get("source", ""),
                        kind=c.get("kind", "markdown"),
                        extra=c.get("extra"),
                    )
            self.set_dirty(True)
            self.update_title()
            if self.find_bar.isVisible():
                self.find_bar.refresh()
            self.log(f"Added notebook example '{path.name}' ({len(cells)} cells)")
            return True

        try:
            code = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as e:
            QMessageBox.critical(self, "Cannot open example", f"Could not read {path}:\n\n{e}")
            return False

        if is_initial_empty:
            cell = self.notebook.cells[0]
            cell.title_edit.setText(path.stem)
            cell.editor.setPlainText(code)
            self.on_selection(cell)
            self.set_dirty(False)
            self._suggested_name = path.stem
        else:
            cell = self.notebook.add_code(title=path.stem, code=code)
            self.on_selection(cell)
            self.set_dirty(True)

        ours = self.nb_meta.setdefault(NB_KEY, {})
        current_board = self.board_combo.currentText()
        if current_board and not ours.get("board"):
            ours["board"] = current_board

        self.update_title()
        if self.find_bar.isVisible():
            self.find_bar.refresh()
        cell_num = self.notebook.cells.index(cell) + 1 if cell in self.notebook.cells else len(self.notebook.cells)
        self.log(f"Opened example '{path.name}' in cell {cell_num}")
        return True

    @staticmethod
    def _scan_examples_dir(examples_dir):
        examples_dir = Path(examples_dir)
        if not examples_dir.is_dir():
            return []
        items = []
        try:
            entries = sorted(examples_dir.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return []
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                main_file = entry / f"{entry.name}.ino"
                if main_file.is_file():
                    items.append({"name": entry.name, "path": main_file, "type": "sketch"})
                else:
                    sketch_files = [p for p in entry.iterdir() if p.is_file() and p.suffix.lower() in (".ino", ".pde")]
                    if sketch_files:
                        items.append({"name": entry.name, "path": sorted(sketch_files)[0], "type": "sketch"})
                    else:
                        sub = MainWindow._scan_examples_dir(entry)
                        if sub:
                            items.append({"name": entry.name, "type": "category", "items": sub})
            elif entry.suffix.lower() in (".ino", ".pde", ".ipynb", NB_EXT):
                items.append({"name": entry.stem, "path": entry, "type": "sketch"})
        return items

    def get_board_examples(self):
        board_name = self.board_combo.currentText()
        if not board_name:
            return []
        try:
            b = self.platforms.registry.board(board_name)
            pid = b.platform_id
        except KeyError:
            pid = None
        if not pid:
            return []

        packages_dir = self.env.ARDUINO_DATA / "packages"
        packager, arch = pid.split(":", 1) if ":" in pid else (pid, pid)
        hw_dir = packages_dir / packager / "hardware" / arch
        if not hw_dir.is_dir():
            return []

        installed = self.platforms.installed_platforms()
        ver = installed.get(pid)
        plat_dir = None
        if ver and (hw_dir / str(ver)).is_dir():
            plat_dir = hw_dir / str(ver)
        else:
            dirs = [d for d in sorted(hw_dir.iterdir()) if d.is_dir()]
            if dirs:
                plat_dir = dirs[-1]
        if not plat_dir:
            return []

        items = []
        libs_dir = plat_dir / "libraries"
        if libs_dir.is_dir():
            try:
                for lib in sorted(libs_dir.iterdir(), key=lambda p: p.name.lower()):
                    if not lib.name.startswith(".") and (lib / "examples").is_dir():
                        exs = self._scan_examples_dir(lib / "examples")
                        if exs:
                            items.append({"name": lib.name, "type": "category", "items": exs})
            except OSError:
                pass

        if (plat_dir / "examples").is_dir():
            top_exs = self._scan_examples_dir(plat_dir / "examples")
            if top_exs:
                items.extend(top_exs)

        return items

    def get_installed_library_examples(self):
        lib_root = self.env.ARDUINO_LIBRARIES
        if not lib_root.is_dir():
            return []
        items = []
        try:
            for lib in sorted(lib_root.iterdir(), key=lambda p: p.name.lower()):
                if not lib.name.startswith(".") and (lib / "examples").is_dir():
                    exs = self._scan_examples_dir(lib / "examples")
                    if exs:
                        items.append({"name": lib.name, "type": "category", "items": exs})
        except OSError:
            pass
        return items

    def get_notebook_examples(self):
        nb_root = self.env.APP_ROOT / "Example Notebooks"
        if not nb_root.is_dir():
            return []
        items = []
        try:
            candidates = sorted(nb_root.glob("*.ipynb")) + sorted(nb_root.glob(f"*{NB_EXT}"))
            for p in candidates:
                if not p.name.startswith("."):
                    items.append({"name": p.stem, "path": p, "type": "sketch"})
        except OSError:
            pass
        return items

    def _add_example_menu_item(self, menu, item):
        if item.get("type") == "category":
            submenu = menu.addMenu(item["name"])
            for sub_item in item.get("items", []):
                self._add_example_menu_item(submenu, sub_item)
        elif item.get("type") == "sketch":
            action = menu.addAction(item["name"])
            path = item.get("path")
            action.triggered.connect(lambda _checked=False, p=path: self.open_sketch_path(p))

    def populate_examples_menu(self):
        if not hasattr(self, "examples_menu") or self.examples_menu is None:
            return
        self.examples_menu.clear()

        # Section 1: Board Examples
        board_name = self.board_combo.currentText()
        board_title = f"Board Examples ({board_name})" if board_name else "Board Examples"
        self.examples_menu.addSection(board_title)

        board_exs = self.get_board_examples()
        if board_exs:
            for item in board_exs:
                self._add_example_menu_item(self.examples_menu, item)
        else:
            action = self.examples_menu.addAction(
                "No board examples available" if board_name else "No board selected")
            action.setEnabled(False)

        # Section 2: Installed Libraries Examples
        self.examples_menu.addSeparator()
        self.examples_menu.addSection("Installed Libraries Examples")

        lib_exs = self.get_installed_library_examples()
        if lib_exs:
            for item in lib_exs:
                self._add_example_menu_item(self.examples_menu, item)
        else:
            action = self.examples_menu.addAction("No installed library examples")
            action.setEnabled(False)

        # Section 3: Notebook Examples (if available)
        nb_exs = self.get_notebook_examples()
        if nb_exs:
            self.examples_menu.addSeparator()
            self.examples_menu.addSection("Notebook Examples")
            for item in nb_exs:
                self._add_example_menu_item(self.examples_menu, item)

    # ------------------------------------------------- toolbar / menu helpers
    def round_button(self, icon, tip, slot):
        b = QToolButton()
        b.setObjectName("round")
        b.setIcon(make_icon(icon))
        b.setIconSize(QSize(34, 34))
        b.setFixedSize(34, 34)
        b.setToolTip(tip)
        b.clicked.connect(lambda: slot())
        return b

    def add_action(self, menu, text, slot, shortcut=None):
        act = QAction(text, self)
        if shortcut:
            if isinstance(shortcut, (list, tuple)):
                act.setShortcuts([QKeySequence(s) for s in shortcut])
            else:
                act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(lambda: slot())
        menu.addAction(act)
        return act

    def _active_editor_widget(self):
        w = QApplication.focusWidget()
        while w and w is not self:
            if isinstance(w, (QPlainTextEdit, QTextEdit, QLineEdit)):
                return w
            w = w.parent()
        cell = self.notebook.current
        if cell is not None:
            if isinstance(cell, CodeCell) and hasattr(cell, "editor"):
                return cell.editor
            if isinstance(cell, MarkdownCell) and hasattr(cell, "view") and not getattr(cell, "preview", False):
                return cell.view
        for c in self.notebook.cells:
            if isinstance(c, CodeCell) and hasattr(c, "editor"):
                return c.editor
            if isinstance(c, MarkdownCell) and hasattr(c, "view") and not getattr(c, "preview", False):
                return c.view
        return None

    def undo(self):
        target = self._active_editor_widget()
        if target is not None and hasattr(target, "undo"):
            target.undo()

    def redo(self):
        target = self._active_editor_widget()
        if target is not None and hasattr(target, "redo"):
            target.redo()

    def toggle_comment(self):
        target = self._active_editor_widget()
        if target is not None and hasattr(target, "toggle_comment"):
            target.toggle_comment()
        elif self.notebook.current is not None and hasattr(self.notebook.current, "editor"):
            self.notebook.current.editor.toggle_comment()

    def current_cell(self):
        cell = self.notebook.current
        if cell is None:
            QMessageBox.information(self, "No cell selected",
                                    "Click inside a code cell first, then use the toolbar.")
        return cell

    def verify_current(self):
        cell = self.current_cell()
        if cell is not None:
            self.compile_cell(cell)

    def upload_current(self):
        cell = self.current_cell()
        if cell is not None:
            self.upload_cell(cell)

    def show_current(self):
        cell = self.current_cell()
        if cell is not None:
            self.show_generated(cell)

    def show_serial_tab(self):
        self.show_bottom_panel(1)
        if not self.serial:
            self.connect_serial()

    def hide_bottom_panel(self):
        sizes = self.main_splitter.sizes()
        if len(sizes) > 1 and sizes[1] > 0:
            self._bottom_panel_size = sizes[1]
        total = max(sum(sizes), self.main_splitter.height(), 1)
        self.main_splitter.setSizes([total, 0])

    def show_bottom_panel(self, tab_index=None):
        if tab_index is not None:
            self.bottom_tabs.setCurrentIndex(tab_index)
        sizes = self.main_splitter.sizes()
        if len(sizes) > 1 and sizes[1] <= 0:
            total = max(sum(sizes), self.main_splitter.height(), 1)
            bottom = min(max(self._bottom_panel_size, 160), max(160, int(total * 0.6)))
            self.main_splitter.setSizes([max(1, total - bottom), bottom])

    def on_selection(self, cell):
        if cell is None:
            self.target_label.setText("No code cell selected")
            return
        n = self.notebook.code_cells().index(cell) + 1
        title = cell.title_edit.text().strip() or "Untitled"
        self.target_label.setText(f"Cell {n}  ·  {title}")

    def _on_board_changed(self, text):
        if text:
            settings = QSettings("EmbeddedNotebook", "EmbeddedNotebook")
            settings.setValue("selected_board", text)
        self.update_target_status()
        if hasattr(self, "populate_examples_menu"):
            self.populate_examples_menu()

    def update_target_status(self, *_):
        board = self.board_combo.currentText()
        port = self.port_combo.currentData()
        self.target_status.setText((f"{board} on {port}" if port else f"{board}  (no port)")
                       if board else "No installed board")

    # ---------------------------------------------------------------- helpers
    def log(self, text, end="\n"):
        self.log_view.moveCursor(QTextCursor.End)
        self.log_view.insertPlainText(text + end)
        self.log_view.moveCursor(QTextCursor.End)

    def set_busy(self, busy, text=None):
        for w in self.busy_widgets:
            w.setEnabled(not busy)
        self.progress.setRange(0, 0 if busy else 1)     # 0,0 = animated bar
        self.progress.setValue(0)
        self.status.setText(text or ("Working..." if busy else "Ready"))

    def board(self):
        return BOARDS.get(self.board_combo.currentText())

    # ------------------------------------------------------- toolchain manager
    def refresh_boards(self):
        selected = self.board_combo.currentText()
        installed = self.platforms.installed_platforms()
        custom_boards = self.platforms.discover_installed_boards(installed)
        for name, b in REGISTRY.boards.items():
            plat = REGISTRY.platforms.get(b.platform_id)
            url = plat.package_url if plat else None
            BOARDS[name] = (b.fqbn, b.platform_id, url)

        builtin_names = [name for name, board in REGISTRY.boards.items()
                         if board.platform_id in installed and name not in custom_boards]
        names = builtin_names + [b for b in custom_boards if b not in builtin_names]

        settings = QSettings("EmbeddedNotebook", "EmbeddedNotebook")
        saved = settings.value("selected_board", None)

        target = None
        if selected and selected in names:
            target = selected
        elif saved and saved in names:
            target = saved
        else:
            for n in names:
                if n == "NodeMCU 0.9" or n.lower().startswith("nodemcu 0.9"):
                    target = n
                    break
            if not target and names:
                target = names[0]

        self.board_combo.blockSignals(True)
        self.board_combo.clear()
        self.board_combo.addItems(names)
        if target and target in names:
            self.board_combo.setCurrentText(target)
        self.board_combo.blockSignals(False)

        current = self.board_combo.currentText()
        if current:
            settings.setValue("selected_board", current)

        if hasattr(self, "target_status"):
            self.update_target_status()
        if hasattr(self, "populate_examples_menu"):
            self.populate_examples_menu()

    def refresh_cli(self):
        self.cli = str(self.cli_mgr.path()) if self.cli_mgr.is_installed() else None

    def first_run_setup(self):
        if not self.cli_mgr.is_installed() or not self.env.is_initialized():
            self.open_toolchain_manager(first_run=True)

    def open_toolchain_manager(self, first_run=False):
        if self.proc is not None:
            return
        dlg = ToolchainManagerDialog(self, self.env, self.cli_mgr, self.platforms, first_run)
        dlg.exec()
        self.refresh_cli()
        self.refresh_boards()
        self.update_target_status()

    def open_library_manager(self):
        if self.proc is not None:
            return
        if self.library_manager_dialog is None:
            self.library_manager_dialog = LibraryManagerDialog(self, self.platforms)
        self._show_manager_window(self.library_manager_dialog)

    @staticmethod
    def _show_manager_window(dialog):
        if dialog.isMinimized():
            dialog.showNormal()
        else:
            dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def open_boards_manager(self):
        if self.proc is not None:
            return
        if self.boards_manager_dialog is not None:
            self._show_manager_window(self.boards_manager_dialog)
            return
        self.refresh_cli()
        if not self.cli:
            self.open_toolchain_manager(first_run=True)
            self.refresh_cli()
        if not self.cli:
            return
        self.boards_manager_dialog = BoardsManagerDialog(self, self.platforms)
        self.boards_manager_dialog.finished.connect(
            lambda _result: (self.refresh_boards(), self.update_target_status()))
        self._show_manager_window(self.boards_manager_dialog)

    def ensure_ready(self, action):
        """True if the selected board's platform is installed; else explain + offer the manager."""
        self.refresh_cli()
        board_name = self.board_combo.currentText()
        if not board_name:
            msg = "No installed boards are available. Install an MCU core in Boards Manager."
            ok = False
        else:
            ok, msg = self.platforms.check_ready(board_name)
        if ok:
            return True
        box = QMessageBox.question(self, f"Cannot {action}",
                                   msg + "\n\nOpen Boards Manager now?")
        self.log(msg)
        if box == QMessageBox.Yes:
            self.open_boards_manager()
        return False

    def refresh_ports(self):
        # Built-in serial ports (/dev/ttyS*) report hwid "n/a"; real boards don't
        ports = sorted((p for p in list_ports.comports() if p.hwid != "n/a"),
                       key=lambda p: p.device)
        current = [(p.device, p.description) for p in ports]
        if current == self._known_ports:
            return
        self._known_ports = current
        selected = self.port_combo.currentData()
        self.port_combo.clear()
        for dev, desc in current:
            self.port_combo.addItem(f"{dev} - {desc}", dev)
        idx = self.port_combo.findData(selected)
        if idx >= 0:
            self.port_combo.setCurrentIndex(idx)
        self.update_target_status()

    def generate(self, cell):
        """Merge the cell + its dependencies into one sketch. Returns source or None."""
        cells = self.notebook.code_cells()
        target = cells.index(cell)
        try:
            source, order = build_sketch([c.data() for c in cells], target)
        except ValueError as e:
            QMessageBox.warning(self, "Cannot build cell", str(e))
            return None
        self.log(f"\nBuilding cell {target + 1} from cells: "
                 f"{', '.join(str(i + 1) for i in order)}")
        return source

    def write_sketch(self, source):
        # Arduino requires the folder name to match the .ino name
        d = self.platforms.sketch_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "notebook_cell.ino").write_text(source, encoding="utf-8")
        return d

    # ------------------------------------------------------- arduino-cli runner
    def run_sequence(self, cmds, on_done=None, busy_text=None):
        self.show_bottom_panel(0)
        self.refresh_cli()
        if not self.cli:
            QMessageBox.warning(self, "arduino-cli missing",
                                "The local Arduino CLI is not installed. "
                                "Open Tools > Boards Manager to install it.")
            return
        if self.proc is not None:
            return
        self.queue = list(cmds)
        self.on_done = on_done
        self.set_busy(True, busy_text)
        self._next()

    def _next(self):
        args = self.queue.pop(0)
        self.log(f"$ {self.env.relpath(self.cli)} {' '.join(args)}")
        p = QProcess(self)
        self.proc = p
        penv = QProcessEnvironment()
        for k, v in self.cli_mgr.process_env().items():
            penv.insert(k, v)
        p.setProcessEnvironment(penv)
        p.setProcessChannelMode(QProcess.MergedChannels)
        p.readyRead.connect(
            lambda: self.log(bytes(p.readAll()).decode(errors="replace"), end=""))
        p.finished.connect(lambda code, _status: self._proc_finished(code))
        p.errorOccurred.connect(
            lambda err: self._proc_finished(-1) if err == QProcess.FailedToStart else None)
        p.start(self.cli, self.cli_mgr.base_args() + args)

    def _proc_finished(self, code):
        if self.proc is None:
            return
        self.proc.deleteLater()
        self.proc = None
        if code != 0:
            self.queue.clear()
            self.log(f"\nFAILED (exit code {code})")
            self._finish(code)
        elif self.queue:
            self._next()
        else:
            self.log("\nDONE")
            self._finish(0)

    def _finish(self, code):
        self.set_busy(False, "Ready" if code == 0 else "Failed - see build log")
        cb, self.on_done = self.on_done, None
        if cb:
            cb(code)

    # ------------------------------------------------------------- actions
    def install_core(self):
        self.open_toolchain_manager()

    def show_generated(self, cell):
        source = self.generate(cell)
        if source is not None:
            n = self.notebook.code_cells().index(cell) + 1
            SourceDialog(self, f"Generated sketch for cell {n}", source, self.mono).exec()

    def compile_cell(self, cell):
        if self.proc is not None:
            return
        self.show_bottom_panel(0)
        if not self.ensure_ready("compile"):
            return
        source = self.generate(cell)
        if source is None:
            return
        d = self.write_sketch(source)
        self.run_sequence([self.platforms.compile_args(self.board_combo.currentText(), d)],
                          busy_text="Compiling...")

    def upload_cell(self, cell):
        if self.proc is not None:
            return
        self.show_bottom_panel(0)
        port = self.port_combo.currentData()
        if not port:
            QMessageBox.information(self, "No port", "Connect a board and press Refresh.")
            return
        if not self.ensure_ready("upload"):
            return
        source = self.generate(cell)
        if source is None:
            return
        d = self.write_sketch(source)

        # The serial port can only be open in one place: release it for the flash.
        resume = self.serial is not None
        if resume:
            self.disconnect_serial()
        self.notebook.mark_running(None)

        def done(code):
            if code == 0:
                self.notebook.mark_running(cell)
            if resume:   # give the board a moment to reboot before reopening
                QTimer.singleShot(1500, self.connect_serial)

        self.run_sequence(
            [self.platforms.compile_args(self.board_combo.currentText(), d, port)],
            on_done=done, busy_text="Compiling and uploading...")

    # ---------------------------------------------------------------- serial
    def toggle_serial(self):
        if self.serial:
            self.disconnect_serial()
        else:
            self.connect_serial()

    def connect_serial(self):
        if self.serial or self.proc is not None:
            return
        port = self.port_combo.currentData()
        if not port:
            return
        w = SerialWorker(port, int(self.baud_combo.currentText()))
        w.line.connect(self.on_serial_line)
        w.error.connect(self.on_serial_error)
        self.serial = w
        w.start()
        self.ser_btn.setText("Disconnect")

    def disconnect_serial(self):
        if self.serial:
            self.serial.stop()
            self.serial = None
        self.ser_btn.setText("Connect")

    def on_serial_line(self, text):
        self.ser_view.appendPlainText(f"{time.strftime('%H:%M:%S')}  {text}")

    def on_serial_error(self, msg):
        self.ser_view.appendPlainText(f"[{msg}]")
        self.disconnect_serial()

    def send_serial(self):
        if self.serial and self.ser_input.text():
            self.serial.send(self.ser_input.text() + "\n")
            self.ser_view.appendPlainText(f"> {self.ser_input.text()}")
            self.ser_input.clear()

    def closeEvent(self, event):
        if not self.maybe_save():
            event.ignore()
            return
        for dialog in (self.boards_manager_dialog, self.library_manager_dialog):
            worker = dialog.worker if dialog is not None else None
            if worker is not None and worker.isRunning():
                QMessageBox.information(self, "Package operation in progress",
                                        "Wait for the package operation to finish before closing Embedded Notebook.")
                event.ignore()
                return
        self.disconnect_serial()
        if self.install_worker is not None and self.install_worker.isRunning():
            self.install_worker.cancel()          # stop cleanly; a half-done install is resumable
            self.install_worker.wait(5000)
        # Only the generated sketch is disposable; cores, libraries and downloads are kept.
        shutil.rmtree(self.platforms.sketch_dir(), ignore_errors=True)
        super().closeEvent(event)

