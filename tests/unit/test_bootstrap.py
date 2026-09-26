import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from keepreadable.integrations.bootstrap import BootstrapError, ToolBootstrapper
from keepreadable.integrations.tool_locator import ToolName, ToolStatus
from keepreadable.integrations.tool_manifest import (
    ToolArtifact,
    ToolManifest,
    ToolMember,
    ToolSpec,
)
from keepreadable.utilities.cancellation import CancellationToken, OperationCancelled


def zip_payload(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def manifest_for(
    payload: bytes,
    *,
    url: str = "https://example.test/tool.zip",
    source: str = "package/bin/ffmpeg.exe",
) -> ToolManifest:
    return ToolManifest(
        schema_version=1,
        tools={
            "ffmpeg": ToolSpec(
                version="1.2.3",
                license="test",
                homepage="https://example.test",
                purpose="test",
                artifacts=(
                    ToolArtifact(
                        name="tool.zip",
                        url=url,
                        sha256=hashlib.sha256(payload).hexdigest(),
                        members=(ToolMember(from_=source, to="ffmpeg.exe"),),
                    ),
                ),
            )
        },
    )


def successful_inventory() -> dict[ToolName, ToolStatus]:
    return {
        name: ToolStatus(name, True, Path(f"{name}.exe"), "1.2.3", None, "app_data")
        for name in ToolName
    }


def test_install_extracts_only_manifest_members_and_writes_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = zip_payload(
        {
            "package/bin/ffmpeg.exe": b"executable",
            "package/extra.txt": b"must not extract",
        }
    )
    monkeypatch.setattr(
        "keepreadable.integrations.bootstrap.ToolLocator.inventory",
        lambda _self: successful_inventory(),
    )
    progress: list[int] = []
    bootstrapper = ToolBootstrapper(
        manifest_for(payload),
        tmp_path / "tools",
        opener=lambda _url: io.BytesIO(payload),
    )
    results = bootstrapper.install(
        progress=lambda _tool, downloaded, _total: progress.append(downloaded)
    )

    destination = tmp_path / "tools" / "ffmpeg"
    assert results[0].installed
    assert (destination / "ffmpeg.exe").read_bytes() == b"executable"
    assert not (destination / "extra.txt").exists()
    metadata = json.loads((destination / "installed.json").read_text(encoding="utf-8"))
    assert metadata["tool"] == "ffmpeg"
    assert metadata["version"] == "1.2.3"
    assert metadata["artifacts"] == ["ffmpeg.exe"]
    assert progress == [len(payload)]
    assert bootstrapper.is_installed("ffmpeg")


def test_checksum_mismatch_installs_nothing(tmp_path: Path) -> None:
    expected = zip_payload({"package/bin/ffmpeg.exe": b"expected"})
    actual = zip_payload({"package/bin/ffmpeg.exe": b"different"})
    bootstrapper = ToolBootstrapper(
        manifest_for(expected),
        tmp_path / "tools",
        opener=lambda _url: io.BytesIO(actual),
    )
    with pytest.raises(BootstrapError, match="Checksum mismatch"):
        bootstrapper.install()
    assert not (tmp_path / "tools" / "ffmpeg" / "ffmpeg.exe").exists()
    assert list((tmp_path / "tools").glob("*.download")) == []


def test_http_url_is_rejected(tmp_path: Path) -> None:
    payload = zip_payload({"package/bin/ffmpeg.exe": b"tool"})
    bootstrapper = ToolBootstrapper(
        manifest_for(payload, url="http://example.test/tool.zip"), tmp_path / "tools"
    )
    with pytest.raises(BootstrapError, match="HTTPS"):
        bootstrapper.plan()


def test_parent_member_is_rejected(tmp_path: Path) -> None:
    payload = zip_payload({"../ffmpeg.exe": b"tool"})
    bootstrapper = ToolBootstrapper(
        manifest_for(payload, source="../ffmpeg.exe"),
        tmp_path / "tools",
        opener=lambda _url: io.BytesIO(payload),
    )
    with pytest.raises(BootstrapError, match="Unsafe archive member"):
        bootstrapper.install()
    assert not (tmp_path / "tools" / "ffmpeg.exe").exists()


def test_cancellation_cleans_download_temp_file(tmp_path: Path) -> None:
    payload = zip_payload({"package/bin/ffmpeg.exe": b"x" * (2 * 1024 * 1024)})
    token = CancellationToken()

    class CancellingResponse(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            chunk = super().read(size)
            if chunk:
                token.cancel()
            return chunk

    bootstrapper = ToolBootstrapper(
        manifest_for(payload),
        tmp_path / "tools",
        opener=lambda _url: CancellingResponse(payload),
    )
    with pytest.raises(OperationCancelled):
        bootstrapper.install(cancel=token)
    assert list((tmp_path / "tools").glob("*.download")) == []
