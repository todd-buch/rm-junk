from __future__ import annotations

import time
from pathlib import Path

from rm_junk.config import Settings
from rm_junk.models import Category, Confidence, Finding
from rm_junk.path_policy import PathPolicy
from rm_junk.progress import NullProgress, ScanProgress
from rm_junk.sizing import entry_size


def scan_developer(
    settings: Settings,
    policy: PathPolicy,
    *,
    progress: ScanProgress | None = None,
    child_targets: list[tuple[Path, str]] | None = None,
    parent_targets: list[tuple[Path, str]] | None = None,
    archives_root: Path | None = None,
) -> list[Finding]:
    """Scan developer caches and tools directories for stale files/folders."""
    prog: ScanProgress = progress or NullProgress()
    findings: list[Finding] = []

    home = Path.home()
    if child_targets is None:
        child_targets = [
            (
                home / "Library" / "Developer" / "Xcode" / "iOS DeviceSupport",
                "Xcode iOS DeviceSupport",
            ),
            (
                home / "Library" / "Application Support" / "MobileSync" / "Backup",
                "iOS Backup",
            ),
            (home / ".android" / "avd", "Android AVD"),
        ]

    if parent_targets is None:
        parent_targets = [
            (home / "Library" / "Caches" / "CocoaPods", "CocoaPods Cache"),
            (home / ".npm", "npm Cache"),
            (home / "Library" / "Caches" / "Yarn", "Yarn Cache"),
            (home / ".cargo" / "registry", "Cargo Registry Cache"),
            (home / ".cargo" / "git", "Cargo Git Cache"),
            (home / "Library" / "Caches" / "pip", "pip Cache"),
            (home / "Library" / "Caches" / "go-build", "Go Build Cache"),
        ]

    if archives_root is None:
        archives_root = home / "Library" / "Developer" / "Xcode" / "Archives"

    min_bytes = settings.scan.dev_junk_min_bytes
    min_age = settings.scan.dev_junk_min_age_days
    now = time.time()

    # Calculate total work: parent targets + child targets + archives root
    prog.log("Developer junk scan…")
    prog.add_work(len(parent_targets) + len(child_targets) + 1)

    # 1. Scan Parent targets
    for path, label in parent_targets:
        prog.status(f"Scanning developer cache: {label}")
        if not path.is_dir() or policy.should_skip(path):
            prog.tick(1, item=f"{label} (skipped)")
            continue

        try:
            mtime = path.stat().st_mtime
            age_days = (now - mtime) / 86400
            if age_days >= min_age:
                size = entry_size(path, policy)
                if size >= min_bytes:
                    findings.append(
                        Finding(
                            path=str(path),
                            size_bytes=size,
                            category=Category.DEV_CACHE,
                            confidence=Confidence.HIGH,
                            reason=f"Stale {label} ({age_days:.0f} days old)",
                        )
                    )
        except OSError:
            pass
        prog.tick(1, item=label)

    # 2. Scan Child targets
    for parent_dir, label in child_targets:
        prog.status(f"Scanning developer directory: {label}")
        if not parent_dir.is_dir() or policy.should_skip(parent_dir):
            prog.tick(1, item=f"{label} (skipped)")
            continue

        try:
            for entry in policy.safe_scandir(parent_dir):
                if entry.is_dir(follow_symlinks=False):
                    child = Path(entry.path)
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
                                        category=Category.DEV_CACHE,
                                        confidence=Confidence.MEDIUM,
                                        reason=(
                                            f"Stale {label} folder: {child.name} "
                                            f"({age_days:.0f} days old)"
                                        ),
                                    )
                                )
                    except OSError:
                        continue
        except OSError:
            pass
        prog.tick(1, item=label)

    # 3. Scan Archives Root
    prog.status("Scanning developer archives: Xcode Archives")
    if archives_root.is_dir() and not policy.should_skip(archives_root):
        try:
            for date_dir in policy.safe_scandir(archives_root):
                if date_dir.is_dir(follow_symlinks=False):
                    for arch_entry in policy.safe_scandir(Path(date_dir.path)):
                        if arch_entry.is_dir(
                            follow_symlinks=False
                        ) and arch_entry.name.endswith(".xcarchive"):
                            child = Path(arch_entry.path)
                            try:
                                st = arch_entry.stat(follow_symlinks=False)
                                age_days = (now - st.st_mtime) / 86400
                                if age_days >= min_age:
                                    size = entry_size(child, policy)
                                    if size >= min_bytes:
                                        findings.append(
                                            Finding(
                                                path=str(child),
                                                size_bytes=size,
                                                category=Category.DEV_CACHE,
                                                confidence=Confidence.MEDIUM,
                                                reason=(
                                                    f"Stale Xcode Archive: "
                                                    f"{child.name} "
                                                    f"({age_days:.0f} days old)"
                                                ),
                                            )
                                        )
                            except OSError:
                                continue
        except OSError:
            pass
    prog.tick(1, item="Xcode Archives")

    return findings
