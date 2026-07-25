from __future__ import annotations

import os
import time
from pathlib import Path

from rm_junk.config import parse_settings
from rm_junk.models import Category, Confidence
from rm_junk.path_policy import PathPolicy
from rm_junk.scanners.mail import scan_mail


def test_scan_mail_finds_stale_attachments(tmp_path: Path):
    # Enable mail attachments scan
    settings_dict = {
        "scan": {
            "includeMailAttachments": True,
            "mailAttachmentMinAgeDays": 30,
            "mailAttachmentMinBytes": 100,
        }
    }
    settings = parse_settings(settings_dict)
    policy = PathPolicy(settings)

    # Disable hard deny checks for tmp_path testing
    policy.is_hard_denied = lambda p: False

    # Create dummy mail structure
    mail_root = tmp_path / "Mail"
    mail_root.mkdir()
    account_dir = mail_root / "IMAP-test@example.com"
    account_dir.mkdir()
    inbox_mbox = account_dir / "INBOX.mbox"
    inbox_mbox.mkdir()
    attachments_dir = inbox_mbox / "Attachments"
    attachments_dir.mkdir()
    sub_attachment_dir = attachments_dir / "12345"
    sub_attachment_dir.mkdir()

    now = time.time()
    day = 86400

    # 1. Stale attachment: (40 days old, 150 bytes) -> SHOULD FIND (Confidence.MEDIUM)
    f1 = sub_attachment_dir / "file1.pdf"
    f1.write_bytes(b"x" * 150)
    stale_time = now - 40 * day
    os.utime(f1, (stale_time, stale_time))

    # 2. Fresh attachment: (5 days old, 200 bytes) -> SHOULD SKIP (too fresh)
    f2 = sub_attachment_dir / "file2.docx"
    f2.write_bytes(b"x" * 200)
    fresh_time = now - 5 * day
    os.utime(f2, (fresh_time, fresh_time))

    # 3. Small attachment: (40 days old, 50 bytes) -> SHOULD SKIP (too small)
    f3 = sub_attachment_dir / "file3.png"
    f3.write_bytes(b"x" * 50)
    os.utime(f3, (stale_time, stale_time))

    # 4. File outside of Attachments: (40 days old, 300 bytes) -> SHOULD SKIP
    f4 = inbox_mbox / "some_message.emlx"
    f4.write_bytes(b"x" * 300)
    os.utime(f4, (stale_time, stale_time))

    findings = scan_mail(
        settings,
        policy,
        mail_roots=[mail_root]
    )

    # We expect exactly 1 finding: f1
    assert len(findings) == 1
    assert findings[0].path == str(f1)
    assert findings[0].category == Category.CACHE
    assert findings[0].confidence == Confidence.MEDIUM
    assert findings[0].size_bytes == 150
    assert "stale mail attachment" in findings[0].reason.lower()
