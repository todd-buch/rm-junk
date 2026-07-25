from __future__ import annotations

import plistlib
from pathlib import Path

from typing import Callable

from rm_junk.config import Settings
from rm_junk.models import Category, Confidence, Finding
from rm_junk.path_policy import PathPolicy
from rm_junk.sizing import entry_size

ProgressFn = Callable[[str], None]


def _read_bundle_id(app_path: Path) -> str | None:
    info = app_path / "Contents" / "Info.plist"
    if not info.is_file():
        return None
    try:
        with info.open("rb") as fh:
            data = plistlib.load(fh)
        bid = data.get("CFBundleIdentifier")
        return str(bid) if bid else None
    except Exception:
        return None


def installed_bundle_ids() -> set[str]:
    ids: set[str] = set()
    for apps_root in (Path("/Applications"), Path.home() / "Applications"):
        if not apps_root.is_dir():
            continue
        try:
            for child in apps_root.iterdir():
                if child.suffix == ".app" and child.is_dir():
                    bid = _read_bundle_id(child)
                    if bid:
                        ids.add(bid)
        except OSError:
            continue
    return ids


def _is_apple(bundle_or_name: str) -> bool:
    lower = bundle_or_name.lower()
    return lower.startswith("com.apple.") or lower.startswith("apple.")


def _plist_domain(name: str) -> str | None:
    if not name.endswith(".plist"):
        return None
    return name[: -len(".plist")]


def scan_leftovers(
    settings: Settings,
    policy: PathPolicy,
    *,
    progress: ProgressFn | None = None,
) -> list[Finding]:
    """Conservative orphan detection via bundle IDs and dead LaunchAgents."""
    _ = settings  # thresholds unused for now; leftovers are mostly presence-based
    findings: list[Finding] = []
    if progress:
        progress("Leftover / orphan scan…")
    installed = installed_bundle_ids()
    home = Path.home()

    # LaunchAgents pointing at missing binaries — high confidence
    agents = home / "Library" / "LaunchAgents"
    if agents.is_dir() and not policy.should_skip(agents):
        for entry in policy.safe_scandir(agents):
            try:
                if not entry.name.endswith(".plist") or not entry.is_file(
                    follow_symlinks=False
                ):
                    continue
                path = Path(entry.path)
                if policy.should_skip(path):
                    continue
                with path.open("rb") as fh:
                    data = plistlib.load(fh)
                program = data.get("Program")
                args = data.get("ProgramArguments") or []
                candidate = program or (args[0] if args else None)
                if not candidate:
                    continue
                prog_path = Path(str(candidate)).expanduser()
                if prog_path.exists():
                    continue
                size = entry_size(path, policy)
                findings.append(
                    Finding(
                        path=str(path),
                        size_bytes=size,
                        category=Category.LEFTOVER,
                        confidence=Confidence.HIGH,
                        reason=(
                            f"LaunchAgent program missing: {prog_path}"
                        ),
                    )
                )
            except Exception:
                continue

    # Saved Application State — bundle id no longer installed
    saved = home / "Library" / "Saved Application State"
    if saved.is_dir() and not policy.should_skip(saved):
        for entry in policy.safe_scandir(saved):
            try:
                name = entry.name
                if not name.endswith(".savedState"):
                    continue
                domain = name[: -len(".savedState")]
                if _is_apple(domain) or domain in installed:
                    continue
                # Only flag if we have a plausible reverse-DNS id
                if domain.count(".") < 1:
                    continue
                path = Path(entry.path)
                size = entry_size(path, policy)
                findings.append(
                    Finding(
                        path=str(path),
                        size_bytes=size,
                        category=Category.LEFTOVER,
                        confidence=Confidence.MEDIUM,
                        reason=f"Saved state for missing app id '{domain}'",
                    )
                )
            except OSError:
                continue

    # Preferences plists — only reverse-DNS and not installed, not Apple
    prefs = home / "Library" / "Preferences"
    if prefs.is_dir() and not policy.should_skip(prefs):
        for entry in policy.safe_scandir(prefs):
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
                domain = _plist_domain(entry.name)
                if not domain or _is_apple(domain):
                    continue
                if domain.count(".") < 2:
                    continue
                if domain in installed:
                    continue
                # Avoid byhost and system-looking noise
                if ".ByHost" in entry.name or domain.startswith("com.apple."):
                    continue
                # Low confidence: prefs can outlive apps we didn't detect
                # (App Store apps in other locations, CLI tools, etc.)
                # Skip tiny noise; still conservative: only if parent patterns match
                # known leftover-ish and size is non-trivial OR we keep medium only
                # for exact-looking ids that are clearly third-party.
                path = Path(entry.path)
                size = entry_size(path, policy)
                # Prefer not to flood: only report prefs > 100KB
                if size < 100_000:
                    continue
                findings.append(
                    Finding(
                        path=str(path),
                        size_bytes=size,
                        category=Category.LEFTOVER,
                        confidence=Confidence.LOW,
                        reason=(
                            f"Preference domain '{domain}' has no matching "
                            f".app in /Applications or ~/Applications"
                        ),
                    )
                )
            except OSError:
                continue

    return findings
