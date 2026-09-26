class EtaEstimator:
    def __init__(self, alpha: float = 0.35) -> None:
        self.alpha = alpha
        self._last_processed = 0
        self._last_elapsed = 0.0
        self._ema_rate: float | None = None
        self._last_estimate: float | None = None

    def update(self, processed: int, total: int, elapsed_seconds: float) -> float | None:
        delta_files = processed - self._last_processed
        delta_seconds = elapsed_seconds - self._last_elapsed
        if delta_files > 0 and delta_seconds > 0:
            rate = delta_files / delta_seconds
            self._ema_rate = (
                rate
                if self._ema_rate is None
                else self.alpha * rate + (1 - self.alpha) * self._ema_rate
            )
        self._last_processed = processed
        self._last_elapsed = elapsed_seconds
        if (
            total <= 0
            or processed >= total
            or elapsed_seconds < 20
            or processed / total < 0.05
            or self._ema_rate is None
        ):
            return None
        estimate = (total - processed) / self._ema_rate
        previous = self._last_estimate
        self._last_estimate = estimate
        if previous is None or max(previous, estimate) == 0:
            return None
        if abs(estimate - previous) / max(previous, estimate) >= 0.3:
            return None
        return estimate

    def reset(self) -> None:
        self._last_processed = 0
        self._last_elapsed = 0.0
        self._ema_rate = None
        self._last_estimate = None
