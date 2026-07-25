from __future__ import annotations

import shutil
import sys
import threading
import time
from collections import deque
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
        return f"{int(round(seconds))}s"
    total = int(round(seconds))
    minutes, sec = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


class ProgressBar:
    """Thread-safe progress bar with parallel-aware, long-tail-aware ETA."""

    _EMA_ALPHA = 0.25
    _RECENT_MAX = 80

    def __init__(
        self,
        total: int = 0,
        *,
        desc: str = "",
        file: TextIO | None = None,
        enabled: bool = True,
        show_items: bool = True,
        parallelism: int = 1,
    ) -> None:
        self.total = max(0, total)
        self.desc = desc
        self.file = file or sys.stderr
        self.enabled = enabled and self._is_tty()
        self.show_items = show_items
        self.parallelism = max(1, parallelism)
        self.n = 0
        self._item = ""
        self._lock = threading.Lock()
        now = time.monotonic()
        self._start = now
        self._last_tick_at = now
        self._ema_sec_per_unit: float | None = None
        self._recent_durations: deque[float] = deque(maxlen=self._RECENT_MAX)
        # item_key -> start monotonic time (for in-flight long-tail ETA)
        self._inflight: dict[str, float] = {}
        self._closed = False
        if self.enabled:
            self._render()

    def _is_tty(self) -> bool:
        try:
            return bool(self.file.isatty())
        except Exception:
            return False

    def set_parallelism(self, workers: int) -> None:
        with self._lock:
            self.parallelism = max(1, workers)

    def begin_item(self, item: str) -> None:
        """Mark a work unit as started (parallel in-flight tracking)."""
        with self._lock:
            if self._closed:
                return
            key = item or f"#{len(self._inflight)}"
            self._inflight[key] = time.monotonic()
            if self.show_items:
                self._item = item
            if self.enabled:
                self._render()

    def _percentile(self, p: float) -> float | None:
        if not self._recent_durations:
            return None
        data = sorted(self._recent_durations)
        if len(data) == 1:
            return data[0]
        idx = min(len(data) - 1, max(0, int(round((len(data) - 1) * p))))
        return data[idx]

    def _unit_estimate(self) -> float | None:
        """Conservative seconds-per-unit for remaining work."""
        p80 = self._percentile(0.80)
        p50 = self._percentile(0.50)
        candidates = [c for c in (self._ema_sec_per_unit, p50, p80) if c and c > 0]
        if not candidates:
            return None
        # Prefer slower of EMA and p80 so long-tail folders aren't underestimated
        base = max(candidates)
        # Floor so we never project absurdly short times after a burst of tiny dirs
        return max(base, 0.02)

    def _eta_seconds(self, now: float) -> float | None:
        remaining = max(0, self.total - self.n) if self.total else 0
        if remaining <= 0:
            return 0.0

        unit = self._unit_estimate()
        inflight_ages = [now - t for t in self._inflight.values()] if self._inflight else []
        oldest = max(inflight_ages) if inflight_ages else 0.0
        n_inflight = len(inflight_ages)
        not_started = max(0, remaining - n_inflight)
        workers = max(1, self.parallelism)

        if unit is None:
            # No completions yet — if something is running, grow with its age
            if oldest > 0:
                return max(oldest, 1.0)
            return None

        # Wall-clock estimate assuming `workers` parallel slots:
        # remaining units each cost ~unit, scheduled across workers.
        parallel_eta = (remaining / workers) * unit

        # Long-tail correction: an in-flight unit that already exceeds the unit
        # estimate will take *at least* as long as it has already run (often more).
        # Project remaining time on the slowest in-flight job as max(unit, age) - age
        # but when age >> unit, assume it needs roughly as much more as it has used
        # (conservative) so ETA rises instead of stuck at "16s".
        long_tail = 0.0
        for age in inflight_ages:
            if age <= unit:
                long_tail = max(long_tail, unit - age)
            else:
                # Already over budget: expect at least another `age` of work
                # (or unit, whichever larger slice) — rises as stall continues
                long_tail = max(long_tail, age)

        # Work not yet started still needs scheduling after/with in-flight
        if not_started > 0:
            queued_eta = (not_started / workers) * unit
        else:
            queued_eta = 0.0

        eta = max(parallel_eta, long_tail + queued_eta * 0.5, long_tail)
        # Also never below oldest in-flight age when only a few left (honest "still going")
        if remaining <= workers and oldest > 0:
            eta = max(eta, oldest if oldest > unit else parallel_eta)

        return max(eta, 0.0)

    def _note_completion(self, item: str | None, duration: float | None = None) -> None:
        now = time.monotonic()
        if duration is None:
            # Fall back to time since last completion event
            duration = max(0.0, now - self._last_tick_at)
        self._last_tick_at = now
        if duration <= 0:
            duration = 1e-3
        self._recent_durations.append(duration)
        if self._ema_sec_per_unit is None:
            self._ema_sec_per_unit = duration
        else:
            a = self._EMA_ALPHA
            self._ema_sec_per_unit = a * duration + (1.0 - a) * self._ema_sec_per_unit
        if item and item in self._inflight:
            del self._inflight[item]

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
        with self._lock:
            if self._closed:
                return
            if self.show_items:
                self._item = item
            # Treat as begin if not already tracked
            if item and item not in self._inflight:
                self._inflight[item] = time.monotonic()
            if self.enabled:
                self._render()

    def update(self, n: int = 1, *, item: str | None = None) -> None:
        with self._lock:
            if self._closed:
                return
            duration = None
            if item and item in self._inflight:
                duration = time.monotonic() - self._inflight[item]
            if n > 0:
                self._note_completion(item, duration)
                # If n>1 without per-item tracking, split duration
                if n > 1 and duration is not None:
                    for _ in range(n - 1):
                        self._recent_durations.append(duration / n)
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
            self._inflight.clear()
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
            active = len(self._inflight)
            par = f" ×{self.parallelism}" if self.parallelism > 1 else ""
            infl = f" [{active} active]" if active > 1 else ""
            tail = f"{pct:3d}% {counts} {_fmt_seconds(elapsed)} ETA {eta_s}{par}{infl}"
        else:
            frac = 0.0
            tail = f"{self.n} {_fmt_seconds(elapsed)} {rate:.1f}/s"

        prefix = f"{self.desc} " if self.desc else ""
        item = ""
        if self.show_items and self._item:
            item = f"  {self._item}"

        fixed = len(prefix) + len(tail) + 5
        bar_width = max(10, min(28, width - fixed - (24 if item else 4)))
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

    def status(self, item: str) -> None: ...

    def begin(self, item: str) -> None: ...

    def close(self) -> None: ...

    def set_parallelism(self, workers: int) -> None: ...


@dataclass
class TerminalProgress:
    """Per-phase progress bars with parallel-aware ETA."""

    file: TextIO | None = None
    enabled: bool = True
    debug: bool = False
    workers: int = 1
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
                show_items=True,
                parallelism=self.workers,
            )
        return self._bar

    def set_parallelism(self, workers: int) -> None:
        self.workers = max(1, workers)
        if self._bar:
            self._bar.set_parallelism(self.workers)

    def log(self, msg: str) -> None:
        if not self.debug:
            return
        assert self.file is not None
        if self._bar and self._bar.enabled:
            self.file.write("\n")
        self.file.write(f"{msg}\n")
        self.file.flush()

    def phase(self, name: str) -> None:
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

    def begin(self, item: str) -> None:
        if not self.enabled or self._bar is None:
            return
        self._bar.begin_item(item)

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

    def begin(self, item: str) -> None:
        return None

    def tick(self, n: int = 1, *, item: str | None = None) -> None:
        return None

    def status(self, item: str) -> None:
        return None

    def set_parallelism(self, workers: int) -> None:
        return None

    def close(self) -> None:
        return None
