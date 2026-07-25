from __future__ import annotations

import os
import time
from pathlib import Path

from rm_junk.config import Settings
from rm_junk.models import Category, Confidence, Finding
from rm_junk.path_policy import PathPolicy
from rm_junk.progress import NullProgress, ScanProgress
from rm_junk.sizing import entry_size


def scan_trash(
    settings: Settings,
    policy: PathPolicy,
    *,
    progress: ScanProgress | None = None,
    trash_roots: list[Path] | None = None,
) -> list[Finding]:
    """Scan local and external volume trash directories for stale files."""
    prog: ScanProgress = progress or NullProgress()
    findings: list[Finding] = []

    if trash_roots is None:
        trash_roots = []
        home_trash = Path.home() / ".Trash"
        if home_trash.is_dir():
            trash_roots.append(home_trash)

        try:
            uid = os.getuid()
        except AttributeError:
            uid = 501

        volumes = Path("/Volumes")
        if volumes.is_dir():
            try:
                for entry in os.scandir(volumes):
                    if entry.is_dir(follow_symlinks=False):
                        ext_trash = Path(entry.path) / ".Trashes" / str(uid)
                        if ext_trash.is_dir():
                            trash_roots.append(ext_trash)
            except OSError:
                pass

    if not trash_roots:
        return []

    min_bytes = settings.scan.trash_min_bytes
    min_age = settings.scan.trash_min_age_days
    now = time.time()

    prog.log("Trash bins scan…")
    prog.add_work(len(trash_roots))

    for root in trash_roots:
        prog.status(f"Scanning trash: {root.name}")
        if policy.should_skip(root):
            prog.tick(1, item=f"{root.name} (skipped)")
            continue

        try:
            for entry in policy.safe_scandir(root):
                child = Path(entry.path)
                if policy.should_skip(child):
                    continue

                try:
                    st = entry.stat(follow_symlinks=False)
                    age_days = (now - st.st_mtime) / 86400
                    if age_days >= min_age:
                        size = entry_size(child, policy)
                        if size >= min_bytes:
                            findings.append(
                                Finding(
                                    path=str(child),
                                    size_bytes=size,
                                    category=Category.CACHE,
                                    confidence=Confidence.HIGH,
                                    reason=f"Trash item ({age_days:.0f} days old)",
                                )
                            )
                except OSError:
                    continue
        except OSError:
            pass

        prog.tick(1, item=root.name)

    return findings
