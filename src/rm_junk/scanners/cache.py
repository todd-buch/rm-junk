from __future__ import annotations

import time
from pathlib import Path

from rm_junk.config import Settings
from rm_junk.models import Category, Confidence, Finding
from rm_junk.path_policy import PathPolicy
from rm_junk.sizing import entry_size


def _stale_enough(path: Path, min_age_days: int) -> bool:
    if min_age_days <= 0:
        return True
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return False
    age_days = (time.time() - mtime) / 86400
    return age_days >= min_age_days


def _scan_cache_root(
    root: Path,
    settings: Settings,
    policy: PathPolicy,
    *,
    category: Category,
    reason_prefix: str,
    confidence: Confidence = Confidence.MEDIUM,
) -> list[Finding]:
    findings: list[Finding] = []
    if not root.is_dir() or policy.should_skip(root):
        return findings
    min_bytes = settings.scan.cache_min_bytes
    min_age = settings.scan.cache_min_age_days
    for entry in policy.safe_scandir(root):
        try:
            child = Path(entry.path)
            if not entry.is_dir(follow_symlinks=False):
                continue
            if not _stale_enough(child, min_age):
                continue
            size = entry_size(child, policy)
            if size < min_bytes:
                continue
            findings.append(
                Finding(
                    path=str(child),
                    size_bytes=size,
                    category=category,
                    confidence=confidence,
                    reason=f"{reason_prefix}: {child.name} ({size} bytes, stale ≥ {min_age}d)",
                )
            )
        except OSError:
            continue
    return findings


def scan_caches(settings: Settings, policy: PathPolicy) -> list[Finding]:
    home = Path.home()
    findings: list[Finding] = []

    findings.extend(
        _scan_cache_root(
            home / "Library" / "Caches",
            settings,
            policy,
            category=Category.CACHE,
            reason_prefix="User Library cache",
            confidence=Confidence.MEDIUM,
        )
    )

    # Homebrew cache is a single well-known dir
    brew = home / "Library" / "Caches" / "Homebrew"
    if brew.is_dir() and not policy.should_skip(brew):
        size = entry_size(brew, policy)
        if size >= settings.scan.cache_min_bytes and _stale_enough(
            brew, settings.scan.cache_min_age_days
        ):
            findings.append(
                Finding(
                    path=str(brew),
                    size_bytes=size,
                    category=Category.CACHE,
                    confidence=Confidence.HIGH,
                    reason="Homebrew download cache",
                )
            )

    derived = home / "Library" / "Developer" / "Xcode" / "DerivedData"
    if derived.is_dir() and not policy.should_skip(derived):
        size = entry_size(derived, policy)
        if size >= settings.scan.cache_min_bytes:
            findings.append(
                Finding(
                    path=str(derived),
                    size_bytes=size,
                    category=Category.DEV_CACHE,
                    confidence=Confidence.HIGH,
                    reason="Xcode DerivedData (rebuildable build products)",
                )
            )

    # Container app caches (one level of containers)
    containers = home / "Library" / "Containers"
    if containers.is_dir() and not policy.should_skip(containers):
        for entry in policy.safe_scandir(containers):
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                cache_dir = (
                    Path(entry.path) / "Data" / "Library" / "Caches"
                )
                findings.extend(
                    _scan_cache_root(
                        cache_dir,
                        settings,
                        policy,
                        category=Category.CACHE,
                        reason_prefix=f"Container cache ({entry.name})",
                        confidence=Confidence.LOW,
                    )
                )
            except OSError:
                continue

    return findings
