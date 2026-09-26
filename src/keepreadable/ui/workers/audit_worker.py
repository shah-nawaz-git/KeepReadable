from PySide6.QtCore import QThread, Signal

from keepreadable.application.audit_service import AuditEngine, AuditProgress
from keepreadable.domain.enums import AuditMode
from keepreadable.utilities.cancellation import CancellationToken


class AuditWorker(QThread):
    progress = Signal(object)
    auditFinished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        engine: AuditEngine,
        *,
        archive_id: int | None = None,
        mode: AuditMode | None = None,
        force_deep_all: bool = False,
        resume_run_id: int | None = None,
    ) -> None:
        super().__init__()
        self.engine = engine
        self.archive_id = archive_id
        self.mode = mode
        self.force_deep_all = force_deep_all
        self.resume_run_id = resume_run_id
        self.token = CancellationToken()

    def run(self) -> None:
        try:
            if self.resume_run_id is not None:
                result = self.engine.resume(
                    self.resume_run_id,
                    cancel=self.token,
                    on_progress=self._progress,
                )
            else:
                assert self.archive_id is not None and self.mode is not None
                result = self.engine.start(
                    self.archive_id,
                    self.mode,
                    force_deep_all=self.force_deep_all,
                    cancel=self.token,
                    on_progress=self._progress,
                )
            self.auditFinished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))

    def pause(self) -> None:
        self.token.cancel("pause")

    def cancel(self) -> None:
        self.token.cancel()

    def _progress(self, progress: AuditProgress) -> None:
        self.progress.emit(progress)
