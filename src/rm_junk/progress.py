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
    """Human duration; never truncates a positive ETA down to a bare '0s'."""
    if seconds <= 0:
        return "0s"
    if seconds < 1:
        return "<1s"
    if seconds < 60:
        # Prefer whole seconds once we're past 1s
        return f"{int(round(seconds))}s"
    total = int(round(seconds))
    minutes, sec = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


class ProgressBar:
    """Thread-safe single-line progress bar for TTY stderr."""

    # Weight recent tick duration more so slow late work isn't hidden by
    # hundreds of near-instant early ticks.
    _EMA_ALPHA = 0.35

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
        now = time.monotonic()
        self._start = now
        self._last_tick_at = now
        self._ema_sec_per_unit: float | None = None
        self._closed = False
        if self.enabled:
            self._render()

    def _is_tty(self) -> bool:
        try:
            return bool(self.file.isatty())
        except Exception:
            return False

    def _note_progress(self, units: int) -> None:
        """Update per-unit timing model after `units` completed."""
        if units <= 0:
            return
        now = time.monotonic()
        dt = max(0.0, now - self._last_tick_at)
        self._last_tick_at = now
        inst = dt / units
        # Ignore pure-zero intervals (batch of same-timestamp updates) for EMA
        # so we don't drive sec/unit to 0 permanently.
        if inst <= 0:
            inst = 1e-3
        if self._ema_sec_per_unit is None:
            self._ema_sec_per_unit = inst
        else:
            a = self._EMA_ALPHA
            self._ema_sec_per_unit = a * inst + (1.0 - a) * self._ema_sec_per_unit

    def _eta_seconds(self, now: float) -> float | None:
        """Estimate remaining seconds, or None if not enough data."""
        remaining = max(0, self.total - self.n) if self.total else 0
        if remaining <= 0:
            return 0.0
        stall = max(0.0, now - self._last_tick_at)

        if self._ema_sec_per_unit is not None and self._ema_sec_per_unit > 0:
            # Time for remaining units, but if we've been stuck on the current
            # unit longer than expected, count that stall toward the current one.
            eta = self._ema_sec_per_unit * remaining
            if stall > self._ema_sec_per_unit:
                eta = stall + self._ema_sec_per_unit * max(0, remaining - 1)
            return eta

        # Fallback: overall average (only once we have completions + elapsed)
        elapsed = now - self._start
        if self.n > 0 and elapsed > 0:
            return (elapsed / self.n) * remaining
        return None

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
            if n > 0:
                self._note_progress(n)
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

    def format_line(self, width: int | None = None) -> str:
        """Return the current bar text (same style as the terminal UI)."""
        width = width or _term_width()
        now = time.monotonic()
        elapsed = now - self._start
        rate = self.n / elapsed if elapsed > 0 else 0.0

        if self.total > 0:
            frac = min(1.0, self.n / self.total)
            pct = int(frac * 100)
            counts = f"{self.n}/{self.total}"
            eta = self._eta_seconds(now)
            if self.n >= self.total:
                eta_s = "0s"
            elif eta is None:
                eta_s = "…"
            else:
                eta_s = _fmt_seconds(eta)
            tail = f"{pct:3d}% {counts} {_fmt_seconds(elapsed)} ETA {eta_s}"
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

        line = f"{prefix}|{bar}| {tail}{item}"
        if len(line) > width:
            line = line[: width - 1]
        return line

    def _render(self) -> None:
        width = _term_width()
        line = self.format_line(width)
        # Clear to end of line after \\r
        padded = "\r" + line + " " * max(0, width - len(line) - 1)
        self.file.write(padded)
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
