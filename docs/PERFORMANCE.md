# Performance

These measurements describe one synthetic, small-file-heavy workload. They are not general storage-device or hashing benchmarks.

## Environment

| Item | Value |
|---|---|
| Operating system | Windows 11, build 10.0.26200 |
| CPU | 12th Gen Intel Core i5-1240P |
| Memory | 16,831,942,656 bytes (15.68 GiB) |
| Disk | KIOXIA KBG50ZNV512G NVMe SSD |
| Python | 3.12.3 |
| Siegfried | 1.11.8 |
| FFmpeg and ffprobe | 8.1.2 gyan.dev essentials |
| Worker count | `min(8, cpu_count)` |
| Persistence batch | 500 |
| Identification batch | 1,000 |

WMIC is not present on the test machine. CPU and disk names were read through PowerShell CIM and stored beside the unavailable WMIC result in the JSON files.

## Corpus

Each run creates a fresh synthetic archive with 200 directories:

- 85 % text files containing 1–8 KiB of deterministic printable bytes;
- 10 % JPEG images at 64×64;
- 5 % PNG images at 64×64.

The 10,000-file and 50,000-file archives contain no generated media files. The `--media-free` flag is recorded for the 50,000-file run.

## Methodology

`scripts/benchmark_scan.py` records `time.perf_counter()` durations. A sampling thread reads RSS every 0.5 seconds. On Windows it also records `peak_wset` from psutil.

The measured phases are:

1. Discovery-only full walk and files per second.
2. Cold Quick Audit and files per second.
3. Incremental Quick Audit with no changes.
4. Cold Deep Audit and hashed bytes per second.
5. Incremental Deep Audit within the verification interval.
6. Cancellation after five seconds and latency until `start()` returns.
7. Pause at half the archive, resume, and total wall time relative to cold Deep.
8. SQLite file size after the primary runs.

Each audit data directory starts fresh. Real Siegfried and FFmpeg installations are available through the normal locator.

## Identification-batch experiment

The 10,000-file archive was measured with the default four workers and identification batch sizes 200, 1,000, and 2,000.

| Identification batch | Quick cold | Files/s | Sampled peak RSS |
|---:|---:|---:|---:|
| 200 | 18.47 s | 541.3 | 107.3 MiB |
| 1,000 | 12.33 s | 811.0 | 115.7 MiB |
| 2,000 | 12.34 s | 810.4 | 125.8 MiB |

A 1,000-file batch reduced this run by about one third compared with 200 while remaining below 250 MiB. It was slightly faster than 2,000 and used less memory. The default was changed to 1,000. Finding additions, resolutions, and evidence updates were also aggregated once per persistence transaction instead of issuing repository calls for each file.

For the complete benchmark recipe, the changes were:

| Corpus | Metric | Before | After |
|---:|---|---:|---:|
| 10,000 | Quick cold | 39.68 s | 30.80 s |
| 10,000 | Deep cold | 35.58 s | 21.46 s |
| 50,000 | Quick cold | 172.88 s | 158.65 s |

## Current benchmark results

| Files | Discovery files/s | Quick cold | Quick incremental | Deep cold | Deep MB/s | Deep incremental | Cancel latency | Pause+resume / Deep | DB size | Peak sampled RSS |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10,000 | 14,308.4 | 30.80 s | 10.87 s | 21.46 s | 1.92 | 11.41 s | 0.039 s | 0.86× | 27.32 MiB | 124.0 MiB |
| 50,000 | 15,388.6 | 158.65 s | 52.47 s | 109.56 s | 1.90 | 54.97 s | 0.140 s | 0.88× | 148.09 MiB | 200.4 MiB |

Raw results:

- [bench-10000.json](benchmarks/bench-10000.json)
- [bench-50000.json](benchmarks/bench-50000.json)

## Observations

- Larger Siegfried batches reduce process startup and signature-loading overhead on cold identification runs.
- Incremental Quick and Deep runs still create historical observations, classify current policy, and reconcile findings, but reuse recent identification and validation evidence.
- Cold Deep elapsed time includes hashing, validator work, classification, and SQLite persistence. It is not only checksum time.
- The measured corpus is dominated by small files. The reported Deep MB/s is therefore not a hashing-throughput figure. Per-file discovery, process, parser, and database overhead are significant.
- Sampled RSS stayed near 124 MiB for 10,000 files and near 200 MiB for 50,000 files.
- The database grew from 27.32 MiB at 10,000 files to 148.09 MiB at 50,000 files after the measured history was recorded.
- Cancellation returned within 0.14 seconds after the five-second trigger in both committed runs.
- The 50,000-file result is the largest committed run. A 100,000-file run was not performed.

## Reproduction

```text
python -m uv run python scripts/benchmark_scan.py --files 10000 --out docs/benchmarks/bench-10000.json
python -m uv run python scripts/benchmark_scan.py --files 50000 --out docs/benchmarks/bench-50000.json --media-free
python -m uv run pytest -q -m benchmark
```

Run on an otherwise idle machine. Results depend on filesystem cache state, storage, CPU, tool versions, and background activity. Commit benchmark numbers only from the JSON output produced by the script.
