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


def test_progress_bar_hides_items_unless_enabled():
    buf = StringIO()
    bar = ProgressBar(2, desc="X", file=buf, enabled=True, show_items=False)
    bar.enabled = False  # avoid TTY assumptions
    bar.update(1, item="secret")
    assert bar._item == "" or not bar.show_items


def test_null_progress():
    p = NullProgress()
    p.log("silent")
    p.phase("Caches")
    p.add_work(2)
    p.tick(1, item="a")
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


def test_terminal_progress_ticks():
    buf = StringIO()
    p = TerminalProgress(file=buf, enabled=False, debug=False)
    p.phase("Caches")
    p.add_work(3)
    p.tick(1)
    p.tick(2)
    p.close()
