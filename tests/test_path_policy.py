from pathlib import Path

from rm_junk.config import parse_settings
from rm_junk.path_policy import PathPolicy


def test_hard_deny_system():
    settings = parse_settings({"excludePaths": [], "whitelist": []})
    policy = PathPolicy(settings)
    assert policy.should_skip(Path("/System/Library"))
    assert policy.should_skip(Path("/Applications/Safari.app"))
    assert not policy.may_delete(Path("/System/Library"))


def test_exclude_and_whitelist(tmp_path: Path):
    keep = tmp_path / "keep_me"
    skip = tmp_path / "skip_me"
    keep.mkdir()
    skip.mkdir()
    settings = parse_settings(
        {
            "excludePaths": [str(skip)],
            "whitelist": [str(keep)],
        }
    )
    policy = PathPolicy(settings)
    assert policy.should_skip(skip)
    assert policy.should_skip(keep)  # whitelist => don't re-report
    assert policy.is_whitelisted(keep)
    assert not policy.may_delete(skip)


def test_app_support_denied():
    settings = parse_settings({"excludePaths": [], "whitelist": []})
    policy = PathPolicy(settings)
    support = Path.home() / "Library" / "Application Support" / "rm-junk"
    assert policy.should_skip(support)
