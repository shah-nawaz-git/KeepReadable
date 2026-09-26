from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from keepreadable.application.archive_service import ArchiveService
from keepreadable.ui.widgets.archive_row import ArchiveRow


class ArchivesScreen(QWidget):
    addArchiveRequested = Signal()
    archiveActivated = Signal(int)

    def __init__(self, service: ArchiveService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        heading = QLabel("Archives")
        heading.setProperty("heading", True)
        add = QPushButton("Add an Archive")
        add.setProperty("primary", True)
        add.setAccessibleName("Add an Archive")
        add.clicked.connect(self.addArchiveRequested)
        header = QHBoxLayout()
        header.addWidget(heading)
        header.addStretch()
        header.addWidget(add)
        self.rows_widget = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_widget)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self.rows_widget)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addLayout(header)
        layout.addWidget(scroll, 1)
        self.refresh()

    def refresh(self) -> None:
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        for archive in self.service.list_archives():
            row = ArchiveRow(
                archive,
                self.service.overview(archive.id or 0),
            )
            row.activated.connect(self.archiveActivated)
            self.rows_layout.addWidget(row)
            row.show()
        self.rows_layout.addStretch()
