"""
Theme definitions, tokens, stylesheet generation, and icon painting.
"""
import re
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap

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

# Theming tokens
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

# Code editor + syntax colours: Arduino IDE 2 "Light (Arduino)"
CODE_BG = "#FFFFFF"      # editor.background
CODE_FG = "#434F54"      # default token foreground
CODE_GUTTER = "#F7F9F9"  # editorWidget.background
CODE_SEL = "#A5DBDC"     # editor.selectionBackground
CODE_GUIDE = "#98ACAD"   # indentation guide
SYN_TYPE = "#00979D"     # storage / support: void int const ... Serial HIGH LOW, 'c'
SYN_FUNC = "#D35400"     # entity.name.function / function calls: setup() delay() pinMode()
SYN_FLOW = "#728E00"     # keyword.control: if else for while return, and #include/#define
SYN_CONST = "#005C5F"    # constants: numbers, true/false, "strings", <Header.h>
SYN_NUM = "#005C5F"
SYN_STR = "#005C5F"
SYN_PP_FUNC = "#9E846D"  # macro name after #define
SYN_COMMENT = "#AAB7B8"  # comments

_TOKEN_NAMES = (
    "TEAL TEAL_DARK TEAL_HOVER ORANGE BAR BORDER TEXT CANVAS BG ACCENT_TEXT MUTED FAINT "
    "SURFACE DIS_FG DIS_BORDER DIS_ROUND HOVER1 HOVER2 SCROLL SEL LOG_BG LOG_FG RUN_GREEN "
    "RUN_ACCENT WARN FIND_ALL FIND_CUR FIND_FG CODE_BG CODE_FG CODE_GUTTER CODE_SEL CODE_GUIDE SYN_TYPE "
    "SYN_FUNC SYN_FLOW SYN_CONST SYN_NUM SYN_STR SYN_PP_FUNC SYN_COMMENT"
).split()

_LIGHT = {n: globals()[n] for n in _TOKEN_NAMES}
_DARK = dict(
    TEAL="#00A9B0", TEAL_DARK="#0B4A4D", TEAL_HOVER="#00838A", ORANGE="#E8813A",
    BAR="#2B383B", BORDER="#43555A", TEXT="#DDE7E7", CANVAS="#161E20", BG="#1F2A2D",
    ACCENT_TEXT="#5FD3D9", MUTED="#A9BCBC", FAINT="#8FA5A5", SURFACE="#253236",
    DIS_FG="#7A8F8F", DIS_BORDER="#3B4B4F", DIS_ROUND="#4B6062", HOVER1="#3A4B4F",
    HOVER2="#33444A", SCROLL="#4F6469", SEL="#1D5C61", LOG_BG="#11191B", LOG_FG="#EAF2F2",
    RUN_GREEN="#5FD68F", RUN_ACCENT="#3CB371", WARN="#FF8A80", FIND_ALL="#5C5220",
    FIND_CUR="#9A5A16", FIND_FG="#FFFFFF",
    CODE_BG="#1F272A", CODE_FG="#DAE3E3", CODE_GUTTER="#171E21", CODE_SEL="#105457",
    CODE_GUIDE="#546F76",
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
    globals().update(tokens)
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
    import sys
    for mod in list(sys.modules.values()):
        if hasattr(mod, "__file__") and mod.__file__ and ("embedded_notebook2" in str(mod.__file__) or "scripts" in str(mod.__file__)):
            mod.__dict__.update(tokens)
            mod.__dict__["CURRENT_THEME"] = name
            mod.__dict__["STYLESHEET"] = STYLESHEET


_ICON_CACHE = {}


def make_icon(kind, color="#ffffff"):
    """Paint and cache toolbar icons for maximum performance."""
    key = (kind, color)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
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
    elif kind in ("tv", "visualize"):
        # TV icon: screen rectangle, stand, and rabbit-ear antennas
        p.drawRoundedRect(QRectF(pt(.18, .28), pt(.82, .72)), 4, 4)
        p.drawLine(pt(.40, .72), pt(.34, .82))
        p.drawLine(pt(.60, .72), pt(.66, .82))
        p.drawLine(pt(.30, .82), pt(.70, .82))
        # Antennas
        p.drawLine(pt(.50, .28), pt(.34, .14))
        p.drawLine(pt(.50, .28), pt(.66, .14))
    p.end()
    icon = QIcon(pm)
    _ICON_CACHE[key] = icon
    return icon
