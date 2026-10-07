#!/usr/bin/env python3
"""
Embedded Notebook - Arduino IDE 2 style interactive notebook.
This file serves as the main application entry point and backward-compatible facade.
Core implementations are modularized under `scripts/`.
"""
import sys
from pathlib import Path

# Add project root to sys.path so scripts can be imported from anywhere
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from PySide6.QtCore import (
    QEvent, QProcessEnvironment, QPointF, QProcess, QRect, QSettings, QSize,
    QThread, QTimer, Qt, Signal,
)
from PySide6.QtGui import (
    QAction, QColor, QFont, QIcon, QKeySequence, QPainter, QPalette, QPen,
    QPixmap, QActionGroup, QShortcut, QSyntaxHighlighter, QTextCharFormat,
    QTextCursor, QKeyEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QProgressBar,
    QScrollArea, QSplitter, QTabWidget, QTextEdit, QToolButton, QVBoxLayout,
    QWidget,
)

import scripts.toolchain as tc
from scripts.common import _mask, matching_bracket, qt_pos_fn
import scripts.theme as _theme
from scripts.theme import (
    apply_theme, resolve_theme, make_icon, THEMES, THEME_MODES, build_stylesheet,
)
from scripts.sketch_builder import build_sketch, split_cell, resolve_order
from scripts.notebook_format import (
    parse_notebook, serialize_notebook, ensure_notebook_suffix,
    new_notebook_metadata, NotebookFormatError, NB_EXT, NB_EXTS, NB_KEY, NB_MINOR,
)
from scripts.serial_worker import SerialWorker
from scripts.editor import CodeEditor, LineNumberArea, CppHighlighter, AutoEditor
from scripts.cells import (
    Notebook, CodeCell, MarkdownCell, CellBase,
    replace_in_document, apply_find_highlights,
)
from scripts.dialogs import (
    FindBar, SourceDialog, ToolchainManagerDialog, LibraryManagerDialog,
    BoardsManagerDialog, InstallWorker, LibraryWorker, PackageTaskPanel,
)
from scripts.main_window import MainWindow, REGISTRY, BOARDS
from scripts.main import main


def __getattr__(name):
    if hasattr(_theme, name):
        return getattr(_theme, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(list(globals().keys()) + dir(_theme))

if __name__ == "__main__":
    sys.exit(main())
