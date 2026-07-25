import json
from pathlib import Path

import pytest

from rm_junk.config import ConfigError, parse_settings


def test_defaults_parse():
    settings = parse_settings({})
    assert settings.scan.large_file_min_bytes == 1024 * 1024 * 1024  # 1 GB default
    assert settings.background.enabled is False
    assert settings.background.require_manual_approval is True
    # Do not deep-scan entire home by default
    assert "~" not in settings.scan.large_file_roots
    assert "~/Library" in settings.scan.large_file_roots
    assert "~/Documents" in settings.exclude_paths
    assert settings.scan.max_depth == 4


def test_large_file_min_gb():
    settings = parse_settings({"scan": {"largeFileMinGB": 50}})
    assert settings.scan.large_file_min_bytes == 50 * (1024**3)


def test_large_file_min_bytes_legacy():
    settings = parse_settings({"scan": {"largeFileMinBytes": 2_000_000_000}})
    assert settings.scan.large_file_min_bytes == 2_000_000_000


def test_background_requires_manual_approval():
    with pytest.raises(ConfigError, match="requireManualApproval"):
        parse_settings(
            {
                "background": {
                    "enabled": True,
                    "requireManualApproval": False,
                }
            }
        )


def test_background_ok_with_approval():
    settings = parse_settings(
        {
            "background": {
                "enabled": True,
                "requireManualApproval": True,
            }
        }
    )
    assert settings.background.enabled is True


def test_merge_partial(tmp_path: Path):
    data = {"scan": {"cacheMinBytes": 1000}, "excludePaths": ["/tmp/foo"]}
    settings = parse_settings(data, path=tmp_path / "settings.json")
    assert settings.scan.cache_min_bytes == 1000
    assert settings.scan.include_home_library_caches is True
    assert settings.exclude_paths == ["/tmp/foo"]


def test_invalid_confidence():
    with pytest.raises(ConfigError):
        parse_settings({"scan": {"minConfidenceForQueue": "nope"}})


def test_roundtrip_example_file():
    example = Path(__file__).resolve().parents[1] / "settings.example.json"
    data = json.loads(example.read_text(encoding="utf-8"))
    settings = parse_settings(data)
    assert settings.version == 1
