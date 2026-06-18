"""Command-line interface: scan, reindex, search."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .indexer import build_index, search
from .intake import format_report, scan_journal
from .migrate import apply_migration
from .model import Entry
from .parser import parse_file
from .store import is_managed, load_managed


def _collect_entries(roots: list[Path]) -> list[tuple[str, Entry]]:
    pairs: list[tuple[str, Entry]] = []
    for root in roots:
        name = root.stem if root.is_file() else root.name
        if root.is_file():
            pairs.extend((name, e) for e in parse_file(root))
        elif is_managed(root):
            pairs.extend((name, e) for e in load_managed(root))
        else:
            pairs.extend((name, e) for e in scan_journal(root).all_entries)
    return pairs


def _migrate(args: argparse.Namespace) -> int:
    if is_managed(args.root):
        print(f"{args.root} already has an entries/ directory — refusing to migrate.")
        return 1
    report = scan_journal(args.root)
    if not args.apply:
        print(format_report(report))
        print("\n(dry run — pass --apply to migrate)")
    else:
        result = apply_migration(report)
        print(f"Wrote {len(result.written)} entries to entries/")
        print(f"Dropped {len(result.dropped_duplicates)} duplicates (see migration-report.md)")
        print(f"Moved {len(result.moved_to_attic)} original files to attic/")
        print(f"Entries still needing a theme: {result.unthemed_count}")
    return 0


def _consolidate(args: argparse.Namespace) -> int:
    from . import consolidate

    specs: list[tuple[str, Path]] = []
    seen: dict[str, int] = {}
    for raw in args.sources:
        path = Path(raw).expanduser()
        name = path.name or "source"
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            name = f"{name}-{seen[name]}"
        specs.append((name, path))
    try:
        report = consolidate.scan_sources(specs)
        if not args.apply:
            print(consolidate.format_report(report, args.dest))
            print("\n(dry run — pass --apply to consolidate)")
        else:
            result = consolidate.apply_consolidation(report, args.dest)
            print(f"Wrote {len(result.written)} entries to {args.dest}")
            print(f"Merged {len(result.dropped_duplicates)} duplicates (see consolidation-report.md)")
            print(f"Archived and removed {len(result.archives)} sources")
    except consolidate.ConsolidationError as exc:
        print(f"Consolidation aborted: {exc}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai-journal")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="dry-run intake report for a journal directory")
    p_scan.add_argument("root", type=Path)

    p_migrate = sub.add_parser("migrate", help="migrate a journal to managed layout")
    p_migrate.add_argument("root", type=Path)
    p_migrate.add_argument("--apply", action="store_true", help="actually write; default prints the dry-run report")

    p_cons = sub.add_parser("consolidate", help="consolidate one or more sources into a new managed journal")
    p_cons.add_argument("dest", type=Path, help="destination path for the new managed journal (must be empty/new)")
    p_cons.add_argument(
        "--from",
        dest="sources",
        action="append",
        required=True,
        metavar="PATH",
        help="a source directory or file to consolidate; repeatable",
    )
    p_cons.add_argument("--apply", action="store_true", help="write; default prints the dry-run report")

    p_reindex = sub.add_parser("reindex", help="(re)build the search index")
    p_reindex.add_argument("roots", type=Path, nargs="+")
    p_reindex.add_argument("--db", type=Path, required=True)

    p_search = sub.add_parser("search", help="full-text search the index")
    p_search.add_argument("query")
    p_search.add_argument("--db", type=Path, required=True)
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--theme")
    p_search.add_argument("--since")
    p_search.add_argument("--until")

    p_refresh = sub.add_parser("refresh", help="regenerate JOURNAL.md and themes/ views")
    p_refresh.add_argument("root", type=Path)

    sub.add_parser("serve", help="run the MCP stdio server (requires ai-journal[server])")

    args = parser.parse_args(argv)

    if args.command == "scan":
        print(format_report(scan_journal(args.root)))
    elif args.command == "migrate":
        return _migrate(args)
    elif args.command == "consolidate":
        return _consolidate(args)
    elif args.command == "reindex":
        pairs = _collect_entries(args.roots)
        count = build_index(args.db, pairs)
        print(f"Indexed {count} entries into {args.db}")
    elif args.command == "refresh":
        from .migrate import refresh_views

        count, rescued = refresh_views(args.root)
        if rescued:
            print(f"Rescued {rescued} hand-added entries from JOURNAL.md into entries/")
        print(f"Regenerated views for {count} entries")
    elif args.command == "serve":
        from .server import main as serve_main

        serve_main()
    elif args.command == "search":
        results = search(args.db, args.query, limit=args.limit, theme=args.theme, since=args.since, until=args.until)
        if not results:
            print("No matches.")
        for row in results:
            title = row["title"] or "(untitled)"
            print(f"\n{row['date']}  [{row['theme']}]  {title}")
            print(f"  {row['source']}:{row['line']}")
            print(f"  {row['snippet']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
