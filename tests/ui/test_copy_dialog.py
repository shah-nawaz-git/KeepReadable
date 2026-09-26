from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QLabel

from keepreadable.application.preservation_service import CopyProposal
from keepreadable.domain.enums import CopyKind, VerificationStatus
from keepreadable.domain.preservation import CopyOperation, GeneratedCopy
from keepreadable.ui.dialogs.copy_dialog import CopyDialog

pytestmark = pytest.mark.ui


class FakeService:
    def execute(self, proposal: CopyProposal, **_kwargs: Any) -> GeneratedCopy:
        return GeneratedCopy(
            id=1,
            source_file_record_id=proposal.file_record_id,
            output_path=str(proposal.destination_dir / proposal.proposed_output_name),
            copy_kind=CopyKind.ACCESS_COPY,
            operation=proposal.operation.value,
            created_at=datetime(2026, 9, 26),
            source_hash="a" * 64,
            output_hash="b" * 64,
            verification_status=VerificationStatus.PASSED,
            verification_details={
                "comparisons": [
                    {
                        "name": "pixel equality",
                        "source": "RGBA",
                        "output": "RGBA",
                        "passed": True,
                    }
                ]
            },
        )


def test_copy_dialog_confirmation_and_passed_result(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    proposal = CopyProposal(
        CopyOperation.BMP_TO_PNG,
        1,
        tmp_path / "source.bmp",
        "Windows Bitmap",
        "PNG",
        "Create a compatibility copy.",
        "The original remains unchanged.",
        False,
        1024,
        tmp_path,
        "source.access.png",
    )
    dialog = CopyDialog(FakeService(), proposal)
    qtbot.addWidget(dialog)
    dialog.show()
    labels = [label.text() for label in dialog.findChildren(QLabel)]
    assert "The original will not be changed." in labels
    dialog._start()
    qtbot.waitUntil(lambda: dialog.stack.currentWidget() is dialog.result_page)
    assert dialog.result_heading.text() == "Copy created"
    assert dialog.verification_pill.label.text() == "Passed"
    assert dialog.comparison_table.rowCount() == 1
