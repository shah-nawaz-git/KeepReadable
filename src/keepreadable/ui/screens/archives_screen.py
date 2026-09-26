from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from keepreadable.application.archive_service import ArchiveService


class ArchivesScreen(QWidget):
    addArchiveRequested = Signal()
    archiveActivated = Signal(int)

    def __init__(self, service: ArchiveService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.archive_ids: list[int] = []
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
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ("Name", "Location", "Availability", "Health", "Last audit")
        )
        self.table.setAccessibleName("Registered archives")
        self.table.cellDoubleClicked.connect(lambda row, _column: self._activate(row))
        self.table.cellActivated.connect(lambda row, _column: self._activate(row))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addLayout(header)
        layout.addWidget(self.table)
        self.refresh()

    def refresh(self) -> None:
        archives = self.service.list_archives()
        self.archive_ids = [archive.id or 0 for archive in archives]
        self.table.setRowCount(len(archives))
        for row, archive in enumerate(archives):
            overview = self.service.overview(archive.id or 0)
            health = (
                ", ".join(
                    f"{state.value.title()}: {count}"
                    for state, count in overview.health_counts.items()
                )
                or "No audited files"
            )
            last = overview.last_deep_run or overview.last_quick_run
            values = (
                archive.name,
                archive.root_path,
                overview.availability.value.title(),
                health,
                last.started_at.strftime("%Y-%m-%d %H:%M") if last else "Never",
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()

    def _activate(self, row: int) -> None:
        if 0 <= row < len(self.archive_ids):
            self.archiveActivated.emit(self.archive_ids[row])
