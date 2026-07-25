# rm-junk

macOS utility that finds leftover junk — app caches, orphaned app data, old installers, and large files/folders — and lets **you** approve every removal.

Nothing is deleted automatically.

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

Creates **project-local** files (same directory as this repo by default):

| File | Purpose |
|------|---------|
| `settings.json` | Your config (gitignored) |
| `findings.json` | Pending scan results (gitignored) |

Override the project directory with `RM_JUNK_HOME=/path/to/dir` if needed.

Edit `settings.json` for thresholds, roots, and excludes. See `settings.example.json`.

| Key | Purpose |
|-----|---------|
| `scan.largeFileMinBytes` | Size threshold for large file/folder scan (default 1 GB) |
| `scan.largeFileRoots` | Where large-item scan looks (default: `Library`, Docker, VMs — **not** whole home) |
| `scan.maxDepth` | Max directory depth for large-item scan (default `4`) |
| `scan.cacheMinBytes` / `cacheMinAgeDays` | Cache size + staleness gates |
| `excludePaths` | Directories **never** entered (default includes Documents, Desktop, media) |
| `whitelist` | Paths you chose to keep (also written by `keep`) |
| `scan.workers` | Thread pool size (`0` = auto) |

## Usage

### CLI

```bash
# Scan (prints results + saves findings.json in the project dir)
python -m rm_junk scan

# Preview without saving
python -m rm_junk scan --dry-run

# Verbose progress details
python -m rm_junk scan --debug

# List / delete / whitelist
python -m rm_junk list
python -m rm_junk delete <id>
python -m rm_junk keep <id>

# Paths
python -m rm_junk paths
```

### Menu bar (always on)

```bash
python -m rm_junk menubar
```

The **rm-junk** icon stays in the menu bar even with 0 findings.

| Menu | Action |
|------|--------|
| **Scan / Rerun** | Run scanners again |
| Status line | Live progress bar (same style as the terminal) |
| Findings | Each path with **Delete (Trash)** / **Keep (whitelist)** |
| Quit | Exit the menu bar app |

While scanning, the menu bar title shows a short progress percent/phase (e.g. `42% Caches`), and the status row shows the full bar.

## macOS permissions

- Many cache/orphan paths under `~/Library` work without special grants.
- Privacy-sensitive areas (Mail, Messages, Safari, …) are **skipped** by design.
- Full Disk Access helps complete large-file inventories under Library.
- Permission errors are skipped; the scan does not crash.

## Safety

- Hard denylist: `/System`, `/usr`, `/Applications`, … and this project directory
- Prefer **Trash** (`send2trash`) over permanent delete
- No automatic deletions

## Development

```bash
pytest
```

## Project notes

Local design hub: `context.md` (gitignored). Do not push feature branches until asked.
