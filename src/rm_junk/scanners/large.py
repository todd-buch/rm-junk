from __future__ import annotations

import os
from pathlib import Path

from rm_junk.config import Settings, expand_path
from rm_junk.models import Category, Confidence, Finding
from rm_junk.path_policy import PathPolicy
from rm_junk.sizing import dir_size

KNOWN_HEAVY_NAMES = {
    ".docker",
    "Docker.raw",
    "com.docker.docker",
    ".vagrant.d",
    "Android",
    "MobileSync",
    "Parallels",
    "VirtualBox VMs",
    "UTM",
}


def _is_known_heavy(path: Path) -> bool:
    parts = set(path.parts)
    name = path.name
    if name in KNOWN_HEAVY_NAMES:
        return True
    if "com.docker.docker" in parts:
        return True
    return False


def scan_large(settings: Settings, policy: PathPolicy) -> list[Finding]:
    """Find large dirs/files under configured roots (parent-only reporting)."""
    findings: list[Finding] = []
    threshold = settings.scan.large_file_min_bytes
    max_depth = settings.scan.max_depth
    reported_ancestors: list[Path] = []

    def under_reported(path: Path) -> bool:
        for ancestor in reported_ancestors:
            try:
                path.relative_to(ancestor)
                return True
            except ValueError:
                continue
        return False

    for root_str in settings.scan.large_file_roots:
        try:
            root = expand_path(root_str)
        except OSError:
            root = Path(root_str).expanduser()
        if not root.exists() or policy.should_skip(root):
            continue
        _walk(
            root,
            depth=0,
            max_depth=max_depth,
            threshold=threshold,
            policy=policy,
            findings=findings,
            reported_ancestors=reported_ancestors,
            under_reported=under_reported,
        )
    return findings


def _walk(
    path: Path,
    *,
    depth: int,
    max_depth: int,
    threshold: int,
    policy: PathPolicy,
    findings: list[Finding],
    reported_ancestors: list[Path],
    under_reported,
) -> int:
    """Return total size of path; emit finding if large and not under another report."""
    if policy.should_skip(path) or under_reported(path):
        return 0

    try:
        is_link = path.is_symlink()
        is_dir = path.is_dir()
        is_file = path.is_file()
    except OSError:
        return 0

    if is_link and not policy.follow_symlinks:
        return 0

    if is_file:
        try:
            size = path.stat().st_size
        except OSError:
            return 0
        if size >= threshold and not under_reported(path):
            heavy = _is_known_heavy(path)
            findings.append(
                Finding(
                    path=str(path.resolve()) if path.exists() else str(path),
                    size_bytes=size,
                    category=Category.LARGE,
                    confidence=Confidence.HIGH if heavy else Confidence.MEDIUM,
                    reason=(
                        "Large file"
                        + (" (known heavy tool data)" if heavy else "")
                        + f" ≥ threshold"
                    ),
                )
            )
            reported_ancestors.append(path.resolve())
        return size

    if not is_dir:
        return 0

    # At max depth, measure whole subtree once without deeper findings on children
    if depth >= max_depth:
        size = dir_size(path, policy)
        if size >= threshold and not under_reported(path):
            heavy = _is_known_heavy(path)
            findings.append(
                Finding(
                    path=str(path.resolve()),
                    size_bytes=size,
                    category=Category.LARGE,
                    confidence=Confidence.HIGH if heavy else Confidence.MEDIUM,
                    reason=(
                        "Large folder"
                        + (" (known heavy tool data)" if heavy else "")
                        + f" ≥ threshold (max depth)"
                    ),
                )
            )
            reported_ancestors.append(path.resolve())
        return size

    total = 0
    child_sizes: list[tuple[Path, int]] = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if not policy.follow_symlinks and entry.is_symlink():
                        continue
                    child = Path(entry.path)
                    if policy.should_skip(child):
                        continue
                    child_size = _walk(
                        child,
                        depth=depth + 1,
                        max_depth=max_depth,
                        threshold=threshold,
                        policy=policy,
                        findings=findings,
                        reported_ancestors=reported_ancestors,
                        under_reported=under_reported,
                    )
                    total += child_size
                    child_sizes.append((child, child_size))
                except OSError:
                    continue
    except OSError:
        return 0

    # Parent-only: if this dir is large and no child was already reported under it,
    # report the parent once (and suppress is handled via reported_ancestors for
    # children that already fired). If children already reported, skip parent.
    if total >= threshold and not under_reported(path):
        # If any direct child was reported, don't also report parent
        child_reported = any(under_reported(c) for c, _ in child_sizes)
        if not child_reported:
            heavy = _is_known_heavy(path)
            # Avoid flagging $HOME itself as a finding
            if path.resolve() != Path.home().resolve():
                findings.append(
                    Finding(
                        path=str(path.resolve()),
                        size_bytes=total,
                        category=Category.LARGE,
                        confidence=Confidence.HIGH if heavy else Confidence.MEDIUM,
                        reason=(
                            "Large folder"
                            + (" (known heavy tool data)" if heavy else "")
                            + " ≥ threshold"
                        ),
                    )
                )
                reported_ancestors.append(path.resolve())

    return total
