# Third-party components

Versions are locked in `uv.lock` or `resources/tools.lock.json`. Python licence fields were checked against the installed wheel METADATA. External-tool hashes are the pinned manifest values.

## Runtime Python dependencies

| Component | Version | Licence | Role | Source | Distribution approach |
|---|---:|---|---|---|---|
| PySide6 | 6.11.2 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | Desktop UI and Qt worker/signalling boundary | https://doc.qt.io/qtforpython-6/ | pip dependency; Windows package keeps Qt as shared libraries |
| SQLAlchemy | 2.0.54 | MIT | ORM, sessions, and SQLite queries | https://www.sqlalchemy.org/ | pip dependency bundled by PyInstaller |
| pydantic | 2.13.5 | MIT | Settings and tool-manifest validation | https://docs.pydantic.dev/ | pip dependency bundled by PyInstaller |
| pypdf | 6.19.0 | BSD-3-Clause | Independent PDF page reading and warning evidence | https://pypdf.readthedocs.io/ | pip dependency bundled by PyInstaller |
| pikepdf | 10.13.0.post1 | MPL-2.0 | PDF object access and syntax checks | https://pikepdf.readthedocs.io/ | pip dependency bundled by PyInstaller |
| qpdf | bundled with pikepdf | Apache-2.0 | Native PDF engine used by pikepdf | https://qpdf.sourceforge.io/ | native shared library bundled as part of pikepdf |
| Pillow | 12.3.0 | MIT-CMU | Image validation, fixtures, icons, and BMP-to-PNG copies | https://python-pillow.github.io/ | pip dependency bundled by PyInstaller |
| python-docx | 1.2.0 | MIT | DOCX deep-load check | https://python-docx.readthedocs.io/ | pip dependency bundled by PyInstaller |
| openpyxl | 3.1.5 | MIT | XLSX read-only deep-load check | https://openpyxl.readthedocs.io/ | pip dependency bundled by PyInstaller |
| python-pptx | 1.0.2 | MIT | PPTX deep-load check | https://python-pptx.readthedocs.io/ | pip dependency bundled by PyInstaller |
| PyYAML | 6.0.3 | MIT | Format-policy registry | https://pyyaml.org/ | pip dependency bundled by PyInstaller |
| platformdirs | 4.11.10 | MIT | Default local data paths | https://github.com/tox-dev/platformdirs | pip dependency bundled by PyInstaller |
| reportlab | 5.0.1 | BSD | PDF audit reports | https://www.reportlab.com/opensource/ | pip dependency bundled by PyInstaller |
| Jinja2 | 3.1.6 | BSD-3-Clause | Autoescaped HTML audit reports | https://jinja.palletsprojects.com/ | pip dependency bundled by PyInstaller |
| defusedxml | 0.7.1 | PSF | Bounded OOXML XML parsing | https://github.com/tiran/defusedxml | pip dependency bundled by PyInstaller |
| lxml | 6.1.3 | BSD-3-Clause | Transitive XML support for pikepdf and Office libraries | https://lxml.de/ | transitive pip dependency bundled by PyInstaller |

## External tools

| Component | Version | Licence | Role | Source | Distribution approach |
|---|---:|---|---|---|---|
| Siegfried | 1.11.8 | Apache-2.0 | PRONOM format identification | https://www.itforarchivists.com/siegfried | Downloaded on demand over HTTPS, checksum-verified, installed locally, and invoked as a separate process |
| FFmpeg and ffprobe | 8.1.2 gyan.dev essentials | GPL-3.0-only | Media probing, full decode checks, and AVI/MOV compatibility copies | https://www.gyan.dev/ffmpeg/builds/ | Downloaded on demand over HTTPS, checksum-verified, installed locally, and invoked as separate processes; not linked or redistributed in the KeepReadable ZIP |

Pinned external artifacts:

| Artifact | SHA-256 | Allow-listed members |
|---|---|---|
| `siegfried_1-11-8_win64.zip` | `53ba621c675e7814073bf9a56937026a988006c25df81afd94fd0ac75e95454b` | `sf.exe` |
| `data_1-11-8.zip` | `7e057c913ec44df1deddad8e57088931fbf14feca8b8e6d78ccc50acc9a0066a` | `siegfried/default.sig` |
| `ffmpeg-8.1.2-essentials_build.zip` | `db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec` | `ffmpeg.exe`, `ffprobe.exe`, `LICENSE`, `README.txt` |

The locator order is:

1. `KEEPREADABLE_SF_PATH`, `KEEPREADABLE_FFMPEG_PATH`, or `KEEPREADABLE_FFPROBE_PATH`.
2. The current data directory's `tools` folder.
3. The default per-user tools folder.
4. A frozen application's adjacent `tools` folder.
5. `PATH`.

The Windows package does not include these tool binaries. Default installation is `%LOCALAPPDATA%\KeepReadable\tools\<tool>\`.

## Signature data

Siegfried uses:

- `DROID_SignatureFile_V125.xml`
- `container-signature-20260119.xml`

The National Archives, UK publishes DROID signature files at https://www.nationalarchives.gov.uk/aboutapps/pronom/droid-signature-files.htm with this statement:

> All content is available under the Open Government Licence v3.0, except where otherwise stated

The signature ZIP is downloaded from the pinned Siegfried release artifact. Only `siegfried/default.sig` is extracted. See The National Archives' terms for the source signature data.

## Development-only dependencies

| Component | Version | Licence | Role | Source | Distribution approach |
|---|---:|---|---|---|---|
| PyInstaller | 6.22.3 | GPLv2-or-later with bootloader exception | Windows one-folder build tool | https://pyinstaller.org/ | Development and CI only; generated bootloader output is distributed under the exception |
| pytest | 9.1.1 | MIT | Test runner | https://pytest.org/ | Development and CI only |
| pytest-qt | 4.5.0 | MIT | Offscreen UI testing | https://pytest-qt.readthedocs.io/ | Development and CI only |
| Ruff | 0.16.8 | MIT | Formatting and lint checks | https://docs.astral.sh/ruff/ | Development and CI only |
| mypy | 2.3.1 | MIT | Strict source typing | https://www.mypy-lang.org/ | Development and CI only |
| pip-audit | 2.10.1 | Apache-2.0 | Dependency advisory scan | https://github.com/pypa/pip-audit | Development and CI only |
| psutil | 7.2.2 | BSD-3-Clause | Benchmark memory sampling | https://github.com/giampaolo/psutil | Development and benchmark use only |

The CI workflow also runs Gitleaks as a repository secret scan.
