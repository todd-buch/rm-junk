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
    """Shallow scan of Downloads for old large installers (one progress unit)."""
    downloads = Path.home() / "Downloads"
    findings: list[Finding] = []
    prog: ScanProgress = progress or NullProgress()
    prog.log("Old installer scan (Downloads)…")
    prog.add_work(1)
    prog.status("Downloads…")

    if not downloads.is_dir() or policy.should_skip(downloads):
        prog.tick(1, item="Downloads (skipped)")
        return findings

    min_bytes = settings.scan.installer_min_bytes
    min_age = settings.scan.installer_min_age_days
    now = time.time()

    for entry in policy.safe_scandir(downloads):
        try:
            path = Path(entry.path)
            if not entry.is_file(follow_symlinks=False):
                continue
            if path.suffix.lower() not in INSTALLER_SUFFIXES:
                continue
            st = entry.stat(follow_symlinks=False)
            if st.st_size < min_bytes:
                continue
            age_days = (now - st.st_mtime) / 86400
            if age_days < min_age:
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
        except OSError:
            continue

    prog.tick(1, item=f"Downloads ({len(findings)} hit)")
    return findings
