from threading import Event


class OperationCancelled(Exception):
    pass


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()
        self._reason: str | None = None

    def cancel(self, reason: str | None = None) -> None:
        self._reason = reason
        self._event.set()

    @property
    def reason(self) -> str | None:
        return self._reason

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise OperationCancelled

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)
