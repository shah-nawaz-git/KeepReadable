# Validation model

KeepReadable separates identity, integrity, structure, readability, and format policy. Each produces different evidence. No individual check proves every property of a file.

## Evidence dimensions

| Dimension | Definition | Evidence produced | Component | Does not prove |
|---|---|---|---|---|
| Identity | A signature or extension indicates a known format family and version. | PUID, format name, version, MIME type, signature warning, extension match | Siegfried with PRONOM signatures | That all internal structures are readable or that bytes are unchanged |
| Integrity | File bytes match or differ from a prior SHA-256 baseline. | SHA-256, hash time, prior/current values, changed-during-read evidence | Streaming hasher and classification | Why bytes changed or whether the current content is desirable |
| Structure | A format-aware parser can read expected headers, containers, objects, XML, or entry metadata. | Structural status, validator details, parser warnings, technical errors | Pillow, zipfile, pikepdf, defusedxml, OOXML libraries, ffprobe | Visual fidelity, semantic accuracy, or unchanged bytes |
| Readability | A validator or decoder can read requested content through the tested path. | Readability status, decode evidence, checked/not-checked lists | Pillow pixel load, ZIP CRC reads, PDF readers, OOXML libraries, FFmpeg decode | That every application renders the content identically |
| Format policy | The local policy set records access guidance for an identified PUID. | Policy status, reason code, explanation, source, policy version | `PolicyRegistry` and `formats.yml` | A file failure or a prediction about availability |

## Health-state derivation

The pure classifier in `domain/health.py` applies these rules in order.

| Condition | Health |
|---|---|
| Structural or readability status is FAILED | UNREADABLE |
| Format was not identified | UNKNOWN |
| Structural or readability is PROTECTED, WARNING, or UNAVAILABLE | REVIEW |
| Policy status is REVIEW | REVIEW |
| Extension does not match signature | REVIEW |
| None of the conditions above | HEALTHY |

A health state is a compact summary of recorded evidence. The observation retains the underlying statuses and details.

## CheckStatus meanings

| Status | Meaning |
|---|---|
| PASSED | The named check completed without evidence that failed its criteria. |
| WARNING | The check completed and produced evidence requiring review. |
| FAILED | The check could not satisfy its structural or decode criteria. |
| PROTECTED | Encryption or password protection prevented internal checks. |
| NOT_CHECKED | The check was outside the selected mode or validator capability. |
| UNAVAILABLE | A required tool or validation path was unavailable. |

## EvidenceCode meanings

| Code | Meaning |
|---|---|
| `STRUCTURAL_FAILURE` | Expected structure could not be read. |
| `DECODE_FAILURE` | Requested content decoding did not complete. |
| `UNEXPECTED_TRUNCATION` | Data ended before a requested read completed. |
| `VALIDATION_WARNING` | The validator returned a reviewable warning. |
| `PROTECTED_CONTENT` | Protection prevented internal validation. |
| `TOOL_UNAVAILABLE` | A required external tool was unavailable. |
| `VALIDATION_LIMITED` | The validator completed only a bounded subset. |
| `NOT_SUPPORTED` | This version has no format-specific validator for the file. |

## Quick and Deep audits

| Work | Quick Audit | Deep Audit |
|---|---|---|
| Discovery and metadata | Yes | Yes |
| Format identification | For new, changed, failed, or signature-updated files | For new, changed, untrusted, overdue, failed, forced, or signature-updated files |
| Quick structure check | Yes when planned | Replaced by the deep validator path |
| Streaming SHA-256 | No | Yes when deep verification is planned |
| Full pixel or stream decode | No | Yes for validators that support it |
| Classification and policy | Always | Always |
| Historical observation | Always | Always |

Quick work consists of `IDENTIFY`, `QUICK_STRUCTURE`, and `CLASSIFY`. It is useful for inventory and structural evidence. It does not establish a checksum baseline.

Deep work consists of `IDENTIFY`, `HASH`, `DEEP_VALIDATE`, and `CLASSIFY`. Recent unchanged files can reuse prior identification and validation when the planner selects `UNCHANGED_RECENT`.

## Deep-verification coverage

A FileRecord receives `last_deep_verified_at` only when a stable hash completed and `deep_verified` is true. A file that changed during the read does not receive a new baseline. Coverage counts present files whose timestamp falls within `deep_verification_interval_days`, which defaults to 180 days.

The coverage percentage is:

```text
verified present files within interval / total present files
```

It is a recency measure. It does not summarize every validator result.

## Terminology

| Term | Definition |
|---|---|
| Identified | A format signature supplied a usable format identity. |
| Structurally valid | The selected structural checks passed. The phrase must be paired with the checks performed. |
| Decodable | The selected decoder completed the requested content read. |
| Protected | Encryption or password protection prevented internal checks. |
| Unavailable | A required tool, archive root, or validation path could not be used. |
| Integrity mismatch | The SHA-256 value differs from the prior Deep baseline. It describes byte change, not cause. |
| Changed during scan | Source size or mtime changed while bytes were being read; no new checksum baseline is retained. |
| Moved | A missing path matches a newly seen file by SHA-256 and size in a Deep Audit. |
| Duplicate content | Present files share size and SHA-256. Intended roles may still differ. |
