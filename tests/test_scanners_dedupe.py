from rm_junk.models import Category, Confidence, Finding
from rm_junk.scanners import dedupe_findings, meets_min_confidence


def test_dedupe_prefers_higher_confidence():
    a = Finding(
        path="/tmp/x",
        size_bytes=10,
        category=Category.CACHE,
        confidence=Confidence.LOW,
        reason="low",
    )
    b = Finding(
        path="/tmp/x",
        size_bytes=5,
        category=Category.LEFTOVER,
        confidence=Confidence.HIGH,
        reason="high",
    )
    out = dedupe_findings([a, b])
    assert len(out) == 1
    assert out[0].confidence == Confidence.HIGH


def test_meets_min_confidence():
    f = Finding(
        path="/tmp/y",
        size_bytes=1,
        category=Category.CACHE,
        confidence=Confidence.MEDIUM,
        reason="m",
    )
    assert meets_min_confidence(f, Confidence.LOW)
    assert meets_min_confidence(f, Confidence.MEDIUM)
    assert not meets_min_confidence(f, Confidence.HIGH)
