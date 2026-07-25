from __future__ import annotations

import json
import os
import re
import shutil
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rm_junk.models import Confidence

SETTINGS_FILENAME = "settings.json"
FINDINGS_FILENAME = "findings.json"
DEFAULT_SETTINGS_VERSION = 1


class ConfigError(Exception):
    """Invalid or unusable configuration."""


def parse_size(value: Any) -> int:
    if isinstance(value, (int, float)):
        if isinstance(value, bool):
            raise ConfigError("Size cannot be a boolean")
        if value < 0:
            raise ConfigError("Size cannot be negative")
        return int(value)
    
    if not isinstance(value, str):
        raise ConfigError(f"Invalid size type: {type(value)}")
    
    val_str = value.strip().upper()
    if not val_str:
        return 0
    
    match = re.match(r"^(\d+(?:\.\d+)?)\s*([A-Z]*)$", val_str)
    if not match:
        raise ConfigError(f"Invalid size format: '{value}'")
    
    num_str, unit = match.groups()
    num = float(num_str)
    
    if not unit or unit == "B":
        return int(num)
    
    units = {
        "K": 1024, "KB": 1024,
        "M": 1024**2, "MB": 1024**2,
        "G": 1024**3, "GB": 1024**3,
        "T": 1024**4, "TB": 1024**4,
        "P": 1024**5, "PB": 1024**5,
    }
    
    if unit not in units:
        raise ConfigError(f"Unsupported size unit: '{unit}' in '{value}'")
    
    return int(num * units[unit])


def format_size(bytes_val: int) -> str:
    if bytes_val < 0:
        return "0B"
    if bytes_val == 0:
        return "0B"
    
    if bytes_val % (1024**3) == 0:
        return f"{bytes_val // (1024**3)}GB"
    
    for unit, factor in [("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)]:
        val = bytes_val / factor
        if val >= 1.0:
            if val.is_integer():
                return f"{int(val)}{unit}"
            formatted = f"{val:.2f}".rstrip("0").rstrip(".")
            try:
                parsed = parse_size(f"{formatted}{unit}")
                if parsed == bytes_val:
                    return f"{formatted}{unit}"
            except ConfigError:
                pass
            
    return f"{bytes_val}B"


def _require_size(data: dict[str, Any], key: str, default: int) -> int:
    if key not in data:
        return default
    value = data[key]
    try:
        return parse_size(value)
    except ConfigError as exc:
        raise ConfigError(f"Invalid size for {key}: {exc}") from exc


def project_root() -> Path:
    """Directory for local data (settings.json, findings.json).

    Preference order:
    1. ``RM_JUNK_HOME`` env var
    2. Nearest project root containing ``pyproject.toml`` named rm-junk
       (from cwd or package install path)
    3. Current working directory
    """
    env = os.environ.get("RM_JUNK_HOME")
    if env:
        path = Path(env).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def is_project(d: Path) -> bool:
        pyproject = d / "pyproject.toml"
        if not pyproject.is_file():
            return False
        try:
            text = pyproject.read_text(encoding="utf-8")
        except OSError:
            return False
        return 'name = "rm-junk"' in text or "name = 'rm-junk'" in text

    starts = [Path.cwd()]
    try:
        # src/rm_junk/config.py -> repo root when editable/source layout
        starts.append(Path(__file__).resolve().parents[2])
    except IndexError:
        pass

    seen: set[Path] = set()
    for start in starts:
        try:
            cur = start.resolve()
        except OSError:
            continue
        for d in [cur, *cur.parents]:
            if d in seen:
                continue
            seen.add(d)
            if is_project(d):
                return d

    cwd = Path.cwd().resolve()
    cwd.mkdir(parents=True, exist_ok=True)
    return cwd


def default_settings_path() -> Path:
    return project_root() / SETTINGS_FILENAME


def default_findings_path() -> Path:
    return project_root() / FINDINGS_FILENAME


def example_settings_path() -> Path:
    """Bundled example next to the project / package."""
    root = project_root()
    candidate = root / "settings.example.json"
    if candidate.is_file():
        return candidate
    # Source layout fallback
    try:
        repo = Path(__file__).resolve().parents[2]
        alt = repo / "settings.example.json"
        if alt.is_file():
            return alt
    except IndexError:
        pass
    return Path(__file__).resolve().parent / "settings.example.json"


# Junk-prone locations only — not the whole home tree (Documents, Downloads,
# Desktop, project folders, etc. are intentionally omitted by default).
DEFAULT_LARGE_FILE_ROOTS: list[str] = [
    "~/Library",
    "~/.docker",
    "~/.vagrant.d",
    "~/.cache",
    "~/.local",
    "~/Parallels",
    "~/VirtualBox VMs",
]

DEFAULTS: dict[str, Any] = {
    "version": DEFAULT_SETTINGS_VERSION,
    "scan": {
        "includeHomeLibraryCaches": True,
        "includeLeftoverAppData": True,
        "includeLargeFiles": True,
        "includeOldInstallers": True,
        "includeLogs": True,
        "includeDeveloperJunk": True,
        "includeMailAttachments": False,
        "includeTrashBins": True,
        "cacheMinBytes": "50MB",
        "cacheMinAgeDays": 3,
        "logMinAgeDays": 30,
        "logMinBytes": "0B",
        "devJunkMinBytes": "50MB",
        "devJunkMinAgeDays": 30,
        "mailAttachmentMinBytes": "5MB",
        "mailAttachmentMinAgeDays": 30,
        "trashMinBytes": "0B",
        "trashMinAgeDays": 7,
        "includeDuplicates": False,
        "duplicateMinBytes": "1MB",
        "largeFileRoots": list(DEFAULT_LARGE_FILE_ROOTS),
        "installerMinBytes": "100MB",
        "installerMinAgeDays": 30,
        "maxDepth": 4,
        "followSymlinks": False,
        "minConfidenceForQueue": "medium",
        "workers": 0,
    },
    # Never enter these (all scanners). Personal media/docs stay off-limits.
    # Note: Downloads is *not* excluded so the optional old-installer scan can
    # list top-level .dmg/.pkg files only (it does not deep-walk Downloads).
    "excludePaths": [
        "~/Documents",
        "~/Desktop",
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
    include_logs: bool = True
    include_developer_junk: bool = True
    include_mail_attachments: bool = False
    include_trash_bins: bool = True
    include_duplicates: bool = False
    cache_min_bytes: int = 50 * 1024 * 1024
    cache_min_age_days: int = 3
    log_min_age_days: int = 30
    log_min_bytes: int = 0
    dev_junk_min_bytes: int = 50 * 1024 * 1024
    dev_junk_min_age_days: int = 30
    mail_attachment_min_bytes: int = 5 * 1024 * 1024
    mail_attachment_min_age_days: int = 30
    trash_min_bytes: int = 0
    trash_min_age_days: int = 7
    duplicate_min_bytes: int = 1024 * 1024
    large_file_min_bytes: int = 1024 * 1024 * 1024
    large_file_roots: list[str] = field(
        default_factory=lambda: list(DEFAULT_LARGE_FILE_ROOTS)
    )
    installer_min_bytes: int = 100 * 1024 * 1024
    installer_min_age_days: int = 30
    max_depth: int = 4
    follow_symlinks: bool = False
    min_confidence_for_queue: Confidence = Confidence.MEDIUM
    workers: int = 0  # 0 = auto (cpu-based)


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
            "includeLogs": settings.scan.include_logs,
            "includeDeveloperJunk": settings.scan.include_developer_junk,
            "includeMailAttachments": settings.scan.include_mail_attachments,
            "includeTrashBins": settings.scan.include_trash_bins,
            "cacheMinBytes": format_size(settings.scan.cache_min_bytes),
            "cacheMinAgeDays": settings.scan.cache_min_age_days,
            "logMinAgeDays": settings.scan.log_min_age_days,
            "logMinBytes": format_size(settings.scan.log_min_bytes),
            "devJunkMinBytes": format_size(settings.scan.dev_junk_min_bytes),
            "devJunkMinAgeDays": settings.scan.dev_junk_min_age_days,
            "mailAttachmentMinBytes": format_size(settings.scan.mail_attachment_min_bytes),
            "mailAttachmentMinAgeDays": settings.scan.mail_attachment_min_age_days,
            "trashMinBytes": format_size(settings.scan.trash_min_bytes),
            "trashMinAgeDays": settings.scan.trash_min_age_days,
            "includeDuplicates": settings.scan.include_duplicates,
            "duplicateMinBytes": format_size(settings.scan.duplicate_min_bytes),
            "largeFileMinBytes": format_size(settings.scan.large_file_min_bytes),
            "largeFileRoots": list(settings.scan.large_file_roots),
            "installerMinBytes": format_size(settings.scan.installer_min_bytes),
            "installerMinAgeDays": settings.scan.installer_min_age_days,
            "maxDepth": settings.scan.max_depth,
            "followSymlinks": settings.scan.follow_symlinks,
            "minConfidenceForQueue": settings.scan.min_confidence_for_queue.value,
            "workers": settings.scan.workers,
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


def _require_number(
    data: dict[str, Any], key: str, default: float, *, min_value: float = 0
) -> float:
    if key not in data:
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{key} must be a number")
    if value < min_value:
        raise ConfigError(f"{key} must be >= {min_value}")
    return float(value)


def _large_file_min_bytes(scan_raw: dict[str, Any]) -> int:
    """Prefer largeFileMinBytes (as size string/bytes); fallback to largeFileMinGB."""
    if "largeFileMinBytes" in scan_raw:
        return _require_size(scan_raw, "largeFileMinBytes", 1024 * 1024 * 1024)
    if "largeFileMinGB" in scan_raw:
        val = scan_raw["largeFileMinGB"]
        if isinstance(val, str):
            try:
                return parse_size(val)
            except ConfigError as exc:
                raise ConfigError(f"largeFileMinGB is not a valid size: {exc}") from exc
        # legacy/numeric gigabytes
        gb = _require_number(scan_raw, "largeFileMinGB", 1.0, min_value=0.001)
        return int(gb * (1024**3))
    return 1024 * 1024 * 1024


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
            include_logs=_require_bool(scan_raw, "includeLogs", True),
            include_developer_junk=_require_bool(
                scan_raw, "includeDeveloperJunk", True
            ),
            include_mail_attachments=_require_bool(
                scan_raw, "includeMailAttachments", False
            ),
            include_trash_bins=_require_bool(scan_raw, "includeTrashBins", True),
            include_duplicates=_require_bool(scan_raw, "includeDuplicates", False),
            cache_min_bytes=_require_size(scan_raw, "cacheMinBytes", 50 * 1024 * 1024),
            cache_min_age_days=_require_int(scan_raw, "cacheMinAgeDays", 3),
            log_min_age_days=_require_int(scan_raw, "logMinAgeDays", 30),
            log_min_bytes=_require_size(scan_raw, "logMinBytes", 0),
            dev_junk_min_bytes=_require_size(
                scan_raw, "devJunkMinBytes", 50 * 1024 * 1024
            ),
            dev_junk_min_age_days=_require_int(scan_raw, "devJunkMinAgeDays", 30),
            mail_attachment_min_bytes=_require_size(
                scan_raw, "mailAttachmentMinBytes", 5 * 1024 * 1024
            ),
            mail_attachment_min_age_days=_require_int(
                scan_raw, "mailAttachmentMinAgeDays", 30
            ),
            trash_min_bytes=_require_size(scan_raw, "trashMinBytes", 0),
            trash_min_age_days=_require_int(scan_raw, "trashMinAgeDays", 7),
            duplicate_min_bytes=_require_size(scan_raw, "duplicateMinBytes", 1024 * 1024),
            large_file_min_bytes=_large_file_min_bytes(scan_raw),
            large_file_roots=_require_str_list(
                scan_raw, "largeFileRoots", list(DEFAULT_LARGE_FILE_ROOTS)
            ),
            installer_min_bytes=_require_size(
                scan_raw, "installerMinBytes", 100 * 1024 * 1024
            ),
            installer_min_age_days=_require_int(scan_raw, "installerMinAgeDays", 30),
            max_depth=_require_int(scan_raw, "maxDepth", 4, min_value=1),
            follow_symlinks=_require_bool(scan_raw, "followSymlinks", False),
            min_confidence_for_queue=min_conf,
            workers=_require_int(scan_raw, "workers", 0, min_value=0),
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
    """Copy example settings into the project directory if missing."""
    settings_path = path or default_settings_path()
    if settings_path.is_file():
        return settings_path
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    example = example_settings_path()
    if example.is_file() and example.resolve() != settings_path.resolve():
        shutil.copyfile(example, settings_path)
    else:
        settings_path.write_text(
            json.dumps(DEFAULTS, indent=2) + "\n", encoding="utf-8"
        )
    return settings_path


def expand_path(value: str) -> Path:
    return Path(os.path.expanduser(value)).resolve()
