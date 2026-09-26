from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from keepreadable.application.archive_service import ArchiveOverview
from keepreadable.domain.archive import Archive
from keepreadable.domain.enums import HealthState
from keepreadable.ui.formatting import pluralize, relative_time
from keepreadable.ui.theme import palette
from keepreadable.ui.widgets.status_pill import StatusPill


class ArchiveRow(QFrame):
    activated = Signal(int)

    def __init__(
        self, archive: Archive, overview: ArchiveOverview, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.archive_id = archive.id or 0
        self.setProperty("surface", True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        name = QLabel(archive.name)
        name.setProperty("subheading", True)
        path = QLabel(archive.root_path)
        path.setProperty("muted", True)
        path.setWordWrap(True)
        text = QVBoxLayout()
        text.addWidget(name)
        text.addWidget(path)
        availability = StatusPill()
        if overview.availability.value == "available":
            availability.set_status("Available", palette.HEALTHY)
        elif overview.availability.value == "relocated":
            availability.set_status("Relocated", palette.REVIEW)
        else:
            availability.set_status("Not connected", palette.UNREADABLE)
        counts = QHBoxLayout()
        health_colours = {
            HealthState.HEALTHY: palette.HEALTHY,
            HealthState.REVIEW: palette.REVIEW,
            HealthState.UNREADABLE: palette.UNREADABLE,
            HealthState.UNKNOWN: palette.UNKNOWN,
        }
        for health in HealthState:
            count = overview.health_counts.get(health, 0)
            pill = StatusPill()
            pill.set_status(
                f"{health.value.title()} {count:,}",
                health_colours[health] if count else "#9AA5B1",
            )
            counts.addWidget(pill)
        latest = overview.last_deep_run or overview.last_quick_run
        last = QLabel(
            "Last audit: Never"
            if latest is None
            else f"Last audit: {relative_time(latest.started_at)} ({latest.mode.value.title()})"
        )
        last.setProperty("muted", True)
        right = QVBoxLayout()
        right.addWidget(availability)
        right.addLayout(counts)
        right.addWidget(last)
        right.addWidget(QLabel(pluralize(overview.file_count, "file")))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.addLayout(text, 2)
        layout.addLayout(right, 3)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.activated.emit(self.archive_id)
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.archive_id)
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.activated.emit(self.archive_id)
        else:
            super().keyPressEvent(event)
