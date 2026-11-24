# Red-Team Security Audit — Focus (c): Timing & Exit Latency

**Auditor:** Independent Red-Team Security Auditor (Focus c — Timing & Exit Latency)  
**Target:** GameRewind (`e:\projects\game hub`, frozen build `dist\GameRewind\GameRewind.exe` `--onedir` & `gamehub/app.py`)  
**Date:** 2026-11-24  
**Host OS:** Windows (Python 3.12.0 venv, ~323 active OS processes during measurement)  
**Scope:** Real wall-clock exit latency measurements (40 steady-state trials + adversarial teardown stress probes) compared against real Fortnite and Valorant anti-cheat launch timelines, plus static/dynamic audit of teardown bottlenecks in `gamehub/app.py` and its workers.

---

## Executive Summary

In **steady-state idle operation** (after startup library discovery settles), GameRewind's `ProtectionGuard` (`DEFAULT_GUARD_INTERVAL_SEC = 0.30`) detects dummy `FortniteLauncher.exe` and `VALORANT.exe` processes and completely removes the GameRewind PID from the Windows OS process table in **~282–289 ms average** and **387.52–397.65 ms max** across 40 real trials (20 Fortnite + 20 Valorant). That is **5.2×–15.5× faster** than Fortnite's real Launcher → EAC bootstrap timeline (~2,000–6,000 ms) and **3.8×–10.1× faster** than Valorant's Riot Client → VALORANT bootstrap (~1,500–4,000 ms). Native Win32 GUI (`QT_QPA_PLATFORM=windows`) matches `offscreen` within noise (**279.23 ms avg, 366.15 ms max**), and an open Qt modal `QMessageBox` closes cleanly in **308.4 ms**.

**However, adversarial worst-case testing uncovered two HIGH-severity and one MEDIUM-severity teardown defects that break the Zero-Presence timing guarantee:**

1. **`TIMING-001` (HIGH):** CPython's `concurrent.futures.thread._python_exit()` `atexit` handler **completely bypasses** `wait=False` in `gamehub/app.py:870,884`, stalling OS process termination until every active `ThreadPoolExecutor` worker finishes. Empirically reproduced: launching `FortniteLauncher.exe` while startup `LibraryController.refresh()` (`XboxDetector` PowerShell) is running stalled exit to **1,228.64–1,340.71 ms (warm PowerShell, 5/5 trials)** and **2,780.3 ms (cold PowerShell pilot)** — breaching Valorant's 1,500 ms lower bound and entering Fortnite's 2,000–6,000 ms EAC bootstrap window. Split-stage instrumentation proved `_run()` returned in **307–341 ms**, while CPython `atexit` held the OS process alive for an extra **976–984 ms** (and up to **8,000 ms** on `XboxDetector` timeout, or **10–60+ s** during `fetch_steamgriddb_cover()` / `store_location.move()`).
2. **`TIMING-002` (HIGH):** `_emergency_shutdown(fail_closed=True)` (`gamehub/app.py:585-593`) displays a **blocking modal `QMessageBox.critical()` BEFORE calling `window.close()` / `app.quit()`**. Empirically reproduced with a failing `WindowsServiceProbe` (`OpenServiceW(EasyAntiCheat_EOS)` error 5): GameRewind **hung indefinitely in the OS process table (`> 4,516 ms`, `in_os_table=True`)** waiting for a manual click while an anti-cheat service error was active.
3. **`TIMING-003` (MEDIUM):** `NotesController.close()` (`notes_controller.py:426-431`), `ControlsController.close()` (`controls_controller.py:152-156`), and non-daemon `SessionWatcher.close()` (`watcher.py:52,67-71`) ignore `emergency_exit[0]` and block with `wait=True` / unbounded `Thread.join()` (and `NotesController.close()` even spawns a new worker thread during emergency exit to run `self._recorder.abort`).
4. **`TIMING-004` (LOW):** The 300 ms `ProtectionGuard` polling interval accounts for ~75% of steady-state worst-case latency (388–398 ms) despite a full `Toolhelp32 + SCM` poll costing only **8.48 ms** average.

**Verdict: FAIL (4 open findings: `TIMING-001` [HIGH], `TIMING-002` [HIGH], `TIMING-003` [MEDIUM], `TIMING-004` [LOW])**

---

## 1. Methodology & Environment Isolation

- **No real anti-cheat games or user data touched:** Every trial used a harmless renamed copy of `C:\Windows\System32\ping.exe` (`FortniteLauncher.exe` or `VALORANT.exe`, run with `127.0.0.1 -n 12` and `CREATE_NO_WINDOW`) in an ephemeral `TemporaryDirectory`.
- **Isolated data root (critical pre-check):** Verification confirmed Qt's `QStandardPaths.writableLocation(GenericDataLocation)` on Windows calls `SHGetKnownFolderPath(FOLDERID_LocalAppData)` and ignores `$env:LOCALAPPDATA`, and `%LOCALAPPDATA%\GameHub` existed on this host. Launching `dist\GameRewind\GameRewind.exe` directly would have triggered `migrate_legacy_data_root()` on the owner's real `%LOCALAPPDATA%`. Therefore, every trial spawned a real isolated child process running the exact production `gamehub.app._run(app, isolated_temp_dir, smoke_test=False)` with zero mocks (real `ProtectedGamesCatalog.load(strict_load=True)`, real `ProtectionGuard` at default `0.30 s`, real `ToolhelpProcessScanner`, real `WindowsServiceProbe`, real `SessionWatcher`, `CaptureScheduler`, `GlobalHotkeys`, `LibraryController`, `NotesController`, `ControlsController`, `VoicePlayer`, `SingleInstance`). Post-audit check confirmed `%LOCALAPPDATA%\GameRewind` remains non-existent (`False`) and zero test processes remain.
- **Packaging parity note:** `dist\GameRewind\GameRewind.exe` is built as PyInstaller `--onedir` (`dist\GameRewind\_internal\`), so it has no `--onefile` bootloader temp-extraction cleanup delay on exit.
- **Phase randomization:** Steady-state trials waited `3.0 s + Uniform(0, 300 ms)` after `gamehub.lock` creation so dummy spawns sampled the 300 ms `ProtectionGuard` poll cycle uniformly rather than phase-locking.
- **Measurement definition:**
  - **Exit from spawn start (`t0 -> t_exit`):** Wall-clock ms (`time.perf_counter()`) from immediately before `subprocess.Popen(dummy)` until `app_proc.wait()` returns (Windows kernel process object signaled terminated). Includes OS process creation overhead (~30–67 ms).
  - **Exit from spawn return (`t_spawned -> t_exit`):** Wall-clock ms from `Popen` return (dummy PID live) until `app_proc.wait()` returns.
  - **OS process table confirmation:** Immediately after `app_proc.wait()` returned, a real `CreateToolhelp32Snapshot` scan (`ToolhelpProcessScanner.list_processes()`) verified `pid_present_after_wait == False` on **100% of trials (50/50)**.

---

## 2. Baseline Win32 Syscall Cost (`ProtectionGuard.check_once`)

Measured over 20 consecutive live scans on this host (**323 running processes**):

| Operation | Min (ms) | Avg (ms) | P95 (ms) | Max (ms) |
|---|---:|---:|---:|---:|
| `ToolhelpProcessScanner.list_processes()` | 7.02 | 7.52 | 8.40 | 8.40 |
| `WindowsServiceProbe.running_services()` (4 services) | 0.38 | 0.54 | 0.88 | 0.88 |
| Full `ProtectionGuard.check_once()` | 7.66 | 8.48 | 10.99 | 10.99 |

---

## 3. Summary Results — 40 Steady-State Trials vs Real Launch Timelines

| Suite (All Real Processes, `rc=0`, `os_gone=True`) | N | Min (ms) | Avg (ms) | Median (ms) | P95 (ms) | Max (ms) |
|---|---:|---:|---:|---:|---:|---:|
| **Fortnite (`FortniteLauncher.exe`) — from spawn start (`t0`)** | 20 | **111.29** | **281.78** | 296.18 | **385.16** | **387.52** |
| Fortnite (`FortniteLauncher.exe`) — from `Popen` return | 20 | 78.76 | 237.09 | 253.16 | 341.63 | 352.52 |
| **Valorant (`VALORANT.exe`) — from spawn start (`t0`)** | 20 | **74.24** | **289.43** | 301.86 | **378.62** | **397.65** |
| Valorant (`VALORANT.exe`) — from `Popen` return | 20 | 43.73 | 244.81 | 254.96 | 343.03 | 358.15 |
| Native Win32 GUI sanity (`QT_QPA_PLATFORM=windows`) | 5 | 163.55 | 279.23 | 324.06 | 364.68 | 366.15 |
| **Adversarial: Startup Refresh Race (`settle=0.2s`, warm PS)** | 5 | **1,228.64** | **1,280.78** | 1,286.16 | **1,330.12** | **1,340.71** |
| **Adversarial: Startup Refresh Race (cold PS pilot)** | 1 | 2,780.30 | 2,780.30 | 2,780.30 | 2,780.30 | **2,780.30** |

### Comparison Against Real Anti-Cheat Launch Timelines

| Game & Launch Chain | Real Bootstrap Window | Steady-State Max | Steady-State Margin | Active-Worker Worst-Case (Reproduced / Ceiling) | Margin Under Active Worker |
|---|---|---:|---:|---:|---|
| **Fortnite** (`FortniteLauncher.exe` → `FortniteBootstrapper.exe` → `EasyAntiCheat_EOS`) | **2,000–6,000 ms** | **387.52 ms** | **+1,612 to +5,612 ms** (5.2×–15.5× faster) | **2,780.3 ms** reproduced (up to **8,000–60,000+ ms** ceiling) | **BREACHED (-780 ms into EAC bootstrap; up to tens of seconds)** |
| **Valorant** (`RiotClientServices.exe` → `VALORANT.exe` → `VALORANT-Win64-Shipping.exe`) | **1,500–4,000 ms** | **397.65 ms** | **+1,102 to +3,602 ms** (3.8×–10.1× faster)* | **2,780.3 ms** reproduced (up to **8,000–60,000+ ms** ceiling) | **BREACHED (-1,280 ms past lower bound; note `RiotClientServices.exe` triggers earlier if not already blocked)** |

*\*Note on Valorant:* In production, `RiotClientServices.exe` is in `always_strict_launchers` (`protected_games.json:5-11`), so launching Riot Client triggers exit even before `VALORANT.exe` spawns. However, if Riot Client is started directly or `VALORANT.exe` launches immediately after Riot Client while a GameRewind worker thread is busy, `TIMING-001` still stalls exit past 1,500–4,000 ms.

---

## 4. Raw Trial Data Tables (All 40 Steady-State Trials + Stress Trials)

### Table 4.1 — Fortnite (`FortniteLauncher.exe`) — 20 Real Trials (Steady-State)

| Trial | App PID | Dummy PID | Phase Jitter (ms) | `Popen` Overhead (ms) | Exit from Spawn Start `t0` (ms) | Exit from `Popen` Return (ms) | Exit Code | PID Present After `wait()` |
|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| 1 | 22508 | 32364 | 247.17 | 40.81 | 225.44 | 184.63 | 0 | False |
| 2 | 39300 | 28756 | 202.60 | 67.49 | 331.15 | 263.66 | 0 | False |
| 3 | 37928 | 22088 | 1.03 | 64.44 | 170.26 | 105.81 | 0 | False |
| 4 | 24768 | 31948 | 201.64 | 55.78 | 314.09 | 258.31 | 0 | False |
| 5 | 32368 | 38672 | 207.46 | 57.51 | 277.25 | 219.73 | 0 | False |
| 6 | 2920 | 34212 | 41.34 | 51.15 | 141.25 | 90.09 | 0 | False |
| 7 | 20672 | 33420 | 181.82 | 43.93 | 324.67 | 280.74 | 0 | False |
| 8 | 31096 | 18620 | 146.88 | 32.52 | 111.29 | 78.76 | 0 | False |
| 9 | 36556 | 31500 | 48.81 | 40.50 | 346.97 | 306.47 | 0 | False |
| 10 | 36688 | 38336 | 131.50 | 46.45 | 387.52 | 341.06 | 0 | False |
| 11 | 36844 | 42132 | 232.97 | 42.20 | 272.72 | 230.52 | 0 | False |
| 12 | 40844 | 19192 | 170.56 | 40.19 | 343.48 | 303.29 | 0 | False |
| 13 | 37288 | 33364 | 22.74 | 44.92 | 294.61 | 249.69 | 0 | False |
| 14 | 9096 | 38708 | 217.42 | 40.84 | 288.22 | 247.39 | 0 | False |
| 15 | 21124 | 20388 | 175.06 | 47.20 | 344.99 | 297.79 | 0 | False |
| 16 | 17500 | 40632 | 265.98 | 48.34 | 238.18 | 189.84 | 0 | False |
| 17 | 37360 | 39996 | 282.75 | 26.97 | 202.72 | 175.76 | 0 | False |
| 18 | 14396 | 14076 | 191.50 | 41.12 | 297.75 | 256.63 | 0 | False |
| 19 | 32220 | 24276 | 87.45 | 32.52 | 385.04 | 352.52 | 0 | False |
| 20 | 37524 | 41092 | 8.13 | 28.93 | 338.06 | 309.14 | 0 | False |
| **Stats** | — | — | — | — | **min 111.29 / avg 281.78 / p95 385.16 / max 387.52** | **min 78.76 / avg 237.09 / p95 341.63 / max 352.52** | **20/20 rc=0** | **0/20 present** |

### Table 4.2 — Valorant (`VALORANT.exe`) — 20 Real Trials (Steady-State)

| Trial | App PID | Dummy PID | Phase Jitter (ms) | `Popen` Overhead (ms) | Exit from Spawn Start `t0` (ms) | Exit from `Popen` Return (ms) | Exit Code | PID Present After `wait()` |
|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| 1 | 17188 | 30500 | 237.38 | 45.53 | 253.14 | 207.60 | 0 | False |
| 2 | 7300 | 24552 | 294.78 | 50.38 | 184.32 | 133.93 | 0 | False |
| 3 | 3788 | 5232 | 162.88 | 44.21 | 336.67 | 292.46 | 0 | False |
| 4 | 15816 | 42976 | 292.80 | 55.15 | 211.62 | 156.47 | 0 | False |
| 5 | 33244 | 25288 | 176.94 | 30.51 | 74.24 | 43.73 | 0 | False |
| 6 | 23268 | 35692 | 21.77 | 55.16 | 322.58 | 267.42 | 0 | False |
| 7 | 20624 | 32596 | 158.62 | 41.37 | 377.17 | 335.80 | 0 | False |
| 8 | 38348 | 27772 | 248.63 | 40.93 | 263.23 | 222.31 | 0 | False |
| 9 | 19704 | 12136 | 49.12 | 44.43 | 362.07 | 317.63 | 0 | False |
| 10 | 42220 | 17292 | 164.64 | 62.54 | 319.09 | 256.56 | 0 | False |
| 11 | 38876 | 37964 | 96.85 | 39.51 | 397.65 | 358.15 | 0 | False |
| 12 | 41444 | 10076 | 237.41 | 49.53 | 257.57 | 208.04 | 0 | False |
| 13 | 16896 | 29376 | 176.88 | 38.67 | 280.80 | 242.12 | 0 | False |
| 14 | 15872 | 3036 | 79.37 | 47.43 | 276.29 | 228.86 | 0 | False |
| 15 | 24928 | 5904 | 109.15 | 40.71 | 360.16 | 319.45 | 0 | False |
| 16 | 40596 | 17524 | 172.65 | 39.06 | 324.40 | 285.34 | 0 | False |
| 17 | 34628 | 18060 | 151.25 | 42.83 | 296.18 | 253.36 | 0 | False |
| 18 | 37184 | 14632 | 9.09 | 37.27 | 307.54 | 270.27 | 0 | False |
| 19 | 41940 | 19448 | 13.19 | 35.39 | 377.62 | 342.23 | 0 | False |
| 20 | 31576 | 41640 | 276.87 | 51.77 | 206.21 | 154.44 | 0 | False |
| **Stats** | — | — | — | — | **min 74.24 / avg 289.43 / p95 378.62 / max 397.65** | **min 43.73 / avg 244.81 / p95 343.03 / max 358.15** | **20/20 rc=0** | **0/20 present** |

### Table 4.3 — Native Win32 GUI (`QT_QPA_PLATFORM=windows`) Sanity Trials (5 Trials)

| Trial | Target Exe | App PID | Exit from `t0` (ms) | Exit from `Popen` Return (ms) | Exit Code | PID Present After `wait()` |
|---:|---|---:|---:|---:|---:|:---:|
| 1 | `FortniteLauncher.exe` | 39616 | 366.15 | 335.68 | 0 | False |
| 2 | `FortniteLauncher.exe` | 16228 | 183.57 | 147.45 | 0 | False |
| 3 | `FortniteLauncher.exe` | 22516 | 324.06 | 289.46 | 0 | False |
| 4 | `VALORANT.exe` | 39812 | 358.82 | 327.35 | 0 | False |
| 5 | `VALORANT.exe` | 36108 | 163.55 | 105.53 | 0 | False |

### Table 4.4 — Adversarial Startup Refresh Race (`settle=0.2s`, `XboxDetector` PowerShell Active)

| Trial / Run | Target Exe | App PID | Exit from `t0` (ms) | Exit from `Popen` Return (ms) | Notes |
|---|---|---:|---:|---:|---|
| Pilot Run 1 | `FortniteLauncher.exe` | — | **2,780.30** | **2,730.00** | Cold PowerShell launch in `XboxDetector` |
| Race 1 | `FortniteLauncher.exe` | 34840 | 1,287.76 | 1,248.30 | Warm PowerShell |
| Race 2 | `FortniteLauncher.exe` | 15644 | 1,340.71 | 1,281.70 | Warm PowerShell |
| Race 3 | `FortniteLauncher.exe` | 36704 | 1,260.61 | 1,206.65 | Warm PowerShell |
| Race 4 | `VALORANT.exe` | 36376 | 1,286.16 | 1,238.70 | Warm PowerShell |
| Race 5 | `VALORANT.exe` | 5204 | 1,228.64 | 1,174.13 | Warm PowerShell |

### Table 4.5 — Split-Stage Teardown Instrumentation (Proving CPython `atexit` Stall)

| Scenario | Total `t0 -> OS Exit` (ms) | `t0 -> _run() return` (ms) | `_run() return -> OS Exit` (`atexit / _python_exit`) (ms) |
|---|---:|---:|---:|
| Steady-state idle (`settle=3.5s`) | 313.7 | 249.1 | 64.6 |
| Active refresh #1 (`settle=0.15s`) | **1,317.8** | 341.6 | **976.0** |
| Active refresh #2 (`settle=0.15s`) | **1,291.4** | 307.0 | **984.2** |

---

## 5. Findings & Teardown Bottleneck Analysis

### `TIMING-001` — [HIGH] CPython `concurrent.futures.thread._python_exit()` Bypasses `wait=False`, Stalling Emergency Exit for 1.2–2.8 s (Reproduced) up to 8–60+ s (Worst Case)

- **Location:**
  - `gamehub/app.py:869-884` (`move_worker.shutdown(wait=not emergency_exit[0], cancel_futures=emergency_exit[0])`, `controller.close(wait=not emergency_exit[0])`)
  - `gamehub/app.py:852` (`QTimer.singleShot(0, controller.refresh)` runs on every app startup)
  - `gamehub/core/library/xbox.py:157-165` (`subprocess.run([powershell.exe, ...], timeout=8)`)
  - `gamehub/app.py:1421-1441` (`fetch_steamgriddb_cover` loop in `move_worker`, `gamehub/core/library/steamgriddb.py:17` `_REQUEST_TIMEOUT_SEC = 6.0` × up to 3 requests per game × N games)
  - `gamehub/app.py:1469-1477` (`run_dummy_process_protection_test` in `move_worker`, up to 3 s + 4 s cleanup)
  - `gamehub/app.py:1521-1526` (`store_location.move()` copying entire data folder in `move_worker`)
- **Root Cause:** The teardown code passes `wait=False` when `emergency_exit[0]` is `True`, expecting `GameRewind` to exit immediately even if a background `ThreadPoolExecutor` worker is busy. However, CPython's `concurrent.futures.thread` module registers an `atexit` handler (`_python_exit`) that **unconditionally calls `t.join()` on every live `ThreadPoolExecutor` worker thread** before allowing the Python interpreter to terminate.
- **Empirical Reproduction & Evidence:**
  - **Cold PowerShell pilot (`settle=0.3s`):** `exit_from_t0 = 2,780.3 ms` (`os_gone = 2,792.4 ms`) — **780 ms past Fortnite's 2,000 ms EAC lower bound and 1,280 ms past Valorant's 1,500 ms lower bound**.
  - **Suite 4 (`settle=0.2s`, warm PowerShell, 5/5 trials):** `min 1,228.64 ms / avg 1,280.78 ms / max 1,340.71 ms`.
  - **Split-stage Probe 1:** `_run()` finished its entire `finally:` block and returned in **307.0–341.6 ms**, after which CPython `atexit` (`_python_exit`) kept the process alive in the OS process table for an additional **976.0–984.2 ms**.
  - If triggered during `XboxDetector` timeout (8 s), `fetch_steamgriddb_cover` (6 s × 3 × N games), or `store_location.move()` (copying gigabytes of screenshots/voice notes), GameRewind remains alive in the OS process table throughout anti-cheat driver initialization and gameplay.
- **Recommended Fix:**
  1. In `gamehub/app.py` `finally:` (after fast non-blocking cleanup of `hotkeys.close()`, `log_handler.close()`, and `instance.close()`), when `emergency_exit[0]` is `True`, call `os._exit(exit_code)` directly so CPython's `_python_exit()` `atexit` handler cannot stall process termination waiting on background workers.
  2. Add a daemon safety-net timer (`threading.Timer(0.25, os._exit, args=(0,))`, `daemon=True`) at the very top of `_emergency_shutdown()` so even if the Qt main thread or a Win32 call stalls during shutdown, the process is guaranteed to vanish from the OS process table within 250 ms.

---

### `TIMING-002` — [HIGH] `_emergency_shutdown(fail_closed=True)` Displays a Blocking Modal `QMessageBox.critical()`, Causing an Infinite Process Hang

- **Location:**
  - `gamehub/app.py:574-594` (`_emergency_shutdown`)
  - `gamehub/app.py:373-381` (`_notify_guard_block` -> `QMessageBox.critical(None, "GameRewind", text)`)
  - `gamehub/app.py:620-623` (`_check_guard_heartbeat` -> `_emergency_shutdown(fail_closed=True)`)
  - `gamehub/core/protection/guard.py:206-214` (`OpenServiceW` returning `ERROR_ACCESS_DENIED` raises `ProtectionCheckError`)
  - `gamehub/core/protection/guard.py:485-488` (`protection_guard.close()` blocks up to `2.0 s` on `join(timeout=2.0)`)
- **Root Cause:** When `ProtectionGuard` encounters a runtime check failure (e.g., `OpenServiceW` returning `ERROR_ACCESS_DENIED (5)` on a hardened anti-cheat service like `EasyAntiCheat_EOS` or `vgc` as it starts, or `guard_watchdog` detecting a stale heartbeat), `_emergency_shutdown(fail_closed=True)` invokes `_notify_guard_block("fail_closed", ...)` **before** `window.close()` and `app.quit()`. In production (`show_guard_dialog=None`), `_notify_guard_block` executes a blocking modal `QMessageBox.critical()`, freezing the shutdown sequence indefinitely until the user clicks OK. Worse, if triggered via `guard_watchdog` (`app.py:620-623`), `protection_guard.close()` (`app.py:584`) first blocks the main thread for `2,000 ms` (`guard.py:488`) on top of the `2,500–3,500 ms` watchdog stale window before reaching the infinite dialog.
- **Empirical Reproduction & Evidence:**
  - **Probe 2 (`CHILD_FAIL_CLOSED_SCRIPT`):** Injected a `ServiceProbe` that raises `ProtectionCheckError("OpenServiceW(EasyAntiCheat_EOS) failed (winerror=5)")` on poll #4 (~900 ms after startup).
  - **Observed output:**
    ```
    [FAIL_CLOSED] HUNG! Still alive in OS process table after 4516.0ms (pid=4808, in_os_table=True) — blocked on modal QMessageBox.critical!
    ```
  - The process never exited on its own and had to be forcefully killed by the audit harness.
- **Recommended Fix:**
  1. Remove the blocking `QMessageBox.critical()` call from `_emergency_shutdown(fail_closed=True)`. A Zero-Presence fail-closed shutdown must **never** wait for user interaction before exiting the OS process table.
  2. Instead, log `protection_guard_failed_closed`, optionally send a non-blocking OS notification (or persist a one-shot notice flag shown on the next manual launch), skip `self._thread.join(timeout=2.0)` during fail-closed/emergency exit, and exit immediately via `os._exit(2)`.

---

### `TIMING-003` — [MEDIUM] Unconditional Blocking Teardown in `NotesController.close()`, `ControlsController.close()`, and Unbounded Non-Daemon `SessionWatcher.close()`

- **Location:**
  - `gamehub/app.py:873-882`
  - `gamehub/modules/memory/notes_controller.py:426-431`
  - `gamehub/modules/memory/controls_controller.py:152-156`
  - `gamehub/core/sessions/watcher.py:52,67-71`
  - `gamehub/core/audio/recorder.py:73-99`
- **Root Cause:** Unlike `move_worker` and `LibraryController`, three other teardown calls in `gamehub/app.py:873-882` ignore `emergency_exit[0]`:
  1. `NotesController.close()` (`notes_controller.py:430-431`) unconditionally runs `self._worker.submit(self._recorder.abort)` followed by `self._worker.shutdown()` (`wait=True`). When idle, this unnecessarily **spawns a brand-new `game-notes` OS thread during emergency shutdown** just to run a no-op `abort()`; when a voice recording is stopping/encoding OGG Vorbis (`AudioRecorder.stop()` -> `soundfile.write()`), emergency exit blocks until PortAudio teardown and Vorbis encoding complete.
  2. `ControlsController.close()` (`controls_controller.py:156`) unconditionally calls `self._worker.shutdown(wait=True)`, blocking emergency exit during up to 16 MB control image imports/conversions.
  3. `SessionWatcher` creates a **non-daemon** thread (`watcher.py:52`) and `watcher.close()` (`watcher.py:71`) calls `self._thread.join()` with **no timeout**. If a protected game launches while `SessionWatcher._run()` is mid-poll (`ProcessProbe.snapshot()` calling `OpenProcess`/`QueryFullProcessImageNameW`/`psutil.Process.create_time()` on tracked games) or executing `self._tracker.shutdown()` (SQLite checkpoint write under lock contention), emergency shutdown blocks until the entire cycle and SQLite commit complete.
- **Evidence:** Direct code inspection + steady-state split-stage Probe 1 (`_run() return -> OS exit = 64.6 ms` even when completely idle, partly reflecting thread pool teardown overhead).
- **Recommended Fix:**
  1. Thread `wait=not emergency_exit[0]` into `notes_controller.close(wait=...)`, `controls_controller.close(wait=...)`, and `watcher.close(timeout=0.10 if emergency_exit[0] else None)`.
  2. In `NotesController.close()`, only submit `self._recorder.abort` if `self._voice is not None` (or `self._recorder._stream is not None`).
  3. Mark `SessionWatcher._thread` as `daemon=True` and pair emergency shutdown with `os._exit()` (`TIMING-001`).

---

### `TIMING-004` — [LOW] `ProtectionGuard` 300 ms Polling Interval Dominates Steady-State Worst-Case Exit Latency (~388–398 ms)

- **Location:** `gamehub/core/protection/guard.py:30` (`DEFAULT_GUARD_INTERVAL_SEC = 0.30`), `gamehub/app.py:358` (`guard_interval_sec: float = 0.30`)
- **Root Cause:** Across 40 steady-state trials, worst-case exit latency was **387.52 ms** (Fortnite) and **397.65 ms** (Valorant), while a full `Toolhelp32 + SCM` poll takes only **8.48 ms avg / 10.99 ms max**. Roughly **75%** of worst-case steady-state exit time is simply sleeping in `self._stop.wait(delay)` waiting for the next 300 ms tick.
- **Impact:** Safe against standard Fortnite (2,000–6,000 ms) and Valorant (1,500–4,000 ms) launch timelines when idle, but leaves less margin for fast NVMe systems, pre-warmed launchers, or other protected games with faster anti-cheat stubs.
- **Recommended Fix:** Reduce `DEFAULT_GUARD_INTERVAL_SEC` from `0.30` to `0.15`–`0.20` s (measured syscall cost `8.5 ms / 150 ms ≈ 5.6%` of one logical core, or `~4.2%` at `200 ms`; even better, consider checking `Toolhelp32` every `150 ms` and SCM every `300 ms`, though SCM only costs `0.54 ms`). That cuts steady-state max exit latency from ~398 ms to ~220–260 ms.

---

### `TIMING-005` — [INFO] Positive Observations & Verified Clean Paths

1. **Steady-state idle exit is fast and deterministic:** 40/40 trials (`FortniteLauncher.exe` × 20, `VALORANT.exe` × 20) exited with `rc=0` and `pid_present_after_wait=False` in **74.24–397.65 ms** (mean ~285 ms).
2. **Native Win32 GUI parity verified:** 5/5 trials under `QT_QPA_PLATFORM=windows` exited in **163.55–366.15 ms** (mean **279.23 ms**), showing no hidden Win32 window-teardown bottleneck vs `offscreen`.
3. **Active Qt modal dialog (`QMessageBox`) closes cleanly:** Probe 3 confirmed that when a Qt modal `QMessageBox.information()` is open and `FortniteLauncher.exe` spawns, `GameHubWindow.closeEvent()`'s `app.closeAllWindows()` closes the modal dialog and terminates GameRewind in **308.4 ms** (`rc=0`, `in_os_table=False`). *(Caveat: a native Win32 file picker via `QFileDialog` without `DontUseNativeDialog` runs a nested Win32 modal loop that could delay queued Qt signals — the `threading.Timer` `os._exit()` safety net recommended in `TIMING-001` also neutralizes this edge case.)*
4. **No PyInstaller `--onefile` cleanup penalty:** `dist\GameRewind\GameRewind.exe` is `--onedir`, eliminating bootloader temp-directory deletion delay on exit.

---

## Verdict

**Verdict: FAIL (4 open findings: `TIMING-001` [HIGH], `TIMING-002` [HIGH], `TIMING-003` [MEDIUM], `TIMING-004` [LOW])**
