# Red-Team Report C1 — Anti-Cheat & Launcher Coverage (`v1.2.0-rc.3`)

**Role:** Independent Anti-Cheat & Launcher Coverage Red-Team Auditor (C1 — fresh eyes)  
**Date:** 2026-11-24  
**Scope:** `protected_games.json`, `catalog.py`, `guard.py`, `lifecycle.py`, `processes.py`, `watcher.py`, `capture/*`, `hotkeys/*`, `epic.py`, `ea.py`, `steam.py`, `xbox.py`, `riot.py`, `app.py`

## Round 1 Findings

### `[HIGH] C1-01` — EA SPORTS FC missing Epic Games Store detection & incomplete EA/Xbox/Steam/title coverage
- **Evidence:** `gamehub/core/protection/protected_games.json` had `"epic_app_names": []` for `ea_fc`, `"ea_ids"` lacked `fc-24`/`fc-25`/`fc-26`/`fc-27` (real host DB showed `('FC 26', 'ea', 'auto')`), Steam lacked FC 25 Showcase (`3103970`), Xbox lacked `ElectronicArts.EASPORTSFC`, `game_exes` lacked trial/showcase variants, and `EpicDetector._pick_exe_in_dir()` scanned only top-level `install_dir` (missing nested Unreal/EA executables).
- **Fix Applied:** Populated `epic_app_names`, `ea_ids`, `steam_app_ids`, `xbox_package_prefixes`, `game_exes`, and conservative `title_aliases` in `protected_games.json`; added normalized title matching in `ProtectedGamesCatalog.match_game(..., game_name=...)` wired through `app.py`, `lifecycle.py`, `watcher.py`, and `mods/engine.py`; added bounded depth-3 fallback executable discovery in `EpicDetector`.
- **Verification:** `tests/test_security_rc3.py::test_ea_sports_fc_detected_across_epic_steam_ea_and_xbox` and `test_epic_detector_discovers_nested_game_executables` PASS.

### `[HIGH] C1-02` — 2026 Anti-Cheat Catalog Gaps
- **Evidence:** Major 2025/2026 kernel/online anti-cheat PC titles were missing or lacked multi-launcher IDs: **Grand Theft Auto V / GTA V Enhanced** (BattlEye — present on test host), **Marvel Rivals** (NetEase/ACE), **Wuthering Waves** (ACE), **Roblox** (Hyperion), **Dota 2** (VAC), Battlefield 6 (`bf6.exe`/`battlefield6.exe`/Steam `2807960`/`eaanticheat.gameservicelauncher.exe`), Call of Duty Battle.net IDs, and Epic/EA/Xbox IDs + `title_aliases` across Apex Legends, Rainbow Six Siege, Destiny 2, Dead by Daylight, Fall Guys, THE FINALS, Delta Force, and HoYoverse titles.
- **Fix Applied:** Updated `protected_games.json` with all 2026 titles and multi-launcher IDs; added `gta5_enhanced.exe`, `gta5_be.exe`, `gta5_enhanced_be.exe`, `sguard64.exe`, `sguardsvc64.exe` to `DEFAULT_NEVER_OPEN_EXES` in `processes.py`.
- **Verification:** `tests/test_security_rc3.py::test_2026_anti_cheat_catalog_entries_and_multi_launcher_coverage` PASS (including negative check confirming single-player games do not falsely match).

### `[LOW] C1-03` — `ProtectionGuard.unignore_pid()` did not invalidate fast PID-diff cache
- **Evidence:** `gamehub/core/protection/guard.py` retained `_last_pid_sig` after `unignore_pid(pid)` during Settings "Test protection", potentially deferring full scan until the next PID change or 2 s audit.
- **Fix Applied:** Reset `self._last_pid_sig = None` inside `unignore_pid()`.
- **Verification:** Code inspection + `tests/test_zero_presence_guard.py` + `tests/test_performance_regressions.py` PASS.

## Speed Changes Security Audit
- **`K32EnumProcesses` fast PID-diff:** Uses public `kernel32.K32EnumProcesses` only (0 process handles opened, 0 new DLLs), captures `_last_pid_sig` strictly BEFORE `list_processes()` (race-free), falls back fail-closed to full `CreateToolhelp32Snapshot` on any error or buffer overflow, runs unconditional full audit every 2.0 s, and runs read-only SCM service checks every 240 ms.
- **Direct guard-thread `os._exit`:** Completely eliminates the UI-thread `QueuedConnection` bottleneck; proven `< 200 ms` even with a 5 s frozen Qt UI thread (`tests/test_performance_regressions.py`).
- **Startup order:** `ProtectionGuard.self_check()` remains strictly first (before migration, `SingleInstance`, window creation, or DB writes); `protection_guard.start()` now starts even earlier (before `window.show()`); startup TOCTOU `check_once()` remains strictly before `mods_engine.recover_incomplete()`, hotkeys, and `watcher.start()`.
- **Process/Handle/Capture/Hotkey hygiene:** Zero `OpenProcess` outside `processes.py` (restricted to `_QUERY_LIMITED_INFORMATION = 0x1000` on verified Full-mode single-player targets only), zero `psutil`, zero hooks/injection/memory reads, `WindowProbe` gated on `tracker.active_pids()`, `CaptureScheduler` paused when idle or in Strict mode.

## Round 2 Verdict: **PASS — 0 Open Findings**
