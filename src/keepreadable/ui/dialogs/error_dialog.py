from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ErrorDialog(QDialog):
    def __init__(
        self,
        message: str,
        reason: str,
        details: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("KeepReadable")
        self.resize(520, 260)
        layout = QVBoxLayout(self)
        title = QLabel(message)
        title.setProperty("subheading", True)
        title.setWordWrap(True)
        layout.addWidget(title)
        reason_label = QLabel(f"Reason: {reason}")
        reason_label.setWordWrap(True)
        layout.addWidget(reason_label)
        self.details = QPlainTextEdit(details)
        self.details.setReadOnly(True)
        self.details.setVisible(False)
        layout.addWidget(self.details)
        self.toggle = QPushButton("Show details")
        self.toggle.setAccessibleName("Show error details")
        self.toggle.clicked.connect(self._toggle)
        layout.addWidget(self.toggle)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _toggle(self) -> None:
        visible = not self.details.isVisible()
        self.details.setVisible(visible)
        self.toggle.setText("Hide details" if visible else "Show details")
        self.adjustSize()
