import argparse
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from create_demo_archive import create_demo_archive  # noqa: E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from keepreadable.application.container import AppContext  # noqa: E402
from keepreadable.domain.enums import AuditMode  # noqa: E402
from keepreadable.ui.dialogs.file_detail_dialog import FileDetailDialog  # noqa: E402
from keepreadable.ui.main_window import MainWindow  # noqa: E402
from keepreadable.ui.screens.archive_screen import ArchiveScreen  # noqa: E402
from keepreadable.ui.theme import apply_theme  # noqa: E402


def pause(milliseconds: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def save_widget(widget: object, path: Path) -> None:
    image = widget.grab().toImage()
    if image.width() > 1440:
        image = image.scaledToWidth(1440)
    image.save(str(path), "PNG")


def capture(out: Path, data_dir: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    archive_root = data_dir.parent / "family-archive-demo"
    if archive_root.exists():
        shutil.rmtree(archive_root)
    if data_dir.exists():
        shutil.rmtree(data_dir)
    create_demo_archive(archive_root, seed=42, media=None)
    context = AppContext.create(data_dir)
    archive = context.archive_service.add_archive("Family Archive", archive_root)
    assert archive.id is not None
    context.audit_engine.start(archive.id, AuditMode.QUICK)
    context.audit_engine.start(archive.id, AuditMode.DEEP)
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    window = MainWindow(context)
    window.resize(1440, 900)
    window.show()
    window.open_archive(archive.id)
    pause(350)
    archive_screen = window.stack.currentWidget()
    assert isinstance(archive_screen, ArchiveScreen)
    saved: list[Path] = []

    def grab(name: str, widget: object = window) -> None:
        path = out / name
        save_widget(widget, path)
        saved.append(path)

    archive_screen.tabs.setCurrentIndex(0)
    pause(150)
    grab("archive_overview.png")
    archive_screen.tabs.setCurrentIndex(1)
    pause(150)
    grab("files.png")
    window.sidebar.setCurrentRow(1)
    pause(150)
    grab("findings.png")
    window.sidebar.setCurrentRow(2)
    pause(150)
    grab("history.png")
    window.sidebar.setCurrentRow(3)
    pause(150)
    grab("settings.png")
    first = context.file_service.list_files(archive.id, 0, 1)[0]
    dialog = FileDetailDialog(context.file_service.file_detail(first.id or 0), window)
    dialog.resize(900, 820)
    dialog.show()
    pause(200)
    grab("file_detail.png", dialog)
    dialog.close()
    welcome_data = data_dir.parent / "welcome-data"
    if welcome_data.exists():
        shutil.rmtree(welcome_data)
    welcome = MainWindow(AppContext.create(welcome_data))
    welcome.resize(1440, 900)
    welcome.show()
    pause(200)
    grab("welcome.png", welcome)
    welcome.close()
    create_demo_archive(archive_root, seed=42, media=False, large=3000)
    window.open_archive(archive.id)
    archive_screen = window.stack.currentWidget()
    assert isinstance(archive_screen, ArchiveScreen)
    archive_screen.tabs.setCurrentIndex(0)
    context.archive_service.estimate_file_count(archive_root, limit=5000, time_budget=5)
    window.controller.start(archive.id, AuditMode.DEEP, True)
    pause(1500)
    grab("deep_audit_progress.png")
    if window.controller.is_running:
        loop = QEventLoop()
        window.controller.finished.connect(loop.quit)
        window.controller.failed.connect(loop.quit)
        QTimer.singleShot(120_000, loop.quit)
        loop.exec()
    window.close()
    return saved


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "screenshots")
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if args.data_dir is None:
        temporary = tempfile.TemporaryDirectory(prefix="keepreadable-screenshots-")
        data_dir = Path(temporary.name) / "data"
    else:
        data_dir = args.data_dir
    app = QApplication.instance() or QApplication(sys.argv)
    assert isinstance(app, QApplication)
    apply_theme(app)
    saved = capture(args.out, data_dir)
    for path in saved:
        print(f"{path.name}\t{path.stat().st_size} bytes")
    if temporary is not None:
        temporary.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
