from __future__ import annotations

import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from types import TracebackType
from typing import TextIO, Protocol


def _term_width() -> int:
    try:
        return max(40, shutil.get_terminal_size(fallback=(80, 24)).columns)
    except OSError:
        return 80


def _fmt_seconds(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


class ProgressBar:
    """Thread-safe single-line progress bar for TTY stderr."""

    def __init__(
        self,
        total: int = 0,
        *,
        desc: str = "",
        file: TextIO | None = None,
        enabled: bool = True,
        show_items: bool = False,
    ) -> None:
        self.total = max(0, total)
        self.desc = desc
        self.file = file or sys.stderr
        self.enabled = enabled and self._is_tty()
        self.show_items = show_items
        self.n = 0
        self._item = ""
        self._lock = threading.Lock()
        self._start = time.monotonic()
        self._closed = False
        if self.enabled:
            self._render()

    def _is_tty(self) -> bool:
        try:
            return bool(self.file.isatty())
        except Exception:
            return False

    def add_total(self, n: int) -> None:
        """Grow expected work (e.g. after discovering more paths to scan)."""
        if n <= 0:
            return
        with self._lock:
            if self._closed:
                return
            self.total += n
            if self.enabled:
                self._render()

    def update(self, n: int = 1, *, item: str | None = None) -> None:
        with self._lock:
            if self._closed:
                return
            self.n += n
            if self.total:
                self.n = min(self.n, self.total)
            if item is not None and self.show_items:
                self._item = item
            if self.enabled:
                self._render()

    def set_description(self, desc: str) -> None:
        with self._lock:
            self.desc = desc
            if self.enabled and not self._closed:
                self._render()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self.total and self.n < self.total:
                self.n = self.total
            if self.enabled:
                self._render()
                self.file.write("\n")
                self.file.flush()
            elif self.desc and self.total:
                elapsed = _fmt_seconds(time.monotonic() - self._start)
                self.file.write(
                    f"{self.desc}: {self.n}/{self.total} done ({elapsed})\n"
                )
                self.file.flush()

    def __enter__(self) -> ProgressBar:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def _render(self) -> None:
        width = _term_width()
        elapsed = time.monotonic() - self._start
        rate = self.n / elapsed if elapsed > 0 else 0.0

        if self.total > 0:
            frac = min(1.0, self.n / self.total)
            pct = int(frac * 100)
            eta = (elapsed / self.n) * (self.total - self.n) if self.n else 0.0
            counts = f"{self.n}/{self.total}"
            tail = f"{pct:3d}% {counts} {_fmt_seconds(elapsed)} ETA {_fmt_seconds(eta)}"
        else:
            frac = 0.0
            tail = f"{self.n} {_fmt_seconds(elapsed)} {rate:.1f}/s"

        prefix = f"{self.desc} " if self.desc else ""
        item = ""
        if self.show_items and self._item:
            item = f"  {self._item}"

        fixed = len(prefix) + len(tail) + 5
        bar_width = max(10, min(30, width - fixed - (24 if item else 4)))
        if self.total:
            filled = int(bar_width * frac)
            bar = "█" * filled + "░" * (bar_width - filled)
        else:
            pos = int(time.monotonic() * 4) % max(1, bar_width)
            cells = ["░"] * bar_width
            for i in range(max(0, pos - 2), min(bar_width, pos + 3)):
                cells[i] = "█"
            bar = "".join(cells)

        line = f"\r{prefix}|{bar}| {tail}{item}"
        if len(line) > width:
            line = line[: width - 1]
        line = line + " " * max(0, width - len(line) - 1)
        self.file.write(line)
        self.file.flush()


class ScanProgress(Protocol):
    """Progress reporting for scanners."""

    @property
    def debug(self) -> bool: ...

    def log(self, msg: str) -> None:
        """Debug-only detail line (no-op unless debug is on)."""
        ...

    def phase(self, name: str) -> None:
        """Set the current high-level phase label on the main bar."""
        ...

    def add_work(self, n: int) -> None:
        """Announce n more work units for the main progress bar."""
        ...

    def tick(self, n: int = 1, *, item: str | None = None) -> None:
        """Advance the main progress bar by n units."""
        ...

    def close(self) -> None:
        """Finish the main progress bar."""
        ...


@dataclass
class TerminalProgress:
    """One general progress bar; verbose logs only when debug=True."""

    file: TextIO | None = None
    enabled: bool = True
    debug: bool = False
    _bar: ProgressBar | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.file = self.file or sys.stderr
        if self.enabled:
            self._bar = ProgressBar(
                0,
                desc="Scan",
                file=self.file,
                enabled=True,
                show_items=self.debug,
            )

    def log(self, msg: str) -> None:
        if not self.debug:
            return
        assert self.file is not None
        # Move off the bar line, print, bar will redraw on next tick
        if self._bar and self._bar.enabled:
            self.file.write("\n")
        self.file.write(f"{msg}\n")
        self.file.flush()

    def phase(self, name: str) -> None:
        self.log(f"→ {name}")
        if self._bar:
            self._bar.set_description(name)

    def add_work(self, n: int) -> None:
        if self._bar:
            self._bar.add_total(n)

    def tick(self, n: int = 1, *, item: str | None = None) -> None:
        if self._bar:
            self._bar.update(n, item=item)

    def close(self) -> None:
        if self._bar:
            self._bar.close()
            self._bar = None


class NullProgress:
    """Silent progress for tests / --no-progress."""

    debug: bool = False

    def log(self, msg: str) -> None:
        return None

    def phase(self, name: str) -> None:
        return None

    def add_work(self, n: int) -> None:
        return None

    def tick(self, n: int = 1, *, item: str | None = None) -> None:
        return None

    def close(self) -> None:
        return None
