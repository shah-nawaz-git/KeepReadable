import os
from pathlib import Path

from platformdirs import user_data_dir


def data_dir() -> Path:
    override = os.environ.get("KEEPREADABLE_DATA_DIR")
    return Path(override) if override else Path(user_data_dir("KeepReadable", appauthor=False))


def default_database_path() -> Path:
    return data_dir() / "keepreadable.db"


def logs_dir() -> Path:
    return data_dir() / "logs"


def tools_dir() -> Path:
    return data_dir() / "tools"


def settings_path() -> Path:
    return data_dir() / "settings.json"
