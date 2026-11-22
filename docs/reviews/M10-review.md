# Milestone M10 Review Council — Game-Aware Lifecycle, Protection & Borderless WGC (Part C)

**Date:** 2026-11-23  
**Scope:** Bundled updatable `protected_games.json` + `ProtectedGamesCatalog` (with local override), Schema v5 migration (`protection_mode`, `exit_after_launch`, `pending_notes`), passive basename-only Toolhelp detection with zero `OpenProcess` handles on protected/strict games, `LifecycleCoordinator` (Play-through, Strict mode, Forgetful-case guard), `GlobalHotkeys.suspend/resume`, `WindowsNotifier`, per-game GamePage & Settings controls, Arabic catalog parity, and borderless WGC (`draw_border=False`) with cached fallback.

---

## Round 1

### Advocate
- `gamehub/core/protection/protected_games.json` stores 34 major anti-cheat titles (Valorant, LoL, Fortnite, Apex Legends, Call of Duty, Rainbow Six Siege, PUBG, Rust, EA SPORTS FC, Battlefield, Helldivers 2, Elden Ring, Halo MCC/Infinite, Sea of Thieves, Destiny 2, DayZ, Tarkov, Arma 3, Dead by Daylight, The Finals, Lost Ark, For Honor, Fall Guys, War Thunder, Genshin Impact, Honkai: Star Rail, ZZZ, Delta Force, Naraka, CS2, Deadlock, Overwatch 2, World of Warcraft) as pure updatable JSON bundled by PyInstaller and extendable via `%LOCALAPPDATA%\GameHub\protected_games_override.json`.
- `ProcessProbe.snapshot` is verified by unit tests to make **zero `inspect()` / `OpenProcess` / `psutil.Process` calls** for protected or Strict-mode basenames.
- Schema v4 → v5 migration backs up `gamehub.db-v4.bak`, cleans up legacy `app.start_with_windows`, and supports deferred Strict-mode notes (`pending_notes`) cleanly without breaking foreign keys or v1.0 history.
- `LifecycleCoordinator`, `LastTimeController`, and `NotesController` enforce Play-through minimize/restore/exit-after-play (`--play` and card checkbox), Strict-mode suspension (hotkeys unregistered, WGC paused, topmost cards suppressed, in-game mic blocked, optional exit-after-launch), and all three Forgetful-case behaviors (`exit_app` default, `strict_mode`, `ask_me`).
- `WgcCapture` requests `draw_border=False` on Windows builds >= 20348 with automatic cached fallback to `draw_border=None` for both synchronous and async worker rejections.

### Critic
1. **External protected game exit did not clear Strict mode:** When `protection.external_behavior` is `strict_mode` or `ask_me`, `SessionWatcher` removed exited protected games from `_announced_protected` without emitting an exit event to `LifecycleCoordinator.clear_external_protected(...)`, leaving hotkeys/capture suspended until app restart. **Fix required:** Add `ProtectedGameExited` event, publish it on exit from `SessionWatcher._emit_protected_detections`, subscribe it in `app.py`, and cover it in tests.
2. **Borderless fallback blocked if `on_closed` set `pending.expired`:** When a driver rejects `draw_border=False` asynchronously and also triggers `on_closed`, `pending.expired` could prevent the single fallback retry with `draw_border=None`. **Fix required:** Re-check `monotonic() < lease.expires_at and is_current(lease)` and clear `pending.expired` before running the fallback attempt.
3. **Live borderless visual check note:** On the locked/unfocused automated terminal desktop (`GetForegroundWindow() == 0`), DWM had no active compositor surface for live WGC frame capture; record this honestly and include live borderless capture verification in the owner's Part G checklist.

### Neutral Analyst
- Both code fixes are targeted and cleanly eliminate real runtime bugs.
- All 182 automated tests (including full Arabic AST `.tr()` parity, Schema v4→v5 migration, zero-`OpenProcess` proof, hotkey suspend/resume, lifecycle flows, and borderless sync/async fallback) and Ruff checks pass after applying the fixes.

### Judge — Round 1 Verdict: **APPROVE WITH CHANGES**
Required changes:
1. Emit and wire `ProtectedGameExited` so external Strict mode clears automatically when a protected game closes.
2. Reset `pending.expired` cleanly before the single `draw_border=None` fallback attempt when the lease is still current.

---

## Round 2 (Verification)

- **Sessions & Capture:** Implemented `ProtectedGameExited` event + watcher emission + `app.py` subscription + unit test, and fixed `WgcCapture._capture` fallback guard.
- **QA:** Confirmed full suite (`182 passed`) and Ruff (`All checks passed!`) pass cleanly.
- **Judge — Final Verdict:** **APPROVE**

Milestone M10 is approved. Tag `m10` as an internal plain git tag and proceed to Part E public-readiness audit & SignPath prep before pausing at Owner Gate 1 (UI mockups + `m0–m8` cleanup list).
