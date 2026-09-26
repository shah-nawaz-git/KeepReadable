# ruff: noqa: E402

import argparse
import json
import os
import platform
import random
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from keepreadable.analysis.discovery import DiscoveryOptions, discover_files
from keepreadable.application.audit_service import AuditProgress, AuditStage
from keepreadable.application.container import AppContext
from keepreadable.config.settings import Settings
from keepreadable.domain.enums import AuditMode
from keepreadable.integrations.tool_locator import ToolName
from keepreadable.utilities.cancellation import CancellationToken
from tests.fixture_factory import make_jpeg, make_png


def build_archive(root: Path, count: int, seed: int = 42) -> None:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    randomizer = random.Random(seed)
    for index in range(count):
        directory = root / f"dir-{index % 200:03}"
        directory.mkdir(exist_ok=True)
        selector = index % 20
        if selector < 17:
            size = randomizer.randint(1024, 8192)
            payload = bytes(randomizer.randrange(32, 127) for _ in range(size))
            (directory / f"file-{index:06}.txt").write_bytes(payload)
        elif selector < 19:
            make_jpeg(
                directory / f"image-{index:06}.jpg",
                size=(64, 64),
                seed=seed + index,
            )
        else:
            make_png(
                directory / f"image-{index:06}.png",
                size=(64, 64),
                seed=seed + index,
            )


class MemorySampler:
    def __init__(self) -> None:
        self.process = psutil.Process()
        self.maximum_rss = self.process.memory_info().rss
        self.running = False
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.running = True
        self.thread = threading.Thread(target=self._sample, daemon=True)
        self.thread.start()

    def stop(self) -> dict[str, int]:
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=2)
        memory = self.process.memory_info()
        return {
            "sampled_peak_rss": self.maximum_rss,
            "process_peak_wset": int(getattr(memory, "peak_wset", self.maximum_rss)),
        }

    def _sample(self) -> None:
        while self.running:
            self.maximum_rss = max(
                self.maximum_rss,
                self.process.memory_info().rss,
            )
            time.sleep(0.5)


def measured(function: Any) -> tuple[Any, float, dict[str, int]]:
    sampler = MemorySampler()
    sampler.start()
    started = time.perf_counter()
    try:
        result = function()
    finally:
        elapsed = time.perf_counter() - started
        memory = sampler.stop()
    return result, elapsed, memory


def command_output(args: list[str]) -> str:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    return result.stdout.strip() or result.stderr.strip() or "unavailable"


def run_benchmark(
    count: int,
    *,
    workspace: Path,
    media_free: bool,
) -> dict[str, Any]:
    archive_root = workspace / f"bench-{count}"
    data_root = workspace / f"bench-{count}-data"
    if data_root.exists():
        shutil.rmtree(data_root)
    build_archive(archive_root, count)
    settings = Settings(
        worker_count=min(8, os.cpu_count() or 1),
        persistence_batch_size=500,
        identification_batch_size=500,
    )
    context = AppContext.create(data_root, settings)
    archive = context.archive_service.add_archive(f"Benchmark {count}", archive_root)
    assert archive.id is not None

    discovered, discovery_seconds, discovery_memory = measured(
        lambda: sum(1 for _ in discover_files(archive_root, DiscoveryOptions()))
    )
    quick_cold, quick_cold_seconds, quick_cold_memory = measured(
        lambda: context.audit_engine.start(archive.id or 0, AuditMode.QUICK)
    )
    _quick_incremental, quick_incremental_seconds, quick_incremental_memory = measured(
        lambda: context.audit_engine.start(archive.id or 0, AuditMode.QUICK)
    )
    deep_cold, deep_cold_seconds, deep_cold_memory = measured(
        lambda: context.audit_engine.start(archive.id or 0, AuditMode.DEEP)
    )
    _deep_incremental, deep_incremental_seconds, deep_incremental_memory = measured(
        lambda: context.audit_engine.start(archive.id or 0, AuditMode.DEEP)
    )
    bytes_hashed = int(deep_cold.resume_state.get("bytes_hashed", 0))

    cancel_data = workspace / f"bench-{count}-cancel-data"
    if cancel_data.exists():
        shutil.rmtree(cancel_data)
    cancel_context = AppContext.create(cancel_data, settings)
    cancel_archive = cancel_context.archive_service.add_archive(
        f"Benchmark cancel {count}", archive_root
    )
    assert cancel_archive.id is not None
    cancel_token = CancellationToken()
    timer = threading.Timer(5.0, cancel_token.cancel)
    timer.start()
    cancellation_started = time.perf_counter()
    cancelled_run = cancel_context.audit_engine.start(
        cancel_archive.id,
        AuditMode.DEEP,
        cancel=cancel_token,
    )
    cancellation_total = time.perf_counter() - cancellation_started
    timer.cancel()
    cancellation_latency = max(0.0, cancellation_total - 5.0)

    resume_data = workspace / f"bench-{count}-resume-data"
    if resume_data.exists():
        shutil.rmtree(resume_data)
    resume_context = AppContext.create(resume_data, settings)
    resume_archive = resume_context.archive_service.add_archive(
        f"Benchmark resume {count}", archive_root
    )
    assert resume_archive.id is not None
    pause_token = CancellationToken()

    def pause_halfway(progress: AuditProgress) -> None:
        if (
            progress.stage is AuditStage.PROCESSING
            and progress.files_total_estimate
            and progress.files_processed / progress.files_total_estimate >= 0.5
        ):
            pause_token.cancel("pause")

    resume_started = time.perf_counter()
    paused = resume_context.audit_engine.start(
        resume_archive.id,
        AuditMode.DEEP,
        cancel=pause_token,
        on_progress=pause_halfway,
    )
    resumed = resume_context.audit_engine.resume(paused.id or 0)
    resume_total = time.perf_counter() - resume_started

    inventory = context.tool_locator.inventory()
    environment = {
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cpu_wmic": command_output(["wmic", "cpu", "get", "name"]),
        "disk_wmic": command_output(["wmic", "diskdrive", "get", "MediaType,Model"]),
        "cpu_cim": command_output(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Processor | Select-Object -ExpandProperty Name",
            ]
        ),
        "disk_cim": command_output(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                (
                    "Get-CimInstance Win32_DiskDrive | ForEach-Object { "
                    '"$($_.MediaType)|$($_.Model)" }'
                ),
            ]
        ),
        "ram_bytes": psutil.virtual_memory().total,
        "python": platform.python_version(),
        "tools": {name.value: inventory[name].version or "not installed" for name in ToolName},
        "media_free": media_free,
    }
    result = {
        "files": count,
        "environment": environment,
        "discovery": {
            "files": discovered,
            "seconds": discovery_seconds,
            "files_per_second": discovered / discovery_seconds,
            "memory": discovery_memory,
        },
        "quick_cold": {
            "seconds": quick_cold_seconds,
            "files_per_second": quick_cold.files_processed / quick_cold_seconds,
            "memory": quick_cold_memory,
        },
        "quick_incremental": {
            "seconds": quick_incremental_seconds,
            "memory": quick_incremental_memory,
        },
        "deep_cold": {
            "seconds": deep_cold_seconds,
            "megabytes_per_second": (
                bytes_hashed / (1024 * 1024) / deep_cold_seconds if deep_cold_seconds else 0
            ),
            "bytes_hashed": bytes_hashed,
            "memory": deep_cold_memory,
        },
        "deep_incremental": {
            "seconds": deep_incremental_seconds,
            "memory": deep_incremental_memory,
        },
        "cancellation": {
            "total_seconds": cancellation_total,
            "latency_seconds": cancellation_latency,
            "status": cancelled_run.status.value,
        },
        "resume": {
            "seconds": resume_total,
            "overhead_ratio": resume_total / deep_cold_seconds,
            "status": resumed.status.value,
        },
        "database_bytes": Path(context.db.path).stat().st_size,
    }
    context.db.dispose()
    cancel_context.db.dispose()
    resume_context.db.dispose()
    return result


def markdown(results: list[dict[str, Any]]) -> str:
    lines = [
        (
            "| Files | Discovery files/s | Quick cold s | Quick incremental s | "
            "Deep cold s | Deep MB/s | Deep incremental s | Cancel latency s | "
            "Resume/deep | DB MB | Peak RSS MB |"
        ),
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        peak = max(
            phase["memory"]["sampled_peak_rss"]
            for key, phase in result.items()
            if isinstance(phase, dict) and "memory" in phase
        )
        lines.append(
            "| {files:,} | {discovery:.1f} | {quick:.2f} | {quick_i:.2f} | "
            "{deep:.2f} | {mbps:.2f} | {deep_i:.2f} | {cancel:.3f} | "
            "{resume:.2f} | {db:.2f} | {rss:.1f} |".format(
                files=result["files"],
                discovery=result["discovery"]["files_per_second"],
                quick=result["quick_cold"]["seconds"],
                quick_i=result["quick_incremental"]["seconds"],
                deep=result["deep_cold"]["seconds"],
                mbps=result["deep_cold"]["megabytes_per_second"],
                deep_i=result["deep_incremental"]["seconds"],
                cancel=result["cancellation"]["latency_seconds"],
                resume=result["resume"]["overhead_ratio"],
                db=result["database_bytes"] / (1024 * 1024),
                rss=peak / (1024 * 1024),
            )
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--media-free", action="store_true")
    args = parser.parse_args()
    result = run_benchmark(
        args.files,
        workspace=ROOT / "tests" / ".tmp",
        media_free=args.media_free,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(markdown([result]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
