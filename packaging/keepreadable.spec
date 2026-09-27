from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"
PACKAGE = SRC / "keepreadable"


def data_files(pattern: str, destination: str):
    return [(str(path), destination) for path in PACKAGE.glob(pattern)]


DATAS = [
    *data_files("resources/*.json", "keepreadable/resources"),
    *data_files("resources/*.png", "keepreadable/resources"),
    *data_files("resources/*.ico", "keepreadable/resources"),
    *data_files("policies/formats.yml", "keepreadable/policies"),
    *data_files("reporting/templates/*.j2", "keepreadable/reporting/templates"),
    *data_files("ui/theme/style.qss", "keepreadable/ui/theme"),
]

HIDDEN_IMPORTS = [
    "sqlalchemy.dialects.sqlite",
    "PySide6.QtSvg",
    *collect_submodules("reportlab"),
]

COMMON = dict(
    pathex=[str(SRC)],
    datas=DATAS,
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "tests", "pytest", "pytestqt", "mypy", "psutil"],
    noarchive=False,
    optimize=0,
)

gui_analysis = Analysis([str(PACKAGE / "app.py")], **COMMON)
gui_pyz = PYZ(gui_analysis.pure)
gui_exe = EXE(
    gui_pyz,
    gui_analysis.scripts,
    [],
    exclude_binaries=True,
    name="KeepReadable",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PACKAGE / "resources" / "icon.ico"),
)

cli_analysis = Analysis([str(PACKAGE / "cli.py")], **COMMON)
cli_pyz = PYZ(cli_analysis.pure)
cli_exe = EXE(
    cli_pyz,
    cli_analysis.scripts,
    [],
    exclude_binaries=True,
    name="KeepReadable-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PACKAGE / "resources" / "icon.ico"),
)

collection = COLLECT(
    gui_exe,
    cli_exe,
    gui_analysis.binaries,
    gui_analysis.datas,
    cli_analysis.binaries,
    cli_analysis.datas,
    strip=False,
    upx=False,
    name="KeepReadable",
)
