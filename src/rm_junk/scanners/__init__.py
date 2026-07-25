from __future__ import annotations

from rm_junk.config import Settings
from rm_junk.models import Confidence, Finding
from rm_junk.parallel import default_workers
from rm_junk.path_policy import PathPolicy
from rm_junk.progress import NullProgress, ScanProgress
from rm_junk.scanners.cache import scan_caches
from rm_junk.scanners.installers import scan_old_installers
from rm_junk.scanners.large import scan_large
from rm_junk.scanners.leftover import scan_leftovers

_CONF_RANK = {
    Confidence.HIGH: 3,
    Confidence.MEDIUM: 2,
    Confidence.LOW: 1,
}


def run_all_scanners(
    settings: Settings,
    policy: PathPolicy,
    *,
    progress: ScanProgress | None = None,
) -> list[Finding]:
    """Run enabled scanners; advance a single progress bar via progress.tick()."""
    prog: ScanProgress = progress or NullProgress()
    workers = default_workers(settings.scan.workers or None)
    prog.set_parallelism(workers)
    prog.log(f"Scan workers (per scanner): {workers}")

    findings: list[Finding] = []
    try:
        if settings.scan.include_home_library_caches:
            prog.phase("Caches")
            prog.set_parallelism(workers)
            batch = scan_caches(settings, policy, progress=prog)
            prog.log(f"← caches: {len(batch)} finding(s)")
            findings.extend(batch)

        if settings.scan.include_leftover_app_data:
            prog.phase("Leftovers")
            batch = scan_leftovers(settings, policy, progress=prog)
            prog.log(f"← leftovers: {len(batch)} finding(s)")
            findings.extend(batch)

        if settings.scan.include_old_installers:
            prog.phase("Installers")
            batch = scan_old_installers(settings, policy, progress=prog)
            prog.log(f"← installers: {len(batch)} finding(s)")
            findings.extend(batch)

        if settings.scan.include_large_files:
            prog.phase("Large files")
            prog.set_parallelism(workers)
            batch = scan_large(settings, policy, progress=prog)
            prog.log(f"← large: {len(batch)} finding(s)")
            findings.extend(batch)
    finally:
        prog.close()

    return dedupe_findings(findings)


def dedupe_findings(findings: list[Finding]) -> list[Finding]:
    """Same path once; keep higher confidence, then larger size."""
    best: dict[str, Finding] = {}
    for finding in findings:
        key = finding.path
        existing = best.get(key)
        if existing is None:
            best[key] = finding
            continue
        if _CONF_RANK[finding.confidence] > _CONF_RANK[existing.confidence]:
            best[key] = finding
        elif (
            _CONF_RANK[finding.confidence] == _CONF_RANK[existing.confidence]
            and finding.size_bytes > existing.size_bytes
        ):
            best[key] = finding
    return sorted(
        best.values(),
        key=lambda f: (_CONF_RANK[f.confidence], f.size_bytes),
        reverse=True,
    )


def meets_min_confidence(finding: Finding, minimum: Confidence) -> bool:
    return _CONF_RANK[finding.confidence] >= _CONF_RANK[minimum]
