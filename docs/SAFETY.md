# Safety model

## Originals are immutable

Audit operations open source files for reading. Discovery uses `scandir` and `stat`. Hashing uses unbuffered binary reads. Validators use read-only library and decoder paths. The audit engine does not rename, move, delete, or rewrite archive files.

Compatibility-copy output is separate from the original. The service rejects a final destination that resolves to the source path.

Immutability is tested with byte snapshots and SHA-256 comparisons, including:

- `test_quick_then_deep_real_tools_and_immutability`
- `test_demo_archive_quick_deep_and_incremental`
- `test_bmp_to_png_passes_pixel_equality_and_conflict_naming`
- `test_real_video_compatibility_copy`
- the `assert_unchanged()` fixture helper

## Local-first operation

Archives, settings, observations, findings, reports, and copy evidence remain local. KeepReadable has no account, telemetry, cloud upload, or remote processing service.

The only application network operation is a user-approved external-tool bootstrap. Bootstrap downloads pinned archives over HTTPS, verifies SHA-256, and extracts only manifest-listed members. The installed tools live below `%LOCALAPPDATA%\KeepReadable\tools` unless the data path is overridden.

## Subprocess boundary

`integrations/subprocess_runner.py` enforces:

- argument lists rather than command strings;
- `shell=False`;
- rejection of NUL characters;
- `stdin=DEVNULL`;
- separate stdout and stderr reader threads;
- bounded output buffers with a truncation marker;
- a polling cancellation and timeout loop;
- `kill()` followed by `wait()` on timeout or cancellation;
- `CREATE_NO_WINDOW` for Windows helper processes.

FFprobe and FFmpeg receive media input with a literal `file:` prefix, which prevents odd filenames from being interpreted as protocols or options. Siegfried receives one UTF-8 path per line in a temporary list file.

## ZIP handling

The ZIP validator never extracts archive members. It reads the central directory, metadata, encryption flags, entry names, declared sizes, compression ratios, and CRC data when Deep validation is selected.

Default limits are:

| Limit | Value |
|---|---:|
| Maximum entries | 100,000 |
| Maximum declared uncompressed size | 50 GiB |
| Suspicious compression ratio | 100.0 for entries larger than 1 MiB |

Absolute paths, drive letters, parent traversal, backslash traversal, and NUL-containing names produce a safety warning. Encrypted entries are marked PROTECTED and are not CRC-read.

## Reparse points and loops

Discovery does not follow reparse points or symbolic links by default. When following is explicitly enabled, directory `(device, inode)` identities prevent loops. File reparse points are not treated as regular source files. The test suite covers symlinks, junctions, ancestor loops, and an outside-root target.

## Data-directory exclusion

Discovery compares candidate directories with the KeepReadable data directory and does not enter it. This prevents the database, logs, tool installation, and generated application state from being audited as archive content when the archive root is a parent folder.

## Compatibility-copy output

The copy pipeline is:

1. Reject the source as destination.
2. Stream the source SHA-256 and deep-analyze the source.
3. Estimate output size and check free space.
4. Reserve `.keepreadable-tmp-<random>.<ext>` in the destination with exclusive creation.
5. Transform into that temporary file.
6. Recheck source size and mtime.
7. Reopen, deep-analyze, and hash the output.
8. Compare measurable source/output characteristics.
9. On PASSED or LIMITED, reserve a conflict-safe final name with `O_EXCL` and move the temporary output with `os.replace`.
10. On failure or cancellation, delete the temporary output and persist a failed GeneratedCopy evidence row with no output path.

Final names use `<stem>.access.<ext>`, followed by `<stem>.access-2.<ext>`, `<stem>.access-3.<ext>`, and so on when names already exist.

AVI and MOV conversion to MP4 uses H.264/AAC and is lossy. BMP conversion to PNG compares dimensions, compatible modes, and RGBA pixels.

## Protected content

Password-protected or encrypted content is marked PROTECTED rather than FAILED when a validator can establish that protection prevented internal checks. ZIP CRC checks are not attempted for encrypted entries. PDF and binary-container evidence records what remained untested.

## Malformed tool output

Adapters validate JSON shape and required container types. Malformed, truncated, and oversized garbage output is rejected as a tool-output error. The audit engine records identification as unavailable for that batch and continues. Tool errors are not treated as evidence about file content.

## Logging

`utilities/logging.py` configures a UTF-8 rotating file log at 5 MiB per file with five backups. The format records timestamp, level, logger name, and message. File contents are never written to logs. UI dialogs show short reasons and hide technical detail behind an explicit control.

## Limitations

- File permissions and exclusive locks can prevent individual checks. The engine records a scan error and continues when the archive root remains connected.
- A tool can validate only the behaviors it implements.
- Protected content cannot be checked internally without the required access information.
- Visual appearance, semantic accuracy, and user intent are outside the general audit model.
- Hardware or filesystem failures outside the observed checks can still occur.
