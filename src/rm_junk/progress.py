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
        show_items: bool = True,
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
        if n <= 0:
            return
        with self._lock:
            if self._closed:
                return
            self.total += n
            if self.enabled:
                self._render()

    def set_item(self, item: str) -> None:
        """Update the label without advancing (e.g. currently scanning X)."""
        with self._lock:
            if self._closed:
                return
            if self.show_items:
                self._item = item
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
        bar_width = max(10, min(30, width - fixed - (28 if item else 4)))
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
    @property
    def debug(self) -> bool: ...

    def log(self, msg: str) -> None: ...

    def phase(self, name: str) -> None: ...

    def add_work(self, n: int) -> None: ...

    def tick(self, n: int = 1, *, item: str | None = None) -> None: ...

    def status(self, item: str) -> None:
        """Show what is currently being scanned (no progress advance)."""
        ...

    def close(self) -> None: ...


@dataclass
class TerminalProgress:
    """Progress bar resets each phase so early fast work cannot fill the bar."""

    file: TextIO | None = None
    enabled: bool = True
    debug: bool = False
    _bar: ProgressBar | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.file = self.file or sys.stderr

    def _ensure_bar(self, desc: str) -> ProgressBar:
        assert self.file is not None
        if self._bar is None:
            self._bar = ProgressBar(
                0,
                desc=desc,
                file=self.file,
                enabled=self.enabled,
                # Always show the *current* path snippet; not a history dump.
                show_items=True,
            )
        return self._bar

    def log(self, msg: str) -> None:
        if not self.debug:
            return
        assert self.file is not None
        if self._bar and self._bar.enabled:
            self.file.write("\n")
        self.file.write(f"{msg}\n")
        self.file.flush()

    def phase(self, name: str) -> None:
        """Start a new phase bar at 0% (closes the previous phase bar)."""
        self.log(f"→ {name}")
        if not self.enabled:
            return
        if self._bar is not None:
            self._bar.close()
            self._bar = None
        self._ensure_bar(name)

    def add_work(self, n: int) -> None:
        if not self.enabled:
            return
        bar = self._ensure_bar(self._bar.desc if self._bar else "Scan")
        bar.add_total(n)

    def tick(self, n: int = 1, *, item: str | None = None) -> None:
        if not self.enabled or self._bar is None:
            return
        self._bar.update(n, item=item)

    def status(self, item: str) -> None:
        if not self.enabled or self._bar is None:
            return
        self._bar.set_item(item)

    def close(self) -> None:
        if self._bar:
            self._bar.close()
            self._bar = None


class NullProgress:
    debug: bool = False

    def log(self, msg: str) -> None:
        return None

    def phase(self, name: str) -> None:
        return None

    def add_work(self, n: int) -> None:
        return None

    def tick(self, n: int = 1, *, item: str | None = None) -> None:
        return None

    def status(self, item: str) -> None:
        return None

    def close(self) -> None:
        return None
