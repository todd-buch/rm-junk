import json
from pathlib import Path

import pytest

from rm_junk.config import ConfigError, parse_settings


def test_defaults_parse():
    settings = parse_settings({})
    assert settings.scan.large_file_min_bytes == 1024 * 1024 * 1024
    assert settings.background.enabled is False
    assert settings.background.require_manual_approval is True


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
