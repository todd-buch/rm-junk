from __future__ import annotations

import os
import time
from pathlib import Path

from rm_junk.config import parse_settings
from rm_junk.models import Category, Confidence
from rm_junk.path_policy import PathPolicy
from rm_junk.scanners.developer import scan_developer


def test_scan_developer_finds_stale_items(tmp_path: Path):
    # Setup settings
    settings_dict = {
        "scan": {
            "includeDeveloperJunk": True,
            "devJunkMinAgeDays": 30,
            "devJunkMinBytes": 50 * 1024 * 1024,  # 50 MB
        }
    }
    settings = parse_settings(settings_dict)
    policy = PathPolicy(settings)

    # Disable hard deny checks for tmp_path testing
    policy.is_hard_denied = lambda p: False

    # Create directories for testing
    npm_dir = tmp_path / "npm_cache"
    npm_dir.mkdir()
    yarn_dir = tmp_path / "yarn_cache"
    yarn_dir.mkdir()
    cocoapods_dir = tmp_path / "cocoapods_cache"
    cocoapods_dir.mkdir()

    device_support_dir = tmp_path / "device_support"
    device_support_dir.mkdir()
    ios_15_5 = device_support_dir / "15.5"
    ios_15_5.mkdir()

    archives_root = tmp_path / "archives"
    archives_root.mkdir()
    date_dir = archives_root / "2026-03-24"
    date_dir.mkdir()
    app_archive = date_dir / "App.xcarchive"
    app_archive.mkdir()

    now = time.time()
    day = 86400

    # 1. Stale Parent Target: npm_cache (40 days old, 60MB) -> SHOULD FIND (Confidence.HIGH)
    f_npm = npm_dir / "somefile.dat"
    f_npm.write_bytes(b"x" * (60 * 1024 * 1024))
    stale_time = now - 40 * day
    os.utime(npm_dir, (stale_time, stale_time))

    # 2. Fresh Parent Target: yarn_cache (5 days old, 70MB) -> SHOULD SKIP (too fresh)
    f_yarn = yarn_dir / "yarnfile.dat"
    f_yarn.write_bytes(b"x" * (70 * 1024 * 1024))
    fresh_time = now - 5 * day
    os.utime(yarn_dir, (fresh_time, fresh_time))

    # 3. Small Parent Target: cocoapods_cache (40 days old, 10MB) -> SHOULD SKIP (too small)
    f_pods = cocoapods_dir / "pods.dat"
    f_pods.write_bytes(b"x" * (10 * 1024 * 1024))
    os.utime(cocoapods_dir, (stale_time, stale_time))

    # 4. Stale Child Target: iOS 15.5 (45 days old, 80MB) -> SHOULD FIND (Confidence.MEDIUM)
    f_ios = ios_15_5 / "symbols"
    f_ios.write_bytes(b"x" * (80 * 1024 * 1024))
    os.utime(ios_15_5, (stale_time, stale_time))

    # 5. Stale Archive: App.xcarchive (50 days old, 100MB) -> SHOULD FIND (Confidence.MEDIUM)
    f_arch = app_archive / "Products"
    f_arch.write_bytes(b"x" * (100 * 1024 * 1024))
    os.utime(app_archive, (stale_time, stale_time))

    # Run scanner with stubbed targets
    findings = scan_developer(
        settings,
        policy,
        parent_targets=[
            (npm_dir, "npm Cache"),
            (yarn_dir, "Yarn Cache"),
            (cocoapods_dir, "CocoaPods Cache"),
        ],
        child_targets=[
            (device_support_dir, "Xcode iOS DeviceSupport"),
        ],
        archives_root=archives_root,
    )

    # We expect exactly 3 findings: npm_cache, ios_15_5, app_archive
    assert len(findings) == 3

    by_path = {f.path: f for f in findings}
    assert str(npm_dir) in by_path
    assert str(ios_15_5) in by_path
    assert str(app_archive) in by_path

    # Verify npm_cache
    npm_f = by_path[str(npm_dir)]
    assert npm_f.category == Category.DEV_CACHE
    assert npm_f.confidence == Confidence.HIGH
    assert npm_f.size_bytes == 60 * 1024 * 1024
    assert "stale" in npm_f.reason.lower()

    # Verify ios_15_5
    ios_f = by_path[str(ios_15_5)]
    assert ios_f.category == Category.DEV_CACHE
    assert ios_f.confidence == Confidence.MEDIUM
    assert ios_f.size_bytes == 80 * 1024 * 1024
    assert "stale" in ios_f.reason.lower()

    # Verify app_archive
    arch_f = by_path[str(app_archive)]
    assert arch_f.category == Category.DEV_CACHE
    assert arch_f.confidence == Confidence.MEDIUM
    assert arch_f.size_bytes == 100 * 1024 * 1024
    assert "stale" in arch_f.reason.lower()
