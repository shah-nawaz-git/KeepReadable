import json
import sys
import threading
import time
from pathlib import Path

import pytest

from keepreadable.integrations.subprocess_runner import ToolNotFoundError, run_command
from keepreadable.utilities.cancellation import CancellationToken, OperationCancelled


def test_arguments_preserve_spaces_unicode_and_shell_characters() -> None:
    arguments = ["space value", "ünïcode 文件", "&& echo x"]
    result = run_command(
        [sys.executable, "-c", "import json,sys; print(json.dumps(sys.argv[1:]))", *arguments],
        timeout=5,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == arguments
    assert result.args[-1] == "&& echo x"


def test_nonzero_exit_is_returned() -> None:
    result = run_command([sys.executable, "-c", "import sys; sys.exit(7)"], timeout=5)
    assert result.returncode == 7
    assert not result.timed_out


def test_timeout_kills_child_quickly() -> None:
    started = time.monotonic()
    result = run_command([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.2)
    assert result.timed_out
    assert time.monotonic() - started < 2


def test_cancellation_kills_child_and_raises() -> None:
    token = CancellationToken()
    timer = threading.Timer(0.2, token.cancel)
    timer.start()
    try:
        with pytest.raises(OperationCancelled):
            run_command(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                timeout=10,
                cancel=token,
            )
    finally:
        timer.cancel()


def test_large_stdout_is_drained_and_captured() -> None:
    size = 5 * 1024 * 1024
    result = run_command(
        [sys.executable, "-c", f"import sys; sys.stdout.buffer.write(b'x' * {size})"],
        timeout=10,
    )
    assert result.returncode == 0
    assert len(result.stdout) == size
    assert result.stdout[:1] == b"x"


def test_nul_argument_is_rejected() -> None:
    with pytest.raises(ValueError, match="NUL"):
        run_command([sys.executable, "bad\0argument"], timeout=5)


def test_missing_executable_raises(tmp_path: Path) -> None:
    with pytest.raises(ToolNotFoundError):
        run_command([tmp_path / "missing-tool.exe"], timeout=5)
