from PySide6.QtWidgets import QLabel, QTableView, QVBoxLayout, QWidget

from keepreadable.application.archive_service import ArchiveService
from keepreadable.ui.models.history_table_model import HistoryTableModel


class HistoryScreen(QWidget):
    def __init__(
        self,
        service: ArchiveService,
        archive_id: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.archive_id = archive_id
        self.model = HistoryTableModel()
        heading = QLabel("History")
        heading.setProperty("heading", True)
        self.table = QTableView()
        self.table.setAccessibleName("Audit history")
        self.table.setModel(self.model)
        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(self.table)
        self.refresh()

    def refresh(self) -> None:
        if self.archive_id is not None:
            runs = self.service.history(self.archive_id)
        else:
            runs = [
                run
                for archive in self.service.list_archives()
                for run in self.service.history(archive.id or 0)
            ]
            runs.sort(key=lambda run: run.started_at, reverse=True)
        self.model.set_runs(runs)
        self.table.resizeColumnsToContents()
