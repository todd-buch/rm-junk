# Plan: macOS menu bar app (rm-junk)

Product plan for the **packaged Mac app** after the terminal CLI (`terminal/cli-v1`).  
Terminal remains a separate, optional developer/power-user interface. End users get a **`.app`**, typically shipped inside a **`.dmg`**.

Difficulty: **moderate–high** for polished circular status UI + dual process (settings vs agent); core scanning is already done.

---

## 1. Product model (locked in)

### 1.1 Mental model

| User action | What actually happens |
|-------------|------------------------|
| Install from **DMG** → drag **rm-junk.app** to Applications | Normal Mac install |
| First open / “Open at Login” | Starts a **background agent** (menu bar only) |
| Day to day | Agent is **idle and silent** (no scan, ~0% CPU). Menu bar shows a **circle with a checkmark** when there is nothing to review |
| Click menu bar icon | Opens **quick menu** (scan, progress, review list) |
| Open app to change settings | Opens a **Settings window**; **Dock shows the app** only while that UI is frontmost / open |
| **⌘Q** while in Settings | Closes the Settings UI / “quits” the foreground app experience — **menu bar agent keeps running** |
| Explicit “Quit rm-junk completely” (menu item) | Stops agent + removes menu bar icon (rare) |
| Automatic scan | Default **once per week** (configurable); no auto-delete — only builds a review queue |
| Manual scan | “Scan now” from the quick menu |

**Important:** Something tiny must stay alive for a permanent menu bar icon. That is **not** Terminal and **not** a Dock “open app.” It is a standard **menu bar agent** (like many Mac utilities): idle most of the time, work only on schedule or when the user asks.

### 1.2 Two surfaces, one product

```
┌──────────────────────────────────────────────────────────────┐
│  rm-junk (distributed as .app, often inside .dmg)            │
│                                                              │
│  ┌─────────────────────┐     ┌────────────────────────────┐  │
│  │  AGENT (always-on)  │     │  SETTINGS UI (on demand)   │  │
│  │  LSUIElement /      │     │  Opens when user wants     │  │
│  │  menu bar only      │◄────│  config; ⌘Q closes this    │  │
│  │  no Dock when idle  │     │  WITHOUT killing agent     │  │
│  └─────────┬───────────┘     └────────────────────────────┘  │
│            │                                                 │
│            ▼                                                 │
│  Shared core: scanners · config · findings · deletion        │
│  Data: ~/Library/Application Support/rm-junk/                │
└──────────────────────────────────────────────────────────────┘
```

Implementation options (either is fine for v1):

1. **Single process:** agent always running; Settings is a window on the same process. ⌘Q is overridden / remapped so it **only closes the window**, not `NSApplication.terminate`. A menu item “Quit rm-junk” fully exits.  
2. **Two processes:** helper agent (menu bar) + main app (settings). Quitting the main app leaves the helper. Slightly cleaner UX separation; more packaging work.

**Recommendation:** start with **(1) single process**, custom ⌘Q / window close behavior — simpler packaging.

### 1.3 Dock / “open” indicator

| State | Dock | Menu bar |
|-------|------|----------|
| Agent idle / scanning / has findings | **Hidden** (`LSUIElement` / agent) | Visible (✓ or progress or count) |
| User opened Settings | **May show** while Settings is open (optional: temporary `activationPolicy`) | Still visible |
| User ⌘Q / closes Settings | Dock icon **goes away** again | Agent **still** visible |

Goal: user does **not** feel like “rm-junk is an open app” 24/7 — only when they opened Settings.

---

## 2. Distribution: `.app` vs `.dmg`

| Format | What it is |
|--------|------------|
| **`.app`** | The actual application bundle (what runs). Users put it in `/Applications`. |
| **`.dmg`** | A **disk image installer wrapper** (optional but standard for sharing). Open DMG → drag `.app` to Applications → eject. |
| **`.zip`** | Simpler alternative to DMG; Gatekeeper still applies. |

**Shipping flow for sharing:**

1. Build **rm-junk.app**  
2. Sign with Developer ID  
3. Notarize with Apple  
4. Put the signed app in a **rm-junk.dmg** (or zip)  
5. User downloads DMG → installs app → grants Full Disk Access if prompted/docs say so  

There is no special “`.dng`” format for Mac apps; people mean **`.dmg`** (disk image) containing a **`.app`**.

CLI users can keep using `pip install` / `rm-junk` from the terminal branch; the DMG is for non-terminal users.

---

## 3. Menu bar icon states

Custom template / drawn icons (not plain text titles).

### 3.1 Idle — nothing to review

- **Circle outline + checkmark** in the center (or filled soft circle + ✓).  
- Means: last completed scan found **0** pending items (or never scanned but healthy idle — product choice: show ✓ only after a successful scan with zero findings; otherwise a neutral empty circle).  
- **Default after clean scan:** checkmark circle.

### 3.2 Has findings for review

- **Circle** with **count** of pending review items in the center (e.g. `3`).  
- Optional mild attention styling if count &gt; 0.  
- Count updates when user deletes/keeps items.

### 3.3 Scan in progress — segmented circular progress

Scan phases (align with CLI scanners), e.g.:

1. Caches  
2. Leftovers  
3. Installers  
4. Large files  

**Icon behavior during scan:**

- Outer ring is **divided into N arcs** (one segment per phase).  
- As phase *i* runs, **only segment *i* fills** (circular progress within that slice).  
- When phase *i* completes, its segment stays **full**, then phase *i+1* begins filling.  
- **Center:** running **count of findings found so far** (updates live as scanners report).  
- Long scans stay understandable: user sees which “slice” of work is active and how much of the overall pipeline is done.

```
  Idle clean          Scanning (phase 2 of 4)       Needs review
  ┌─────┐               ┌─────┐                     ┌─────┐
  │  ✓  │               │  2  │  ← count so far     │  5  │
  │ ○○○ │               │ ◔○○ │  ← seg1 done,       │ ○○○ │
  └─────┘               └─────┘    seg2 filling     └─────┘
```

Implementation note: draw with **AppKit** (`NSImage` / Core Graphics) or pre-render frames; **rumps** alone is weak for custom animated rings — expect **PyObjC** drawing or a small Swift status-item helper. This is the main UI cost beyond packaging.

### 3.4 Error / blocked

- Optional: circle + `!` if scan failed or FDA missing (tooltip / menu explains).

---

## 4. Quick menu (click menu bar)

Clicking the status item opens a **quick menu** (and/or a compact popover — menu first for v1).

### 4.1 Contents

1. **Header / status**  
   - Idle: “Up to date” / “Last scan: …”  
   - Scanning: overall summary  

2. **Phase progress bars** (same spirit as terminal CLI)  
   - One linear bar (or labeled row) **per scan phase**  
   - Shows % / done / current path snippet while that phase is active  
   - Mirrors the segmented ring so terminal users and menu users share mental model  

3. **Scan now** (disabled while a scan is running)  

4. **Findings list** (pending review)  
   Each item shows size, category, path (truncated), reason.  
   Per item actions:  
   | Action | Behavior |
   |--------|----------|
   | **Confirm delete** | Move to Trash (default); requires confirmation if settings say so |
   | **Always keep** | Add to **whitelist**; never flag again |
   | **Ignore for this scan** | Drop from **current** pending queue only; may reappear on a later scan |

5. **Open Settings…** → Settings window (Dock may appear)  

6. **Quit rm-junk completely** → stops agent (explicit; not ⌘Q from Settings)

### 4.2 Review action semantics

| Action | Persist | Next weekly scan |
|--------|---------|------------------|
| Confirm delete | File gone (Trash); finding marked deleted | Won’t appear unless recreated |
| Always keep | Path/rule in `whitelist` | Suppressed |
| Ignore for this scan | Pending list only (or short-lived “snooze”) | **Can appear again** |

“Ignore for this scan” is **not** whitelist — important for false-ish positives the user isn’t ready to decide on.

---

## 5. Scheduling (built into the app)

| Setting | Default | Notes |
|---------|---------|--------|
| Auto-scan enabled | **On** | |
| Interval | **Once per week** | e.g. 7×24h since last success, or a chosen weekday/time |
| Manual scan | Always available from quick menu | |
| Auto-delete | **Never** | Only queue for review |

Implementation:

- In-agent timer / calendar check while agent is running.  
- **Open at Login** so agent (and schedule) survive reboot — configured from Settings, no Terminal.  
- Optional later: system `LaunchAgent` installed by the app for resilience; not required for v1 if Open at Login + in-process timer is solid.

---

## 6. Settings window

Opened via quick menu “Open Settings…” or double-clicking the app in Applications when agent already running (single-instance → show Settings).

**⌘Q / red close button:** dismiss Settings only; **agent continues**.

Suggested settings (v1):

- Auto-scan on/off + interval (default weekly)  
- Large-file threshold / roots (or “advanced”)  
- Exclude paths  
- Open at login  
- Move to Trash vs permanent (default Trash)  
- Link to Full Disk Access instructions  

Data: `~/Library/Application Support/rm-junk/settings.json` (+ `findings.json`).

---

## 7. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  rm-junk.app                                                │
│                                                             │
│  StatusItemController                                       │
│    · icon renderer (✓ / count / segmented ring)             │
│    · quick menu + phase bars + review actions               │
│                                                             │
│  ScanCoordinator                                            │
│    · manual + weekly schedule                               │
│    · drives scanners on background queue                    │
│    · feeds progress → icon + menu bars                      │
│                                                             │
│  SettingsWindowController                                   │
│    · ⌘Q closes window, does not terminate agent             │
│                                                             │
│  Shared Python (or later mixed) core                        │
│    · same scanners / path_policy / finding_store / delete   │
└─────────────────────────────────────────────────────────────┘
```

**Reuse rule:** no second implementation of scan heuristics — call the existing package.

**UI stack recommendation:**

| Layer | Choice | Why |
|-------|--------|-----|
| Status item + custom circular icon | **PyObjC / AppKit** (or Swift) | rumps too limited for segmented ring |
| Quick menu | AppKit `NSMenu` or small `NSPopover` | Progress rows need more than plain rumps menus |
| Settings | SwiftUI/AppKit window or simple form | |
| Packaging | py2app / Briefcase / eventual native wrapper | Ship `.app` + `.dmg` |

Pure **rumps** is fine for a prototype menu; **not** enough alone for the segmented circular status icon. Budget real AppKit drawing time.

---

## 8. Implementation phases

### Phase A — Agent shell + lifecycle

- [ ] Menu bar agent, no Dock when idle  
- [ ] Settings window; ⌘Q / close ≠ quit agent  
- [ ] Explicit “Quit completely”  
- [ ] Application Support paths  
- [ ] Open at Login toggle  

### Phase B — Icons + scan progress

- [ ] Idle ✓ circle  
- [ ] Count-in-circle for pending findings  
- [ ] Segmented circular progress (N phases) + live center count  
- [ ] Wire scanner phase events from shared progress API  

### Phase C — Quick menu review

- [ ] Phase linear progress rows during scan  
- [ ] Findings list  
- [ ] Confirm delete / Always keep / Ignore for this scan  
- [ ] Scan now  

### Phase D — Schedule

- [ ] Default weekly auto-scan  
- [ ] Configurable interval  
- [ ] Last-run / next-run display in Settings or menu  

### Phase E — Package & share

- [ ] Build **rm-junk.app**  
- [ ] Create **rm-junk.dmg** (Applications symlink + background optional)  
- [ ] Code sign + notarize for Gatekeeper  
- [ ] README: FDA, first launch, Open at Login  

---

## 9. Difficulty (updated)

| Work | Effort |
|------|--------|
| Agent + Settings ⌘Q semantics | Medium |
| Segmented circular menu-bar icon | **Medium–high** (custom drawing + animation) |
| Quick menu + three review actions | Medium |
| Weekly scheduler + login item | Small–medium |
| `.app` + `.dmg` packaging | Medium |
| Sign / notarize | Medium (Apple Developer Program) |
| Reuse scanners | Already done (CLI) |

**Rough:** usable internal build in about a week of focused work; polish + notarized DMG longer.

---

## 10. Success criteria

- [ ] Installed from DMG; no Terminal required for normal use  
- [ ] Menu bar always shows ✓ when clean / count when review needed  
- [ ] During scan, segmented ring fills phase-by-phase; center count updates  
- [ ] Quick menu shows phase bars + review actions (delete / always keep / ignore this scan)  
- [ ] ⌘Q from Settings does **not** kill the agent  
- [ ] Weekly auto-scan by default; manual scan from menu  
- [ ] Never auto-deletes  
- [ ] CLI package still works without the GUI stack  

---

## 11. Open decisions

1. **Idle before first scan:** neutral circle vs ✓ vs “—”  
2. **Popover vs dense `NSMenu`** for progress + long finding lists  
3. **Ignore this scan** storage: memory-only vs findings status `ignored` until next scan clears  
4. **Single process vs agent helper** for Settings ⌘Q  
5. **Swift status item + Python scanners** if AppKit-from-Python drawing is too painful  

---

## 12. Relation to terminal branch

| Branch / artifact | Role |
|-------------------|------|
| `terminal/cli-v1` | Standalone CLI; no menu bar |
| Future `feature/app-*` | Implements this document |
| Shared | Scanners, policy, findings model, delete/whitelist |

Do not block CLI on app packaging; app consumes the same core.
