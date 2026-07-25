from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from pathlib import Path

from rm_junk.config import Settings
from rm_junk.models import Category, Confidence, Finding
from rm_junk.path_policy import PathPolicy
from rm_junk.progress import NullProgress, ScanProgress


def scan_duplicates(
    settings: Settings,
    policy: PathPolicy,
    *,
    progress: ScanProgress | None = None,
    duplicate_roots: list[Path] | None = None,
) -> list[Finding]:
    """Scan configured roots for duplicate files."""
    prog: ScanProgress = progress or NullProgress()
    findings: list[Finding] = []

    if duplicate_roots is None:
        from rm_junk.config import expand_path

        duplicate_roots = []
        for root_str in settings.scan.large_file_roots:
            try:
                root = expand_path(root_str)
                if root.is_dir():
                    duplicate_roots.append(root)
            except OSError:
                pass

    if not duplicate_roots:
        return []

    min_bytes = settings.scan.duplicate_min_bytes

    prog.log("Duplicate files scan…")
    prog.add_work(len(duplicate_roots))

    # Map file sizes to list of paths
    by_size: dict[int, list[Path]] = defaultdict(list)

    # 1. Walk and collect files by size
    for root in duplicate_roots:
        prog.status(f"Scanning directory for duplicates: {root.name}")
        if policy.should_skip(root):
            prog.tick(1, item=f"{root.name} (skipped)")
            continue

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

                            if entry.is_file(follow_symlinks=False):
                                try:
                                    st = entry.stat(follow_symlinks=False)
                                except OSError:
                                    continue
                                if st.st_size >= min_bytes:
                                    by_size[st.st_size].append(child)
                            elif entry.is_dir(follow_symlinks=False):
                                stack.append(child)
                        except OSError:
                            continue
            except OSError:
                continue
        prog.tick(1, item=root.name)

    # Filter sizes that have more than 1 file
    candidate_sizes = {
        size: paths for size, paths in by_size.items() if len(paths) > 1
    }
    if not candidate_sizes:
        return []

    # 2. Hash first chunk (fast filter)
    by_partial_hash: dict[tuple[int, str], list[Path]] = defaultdict(list)
    for size, paths in candidate_sizes.items():
        for path in paths:
            phash = _hash_file(path, full=False)
            if phash:
                by_partial_hash[(size, phash)].append(path)

    # Filter partial hashes that have more than 1 file
    candidate_partials = {
        key: paths for key, paths in by_partial_hash.items() if len(paths) > 1
    }
    if not candidate_partials:
        return []

    # 3. Hash full files
    by_full_hash: dict[tuple[int, str], list[Path]] = defaultdict(list)
    for (size, phash), paths in candidate_partials.items():
        for path in paths:
            fhash = _hash_file(path, full=True)
            if fhash:
                by_full_hash[(size, fhash)].append(path)

    # 4. Generate findings for duplicate files
    for (size, fhash), paths in by_full_hash.items():
        if len(paths) <= 1:
            continue

        # Determine "original" by sorting (shorter path name first)
        sorted_paths = sorted(paths, key=lambda p: (len(str(p)), str(p)))
        original = sorted_paths[0]
        duplicates = sorted_paths[1:]

        for dup in duplicates:
            findings.append(
                Finding(
                    path=str(dup),
                    size_bytes=size,
                    category=Category.LEFTOVER,
                    confidence=Confidence.HIGH,
                    reason=f"Duplicate of {original.name} (original at {original})",
                )
            )

    return findings


def _hash_file(path: Path, full: bool = False) -> str:
    h = hashlib.md5()
    try:
        with path.open("rb") as f:
            if not full:
                h.update(f.read(65536))
            else:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()
