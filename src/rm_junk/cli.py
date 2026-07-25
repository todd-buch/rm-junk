from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rm_junk import __version__
from rm_junk.config import (
    ConfigError,
    default_settings_path,
    ensure_user_settings,
    load_settings,
)
from rm_junk.deletion import DeletionError, delete_path
from rm_junk.finding_store import FindingStore
from rm_junk.models import FindingStatus, format_bytes
from rm_junk.path_policy import PathPolicy
from rm_junk.scanners import meets_min_confidence, run_all_scanners


def _print_finding(idx: int, finding, *, show_id: bool = True) -> None:
    """Human-readable finding block for scan/list output."""
    size = format_bytes(finding.size_bytes)
    cat = finding.category.value.replace("_", " ")
    conf = finding.confidence.value
    print(f"  {idx}.  {size}  ·  {cat}  ·  {conf} confidence")
    print(f"      {finding.path}")
    print(f"      {finding.reason}")
    if show_id:
        print(f"      id: {finding.id}")
    print()


def cmd_init(_args: argparse.Namespace) -> int:
    path = ensure_user_settings()
    print(f"Settings ready: {path}")
    print("Edit that file to configure exclude paths, thresholds, and scan options.")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    try:
        settings = load_settings(Path(args.config) if args.config else None)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1

    policy = PathPolicy(settings)
    from rm_junk.parallel import default_workers
    from rm_junk.progress import NullProgress, TerminalProgress

    w = default_workers(settings.scan.workers or None)
    threshold_gb = settings.scan.large_file_min_bytes / (1024**3)
    print("rm-junk scan", flush=True)
    if args.debug:
        print(
            f"  workers={w}  large≥{threshold_gb:g}GB  "
            f"(permission-denied paths are skipped)",
            flush=True,
        )
    if args.no_progress:
        progress = NullProgress()
    else:
        progress = TerminalProgress(debug=args.debug, workers=w)

    findings = run_all_scanners(settings, policy, progress=progress)

    if args.queue_only:
        findings = [
            f
            for f in findings
            if meets_min_confidence(f, settings.scan.min_confidence_for_queue)
        ]

    if not findings:
        print("No findings.")
        if not args.dry_run:
            store = FindingStore()
            store.replace_pending_with([])
        return 0

    total = sum(f.size_bytes for f in findings)
    by_cat: dict[str, int] = {}
    for f in findings:
        by_cat[f.category.value] = by_cat.get(f.category.value, 0) + 1

    print(f"\nFound {len(findings)} item(s)  ·  ~{format_bytes(total)}")
    if by_cat:
        summary = ", ".join(
            f"{k.replace('_', ' ')}: {v}" for k, v in sorted(by_cat.items())
        )
        print(f"Categories: {summary}")
    print()
    for i, finding in enumerate(findings, start=1):
        _print_finding(i, finding)

    if args.dry_run:
        print("Dry run — results not saved.")
        return 0

    store = FindingStore()
    store.replace_pending_with(findings)
    print(f"Saved {len(findings)} pending item(s) → {store.path}")
    print("Review:  rm-junk list")
    print("Act:     rm-junk delete <id> [id…]   |   rm-junk delete --all")
    print("         rm-junk keep <id> [id…]     |   rm-junk keep --all")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    store = FindingStore()
    pending = store.pending
    if not pending:
        print("No pending findings. Run: rm-junk scan")
        return 0
    total = sum(f.size_bytes for f in pending)
    print(f"{len(pending)} pending (~{format_bytes(total)}):\n")
    for i, finding in enumerate(pending, start=1):
        _print_finding(i, finding)
    return 0


def _resolve_pending(store: FindingStore, ids: list[str]):
    """Resolve finding ids; support full hex ids only (not list numbers)."""
    found = []
    missing = []
    for fid in ids:
        finding = store.get(fid)
        if finding is None or finding.status != FindingStatus.PENDING:
            missing.append(fid)
        else:
            found.append(finding)
    return found, missing


def cmd_delete(args: argparse.Namespace) -> int:
    try:
        settings = load_settings(Path(args.config) if args.config else None)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1

    store = FindingStore()
    if args.all:
        targets = list(store.pending)
        if not targets:
            print("No pending findings to delete.")
            return 0
    else:
        if not args.ids:
            print("Pass one or more ids, or use --all.", file=sys.stderr)
            return 1
        targets, missing = _resolve_pending(store, args.ids)
        for fid in missing:
            print(f"No pending finding with id {fid}", file=sys.stderr)
        if not targets:
            return 1

    total = sum(f.size_bytes for f in targets)
    action = "Trash" if settings.deletion.move_to_trash else "Delete"
    print(f"{action} {len(targets)} item(s) (~{format_bytes(total)})?")
    for f in targets:
        print(f"  · {format_bytes(f.size_bytes):>10}  {f.path}")

    if not args.yes:
        reply = input(f"\nProceed? [y/N] ").strip().lower()
        if reply not in {"y", "yes"}:
            print("Cancelled.")
            return 0

    policy = PathPolicy(settings)
    ok = 0
    failed = 0
    recovered = 0
    for finding in targets:
        try:
            delete_path(
                finding.path,
                policy,
                to_trash=settings.deletion.move_to_trash,
            )
            store.mark(finding.id, FindingStatus.DELETED)
            print(f"  ✓ {format_bytes(finding.size_bytes):>10}  {finding.path}")
            ok += 1
            recovered += finding.size_bytes
        except DeletionError as exc:
            print(f"  ✗ {finding.path}: {exc}", file=sys.stderr)
            failed += 1

    done = "Trashed" if settings.deletion.move_to_trash else "Deleted"
    print()
    if ok:
        where = "Trash" if settings.deletion.move_to_trash else "disk"
        print(f"{done} {ok} item(s)" + (f", {failed} failed" if failed else ""))
        print(f"Space recovered:  ~{format_bytes(recovered)}")
        if settings.deletion.move_to_trash:
            print(f"(Moved to {where} — empty Trash later to free disk fully.)")
    else:
        print(f"Nothing removed" + (f" ({failed} failed)" if failed else ""))
    return 1 if failed and not ok else 0


def cmd_keep(args: argparse.Namespace) -> int:
    try:
        settings = load_settings(Path(args.config) if args.config else None)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1

    store = FindingStore()
    if args.all:
        targets = list(store.pending)
        if not targets:
            print("No pending findings to keep.")
            return 0
    else:
        if not args.ids:
            print("Pass one or more ids, or use --all.", file=sys.stderr)
            return 1
        targets, missing = _resolve_pending(store, args.ids)
        for fid in missing:
            print(f"No pending finding with id {fid}", file=sys.stderr)
        if not targets:
            return 1

    whitelist = list(settings.whitelist)
    for finding in targets:
        whitelist.append(finding.path)
        store.mark(finding.id, FindingStatus.KEPT)
        print(f"Whitelisted: {finding.path}")
    settings.save_whitelist(whitelist)
    print(f"Updated: {settings.path}  ({len(targets)} kept)")
    return 0


def cmd_paths(_args: argparse.Namespace) -> int:
    from rm_junk.config import default_findings_path, project_root

    print(f"project:  {project_root()}")
    print(f"settings: {default_settings_path()}")
    print(f"findings: {default_findings_path()}")
    print(f"example:  settings.example.json (repo root)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rm-junk",
        description="Find leftover caches, orphans, and large files on macOS.",
    )
    parser.add_argument("--version", action="version", version=f"rm-junk {__version__}")
    parser.add_argument(
        "--config",
        help="Path to settings.json (default: project dir settings.json)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create default settings.json if missing")
    p_init.set_defaults(func=cmd_init)

    p_scan = sub.add_parser("scan", help="Run scanners and save pending findings")
    p_scan.add_argument(
        "--dry-run",
        action="store_true",
        help="Print findings without saving",
    )
    p_scan.add_argument(
        "--queue-only",
        action="store_true",
        help="Only include findings meeting minConfidenceForQueue",
    )
    p_scan.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable the progress bar",
    )
    p_scan.add_argument(
        "--debug",
        action="store_true",
        help="Verbose scan logs and per-item names on the progress bar",
    )
    p_scan.set_defaults(func=cmd_scan)

    p_list = sub.add_parser("list", help="List pending findings")
    p_list.set_defaults(func=cmd_list)

    p_del = sub.add_parser(
        "delete",
        help="Delete (trash) findings by id, or --all remaining pending",
    )
    p_del.add_argument(
        "ids",
        nargs="*",
        help="One or more finding ids from scan/list",
    )
    p_del.add_argument(
        "--all",
        action="store_true",
        help="Delete every remaining pending finding",
    )
    p_del.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    p_del.set_defaults(func=cmd_delete)

    p_keep = sub.add_parser(
        "keep",
        help="Whitelist findings by id, or --all remaining pending",
    )
    p_keep.add_argument(
        "ids",
        nargs="*",
        help="One or more finding ids from scan/list",
    )
    p_keep.add_argument(
        "--all",
        action="store_true",
        help="Whitelist every remaining pending finding",
    )
    p_keep.set_defaults(func=cmd_keep)

    p_paths = sub.add_parser("paths", help="Print config/data file locations")
    p_paths.set_defaults(func=cmd_paths)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
