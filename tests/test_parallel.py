from rm_junk.parallel import default_workers, map_as_completed, map_parallel


def test_map_parallel_preserves_order():
    out = map_parallel(lambda x: x * 2, [1, 2, 3, 4], workers=4)
    assert out == [2, 4, 6, 8]


def test_map_parallel_single_worker():
    out = map_parallel(lambda x: x + 1, [10, 20], workers=1)
    assert out == [11, 21]


def test_map_as_completed_calls_on_done():
    seen: list[int] = []

    def work(x: int) -> int:
        return x * 3

    def on_done(item: int, result: int) -> None:
        seen.append(item)
        assert result == item * 3

    results = map_as_completed(work, [1, 2, 3], workers=3, on_done=on_done)
    assert sorted(results) == [3, 6, 9]
    assert sorted(seen) == [1, 2, 3]


def test_default_workers_respects_config():
    assert default_workers(8) == 8
    assert default_workers(0) is not None  # 0 treated as unset via callers; helper sees 0 as falsy only if None
    auto = default_workers(None)
    assert 4 <= auto <= 32
