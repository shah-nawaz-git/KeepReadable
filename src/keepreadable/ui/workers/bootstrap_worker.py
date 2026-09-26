from collections.abc import Sequence

from PySide6.QtCore import QThread, Signal

from keepreadable.integrations.bootstrap import ToolBootstrapper
from keepreadable.utilities.cancellation import CancellationToken


class BootstrapWorker(QThread):
    progress = Signal(str, int, object)
    bootstrapFinished = Signal(object)
    failed = Signal(str)

    def __init__(self, bootstrapper: ToolBootstrapper, tools: Sequence[str] | None = None) -> None:
        super().__init__()
        self.bootstrapper = bootstrapper
        self.tools = tools
        self.token = CancellationToken()

    def run(self) -> None:
        try:
            result = self.bootstrapper.install(
                self.tools,
                progress=self._progress,
                cancel=self.token,
            )
            self.bootstrapFinished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))

    def cancel(self) -> None:
        self.token.cancel()

    def _progress(self, tool: str, received: int, total: int | None) -> None:
        self.progress.emit(tool, received, total)
