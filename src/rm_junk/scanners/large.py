from __future__ import annotations

import os
from pathlib import Path

from rm_junk.config import Settings, expand_path
from rm_junk.models import Category, Confidence, Finding
from rm_junk.parallel import default_workers, map_as_completed
from rm_junk.path_policy import PathPolicy
from rm_junk.progress import NullProgress, ScanProgress
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

# First-level folders under Library that are huge — expand one level so progress
# and parallelism don't stall on a single "Containers" work unit.
EXPAND_ALWAYS = {
    "Library",
    "Containers",
    "Application Support",
    "Group Containers",
    "Developer",
    "Caches",
}


def _is_known_heavy(path: Path) -> bool:
    parts = set(path.parts)
    name = path.name
    if name in KNOWN_HEAVY_NAMES:
        return True
    if "com.docker.docker" in parts:
        return True
    return False


def _make_large_finding(path: Path, size: int, *, at_max_depth: bool = False) -> Finding:
    heavy = _is_known_heavy(path)
    kind = "folder" if path.is_dir() else "file"
    reason = f"Large {kind}"
    if heavy:
        reason += " (known heavy tool data)"
    reason += " ≥ threshold"
    if at_max_depth:
        reason += " (max depth)"
    try:
        path_str = str(path.resolve())
    except OSError:
        path_str = str(path)
    return Finding(
        path=path_str,
        size_bytes=size,
        category=Category.LARGE,
        confidence=Confidence.HIGH if heavy else Confidence.MEDIUM,
        reason=reason,
    )


def _list_dir_children(path: Path, policy: PathPolicy) -> list[Path]:
    out: list[Path] = []
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
                        out.append(child)
                except OSError:
                    continue
    except OSError:
        return []
    return out


def _expand_work_items(
    children: list[Path],
    policy: PathPolicy,
    *,
    max_depth: int,
    depth: int = 1,
) -> list[tuple[Path, int]]:
    """Return (path, start_depth) work units.

    Expand bulky dirs so work is fine-grained enough for multi-core pools.
    One giant ``Containers`` folder must not monopolize a single worker.
    """
    items: list[tuple[Path, int]] = []
    for child in children:
        should_expand = child.name in EXPAND_ALWAYS or any(
            part in EXPAND_ALWAYS for part in child.parts[-3:]
        )
        # Also expand any dir with many immediate children (keeps pool busy)
        subs = _list_dir_children(child, policy) if should_expand or depth < 3 else []
        if should_expand and max_depth >= depth + 1 and subs:
            # One more level for very wide trees (Containers apps, App Support)
            if len(subs) > 8 and depth < 3:
                for sub in subs:
                    nested = _list_dir_children(sub, policy)
                    if nested and len(nested) > 4:
                        for n in nested:
                            items.append((n, depth + 2))
                    else:
                        items.append((sub, depth + 1))
            else:
                for sub in subs:
                    items.append((sub, depth + 1))
            continue
        if not should_expand and len(subs) >= 24 and max_depth >= depth + 1:
            for sub in subs:
                items.append((sub, depth + 1))
            continue
        items.append((child, depth))
    return items


def scan_large(
    settings: Settings,
    policy: PathPolicy,
    *,
    progress: ScanProgress | None = None,
) -> list[Finding]:
    """Find large dirs/files under configured roots.

    Parallelism: independent subtrees on worker threads (no nested pools).
    """
    prog: ScanProgress = progress or NullProgress()
    findings: list[Finding] = []
    threshold = settings.scan.large_file_min_bytes
    max_depth = settings.scan.max_depth
    workers = default_workers(settings.scan.workers or None)
    home = Path.home().resolve()

    prog.set_parallelism(workers)
    prog.log(f"Large-file scan using {workers} worker threads…")

    for root_str in settings.scan.large_file_roots:
        try:
            root = expand_path(root_str)
        except OSError:
            root = Path(root_str).expanduser()
        if not root.exists() or policy.should_skip(root):
            continue

        prog.log(f"  Root: {root}")

        children: list[Path] = []
        root_file_findings: list[Finding] = []
        try:
            with os.scandir(root) as it:
                for entry in it:
                    try:
                        if not policy.follow_symlinks and entry.is_symlink():
                            continue
                        child = Path(entry.path)
                        if policy.should_skip(child):
                            continue
                        if entry.is_file(follow_symlinks=False):
                            try:
                                size = entry.stat(follow_symlinks=False).st_size
                            except OSError:
                                continue
                            if size >= threshold:
                                root_file_findings.append(
                                    _make_large_finding(child, size)
                                )
                        elif entry.is_dir(follow_symlinks=policy.follow_symlinks):
                            children.append(child)
                    except OSError:
                        continue
        except OSError:
            continue

        findings.extend(root_file_findings)
        if not children:
            continue

        # If root itself is Library-like, expand first-level into second-level.
        if root.name in EXPAND_ALWAYS or root.name == "Library":
            work = _expand_work_items(children, policy, max_depth=max_depth)
        else:
            # Still expand known heavy child names (e.g. Containers under Library)
            work = _expand_work_items(children, policy, max_depth=max_depth)

        if not work:
            continue

        prog.add_work(len(work))
        prog.log(f"  walking {len(work)} folders under {root}…")

        def _label(path: Path) -> str:
            try:
                return f"{path.parent.name}/{path.name}"
            except Exception:
                return path.name

        def walk_one(item: tuple[Path, int]) -> tuple[Path, list[Finding], int]:
            path, start_depth = item
            reported: list[Path] = []
            child_findings: list[Finding] = []
            size = _walk(
                path,
                depth=start_depth,
                max_depth=max_depth,
                threshold=threshold,
                policy=policy,
                findings=child_findings,
                reported_ancestors=reported,
                home=home,
                size_workers=max(1, workers // 4),
            )
            return path, child_findings, size

        def on_start(item: tuple[Path, int]) -> None:
            prog.begin(_label(item[0]))

        def on_done(
            item: tuple[Path, int], result: tuple[Path, list[Finding], int]
        ) -> None:
            path, child_findings, size = result
            label = _label(path)
            prog.tick(1, item=f"{label} ({_fmt(size)})")
            prog.log(
                f"    done {label} (~{_fmt(size)}, {len(child_findings)} hit(s))"
            )

        results = map_as_completed(
            walk_one,
            work,
            workers=workers,
            on_start=on_start,
            on_done=on_done,
        )
        for _path, child_findings, _size in results:
            findings.extend(child_findings)

    return findings


def _fmt(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{n} B"


def _walk(
    path: Path,
    *,
    depth: int,
    max_depth: int,
    threshold: int,
    policy: PathPolicy,
    findings: list[Finding],
    reported_ancestors: list[Path],
    home: Path,
    size_workers: int = 1,
) -> int:
    """Walk one subtree (runs inside a worker thread)."""

    def under_reported(p: Path) -> bool:
        try:
            resolved = p.resolve()
        except OSError:
            resolved = p
        for ancestor in reported_ancestors:
            try:
                resolved.relative_to(ancestor)
                return True
            except ValueError:
                continue
        return False

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
            findings.append(_make_large_finding(path, size))
            try:
                reported_ancestors.append(path.resolve())
            except OSError:
                reported_ancestors.append(path)
        return size

    if not is_dir:
        return 0

    if depth >= max_depth:
        size = dir_size(path, policy, workers=size_workers)
        if size >= threshold and not under_reported(path):
            findings.append(_make_large_finding(path, size, at_max_depth=True))
            try:
                reported_ancestors.append(path.resolve())
            except OSError:
                reported_ancestors.append(path)
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
                        home=home,
                        size_workers=size_workers,
                    )
                    total += child_size
                    child_sizes.append((child, child_size))
                except OSError:
                    continue
    except OSError:
        return 0

    if total >= threshold and not under_reported(path):
        child_reported = any(under_reported(c) for c, _ in child_sizes)
        if not child_reported:
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if resolved != home:
                findings.append(_make_large_finding(path, total))
                reported_ancestors.append(resolved)

    return total
