from __future__ import annotations

import json
import os
import shutil
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rm_junk.models import Confidence

APP_SUPPORT_DIRNAME = "rm-junk"
SETTINGS_FILENAME = "settings.json"
FINDINGS_FILENAME = "findings.json"
DEFAULT_SETTINGS_VERSION = 1


class ConfigError(Exception):
    """Invalid or unusable configuration."""


def app_support_dir() -> Path:
    base = Path.home() / "Library" / "Application Support" / APP_SUPPORT_DIRNAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def default_settings_path() -> Path:
    return app_support_dir() / SETTINGS_FILENAME


def default_findings_path() -> Path:
    return app_support_dir() / FINDINGS_FILENAME


def example_settings_path() -> Path:
    """Repo-bundled example next to package root when installed editable / from source."""
    # src/rm_junk/config.py -> parents: rm_junk, src, repo
    repo_root = Path(__file__).resolve().parents[2]
    candidate = repo_root / "settings.example.json"
    if candidate.is_file():
        return candidate
    # Fallback: alongside package (if we later ship data files)
    return Path(__file__).resolve().parent / "settings.example.json"


DEFAULTS: dict[str, Any] = {
    "version": DEFAULT_SETTINGS_VERSION,
    "scan": {
        "includeHomeLibraryCaches": True,
        "includeLeftoverAppData": True,
        "includeLargeFiles": True,
        "includeOldInstallers": True,
        "cacheMinBytes": 50 * 1024 * 1024,
        "cacheMinAgeDays": 3,
        "largeFileMinBytes": 1024 * 1024 * 1024,
        "largeFileRoots": ["~"],
        "installerMinBytes": 100 * 1024 * 1024,
        "installerMinAgeDays": 30,
        "maxDepth": 6,
        "followSymlinks": False,
        "minConfidenceForQueue": "medium",
    },
    "excludePaths": [
        "~/Pictures",
        "~/Movies",
        "~/Music",
    ],
    "whitelist": [],
    "background": {
        "enabled": False,
        "requireManualApproval": True,
        "intervalMinutes": 1440,
        "showMenuBarWhenFindings": True,
    },
    "deletion": {
        "moveToTrash": True,
        "confirmEachItem": True,
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


@dataclass
class ScanSettings:
    include_home_library_caches: bool = True
    include_leftover_app_data: bool = True
    include_large_files: bool = True
    include_old_installers: bool = True
    cache_min_bytes: int = 50 * 1024 * 1024
    cache_min_age_days: int = 3
    large_file_min_bytes: int = 1024 * 1024 * 1024
    large_file_roots: list[str] = field(default_factory=lambda: ["~"])
    installer_min_bytes: int = 100 * 1024 * 1024
    installer_min_age_days: int = 30
    max_depth: int = 6
    follow_symlinks: bool = False
    min_confidence_for_queue: Confidence = Confidence.MEDIUM


@dataclass
class BackgroundSettings:
    enabled: bool = False
    require_manual_approval: bool = True
    interval_minutes: int = 1440
    show_menu_bar_when_findings: bool = True


@dataclass
class DeletionSettings:
    move_to_trash: bool = True
    confirm_each_item: bool = True


@dataclass
class Settings:
    version: int
    scan: ScanSettings
    exclude_paths: list[str]
    whitelist: list[str]
    background: BackgroundSettings
    deletion: DeletionSettings
    path: Path | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def ensure_background_safe(self) -> None:
        """Hard product rule: background requires manual approval."""
        if self.background.enabled and not self.background.require_manual_approval:
            raise ConfigError(
                "background.enabled requires background.requireManualApproval "
                "to be true (automatic deletion is not allowed)."
            )

    def save_whitelist(self, paths: list[str]) -> None:
        self.whitelist = sorted(set(paths))
        if self.path is None:
            raise ConfigError("No settings path to save whitelist")
        data = deepcopy(self.raw) if self.raw else settings_to_dict(self)
        data["whitelist"] = self.whitelist
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        self.raw = data


def settings_to_dict(settings: Settings) -> dict[str, Any]:
    return {
        "version": settings.version,
        "scan": {
            "includeHomeLibraryCaches": settings.scan.include_home_library_caches,
            "includeLeftoverAppData": settings.scan.include_leftover_app_data,
            "includeLargeFiles": settings.scan.include_large_files,
            "includeOldInstallers": settings.scan.include_old_installers,
            "cacheMinBytes": settings.scan.cache_min_bytes,
            "cacheMinAgeDays": settings.scan.cache_min_age_days,
            "largeFileMinBytes": settings.scan.large_file_min_bytes,
            "largeFileRoots": list(settings.scan.large_file_roots),
            "installerMinBytes": settings.scan.installer_min_bytes,
            "installerMinAgeDays": settings.scan.installer_min_age_days,
            "maxDepth": settings.scan.max_depth,
            "followSymlinks": settings.scan.follow_symlinks,
            "minConfidenceForQueue": settings.scan.min_confidence_for_queue.value,
        },
        "excludePaths": list(settings.exclude_paths),
        "whitelist": list(settings.whitelist),
        "background": {
            "enabled": settings.background.enabled,
            "requireManualApproval": settings.background.require_manual_approval,
            "intervalMinutes": settings.background.interval_minutes,
            "showMenuBarWhenFindings": settings.background.show_menu_bar_when_findings,
        },
        "deletion": {
            "moveToTrash": settings.deletion.move_to_trash,
            "confirmEachItem": settings.deletion.confirm_each_item,
        },
    }


def _require_bool(data: dict[str, Any], key: str, default: bool) -> bool:
    if key not in data:
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise ConfigError(f"{key} must be a boolean")
    return value


def _require_int(data: dict[str, Any], key: str, default: int, *, min_value: int = 0) -> int:
    if key not in data:
        return default
    value = data[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{key} must be an integer")
    if value < min_value:
        raise ConfigError(f"{key} must be >= {min_value}")
    return value


def _require_str_list(data: dict[str, Any], key: str, default: list[str]) -> list[str]:
    if key not in data:
        return list(default)
    value = data[key]
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ConfigError(f"{key} must be a list of strings")
    return list(value)


def parse_settings(data: dict[str, Any], *, path: Path | None = None) -> Settings:
    merged = _deep_merge(DEFAULTS, data)
    scan_raw = merged.get("scan", {})
    bg_raw = merged.get("background", {})
    del_raw = merged.get("deletion", {})

    if not isinstance(scan_raw, dict) or not isinstance(bg_raw, dict) or not isinstance(
        del_raw, dict
    ):
        raise ConfigError("scan, background, and deletion must be objects")

    try:
        min_conf = Confidence.parse(
            str(scan_raw.get("minConfidenceForQueue", "medium"))
        )
    except ValueError as exc:
        raise ConfigError(
            "scan.minConfidenceForQueue must be high, medium, or low"
        ) from exc

    settings = Settings(
        version=int(merged.get("version", DEFAULT_SETTINGS_VERSION)),
        scan=ScanSettings(
            include_home_library_caches=_require_bool(
                scan_raw, "includeHomeLibraryCaches", True
            ),
            include_leftover_app_data=_require_bool(
                scan_raw, "includeLeftoverAppData", True
            ),
            include_large_files=_require_bool(scan_raw, "includeLargeFiles", True),
            include_old_installers=_require_bool(
                scan_raw, "includeOldInstallers", True
            ),
            cache_min_bytes=_require_int(scan_raw, "cacheMinBytes", 50 * 1024 * 1024),
            cache_min_age_days=_require_int(scan_raw, "cacheMinAgeDays", 3),
            large_file_min_bytes=_require_int(
                scan_raw, "largeFileMinBytes", 1024 * 1024 * 1024
            ),
            large_file_roots=_require_str_list(scan_raw, "largeFileRoots", ["~"]),
            installer_min_bytes=_require_int(
                scan_raw, "installerMinBytes", 100 * 1024 * 1024
            ),
            installer_min_age_days=_require_int(scan_raw, "installerMinAgeDays", 30),
            max_depth=_require_int(scan_raw, "maxDepth", 6, min_value=1),
            follow_symlinks=_require_bool(scan_raw, "followSymlinks", False),
            min_confidence_for_queue=min_conf,
        ),
        exclude_paths=_require_str_list(merged, "excludePaths", DEFAULTS["excludePaths"]),
        whitelist=_require_str_list(merged, "whitelist", []),
        background=BackgroundSettings(
            enabled=_require_bool(bg_raw, "enabled", False),
            require_manual_approval=_require_bool(
                bg_raw, "requireManualApproval", True
            ),
            interval_minutes=_require_int(bg_raw, "intervalMinutes", 1440, min_value=1),
            show_menu_bar_when_findings=_require_bool(
                bg_raw, "showMenuBarWhenFindings", True
            ),
        ),
        deletion=DeletionSettings(
            move_to_trash=_require_bool(del_raw, "moveToTrash", True),
            confirm_each_item=_require_bool(del_raw, "confirmEachItem", True),
        ),
        path=path,
        raw=merged,
    )
    settings.ensure_background_safe()
    return settings


def load_settings(path: Path | None = None, *, create_if_missing: bool = True) -> Settings:
    settings_path = path or default_settings_path()
    if not settings_path.is_file():
        if not create_if_missing:
            raise ConfigError(f"Settings not found: {settings_path}")
        ensure_user_settings(settings_path)
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {settings_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("Settings root must be a JSON object")
    return parse_settings(data, path=settings_path)


def ensure_user_settings(path: Path | None = None) -> Path:
    """Copy example settings into Application Support if missing."""
    settings_path = path or default_settings_path()
    if settings_path.is_file():
        return settings_path
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    example = example_settings_path()
    if example.is_file():
        shutil.copyfile(example, settings_path)
    else:
        settings_path.write_text(
            json.dumps(DEFAULTS, indent=2) + "\n", encoding="utf-8"
        )
    return settings_path


def expand_path(value: str) -> Path:
    return Path(os.path.expanduser(value)).resolve()
