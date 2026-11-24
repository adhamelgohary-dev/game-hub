# Review Council — M14 (Part 1: Zero-Presence Anti-Cheat Protocol)

**Date:** 2026-11-24  
**Test verification:** `197 passed in 16.59s`, `ruff check .` clean (0 errors).

## Advocate
- Implemented all 7 technical layers plus Step C UI:
  - **Layer 1:** Expanded AST/static code-scan test in `tests/test_packaging.py` fails on `SendInput`, `keybd_event`, `mouse_event`, `SetWindowsHookEx`, `ReadProcessMemory`/`WriteProcessMemory`/`CreateRemoteThread`, `OpenProcess` outside `processes.py`, admin manifests, or `upx=True`.
  - **Layer 2:** Fail-closed startup self-check (`ProtectedGamesCatalog.load(..., strict_load=True)` + `ProtectionGuard.self_check()`) executes **before** `SingleInstance.claim_or_activate()` and before creating any window or DB writes. All 4 event orders + read-only SCM service checks (`EasyAntiCheat_EOS`, `EasyAntiCheat`, `BEService`, `vgc`) + 1-second watchdog heartbeat are tested.
  - **Layer 3:** Fast 300 ms passive Toolhelp32 `ProtectionGuard` detects earliest `launcher_stage_exes` (`FortniteBootstrapper.exe`, `FortniteLauncher.exe`, `VALORANT.exe`, `EAAntiCheat.GameServiceLauncher.exe`), and emergency teardown skips waiting on slow background library scans (`wait=False`) so exit completes in milliseconds.
  - **Layer 4:** Riot Client is locked ALWAYS strict; Epic/EA/Battle.net/Ubisoft/Steam remain allowed by default so story games work in Full mode, with opt-in per-launcher strict toggles and confirmation-guarded per-game overrides.
  - **Layer 5:** Official URI & detached Riot Client launching with mandatory immediate exit + pending note for protected games.
  - **Layer 7 & Step C:** Real Windows dummy-process test lab verifies 6 renamed dummy processes (< 1 s latency) and powers Settings → **Protected games** **"Test protection"** button without tripping the live guard.

## Critic
- Checked race safety of `"Test protection"`: `_scan_lock` serializes spawning the dummy `FortniteLauncher.exe` and registering its PID in `live_guard._ignored_pids`, preventing false closure while keeping real protection active for every other PID.
- Checked real-PC validation: `ProtectionGuard` live-detected `fc26.exe` on the test PC on first run, confirming real-world enforcement.

## Neutral Analyst
- Schema v5 → v6 migration preserves all foreign keys, creates `gamehub.db-v5.bak`, and passes `PRAGMA foreign_key_check`.
- Full EN/AR catalog parity and mnemonic-free UI tests remain 100% green.

## Judge
**Verdict: APPROVE.** Tag `m14` and proceed immediately to **M15 (Part 2 — Find All Games)**.
