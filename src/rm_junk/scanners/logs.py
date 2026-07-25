from __future__ import annotations

import time
from pathlib import Path

from rm_junk.config import Settings
from rm_junk.models import Category, Confidence, Finding
from rm_junk.path_policy import PathPolicy
from rm_junk.progress import NullProgress, ScanProgress


def scan_logs(
    settings: Settings,
    policy: PathPolicy,
    *,
    progress: ScanProgress | None = None,
    log_roots: list[Path] | None = None,
) -> list[Finding]:
    """Scan system and user log directories for stale log files."""
    prog: ScanProgress = progress or NullProgress()
    findings: list[Finding] = []

    if log_roots is None:
        log_roots = [
            Path("/var/log"),
            Path("/Library/Logs"),
            Path.home() / "Library" / "Logs",
        ]

    min_bytes = settings.scan.log_min_bytes
    min_age = settings.scan.log_min_age_days
    now = time.time()

    prog.log("Log / diagnostic cache scan…")
    prog.add_work(len(log_roots))

    for root in log_roots:
        prog.status(f"Scanning logs: {root}")
        if not root.is_dir() or policy.should_skip(root):
            prog.tick(1, item=f"{root.name} (skipped)")
            continue

        findings.extend(_walk_log_dir(root, root, min_bytes, min_age, now, policy))
        prog.tick(1, item=root.name)

    return findings


def _walk_log_dir(
    root: Path,
    current: Path,
    min_bytes: int,
    min_age_days: int,
    now: float,
    policy: PathPolicy,
    depth: int = 1,
    max_depth: int = 5,
) -> list[Finding]:
    findings: list[Finding] = []
    if depth > max_depth or policy.should_skip(current):
        return findings

    try:
        entries = list(policy.safe_scandir(current))
    except (OSError, PermissionError):
        return findings

    for entry in entries:
        try:
            path = Path(entry.path)
            if policy.should_skip(path):
                continue

            if entry.is_symlink():
                continue

            if entry.is_file(follow_symlinks=False):
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue

                if st.st_size < min_bytes:
                    continue

                age_days = (now - st.st_mtime) / 86400
                if age_days < min_age_days:
                    continue

                confidence = (
                    Confidence.HIGH
                    if path.suffix in (".log", ".gz", ".bz2", ".tbz", ".txt")
                    else Confidence.MEDIUM
                )

                findings.append(
                    Finding(
                        path=str(path),
                        size_bytes=st.st_size,
                        category=Category.LOG,
                        confidence=confidence,
                        reason=f"Stale log file ({age_days:.0f} days old)",
                    )
                )
            elif entry.is_dir(follow_symlinks=False):
                findings.extend(
                    _walk_log_dir(
                        root,
                        path,
                        min_bytes,
                        min_age_days,
                        now,
                        policy,
                        depth + 1,
                        max_depth,
                    )
                )
        except (OSError, PermissionError):
            continue

    return findings
