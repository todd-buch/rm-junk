from __future__ import annotations

import shutil
import sys
import threading
import time
from dataclasses import dataclass
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
        total: int,
        *,
        desc: str = "",
        file: TextIO | None = None,
        enabled: bool = True,
    ) -> None:
        self.total = max(0, total)
        self.desc = desc
        self.file = file or sys.stderr
        self.enabled = enabled and self._is_tty()
        self.n = 0
        self._item = ""
        self._lock = threading.Lock()
        self._start = time.monotonic()
        self._closed = False
        if self.enabled and self.total > 0:
            self._render()

    def _is_tty(self) -> bool:
        try:
            return bool(self.file.isatty())
        except Exception:
            return False

    def update(self, n: int = 1, *, item: str | None = None) -> None:
        with self._lock:
            if self._closed:
                return
            self.n += n
            if self.total:
                self.n = min(self.n, self.total)
            if item is not None:
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
            elif self.desc:
                # Non-TTY: one summary line
                elapsed = _fmt_seconds(time.monotonic() - self._start)
                self.file.write(
                    f"{self.desc}: {self.n}/{self.total or self.n} done ({elapsed})\n"
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
        item = f" {self._item}" if self._item else ""
        # Reserve space for prefix + bar + tail + item
        fixed = len(prefix) + len(tail) + 5  # brackets/spaces
        bar_width = max(10, min(30, width - fixed - 20))
        filled = int(bar_width * frac) if self.total else int(time.monotonic() * 2) % (
            bar_width + 1
        )
        if self.total:
            bar = "█" * filled + "░" * (bar_width - filled)
        else:
            # Indeterminate bounce
            pos = int(time.monotonic() * 4) % max(1, bar_width)
            cells = ["░"] * bar_width
            for i in range(max(0, pos - 2), min(bar_width, pos + 3)):
                cells[i] = "█"
            bar = "".join(cells)

        # Truncate item to fit
        line = f"\r{prefix}|{bar}| {tail}{item}"
        if len(line) > width:
            line = line[: width - 1]
        # Clear to end of line
        line = line + " " * max(0, width - len(line) - 1)
        self.file.write(line)
        self.file.flush()


class ScanProgress(Protocol):
    def log(self, msg: str) -> None: ...

    def bar(self, total: int, *, desc: str = "") -> ProgressBar: ...


@dataclass
class TerminalProgress:
    """Default CLI progress: logs + progress bars on stderr."""

    file: TextIO | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        self.file = self.file or sys.stderr

    def log(self, msg: str) -> None:
        # Ensure we don't stomp an active bar: print newline-terminated line
        assert self.file is not None
        self.file.write(f"{msg}\n")
        self.file.flush()

    def bar(self, total: int, *, desc: str = "") -> ProgressBar:
        assert self.file is not None
        return ProgressBar(
            total,
            desc=desc,
            file=self.file,
            enabled=self.enabled,
        )


class NullProgress:
    """Silent progress for tests / library use."""

    def log(self, msg: str) -> None:
        return None

    def bar(self, total: int, *, desc: str = "") -> ProgressBar:
        return ProgressBar(total, desc=desc, enabled=False)
