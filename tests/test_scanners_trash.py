from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

from rm_junk.config import parse_settings
from rm_junk.deletion import delete_path
from rm_junk.models import Category, Confidence
from rm_junk.path_policy import PathPolicy
from rm_junk.scanners.trash import scan_trash


def test_scan_trash_finds_stale_files(tmp_path: Path):
    # Setup settings
    settings_dict = {
        "scan": {
            "includeTrashBins": True,
            "trashMinAgeDays": 7,
            "trashMinBytes": 100,
        }
    }
    settings = parse_settings(settings_dict)
    policy = PathPolicy(settings)
    policy.is_hard_denied = lambda p: False

    # Create dummy trash dir
    trash_dir = tmp_path / "Trash"
    trash_dir.mkdir()

    now = time.time()
    day = 86400

    # 1. Stale trash file (10 days old, 150 bytes) -> SHOULD FIND (Confidence.HIGH)
    f1 = trash_dir / "stale.txt"
    f1.write_bytes(b"x" * 150)
    stale_time = now - 10 * day
    os.utime(f1, (stale_time, stale_time))

    # 2. Fresh trash file (2 days old, 200 bytes) -> SHOULD SKIP (too fresh)
    f2 = trash_dir / "fresh.txt"
    f2.write_bytes(b"x" * 200)
    fresh_time = now - 2 * day
    os.utime(f2, (fresh_time, fresh_time))

    # 3. Small trash file (10 days old, 50 bytes) -> SHOULD SKIP (too small)
    f3 = trash_dir / "small.txt"
    f3.write_bytes(b"x" * 50)
    os.utime(f3, (stale_time, stale_time))

    findings = scan_trash(
        settings,
        policy,
        trash_roots=[trash_dir]
    )

    # We expect exactly 1 finding: f1
    assert len(findings) == 1
    assert findings[0].path == str(f1)
    assert findings[0].category == Category.CACHE
    assert findings[0].confidence == Confidence.HIGH
    assert findings[0].size_bytes == 150
    assert "trash item" in findings[0].reason.lower()


def test_delete_path_bypasses_send2trash_in_trash_folders(tmp_path: Path):
    settings = parse_settings({})
    policy = PathPolicy(settings)
    policy.is_hard_denied = lambda p: False

    # Create a path representing a trash directory
    fake_trash = tmp_path / ".Trash"
    fake_trash.mkdir()
    target_file = fake_trash / "trash_item.txt"
    target_file.touch()

    # If we call delete_path with to_trash=True, it should bypass send2trash
    # and delete it permanently. We patch send2trash to assert it was never called.
    with patch("send2trash.send2trash") as mock_send:
        delete_path(target_file, policy, to_trash=True)
        assert not target_file.exists()
        mock_send.assert_not_called()


def test_delete_path_falls_back_to_permanent_delete(tmp_path: Path):
    settings = parse_settings({})
    policy = PathPolicy(settings)
    policy.is_hard_denied = lambda p: False

    target_file = tmp_path / "fallback_item.txt"
    target_file.touch()

    # If send2trash raises OSError, it should fallback to permanent delete (unlink)
    with patch("send2trash.send2trash", side_effect=OSError("fake permission error")) as mock_send:
        delete_path(target_file, policy, to_trash=True)
        assert not target_file.exists()
        mock_send.assert_called_once()


def test_delete_path_raises_deletion_error_on_total_failure(tmp_path: Path):
    settings = parse_settings({})
    policy = PathPolicy(settings)
    policy.is_hard_denied = lambda p: False

    target_file = tmp_path / "total_failure_item.txt"
    target_file.touch()

    # If both send2trash and permanent delete fail (e.g. unlink raises OSError),
    # it should raise DeletionError
    from rm_junk.deletion import DeletionError
    with patch("send2trash.send2trash", side_effect=OSError("fake error")), \
         patch("pathlib.Path.unlink", side_effect=OSError("absolute permission error")):
        import pytest
        with pytest.raises(DeletionError, match="absolute permission error"):
            delete_path(target_file, policy, to_trash=True)
