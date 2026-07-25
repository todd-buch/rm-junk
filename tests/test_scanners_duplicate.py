from __future__ import annotations

from pathlib import Path

from rm_junk.config import parse_settings
from rm_junk.models import Category, Confidence
from rm_junk.path_policy import PathPolicy
from rm_junk.scanners.duplicate import scan_duplicates


def test_scan_duplicates_finds_identical_files(tmp_path: Path):
    settings_dict = {
        "scan": {
            "includeDuplicates": True,
            "duplicateMinBytes": 100,
        }
    }
    settings = parse_settings(settings_dict)
    policy = PathPolicy(settings)
    policy.is_hard_denied = lambda p: False

    # Create test root and files
    root = tmp_path / "dup_root"
    root.mkdir()

    # 1 & 2. Duplicates (165 bytes, same content)
    file_a = root / "file_a.dat"
    file_a.write_bytes(b"hello world" * 15)
    file_b = root / "file_b.dat"
    file_b.write_bytes(b"hello world" * 15)

    # 3. Same size, different content -> SHOULD NOT BE DUPLICATE
    file_c = root / "file_c.dat"
    file_c.write_bytes(b"different content!" * 9 + b"x" * 3)  # 165 bytes

    # 4 & 5. Tiny duplicates (50 bytes) -> SHOULD SKIP (below 100 bytes limit)
    file_d = root / "file_d.dat"
    file_d.write_bytes(b"tiny" * 12 + b"xx")
    file_e = root / "file_e.dat"
    file_e.write_bytes(b"tiny" * 12 + b"xx")

    findings = scan_duplicates(
        settings,
        policy,
        duplicate_roots=[root]
    )

    # We expect exactly 1 duplicate finding (file_b as duplicate of file_a,
    # because file_a has the shorter path name: "file_a.dat" vs "file_b.dat" - wait, length is same.
    # Sorted by (len(path), path) -> file_a.dat < file_b.dat, so file_a is original, file_b is dup!)
    assert len(findings) == 1
    assert findings[0].path == str(file_b)
    assert findings[0].category == Category.LEFTOVER
    assert findings[0].confidence == Confidence.HIGH
    assert findings[0].size_bytes == 165
    assert "duplicate of file_a.dat" in findings[0].reason.lower()
