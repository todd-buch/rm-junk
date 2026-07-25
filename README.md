# rm-junk (CLI)

macOS **command-line** junk finder: leftover caches, orphaned app data, old installers, and large folders — with **manual approval** before anything is removed.

Nothing is deleted automatically. There is no menu-bar app on this branch.

## Requirements

- macOS
- Python 3.11+

## Install

```bash
cd rm-junk
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

```bash
python -m rm_junk …
# or
rm-junk …
```

## Quick start

```bash
rm-junk init
rm-junk scan --dry-run             # preview
rm-junk scan                       # save findings
rm-junk list
rm-junk delete <id> [id...]        # Trash specific finding(s) (confirms)
rm-junk delete --all               # Trash all remaining pending findings
rm-junk keep <id> [id...]          # Whitelist specific finding(s)
rm-junk keep --all                 # Whitelist all remaining pending findings
```

## Scan performance

Scans use a **thread pool** (default roughly `cpu × 8`, between 16 and 64 workers) because work is mostly disk I/O (`stat` / `scandir` release the GIL).

| Setting | Meaning |
|---------|---------|
| `scan.workers` | Thread count (`0` = auto). Raise (e.g. `48`) on fast SSDs if you want more concurrency. |

Progress bars show **active** jobs and **ETA** that accounts for:

- Parallel wall-clock (remaining ÷ workers × time-per-item)
- Long-tail folders already running longer than the average (ETA rises instead of stuck at “16s”)

```bash
rm-junk scan --debug            # verbose path logs
rm-junk scan --no-progress      # quiet
```

## Commands

| Command | Description |
|---------|-------------|
| `init` | Create `settings.json` if missing |
| `scan` | Run scanners; print + optionally save queue |
| `list` | Pending findings |
| `delete <ids...> / --all` | Trash one or more findings by ID, or `--all` remaining pending (`-y` skips confirm) |
| `keep <ids...> / --all` | Whitelist one or more findings by ID, or `--all` remaining pending |
| `paths` | Show config/data locations |

## Config

Project-local by default (or `RM_JUNK_HOME`):

| File | Purpose |
|------|---------|
| `settings.json` | Your config (gitignored) |
| `findings.json` | Pending results (gitignored) |
| `settings.example.json` | Defaults |

Large-file scan defaults to **Library / Docker / VMs** — not whole home.

| Key | Notes |
|-----|--------|
| `scan.largeFileMinGB` | Minimum size in **gigabytes** (e.g. `50`). Preferred over bytes. |
| `scan.largeFileRoots` | Where to look for large items |
| `excludePaths` | Never enter these directories |

## Safety

- Explicit delete only
- Prefer **Trash** (`send2trash`)
- Hard denylist + exclude paths + whitelist
- Skips privacy-sensitive Library areas

## Development

```bash
pytest
```

## Branch

**`feature/cli-perf`** — CLI only: faster parallel scans, better ETA, clearer terminal UI.
