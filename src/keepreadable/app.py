import logging
import sys
import traceback
from importlib.resources import files
from types import TracebackType

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from keepreadable.application.container import AppContext
from keepreadable.config.paths import logs_dir
from keepreadable.persistence.repositories import AuditRunRepository
from keepreadable.ui.dialogs.error_dialog import ErrorDialog
from keepreadable.ui.dialogs.resume_dialog import ResumeChoice, ResumeDialog
from keepreadable.ui.main_window import MainWindow
from keepreadable.ui.theme import apply_theme
from keepreadable.utilities.logging import configure_logging

logger = logging.getLogger(__name__)


def main() -> int:
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication(sys.argv)
    app.setApplicationName("KeepReadable")
    app.setOrganizationName("KeepReadable")
    apply_theme(app)
    icon_path = files("keepreadable.resources").joinpath("icon.png")
    app.setWindowIcon(QIcon(str(icon_path)))
    configure_logging(logs_dir(), logging.INFO)
    context = AppContext.create()
    context.audit_engine.recover_interrupted()
    with context.db.session() as session:
        resumable = AuditRunRepository(session).find_interrupted()
    window = MainWindow(context)

    def exception_hook(
        exception_type: type[BaseException],
        exception: BaseException,
        traceback_object: TracebackType | None,
    ) -> None:
        details = "".join(traceback.format_exception(exception_type, exception, traceback_object))
        logger.error("Unhandled UI exception\n%s", details)
        ErrorDialog(
            "KeepReadable encountered an unexpected problem.",
            str(exception) or exception_type.__name__,
            details,
            window,
        ).show()

    sys.excepthook = exception_hook
    if resumable:
        dialog = ResumeDialog(len(resumable))
        dialog.exec()
        if dialog.choice is ResumeChoice.RESUME and resumable[0].id is not None:
            window.controller.resume(resumable[0].id)
        elif dialog.choice is ResumeChoice.DISCARD:
            for run in resumable:
                if run.id is not None:
                    context.audit_engine.discard(run.id)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
