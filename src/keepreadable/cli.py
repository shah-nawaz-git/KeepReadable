import argparse
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from keepreadable.application.container import AppContext
from keepreadable.config.paths import tools_dir
from keepreadable.domain.enums import AuditMode, AuditStatus
from keepreadable.integrations.bootstrap import BootstrapError, ToolBootstrapper
from keepreadable.integrations.tool_locator import ToolLocator
from keepreadable.integrations.tool_manifest import load_tool_manifest


def _print_inventory(locator: ToolLocator) -> bool:
    inventory = locator.inventory()
    for name, status in inventory.items():
        state = "installed" if status.installed else "unavailable"
        version = f" {status.version}" if status.version else ""
        source = f" [{status.source}]" if status.source else ""
        print(f"{name.value}: {state}{version}{source}")
        if status.path is not None:
            print(f"  path: {status.path}")
        if status.detail:
            for line in status.detail.splitlines()[1:] if status.installed else [status.detail]:
                print(f"  {line}")
    return all(status.installed for status in inventory.values())


def _bootstrap(args: argparse.Namespace) -> int:
    destination = Path(args.dest) if args.dest else tools_dir()
    cache = Path(args.cache) if args.cache else None
    bootstrapper = ToolBootstrapper(load_tool_manifest(), destination, download_cache=cache)
    selected = args.tool or None
    if args.check:
        return 0 if _print_inventory(ToolLocator(tools_dir=destination)) else 1
    try:
        plan = bootstrapper.plan(selected)
        if not args.yes:
            for item in plan:
                size = str(item.size_hint) if item.size_hint is not None else "unknown"
                print(f"{item.tool} {item.version}: {item.url}")
                print(f"  sha256: {item.sha256}; size: {size}; destination: {item.destination}")
            if input("Install these tools? [y/N] ").strip().casefold() != "y":
                return 1
        results = bootstrapper.install(
            selected,
            progress=lambda tool, downloaded, total: print(
                f"\r{tool}: {downloaded}/{total or '?'} bytes", end="", flush=True
            ),
        )
        print()
        for result in results:
            state = "installed" if result.installed else "failed"
            print(f"{result.tool}: {state} {result.version or ''}".rstrip())
            if result.detail:
                print(f"  {result.detail}")
        return 0 if all(result.installed for result in results) else 1
    except (BootstrapError, OSError) as exc:
        print(f"Bootstrap failed: {exc}")
        return 1


def _context(args: argparse.Namespace) -> AppContext:
    return AppContext.create(Path(args.data_dir) if getattr(args, "data_dir", None) else None)


def _archive_for_target(context: AppContext, target: str) -> int:
    try:
        archive_id = int(target)
    except ValueError:
        path = Path(target).resolve()
        for archive in context.archive_service.list_archives():
            if Path(archive.root_path) == path:
                assert archive.id is not None
                return archive.id
        archive = context.archive_service.add_archive(path.name or "Archive", path)
        assert archive.id is not None
        return archive.id
    if not any(archive.id == archive_id for archive in context.archive_service.list_archives()):
        raise ValueError(f"Archive {archive_id} does not exist")
    return archive_id


def _run_document(
    context: AppContext, archive_id: int, run_id: int, status: AuditStatus
) -> dict[str, object]:
    overview = context.archive_service.overview(archive_id)
    findings = context.findings_service.list_findings(archive_id=archive_id, limit=100000)
    files = context.file_service.list_files(archive_id, 0, 100000)
    return {
        "run_id": run_id,
        "status": status.value,
        "files": [
            {
                "id": record.id,
                "path": record.relative_path,
                "health": record.last_health.value if record.last_health else None,
            }
            for record in files
        ],
        "counts": {
            "files": overview.file_count,
            "bytes": overview.total_bytes,
            "health": {key.value: value for key, value in overview.health_counts.items()},
            "findings": dict(Counter(item.finding.code for item in findings)),
        },
    }


def _audit(args: argparse.Namespace) -> int:
    context = _context(args)
    archive_id = _archive_for_target(context, args.target)
    run = context.audit_engine.start(
        archive_id,
        AuditMode(args.mode),
        force_deep_all=args.force_deep_all,
    )
    document = _run_document(context, archive_id, run.id or 0, run.status)
    if args.json:
        print(json.dumps(document, indent=2))
    else:
        print(f"run id: {run.id}")
        print(f"status: {run.status.value}")
        counts = document["counts"]
        if isinstance(counts, dict):
            for name, value in counts.items():
                print(f"{name}: {value}")
    return 0 if run.status is AuditStatus.COMPLETED else 2


def _report(args: argparse.Namespace) -> int:
    context = _context(args)
    formats = ("html", "pdf") if args.format == "both" else (args.format,)
    paths = context.report_service.generate(
        args.run_id,
        Path(args.out),
        formats=formats,
    )
    for path in paths:
        print(path)
    return 0


def _resume(args: argparse.Namespace) -> int:
    context = _context(args)
    run = context.audit_engine.resume(args.run_id)
    document = _run_document(context, run.archive_id, run.id or 0, run.status)
    print(json.dumps(document, indent=2) if args.json else f"run {run.id}: {run.status.value}")
    return 0 if run.status is AuditStatus.COMPLETED else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keepreadable-cli")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("tools", help="show external tool inventory")
    bootstrap = subcommands.add_parser("bootstrap", help="install pinned external tools")
    bootstrap.add_argument("--tool", action="append", choices=["siegfried", "ffmpeg"])
    bootstrap.add_argument("--dest")
    bootstrap.add_argument("--cache")
    bootstrap.add_argument("--yes", action="store_true")
    bootstrap.add_argument("--check", action="store_true")
    archives = subcommands.add_parser("archives")
    archives.add_argument("--data-dir")
    add = subcommands.add_parser("add")
    add.add_argument("name")
    add.add_argument("directory")
    add.add_argument("--data-dir")
    audit = subcommands.add_parser("audit")
    audit.add_argument("target")
    audit.add_argument("--mode", choices=[mode.value for mode in AuditMode], default="quick")
    audit.add_argument("--force-deep-all", action="store_true")
    audit.add_argument("--json", action="store_true")
    audit.add_argument("--data-dir")
    resume = subcommands.add_parser("resume")
    resume.add_argument("run_id", type=int)
    resume.add_argument("--json", action="store_true")
    resume.add_argument("--data-dir")
    report = subcommands.add_parser("report")
    report.add_argument("run_id", type=int)
    report.add_argument("--out", required=True)
    report.add_argument("--format", choices=("html", "pdf", "both"), default="both")
    report.add_argument("--data-dir")
    findings = subcommands.add_parser("findings")
    findings.add_argument("archive_id", type=int)
    findings.add_argument("--json", action="store_true")
    findings.add_argument("--data-dir")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "tools":
            return 0 if _print_inventory(ToolLocator()) else 1
        if args.command == "bootstrap":
            return _bootstrap(args)
        context = _context(args)
        if args.command == "archives":
            for archive in context.archive_service.list_archives():
                print(f"{archive.id}\t{archive.name}\t{archive.root_path}")
            return 0
        if args.command == "add":
            archive = context.archive_service.add_archive(args.name, Path(args.directory))
            print(f"{archive.id}\t{archive.name}\t{archive.root_path}")
            return 0
        if args.command == "audit":
            return _audit(args)
        if args.command == "resume":
            return _resume(args)
        if args.command == "report":
            return _report(args)
        if args.command == "findings":
            items = context.findings_service.list_findings(archive_id=args.archive_id, limit=100000)
            if args.json:
                print(
                    json.dumps(
                        [
                            {
                                "id": item.finding.id,
                                "code": item.finding.code,
                                "severity": item.finding.severity.value,
                                "path": item.relative_path,
                                "title": item.finding.title,
                            }
                            for item in items
                        ],
                        indent=2,
                    )
                )
            else:
                for item in items:
                    print(
                        f"{item.finding.severity.value}\t{item.finding.code}\t"
                        f"{item.relative_path or '-'}\t{item.finding.title}"
                    )
            return 0
    except Exception as exc:
        print(f"Error: {exc}")
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
