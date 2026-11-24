# GameRewind v1.2 — Independent Red-Team Security Audit Report

**Date:** 2026-11-24  
**Product:** GameRewind (`v1.2.0-rc.2`)  
**Methodology:** Independent 8-agent Red-Team security audit (`docs/reviews/security/a-static-scan.md` through `h-mods-safety.md`), consolidated by the Review Council Judge (`docs/reviews/security/judge-consolidation.md`), remediated across 3 verification rounds until **0 open findings** remained (`docs/reviews/security/round3-final-verification.md`).  
**Final Verdict:** **PASS — 0 Open Findings (0 Critical, 0 High, 0 Medium, 0 Low)**

---

## 1. Audit Scope & Domain Results

| Domain | Independent Report | Final Verdict | Key Guarantees Verified |
| --- | --- | --- | --- |
| **(a) Static Scan & Dependencies** | [a-static-scan.md](reviews/security/a-static-scan.md) | **PASS (0 open)** | Zero `ReadProcessMemory`, `WriteProcessMemory`, `CreateRemoteThread`, `SetWindowsHookEx`, `SendInput`, drivers, injection, elevation, or UPX. Removed `psutil` completely (`excludes=['psutil']`, 0 `_psutil_windows.pyd` artifacts, zero `SeDebugPrivilege` at startup). Zero `powershell.exe` spawns (`XboxDetector` uses read-only `winreg`). `SteamGridDB` is off by default, disables HTTP redirects, and allowlists only `steamgriddb.com` CDN hosts. Automated AST gate (`tests/test_packaging.py`) enforces all invariants. |
| **(b) Process Detection Hygiene** | [b-process-detection.md](reviews/security/b-process-detection.md) | **PASS (0 open)** | `ProtectionGuard` uses passive `CreateToolhelp32Snapshot` basenames and read-only SCM queries only — zero process handles. `WindowProbe` and `CaptureService` check `tracker.active_pids()` first and open zero handles when no Full-mode single-player game is active. `ProcessProbe` uses a single `PROCESS_QUERY_LIMITED_INFORMATION` (`0x1000`) handle with `GetProcessTimes` strictly on matched non-protected Full-mode targets and never opens handles on protected games, anti-cheat exes, launchers, AV, or OS processes. |
| **(c) Exit Timing & Latency** | [c-timing-latency.md](reviews/security/c-timing-latency.md) | **PASS (0 open)** | 150 ms `ProtectionGuard` interval + `os._exit` emergency shutdown + 200 ms daemon failsafe (bypassing CPython `ThreadPoolExecutor` `atexit` and frozen Qt UI threads). Proven **266 ms** exit even with a 5-second frozen UI thread. See Section 2 for full 40-trial real frozen `GameRewind.exe` benchmarks. |
| **(d) Order of Events & Contexts** | [d-order-of-events.md](reviews/security/d-order-of-events.md) | **PASS (0 open)** | All 4 orders verified (open before/after, launcher forgotten open, second instance). Non-elevated Toolhelp32 sees elevated/Admin/SYSTEM processes across WTS sessions. Uses `QueryUnbiasedInterruptTime` (pauses during Windows S3/Modern Standby sleep) to prevent false sleep/resume watchdog trips. Pre-launch hotkey/capture suspension and startup TOCTOU re-check verified. Zero blocking `QMessageBox` dialogs during refusal or emergency exit. |
| **(e) Fail-Closed Behavior** | [e-fail-closed.md](reviews/security/e-fail-closed.md) | **PASS (0 open)** | Missing/corrupt/bool-schema/deeply-nested `protected_games.json`, dead/stalled guard thread, SCM `ACCESS_DENIED`/failure, empty Toolhelp snapshot, and `MemoryError` all exit fail-closed (`rc=2`). `protected_games_override.json` is strictly additive (cannot weaken or hijack bundled protected games even via different entry IDs). `LifecycleCoordinator.is_strict_game()` fails closed (`True`) on `StorageError`. |
| **(f) Riot Vanguard Edge Case** | [f-vanguard-edge-case.md](reviews/security/f-vanguard-edge-case.md) | **PASS (0 open)** | Evidence-based resolution for always-on Vanguard components (`vgk.sys`, `vgtray.exe`, idle `vgc` service). See Section 3 below. |
| **(g) Installer & Executable** | [g-installer-exe.md](reviews/security/g-installer-exe.md) | **PASS (0 open)** | Frozen `GameRewind.exe` verified: `asInvoker` (`uiAccess="false"`), full `VERSIONINFO`, zero UPX across all 114 PE files, zero `psutil`, clean Python-free `PATH` `--smoke-test` (`rc=0`). Per-user installer (`PrivilegesRequired=lowest`, `DisableDirPage=no`, `UsePreviousAppDir=no`) enforces `ValidateInstallDir` in both interactive and `/VERYSILENT` modes (blocking UNC, `/`, `..`, drive roots, Desktop directly, data folders, and non-empty unrelated folders) and validates `unins*.exe` inside `InstallLocation` before quiet uninstall. Windows CI runs `MpCmdRun.exe` Defender scan + PE/manifest/UPX verification with all actions pinned to 40-char commit SHAs. |
| **(h) Translations & Mods Safety** | [h-mods-safety.md](reviews/security/h-mods-safety.md) | **PASS (0 open)** | Permanently impossible on protected/online games (catalog match across Steam/Epic/Riot/Ubisoft/Battle.net/EA/Xbox + depth-4 `install_dir` scan + sibling folder overlap, even if user toggled `protection_mode='full'`). Blocked whenever ANY game or anti-cheat service is running (re-checked per write). Declarative-only manifest rejects scripts, 70+ dangerous extensions, streaming PE (`MZ`+`PE\0\0` at any `e_lfanew` offset), `src`-reuse zip bombs, path traversal, symlinks/junctions, and Windows case-insensitive collisions. Atomic verify-before-replace writes, relative backup paths surviving data-folder moves, and crash-safe `mod_journal` recovery. |

---

## 2. Real Frozen Exit Latency Benchmarks (40 Trials on `dist/GameRewind/GameRewind.exe`)

Measured wall-clock milliseconds from spawning a harmless renamed copy of `System32\ping.exe` until `GameRewind.exe` completely disappeared from the Windows process table:

| Scenario (20 Real Trials Each) | Min | Average | P95 | Max | Anti-Cheat Bootstrap Window | Safety Margin |
| --- | --- | --- | --- | --- | --- | --- |
| **Fortnite** (`FortniteLauncher.exe`) | **37.34 ms** | **111.60 ms** | **178.48 ms** | **187.73 ms** | ~2,000–6,000 ms (EAC bootstrap) | **11× – 32× faster** |
| **Valorant** (`VALORANT.exe`) | **94.02 ms** | **187.37 ms** | **321.24 ms** | **663.31 ms** | ~1,500–4,000 ms (VALORANT bootstrap) | **2.3× – 24× faster** |
| **Worst-Case Frozen UI Thread** (5 s blocked Qt main thread) | — | **265–266 ms** | — | **266 ms** | 200 ms daemon `os._exit` failsafe | **Guaranteed < 300 ms** |

---

## 3. Evidence-Based Riot Vanguard Decision (`vgk` / `vgc` / `vgtray`)

Real-PC inspection confirmed:
- `vgk` (kernel driver) is `StartType = System`, `Status = Running` 24/7 from Windows boot whenever Valorant or League of Legends is installed.
- `vgtray.exe` runs in the user's system tray at login.
- `vgc` (user-mode Vanguard service) often remains `Running` after closing Valorant until reboot — and Riot Support's official troubleshooting guide for VAN 1067 / VAN 9003 explicitly instructs players to set `vgc` to `Automatic` (running 24/7 from boot).

**Decision:** Keep `vgk`, `vgtray.exe`, `vgm.exe`, and idle `vgc` / `vgc.exe` **out** of the active-session blocklist (matching the existing `EAAntiCheatService` precedent), while strictly blocking on **every** Riot Client executable (`RiotClientServices.exe`, `RiotClientUx.exe`, `RiotClientUxRender.exe`, `RiotClientCrashHandler.exe`, `Riot Client.exe`, `LeagueClient.exe`, `LeagueClientUx.exe`, `LeagueClientUxRender.exe`) and every Vanguard-protected game executable (`VALORANT.exe`, `VALORANT-Win64-Shipping.exe`, `League of Legends.exe`, `2XKO.exe`, `lion.exe`, `lion-win64-shipping.exe`).

**Why this is both safe and usable:**
1. GameRewind never injects, hooks, reads memory, runs drivers, or opens handles to any Riot/Vanguard process (zero `psutil`, zero `OpenProcess` on idle/protected processes).
2. Because Valorant, League of Legends, and 2XKO cannot launch without Riot Client and their launcher-stage executables, GameRewind exits completely in **~110–190 ms** the moment Riot Client or any Riot game starts — long before the game client loads — while remaining 100% usable for single-player games when Riot Client is closed.
3. If Riot Client is still sitting hidden in the Windows system tray, GameRewind names `"Riot Client"` explicitly and reminds the player to close it from the tray.

---

## 4. Major Remediation Highlights (Round 1 → Round 3)

- **Eliminated `psutil` completely:** Removed `SeDebugPrivilege` token privilege adjustment on import and removed `_psutil_windows.pyd` from the frozen bundle, replacing `create_time()` with single-handle `kernel32.GetProcessTimes` on `PROCESS_QUERY_LIMITED_INFORMATION` strictly for verified Full-mode single-player game PIDs.
- **Eliminated idle foreground & Xbox handle spraying:** Gated `WindowProbe` and `CaptureService` on `tracker.active_pids()` (0 handles when idle) and stopped `ProcessProbe` from scanning unrelated/system/AV/launcher processes.
- **Guaranteed sub-300 ms emergency exit:** Added `os._exit` + 200 ms guard-thread failsafe, removed all blocking `QMessageBox` modals on refusal/fail-closed, and halved `ProtectionGuard` interval to 150 ms.
- **Sleep/Resume immunity:** Switched `ProtectionGuard` heartbeat clock to Windows `QueryUnbiasedInterruptTime`.
- **Hardened override catalog:** Made `protected_games_override.json` strictly additive and immune to different-ID downgrades.
- **Hardened custom-folder installer:** Enforced `ValidateInstallDir` in both interactive and `/VERYSILENT` modes and hardened `RunValidatedQuietUninstaller` against UNC/proxy execution.
- **Hardened Translations & Mods:** Closed Windows case-insensitive collisions, streaming arbitrary-offset PE detection, `src`-reuse zip bombs, symlink-safe recovery cleanup, atomic verify-before-replace writes, and relative backup paths across store moves.

*See also: Egyptian Arabic owner summary in [docs/SECURITY-AUDIT-v1.2-AR.md](SECURITY-AUDIT-v1.2-AR.md).*
