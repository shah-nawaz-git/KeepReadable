import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from keepreadable.integrations.tool_locator import ToolLocator, ToolName
from keepreadable.persistence.database import Database

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "keepreadable.db")
    database.initialize()
    yield database
    database.engine.dispose()


@pytest.fixture
def tools_available() -> ToolLocator:
    locator = ToolLocator()
    missing = [name.value for name in ToolName if locator.locate(name) is None]
    if locator.siegfried_home() is None:
        missing.append("siegfried signatures")
    if missing:
        pytest.skip(f"external tools unavailable: {', '.join(missing)}")
    return locator
