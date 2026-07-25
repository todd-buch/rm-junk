from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rm_junk.path_policy import PathPolicy


def dir_size(
    path: Path,
    policy: PathPolicy,
    *,
    max_entries: int = 200_000,
    workers: int = 1,
) -> int:
    """Approximate total size of a directory tree.

    When ``workers`` > 1, top-level subdirectories are sized in parallel
    (helps on multi-core / SSD when a single huge tree is the bottleneck).
    """
    if policy.should_skip(path):
        return 0
    try:
        if path.is_file():
            return path.stat().st_size
    except OSError:
        return 0

    if workers <= 1:
        return _dir_size_sequential(path, policy, max_entries=max_entries)

    # Parallelize first level of children, sequential within each
    subdirs: list[Path] = []
    total = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if not policy.follow_symlinks and entry.is_symlink():
                        continue
                    child = Path(entry.path)
                    if policy.should_skip(child):
                        continue
                    if entry.is_dir(follow_symlinks=policy.follow_symlinks):
                        subdirs.append(child)
                    elif entry.is_file(follow_symlinks=policy.follow_symlinks):
                        total += entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
    except OSError:
        return total

    if not subdirs:
        return total

    # Cap nested parallelism so we don't explode thread count
    w = min(workers, max(1, len(subdirs)), 16)
    per_budget = max(1_000, max_entries // max(1, len(subdirs)))

    def size_one(p: Path) -> int:
        return _dir_size_sequential(p, policy, max_entries=per_budget)

    with ThreadPoolExecutor(max_workers=w) as pool:
        futs = [pool.submit(size_one, d) for d in subdirs]
        for fut in as_completed(futs):
            try:
                total += fut.result()
            except Exception:
                continue
    return total


def _dir_size_sequential(
    path: Path,
    policy: PathPolicy,
    *,
    max_entries: int,
) -> int:
    total = 0
    seen = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    seen += 1
                    if seen > max_entries:
                        return total
                    try:
                        if not policy.follow_symlinks and entry.is_symlink():
                            continue
                        child = Path(entry.path)
                        if policy.should_skip(child):
                            continue
                        if entry.is_dir(follow_symlinks=policy.follow_symlinks):
                            stack.append(child)
                        elif entry.is_file(follow_symlinks=policy.follow_symlinks):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def entry_size(path: Path, policy: PathPolicy, *, workers: int = 1) -> int:
    try:
        if path.is_dir() and (policy.follow_symlinks or not path.is_symlink()):
            return dir_size(path, policy, workers=workers)
        return path.stat().st_size
    except OSError:
        return 0
