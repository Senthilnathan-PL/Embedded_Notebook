"""
Embedded Notebook package.
"""
from scripts.common import _mask, matching_bracket, qt_pos_fn
from scripts.theme import (
    apply_theme, resolve_theme, make_icon, CURRENT_THEME, THEMES, THEME_MODES,
    TEAL, TEAL_DARK, TEAL_HOVER, ORANGE, BAR, BORDER, TEXT, CANVAS, BG,
    ACCENT_TEXT, MUTED, FAINT, SURFACE, DIS_FG, DIS_BORDER, DIS_ROUND, HOVER1,
    HOVER2, SCROLL, SEL, LOG_BG, LOG_FG, RUN_GREEN, RUN_ACCENT, WARN, FIND_ALL,
    FIND_CUR, FIND_FG, CODE_BG, CODE_FG, CODE_GUTTER, CODE_SEL, CODE_GUIDE,
    SYN_TYPE, SYN_FUNC, SYN_FLOW, SYN_CONST, SYN_NUM, SYN_STR, SYN_PP_FUNC,
    SYN_COMMENT, STYLESHEET, build_stylesheet,
)
from scripts.sketch_builder import (
    build_sketch, split_cell, resolve_order,
)
from scripts.notebook_format import (
    parse_notebook, serialize_notebook, ensure_notebook_suffix,
    new_notebook_metadata, NotebookFormatError, NB_EXT, NB_EXTS, NB_KEY, NB_MINOR,
)
from scripts.serial_worker import SerialWorker
from scripts.editor import (
    CodeEditor, LineNumberArea, CppHighlighter, AutoEditor,
)
from scripts.cells import (
    Notebook, CodeCell, MarkdownCell, CellBase,
    replace_in_document, apply_find_highlights,
)
from scripts.dialogs import (
    FindBar, SourceDialog, ToolchainManagerDialog, LibraryManagerDialog,
    BoardsManagerDialog, InstallWorker, LibraryWorker, PackageTaskPanel,
)
from scripts.main_window import (
    MainWindow, REGISTRY, BOARDS,
)
from scripts.main import main

__all__ = [
    "main", "MainWindow", "Notebook", "CodeCell", "MarkdownCell", "CellBase",
    "CodeEditor", "LineNumberArea", "CppHighlighter", "AutoEditor",
    "FindBar", "SourceDialog", "ToolchainManagerDialog", "LibraryManagerDialog",
    "BoardsManagerDialog", "InstallWorker", "LibraryWorker", "PackageTaskPanel",
    "SerialWorker", "build_sketch", "split_cell", "resolve_order",
    "parse_notebook", "serialize_notebook", "ensure_notebook_suffix",
    "new_notebook_metadata", "NotebookFormatError", "REGISTRY", "BOARDS",
    "apply_theme", "resolve_theme", "make_icon", "CURRENT_THEME", "THEMES",
    "THEME_MODES", "STYLESHEET", "matching_bracket", "qt_pos_fn",
]

