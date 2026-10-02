#!/usr/bin/env python3
"""
Embedded Notebook - prototype 3 (Arduino IDE 2 look)
Multi-cell notebook + dependency-based sketch merging + arduino-cli + serial monitor.

Setup:
    pip install PySide6 pyserial
    arduino-cli is NOT required on PATH: Embedded Notebook keeps its own copy, cores,
    libraries and build files in a project-local ".embedded/" folder next to this script
    (Tools > Boards Manager). See embedded_toolchain.py.

Run:
    python embedded_notebook2.py [notebook.icpnb]

Files
-----
Notebooks are saved as ".icpnb": exactly the Jupyter ".ipynb" JSON (nbformat 4), only
the extension differs. ".ipynb" files can be opened too. See "Notebook files" below.

How cells combine
-----------------
Every code cell is written like a normal Arduino program: globals, functions,
and optionally setup() / loop(). A cell can list other cells in "Depends on"
(by number or title). When you Upload / Compile a cell, ONE sketch is built from:
  * #include lines of all involved cells (deduplicated)
  * globals + functions of every dependency, dependencies first
  * setup() bodies of every dependency, then of the cell itself
  * loop() of ONLY the cell you uploaded
"""
import copy
from html import escape
import json
import os
import re
import shutil
import sys
import textwrap
import time
import uuid
from pathlib import Path

import serial
from serial.tools import list_ports
from PySide6.QtCore import (QEvent, QProcessEnvironment, QPointF, QProcess, QRect, QSettings, QSize, QThread, QTimer,
                            Qt, Signal)
from PySide6.QtGui import (
    QAction, QColor, QFont, QIcon, QKeySequence, QPainter, QPalette, QPen, QPixmap,
    QActionGroup, QShortcut, QSyntaxHighlighter, QTextCharFormat, QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QProgressBar, QScrollArea,
    QSplitter, QTabWidget, QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import embedded_toolchain as tc      # noqa: E402  (environment, registry, arduino-cli, cores)
from embedded_toolchain import ESP32_URL  # noqa: E402,F401

# The board registry is the single source of truth (selector, installer, compile, status).
REGISTRY = tc.BoardRegistry()
# Legacy view kept for compatibility: name -> (fqbn, core, additional_urls)
BOARDS = {b.name: (b.fqbn, b.platform_id, REGISTRY.platform(b.platform_id).package_url)
          for b in REGISTRY.boards.values()}

# --------------------------------------------------------------------------
# Arduino IDE 2 look: colours, stylesheet, painted icons
# --------------------------------------------------------------------------
TEAL = "#00979D"
TEAL_DARK = "#005C5F"
TEAL_HOVER = "#00777C"
ORANGE = "#D35400"
BAR = "#DAE3E3"          # toolbar / tab strip / menu bar
BORDER = "#C4CFCF"
TEXT = "#2B3A3A"
CANVAS = "#EEF2F2"       # notebook background behind the cells
# --- tokens added for theming (values below are the original light-theme literals) ---
BG = "#FFFFFF"           # cells, editors, inputs, menus
ACCENT_TEXT = "#005C5F"  # teal used as *text* (button labels, links)
MUTED = "#4A5A5A"        # secondary labels
FAINT = "#5F7070"        # comments, line numbers, placeholders
SURFACE = "#F3F6F6"      # gutter, disabled button background
DIS_FG = "#6F7F7F"
DIS_BORDER = "#B8C4C4"
DIS_ROUND = "#7E9494"
HOVER1 = "#C6D4D4"
HOVER2 = "#E3EBEB"
SCROLL = "#B6C4C4"
SEL = "#B4E0E2"          # text selection
LOG_BG = "#1F2B2E"
LOG_FG = "#EAF2F2"
RUN_GREEN = "#1E6B40"
RUN_ACCENT = "#3CB371"
WARN = "#B3261E"
FIND_ALL = "#F9E79F"     # Find: every match
FIND_CUR = "#F5A25D"     # Find: current match
FIND_FG = "#2B3A3A"      # text colour on top of Find highlights
# --- code editor + syntax colours: Arduino IDE 2 "Light (Arduino)" (default.color-theme.json) ---
CODE_BG = "#FFFFFF"      # editor.background
CODE_FG = "#434F54"      # default token foreground
CODE_GUTTER = "#F7F9F9"  # editorWidget.background
CODE_SEL = "#A5DBDC"     # editor.selectionBackground #7fcbcdb3 blended on white
CODE_GUIDE = "#D5DEDF"   # indentation guide
SYN_TYPE = "#00979D"     # storage / support: void int const ... Serial HIGH LOW, 'c'
SYN_FUNC = "#D35400"     # entity.name.function / function calls: setup() delay() pinMode()
SYN_FLOW = "#728E00"     # keyword.control: if else for while return, and #include/#define
SYN_CONST = "#005C5F"    # constants: numbers, true/false, "strings", <Header.h>
SYN_NUM = "#005C5F"
SYN_STR = "#005C5F"
SYN_PP_FUNC = "#9E846D"  # macro name after #define
SYN_COMMENT = "#AAB7B8"  # #95a5a6cc blended on white

_TOKEN_NAMES = ("TEAL TEAL_DARK TEAL_HOVER ORANGE BAR BORDER TEXT CANVAS BG ACCENT_TEXT MUTED FAINT "
                "SURFACE DIS_FG DIS_BORDER DIS_ROUND HOVER1 HOVER2 SCROLL SEL LOG_BG LOG_FG RUN_GREEN "
                "RUN_ACCENT WARN FIND_ALL FIND_CUR FIND_FG CODE_BG CODE_FG CODE_GUTTER CODE_SEL CODE_GUIDE SYN_TYPE "
                "SYN_FUNC SYN_FLOW SYN_CONST SYN_NUM SYN_STR SYN_PP_FUNC SYN_COMMENT").split()

# To add a theme: copy a dict below, change the values, register it in THEMES.
_LIGHT = {n: globals()[n] for n in _TOKEN_NAMES}
_DARK = dict(
    TEAL="#00A9B0", TEAL_DARK="#0B4A4D", TEAL_HOVER="#00838A", ORANGE="#E8813A",
    BAR="#2B383B", BORDER="#43555A", TEXT="#DDE7E7", CANVAS="#161E20", BG="#1F2A2D",
    ACCENT_TEXT="#5FD3D9", MUTED="#A9BCBC", FAINT="#8FA5A5", SURFACE="#253236",
    DIS_FG="#7A8F8F", DIS_BORDER="#3B4B4F", DIS_ROUND="#4B6062", HOVER1="#3A4B4F",
    HOVER2="#33444A", SCROLL="#4F6469", SEL="#1D5C61", LOG_BG="#11191B", LOG_FG="#EAF2F2",
    RUN_GREEN="#5FD68F", RUN_ACCENT="#3CB371", WARN="#FF8A80", FIND_ALL="#5C5220",
    FIND_CUR="#9A5A16", FIND_FG="#FFFFFF",
    # Arduino IDE 2 "Dark (Arduino)" (dark.color-theme.json)
    CODE_BG="#1F272A", CODE_FG="#DAE3E3", CODE_GUTTER="#171E21", CODE_SEL="#105457",
    CODE_GUIDE="#354246",
    SYN_TYPE="#0CA1A6", SYN_FUNC="#F39C12", SYN_FLOW="#C586C0", SYN_CONST="#7FCBCD",
    SYN_NUM="#7FCBCD", SYN_STR="#7FCBCD", SYN_PP_FUNC="#569CD6", SYN_COMMENT="#7F8C8D",
)
THEMES = {"Light": _LIGHT, "Dark": _DARK}
THEME_MODES = ("Auto", "Light", "Dark")
CURRENT_THEME = "Light"

_QSS = """
QWidget { color: @TEXT@; }
QMainWindow, QDialog { background: @BG@; }
QLabel { background: transparent; }
QToolTip { background: @TEAL_DARK@; color: white; border: none; padding: 4px 6px; }

QMenuBar { background: @BAR@; color: @TEXT@; padding: 2px 6px; }
QMenuBar::item { padding: 4px 10px; background: transparent; border-radius: 3px; }
QMenuBar::item:selected { background: @TEAL_HOVER@; color: white; }
QMenu { background: @BG@; color: @TEXT@; border: 1px solid @BORDER@; padding: 4px 0; }
QMenu::item { padding: 6px 30px 6px 24px; }
QMenu::item:selected { background: @TEAL_HOVER@; color: white; }
QMenu::item:disabled { color: @DIS_FG@; }
QMenu::separator { height: 1px; background: @BORDER@; margin: 4px 0; }

#toolbar { background: @BAR@; border-bottom: 1px solid @BORDER@; }
#strip { background: @BAR@; border-top: 1px solid @BORDER@; border-bottom: 1px solid @BORDER@; }

QToolButton#round { background: @TEAL@; border: none; border-radius: 17px; }
QToolButton#round:hover { background: @TEAL_HOVER@; }
QToolButton#round:pressed { background: @TEAL_DARK@; }
QToolButton#round:disabled { background: @DIS_ROUND@; }
QToolButton#flat { background: transparent; border: none; border-radius: 17px; }
QToolButton#flat:hover { background: @HOVER1@; }

QComboBox { background: @BG@; color: @TEXT@; border: 1px solid @BORDER@; border-radius: 3px;
            padding: 4px 8px; min-height: 20px; }
QComboBox:hover, QComboBox:focus { border-color: @TEAL@; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: @BG@; color: @TEXT@; border: 1px solid @BORDER@; outline: 0;
                              selection-background-color: @TEAL@; selection-color: white; }

QLineEdit { background: @BG@; color: @TEXT@; border: 1px solid @BORDER@; border-radius: 3px;
            padding: 4px 6px; selection-background-color: @TEAL@; selection-color: white; }
QLineEdit:focus { border-color: @TEAL@; }

QPushButton { background: @BG@; color: @ACCENT_TEXT@; border: 1px solid @TEAL@;
              border-radius: 3px; padding: 4px 12px; }
QPushButton:hover { background: @TEAL_HOVER@; color: white; }
QPushButton:pressed { background: @TEAL_DARK@; color: white; }
QPushButton:disabled { background: @SURFACE@; color: @DIS_FG@; border-color: @DIS_BORDER@; }
QPushButton#primary { background: @TEAL_HOVER@; color: white; }
QPushButton#primary:hover { background: @TEAL_DARK@; }
QPushButton#primary:disabled { background: @SURFACE@; border-color: @DIS_BORDER@; color: @DIS_FG@; }
QPushButton#move { background: transparent; color: @MUTED@; border: none; padding: 2px 4px; }
QPushButton#move:hover { background: @HOVER2@; color: @ACCENT_TEXT@; }
QPushButton#quiet { background: transparent; border: 1px solid transparent; color: @ACCENT_TEXT@; }
QPushButton#quiet:hover { background: @BG@; border-color: @TEAL@; color: @ACCENT_TEXT@; }

QScrollArea { border: none; background: @CANVAS@; }
#nbinner { background: @CANVAS@; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 0; }
QScrollBar::handle:vertical { background: @SCROLL@; border-radius: 5px; min-height: 30px; margin: 2px; }
QScrollBar::handle:vertical:hover { background: @TEAL@; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 0; }
QScrollBar::handle:horizontal { background: @SCROLL@; border-radius: 5px; min-width: 30px; margin: 2px; }
QScrollBar::handle:horizontal:hover { background: @TEAL@; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QPlainTextEdit, QTextEdit { background: @BG@; color: @TEXT@; border: none;
                            selection-background-color: @SEL@; selection-color: @TEXT@; }

#packageTaskPanel { background: @SURFACE@; border-top: 1px solid @BORDER@; }
#packageTaskStatus { font-weight: bold; }
#packageTaskFile { color: @MUTED@; }
#packageTaskOutput { background: @LOG_BG@; color: @LOG_FG@; border: 1px solid @BORDER@; }
#packageTaskPanel QProgressBar { border: 1px solid @BORDER@; background: @BAR@;
                                min-height: 10px; max-height: 10px; }
#packageTaskPanel QProgressBar::chunk { background: @TEAL@; }

QTabWidget::pane { border: none; border-top: 1px solid @BORDER@; }
QTabBar { background: @BAR@; }
QTabBar::tab { background: @BAR@; color: @MUTED@; padding: 7px 18px; border-top: 2px solid transparent; }
QTabBar::tab:selected { background: @BG@; color: @TEXT@; border-top: 2px solid @TEAL@; }
QTabBar::tab:hover:!selected { background: @HOVER2@; }

QProgressBar { border: none; background: @BAR@; min-height: 3px; max-height: 3px; }
QProgressBar::chunk { background: @TEAL@; }

QSplitter::handle { background: @BORDER@; }
QSplitter::handle:vertical { height: 1px; }

QStatusBar { background: @TEAL_DARK@; }
QStatusBar::item { border: none; }
QStatusBar QLabel { color: white; padding: 2px 8px; }
#findbar { background: @BAR@; border-bottom: 1px solid @BORDER@; }
QCheckBox { background: transparent; spacing: 5px; }
"""

def build_stylesheet(tokens):
    return re.sub(r"@(\w+)@", lambda m: tokens[m.group(1)], _QSS)


STYLESHEET = build_stylesheet(_LIGHT)


def resolve_theme(mode, color_scheme):
    if mode in THEMES:
        return mode
    return "Dark" if color_scheme == Qt.ColorScheme.Dark else "Light"


def apply_theme(app, name):
    """Switch every module-level colour token, the palette and the application stylesheet."""
    global STYLESHEET, CURRENT_THEME
    tokens = THEMES[name]
    globals().update(tokens)            # existing code reads TEAL, BORDER ... at call time
    CURRENT_THEME = name
    STYLESHEET = build_stylesheet(tokens)
    pal = QPalette()
    for role, col in ((QPalette.Window, BG), (QPalette.WindowText, TEXT), (QPalette.Base, BG),
                      (QPalette.AlternateBase, CANVAS), (QPalette.Text, TEXT), (QPalette.Button, BG),
                      (QPalette.ButtonText, TEXT), (QPalette.ToolTipBase, TEAL_DARK),
                      (QPalette.ToolTipText, "#FFFFFF"), (QPalette.Highlight, TEAL_HOVER),
                      (QPalette.HighlightedText, "#FFFFFF"), (QPalette.PlaceholderText, FAINT),
                      (QPalette.Link, ACCENT_TEXT)):
        pal.setColor(role, QColor(col))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(DIS_FG))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)


def make_icon(kind, color="#ffffff"):
    """Paint the toolbar icons so no icon files or emoji fonts are needed."""
    S = 64
    pm = QPixmap(S, S)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color), 6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

    def pt(x, y):
        return QPointF(x * S, y * S)

    if kind == "verify":
        p.drawPolyline([pt(.26, .52), pt(.43, .68), pt(.75, .33)])
    elif kind == "upload":
        p.drawLine(pt(.24, .5), pt(.74, .5))
        p.drawPolyline([pt(.54, .28), pt(.76, .5), pt(.54, .72)])
    elif kind == "monitor":
        p.drawEllipse(pt(.44, .44), .19 * S, .19 * S)
        p.drawLine(pt(.58, .58), pt(.77, .77))
    p.end()
    return QIcon(pm)


# --------------------------------------------------------------------------
# Sketch generation (pure functions - no GUI)
# --------------------------------------------------------------------------
_FUNC_RE = re.compile(r"\bvoid\s+(setup|loop)\s*\(\s*(?:void)?\s*\)\s*\{")
_INCLUDE_RE = re.compile(r"\s*#\s*include\b")


def _mask(src):
    """Same-length copy of src with comments and string/char literals blanked."""
    out = list(src)
    n, i = len(src), 0

    def blank(a, b):
        for k in range(a, b):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            blank(i, j)
            i = j
        elif src[i] in "\"'":
            q, j = src[i], i + 1
            while j < n and src[j] != q and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            j = min(j + 1, n)
            blank(i, j)
            i = j
        else:
            i += 1
    return "".join(out)


_BRACKET_PAIRS = {"(": ")", "[": "]", "{": "}"}
_BRACKET_OPEN = {value: key for key, value in _BRACKET_PAIRS.items()}


def matching_bracket(src, index):
    """Return the matching bracket index, ignoring comments and string literals."""
    if not 0 <= index < len(src):
        return None
    masked = _mask(src)
    bracket = masked[index]
    if bracket in _BRACKET_PAIRS:
        expected = [_BRACKET_PAIRS[bracket]]
        for pos in range(index + 1, len(masked)):
            char = masked[pos]
            if char in _BRACKET_PAIRS:
                expected.append(_BRACKET_PAIRS[char])
            elif char in _BRACKET_OPEN:
                if char != expected[-1]:
                    continue
                expected.pop()
                if not expected:
                    return pos
    elif bracket in _BRACKET_OPEN:
        expected = [_BRACKET_OPEN[bracket]]
        for pos in range(index - 1, -1, -1):
            char = masked[pos]
            if char in _BRACKET_OPEN:
                expected.append(_BRACKET_OPEN[char])
            elif char in _BRACKET_PAIRS and char == expected[-1]:
                expected.pop()
                if not expected:
                    return pos
    return None


def _match_brace(masked, open_idx):
    depth = 0
    for i in range(open_idx, len(masked)):
        if masked[i] == "{":
            depth += 1
        elif masked[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def split_cell(code):
    """-> (include_lines, declarations, setup_body, loop_body)"""
    masked = _mask(code)
    bodies, spans = {}, []
    for m in _FUNC_RE.finditer(masked):
        name = m.group(1)
        if name in bodies:
            continue
        open_idx = m.end() - 1
        close = _match_brace(masked, open_idx)
        if close < 0:
            raise ValueError(f"Unbalanced braces in {name}()")
        bodies[name] = code[open_idx + 1:close]
        spans.append((m.start(), close + 1))
    rest = code
    for s, e in reversed(spans):
        rest = rest[:s] + rest[e:]
    includes, decl = [], []
    for line in rest.splitlines():
        (includes if _INCLUDE_RE.match(line) else decl).append(line)
    return (
        [l.strip() for l in includes],
        "\n".join(decl).strip(),
        bodies.get("setup", ""),
        bodies.get("loop", ""),
    )


def _split_deps(text):
    return [t.strip() for t in re.split(r"[,;]", text or "") if t.strip()]


def resolve_order(cells, target):
    """Dependency-first order of cell indices needed to build `target`."""
    def find(token, owner):
        if token.isdigit():
            n = int(token)
            if 1 <= n <= len(cells):
                return n - 1
            raise ValueError(f'Cell {owner + 1} depends on "{token}", but there is no cell {n}.')
        for i, c in enumerate(cells):
            if c["title"].strip().lower() == token.lower():
                return i
        raise ValueError(f'Cell {owner + 1} depends on "{token}", but no cell has that title.')

    order = []

    def visit(i, path):
        if i in order:
            return
        if i in path:
            chain = " -> ".join(str(p + 1) for p in path + [i])
            raise ValueError(f"Circular dependency between cells: {chain}")
        for tok in _split_deps(cells[i]["deps"]):
            visit(find(tok, i), path + [i])
        order.append(i)

    visit(target, [])
    return order


def _block(text, spaces):
    return textwrap.indent(textwrap.dedent(text).strip("\n"), " " * spaces)


def build_sketch(cells, target):
    """cells: list of {"title","deps","code"}. Returns (sketch_source, order)."""
    order = resolve_order(cells, target)
    includes, decls, setups, loop_body = [], [], [], ""
    for i in order:
        c = cells[i]
        inc, decl, setup, loop = split_cell(c["code"])
        includes += [l for l in inc if l not in includes]
        if decl:
            decls.append(f"// ===== Cell {i + 1}: {c['title']} =====\n{decl}")
        if setup.strip():
            setups.append(f"  // {c['title']}\n  {{\n{_block(setup, 4)}\n  }}")
        if i == target:
            loop_body = loop
    parts = []
    if includes:
        parts.append("\n".join(includes))
    parts += decls
    parts.append("void setup() {\n" + "\n".join(setups) + ("\n" if setups else "") + "}")
    parts.append("void loop() {\n" + (_block(loop_body, 2) + "\n" if loop_body.strip() else "") + "}")
    header = (f"// Generated from cell {target + 1} ({cells[target]['title']}); "
              f"cells used: {', '.join(str(i + 1) for i in order)}\n")
    return header + "\n\n".join(parts) + "\n", order


# --------------------------------------------------------------------------
# Notebook files: ".icpnb" is byte-for-byte the Jupyter ".ipynb" JSON (nbformat 4).
# Only the filename extension differs. Pure functions - no GUI.
#
# The two app-specific fields (cell title, "Depends on") live in each code cell's
# free-form `metadata["embedded_notebook"]`, which Jupyter tolerates and ignores.
# Everything else (ids, outputs, execution_count, attachments, other metadata,
# notebook metadata) is carried through untouched so a load/save round trip
# does not lose data.
# --------------------------------------------------------------------------
NB_EXT = ".icpnb"
NB_EXTS = (".icpnb", ".ipynb")
NB_KEY = "embedded_notebook"
NB_MINOR = 5                     # 4.5 = cells carry an "id"
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class NotebookFormatError(ValueError):
    """The file is not a usable Jupyter (nbformat 4) notebook."""


def new_notebook_metadata():
    return {"language_info": {"name": "c++"}}


def ensure_notebook_suffix(path):
    """Save As rule: keep .icpnb/.ipynb if the user typed one, otherwise append .icpnb."""
    path = Path(path)
    return path if path.suffix.lower() in NB_EXTS else path.with_name(path.name + NB_EXT)


def _source_to_str(src, where):
    if isinstance(src, str):
        return src
    if isinstance(src, list) and all(isinstance(x, str) for x in src):
        return "".join(src)
    raise NotebookFormatError(f"{where}: 'source' must be a string or a list of strings.")


def _source_to_lines(text):
    """nbformat stores source as a list of lines, each keeping its trailing newline."""
    parts = text.split("\n")
    lines = [p + "\n" for p in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def parse_notebook(text):
    """JSON text -> (cells, notebook_metadata, nbformat_minor). Raises NotebookFormatError.

    Each cell is {"type": code|markdown|raw, "source", "title", "deps", "extra"}.
    """
    try:
        nb = json.loads(text)
    except json.JSONDecodeError as e:
        raise NotebookFormatError(
            f"The file is not valid JSON: {e.msg} (line {e.lineno}, column {e.colno}).") from None
    except RecursionError:
        raise NotebookFormatError("The JSON is nested too deeply to read.") from None
    if not isinstance(nb, dict):
        raise NotebookFormatError("The top level of a notebook must be a JSON object.")
    ver = nb.get("nbformat")
    if not isinstance(ver, int) or isinstance(ver, bool):
        raise NotebookFormatError("Missing \"nbformat\" field - this is not a Jupyter notebook.")
    if ver != 4:
        raise NotebookFormatError(f"Unsupported notebook format version {ver}; only nbformat 4 "
                                  "is supported.")
    minor = nb.get("nbformat_minor", 0)
    minor = minor if isinstance(minor, int) and not isinstance(minor, bool) and minor >= 0 else 0
    meta = nb.get("metadata", {})
    if not isinstance(meta, dict):
        raise NotebookFormatError("Notebook \"metadata\" must be a JSON object.")
    raw_cells = nb.get("cells")
    if not isinstance(raw_cells, list):
        raise NotebookFormatError("Missing \"cells\" list.")

    cells = []
    for n, c in enumerate(raw_cells, 1):
        where = f"Cell {n}"
        if not isinstance(c, dict):
            raise NotebookFormatError(f"{where} is not a JSON object.")
        kind = c.get("cell_type")
        if kind not in ("code", "markdown", "raw"):
            raise NotebookFormatError(f"{where}: unknown cell_type {kind!r}.")
        source = _source_to_str(c.get("source", ""), where)
        cmeta = c.get("metadata", {})
        if not isinstance(cmeta, dict):
            raise NotebookFormatError(f"{where}: \"metadata\" must be a JSON object.")
        cmeta = copy.deepcopy(cmeta)
        title = deps = ""
        extra = {}
        if kind == "code":
            ours = cmeta.pop(NB_KEY, None)
            if isinstance(ours, dict):
                title = ours["title"] if isinstance(ours.get("title"), str) else ""
                deps = ours["deps"] if isinstance(ours.get("deps"), str) else ""
            outputs = c.get("outputs", [])
            if not isinstance(outputs, list):
                raise NotebookFormatError(f"{where}: \"outputs\" must be a list.")
            ec = c.get("execution_count")
            extra["outputs"] = copy.deepcopy(outputs)
            extra["execution_count"] = ec if isinstance(ec, int) and not isinstance(ec, bool) else None
        elif isinstance(c.get("attachments"), dict):
            extra["attachments"] = copy.deepcopy(c["attachments"])
        extra["metadata"] = cmeta
        if isinstance(c.get("id"), str):
            extra["id"] = c["id"]
        cells.append({"type": kind, "source": source, "title": title, "deps": deps, "extra": extra})
    return cells, copy.deepcopy(meta), minor


def serialize_notebook(cells, metadata, minor=NB_MINOR):
    """Inverse of parse_notebook. Same JSON style nbformat itself writes (indent=1, sorted keys)."""
    out, seen = [], set()
    for c in cells:
        ex = c.get("extra") or {}
        cid = ex.get("id")
        if not (isinstance(cid, str) and _ID_RE.match(cid)) or cid in seen:
            cid = uuid.uuid4().hex[:8]
        seen.add(cid)
        cmeta = copy.deepcopy(ex.get("metadata", {}))
        cell = {"cell_type": c["type"], "id": cid, "source": _source_to_lines(c["source"])}
        if c["type"] == "code":
            if c.get("title") or c.get("deps"):
                cmeta[NB_KEY] = {k: c[k] for k in ("title", "deps") if c.get(k)}
            cell["execution_count"] = ex.get("execution_count")
            cell["outputs"] = copy.deepcopy(ex.get("outputs", []))
        elif "attachments" in ex:
            cell["attachments"] = copy.deepcopy(ex["attachments"])
        cell["metadata"] = cmeta
        out.append(cell)
    nb = {"cells": out, "metadata": metadata, "nbformat": 4, "nbformat_minor": max(minor, NB_MINOR)}
    return json.dumps(nb, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------
# Syntax highlighting
# --------------------------------------------------------------------------
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
        # (regex, format, group). Later rules win, so comments come last.
        # Colours follow the Arduino IDE 2 themes: functions orange, storage/support teal,
        # keyword.control + directives green (light) / purple (dark), constants/strings/numbers dark teal.
        self.rules = [
            (re.compile(r"\b[A-Za-z_]\w*(?=\s*\()"), fmt(SYN_FUNC), 0),     # setup() delay() foo()
            (re.compile(types), fmt(SYN_TYPE), 0),
            (re.compile(consts), fmt(SYN_TYPE), 0),
            (re.compile(r"\b(true|false|NULL)\b"), fmt(SYN_CONST), 0),
            (re.compile(flow), fmt(SYN_FLOW), 0),
            (re.compile(r"\b\d+(\.\d+)?([fFuUlL]*)\b|\b0[xX][0-9A-Fa-f]+\b|\b0[bB][01]+\b"),
             fmt(SYN_NUM), 0),
            (re.compile(r"^\s*#\s*define\s+(\w+)"), fmt(SYN_PP_FUNC), 1),
            (re.compile(r"^\s*(#\s*\w+)"), fmt(SYN_FLOW), 1),                 # #include #define
            (re.compile(r"^\s*#\s*include\s*(<[^>\n]*>)"), fmt(SYN_STR), 1),   # <Servo.h>
            (re.compile(r"'(?:[^'\\\n]|\\.)*'"), fmt(SYN_TYPE), 0),            # 'c'
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


# --------------------------------------------------------------------------
# Serial reader thread
# --------------------------------------------------------------------------
class SerialWorker(QThread):
    line = Signal(str)
    error = Signal(str)

    def __init__(self, port, baud):
        super().__init__()
        self.port, self.baud = port, baud
        self._running = True
        self._ser = None

    def run(self):
        try:
            self._ser = serial.Serial(self.port, self.baud, timeout=0.1)
        except Exception as e:  # noqa: BLE001
            self.error.emit(f"Could not open {self.port}: {e}")
            return
        buf = b""
        while self._running:
            try:
                data = self._ser.read(256)
            except Exception as e:  # noqa: BLE001
                self.error.emit(f"Serial error: {e}")
                break
            if not data:
                continue
            buf += data
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                self.line.emit(raw.decode(errors="replace").rstrip("\r"))
        try:
            self._ser.close()
        except Exception:  # noqa: BLE001
            pass

    def send(self, text):
        if self._ser and self._ser.is_open:
            self._ser.write(text.encode())

    def stop(self):
        self._running = False
        self.wait(2000)


# --------------------------------------------------------------------------
# Notebook widgets
# --------------------------------------------------------------------------
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
        """Editor colours come from the Arduino highlight.js themes (CODE_BG / CODE_FG)."""
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

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.show_indentation_guides:
            return
        painter = QPainter(self.viewport())
        painter.setPen(QPen(QColor(CODE_GUIDE), 1, Qt.DotLine))
        space_width = max(1, self.fontMetrics().horizontalAdvance(" "))
        tab_columns = max(1, round(self.tabStopDistance() / space_width))
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        while block.isValid() and top <= self.viewport().height():
            bottom = top + round(self.blockBoundingRect(block).height())
            columns = 0
            for char in block.text():
                if char == " ":
                    columns += 1
                elif char == "\t":
                    columns += tab_columns - columns % tab_columns
                else:
                    break
            for column in range(tab_columns, columns + 1, tab_columns):
                x = round(self.document().documentMargin() + column * space_width)
                painter.drawLine(x, max(0, top), x, min(bottom, self.viewport().height()))
            block = block.next()
            top = bottom
        painter.end()

    def gutter_width(self):
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 16 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_gutter_width(self, *_):
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

    def wheelEvent(self, e):      # let the notebook scroll
        e.ignore()


_ASTRAL_RE = re.compile("[\U00010000-\U0010ffff]")


def qt_pos_fn(text):
    """Python str index -> QTextDocument position (Qt counts UTF-16 units, Python code points)."""
    if not _ASTRAL_RE.search(text):
        return lambda i: i
    return lambda i: len(text[:i].encode("utf-16-le")) // 2


def replace_in_document(doc, text, spans, repl):
    """Replace spans (Python indices into `text`) inside a QTextDocument as ONE undo step."""
    qp = qt_pos_fn(text)
    cur = QTextCursor(doc)
    cur.beginEditBlock()
    for a, b in reversed(spans):            # back to front so earlier offsets stay valid
        cur.setPosition(qp(a))
        cur.setPosition(qp(b), QTextCursor.KeepAnchor)
        cur.insertText(repl)
    cur.endEditBlock()


def apply_find_highlights(widget, text, spans, current):
    """Paint Find matches on a QPlainTextEdit/QTextEdit via extra selections (no text change)."""
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
    changed = Signal()                     # the person edited this cell

    def __init__(self):
        super().__init__()
        self.extra = {}                    # nbformat fields we carry through (id, outputs, ...)
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

        # Clicking or typing anywhere in the cell makes it the toolbar's target
        for w in (self.title_edit, self.deps_edit, self.editor):
            w.installEventFilter(self)

        # Any edit marks the document as modified (connected last: the initial text is not an edit)
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

    # --- Find / Replace interface (shared with MarkdownCell) ---
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
        self.preview = kind == "markdown" and bool(text.strip())   # empty cells open for typing
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
            self._render()                 # re-render so link colours follow the theme

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

    # --- Find / Replace interface ---
    def find_text(self):
        return self.get_text()

    def find_widget(self):
        return None if self.preview else self.view

    def prepare_find(self):
        if self.preview:                   # rendered Markdown hides the source: show it
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
    selection_changed = Signal(object)     # the code cell the toolbar acts on (or None)
    modified = Signal()                    # content or structure changed (document is dirty)

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

    # --- whole-document operations (used by File > New / Open / Save) ---
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
        m_file.addSeparator()
        self.add_action(m_file, "&Save", self.save_file, "Ctrl+S")
        self.add_action(m_file, "Save &As...", self.save_file_as, "Ctrl+Shift+S")
        m_file.addSeparator()
        self.add_action(m_file, "&Quit", self.close, "Ctrl+Q")
        m_edit = self.menuBar().addMenu("&Edit")
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
        self.board_combo.currentTextChanged.connect(self.update_target_status)
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
        suggested = (self.path.with_suffix(NB_EXT) if self.path
                     else Path.home() / ("Untitled" + NB_EXT))
        path = self.pick_save_path(suggested)
        return path is not None and self.write_path(path)

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
            act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(lambda: slot())
        menu.addAction(act)
        return act

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
        names = [name for name, board in REGISTRY.boards.items()
                 if board.platform_id in installed]
        self.board_combo.blockSignals(True)
        self.board_combo.clear()
        self.board_combo.addItems(names)
        if selected in names:
            self.board_combo.setCurrentText(selected)
        self.board_combo.blockSignals(False)
        if hasattr(self, "target_status"):
            self.update_target_status()

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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow(prompt_setup=True)
    win.show()
    if len(sys.argv) > 1:                       # python embedded_notebook2.py my.icpnb
        win.load_path(sys.argv[1])
    sys.exit(app.exec())
