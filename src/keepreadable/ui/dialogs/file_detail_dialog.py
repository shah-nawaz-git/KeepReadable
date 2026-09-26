from datetime import datetime

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFontDatabase
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from keepreadable.application.file_service import FileDetail
from keepreadable.application.preservation_service import PreservationService
from keepreadable.domain.enums import CheckStatus, PolicyStatus
from keepreadable.domain.preservation import CopyOperation
from keepreadable.ui.dialogs.copy_dialog import CopyDialog
from keepreadable.ui.formatting import format_bytes, label_for
from keepreadable.ui.table import configure_table
from keepreadable.ui.theme import palette
from keepreadable.ui.widgets.section_header import SectionHeader
from keepreadable.ui.widgets.status_pill import StatusPill


class FileDetailDialog(QDialog):
    def __init__(
        self,
        detail: FileDetail,
        parent: QWidget | None = None,
        preservation_service: PreservationService | None = None,
    ) -> None:
        super().__init__(parent)
        self.detail = detail
        self.preservation_service = preservation_service
        self.setWindowTitle(detail.record.relative_path)
        self.resize(820, 760)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)
        observation = detail.latest_observation
        layout.addWidget(SectionHeader("File"))
        file_form = QFormLayout()
        file_form.addRow("Relative path", self._wrapped(detail.record.relative_path))
        file_form.addRow("Size", QLabel(format_bytes(detail.record.size)))
        file_form.addRow(
            "Modified",
            QLabel(
                datetime.fromtimestamp(detail.record.mtime_ns / 1_000_000_000).strftime(
                    "%Y-%m-%d %H:%M"
                )
            ),
        )
        health = StatusPill()
        if detail.record.last_health is not None:
            health.set_health(detail.record.last_health)
        file_form.addRow("Health", health)
        layout.addLayout(file_form)
        layout.addWidget(SectionHeader("IDENTIFICATION"))
        identification = QFormLayout()
        identification.addRow(
            "Extension", QLabel(observation.extension.upper() if observation else "—")
        )
        format_text = "Unknown"
        if observation and observation.detected_format:
            format_text = observation.detected_format
            if observation.format_version:
                format_text += f" {observation.format_version}"
        identification.addRow("Detected format", self._wrapped(format_text))
        identification.addRow("PUID", QLabel(observation.puid or "—" if observation else "—"))
        identification.addRow(
            "MIME type", QLabel(observation.mime_type or "—" if observation else "—")
        )
        engine = (
            observation.validation_details.get("identification_engine") if observation else None
        )
        identification.addRow("Identification engine", QLabel(str(engine or "—")))
        match = observation.extension_matches_signature if observation else None
        identification.addRow(
            "Extension matches signature",
            QLabel("Yes" if match is True else "No" if match is False else "—"),
        )
        layout.addLayout(identification)
        layout.addWidget(SectionHeader("INTEGRITY"))
        integrity = QFormLayout()
        sha = observation.sha256 if observation else None
        sha_label = QLabel(sha or "Not verified")
        sha_label.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        sha_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        integrity.addRow("Last SHA-256", sha_label)
        integrity.addRow(
            "Last deep verification",
            QLabel(
                detail.record.last_deep_verified_at.strftime("%Y-%m-%d %H:%M")
                if detail.record.last_deep_verified_at
                else "Never"
            ),
        )
        previous_sha = next(
            (item.sha256 for item in detail.history[1:] if item.sha256 is not None),
            None,
        )
        changed = (
            "Not verified"
            if sha is None or previous_sha is None
            else "Yes"
            if sha != previous_sha
            else "No"
        )
        integrity.addRow("Changed since baseline?", QLabel(changed))
        layout.addLayout(integrity)
        layout.addWidget(SectionHeader("VALIDATION"))
        validation = QFormLayout()
        structural = StatusPill()
        readability = StatusPill()
        if observation:
            structural.set_status(
                label_for(observation.structural_status),
                self._check_colour(observation.structural_status),
            )
            readability.set_status(
                label_for(observation.readability_status),
                self._check_colour(observation.readability_status),
            )
        validation.addRow("Structural result", structural)
        validation.addRow("Readability result", readability)
        validation.addRow(
            "Validator",
            QLabel(
                (
                    f"{observation.validator_name or '—'} {observation.validator_version or ''}"
                ).strip()
                if observation
                else "—"
            ),
        )
        details = observation.validation_details if observation else {}
        summary = QLabel(str(details.get("summary") or "No validation summary recorded."))
        summary.setWordWrap(True)
        validation.addRow("Summary", summary)
        validation.addRow(
            "What was checked",
            self._bullet_list(details.get("checks_performed", [])),
        )
        validation.addRow(
            "Not checked",
            self._bullet_list(details.get("checks_not_performed", [])),
        )
        layout.addLayout(validation)
        layout.addWidget(SectionHeader("FORMAT POLICY"))
        policy = QFormLayout()
        policy_pill = StatusPill()
        if observation:
            colour = (
                palette.REVIEW
                if observation.policy_status is PolicyStatus.REVIEW
                else palette.HEALTHY
                if observation.policy_status is PolicyStatus.NORMAL
                else palette.UNKNOWN
            )
            policy_pill.set_status(label_for(observation.policy_status), colour)
        policy.addRow("Status", policy_pill)
        policy.addRow(
            "Reason",
            self._wrapped(
                observation.policy_reason
                if observation and observation.policy_reason
                else "No policy guidance recorded."
            ),
        )
        layout.addLayout(policy)
        layout.addWidget(SectionHeader("HISTORY"))
        history = QTableWidget(len(detail.history), 5)
        history.setHorizontalHeaderLabels(("Audit date", "Mode", "Health", "Change", "SHA-256"))
        for row, item in enumerate(detail.history):
            run = detail.audit_runs.get(item.audit_run_id)
            values = (
                item.created_at.strftime("%Y-%m-%d %H:%M"),
                label_for(run.mode) if run else "—",
                label_for(item.health),
                label_for(item.change_kind),
                f"{item.sha256[:12]}…" if item.sha256 else "—",
            )
            for column, value in enumerate(values):
                history.setItem(row, column, QTableWidgetItem(value))
        configure_table(history, stretch_columns=(0,))
        history.setMinimumHeight(history.verticalHeader().defaultSectionSize() * 7)
        layout.addWidget(history)
        layout.addWidget(SectionHeader("OPEN FINDINGS"))
        if detail.open_findings:
            for finding in detail.open_findings:
                label = QLabel(f"{label_for(finding.severity)} · {finding.title}")
                label.setWordWrap(True)
                layout.addWidget(label)
        else:
            layout.addWidget(QLabel("No open findings for this file."))
        layout.addWidget(SectionHeader("COMPATIBILITY COPIES"))
        if detail.generated_copies:
            for generated in detail.generated_copies:
                copy_row = QHBoxLayout()
                copy_row.addWidget(QLabel(generated.created_at.strftime("%Y-%m-%d %H:%M")))
                copy_row.addWidget(self._wrapped(generated.output_path or "No output retained"), 1)
                copy_status = StatusPill()
                copy_status.set_status(label_for(generated.verification_status))
                copy_row.addWidget(copy_status)
                layout.addLayout(copy_row)
        else:
            layout.addWidget(QLabel("No compatibility copies recorded."))
        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self.actions_layout = QHBoxLayout()
        open_button = QPushButton("Open file location")
        open_button.setAccessibleName("Open file location")
        open_button.clicked.connect(self._open_location)
        self.actions_layout.addWidget(open_button)
        if preservation_service is not None and detail.record.id is not None:
            operations = preservation_service.available_operations(detail.record.id)
            copy_button = QPushButton("Create compatibility copy…")
            copy_button.setAccessibleName("Create compatibility copy")
            if operations:
                copy_button.clicked.connect(lambda: self._create_copy(operations[0]))
            else:
                detected = (
                    detail.latest_observation.detected_format.casefold()
                    if detail.latest_observation and detail.latest_observation.detected_format
                    else ""
                )
                if "avi" in detected or "quicktime" in detected:
                    copy_button.setEnabled(False)
                    copy_button.setToolTip("FFmpeg is required")
                else:
                    copy_button.setVisible(False)
            self.actions_layout.addWidget(copy_button)
        self.actions_layout.addStretch()
        close = QPushButton("Close")
        close.setAccessibleName("Close file details")
        close.clicked.connect(self.accept)
        self.actions_layout.addWidget(close)
        outer.addLayout(self.actions_layout)

    @staticmethod
    def _wrapped(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        return label

    @staticmethod
    def _bullet_list(values: object) -> QLabel:
        items = list(values) if isinstance(values, (list, tuple)) else []
        return FileDetailDialog._wrapped("\n".join(f"• {value}" for value in items) or "—")

    @staticmethod
    def _check_colour(status: CheckStatus) -> str:
        if status is CheckStatus.PASSED:
            return palette.HEALTHY
        if status in {CheckStatus.WARNING, CheckStatus.PROTECTED}:
            return palette.REVIEW
        if status is CheckStatus.FAILED:
            return palette.UNREADABLE
        return palette.UNKNOWN

    def _create_copy(self, operation: CopyOperation) -> None:
        if self.preservation_service is None or self.detail.record.id is None:
            return
        proposal = self.preservation_service.propose(self.detail.record.id, operation)
        CopyDialog(self.preservation_service, proposal, self).exec()

    def _open_location(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.detail.absolute_path.parent)))
