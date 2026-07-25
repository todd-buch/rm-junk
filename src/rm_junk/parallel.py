from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def default_workers(configured: int | None = None) -> int:
    """Thread count for I/O-bound filesystem work."""
    if configured is not None and configured > 0:
        return configured
    cpu = os.cpu_count() or 4
    # Filesystem scans benefit from more threads than cores; cap to avoid thrash.
    return max(4, min(32, cpu * 4))


def map_parallel(
    fn: Callable[[T], R],
    items: Iterable[T],
    *,
    workers: int,
) -> list[R]:
    """Run fn over items with a thread pool; preserve completion-agnostic list order."""
    item_list = list(items)
    if not item_list:
        return []
    if workers <= 1 or len(item_list) == 1:
        return [fn(item) for item in item_list]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, item_list))


def map_as_completed(
    fn: Callable[[T], R],
    items: Iterable[T],
    *,
    workers: int,
    on_done: Callable[[T, R], None] | None = None,
) -> list[R]:
    """Run fn over items; optionally notify as each finishes. Returns results in completion order."""
    item_list = list(items)
    if not item_list:
        return []
    if workers <= 1 or len(item_list) == 1:
        results: list[R] = []
        for item in item_list:
            result = fn(item)
            if on_done:
                on_done(item, result)
            results.append(result)
        return results

    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn, item): item for item in item_list}
        for future in as_completed(futures):
            item = futures[future]
            result = future.result()
            if on_done:
                on_done(item, result)
            results.append(result)
    return results
