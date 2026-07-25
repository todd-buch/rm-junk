from __future__ import annotations

import os
from pathlib import Path

from rm_junk.config import Settings, expand_path, project_root

# Paths we never enter or suggest for deletion (prefix match after resolve).
HARD_DENY_PREFIXES: tuple[str, ...] = (
    "/System",
    "/usr",
    "/bin",
    "/sbin",
    "/private/var/vm",
    "/private/var/folders",
    "/Library/Apple",
    "/Applications",
)

# Sensitive user Library areas — skip entirely (TCC / privacy).
SENSITIVE_LIBRARY_SUFFIXES: tuple[str, ...] = (
    "Library/Mail",
    "Library/Messages",
    "Library/Safari",
    "Library/Cookies",
    "Library/Accounts",
    "Library/IdentityServices",
    "Library/Application Support/AddressBook",
    "Library/Application Support/CallHistoryDB",
    "Library/Application Support/CallHistoryTransactions",
    "Library/Application Support/com.apple.TCC",
    "Library/Application Support/Knowledge",
    "Library/Application Support/FileProvider",
    "Library/Calendars",
    "Library/Reminders",
    "Library/Containers/com.apple.mail",
    "Library/Containers/com.apple.MobileSMS",
    "Library/Group Containers/group.com.apple.shortcuts",
)


class PathPolicy:
    """Central gate for scan traversal and delete eligibility."""

    def __init__(self, settings: Settings) -> None:
        self.follow_symlinks = settings.scan.follow_symlinks
        self._exclude = self._normalize_list(settings.exclude_paths)
        self._whitelist = self._normalize_list(settings.whitelist)
        # Never scan/delete our own project data (settings, findings, source).
        try:
            self._project_root = project_root().resolve()
        except OSError:
            self._project_root = project_root()
        home = Path.home().resolve()
        sensitive_suffixes = list(SENSITIVE_LIBRARY_SUFFIXES)
        if getattr(settings.scan, "include_mail_attachments", False):
            sensitive_suffixes = [
                s for s in sensitive_suffixes
                if s not in ("Library/Mail", "Library/Containers/com.apple.mail")
            ]
        self._sensitive = [
            (home / rel).resolve() for rel in sensitive_suffixes
        ]

    @staticmethod
    def _normalize_list(values: list[str]) -> list[Path]:
        out: list[Path] = []
        for value in values:
            try:
                out.append(expand_path(value))
            except OSError:
                # Path may not exist yet; still keep expanded form.
                out.append(Path(os.path.expanduser(value)).absolute())
        return out

    def is_hard_denied(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path.absolute()
        text = str(resolved)
        if text == "/" or text == "":
            return True
        for prefix in HARD_DENY_PREFIXES:
            if text == prefix or text.startswith(prefix + "/"):
                return True
        # Never touch our own project directory (local settings/findings/code).
        try:
            resolved.relative_to(self._project_root)
            return True
        except ValueError:
            pass
        return False

    def is_sensitive(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path.absolute()
        for sensitive in self._sensitive:
            try:
                resolved.relative_to(sensitive)
                return True
            except ValueError:
                if resolved == sensitive:
                    return True
        return False

    def is_excluded(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path.absolute()
        for excluded in self._exclude:
            try:
                resolved.relative_to(excluded)
                return True
            except ValueError:
                if resolved == excluded:
                    return True
        return False

    def is_whitelisted(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path.absolute()
        for kept in self._whitelist:
            try:
                resolved.relative_to(kept)
                return True
            except ValueError:
                if resolved == kept:
                    return True
        return False

    def should_skip(self, path: Path) -> bool:
        """True if scanners must not enter or report this path."""
        if self.is_hard_denied(path):
            return True
        if self.is_sensitive(path):
            return True
        if self.is_excluded(path):
            return True
        if self.is_whitelisted(path):
            return True
        return False

    def may_delete(self, path: Path) -> bool:
        """Stricter: same as skip, plus refuse hard denylist always."""
        if self.is_hard_denied(path):
            return False
        if self.is_sensitive(path):
            return False
        if self.is_excluded(path):
            return False
        return True

    def safe_scandir(self, path: Path):
        """Yield DirEntry children, honoring symlink policy and skips."""
        if self.should_skip(path):
            return
        try:
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        child = Path(entry.path)
                        if not self.follow_symlinks and entry.is_symlink():
                            continue
                        if self.should_skip(child):
                            continue
                        yield entry
                    except OSError:
                        continue
        except OSError:
            return
