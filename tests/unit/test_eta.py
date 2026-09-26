import pytest

from keepreadable.analysis.eta import EtaEstimator


def test_eta_requires_time_progress_and_stability() -> None:
    estimator = EtaEstimator(alpha=1.0)
    assert estimator.update(10, 1000, 10) is None
    assert estimator.update(50, 1000, 20) is None
    estimate = estimator.update(100, 1000, 30)
    assert estimate == pytest.approx(180.0)
    estimator.reset()
    assert estimator.update(100, 1000, 30) is None
