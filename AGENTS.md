# Contributor Guide

## Hard rules

- Originals are never modified, renamed, moved, or deleted; scanning is read-only.
- Describe findings with evidence. A checksum difference is byte-change evidence, not a statement about cause.
- Run subprocesses with argument lists, `shell=False`, and timeouts.
- No AI, cloud, accounts, telemetry, web frontend, or backup features.
- Keep code compact, fully typed, and free of unnecessary comments.
- The prohibited user-facing terminology is enforced by `tests/unit/test_security.py`. Do not add unsupported preservation claims or broaden its allow-list.

## Architecture

Dependencies flow `ui -> application -> domain/analysis/validators/integrations/persistence`.
The domain layer depends on no other application layer. Only `ui` and `app.py` may import PySide6.

## Setup and quality

- `python -m uv sync --group dev`
- `python -m uv run ruff format --check .`
- `python -m uv run ruff check .`
- `python -m uv run mypy src`
- `python -m uv run pytest -q`

## Test groups

- CI unit/integration: `python -m uv run pytest -q -m "not external_tools and not e2e and not packaged and not benchmark"`
- External tools and E2E: `python -m uv run pytest -q -m "external_tools or e2e"`
- UI: `python -m uv run pytest -q -m ui`
- Slow: `python -m uv run pytest -q -m slow`
- Benchmark: `python -m uv run pytest -q -m benchmark`
- Packaged application: `python -m uv run pytest -q -m packaged`

## Project scripts

- `scripts/bootstrap_tools.py`: install pinned external tools.
- `scripts/create_demo_archive.py`: build the deterministic synthetic archive.
- `scripts/capture_screenshots.py`: capture desktop screenshots from the real application.
- `scripts/benchmark_scan.py`: generate raw benchmark JSON.
- `scripts/build_windows.py`: build and zip the Windows one-folder package.
- `scripts/generate_format_support.py`: regenerate `docs/FORMAT_SUPPORT.md`.
- `scripts/extract_pronom_puids.py`: reproduce PUID family lists from a DROID signature file.
- `scripts/make_icon.py`: regenerate application icons.

## Generated evidence rules

- `docs/FORMAT_SUPPORT.md` is generated. Run `scripts/generate_format_support.py`; the equality test enforces it.
- Screenshots must come from `scripts/capture_screenshots.py`, not from mock layouts or image editors.
- Benchmark numbers must come from committed `docs/benchmarks/*.json` files produced by `scripts/benchmark_scan.py`.
- Keep generated files and their source registries in the same commit.

## V1 exclusions

KeepReadable V1 does not provide AI features, cloud services, user accounts, telemetry,
a web frontend, backup functionality, or scheduled audits.
