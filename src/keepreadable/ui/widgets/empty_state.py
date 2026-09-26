from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class EmptyState(QWidget):
    actionRequested = Signal()

    def __init__(
        self,
        title: str,
        hint: str,
        action_text: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        title_label = QLabel(title)
        title_label.setProperty("subheading", True)
        title_label.setWordWrap(True)
        hint_label = QLabel(hint)
        hint_label.setProperty("muted", True)
        hint_label.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(12)
        layout.addStretch()
        layout.addWidget(title_label)
        layout.addWidget(hint_label)
        if action_text:
            button = QPushButton(action_text)
            button.setAccessibleName(action_text)
            button.clicked.connect(self.actionRequested)
            layout.addWidget(button)
        layout.addStretch()
