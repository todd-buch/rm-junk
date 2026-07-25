from __future__ import annotations

import plistlib
from pathlib import Path

from rm_junk.config import parse_settings
from rm_junk.models import Category, Confidence
from rm_junk.path_policy import PathPolicy
from rm_junk.scanners.leftover import scan_leftovers


def test_scan_leftovers_launch_agents_and_pref_panes(tmp_path: Path):
    settings = parse_settings({})
    policy = PathPolicy(settings)

    # Disable hard deny checks for tmp_path testing
    policy.is_hard_denied = lambda p: False

    # Create directories for testing
    agent_dir = tmp_path / "agents"
    agent_dir.mkdir()
    pane_dir = tmp_path / "panes"
    pane_dir.mkdir()

    # 1. LaunchAgent with missing executable -> SHOULD FIND
    plist1 = agent_dir / "com.broken.plist"
    plist1_data = {
        "Program": str(tmp_path / "non_existent_binary")
    }
    with plist1.open("wb") as fh:
        plistlib.dump(plist1_data, fh)

    # 2. LaunchAgent with existing executable -> SHOULD SKIP
    existing_exec = tmp_path / "existing_binary"
    existing_exec.touch()
    plist2 = agent_dir / "com.working.plist"
    plist2_data = {
        "Program": str(existing_exec)
    }
    with plist2.open("wb") as fh:
        plistlib.dump(plist2_data, fh)

    # 3. Preference Pane with missing Info.plist -> SHOULD FIND
    pane_broken = pane_dir / "Broken.prefPane"
    pane_broken.mkdir()

    # 4. Preference Pane with missing executable -> SHOULD FIND
    pane_missing_exec = pane_dir / "MissingExec.prefPane"
    pane_missing_exec.mkdir()
    contents_dir = pane_missing_exec / "Contents"
    contents_dir.mkdir()
    info_plist = contents_dir / "Info.plist"
    info_data = {
        "CFBundleExecutable": "MyHelper"
    }
    with info_plist.open("wb") as fh:
        plistlib.dump(info_data, fh)

    # 5. Preference Pane with existing executable -> SHOULD SKIP
    pane_working = pane_dir / "Working.prefPane"
    pane_working.mkdir()
    contents_working = pane_working / "Contents"
    contents_working.mkdir()
    macos_dir = contents_working / "MacOS"
    macos_dir.mkdir()
    working_exec = macos_dir / "WorkingHelper"
    working_exec.touch()
    info_plist_working = contents_working / "Info.plist"
    info_data_working = {
        "CFBundleExecutable": "WorkingHelper"
    }
    with info_plist_working.open("wb") as fh:
        plistlib.dump(info_data_working, fh)

    findings = scan_leftovers(
        settings,
        policy,
        agent_dirs=[(agent_dir, "LaunchAgent")],
        pref_pane_dirs=[pane_dir],
    )

    # Filter findings to check only our test directories
    test_paths = {str(plist1), str(pane_broken), str(pane_missing_exec)}
    matched = [f for f in findings if f.path in test_paths]

    assert len(matched) == 3

    by_path = {f.path: f for f in matched}
    assert str(plist1) in by_path
    assert str(pane_broken) in by_path
    assert str(pane_missing_exec) in by_path

    # Verify plist1 details
    f_plist = by_path[str(plist1)]
    assert f_plist.category == Category.LEFTOVER
    assert f_plist.confidence == Confidence.HIGH
    assert "missing" in f_plist.reason

    # Verify pane_broken details
    f_broken = by_path[str(pane_broken)]
    assert f_broken.category == Category.LEFTOVER
    assert f_broken.confidence == Confidence.HIGH
    assert "missing Info.plist" in f_broken.reason

    # Verify pane_missing_exec details
    f_missing_exec = by_path[str(pane_missing_exec)]
    assert f_missing_exec.category == Category.LEFTOVER
    assert f_missing_exec.confidence == Confidence.HIGH
    assert "executable missing" in f_missing_exec.reason
