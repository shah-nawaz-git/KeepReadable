import argparse
from collections.abc import Sequence
from pathlib import Path

from keepreadable.config.paths import tools_dir
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "tools":
        return 0 if _print_inventory(ToolLocator()) else 1
    if args.command == "bootstrap":
        return _bootstrap(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
