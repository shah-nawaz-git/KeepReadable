from enum import StrEnum, auto

from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ResumeChoice(StrEnum):
    RESUME = auto()
    START_NEW = auto()
    DISCARD = auto()


class ResumeDialog(QDialog):
    def __init__(self, run_count: int = 1, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Resume audit")
        self.choice: ResumeChoice | None = None
        layout = QVBoxLayout(self)
        heading = QLabel("An audit can be resumed")
        heading.setProperty("subheading", True)
        layout.addWidget(heading)
        message = QLabel(
            f"{run_count} paused or interrupted audit{'s' if run_count != 1 else ''} "
            "were found. Choose how to continue."
        )
        message.setWordWrap(True)
        layout.addWidget(message)
        for text, choice in (
            ("Resume", ResumeChoice.RESUME),
            ("Start new audit", ResumeChoice.START_NEW),
            ("Discard", ResumeChoice.DISCARD),
        ):
            button = QPushButton(text)
            button.setAccessibleName(text)
            button.clicked.connect(lambda _checked=False, value=choice: self._choose(value))
            layout.addWidget(button)

    def _choose(self, choice: ResumeChoice) -> None:
        self.choice = choice
        self.accept()
