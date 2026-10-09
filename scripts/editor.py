"""
CodeEditor, LineNumberArea, CppHighlighter, and AutoEditor widgets.
"""
import re
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPen, QSyntaxHighlighter,
    QTextCharFormat, QTextCursor,
)
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

from scripts.common import matching_bracket, qt_pos_fn
from scripts.theme import (
    BORDER, CODE_BG, CODE_FG, CODE_GUIDE, CODE_GUTTER, CODE_SEL,
    FAINT, FIND_CUR, FIND_FG, SYN_COMMENT, SYN_CONST, SYN_FLOW,
    SYN_FUNC, SYN_NUM, SYN_PP_FUNC, SYN_STR, SYN_TYPE,
)


class CppHighlighter(QSyntaxHighlighter):
    def __init__(self, doc):
        super().__init__(doc)
        self._build()

    def retheme(self):
        self._build()
        self.rehighlight()

    def _build(self):
        def fmt(color, bold=False, italic=False):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(QFont.Bold)
            f.setFontItalic(italic)
            return f

        types = (r"\b(void|int|long|float|double|char|bool|byte|const|static|unsigned|"
                 r"volatile|uint8_t|uint16_t|uint32_t|int8_t|int16_t|int32_t|String|"
                 r"boolean|class|struct|enum|typedef|auto|inline|extern|short|signed|size_t|word|"
                 r"private|public|protected|template|namespace)\b")
        flow = r"\b(if|else|for|while|do|switch|case|default|break|continue|return|goto|new|delete)\b"
        consts = r"\b(Serial\d?|Wire|SPI|HIGH|LOW|INPUT|OUTPUT|INPUT_PULLUP|LED_BUILTIN|CHANGE|RISING|FALLING)\b"
        self.rules = [
            (re.compile(r"\b[A-Za-z_]\w*(?=\s*\()"), fmt(SYN_FUNC), 0),
            (re.compile(types), fmt(SYN_TYPE), 0),
            (re.compile(consts), fmt(SYN_TYPE), 0),
            (re.compile(r"\b(true|false|NULL)\b"), fmt(SYN_CONST), 0),
            (re.compile(flow), fmt(SYN_FLOW), 0),
            (re.compile(r"\b\d+(\.\d+)?([fFuUlL]*)\b|\b0[xX][0-9A-Fa-f]+\b|\b0[bB][01]+\b"),
             fmt(SYN_NUM), 0),
            (re.compile(r"^\s*#\s*define\s+(\w+)"), fmt(SYN_PP_FUNC), 1),
            (re.compile(r"^\s*(#\s*\w+)"), fmt(SYN_FLOW), 1),
            (re.compile(r"^\s*#\s*include\s*(<[^>\n]*>)"), fmt(SYN_STR), 1),
            (re.compile(r"'(?:[^'\\\n]|\\.)*'"), fmt(SYN_TYPE), 0),
            (re.compile(r'"[^"\\]*(\\.[^"\\]*)*"'), fmt(SYN_STR), 0),
            (re.compile(r"//[^\n]*"), fmt(SYN_COMMENT, italic=True), 0),
        ]
        self.comment_fmt = fmt(SYN_COMMENT, italic=True)

    def highlightBlock(self, text):
        for rx, f, g in self.rules:
            for m in rx.finditer(text):
                if m.start(g) >= 0:
                    self.setFormat(m.start(g), m.end(g) - m.start(g), f)
        self.setCurrentBlockState(0)
        in_comment = self.previousBlockState() == 1
        start = 0 if in_comment else text.find("/*")
        while start >= 0:
            end = text.find("*/", start if in_comment and start == 0 else start + 2)
            if end < 0:
                self.setCurrentBlockState(1)
                length = len(text) - start
            else:
                length = end - start + 2
            self.setFormat(start, length, self.comment_fmt)
            start = text.find("/*", start + max(length, 1))


class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.ed = editor

    def sizeHint(self):
        return QSize(self.ed.gutter_width(), 0)

    def paintEvent(self, event):
        self.ed.paint_gutter(event)


class CodeEditor(QPlainTextEdit):
    """Plain-text editor with an Arduino-IDE-style line number gutter."""

    def __init__(self, text, mono):
        super().__init__(text)
        self.setFont(mono)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._find_highlights = []
        self._bracket_highlights = []
        self.show_indentation_guides = True
        self.gutter = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._update_bracket_highlights)
        self._update_gutter_width()
        self.apply_theme()
        self._update_bracket_highlights()

    def apply_theme(self):
        self.setStyleSheet(
            f"QPlainTextEdit {{ background: {CODE_BG}; color: {CODE_FG}; border: 1px solid {BORDER}; "
            f"selection-background-color: {CODE_SEL}; selection-color: {CODE_FG}; }}")
        self.gutter.update()
        self.viewport().update()

    def set_find_highlights(self, selections):
        self._find_highlights = selections
        self.setExtraSelections(self._find_highlights + self._bracket_highlights)

    def _update_bracket_highlights(self):
        text = self.toPlainText()
        cursor_position = self.textCursor().position()
        qt_position = qt_pos_fn(text)
        bracket_chars = set("()[]{}")
        candidate = next((i for i, char in enumerate(text)
                          if char in bracket_chars and qt_position(i + 1) == cursor_position), None)
        if candidate is None:
            candidate = next((i for i, char in enumerate(text)
                              if char in bracket_chars and qt_position(i) == cursor_position), None)

        self._bracket_highlights = []
        match = matching_bracket(text, candidate) if candidate is not None else None
        if candidate is not None and match is not None:
            for index in (candidate, match):
                selection = QTextEdit.ExtraSelection()
                selection.cursor = QTextCursor(self.document())
                selection.cursor.setPosition(qt_position(index))
                selection.cursor.setPosition(qt_position(index + 1), QTextCursor.KeepAnchor)
                selection.format.setBackground(QColor(FIND_CUR))
                selection.format.setForeground(QColor(FIND_FG))
                selection.format.setFontWeight(QFont.Bold)
                self._bracket_highlights.append(selection)
        self.setExtraSelections(self._find_highlights + self._bracket_highlights)

    @staticmethod
    def _indent_columns(text, tab_columns):
        cols = 0
        for char in text:
            if char == " ":
                cols += 1
            elif char == "\t":
                cols += tab_columns - cols % tab_columns
            else:
                break
        return cols

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.show_indentation_guides:
            return
        painter = QPainter(self.viewport())
        painter.setPen(QPen(QColor(CODE_GUIDE), 1, Qt.SolidLine))
        space_width = max(1, self.fontMetrics().horizontalAdvance(" "))
        tab_columns = max(1, round(self.tabStopDistance() / space_width))
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        while block.isValid() and top <= self.viewport().height():
            bottom = top + round(self.blockBoundingRect(block).height())
            text = block.text()
            if text.strip():
                columns = self._indent_columns(text, tab_columns)
            else:
                prev_b = block.previous()
                prev_cols, prev_text = 0, ""
                while prev_b.isValid():
                    p_txt = prev_b.text()
                    if p_txt.strip():
                        prev_text = p_txt.rstrip()
                        prev_cols = self._indent_columns(p_txt, tab_columns)
                        break
                    prev_b = prev_b.previous()

                next_b = block.next()
                next_cols = 0
                while next_b.isValid():
                    n_txt = next_b.text()
                    if n_txt.strip():
                        next_cols = self._indent_columns(n_txt, tab_columns)
                        break
                    next_b = next_b.next()

                if prev_text.endswith(("{", "(", "[", ":")):
                    columns = next_cols
                else:
                    columns = min(prev_cols, next_cols)

            for column in range(tab_columns, columns + 1, tab_columns):
                x = round(self.document().documentMargin() + column * space_width) - 16
                painter.drawLine(x, max(0, top), x, min(bottom, self.viewport().height()))
            block = block.next()
            top = bottom
        painter.end()

    def get_indent_unit(self):
        for block_num in range(min(50, self.document().blockCount())):
            txt = self.document().findBlockByNumber(block_num).text()
            m = re.match(r'^( +)\S', txt)
            if m:
                spaces = len(m.group(1))
                if spaces in (2, 4):
                    return " " * spaces
        return "  "

    def toggle_comment(self):
        cursor = self.textCursor()
        has_sel = cursor.hasSelection()
        start_pos = cursor.selectionStart()
        end_pos = cursor.selectionEnd()

        start_cursor = QTextCursor(self.document())
        start_cursor.setPosition(start_pos)
        start_block = start_cursor.block()

        end_cursor = QTextCursor(self.document())
        end_cursor.setPosition(end_pos)
        end_block = end_cursor.block()

        if has_sel and end_pos > start_pos and end_cursor.positionInBlock() == 0 and end_block != start_block:
            end_block = end_block.previous()

        start_block_num = start_block.blockNumber()
        end_block_num = end_block.blockNumber()
        start_col = start_pos - start_block.position()
        cursor_col = cursor.positionInBlock()

        blocks = []
        b = start_block
        while b.isValid():
            blocks.append(b)
            if b == end_block:
                break
            b = b.next()

        new_col = cursor_col
        if len(blocks) == 1:
            line0 = blocks[0].text()
            if re.match(r'^\s*//', line0):
                new_line = re.sub(r'^(\s*)// ?', r'\1', line0)
                delta = len(new_line) - len(line0)
                new_lines = [new_line]
                new_col = max(0, min(cursor_col + delta, len(new_line)))
            else:
                c = start_col if has_sel else cursor_col
                indent_len = len(re.match(r'^\s*', line0).group(0))
                if c <= indent_len:
                    prefix0 = line0[:indent_len]
                    code0 = line0[indent_len:]
                    new_line = prefix0 + "// " + code0
                    new_lines = [new_line]
                    new_col = indent_len + 3 if cursor_col >= indent_len else cursor_col
                else:
                    prefix0 = line0[:c]
                    suffix0 = line0[c:]
                    m0 = re.match(r'^(\s*)', suffix0)
                    lead0 = m0.group(1)
                    code0 = suffix0[len(lead0):]
                    if code0.startswith("//"):
                        new_code = re.sub(r'^// ?', '', code0)
                        new_line = prefix0 + lead0 + new_code
                        new_lines = [new_line]
                        new_col = c
                    else:
                        m_pre = re.search(r'// ?(\s*)$', prefix0)
                        if m_pre:
                            new_prefix = prefix0[:m_pre.start()] + m_pre.group(1)
                            new_line = new_prefix + suffix0
                            new_lines = [new_line]
                            new_col = len(new_prefix)
                        else:
                            new_line = prefix0 + lead0 + "// " + code0
                            new_lines = [new_line]
                            new_col = c + len(lead0) + 3
        else:
            line0 = blocks[0].text()
            prefix0 = line0[:start_col]
            suffix0 = line0[start_col:]
            m0 = re.match(r'^(\s*)', suffix0)
            lead0 = m0.group(1)
            code0 = suffix0[len(lead0):]

            check_parts = []
            if code0.strip():
                check_parts.append(code0.startswith("//"))
            for blk in blocks[1:]:
                txt = blk.text()
                if txt.strip():
                    check_parts.append(bool(re.match(r'^\s*//', txt)))

            all_commented = bool(check_parts) and all(check_parts)

            new_lines = []
            if all_commented:
                new_code0 = re.sub(r'^// ?', '', code0)
                new_lines.append(prefix0 + lead0 + new_code0)
                for blk in blocks[1:]:
                    new_lines.append(re.sub(r'^(\s*)// ?', r'\1', blk.text()))
            else:
                new_code0 = ("// " + code0) if code0.strip() else code0
                new_lines.append(prefix0 + lead0 + new_code0)
                for blk in blocks[1:]:
                    txt = blk.text()
                    if txt.strip():
                        new_lines.append(re.sub(r'^(\s*)', r'\1// ', txt))
                    else:
                        new_lines.append(txt)

        cursor.beginEditBlock()
        replacement = "\n".join(new_lines)
        replace_cursor = QTextCursor(self.document())
        replace_cursor.setPosition(start_block.position())
        replace_cursor.setPosition(end_block.position() + len(end_block.text()), QTextCursor.KeepAnchor)
        replace_cursor.insertText(replacement)

        new_start_block = self.document().findBlockByNumber(start_block_num)
        new_end_block = self.document().findBlockByNumber(end_block_num)

        final_cursor = QTextCursor(self.document())
        if has_sel:
            final_cursor.setPosition(new_start_block.position() + start_col)
            final_cursor.setPosition(new_end_block.position() + len(new_end_block.text()), QTextCursor.KeepAnchor)
        else:
            final_cursor.setPosition(new_start_block.position() + new_col)

        self.setTextCursor(final_cursor)
        cursor.endEditBlock()

    def keyPressEvent(self, event):
        if (event.modifiers() & Qt.ControlModifier) and event.key() in (Qt.Key_Slash, Qt.Key_Question):
            self.toggle_comment()
            event.accept()
            return

        mods = event.modifiers()
        has_nav_mods = bool(mods & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))

        if not has_nav_mods:
            auto_pairs = {'(': ')', '[': ']', '{': '}', '"': '"', "'": "'"}
            close_chars = {')', ']', '}', '"', "'"}

            if event.key() == Qt.Key_Backspace:
                cursor = self.textCursor()
                if not cursor.hasSelection():
                    pos = cursor.position()
                    doc = self.document()
                    if 0 < pos < doc.characterCount() - 1:
                        char_before = doc.characterAt(pos - 1)
                        char_after = doc.characterAt(pos)
                        if auto_pairs.get(char_before) == char_after:
                            cursor.beginEditBlock()
                            cursor.deletePreviousChar()
                            cursor.deleteChar()
                            cursor.endEditBlock()
                            event.accept()
                            return

            text = event.text()

            cursor = self.textCursor()
            if cursor.hasSelection() and text in auto_pairs:
                start = cursor.selectionStart()
                selected = cursor.selectedText()
                close_ch = auto_pairs[text]
                cursor.beginEditBlock()
                cursor.insertText(text + selected + close_ch)
                new_cursor = self.textCursor()
                new_cursor.setPosition(start + 1)
                new_cursor.setPosition(start + 1 + len(selected), QTextCursor.KeepAnchor)
                self.setTextCursor(new_cursor)
                cursor.endEditBlock()
                event.accept()
                return

            if text in close_chars and not cursor.hasSelection():
                pos = cursor.position()
                doc = self.document()
                if pos < doc.characterCount() - 1:
                    char_after = doc.characterAt(pos)
                    if char_after == text:
                        cursor.movePosition(QTextCursor.NextCharacter)
                        self.setTextCursor(cursor)
                        event.accept()
                        return

            if text in auto_pairs and not cursor.hasSelection():
                pos = cursor.position()
                doc = self.document()
                char_after = doc.characterAt(pos) if pos < doc.characterCount() - 1 else ''
                char_before = doc.characterAt(pos - 1) if pos > 0 else ''

                if text in ('"', "'") and (char_after.isalnum() or char_after == '_'):
                    super().keyPressEvent(event)
                    return

                if text == "'" and (char_before.isalnum() or char_before == '_'):
                    super().keyPressEvent(event)
                    return

                close_ch = auto_pairs[text]
                cursor.beginEditBlock()
                cursor.insertText(text + close_ch)
                cursor.movePosition(QTextCursor.PreviousCharacter)
                self.setTextCursor(cursor)
                cursor.endEditBlock()
                event.accept()
                return

        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            mods = event.modifiers()
            if mods == Qt.NoModifier or mods == Qt.KeypadModifier:
                cursor = self.textCursor()
                if cursor.hasSelection():
                    cursor.removeSelectedText()

                block = cursor.block()
                block_text = block.text()
                pos_in_block = cursor.positionInBlock()
                before_cursor = block_text[:pos_in_block]
                after_cursor = block_text[pos_in_block:]

                m = re.match(r'^\s*', block_text)
                current_indent = m.group(0) if m else ""
                indent_unit = self.get_indent_unit()

                bracket_pairs = [("{", "}"), ("(", ")"), ("[", "]")]
                between_brackets = any(
                    before_cursor.rstrip().endswith(op) and after_cursor.lstrip().startswith(cl)
                    for op, cl in bracket_pairs
                )

                if between_brackets:
                    cursor.beginEditBlock()
                    cursor.insertText("\n" + current_indent + indent_unit + "\n" + current_indent)
                    cursor.movePosition(QTextCursor.PreviousBlock)
                    cursor.movePosition(QTextCursor.EndOfBlock)
                    self.setTextCursor(cursor)
                    cursor.endEditBlock()
                    event.accept()
                    return

                if before_cursor.rstrip().endswith(("{", "(", "[", ":")):
                    cursor.beginEditBlock()
                    cursor.insertText("\n" + current_indent + indent_unit)
                    self.setTextCursor(cursor)
                    cursor.endEditBlock()
                    event.accept()
                    return

                cursor.beginEditBlock()
                cursor.insertText("\n" + current_indent)
                self.setTextCursor(cursor)
                cursor.endEditBlock()
                event.accept()
                return

        super().keyPressEvent(event)

    def gutter_width(self):
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 16 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_gutter_width(self):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _update_gutter(self, rect, dy):
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cr = self.contentsRect()
        self.gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, event):
        p = QPainter(self.gutter)
        p.fillRect(event.rect(), QColor(CODE_GUTTER))
        p.setPen(QColor(BORDER))
        p.drawLine(self.gutter.width() - 1, event.rect().top(),
                   self.gutter.width() - 1, event.rect().bottom())
        p.setFont(self.font())
        block = self.firstVisibleBlock()
        n = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        h = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                p.setPen(QColor(FAINT))
                p.drawText(0, top, self.gutter.width() - 8, h, Qt.AlignRight, str(n + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            n += 1
        p.end()


class AutoEditor(CodeEditor):
    """Editor that grows with its content so the notebook scrolls, not the cell."""

    def __init__(self, text, mono, min_lines=4):
        super().__init__(text, mono)
        self.min_lines = min_lines
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTabStopDistance(2 * self.fontMetrics().horizontalAdvance(" "))
        self.textChanged.connect(self._fit)
        self._fit()

    def _fit(self):
        lines = max(self.document().blockCount(), self.min_lines)
        h = (lines * self.fontMetrics().lineSpacing() + 2 * self.frameWidth()
             + int(self.document().documentMargin() * 2) + 20)
        self.setFixedHeight(h)

    def wheelEvent(self, e):
        e.ignore()

