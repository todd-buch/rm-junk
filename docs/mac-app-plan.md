# Plan: Native-feeling macOS app (menu bar)

This document plans the **next product slice** after the terminal CLI (`terminal/cli-v1`). Goal: an always-on menu bar utility that does **not** require a terminal window.

Difficulty overall: **moderate** (a few days for a solid v1; longer if notarized distribution).

---

## Goals

| Goal | Notes |
|------|--------|
| Always in menu bar | No Terminal.app dependency |
| Launch at login | Optional setting |
| Scan / Rerun from menu | Same scanners as CLI |
| Progress UI | Same phase bars as terminal (title + status line) |
| Review findings | Delete (Trash) / Keep (whitelist) |
| Full Disk Access | Granted once to **rm-junk.app**, not Terminal |
| Reuse CLI core | Scanners, config, path policy, findings store stay shared |

Non-goals for app v1: Mac App Store, full windowed CleanMyMac clone, Windows/Linux.

---

## Difficulty breakdown

| Work item | Effort | Notes |
|-----------|--------|--------|
| Re-add menu bar module (`rumps` or PyObjC) | Small | We already prototyped this; restore on an app branch |
| Progress → menu bar | Small | `CallbackProgress`-style bridge (callback + main-thread refresh) |
| Package as `.app` | Medium | py2app / Briefcase / PyInstaller |
| Login item | Small–medium | `SMAppService` / LaunchAgent / login-items helper |
| Code signing | Medium | Apple Developer ID (~$99/year) |
| Notarization | Medium | Required for Gatekeeper on other Macs |
| Hardened runtime / entitlements | Medium | Full Disk Access still user-granted in System Settings |
| Polish (icon, about, preferences UI) | Medium | Can ship with file-based settings first |

**Realistic path:** reusable Python core + **py2app** + **rumps** menu bar → signed `.app` in ~1–2 focused weeks for a personal/local build; add notarization when sharing outside your machine.

---

## Recommended architecture

```
┌─────────────────────────────────────────────┐
│  rm-junk.app  (packaged Python)             │
│  ┌───────────────────────────────────────┐  │
│  │  Menu bar (rumps / AppKit)            │  │
│  │   - always visible                    │  │
│  │   - Scan / Rerun                      │  │
│  │   - progress status                   │  │
│  │   - findings → Delete / Keep          │  │
│  └───────────────┬───────────────────────┘  │
│                  │                          │
│  ┌───────────────▼───────────────────────┐  │
│  │  Shared library (current package)     │  │
│  │  config · scanners · path_policy ·    │  │
│  │  finding_store · deletion · progress  │  │
│  └───────────────────────────────────────┘  │
│                  │                          │
│  Data: ~/Library/Application Support/      │
│        rm-junk/{settings,findings}.json    │
└─────────────────────────────────────────────┘

CLI remains:  python -m rm_junk / rm-junk
  (optional same codebase, different entrypoint)
```

**Data location for the app:** prefer  
`~/Library/Application Support/rm-junk/`  
so the app is not tied to the git checkout. CLI can keep `RM_JUNK_HOME` / project-dir default; document both.

---

## Packaging options (pick one)

### 1. py2app (good default for rumps)

- Mature for menu bar + PyObjC apps  
- `setup.py` / `py2app` alias builds for dev, deploy builds for `.app`  
- **Pros:** Fits rumps well  
- **Cons:** Setup can be fiddly; fat binaries / arm64+x86_64 need care  

### 2. BeeWare Briefcase

- Modern packaging, generates Xcode project  
- **Pros:** Cleaner long-term  
- **Cons:** Slightly more structure; rumps integration less “classic” than py2app  

### 3. PyInstaller

- Single-folder or onedir `.app`  
- **Pros:** Familiar  
- **Cons:** Menu bar / arg-less GUI mode and signing need extra glue  

### 4. Rewrite UI in Swift, keep Python scanners

- SwiftUI menu bar + Python via subprocess or PyO3  
- **Pros:** Best native feel  
- **Cons:** Highest cost; only if packaging Python becomes painful  

**Recommendation:** **py2app + rumps** for app v1, reuse existing scanners.

---

## Implementation phases

### Phase A — App branch scaffold (0.5–1 day)

1. Branch from `terminal/cli-v1` (or merge terminal into `develop` first).  
2. Restore menu bar entrypoint (`rm-junk menubar` or app-only main).  
3. Optional dep: `rumps` under `.[app]` extra, not required for pure CLI.  
4. Application Support paths when running as `.app` (`sys.frozen` / bundle id).  

### Phase B — Menu UX parity (1 day)

1. Always-on icon (`rm-junk` / `rm-junk · N`).  
2. Scan / Rerun on background thread.  
3. Progress: short title + full bar status line (reuse terminal bar formatting).  
4. Findings list: Delete / Keep.  
5. Disable actions while scanning.  

### Phase C — Package `.app` (1–2 days)

1. `py2app` recipe: no console, LSUIElement=1 (agent app, no Dock icon).  
2. Bundle icon (`.icns`).  
3. Local run: open `dist/rm-junk.app`.  
4. Fix resource paths for `settings.example.json`.  

### Phase D — Login & permissions (0.5–1 day)

1. “Open at login” (app setting → SMAppService or LaunchAgent).  
2. README: grant **Full Disk Access** to rm-junk.app.  
3. First-run note if scan looks empty.  

### Phase E — Sign & notarize (when distributing)

1. Apple Developer Program.  
2. Developer ID Application certificate.  
3. `codesign --options runtime` + notarize + staple.  
4. Zip/DMG for distribution.  

Skip E for personal use if Gatekeeper allows right-click Open once.

---

## Key technical details

### Agent app (menu bar only)

Info.plist:

```xml
<key>LSUIElement</key>
<true/>
```

No Dock icon; only menu bar.

### Threading

- Scanners run off the main thread.  
- UI updates (title, menu titles) on main thread (`rumps.Timer` poll or AppKit performSelector).  

### Full Disk Access

- Packaged app has a stable code identity → user grants FDA to that app.  
- Terminal-only CLI grants FDA to Terminal/iTerm instead (worse UX).  

### Shared code rule

- **No scan logic in the menu bar module** — only UI + calls into `rm_junk.scanners` / `FindingStore` / `deletion`.  
- CLI and app stay in lockstep.

---

## Suggested branch / PR layout

| Branch | Deliverable |
|--------|-------------|
| `terminal/cli-v1` | Done: CLI only |
| `feature/app-menubar` | Menu bar UI + `.[app]` deps |
| `feature/app-packaging` | py2app / Briefcase recipe |
| `feature/app-login-fda-docs` | Login item + permissions docs |
| `feature/app-signing` | Signing/notarization scripts (optional) |

---

## Success criteria (app v1)

- [ ] Double-click `.app` → menu bar icon, no Terminal  
- [ ] Scan shows progress similar to CLI  
- [ ] Findings review without CLI  
- [ ] Survives log out/in when “open at login” enabled  
- [ ] FDA documented and works when granted  
- [ ] CLI still installable without rumps (`pip install .` without app extra)

---

## Open decisions

1. **Data dir:** Application Support only vs also support project-local via env.  
2. **Dock:** pure agent (`LSUIElement`) vs optional Dock icon.  
3. **Preferences:** edit JSON only vs small settings window.  
4. **Auto-scan interval:** off by default; optional timer if manual approval remains required.  
