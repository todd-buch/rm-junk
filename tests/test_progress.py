from io import StringIO

from rm_junk.progress import NullProgress, ProgressBar, TerminalProgress


def test_progress_bar_completes():
    buf = StringIO()
    # Force-enable even though StringIO is not a TTY by subclassing behavior
    bar = ProgressBar(5, desc="Test", file=buf, enabled=True)
    # enabled=True but isatty is false on StringIO — bar.enabled becomes False
    # So test the math path with a direct non-tty summary on close
    bar.enabled = False
    for i in range(5):
        bar.update(1, item=f"item-{i}")
    bar.close()
    assert bar.n == 5
    assert "Test:" in buf.getvalue()


def test_progress_bar_context_manager():
    buf = StringIO()
    with ProgressBar(3, desc="Ctx", file=buf, enabled=False) as bar:
        bar.update(1)
        bar.update(2)
    assert bar.n == 3


def test_null_progress():
    p = NullProgress()
    p.log("silent")
    with p.bar(2, desc="x") as bar:
        bar.update(1)
        bar.update(1)
    assert bar.n == 2


def test_terminal_progress_log():
    buf = StringIO()
    p = TerminalProgress(file=buf, enabled=False)
    p.log("hello")
    assert "hello" in buf.getvalue()
