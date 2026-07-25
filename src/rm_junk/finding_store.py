from __future__ import annotations

import json
from pathlib import Path

from rm_junk.config import default_findings_path
from rm_junk.models import Finding, FindingStatus


class FindingStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_findings_path()
        self._findings: list[Finding] = []
        self.load()

    def load(self) -> None:
        if not self.path.is_file():
            self._findings = []
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            items = data.get("findings", data if isinstance(data, list) else [])
            self._findings = [Finding.from_dict(x) for x in items]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            self._findings = []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "findings": [f.to_dict() for f in self._findings],
        }
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    @property
    def pending(self) -> list[Finding]:
        return [f for f in self._findings if f.status == FindingStatus.PENDING]

    def all(self) -> list[Finding]:
        return list(self._findings)

    def replace_pending_with(self, findings: list[Finding]) -> None:
        """Merge scan results: keep non-pending history lightly, reset pending set."""
        kept_or_deleted = [
            f for f in self._findings if f.status != FindingStatus.PENDING
        ]
        # Drop history beyond last 200 non-pending
        history = kept_or_deleted[-200:]
        # Avoid re-adding paths already whitelisted externally — caller handles policy
        self._findings = history + [
            f for f in findings if f.status == FindingStatus.PENDING
        ]
        self.save()

    def get(self, finding_id: str) -> Finding | None:
        for f in self._findings:
            if f.id == finding_id:
                return f
        return None

    def mark(self, finding_id: str, status: FindingStatus) -> Finding | None:
        finding = self.get(finding_id)
        if finding is None:
            return None
        finding.status = status
        self.save()
        return finding
