from keepreadable.integrations.tool_manifest import load_tool_manifest


def test_packaged_tool_manifest_loads_pinned_tools() -> None:
    manifest = load_tool_manifest()
    assert manifest.schema_version == 1
    assert manifest.tools["siegfried"].version == "1.11.8"
    assert manifest.tools["ffmpeg"].version == "8.1.2"
    assert manifest.tools["siegfried"].artifacts[0].members[0].from_ == "sf.exe"
