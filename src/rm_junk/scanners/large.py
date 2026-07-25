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


def scan_large(
    settings: Settings,
    policy: PathPolicy,
    *,
    progress: ScanProgress | None = None,
) -> list[Finding]:
    """Find large dirs/files under configured roots.

    Parallelism: each top-level child of a root is walked on its own thread
    (no nested pools — avoids ThreadPoolExecutor deadlocks).
    """
    prog: ScanProgress = progress or NullProgress()
    findings: list[Finding] = []
    threshold = settings.scan.large_file_min_bytes
    max_depth = settings.scan.max_depth
    workers = default_workers(settings.scan.workers or None)
    home = Path.home().resolve()

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

        prog.add_work(len(children))
        prog.log(f"  walking {len(children)} top-level folders…")

        def walk_child(child: Path) -> tuple[Path, list[Finding], int]:
            reported: list[Path] = []
            child_findings: list[Finding] = []
            size = _walk(
                child,
                depth=1,
                max_depth=max_depth,
                threshold=threshold,
                policy=policy,
                findings=child_findings,
                reported_ancestors=reported,
                home=home,
            )
            return child, child_findings, size

        def on_done(
            child: Path, result: tuple[Path, list[Finding], int]
        ) -> None:
            _c, child_findings, size = result
            prog.tick(
                1,
                item=f"{child.name} ({_fmt(size)}, {len(child_findings)} hit)",
            )
            prog.log(
                f"    done {child.name} (~{_fmt(size)}, {len(child_findings)} hit(s))"
            )

        results = map_as_completed(
            walk_child,
            children,
            workers=workers,
            on_done=on_done,
        )
        for _child, child_findings, _size in results:
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
) -> int:
    """Sequential walk of one subtree (runs inside a worker thread)."""

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
        size = dir_size(path, policy)
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
