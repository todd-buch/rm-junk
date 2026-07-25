from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

from rm_junk.cli import build_parser, cmd_delete
from rm_junk.models import Category, Confidence, Finding, FindingStatus


def test_parser_delete_high_confidence():
    parser = build_parser()
    args = parser.parse_args(["delete", "--high-confidence", "-y"])
    assert args.high_confidence is True
    assert args.yes is True


@patch("rm_junk.cli.FindingStore")
@patch("rm_junk.cli.delete_path")
@patch("rm_junk.cli.load_settings")
def test_cmd_delete_high_confidence(
    mock_load_settings, mock_delete_path, mock_finding_store
):
    # Mock settings
    mock_settings = MagicMock()
    mock_settings.deletion.move_to_trash = False
    mock_load_settings.return_value = mock_settings

    # Mock findings store with 1 high and 1 medium confidence findings
    finding_high = Finding(
        path="/tmp/high.txt",
        size_bytes=100,
        category=Category.CACHE,
        confidence=Confidence.HIGH,
        reason="high",
    )
    finding_medium = Finding(
        path="/tmp/medium.txt",
        size_bytes=200,
        category=Category.CACHE,
        confidence=Confidence.MEDIUM,
        reason="medium",
    )

    mock_store = MagicMock()
    mock_store.pending = [finding_high, finding_medium]
    mock_finding_store.return_value = mock_store

    # Call cmd_delete with high_confidence=True
    args = argparse.Namespace(
        config=None,
        all=False,
        high_confidence=True,
        ids=[],
        yes=True,
    )

    result = cmd_delete(args)
    assert result == 0

    # Ensure only finding_high was marked for deletion
    mock_delete_path.assert_called_once()
    args_called = mock_delete_path.call_args[0]
    assert args_called[0] == "/tmp/high.txt"

    mock_store.mark.assert_called_once_with(finding_high.id, FindingStatus.DELETED)
