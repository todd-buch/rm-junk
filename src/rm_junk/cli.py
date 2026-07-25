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
    prefix = f"  [{idx}]"
    if show_id:
        prefix += f" id={finding.id}"
    print(
        f"{prefix} {format_bytes(finding.size_bytes):>10}  "
        f"{finding.category.value:12}  {finding.confidence.value:6}  "
        f"{finding.path}"
    )
    print(f"       {finding.reason}")


def cmd_init(_args: argparse.Namespace) -> int:
    path = ensure_user_settings()
    print(f"Settings ready: {path}")
    print("Edit that file to configure exclude paths, thresholds, and background mode.")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    try:
        settings = load_settings(Path(args.config) if args.config else None)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1

    policy = PathPolicy(settings)
    workers = settings.scan.workers
    from rm_junk.parallel import default_workers

    w = default_workers(workers or None)
    print(
        f"Scanning… ({w} workers; permission-denied paths are skipped)",
        flush=True,
    )

    def progress(msg: str) -> None:
        print(msg, flush=True)

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
    print(f"Found {len(findings)} item(s), ~{format_bytes(total)} total:\n")
    for i, finding in enumerate(findings, start=1):
        _print_finding(i, finding)

    if args.dry_run:
        print("\nDry run — results not saved.")
        return 0

    store = FindingStore()
    store.replace_pending_with(findings)
    print(f"\nSaved {len(findings)} pending finding(s) to {store.path}")
    print("Review with:  python -m rm_junk list")
    print("Delete:       python -m rm_junk delete <id>")
    print("Keep:         python -m rm_junk keep <id>")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    store = FindingStore()
    pending = store.pending
    if not pending:
        print("No pending findings. Run: python -m rm_junk scan")
        return 0
    total = sum(f.size_bytes for f in pending)
    print(f"{len(pending)} pending (~{format_bytes(total)}):\n")
    for i, finding in enumerate(pending, start=1):
        _print_finding(i, finding)
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    try:
        settings = load_settings(Path(args.config) if args.config else None)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1

    store = FindingStore()
    finding = store.get(args.id)
    if finding is None or finding.status != FindingStatus.PENDING:
        print(f"No pending finding with id {args.id}", file=sys.stderr)
        return 1

    policy = PathPolicy(settings)
    if settings.deletion.confirm_each_item and not args.yes:
        reply = input(f"Move to trash?\n  {finding.path}\n[y/N] ").strip().lower()
        if reply not in {"y", "yes"}:
            print("Cancelled.")
            return 0

    try:
        delete_path(
            finding.path,
            policy,
            to_trash=settings.deletion.move_to_trash,
        )
    except DeletionError as exc:
        print(f"Delete failed: {exc}", file=sys.stderr)
        return 1

    store.mark(finding.id, FindingStatus.DELETED)
    action = "Trashed" if settings.deletion.move_to_trash else "Deleted"
    print(f"{action}: {finding.path}")
    return 0


def cmd_keep(args: argparse.Namespace) -> int:
    try:
        settings = load_settings(Path(args.config) if args.config else None)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1

    store = FindingStore()
    finding = store.get(args.id)
    if finding is None or finding.status != FindingStatus.PENDING:
        print(f"No pending finding with id {args.id}", file=sys.stderr)
        return 1

    whitelist = list(settings.whitelist) + [finding.path]
    settings.save_whitelist(whitelist)
    store.mark(finding.id, FindingStatus.KEPT)
    print(f"Whitelisted: {finding.path}")
    print(f"Updated: {settings.path}")
    return 0


def cmd_menubar(args: argparse.Namespace) -> int:
    try:
        settings = load_settings(Path(args.config) if args.config else None)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1

    settings.ensure_background_safe()
    if not settings.background.enabled and not args.force:
        print(
            "Menu bar is for background review. Set background.enabled=true "
            "in settings (with requireManualApproval=true), or pass --force.",
            file=sys.stderr,
        )
        return 1

    store = FindingStore()
    pending = [
        f
        for f in store.pending
        if meets_min_confidence(f, settings.scan.min_confidence_for_queue)
    ]
    if not pending:
        print("No pending findings — not showing menu bar icon.")
        return 0

    policy = PathPolicy(settings)

    def on_delete(finding) -> None:
        delete_path(
            finding.path,
            policy,
            to_trash=settings.deletion.move_to_trash,
        )
        store.mark(finding.id, FindingStatus.DELETED)

    def on_keep(finding) -> None:
        # Reload settings for fresh whitelist in case of multiple actions
        current = load_settings(settings.path)
        current.save_whitelist(list(current.whitelist) + [finding.path])
        store.mark(finding.id, FindingStatus.KEPT)

    from rm_junk.menubar import run_menu_bar

    run_menu_bar(pending, on_delete=on_delete, on_keep=on_keep)
    return 0


def cmd_paths(_args: argparse.Namespace) -> int:
    print(f"settings: {default_settings_path()}")
    from rm_junk.config import default_findings_path

    print(f"findings: {default_findings_path()}")
    print(f"example:  bundled settings.example.json (repo root)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rm-junk",
        description="Find leftover caches, orphans, and large files on macOS.",
    )
    parser.add_argument("--version", action="version", version=f"rm-junk {__version__}")
    parser.add_argument(
        "--config",
        help="Path to settings.json (default: ~/Library/Application Support/rm-junk/)",
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
    p_scan.set_defaults(func=cmd_scan)

    p_list = sub.add_parser("list", help="List pending findings")
    p_list.set_defaults(func=cmd_list)

    p_del = sub.add_parser("delete", help="Delete (trash) a finding by id")
    p_del.add_argument("id", help="Finding id from scan/list")
    p_del.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    p_del.set_defaults(func=cmd_delete)

    p_keep = sub.add_parser("keep", help="Whitelist a finding path by id")
    p_keep.add_argument("id", help="Finding id from scan/list")
    p_keep.set_defaults(func=cmd_keep)

    p_bar = sub.add_parser("menubar", help="Show menu bar review UI (macOS)")
    p_bar.add_argument(
        "--force",
        action="store_true",
        help="Run even if background.enabled is false",
    )
    p_bar.set_defaults(func=cmd_menubar)

    p_paths = sub.add_parser("paths", help="Print config/data file locations")
    p_paths.set_defaults(func=cmd_paths)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
