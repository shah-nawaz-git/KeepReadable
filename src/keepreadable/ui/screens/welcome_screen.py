from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from keepreadable.ui.dialogs.support_dialog import SupportDialog


class WelcomeScreen(QWidget):
    addArchiveRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        content = QWidget()
        content.setMaximumWidth(680)
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(16)
        heading = QLabel("Understand the health of your digital archive")
        heading.setProperty("heading", True)
        heading.setWordWrap(True)
        content_layout.addWidget(heading)
        for text in (
            "KeepReadable identifies formats and checks file structure.",
            "Deep Audit adds checksum and format-aware readability evidence.",
            "Original files are never modified, moved, renamed, or deleted.",
        ):
            label = QLabel(text)
            label.setStyleSheet("font-size: 11pt")
            label.setWordWrap(True)
            content_layout.addWidget(label)
        backup = QLabel("It does not replace backup. Keep your files backed up separately.")
        backup.setStyleSheet("font-size: 11pt; font-weight: 600; color: #52606D")
        backup.setWordWrap(True)
        content_layout.addWidget(backup)
        buttons = QHBoxLayout()
        add = QPushButton("Add an Archive")
        add.setProperty("primary", True)
        add.setAccessibleName("Add an Archive")
        add.clicked.connect(self.addArchiveRequested)
        buttons.addWidget(add)
        learn = QPushButton("Learn what KeepReadable checks")
        learn.setAccessibleName("Learn what KeepReadable checks")
        learn.clicked.connect(lambda: SupportDialog(self).exec())
        buttons.addWidget(learn)
        buttons.addStretch()
        content_layout.addLayout(buttons)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(80, 80, 80, 80)
        layout.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(content)
        row.addStretch()
        layout.addLayout(row)
        layout.addStretch()
