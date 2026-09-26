from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class StatTile(QFrame):
    def __init__(self, title: str, value: str = "—", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("surface")
        self.value_label = QLabel(value)
        self.value_label.setProperty("subheading", True)
        title_label = QLabel(title)
        title_label.setProperty("muted", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        layout.addWidget(title_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)
