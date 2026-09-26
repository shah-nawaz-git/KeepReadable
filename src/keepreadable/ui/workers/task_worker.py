from collections.abc import Callable

from PySide6.QtCore import QThread, Signal


class TaskWorker(QThread):
    taskFinished = Signal(object)
    failed = Signal(str)

    def __init__(self, task: Callable[[], object]) -> None:
        super().__init__()
        self.task = task

    def run(self) -> None:
        try:
            self.taskFinished.emit(self.task())
        except Exception as exc:
            self.failed.emit(str(exc))
