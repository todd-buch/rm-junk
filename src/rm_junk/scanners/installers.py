from __future__ import annotations

import time
from pathlib import Path

from rm_junk.config import Settings
from rm_junk.models import Category, Confidence, Finding
from rm_junk.path_policy import PathPolicy
from rm_junk.progress import NullProgress, ScanProgress

INSTALLER_SUFFIXES = {".dmg", ".pkg", ".zip"}


def scan_old_installers(
    settings: Settings,
    policy: PathPolicy,
    *,
    progress: ScanProgress | None = None,
) -> list[Finding]:
    downloads = Path.home() / "Downloads"
    findings: list[Finding] = []
    prog: ScanProgress = progress or NullProgress()
    prog.log("Old installer scan (Downloads)…")
    if not downloads.is_dir() or policy.should_skip(downloads):
        prog.add_work(1)
        prog.tick(1, item="Downloads (skipped)")
        return findings

    min_bytes = settings.scan.installer_min_bytes
    min_age = settings.scan.installer_min_age_days
    now = time.time()

    entries = list(policy.safe_scandir(downloads))
    prog.add_work(max(1, len(entries)))

    scanned = 0
    for entry in entries:
        try:
            path = Path(entry.path)
            scanned += 1
            if not entry.is_file(follow_symlinks=False):
                prog.tick(1, item=entry.name)
                continue
            if path.suffix.lower() not in INSTALLER_SUFFIXES:
                prog.tick(1, item=entry.name)
                continue
            st = entry.stat(follow_symlinks=False)
            if st.st_size < min_bytes:
                prog.tick(1, item=entry.name)
                continue
            age_days = (now - st.st_mtime) / 86400
            if age_days < min_age:
                prog.tick(1, item=entry.name)
                continue
            findings.append(
                Finding(
                    path=str(path),
                    size_bytes=st.st_size,
                    category=Category.INSTALLER,
                    confidence=Confidence.MEDIUM,
                    reason=(
                        f"Old installer/archive in Downloads "
                        f"({age_days:.0f} days old)"
                    ),
                )
            )
            prog.tick(1, item=entry.name)
        except OSError:
            prog.tick(1, item=getattr(entry, "name", "?"))
            continue

    if scanned == 0:
        prog.tick(1, item="Downloads")

    return findings
