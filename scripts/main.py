#!/usr/bin/env python3
"""
Embedded Notebook main launcher.
"""
import sys
from PySide6.QtWidgets import QApplication

from scripts.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow(prompt_setup=True)
    win.show()
    if len(sys.argv) > 1:
        win.load_path(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

