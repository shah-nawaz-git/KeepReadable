import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from keepreadable.integrations.tool_locator import ToolLocator, ToolName
from keepreadable.persistence.database import Database
from keepreadable.validators.base import ValidationResult

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest_plugins = ("tests.fixture_factory.pytest_fixtures",)


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


@pytest.fixture(scope="session")
def validation_results() -> list[ValidationResult]:
    return []


@pytest.fixture
def record_validation(
    validation_results: list[ValidationResult],
) -> Callable[[ValidationResult], ValidationResult]:
    def record(result: ValidationResult) -> ValidationResult:
        validation_results.append(result)
        return result

    return record


@pytest.fixture(scope="session", autouse=True)
def enforce_validation_terminology(
    validation_results: list[ValidationResult],
) -> Iterator[None]:
    yield
    forbidden = (
        "corrupt",
        "guaranteed",
        "permanently",
        "future-proof",
        "fully valid",
        "archival master",
        "100%",
    )
    for result in validation_results:
        lowered = result.summary.casefold()
        assert not any(term in lowered for term in forbidden), result.summary
