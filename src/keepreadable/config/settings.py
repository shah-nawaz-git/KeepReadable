import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


class Settings(BaseModel):
    deep_verification_interval_days: int = 180
    worker_count: int = min(4, os.cpu_count() or 1)
    media_decode_workers: int = 2
    hash_buffer_size: int = 1024 * 1024
    follow_reparse_points: bool = False
    subprocess_timeout_seconds: int = 600
    identification_batch_size: int = 200
    persistence_batch_size: int = 500
    zip_max_entries: int = 100_000
    zip_max_declared_size_bytes: int = 50 * 1024**3
    zip_suspicious_ratio: float = 100.0
    copies_default_destination: str | None = None


def load_settings(path: Path) -> Settings:
    try:
        return Settings.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        logger.warning("Unable to load settings from %s; using defaults: %s", path, exc)
        return Settings()


def save_settings(settings: Settings, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(settings.model_dump_json(indent=2) + "\n", encoding="utf-8")
