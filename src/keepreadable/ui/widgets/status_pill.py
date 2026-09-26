from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from keepreadable.domain.enums import HealthState
from keepreadable.ui.theme import palette


class StatusPill(QWidget):
    def __init__(self, text: str = "Unknown", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.dot = QLabel("●")
        self.label = QLabel(text)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.dot)
        layout.addWidget(self.label)
        layout.addStretch()
        self.setAccessibleName(text)
        self.set_health(HealthState.UNKNOWN)

    def set_health(self, health: HealthState) -> None:
        colours = {
            HealthState.HEALTHY: palette.HEALTHY,
            HealthState.REVIEW: palette.REVIEW,
            HealthState.UNREADABLE: palette.UNREADABLE,
            HealthState.UNKNOWN: palette.UNKNOWN,
        }
        text = health.value.replace("_", " ").title()
        self.dot.setStyleSheet(f"color: {colours[health]}; background: transparent;")
        self.label.setText(text)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setAccessibleName(text)

    def set_status(self, text: str, colour: str = palette.UNKNOWN) -> None:
        self.dot.setStyleSheet(f"color: {colour}; background: transparent;")
        self.label.setText(text)
        self.setAccessibleName(text)
