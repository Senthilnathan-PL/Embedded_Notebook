"""
Notebook cell widgets: CodeCell, MarkdownCell, CellBase, and Notebook container.
"""
import base64
from pathlib import Path
import re
import uuid

from PySide6.QtCore import QBuffer, QEvent, QIODevice, QSize, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QImage, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from scripts.common import qt_pos_fn
from scripts.editor import AutoEditor, CppHighlighter
from scripts.media import (
    MarkdownDocument, VideoPlayerWidget, GifPlayer,
    cache_attachment_video, encode_file_to_attachment,
    extract_video_sources, extract_gif_sources, get_attachment_bytes,
    is_image_file, is_video_file,
)
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
    """Markdown cell with support for attaching and rendering images and videos."""

    def __init__(self, mono, text="", kind="markdown", extra=None, notebook_dir=None):
        super().__init__()
        self.extra = extra or {}
        self.notebook_dir = notebook_dir
        self.kind = kind
        self.text = text
        self.preview = kind == "markdown" and bool(text.strip())
        self._rendering = False
        self.video_players = []
        self.gif_players = []

        self.view = QTextEdit()
        self.doc = MarkdownDocument(lambda: self, parent=self.view)
        self.view.setDocument(self.doc)
        self.view.setFont(mono)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setPlaceholderText("Write Markdown here..." if kind == "markdown"
                                     else "Raw cell")
        self.view.installEventFilter(self)

        self.toggle_btn = QPushButton("Edit")
        self.toggle_btn.clicked.connect(self.toggle)
        self.md_label = QLabel("MARKDOWN" if kind == "markdown" else "RAW")

        head = QHBoxLayout()
        head.addWidget(self.md_label)
        head.addStretch()
        if kind == "markdown":
            self.attach_btn = QPushButton("Attach Media")
            self.attach_btn.setToolTip("Attach an image or video to this markdown cell")
            self.attach_btn.clicked.connect(self.prompt_attach_media)
            head.addWidget(self.attach_btn)
            head.addWidget(self.toggle_btn)
        for b in self._move_buttons():
            head.addWidget(b)

        lay = QVBoxLayout(self)
        lay.addLayout(head)
        lay.addWidget(self.view)

        # Embedded media players for videos
        self.media_container = QWidget()
        self.media_layout = QVBoxLayout(self.media_container)
        self.media_layout.setContentsMargins(0, 4, 0, 0)
        self.media_layout.setSpacing(8)
        lay.addWidget(self.media_container)

        self.setAcceptDrops(True)

        self._render()
        self.view.textChanged.connect(self._on_edit)
        self._style()

    def _style(self):
        self.md_label.setStyleSheet(f"color: {MUTED}; font-weight: bold;")

    def retheme(self):
        self._style()
        self._apply_style()
        for p in self.video_players:
            p.retheme()
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

    def prompt_attach_media(self):
        """Open file dialog to attach images or videos."""
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Attach Image or Video",
            str(self.notebook_dir) if self.notebook_dir else "",
            "Supported Media (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.svg *.ico *.mp4 *.webm *.mkv *.avi *.mov);;"
            "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.svg *.ico);;"
            "Videos (*.mp4 *.webm *.mkv *.avi *.mov);;"
            "All Files (*)",
        )
        if not paths:
            return
        for p in paths:
            self.attach_file(p)

    def attach_file(self, filepath: str | Path):
        """Encode file into cell's attachments dictionary and insert markdown tag."""
        try:
            filename, mime, b64_str = encode_file_to_attachment(filepath)
        except Exception as e:
            QMessageBox.warning(self, "Attachment Error", f"Could not read {filepath}:\n{e}")
            return

        atts = self.extra.setdefault("attachments", {})
        base_name = filename
        idx = 1
        stem = Path(filename).stem
        ext = Path(filename).suffix
        while filename in atts and atts[filename] != {mime: b64_str}:
            filename = f"{stem}_{idx}{ext}"
            idx += 1

        atts[filename] = {mime: b64_str}

        if is_video_file(filename):
            tag = f'\n\n<video src="attachment:{filename}" controls></video>\n'
        else:
            tag = f"\n\n![{filename}](attachment:{filename})\n"

        if self.preview:
            self.text = self.text.rstrip() + tag
            self._render()
        else:
            cur = self.view.textCursor()
            if cur.position() == 0 and not self.view.toPlainText().strip():
                self.view.setPlainText(tag.strip() + "\n")
            else:
                cur.insertText(tag)
            self.text = self.view.toPlainText()
            self._fit()

        self.changed.emit()
        return filename

    def attach_image_object(self, qimg: QImage, name_hint="pasted_image"):
        """Encode QImage from clipboard or screenshot into cell attachments."""
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        qimg.save(buf, "PNG")
        raw = bytes(buf.data())
        b64_str = base64.b64encode(raw).decode("ascii")
        filename = f"{name_hint}_{uuid.uuid4().hex[:6]}.png"
        atts = self.extra.setdefault("attachments", {})
        atts[filename] = {"image/png": b64_str}
        tag = f"\n\n![{filename}](attachment:{filename})\n"

        if self.preview:
            self.text = self.text.rstrip() + tag
            self._render()
        else:
            cur = self.view.textCursor()
            cur.insertText(tag)
            self.text = self.view.toPlainText()
            self._fit()

        self.changed.emit()

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            for u in ev.mimeData().urls():
                if u.isLocalFile():
                    p = u.toLocalFile()
                    if is_image_file(p) or is_video_file(p):
                        ev.acceptProposedAction()
                        return
        super().dragEnterEvent(ev)

    def dropEvent(self, ev):
        if ev.mimeData().hasUrls():
            added = False
            for u in ev.mimeData().urls():
                if u.isLocalFile():
                    p = u.toLocalFile()
                    if is_image_file(p) or is_video_file(p):
                        self.attach_file(p)
                        added = True
            if added:
                ev.acceptProposedAction()
                return
        super().dropEvent(ev)

    def eventFilter(self, obj, ev):
        if obj is self.view and ev.type() == QEvent.KeyPress:
            if ev.key() == Qt.Key_V and (ev.modifiers() & Qt.ControlModifier):
                cb = QApplication.clipboard()
                md = cb.mimeData()
                if md and md.hasImage():
                    qimg = cb.image()
                    if not qimg.isNull():
                        self.attach_image_object(qimg)
                        return True
        return super().eventFilter(obj, ev)

    def _on_delete_video(self, player_widget):
        if QMessageBox.question(
            self, "Remove Video",
            f"Remove '{player_widget.name}' from this cell?",
            QMessageBox.Yes | QMessageBox.No,
        ) != QMessageBox.Yes:
            return

        name = player_widget.name
        atts = self.extra.get("attachments", {})
        if name in atts:
            del atts[name]

        # Clean markdown tags referencing this attachment
        text = self.get_text()
        text = re.sub(rf'<video[^>]*src=["\']attachment:{re.escape(name)}["\'][^>]*>.*?</video>', '', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(rf'<video[^>]*src=["\']attachment:{re.escape(name)}["\'][^>]*>', '', text, flags=re.IGNORECASE)
        text = re.sub(rf'\[.*?\]\(attachment:{re.escape(name)}\)', '', text)
        text = re.sub(rf'!\[.*?\]\(attachment:{re.escape(name)}\)', '', text)
        self.text = text.strip()
        if not self.preview:
            self.view.setPlainText(self.text)
        self._render()
        self.changed.emit()

    def _render(self):
        self._rendering = True
        try:
            for player in self.video_players:
                player.release()
                self.media_layout.removeWidget(player)
                player.deleteLater()
            self.video_players = []
            for gp in self.gif_players:
                gp.release()
            self.gif_players = []

            if self.preview:
                self.view.setReadOnly(True)
                doc = self.view.document()
                if hasattr(doc, "clear_cache"):
                    doc.clear_cache()
                self.view.setMarkdown(self.text)

                # Explicitly register attachment image resources
                atts = self.extra.get("attachments", {})
                if isinstance(atts, dict):
                    for fname in atts:
                        if is_image_file(fname):
                            _, raw = get_attachment_bytes(atts, fname)
                            if raw:
                                qimg = QImage()
                                if qimg.loadFromData(raw):
                                    doc.addResource(QTextDocument.ImageResource, QUrl(f"attachment:{fname}"), qimg)
                                    doc.addResource(QTextDocument.ImageResource, QUrl(fname), qimg)

                # Scan and build animated GIF players
                gif_sources = extract_gif_sources(self.text, atts, base_dir=self.notebook_dir)
                for gs in gif_sources:
                    gp = GifPlayer(
                        doc=doc,
                        view=self.view,
                        src=gs["src"],
                        file_path=gs["file_path"],
                        raw_bytes=gs["raw_bytes"],
                        on_first_frame=self._fit,
                        parent=self,
                    )
                    gp.start()
                    self.gif_players.append(gp)

                # Scan and build video player widgets
                video_sources = extract_video_sources(self.text, atts)
                for vs in video_sources:
                    cached_file = None
                    if vs["is_attachment"]:
                        _, raw = get_attachment_bytes(atts, vs["name"])
                        if raw:
                            cached_file = cache_attachment_video(vs["name"], raw)
                    else:
                        cand = Path(vs["src"])
                        if not cand.is_file() and self.notebook_dir:
                            cand = Path(self.notebook_dir) / vs["src"]
                        if cand.is_file():
                            cached_file = cand

                    player_w = VideoPlayerWidget(
                        src=vs["src"],
                        name=vs["name"],
                        is_attachment=vs["is_attachment"],
                        local_file=cached_file,
                        parent=self.media_container,
                    )
                    player_w.delete_req.connect(self._on_delete_video)
                    self.media_layout.addWidget(player_w)
                    self.video_players.append(player_w)

                self.media_container.setVisible(bool(self.video_players))
                self.toggle_btn.setText("Edit")
            else:
                self.media_container.setVisible(False)
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

    def release(self):
        """Release media players and resources cleanly."""
        for gp in self.gif_players:
            gp.release()
        self.gif_players.clear()
        for player in self.video_players:
            player.release()


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
        self.notebook_dir = None
        self._loading = False
        self.setWidgetResizable(True)
        inner = QWidget()
        inner.setObjectName("nbinner")
        self.vbox = QVBoxLayout(inner)
        self.vbox.setContentsMargins(14, 14, 14, 14)
        self.vbox.setSpacing(12)
        self.vbox.addStretch()
        self.setWidget(inner)

    def set_notebook_path(self, path):
        """Set the notebook directory for resolving relative media paths."""
        self.notebook_dir = Path(path).parent if path else None
        for c in self.cells:
            if isinstance(c, MarkdownCell):
                c.notebook_dir = self.notebook_dir

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
        w = MarkdownCell(self.mono, text, kind, extra=extra, notebook_dir=self.notebook_dir)
        return self._add(w, scroll)

    def load_cells(self, items):
        """Replace every cell with `items` (the dicts parse_notebook returns)."""
        self.setUpdatesEnabled(False)
        self._loading = True
        try:
            for w in self.cells:
                if hasattr(w, "release"):
                    w.release()
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
        if hasattr(w, "release"):
            w.release()
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

