# rm-junk (terminal)

macOS **command-line** junk finder: leftover caches, orphaned app data, old installers, and large folders — with **manual approval** before anything is removed.

This branch is the **standalone terminal app**. No menu bar, no GUI. A native Mac app plan lives in [`docs/mac-app-plan.md`](docs/mac-app-plan.md).

Nothing is deleted automatically.

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

After install you can use either:

```bash
python -m rm_junk …
# or
rm-junk …
```

## Quick start

```bash
# 1. Create local settings (once)
rm-junk init

# 2. Scan (progress bars in the terminal)
rm-junk scan --dry-run          # preview only
rm-junk scan                    # save pending findings

# 3. Review & act
rm-junk list
rm-junk delete <id>             # move to Trash (confirms first)
rm-junk keep <id>               # whitelist — never flag again
```

## Commands

| Command | Description |
|---------|-------------|
| `init` | Create `settings.json` from the example if missing |
| `scan` | Run scanners; print findings; optionally save queue |
| `list` | Show pending findings from the last scan |
| `delete <id>` | Trash one finding (prompt unless `-y`) |
| `keep <id>` | Add path to whitelist and drop from pending |
| `paths` | Print where settings/findings live |

### `scan` flags

| Flag | Meaning |
|------|---------|
| `--dry-run` | Print results; do **not** write `findings.json` |
| `--debug` | Verbose phase logs + current path names on the bar |
| `--no-progress` | No progress bar |
| `--queue-only` | Only keep findings at/above `minConfidenceForQueue` |
| `--config PATH` | Use a specific settings file |

## Config & data files

By default these sit in the **project directory** (this repo):

| File | Purpose | Git |
|------|---------|-----|
| `settings.json` | Your preferences | ignored |
| `findings.json` | Pending scan results | ignored |
| `settings.example.json` | Documented defaults | tracked |

Override the project root with:

```bash
export RM_JUNK_HOME=~/.config/rm-junk
rm-junk init
```

### Important settings

| Key | Default idea |
|-----|----------------|
| `scan.largeFileRoots` | `~/Library`, Docker/VM paths — **not** whole home |
| `scan.largeFileMinBytes` | 1 GB |
| `scan.maxDepth` | 4 |
| `scan.cacheMinBytes` / `cacheMinAgeDays` | Size + staleness gates for caches |
| `excludePaths` | Never enter (Documents, Desktop, media by default) |
| `whitelist` | Kept paths (also filled by `keep`) |
| `scan.workers` | `0` = auto thread count |
| `deletion.moveToTrash` | Prefer Trash over permanent delete |

## What gets scanned

1. **Caches** — `~/Library/Caches`, container caches, optional Homebrew / Xcode DerivedData  
2. **Leftovers** — dead LaunchAgents, orphaned saved state / prefs (conservative)  
3. **Installers** — old large `.dmg` / `.pkg` / `.zip` in Downloads (shallow)  
4. **Large files/folders** — under configured roots only  

Privacy-sensitive Library areas (Mail, Messages, Safari, …) are skipped. System paths are hard-denied. This project directory is never suggested for deletion.
