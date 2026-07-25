from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class Category(str, Enum):
    CACHE = "cache"
    DEV_CACHE = "dev_cache"
    LEFTOVER = "leftover"
    INSTALLER = "installer"
    LARGE = "large"
    BROKEN_LINK = "broken_link"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    def rank(self) -> int:
        return {Confidence.HIGH: 3, Confidence.MEDIUM: 2, Confidence.LOW: 1}[self]

    @classmethod
    def parse(cls, value: str) -> Confidence:
        return cls(value.lower())


class FindingStatus(str, Enum):
    PENDING = "pending"
    KEPT = "kept"
    DELETED = "deleted"


@dataclass
class Finding:
    path: str
    size_bytes: int
    category: Category
    confidence: Confidence
    reason: str
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    discovered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    status: FindingStatus = FindingStatus.PENDING

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["category"] = self.category.value
        data["confidence"] = self.confidence.value
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Finding:
        return cls(
            id=data.get("id", uuid4().hex[:12]),
            path=data["path"],
            size_bytes=int(data["size_bytes"]),
            category=Category(data["category"]),
            confidence=Confidence(data["confidence"]),
            reason=data["reason"],
            discovered_at=data.get(
                "discovered_at", datetime.now(timezone.utc).isoformat()
            ),
            status=FindingStatus(data.get("status", FindingStatus.PENDING.value)),
        )


def format_bytes(n: int) -> str:
    """Human-readable size."""
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{n} B"
