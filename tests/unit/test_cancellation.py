import pytest

from keepreadable.utilities.cancellation import CancellationToken, OperationCancelled


def test_cancellation_token_lifecycle() -> None:
    token = CancellationToken()
    assert not token.is_cancelled
    assert not token.wait(0)
    token.raise_if_cancelled()
    token.cancel()
    assert token.is_cancelled
    assert token.wait(0)
    with pytest.raises(OperationCancelled):
        token.raise_if_cancelled()
