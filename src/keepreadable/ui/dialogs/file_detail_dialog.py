from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from keepreadable.application.file_service import FileDetail
from keepreadable.ui.formatting import format_bytes
from keepreadable.ui.widgets.section_header import SectionHeader


class FileDetailDialog(QDialog):
    def __init__(self, detail: FileDetail, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.detail = detail
        self.setWindowTitle(detail.record.relative_path)
        self.resize(760, 720)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(SectionHeader("File"))
        file_form = QFormLayout()
        file_form.addRow("Path", QLabel(detail.record.relative_path))
        file_form.addRow("Size", QLabel(format_bytes(detail.record.size)))
        file_form.addRow(
            "Health",
            QLabel(
                detail.record.last_health.value.title() if detail.record.last_health else "Unknown"
            ),
        )
        layout.addLayout(file_form)
        observation = detail.latest_observation
        layout.addWidget(SectionHeader("IDENTIFICATION"))
        identification = QFormLayout()
        identification.addRow(
            "Format", QLabel(observation.detected_format or "Unknown" if observation else "Unknown")
        )
        identification.addRow("PUID", QLabel(observation.puid or "—" if observation else "—"))
        identification.addRow(
            "MIME type", QLabel(observation.mime_type or "—" if observation else "—")
        )
        layout.addLayout(identification)
        layout.addWidget(SectionHeader("INTEGRITY"))
        integrity = QFormLayout()
        integrity.addRow(
            "SHA-256",
            QLabel(
                observation.sha256 or "Not deeply verified"
                if observation
                else "Not deeply verified"
            ),
        )
        integrity.addRow(
            "Last deep verification", QLabel(str(detail.record.last_deep_verified_at or "Never"))
        )
        layout.addLayout(integrity)
        layout.addWidget(SectionHeader("VALIDATION"))
        validation = QFormLayout()
        validation.addRow(
            "Structural result",
            QLabel(observation.structural_status.value.title() if observation else "Not checked"),
        )
        validation.addRow(
            "Readability result",
            QLabel(observation.readability_status.value.title() if observation else "Not checked"),
        )
        validation.addRow(
            "Validator", QLabel(observation.validator_name or "—" if observation else "—")
        )
        checked = observation.validation_details.get("checks_performed", []) if observation else []
        not_checked = (
            observation.validation_details.get("checks_not_performed", []) if observation else []
        )
        validation.addRow("What was checked", QLabel(", ".join(checked) or "See audit evidence"))
        validation.addRow("Not checked", QLabel(", ".join(not_checked) or "—"))
        layout.addLayout(validation)
        layout.addWidget(SectionHeader("FORMAT POLICY"))
        policy = QFormLayout()
        policy.addRow(
            "Status", QLabel(observation.policy_status.value.title() if observation else "Unknown")
        )
        policy_reason = QLabel(
            observation.policy_reason or "No policy evidence recorded."
            if observation
            else "No policy evidence recorded."
        )
        policy_reason.setWordWrap(True)
        policy.addRow("Guidance", policy_reason)
        layout.addLayout(policy)
        layout.addWidget(SectionHeader("HISTORY"))
        history = QTableWidget(len(detail.history), 4)
        history.setHorizontalHeaderLabels(("Audit", "Observed", "Health", "Change"))
        for row, item in enumerate(detail.history):
            for column, value in enumerate(
                (
                    str(item.audit_run_id),
                    item.created_at.strftime("%Y-%m-%d %H:%M"),
                    item.health.value.title(),
                    item.change_kind.value.title(),
                )
            ):
                history.setItem(row, column, QTableWidgetItem(value))
        layout.addWidget(history)
        if detail.open_findings:
            layout.addWidget(SectionHeader("Open findings"))
            for finding in detail.open_findings:
                label = QLabel(f"{finding.severity.value.title()}: {finding.title}")
                label.setWordWrap(True)
                layout.addWidget(label)
        self.actions_layout = QHBoxLayout()
        open_button = QPushButton("Open file location")
        open_button.setAccessibleName("Open file location")
        open_button.clicked.connect(self._open_location)
        self.actions_layout.addWidget(open_button)
        self.actions_layout.addStretch()
        close = QPushButton("Close")
        close.setAccessibleName("Close file details")
        close.clicked.connect(self.accept)
        self.actions_layout.addWidget(close)
        layout.addLayout(self.actions_layout)

    def _open_location(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.detail.absolute_path.parent)))
