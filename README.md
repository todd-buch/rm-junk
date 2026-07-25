# rm-junk

macOS utility that finds leftover junk — app caches, orphaned app data, old installers, and large files/folders — and lets **you** approve every removal.

Nothing is deleted automatically. Background mode (when enabled) only queues findings for review.

## Requirements

- macOS
- Python 3.11+

## Setup

```bash
cd rm-junk
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configure

```bash
python -m rm_junk init
```

This copies `settings.example.json` to:

`~/Library/Application Support/rm-junk/settings.json`

Edit that file to set:

| Key | Purpose |
|-----|---------|
| `scan.largeFileMinBytes` | Size threshold for large file/folder scan (default 1 GB) |
| `scan.largeFileRoots` | Where to look for large items (default `["~"]`) |
| `scan.cacheMinBytes` / `cacheMinAgeDays` | Cache size + staleness gates |
| `excludePaths` | Directories **never** entered |
| `whitelist` | Paths you chose to keep (also written by `keep`) |
| `background.enabled` | Allow background / menu bar agent |
| `background.requireManualApproval` | **Must be true** if background is enabled |
| `scan.workers` | Thread pool size for scans (`0` = auto, typically `cpu × 4`, max 32) |

## Usage

```bash
# Scan (saves pending findings)
python -m rm_junk scan

# Preview without saving
python -m rm_junk scan --dry-run

# List pending
python -m rm_junk list

# Trash a finding (id from list)
python -m rm_junk delete <id>

# Whitelist (never flag again)
python -m rm_junk keep <id>

# Menu bar review UI (count badge; only useful with pending items)
python -m rm_junk menubar --force

# Where settings/findings live
python -m rm_junk paths
```

Or after install: `rm-junk scan`, etc.

## macOS permissions

- Many cache/orphan paths under `~/Library` work without special grants.
- Privacy-sensitive areas (Mail, Messages, Safari, …) are **skipped** by design.
- A full home large-file inventory is more complete with **Full Disk Access** granted to Terminal (dev) or a future `rm-junk.app`.
- Permission errors are skipped; the scan does not crash.

## Safety

- Hard denylist: `/System`, `/usr`, `/Applications`, … and the app’s own support dir
- Prefer **Trash** (`send2trash`) over permanent delete
- Background mode refuses to start if manual approval is not required

## Development

```bash
pytest
```

## Project notes

Local design hub: `context.md` (gitignored). Do not push feature branches until asked.
