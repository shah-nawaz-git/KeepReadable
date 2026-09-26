import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from keepreadable.persistence.database import Database

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "keepreadable.db")
    database.initialize()
    yield database
    database.engine.dispose()
