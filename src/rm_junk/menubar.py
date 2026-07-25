from __future__ import annotations

"""Always-on macOS menu bar app for rm-junk."""

import threading
from pathlib import Path

from rm_junk.config import load_settings
from rm_junk.deletion import DeletionError, delete_path
from rm_junk.finding_store import FindingStore
from rm_junk.models import Finding, FindingStatus, format_bytes
from rm_junk.path_policy import PathPolicy
from rm_junk.progress import CallbackProgress
from rm_junk.scanners import meets_min_confidence, run_all_scanners


def run_menu_bar(*, config_path: Path | None = None) -> None:
    """Start the always-visible menu bar app (blocks until quit)."""
    try:
        import rumps
    except ImportError as exc:
        raise SystemExit(
            "rumps is required for the menu bar UI. "
            "Install with: pip install -e '.[dev]'"
        ) from exc

    class RmJunkBar(rumps.App):
        def __init__(self) -> None:
            super().__init__(
                "rm-junk",
                title="rm-junk",
                quit_button=None,
            )
            self._config_path = config_path
            self._scanning = False
            self._scan_lock = threading.Lock()
            self._ui_lock = threading.Lock()
            self._status_line = "Ready — choose Scan / Rerun"
            self._progress_title: str | None = None
            self._findings: list[Finding] = []
            self._status_item: rumps.MenuItem | None = None
            self._scan_item: rumps.MenuItem | None = None
            self._load_findings()
            self._rebuild_menu()
            self._timer = rumps.Timer(self._on_timer, 0.25)
            self._timer.start()

        def _settings(self):
            return load_settings(self._config_path)

        def _load_findings(self) -> None:
            settings = self._settings()
            store = FindingStore()
            self._findings = [
                f
                for f in store.pending
                if meets_min_confidence(f, settings.scan.min_confidence_for_queue)
            ]

        def _idle_title(self) -> str:
            n = len(self._findings)
            return f"rm-junk · {n}" if n else "rm-junk"

        def _on_timer(self, _) -> None:
            with self._ui_lock:
                scanning = self._scanning
                progress_title = self._progress_title
                status = self._status_line
            if scanning and progress_title:
                self.title = progress_title
            else:
                self.title = self._idle_title()
            if self._status_item is not None:
                try:
                    self._status_item.title = _truncate(status, 96)
                except Exception:
                    pass

        def _progress_callback(
            self, short_title: str, full_line: str, done: bool
        ) -> None:
            with self._ui_lock:
                if done:
                    self._progress_title = None
                    self._scanning = False
                    if not self._status_line.startswith("Done"):
                        self._status_line = full_line or "Scan complete"
                else:
                    self._progress_title = short_title
                    self._status_line = full_line

        def _rebuild_menu(self) -> None:
            with self._ui_lock:
                status = self._status_line
                scanning = self._scanning
            findings = list(self._findings)

            self.menu.clear()
            self._status_item = None
            self._scan_item = None

            scan_label = "Scanning…" if scanning else "Scan / Rerun"
            self._scan_item = rumps.MenuItem(
                scan_label,
                callback=None if scanning else self._on_scan,
            )
            self.menu.add(self._scan_item)

            self._status_item = rumps.MenuItem(_truncate(status, 96))
            self._status_item.set_callback(None)
            self.menu.add(self._status_item)

            self.menu.add(rumps.separator)

            if not findings:
                empty = rumps.MenuItem("No pending findings")
                empty.set_callback(None)
                self.menu.add(empty)
            else:
                header = rumps.MenuItem(f"Findings ({len(findings)})")
                header.set_callback(None)
                self.menu.add(header)
                for finding in findings:
                    label = _truncate(
                        f"{format_bytes(finding.size_bytes)}  "
                        f"[{finding.category.value}]  {finding.path}",
                        96,
                    )
                    item = rumps.MenuItem(label)
                    if not scanning:
                        item.add(
                            rumps.MenuItem(
                                "Delete (Trash)",
                                callback=self._make_delete(finding),
                            )
                        )
                        item.add(
                            rumps.MenuItem(
                                "Keep (whitelist)",
                                callback=self._make_keep(finding),
                            )
                        )
                    self.menu.add(item)

            self.menu.add(rumps.separator)
            self.menu.add(rumps.MenuItem("Quit rm-junk", callback=self._on_quit))

            if not scanning:
                self.title = self._idle_title()

        def _on_scan(self, _) -> None:
            if not self._scan_lock.acquire(blocking=False):
                return
            with self._ui_lock:
                if self._scanning:
                    self._scan_lock.release()
                    return
                self._scanning = True
                self._status_line = "Starting scan…"
                self._progress_title = "… Scan"
            self._rebuild_menu()

            def worker() -> None:
                try:
                    settings = self._settings()
                    policy = PathPolicy(settings)
                    progress = CallbackProgress(self._progress_callback)
                    findings = run_all_scanners(
                        settings, policy, progress=progress
                    )
                    findings = [
                        f
                        for f in findings
                        if meets_min_confidence(
                            f, settings.scan.min_confidence_for_queue
                        )
                    ]
                    store = FindingStore()
                    store.replace_pending_with(findings)
                    self._findings = [
                        f
                        for f in store.pending
                        if meets_min_confidence(
                            f, settings.scan.min_confidence_for_queue
                        )
                    ]
                    with self._ui_lock:
                        self._status_line = (
                            f"Done — {len(self._findings)} finding(s)"
                        )
                        self._progress_title = None
                        self._scanning = False
                except Exception as exc:
                    with self._ui_lock:
                        self._status_line = f"Scan failed: {exc}"
                        self._progress_title = None
                        self._scanning = False
                finally:
                    rumps.Timer(self._finish_scan_ui, 0.05).start()
                    self._scan_lock.release()

            threading.Thread(target=worker, daemon=True).start()

        def _finish_scan_ui(self, timer) -> None:
            try:
                timer.stop()
            except Exception:
                pass
            self._rebuild_menu()

        def _make_delete(self, finding: Finding):
            def handler(_):
                try:
                    settings = self._settings()
                    policy = PathPolicy(settings)
                    delete_path(
                        finding.path,
                        policy,
                        to_trash=settings.deletion.move_to_trash,
                    )
                    FindingStore().mark(finding.id, FindingStatus.DELETED)
                    self._findings = [
                        f for f in self._findings if f.id != finding.id
                    ]
                    with self._ui_lock:
                        self._status_line = f"Trashed {finding.path}"
                    self._rebuild_menu()
                except (DeletionError, Exception) as exc:
                    rumps.alert(title="Delete failed", message=str(exc))

            return handler

        def _make_keep(self, finding: Finding):
            def handler(_):
                try:
                    settings = self._settings()
                    settings.save_whitelist(
                        list(settings.whitelist) + [finding.path]
                    )
                    FindingStore().mark(finding.id, FindingStatus.KEPT)
                    self._findings = [
                        f for f in self._findings if f.id != finding.id
                    ]
                    with self._ui_lock:
                        self._status_line = f"Whitelisted {finding.path}"
                    self._rebuild_menu()
                except Exception as exc:
                    rumps.alert(title="Keep failed", message=str(exc))

            return handler

        def _on_quit(self, _) -> None:
            rumps.quit_application()

    RmJunkBar().run()


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
