#!/usr/bin/env python3
"""
Embedded Notebook main launcher.
"""
import sys
from pathlib import Path
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from scripts.main_window import MainWindow


def _get_app_icon() -> QIcon | None:
    root = Path(__file__).resolve().parent.parent
    candidates = [
        root / "Windows" / "embeddednotebook.ico",
        root / "Linux" / "embeddednotebook.png",
        root / "embeddednotebook.ico",
        root / "embeddednotebook.png",
    ]
    for p in candidates:
        if p.is_file():
            return QIcon(str(p))
    return None


def main():
    print("=" * 60, flush=True)
    print("  Embedded Notebook - Console Logger", flush=True)
    print("  Live log stream active. Close this window or app to exit.", flush=True)
    print("=" * 60, flush=True)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    icon = _get_app_icon()
    if icon:
        app.setWindowIcon(icon)
    win = MainWindow(prompt_setup=False)
    if icon:
        win.setWindowIcon(icon)
    win.show()
    if len(sys.argv) > 1:
        win.load_path(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
