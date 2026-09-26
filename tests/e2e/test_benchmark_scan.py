from pathlib import Path

import pytest

from scripts.benchmark_scan import run_benchmark

pytestmark = pytest.mark.benchmark


def test_benchmark_sanity_two_thousand_files(tmp_path: Path) -> None:
    result = run_benchmark(2000, workspace=tmp_path, media_free=True)
    assert result["discovery"]["files"] == 2000
    assert result["quick_cold"]["files_per_second"] > 0
    assert result["quick_incremental"]["seconds"] < result["quick_cold"]["seconds"]
    peak = max(
        phase["memory"]["sampled_peak_rss"]
        for phase in result.values()
        if isinstance(phase, dict) and "memory" in phase
    )
    assert peak < 600 * 1024 * 1024
