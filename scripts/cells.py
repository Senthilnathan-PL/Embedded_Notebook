"""
Notebook cell widgets: CodeCell, MarkdownCell, CellBase, and Notebook container.
"""
import copy
from PySide6.QtCore import QEvent, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from scripts.common import qt_pos_fn
from scripts.editor import AutoEditor, CppHighlighter
from scripts.theme import (
    ACCENT_TEXT, BG, BORDER, FIND_ALL, FIND_CUR, FIND_FG,
    MUTED, RUN_ACCENT, RUN_GREEN, TEAL, TEAL_HOVER, make_icon,
)


def replace_in_document(doc, text, spans, repl):
    """Replace spans (Python indices into `text`) inside a QTextDocument as ONE undo step."""
    qp = qt_pos_fn(text)
    cur = QTextCursor(doc)
    cur.beginEditBlock()
    for a, b in reversed(spans):
        cur.setPosition(qp(a))
        cur.setPosition(qp(b), QTextCursor.KeepAnchor)
        cur.insertText(repl)
    cur.endEditBlock()


def apply_find_highlights(widget, text, spans, current):
    """Paint Find matches on a QPlainTextEdit/QTextEdit via extra selections."""
    if widget is None:
        return
    qp = qt_pos_fn(text)
    sels = []
    for sp in spans:
        sel = QTextEdit.ExtraSelection()
        c = QTextCursor(widget.document())
        c.setPosition(qp(sp[0]))
        c.setPosition(qp(sp[1]), QTextCursor.KeepAnchor)
        sel.cursor = c
        sel.format.setBackground(QColor(FIND_CUR if sp == current else FIND_ALL))
        sel.format.setForeground(QColor(FIND_FG))
        sels.append(sel)
    set_find_highlights = getattr(widget, "set_find_highlights", None)
    if set_find_highlights is None:
        widget.setExtraSelections(sels)
    else:
        set_find_highlights(sels)


class CellBase(QFrame):
    up_req = Signal()
    down_req = Signal()
    del_req = Signal()
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.extra = {}
        self.setObjectName("cell")
        self.setFrameShape(QFrame.NoFrame)
        self._selected = False
        self._running = False
        self._apply_style()

    def _apply_style(self):
        color = TEAL if self._selected else BORDER
        width = 2 if self._selected else 1
        accent = f"border-left: 5px solid {RUN_ACCENT};" if self._running else ""
        self.setStyleSheet(f"#cell {{ background: {BG}; border: {width}px solid {color}; "
                           f"{accent} border-radius: 4px; }}")

    def _move_buttons(self):
        out = []
        for text, sig, tip in (("▲", self.up_req, "Move up"), ("▼", self.down_req, "Move down"),
                               ("✕", self.del_req, "Delete cell")):
            b = QPushButton(text)
            b.setObjectName("move")
            b.setFixedWidth(28)
            b.setToolTip(tip)
            b.clicked.connect(sig)
            out.append(b)
        return out


class CodeCell(CellBase):
    compile_req = Signal(object)
    upload_req = Signal(object)
    show_req = Signal(object)
    selected = Signal(object)

    def __init__(self, mono, title="", deps="", code=""):
        super().__init__()
        self.num_label = QLabel()
        self.title_edit = QLineEdit(title)
        self.title_edit.setPlaceholderText("Cell title (e.g. Debounce)")
        self.deps_edit = QLineEdit(deps)
        self.deps_edit.setPlaceholderText("Cell numbers or titles, e.g. Blink, 3")
        self.editor = AutoEditor(code, mono)
        self.editor.setPlaceholderText("Write Arduino code here...")
        self.highlighter = CppHighlighter(self.editor.document())
        self.run_label = QLabel("")

        head = QHBoxLayout()
        head.addWidget(self.num_label)
        head.addWidget(self.title_edit, 1)
        comp_b = QToolButton()
        comp_b.setObjectName("flat")
        comp_b.setIcon(make_icon("verify", ACCENT_TEXT))
        comp_b.setIconSize(QSize(20, 20))
        comp_b.setFixedSize(30, 30)
        comp_b.setToolTip("Verify / compile this cell")
        comp_b.setAccessibleName("Verify")
        up_b = QToolButton()
        up_b.setObjectName("flat")
        up_b.setIcon(make_icon("upload", ACCENT_TEXT))
        up_b.setIconSize(QSize(20, 20))
        up_b.setFixedSize(30, 30)
        up_b.setToolTip("Upload this cell to the selected board")
        up_b.setAccessibleName("Upload")
        comp_b.clicked.connect(lambda: (self.selected.emit(self), self.compile_req.emit(self)))
        up_b.clicked.connect(lambda: (self.selected.emit(self), self.upload_req.emit(self)))
        for b in (comp_b, up_b):
            head.addWidget(b)
        for b in self._move_buttons():
            head.addWidget(b)

        deps_row = QHBoxLayout()
        self.deps_label = QLabel("Depends on:")
        deps_row.addWidget(self.deps_label)
        deps_row.addWidget(self.deps_edit, 1)

        foot = QHBoxLayout()
        foot.addWidget(self.run_label)
        foot.addStretch()

        lay = QVBoxLayout(self)
        lay.addLayout(head)
        lay.addLayout(deps_row)
        lay.addWidget(self.editor)
        lay.addLayout(foot)

        for w in (self.title_edit, self.deps_edit, self.editor):
            w.installEventFilter(self)

        self.editor.textChanged.connect(self.changed)
        self.title_edit.textChanged.connect(self.changed)
        self.deps_edit.textChanged.connect(self.changed)
        self._style()

    def _style(self):
        self.num_label.setStyleSheet(
            f"background: {TEAL_HOVER}; color: white; font-weight: bold; "
            "border-radius: 3px; padding: 2px 8px;")
        self.title_edit.setStyleSheet(
            "QLineEdit { border: 1px solid transparent; background: transparent; "
            "font-weight: bold; }"
            f"QLineEdit:hover, QLineEdit:focus {{ border-color: {TEAL}; background: {BG}; }}")
        self.editor.apply_theme()
        self.run_label.setStyleSheet(f"color: {RUN_GREEN}; font-weight: bold;")
        self.deps_label.setStyleSheet(f"color: {MUTED};")

    def retheme(self):
        self._style()
        self._apply_style()
        self.highlighter.retheme()
        self.editor._update_bracket_highlights()
        self.editor.gutter.update()

    def find_text(self):
        return self.editor.toPlainText()

    def find_widget(self):
        return self.editor

    def prepare_find(self):
        pass

    def set_highlights(self, spans, current):
        apply_find_highlights(self.editor, self.find_text(), spans, current)

    def replace_spans(self, spans, repl):
        replace_in_document(self.editor.document(), self.find_text(), spans, repl)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.FocusIn:
            self.selected.emit(self)
        return super().eventFilter(obj, ev)

    def mousePressEvent(self, ev):
        self.selected.emit(self)
        super().mousePressEvent(ev)

    def set_number(self, n):
        self.num_label.setText(f"CELL {n}")

    def set_selected(self, on):
        self._selected = on
        self._apply_style()

    def set_running(self, running):
        self._running = running
        self._apply_style()
        self.run_label.setText("● running on board" if running else "")

    def data(self):
        return {"title": self.title_edit.text().strip() or "Untitled",
                "deps": self.deps_edit.text(),
                "code": self.editor.toPlainText()}


class MarkdownCell(CellBase):
    """Markdown cell. kind="raw" is an nbformat raw cell: kept, shown as plain text, never rendered."""

    def __init__(self, mono, text="", kind="markdown"):
        super().__init__()
        self.kind = kind
        self.text = text
        self.preview = kind == "markdown" and bool(text.strip())
        self._rendering = False
        self.view = QTextEdit()
        self.view.setFont(mono)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setPlaceholderText("Write Markdown here..." if kind == "markdown"
                                     else "Raw cell")
        self.toggle_btn = QPushButton("Edit")
        self.toggle_btn.clicked.connect(self.toggle)
        self.md_label = QLabel("MARKDOWN" if kind == "markdown" else "RAW")
        head = QHBoxLayout()
        head.addWidget(self.md_label)
        head.addStretch()
        if kind == "markdown":
            head.addWidget(self.toggle_btn)
        for b in self._move_buttons():
            head.addWidget(b)
        lay = QVBoxLayout(self)
        lay.addLayout(head)
        lay.addWidget(self.view)
        self._render()
        self.view.textChanged.connect(self._on_edit)
        self._style()

    def _style(self):
        self.md_label.setStyleSheet(f"color: {MUTED}; font-weight: bold;")

    def retheme(self):
        self._style()
        self._apply_style()
        if self.preview:
            self._render()

    def get_text(self):
        return self.text if self.preview else self.view.toPlainText()

    def _on_edit(self):
        if not self._rendering and not self.preview:
            self._fit()
            self.changed.emit()

    def toggle(self):
        if not self.preview:
            self.text = self.view.toPlainText()
        self.preview = not self.preview
        self._render()

    def _render(self):
        self._rendering = True
        try:
            if self.preview:
                self.view.setReadOnly(True)
                self.view.setMarkdown(self.text)
                self.toggle_btn.setText("Edit")
            else:
                self.view.setReadOnly(False)
                self.view.setPlainText(self.text)
                self.toggle_btn.setText("Preview")
        finally:
            self._rendering = False
        self._fit()

    def _fit(self):
        if self.preview:
            doc = self.view.document()
            doc.setTextWidth(max(self.view.viewport().width(), 200))
            self.view.setFixedHeight(max(int(doc.size().height()) + 14, 40))
        else:
            lines = self.view.document().blockCount()
            line_height = self.view.fontMetrics().lineSpacing()
            self.view.setFixedHeight(max(140, line_height * (lines + 2) + 20))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._fit)

    def find_text(self):
        return self.get_text()

    def find_widget(self):
        return None if self.preview else self.view

    def prepare_find(self):
        if self.preview:
            self.toggle()

    def set_highlights(self, spans, current):
        if not self.preview:
            apply_find_highlights(self.view, self.find_text(), spans, current)

    def replace_spans(self, spans, repl):
        if not self.preview:
            replace_in_document(self.view.document(), self.find_text(), spans, repl)
            return
        t = self.text
        for a, b in reversed(spans):
            t = t[:a] + repl + t[b:]
        self.text = t
        self._render()
        self.changed.emit()


class Notebook(QScrollArea):
    compile_req = Signal(object)
    upload_req = Signal(object)
    show_req = Signal(object)
    selection_changed = Signal(object)
    modified = Signal()

    def __init__(self, mono):
        super().__init__()
        self.mono = mono
        self.cells = []
        self.current = None
        self._loading = False
        self.setWidgetResizable(True)
        inner = QWidget()
        inner.setObjectName("nbinner")
        self.vbox = QVBoxLayout(inner)
        self.vbox.setContentsMargins(14, 14, 14, 14)
        self.vbox.setSpacing(12)
        self.vbox.addStretch()
        self.setWidget(inner)

    def code_cells(self):
        return [c for c in self.cells if isinstance(c, CodeCell)]

    def _add(self, w, scroll=True):
        self.cells.append(w)
        w.changed.connect(self.modified)
        self.vbox.insertWidget(self.vbox.count() - 1, w)
        w.up_req.connect(lambda: self.move(w, -1))
        w.down_req.connect(lambda: self.move(w, +1))
        w.del_req.connect(lambda: self.remove(w))
        if isinstance(w, CodeCell):
            w.compile_req.connect(self.compile_req)
            w.upload_req.connect(self.upload_req)
            w.show_req.connect(self.show_req)
            w.selected.connect(self.select)
            w.title_edit.textChanged.connect(
                lambda _t: self.selection_changed.emit(self.current) if self.current is w else None)
        if not self._loading:
            self.renumber()
        if isinstance(w, CodeCell) and self.current is None:
            self.select(w)
        if scroll:
            QTimer.singleShot(80, lambda: self.verticalScrollBar().setValue(
                self.verticalScrollBar().maximum()))
        if not self._loading:
            self.modified.emit()
        return w

    def add_code(self, title="", deps="", code="", extra=None, scroll=True):
        w = CodeCell(self.mono, title, deps, code)
        w.extra = extra or {}
        return self._add(w, scroll)

    def add_markdown(self, text="", kind="markdown", extra=None, scroll=True):
        w = MarkdownCell(self.mono, text, kind)
        w.extra = extra or {}
        return self._add(w, scroll)

    def load_cells(self, items):
        """Replace every cell with `items` (the dicts parse_notebook returns)."""
        self.setUpdatesEnabled(False)
        self._loading = True
        try:
            for w in self.cells:
                self.vbox.removeWidget(w)
                w.hide()
                w.deleteLater()
            self.cells = []
            self.current = None
            for it in items:
                if it["type"] == "code":
                    self.add_code(it["title"], it["deps"], it["source"], it["extra"], scroll=False)
                else:
                    self.add_markdown(it["source"], it["type"], it["extra"], scroll=False)
        finally:
            self._loading = False
            self.setUpdatesEnabled(True)
        self.renumber()
        if self.current is None:
            self.selection_changed.emit(None)
        QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(0))

    def export_cells(self):
        out = []
        for w in self.cells:
            if isinstance(w, CodeCell):
                out.append({"type": "code", "source": w.editor.toPlainText(),
                            "title": w.title_edit.text().strip(), "deps": w.deps_edit.text().strip(),
                            "extra": w.extra})
            else:
                out.append({"type": w.kind, "source": w.get_text(), "title": "", "deps": "",
                            "extra": w.extra})
        return out

    def retheme(self):
        for w in self.cells:
            w.retheme()

    def select(self, cell):
        self.current = cell
        for c in self.code_cells():
            c.set_selected(c is cell)
        self.selection_changed.emit(cell)

    def renumber(self):
        for n, c in enumerate(self.code_cells(), 1):
            c.set_number(n)
        self.selection_changed.emit(self.current)

    def move(self, w, delta):
        i = self.cells.index(w)
        j = i + delta
        if not 0 <= j < len(self.cells):
            return
        self.cells.insert(j, self.cells.pop(i))
        self.vbox.removeWidget(w)
        self.vbox.insertWidget(j, w)
        self.renumber()
        self.modified.emit()

    def remove(self, w):
        if QMessageBox.question(self, "Delete cell", "Delete this cell?") != QMessageBox.Yes:
            return
        was_current = w is self.current
        self.cells.remove(w)
        self.vbox.removeWidget(w)
        w.deleteLater()
        if was_current:
            self.current = None
        self.renumber()
        if was_current:
            cs = self.code_cells()
            self.select(cs[0] if cs else None)
        self.modified.emit()

    def mark_running(self, cell):
        for c in self.code_cells():
            c.set_running(c is cell)

