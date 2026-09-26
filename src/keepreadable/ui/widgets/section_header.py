from PySide6.QtWidgets import QLabel, QWidget


class SectionHeader(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("subheading", True)
