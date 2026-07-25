from __future__ import annotations

import time
from pathlib import Path

from rm_junk.config import Settings
from rm_junk.models import Category, Confidence, Finding
from rm_junk.parallel import default_workers, map_as_completed
from rm_junk.path_policy import PathPolicy
from rm_junk.progress import NullProgress, ScanProgress
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
    workers: int = 1,
    progress: ScanProgress | None = None,
) -> list[Finding]:
    prog: ScanProgress = progress or NullProgress()
    if not root.is_dir() or policy.should_skip(root):
        return []
    min_bytes = settings.scan.cache_min_bytes
    min_age = settings.scan.cache_min_age_days

    candidates: list[Path] = []
    for entry in policy.safe_scandir(root):
        try:
            child = Path(entry.path)
            if not entry.is_dir(follow_symlinks=False):
                continue
            if not _stale_enough(child, min_age):
                continue
            candidates.append(child)
        except OSError:
            continue

    if not candidates:
        return []

    prog.add_work(len(candidates))
    prog.log(f"  sizing {len(candidates)} dirs under {root}")

    def measure(child: Path) -> Finding | None:
        prog.status(f"sizing {child.name}…")
        try:
            size = entry_size(child, policy)
            if size < min_bytes:
                return None
            return Finding(
                path=str(child),
                size_bytes=size,
                category=category,
                confidence=confidence,
                reason=(
                    f"{reason_prefix}: {child.name} "
                    f"({size} bytes, stale ≥ {min_age}d)"
                ),
            )
        except OSError:
            return None

    def on_done(child: Path, result: Finding | None) -> None:
        prog.tick(1, item=child.name)

    results = map_as_completed(
        measure,
        candidates,
        workers=workers,
        on_done=on_done,
    )
    return [f for f in results if f is not None]


def scan_caches(
    settings: Settings,
    policy: PathPolicy,
    *,
    progress: ScanProgress | None = None,
) -> list[Finding]:
    prog: ScanProgress = progress or NullProgress()
    home = Path.home()
    findings: list[Finding] = []
    workers = default_workers(settings.scan.workers or None)

    prog.log(f"Cache scan using {workers} worker threads…")

    findings.extend(
        _scan_cache_root(
            home / "Library" / "Caches",
            settings,
            policy,
            category=Category.CACHE,
            reason_prefix="User Library cache",
            confidence=Confidence.MEDIUM,
            workers=workers,
            progress=prog,
        )
    )

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

    containers = home / "Library" / "Containers"
    container_roots: list[tuple[Path, str]] = []
    if containers.is_dir() and not policy.should_skip(containers):
        for entry in policy.safe_scandir(containers):
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                cache_dir = Path(entry.path) / "Data" / "Library" / "Caches"
                if cache_dir.is_dir() and not policy.should_skip(cache_dir):
                    container_roots.append((cache_dir, entry.name))
            except OSError:
                continue

    def scan_one_container(item: tuple[Path, str]) -> list[Finding]:
        cache_dir, name = item
        # Don't double-count progress: outer loop ticks containers only
        return _scan_cache_root(
            cache_dir,
            settings,
            policy,
            category=Category.CACHE,
            reason_prefix=f"Container cache ({name})",
            confidence=Confidence.LOW,
            workers=1,
            progress=None,
        )

    if container_roots:
        prog.add_work(len(container_roots))
        prog.log(f"  sizing {len(container_roots)} container cache trees…")

        def on_done(item: tuple[Path, str], result: list[Finding]) -> None:
            prog.tick(1, item=item[1][:48])

        nested = map_as_completed(
            scan_one_container,
            container_roots,
            workers=workers,
            on_done=on_done,
        )
        for batch in nested:
            findings.extend(batch)

    prog.log(f"  Cache findings: {len(findings)}")
    return findings
