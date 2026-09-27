import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
os.environ["QT_SCALE_FACTOR"] = "1"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from create_demo_archive import create_demo_archive  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtCore import QEventLoop, QPoint, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit  # noqa: E402

from keepreadable.application.container import AppContext  # noqa: E402
from keepreadable.domain.enums import AuditMode  # noqa: E402
from keepreadable.domain.preservation import CopyOperation  # noqa: E402
from keepreadable.integrations.tool_locator import ToolLocator, ToolName  # noqa: E402
from keepreadable.ui.dialogs.add_archive_dialog import AddArchiveDialog  # noqa: E402
from keepreadable.ui.dialogs.copy_dialog import CopyDialog  # noqa: E402
from keepreadable.ui.dialogs.file_detail_dialog import FileDetailDialog  # noqa: E402
from keepreadable.ui.dialogs.resume_dialog import ResumeDialog  # noqa: E402
from keepreadable.ui.main_window import MainWindow  # noqa: E402
from keepreadable.ui.screens.archive_screen import ArchiveScreen  # noqa: E402
from keepreadable.ui.theme import apply_theme  # noqa: E402


def pause(milliseconds: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def save_widget(widget: object, path: Path) -> None:
    pixmap = widget.grab()
    pixmap.save(str(path), "PNG")
    if path.stat().st_size > 400 * 1024:
        with Image.open(path) as image:
            image.convert("P", palette=Image.Palette.ADAPTIVE, colors=256).save(
                path, format="PNG", optimize=True
            )


def assert_overview_findings_visible(
    path: Path, archive_screen: ArchiveScreen, window: MainWindow
) -> None:
    origin = archive_screen.top_findings_widget.mapTo(window, QPoint(0, 0))
    width = min(
        archive_screen.top_findings_widget.width(),
        window.width() - origin.x(),
    )
    height = min(
        archive_screen.top_findings_widget.height(),
        window.height() - origin.y(),
    )
    if width <= 0 or height <= 0:
        raise RuntimeError("archive overview top-findings region is outside the capture")
    bounds = (origin.x(), origin.y(), origin.x() + width, origin.y() + height)
    with Image.open(path) as image:
        region = image.convert("L").crop(bounds)
        pixels = list(region.getdata())
        dark_ratio = sum(value < 170 for value in pixels) / max(1, len(pixels))
    if dark_ratio < 0.01:
        raise RuntimeError("archive overview top-findings region appears blank")


def mirror_tools_for_capture(data_dir: Path) -> None:
    locator = ToolLocator()
    destinations = {
        ToolName.SIEGFRIED: data_dir / "tools" / "siegfried" / "sf.exe",
        ToolName.FFMPEG: data_dir / "tools" / "ffmpeg" / "ffmpeg.exe",
        ToolName.FFPROBE: data_dir / "tools" / "ffmpeg" / "ffprobe.exe",
    }
    for name, destination in destinations.items():
        source = locator.locate(name)
        if source is not None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    home = locator.siegfried_home()
    if home is not None and (home / "default.sig").is_file():
        destination = data_dir / "tools" / "siegfried" / "default.sig"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(home / "default.sig", destination)


def capture(
    out: Path,
    data_dir: Path,
    archive_root: Path | None = None,
) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    explicit_archive_root = archive_root is not None
    archive_root = archive_root or data_dir.parent / "family-archive-demo"
    if archive_root.exists():
        if explicit_archive_root:
            raise FileExistsError(f"Refusing to replace existing archive root: {archive_root}")
        shutil.rmtree(archive_root)
    archive_root.parent.mkdir(parents=True, exist_ok=True)
    if data_dir.exists():
        shutil.rmtree(data_dir)
    mirror_tools_for_capture(data_dir)
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
    if archive_screen.path.text() != str(archive_root):
        raise RuntimeError("archive header does not show the requested neutral root")
    saved: list[Path] = []

    def grab(name: str, widget: object = window) -> None:
        visible_text = [label.text() for label in widget.findChildren(QLabel)]
        visible_text.extend(field.text() for field in widget.findChildren(QLineEdit))
        if str(Path.home()).casefold() in " ".join(visible_text).casefold():
            raise RuntimeError(f"{name} contains the local user profile path")
        path = out / name
        save_widget(widget, path)
        saved.append(path)

    archive_screen.tabs.setCurrentIndex(0)
    archive_screen.overview_tab.verticalScrollBar().setValue(0)
    pause(150)
    grab("archive_overview.png")
    assert_overview_findings_visible(out / "archive_overview.png", archive_screen, window)
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
    settings_text = " ".join(
        label.text() for label in window.stack.currentWidget().findChildren(QLabel)
    )
    if str(Path.home()).casefold() in settings_text.casefold():
        raise RuntimeError("settings screenshot contains the local user profile path")
    grab("settings.png")
    first = context.file_service.list_files(archive.id, 0, 1)[0]
    dialog = FileDetailDialog(context.file_service.file_detail(first.id or 0), window)
    dialog.resize(900, 820)
    dialog.show()
    pause(200)
    grab("file_detail.png", dialog)
    dialog.close()
    bmp_record = next(
        record
        for record in context.file_service.list_files(archive.id, 0, 1000)
        if record.relative_path.casefold().endswith(".bmp")
    )
    assert bmp_record.id is not None
    copy_proposal = context.preservation_service.propose(bmp_record.id, CopyOperation.BMP_TO_PNG)
    copy_result = context.preservation_service.execute(copy_proposal)
    copy_dialog = CopyDialog(context.preservation_service, copy_proposal, window)
    copy_dialog._finished(copy_result)
    copy_dialog.resize(760, 560)
    copy_dialog.show()
    pause(150)
    grab("copy_verification.png", copy_dialog)
    copy_dialog.close()
    add_dialog = AddArchiveDialog(context.archive_service, window)
    add_dialog.location_edit.setText(str(archive_root))
    add_dialog.name_edit.setText("Family Archive")
    add_dialog.availability_label.setText("Available")
    add_dialog.estimate_label.setText("Estimated files: 120")
    add_dialog.show()
    pause(150)
    grab("add_archive.png", add_dialog)
    add_dialog.close()
    resume_dialog = ResumeDialog(1, window)
    resume_dialog.show()
    pause(150)
    grab("resume_dialog.png", resume_dialog)
    resume_dialog.close()
    welcome_data = data_dir.parent / "welcome-data"
    if welcome_data.exists():
        shutil.rmtree(welcome_data)
    welcome_context = AppContext.create(welcome_data)
    welcome = MainWindow(welcome_context)
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
    latest_progress: list[object | None] = [None]
    window.controller.progress.connect(lambda progress: latest_progress.__setitem__(0, progress))
    window.controller.start(archive.id, AuditMode.DEEP, True)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        pause(50)
        progress = latest_progress[0]
        if progress is None or progress.stage.value != "processing":
            continue
        total = progress.files_total_estimate
        ratio = progress.files_processed / total if total else 0
        if 0.3 <= ratio <= 0.7 and progress.current_path:
            break
    grab("deep_audit_progress.png")
    if window.controller.is_running:
        loop = QEventLoop()
        window.controller.finished.connect(loop.quit)
        window.controller.failed.connect(loop.quit)
        QTimer.singleShot(120_000, loop.quit)
        loop.exec()
    window.close()
    for widget in (
        dialog,
        copy_dialog,
        add_dialog,
        resume_dialog,
        welcome,
        window,
    ):
        widget.deleteLater()
    app.processEvents()
    context.db.dispose()
    welcome_context.db.dispose()
    return saved


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "screenshots")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--archive-root", type=Path)
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
    owned_archive_root = args.archive_root is not None and not args.archive_root.exists()
    try:
        saved = capture(args.out, data_dir, args.archive_root)
        for path in saved:
            print(f"{path.name}\t{path.stat().st_size} bytes")
    finally:
        if owned_archive_root and args.archive_root is not None and args.archive_root.exists():
            shutil.rmtree(args.archive_root)
        if args.archive_root is not None and data_dir.exists():
            shutil.rmtree(data_dir)
        welcome_data = data_dir.parent / "welcome-data"
        if args.archive_root is not None and welcome_data.exists():
            shutil.rmtree(welcome_data)
        if temporary is not None:
            temporary.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
