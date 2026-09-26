from PySide6.QtCore import QObject, Signal

from keepreadable.application.audit_service import AuditEngine
from keepreadable.domain.enums import AuditMode
from keepreadable.ui.workers.audit_worker import AuditWorker


class AuditController(QObject):
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)
    runningChanged = Signal(bool)

    def __init__(self, engine: AuditEngine) -> None:
        super().__init__()
        self.engine = engine
        self.worker: AuditWorker | None = None
        self.current_mode: AuditMode | None = None
        self.current_archive_id: int | None = None

    @property
    def is_running(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def start(self, archive_id: int, mode: AuditMode, force: bool = False) -> bool:
        if self.is_running:
            return False
        self.current_mode = mode
        self.current_archive_id = archive_id
        self.worker = AuditWorker(
            self.engine,
            archive_id=archive_id,
            mode=mode,
            force_deep_all=force,
        )
        self._connect_worker()
        self.runningChanged.emit(True)
        self.worker.start()
        return True

    def resume(self, run_id: int) -> bool:
        if self.is_running:
            return False
        self.current_mode = None
        self.current_archive_id = None
        self.worker = AuditWorker(self.engine, resume_run_id=run_id)
        self._connect_worker()
        self.runningChanged.emit(True)
        self.worker.start()
        return True

    def pause(self) -> None:
        if self.worker is not None:
            self.worker.pause()

    def cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel()

    def wait(self, milliseconds: int = 30_000) -> bool:
        return self.worker is None or self.worker.wait(milliseconds)

    def _connect_worker(self) -> None:
        assert self.worker is not None
        self.worker.progress.connect(self.progress)
        self.worker.auditFinished.connect(self._finished)
        self.worker.failed.connect(self._failed)

    def _finished(self, result: object) -> None:
        self.finished.emit(result)
        self.runningChanged.emit(False)
        self.worker = None

    def _failed(self, message: str) -> None:
        self.failed.emit(message)
        self.runningChanged.emit(False)
        self.worker = None
