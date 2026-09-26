from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from keepreadable.ui.dialogs.support_dialog import SupportDialog


class WelcomeScreen(QWidget):
    addArchiveRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(80, 80, 80, 80)
        layout.setSpacing(16)
        layout.addStretch()
        heading = QLabel("Understand the health of your digital archive")
        heading.setProperty("heading", True)
        heading.setWordWrap(True)
        layout.addWidget(heading)
        for text in (
            "KeepReadable identifies formats and checks file structure.",
            "Deep Audit adds checksum and format-aware readability evidence.",
            "Original files are never modified, moved, renamed, or deleted.",
        ):
            label = QLabel(text)
            label.setWordWrap(True)
            layout.addWidget(label)
        backup = QLabel("It does not replace backup. Keep your files backed up separately.")
        backup.setProperty("muted", True)
        backup.setWordWrap(True)
        layout.addWidget(backup)
        add = QPushButton("Add an Archive")
        add.setProperty("primary", True)
        add.setAccessibleName("Add an Archive")
        add.clicked.connect(self.addArchiveRequested)
        layout.addWidget(add)
        learn = QPushButton("Learn what KeepReadable checks")
        learn.setAccessibleName("Learn what KeepReadable checks")
        learn.clicked.connect(lambda: SupportDialog(self).exec())
        layout.addWidget(learn)
        layout.addStretch()
