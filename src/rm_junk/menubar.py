from __future__ import annotations

"""Menu bar review queue (macOS) using rumps.

Only intended when background mode is enabled and pending findings exist.
"""

from typing import Callable

from rm_junk.models import Finding, format_bytes


def run_menu_bar(
    findings: list[Finding],
    *,
    on_delete: Callable[[Finding], None] | None = None,
    on_keep: Callable[[Finding], None] | None = None,
) -> None:
    if not findings:
        print("No pending findings — menu bar icon is not shown when count is 0.")
        return

    try:
        import rumps
    except ImportError as exc:
        raise SystemExit(
            "rumps is required for the menu bar UI. Install with: pip install rumps"
        ) from exc

    class RmJunkBar(rumps.App):
        def __init__(self) -> None:
            super().__init__(
                f"{len(findings)}",
                title=f"{len(findings)}",
                quit_button="Quit rm-junk",
            )
            self._findings = list(findings)
            self._rebuild()

        def _rebuild(self) -> None:
            self.menu.clear()
            if not self._findings:
                self.title = ""
                rumps.quit_application()
                return
            self.title = str(len(self._findings))
            for finding in self._findings:
                label = (
                    f"{format_bytes(finding.size_bytes)}  "
                    f"[{finding.category.value}]  {finding.path}"
                )
                # Truncate very long labels for menu usability
                if len(label) > 96:
                    label = label[:93] + "..."
                item = rumps.MenuItem(label)
                item.add(
                    rumps.MenuItem(
                        "Delete",
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

        def _make_delete(self, finding: Finding):
            def handler(_):
                if on_delete:
                    try:
                        on_delete(finding)
                    except Exception as exc:
                        rumps.alert(title="Delete failed", message=str(exc))
                        return
                self._findings = [f for f in self._findings if f.id != finding.id]
                self._rebuild()

            return handler

        def _make_keep(self, finding: Finding):
            def handler(_):
                if on_keep:
                    try:
                        on_keep(finding)
                    except Exception as exc:
                        rumps.alert(title="Keep failed", message=str(exc))
                        return
                self._findings = [f for f in self._findings if f.id != finding.id]
                self._rebuild()

            return handler

    RmJunkBar().run()
