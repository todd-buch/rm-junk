from __future__ import annotations

import os
from pathlib import Path

from rm_junk.path_policy import PathPolicy


def dir_size(
    path: Path,
    policy: PathPolicy,
    *,
    max_entries: int = 200_000,
) -> int:
    """Approximate total size of a directory tree. Skips unreadable / denied paths."""
    total = 0
    seen = 0
    if policy.should_skip(path):
        return 0
    try:
        if path.is_file():
            return path.stat().st_size
    except OSError:
        return 0

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


def entry_size(path: Path, policy: PathPolicy) -> int:
    try:
        if path.is_dir() and (policy.follow_symlinks or not path.is_symlink()):
            return dir_size(path, policy)
        return path.stat().st_size
    except OSError:
        return 0
