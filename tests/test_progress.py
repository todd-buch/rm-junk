import time
from io import StringIO

from rm_junk.progress import NullProgress, ProgressBar, TerminalProgress, _fmt_seconds


def test_fmt_seconds_never_shows_bare_zero_for_positive():
    assert _fmt_seconds(0) == "0s"
    assert _fmt_seconds(0.4) == "<1s"
    assert _fmt_seconds(1.2) == "1s"
    assert _fmt_seconds(65) == "1m05s"


def test_eta_rises_with_long_running_inflight():
    """A single slow unit should not leave ETA stuck at a tiny average."""
    bar = ProgressBar(10, desc="T", file=StringIO(), enabled=False, parallelism=4)
    # 8 fast completions
    for i in range(8):
        bar.begin_item(f"fast-{i}")
        bar._inflight[f"fast-{i}"] = time.monotonic() - 0.01
        bar.update(1, item=f"fast-{i}")
    # One slow in-flight already running 40s, one remaining not started
    bar.begin_item("slow")
    bar._inflight["slow"] = time.monotonic() - 40.0
    eta = bar._eta_seconds(time.monotonic())
    assert eta is not None
    # Must reflect the long-tail job (not ~1s from tiny averages)
    assert eta >= 20.0


def test_eta_accounts_for_parallelism():
    bar = ProgressBar(100, desc="T", file=StringIO(), enabled=False, parallelism=10)
    for i in range(10):
        bar.begin_item(f"x{i}")
        bar._inflight[f"x{i}"] = time.monotonic() - 1.0
        bar.update(1, item=f"x{i}")
    # Force unit estimate ~1s
    bar._recent_durations.clear()
    for _ in range(20):
        bar._recent_durations.append(1.0)
    bar._ema_sec_per_unit = 1.0
    eta = bar._eta_seconds(time.monotonic())
    assert eta is not None
    # 90 remaining / 10 workers * 1s ≈ 9s (order of magnitude, not 90s)
    assert eta < 40.0


def test_progress_bar_add_total():
    buf = StringIO()
    bar = ProgressBar(0, desc="Grow", file=buf, enabled=False)
    bar.add_total(3)
    assert bar.total == 3
    bar.update(2)
    bar.add_total(2)
    assert bar.total == 5
    bar.update(3)
    bar.close()
    assert bar.n == 5


def test_null_progress():
    p = NullProgress()
    p.log("silent")
    p.phase("Caches")
    p.add_work(2)
    p.begin("a")
    p.tick(1, item="a")
    p.set_parallelism(8)
    p.close()


def test_terminal_phase_resets_bar():
    buf = StringIO()
    p = TerminalProgress(file=buf, enabled=True, debug=False, workers=8)
    p.enabled = True
    p.phase("Caches")
    assert p._bar is not None
    p.add_work(10)
    for i in range(10):
        p.begin(f"c{i}")
        p.tick(1, item=f"c{i}")
    assert p._bar.n == 10
    p.phase("Large files")
    assert p._bar is not None
    assert p._bar.n == 0
    p.close()
