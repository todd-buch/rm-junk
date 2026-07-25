from __future__ import annotations

import os
import time
from pathlib import Path

from rm_junk.config import Settings
from rm_junk.models import Category, Confidence, Finding
from rm_junk.path_policy import PathPolicy
from rm_junk.progress import NullProgress, ScanProgress


def scan_mail(
    settings: Settings,
    policy: PathPolicy,
    *,
    progress: ScanProgress | None = None,
    mail_roots: list[Path] | None = None,
) -> list[Finding]:
    """Scan macOS Mail attachments cache for stale attachments."""
    prog: ScanProgress = progress or NullProgress()
    findings: list[Finding] = []

    if mail_roots is None:
        home = Path.home()
        mail_dir = home / "Library" / "Mail"
        if not mail_dir.is_dir():
            return []

        mail_roots = []
        try:
            for entry in os.scandir(mail_dir):
                if entry.is_dir() and entry.name.startswith("V"):
                    mail_roots.append(Path(entry.path))
        except OSError:
            pass

    if not mail_roots:
        return []

    min_bytes = settings.scan.mail_attachment_min_bytes
    min_age = settings.scan.mail_attachment_min_age_days
    now = time.time()

    prog.log("Mail attachments scan…")
    prog.add_work(len(mail_roots))

    for root in mail_roots:
        prog.status(f"Scanning Mail attachments: {root.name}")
        if policy.should_skip(root):
            prog.tick(1, item=f"{root.name} (skipped)")
            continue

        findings.extend(_walk_attachments(root, min_bytes, min_age, now, policy))
        prog.tick(1, item=root.name)

    return findings


def _walk_attachments(
    root: Path,
    min_bytes: int,
    min_age_days: int,
    now: float,
    policy: PathPolicy,
) -> list[Finding]:
    findings: list[Finding] = []

    stack = [root]
    while stack:
        current = stack.pop()
        if policy.should_skip(current):
            continue

        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        child = Path(entry.path)
                        if policy.should_skip(child):
                            continue
                        if entry.is_symlink():
                            continue

                        if entry.is_dir(follow_symlinks=False):
                            if entry.name.lower() == "attachments":
                                findings.extend(
                                    _collect_attachment_files(
                                        child, min_bytes, min_age_days, now, policy
                                    )
                                )
                            else:
                                stack.append(child)
                    except OSError:
                        continue
        except OSError:
            continue

    return findings


def _collect_attachment_files(
    attachments_dir: Path,
    min_bytes: int,
    min_age_days: int,
    now: float,
    policy: PathPolicy,
) -> list[Finding]:
    findings: list[Finding] = []
    stack = [attachments_dir]
    while stack:
        current = stack.pop()
        if policy.should_skip(current):
            continue

        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        child = Path(entry.path)
                        if policy.should_skip(child):
                            continue
                        if entry.is_symlink():
                            continue

                        if entry.is_file(follow_symlinks=False):
                            try:
                                st = entry.stat(follow_symlinks=False)
                            except OSError:
                                continue
                            if st.st_size >= min_bytes:
                                age_days = (now - st.st_mtime) / 86400
                                if age_days >= min_age_days:
                                    findings.append(
                                        Finding(
                                            path=str(child),
                                            size_bytes=st.st_size,
                                            category=Category.CACHE,
                                            confidence=Confidence.MEDIUM,
                                            reason=f"Stale Mail attachment ({age_days:.0f} days old)",
                                        )
                                    )
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(child)
                    except OSError:
                        continue
        except OSError:
            continue

    return findings
