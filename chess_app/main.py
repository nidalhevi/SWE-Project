"""Run with: python main.py"""

import sys

from PySide6.QtWidgets import QApplication

from main_window import MainWindow



def main() -> int:
    app = QApplication(sys.argv)

    window = MainWindow()
    window.show()

    # The event loop receives clicks, redraw requests, and other events.
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())