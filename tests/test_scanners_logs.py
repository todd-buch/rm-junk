from __future__ import annotations

import os
import time
from pathlib import Path

from rm_junk.config import parse_settings
from rm_junk.models import Category, Confidence
from rm_junk.path_policy import PathPolicy
from rm_junk.scanners.logs import scan_logs


def test_scan_logs_finds_stale_files(tmp_path: Path):
    # Create mock settings
    settings_dict = {
        "scan": {
            "includeLogs": True,
            "logMinAgeDays": 30,
            "logMinBytes": 100,
        }
    }
    settings = parse_settings(settings_dict)
    policy = PathPolicy(settings)

    # Mock is_hard_denied to return False so that the tmp_path is not skipped
    policy.is_hard_denied = lambda p: False

    # Set up some dummy log roots inside tmp_path
    var_log = tmp_path / "var_log"
    var_log.mkdir()
    lib_logs = tmp_path / "lib_logs"
    lib_logs.mkdir()
    user_logs = tmp_path / "user_logs"
    user_logs.mkdir()

    now = time.time()
    day = 86400

    # 1. Stale log file (40 days old, 150 bytes) -> SHOULD FIND (Confidence.HIGH)
    f1 = var_log / "system.log"
    f1.write_bytes(b"x" * 150)
    stale_time = now - 40 * day
    os.utime(f1, (stale_time, stale_time))

    # 2. Fresh log file (5 days old, 200 bytes) -> SHOULD SKIP (too fresh)
    f2 = var_log / "fresh.log"
    f2.write_bytes(b"x" * 200)
    fresh_time = now - 5 * day
    os.utime(f2, (fresh_time, fresh_time))

    # 3. Stale small log file (40 days old, 50 bytes) -> SHOULD SKIP (too small)
    f3 = lib_logs / "small.log"
    f3.write_bytes(b"x" * 50)
    os.utime(f3, (stale_time, stale_time))

    # 4. Stale non-log file (45 days old, 300 bytes) -> SHOULD FIND (Confidence.MEDIUM)
    f4 = user_logs / "other.tmp"
    f4.write_bytes(b"x" * 300)
    os.utime(f4, (stale_time, stale_time))

    findings = scan_logs(
        settings,
        policy,
        log_roots=[var_log, lib_logs, user_logs]
    )

    # We expect exactly 2 findings: f1 and f4
    assert len(findings) == 2

    # Map findings by path
    by_path = {f.path: f for f in findings}
    assert str(f1) in by_path
    assert str(f4) in by_path

    # Verify details of f1
    f1_finding = by_path[str(f1)]
    assert f1_finding.category == Category.LOG
    assert f1_finding.confidence == Confidence.HIGH
    assert f1_finding.size_bytes == 150
    assert "days old" in f1_finding.reason

    # Verify details of f4
    f4_finding = by_path[str(f4)]
    assert f4_finding.category == Category.LOG
    assert f4_finding.confidence == Confidence.MEDIUM
    assert f4_finding.size_bytes == 300
    assert "days old" in f4_finding.reason
