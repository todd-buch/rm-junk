from io import StringIO

from rm_junk.progress import NullProgress, ProgressBar, TerminalProgress


def test_progress_bar_completes():
    buf = StringIO()
    bar = ProgressBar(5, desc="Test", file=buf, enabled=False)
    for i in range(5):
        bar.update(1, item=f"item-{i}")
    bar.close()
    assert bar.n == 5
    assert "Test:" in buf.getvalue()


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
    p.tick(1, item="a")
    p.status("working")
    p.tick(1)
    p.close()


def test_terminal_progress_debug_logs_only_when_debug():
    quiet = StringIO()
    p = TerminalProgress(file=quiet, enabled=False, debug=False)
    p.log("hidden")
    assert quiet.getvalue() == ""

    noisy = StringIO()
    p2 = TerminalProgress(file=noisy, enabled=False, debug=True)
    p2.log("visible")
    assert "visible" in noisy.getvalue()
    p2.close()


def test_terminal_phase_resets_bar():
    """Each phase gets a fresh bar so early work cannot pin percent near 100%."""
    buf = StringIO()
    p = TerminalProgress(file=buf, enabled=True, debug=False)
    # Force non-TTY path still creates bars with enabled from isatty;
    # drive via internal API after creating with enabled True on StringIO
    # which disables rendering — still tracks n/total.
    p.enabled = True
    p.phase("Caches")
    assert p._bar is not None
    p.add_work(10)
    for _ in range(10):
        p.tick(1)
    assert p._bar.n == 10
    assert p._bar.total == 10

    p.phase("Large files")
    assert p._bar is not None
    assert p._bar.n == 0
    assert p._bar.total == 0
    p.add_work(5)
    assert p._bar.total == 5
    p.tick(1, item="Containers/foo")
    assert p._bar.n == 1
    p.close()
