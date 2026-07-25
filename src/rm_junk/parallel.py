from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def default_workers(configured: int | None = None) -> int:
    """Thread count for I/O-bound filesystem work.

    File scanning is mostly blocked on disk I/O (GIL released during stat/scandir),
    so we want *more* threads than CPU cores. Default aims for high concurrency.
    """
    if configured is not None and configured > 0:
        return configured
    cpu = os.cpu_count() or 4
    # I/O bound: many concurrent stats. Cap avoids pathologically huge pools.
    return max(16, min(64, cpu * 8))


def map_parallel(
    fn: Callable[[T], R],
    items: Iterable[T],
    *,
    workers: int,
) -> list[R]:
    """Run fn over items with a thread pool; preserve input order."""
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
    on_start: Callable[[T], None] | None = None,
    on_done: Callable[[T, R], None] | None = None,
) -> list[R]:
    """Run fn over items; notify as each starts/finishes. Completion order results."""
    item_list = list(items)
    if not item_list:
        return []
    if workers <= 1 or len(item_list) == 1:
        results: list[R] = []
        for item in item_list:
            if on_start:
                on_start(item)
            result = fn(item)
            if on_done:
                on_done(item, result)
            results.append(result)
        return results

    results: list[R] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for item in item_list:
            if on_start:
                on_start(item)
            futures[pool.submit(fn, item)] = item
        for future in as_completed(futures):
            item = futures[future]
            result = future.result()
            if on_done:
                on_done(item, result)
            results.append(result)
    return results
