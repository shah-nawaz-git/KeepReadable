from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt

from keepreadable.domain.audit import AuditRun
from keepreadable.ui.formatting import format_duration

_INVALID_INDEX = QModelIndex()


class HistoryTableModel(QAbstractTableModel):
    headers = (
        "Mode",
        "Status",
        "Started",
        "Duration",
        "Discovered",
        "Processed",
        "Failed",
        "Findings",
    )

    def __init__(self) -> None:
        super().__init__()
        self.runs: list[AuditRun] = []

    def set_runs(self, runs: list[AuditRun]) -> None:
        self.beginResetModel()
        self.runs = runs
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _INVALID_INDEX) -> int:
        return 0 if parent.isValid() else len(self.runs)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = _INVALID_INDEX) -> int:
        return 0 if parent.isValid() else len(self.headers)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        run = self.runs[index.row()]
        duration = (run.completed_at - run.started_at).total_seconds() if run.completed_at else None
        return (
            run.mode.value.title(),
            run.status.value.title(),
            run.started_at.strftime("%Y-%m-%d %H:%M"),
            format_duration(duration),
            f"{run.files_discovered:,}",
            f"{run.files_processed:,}",
            f"{run.files_failed:,}",
            f"{run.findings_count:,}",
        )[index.column()]

    def run_at(self, row: int) -> AuditRun | None:
        return self.runs[row] if 0 <= row < len(self.runs) else None

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> object:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return None
