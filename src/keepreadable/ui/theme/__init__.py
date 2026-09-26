from importlib.resources import files

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication


def apply_theme(app: QApplication) -> None:
    app.setFont(QFont("Segoe UI", 10))
    stylesheet = files("keepreadable.ui.theme").joinpath("style.qss").read_text(encoding="utf-8")
    app.setStyleSheet(stylesheet)
