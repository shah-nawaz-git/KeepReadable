# Contributor Guide

## Hard rules

- Originals are never modified, renamed, moved, or deleted; scanning is read-only.
- Describe findings with evidence. Never equate a hash change with corruption or make unsupported preservation claims.
- Run subprocesses with argument lists, `shell=False`, and timeouts.
- No AI, cloud, accounts, telemetry, web frontend, or backup features.
- Keep code compact, fully typed, and free of unnecessary comments.

## Architecture

Dependencies flow `ui -> application -> domain/analysis/validators/integrations/persistence`.
The domain layer depends on no other application layer. Only `ui` may import PySide6.

## Commands

- `python -m uv sync --group dev`
- `python -m uv run ruff format --check .`
- `python -m uv run ruff check .`
- `python -m uv run mypy src`
- `python -m uv run pytest`
- `python -m uv run pytest -m external_tools`
- `python -m uv run python scripts/build_windows.py`
- `python -m uv run pytest -m packaged`
- `python -m uv run pytest -m benchmark`

## V1 exclusions

KeepReadable V1 does not provide AI features, cloud services, user accounts, telemetry,
a web frontend, or backup functionality.
