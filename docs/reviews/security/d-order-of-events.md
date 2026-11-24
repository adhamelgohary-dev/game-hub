# Security Audit Report — Focus (d): Order-of-Events & Launch Contexts

- **Target:** GameRewind (`e:\projects\game hub\gamehub\`)
- **Primary Scope:** `app.py`, `single_instance.py`, `core/protection/guard.py`, `core/protection/lifecycle.py`, `core/sessions/watcher.py` (plus interacting modules `core/sessions/processes.py`, `core/protection/catalog.py`, `core/protection/protected_games.json`, `modules/memory/last_time_controller.py`, `modules/memory/notes_controller.py`, `modules/memory/controls_controller.py`, `ui/library_controller.py`)
- **Test Host:** Windows 11 (non-elevated user, `IsUserAnAdmin=False`, WTS Session 1, Python 3.12 `.venv` + PySide6)
- **Date:** 2026-11-24
- **Role:** Independent Red-Team Security Auditor (read-only audit; zero application/test files modified)

---

## Executive Summary

While GameRewind's core passive detection primitives (`ToolhelpProcessScanner` via `CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)` and read-only `WindowsServiceProbe`) work reliably even from a non-elevated Windows 11 account across WTS sessions and integrity levels (including SYSTEM/PPL processes), live adversarial testing uncovered **11 open security and reliability findings** across the four core event orders, sleep/resume, launch vectors, and emergency shutdown teardown:

| Severity | Count | Finding IDs |
|---|---:|---|
| **CRITICAL** | 1 | `ORD-01` |
| **HIGH** | 4 | `ORD-02`, `ORD-03`, `ORD-04`, `ORD-05` |
| **MEDIUM** | 4 | `ORD-06`, `ORD-07`, `ORD-08`, `ORD-09` |
| **LOW** | 2 | `ORD-10`, `ORD-11` |
| **INFO (Verified Controls)** | 6 | `INFO-01` – `INFO-06` |

---

## Coverage Matrix Across All 5 Audit Areas

| Audit Area | Result | Relevant Findings / Verified Controls |
|---|---|---|
| **1. Core Event Orders (Cases 1–4)** | **FAIL** | Case 1: `ORD-01`, `ORD-05`, `ORD-06`; Case 2: `ORD-02`, `ORD-06`, `ORD-07`, `ORD-09`, `INFO-04`; Case 3: `ORD-04`, `ORD-08`, `ORD-06`; Case 4: `ORD-01`, `ORD-10`, `INFO-05` |
| **2. Sleep / Resume (S3 / Modern Standby)** | **FAIL** | `ORD-03` (chains into `ORD-01` indefinite unprotected hang) |
| **3. Fast User Switching / WTS Session Lock** | **PARTIAL** | Cross-session Toolhelp32 visibility works (`INFO-01`), but locked/disconnected sessions amplify `ORD-01` & `ORD-03` because no user can dismiss blocking `QMessageBox` dialogs (`INFO-06`) |
| **4. Launch Vectors (Desktop, Steam, Epic, Xbox/Game Pass, Admin/Elevated)** | **FAIL** | Elevated/SYSTEM/PPL visibility PASS (`INFO-01`, `INFO-02`); Xbox/Game Pass FAIL (`ORD-04`); Play-through FAIL (`ORD-07`); Steam/Epic EAC shared bootstrapper FAIL (`ORD-08`) |
| **5. Modal Dialogs Blocking Emergency Shutdown** | **FAIL** | Parented `QFileDialog` / `QMessageBox` / `ScanFolderDialog` / `LastMomentsDialog` & `LastTimeCard` PASS (`INFO-03`); Guard's own parentless `QMessageBox` (`ORD-01`), `ThreadPoolExecutor` `atexit` (`ORD-02`), and `NoteDialog` re-reveal (`ORD-11`) FAIL |

---

## Detailed Findings

### [ORD-01] CRITICAL — Blocking `QMessageBox` Keeps `GameRewind.exe` Alive Indefinitely During Startup Refusal (Cases 1 & 4) and Runtime Fail-Closed (With Guard Dead)

- **Locations:**
  - `gamehub/app.py:373-380` (`_notify_guard_block`)
  - `gamehub/app.py:398-421` (Case 1 & Case 4 startup refusal / fail-closed)
  - `gamehub/app.py:574-594` (`_emergency_shutdown(fail_closed=True)`)
- **Description:**
  Zero-Presence protection promises that `GameRewind.exe` is never alive alongside a protected game or when protection cannot verify system state. However, `_notify_guard_block()` synchronously invokes blocking modal `QMessageBox.information(None, ...)` or `QMessageBox.critical(None, ...)`:
  1. **Cases 1 & 4 (Startup Refusal, `app.py:408-421`):** When a protected game or Riot Client is *already* running and the user launches GameRewind (or a second instance), `QMessageBox.information(None, ...)` blocks `main()` indefinitely until the user manually clicks OK. If the dialog spawns behind an exclusive-fullscreen/borderless game or the user ignores it, `GameRewind.exe` remains a live process alongside the kernel anti-cheat for the entire gaming session.
  2. **Runtime Fail-Closed (`app.py:574-594`):** When `guard_watchdog` or `ProtectionGuard` triggers `_emergency_shutdown(fail_closed=True)` (e.g., on sleep/resume `ORD-03`, transient SCM failure, or snapshot failure):
     - Line 577 stops `guard_watchdog`.
     - Line 584 calls `protection_guard.close()` (shutting down the protection thread!).
     - Line 586 blocks **indefinitely** on `QMessageBox.critical(None, ...)` **before** calling `window.close()` (line 592) and `app.quit()` (line 593).
     - During this indefinite block, `GameHubWindow` remains open, `SingleInstance` remains locked, `SessionWatcher` (which isn't closed until `finally:` line 882) continues polling Windows processes every 3 seconds, and **`ProtectionGuard` is completely dead**. If the user later starts Valorant/Fortnite without noticing the buried dialog (or if this happens on a locked/background WTS session), GameRewind remains alive indefinitely with zero active guard.
- **Live Evidence:**
  - **Runtime fail-closed (`probe_modal_shutdown.py`, scenario `fail_closed_qmessagebox`):**
    ```text
    GUARD_TRIGGER_EMITTED
    EMERGENCY_SHUTDOWN_ENTER dt=0.000s
    HUNG / BLOCKED past 4.03s -> KILLED!
    ```
  - **Case 1 real `_run()` without test override (`probe_races_and_vectors.py`, scenario `Case1-RealDialog`):**
    ```text
    [Case1-RealDialog] BLOCKED/ALIVE past 3.52s while FortniteLauncher.exe running -> KILLED! stdout='CASE1_STARTING'
    ```
  *(Note: `tests/test_zero_presence_guard.py:123, 145, 194, 207` masked this bug in CI by injecting a non-blocking mock `show_guard_dialog` callback.)*
- **Recommended Fix:**
  - Never block process exit on a modal dialog inside the live `GameRewind.exe` process.
  - For **Case 1 / Case 4 startup refusal** and **runtime fail-closed**: send a non-blocking Windows toast notification (`WindowsNotifier`) **or** auto-dismissing non-modal / timed notification (e.g., max 3–5s, or toast only) and **exit the process immediately**.
  - Specifically in `_emergency_shutdown(fail_closed=True)`: close `window`, stop `watcher`, release `instance`, call `app.quit()` FIRST, and if a notice must be shown, use a fire-and-forget Windows toast notification (which is hosted by Windows Shell, not `GameRewind.exe`) so `GameRewind.exe` terminates in `< 500ms` with zero user interaction.

---

### [ORD-02] HIGH — `ThreadPoolExecutor` `atexit` Hook and Blocking `finally:` Calls Hang Emergency Shutdown Until Background Jobs Finish

- **Locations:**
  - `gamehub/app.py:863-889` (`_run` `finally:` cleanup)
  - `gamehub/app.py:1354, 1421-1441, 1469-1477, 1521-1526` (`move_worker`: `fetch_missing_covers`, `run_protection_test`, `store_location.move`)
  - `gamehub/modules/memory/controls_controller.py:152-156` (`self._worker.shutdown(wait=True)`)
  - `gamehub/modules/memory/notes_controller.py:426-431` (`self._worker.shutdown()` -> `wait=True`)
  - `gamehub/core/sessions/watcher.py:67-71` (`self._thread.join()` without timeout)
  - `gamehub/ui/library_controller.py:161-162` (`self._worker.shutdown(wait=wait, cancel_futures=True)`)
  - `gamehub/core/capture/scheduler.py:94-97` (`self._worker.shutdown(wait=False, cancel_futures=True)`)
  - `gamehub/modules/memory/last_time_controller.py:315-325` (`self._worker.shutdown(wait=False, cancel_futures=True)`)
- **Description:**
  `app.py:870` and `app.py:884` pass `wait=not emergency_exit[0]` (`wait=False`) to `move_worker.shutdown(...)` and `controller.close(...)` assuming this makes emergency exit immediate. That assumption is **false in CPython**:
  1. `concurrent.futures.thread._python_exit` registers an `atexit` handler that unconditionally calls `.join()` on **every running `ThreadPoolExecutor` worker thread** before the Python interpreter exits—**even after `shutdown(wait=False, cancel_futures=True)`**.
  2. Several long-running jobs execute on `ThreadPoolExecutor`s with zero cooperative cancellation:
     - `fetch_missing_covers` (`app.py:1428-1439`): sequential HTTP requests to SteamGridDB for every game missing a cover (can take 30–120+ seconds).
     - `store_location.move()` (`app.py:1523`): copies/moves the entire GameRewind data directory (potentially gigabytes of screenshots and audio across drives).
     - `library.refresh()` (`ui/library_controller.py:49`): scans all 10 game launchers and disk folders.
     - `run_dummy_process_protection_test()` (`app.py:1470`): waits up to 3.0s.
  3. In addition, inside `finally:` (`app.py:873-882`), `controls_controller.close()`, `notes_controller.close()`, and `watcher.close()` **ignore `emergency_exit[0]` entirely** and block synchronously (`wait=True` / unbounded `join()`).
  4. Result: If a protected game launches (Case 2/3) while any background job is in flight, `GameRewind.exe` remains alive in the OS process table for the full duration of that background job—potentially minutes—while the protected game and its kernel anti-cheat run.
- **Live Evidence (`probe_modal_shutdown.py`, scenario `threadpool_atexit_hang`):**
  ```text
  SLOW_JOB_STARTED
  GUARD_TRIGGER_EMITTED
  EMERGENCY_SHUTDOWN_ENTER dt=0.000s
  EMERGENCY_SHUTDOWN_EXIT dt=0.000s
  APP_EXEC_RETURNED rc=0 NOW_EXITING_PYTHON
  HUNG / BLOCKED past 4.03s -> KILLED!
  ```
- **Recommended Fix:**
  - Add a shared cancellation `Event` checked inside `fetch_missing_covers` and `library.refresh` loops, and make `controls_controller.close(wait=...)`, `notes_controller.close(wait=...)`, and `watcher.close(timeout=...)` respect `emergency_exit[0]`.
  - Release `instance.close()` and flush logs/SQLite checkpoints first, then enforce a strict emergency-exit deadline (e.g., `0.5s`–`1.0s` daemon watchdog thread calling `os._exit(0)` if Python shutdown/`atexit` has not exited in time when `emergency_exit[0]` is `True`). Note: never `os._exit` mid-SQLite transaction without giving `Database` writes a short grace window, or ensure `store_location.move()` is atomic/recoverable on next launch (it already uses staged/recoverable patterns; verify recovery).

---

### [ORD-03] HIGH — Sleep / Resume (S3 / Modern Standby) Causes False Fail-Closed Watchdog Trip (Chaining Into `ORD-01` Unprotected Hang)

- **Locations:**
  - `gamehub/core/protection/guard.py:23, 31, 250, 434-450, 461-474`
  - `gamehub/app.py:617-626` (`guard_watchdog` `QTimer` at 1000ms interval)
- **Description:**
  `ProtectionGuard` uses Python's `time.monotonic()` to stamp `self._last_heartbeat` (`guard.py:437`) and verify freshness against `DEFAULT_WATCHDOG_STALE_SEC = 2.5` in `is_healthy()` (`guard.py:461-474`).
  1. On Windows, Python's `time.monotonic()` is backed by **`GetTickCount64()`**, which per Microsoft documentation **includes time spent in S3 Sleep, Modern Standby (S0ix), and S4 Hibernate** (unlike `QueryUnbiasedInterruptTime()`).
  2. When Windows sleeps or enters Modern Standby (where the Desktop Activity Moderator suspends Win32 apps) for > 2.5 seconds and resumes:
     - `GetTickCount64()` jumps forward by the full sleep duration (e.g., +300s).
     - On resume, the Qt main thread's overdue `guard_watchdog` `QTimer(1000)` races against the `protection-guard` thread waking from `Event.wait()` and completing a full `check_once()` (Toolhelp32 snapshot + 4 SCM `OpenServiceW`/`QueryServiceStatusEx` RPCs).
     - Whenever `guard_watchdog` fires first—which is likely on resume when SCM/CPU is waking—`is_healthy()` computes `(clock() - last) > 2.5` and returns `False`.
  3. There is **no `WM_POWERBROADCAST` (`PBT_APMSUSPEND` / `PBT_APMRESUMEAUTOMATIC`) handler** anywhere in `gamehub/`.
  4. **Chained Impact:** `_check_guard_heartbeat()` calls `_emergency_shutdown(fail_closed=True)` -> stops `protection_guard` -> hits `ORD-01` (`QMessageBox.critical`), leaving `GameRewind.exe` **alive indefinitely with `ProtectionGuard` shut down** after waking from sleep!
  5. Conversely, if `protection-guard` wins the wake race, it performs an immediate `check_once()` on wake (closing any blind gap within ~50–300ms). Thus the primary hazard is the high-probability false fail-closed crash turning into an unprotected hung process via `ORD-01`.
- **Live Evidence (`probe_os_and_clock.py`):**
  ```text
  monotonic info: namespace(implementation='GetTickCount64()', monotonic=True, adjustable=False, resolution=0.015625)
  perf_counter info: namespace(implementation='QueryPerformanceCounter()', monotonic=True, adjustable=False, resolution=1e-07)
  Python time.monotonic()         = 245243.687 s
  GetTickCount64()                = 245243.687 s
  QueryUnbiasedInterruptTime()    = 245243.701 s (ok=1)
  Guard is_healthy() before sleep (dt=0.0s): True
  Guard is_healthy() right on wake after 3.0s sleep (dt=3.0s > 2.5s): False
  ```
- **Recommended Fix:**
  - Use Windows **`QueryUnbiasedInterruptTime()`** (via `ctypes.WinDLL("kernel32")`, falling back to `monotonic()` on non-Windows) as the default `clock` for `ProtectionGuard`, since unbiased interrupt time pauses during S3/S4/Modern Standby and does not jump on resume.
  - Also install a native event filter for `WM_POWERBROADCAST` (`PBT_APMRESUMEAUTOMATIC` / `PBT_APMRESUMESUSPEND`) to immediately wake `protection-guard` for a fresh `check_once()` upon resume (eliminating any post-wake blind window) while granting one fresh poll cycle before the watchdog declares staleness.
  - Independently fix `ORD-01` so even a legitimate fail-closed exit never hangs on a modal dialog.

---

### [ORD-04] HIGH — Xbox / Game Pass Launch Vector Causes `ProcessProbe` to Call `OpenProcess` on Every Non-Catalog Process on Windows (Plus Missing `-WinGDK-Shipping.exe`)

- **Locations:**
  - `gamehub/core/sessions/processes.py:168-190, 216-229` (`ProcessProbe.snapshot` and `_matches`)
  - `gamehub/core/sessions/watcher.py:120-125, 159-166`
  - `gamehub/core/protection/protected_games.json:378` (`dead_by_daylight`)
- **Description:**
  1. **Broad `OpenProcess` Leak Across All Unlisted Processes (`processes.py:184-188`):**
     ```python
     check_image = norm_name in basenames
     if not check_image and not packages:
         continue
     try:
         matches = self._matches(pid, check_image, executables, packages)
     ```
     Because `XboxDetector()` runs automatically on startup (`app.py:476`), if the user has **even one** non-strict Xbox/Game Pass game installed (`packages` is non-empty), `not packages` is `False`. Consequently, every 3 seconds `SessionWatcher` -> `ProcessProbe.snapshot()` calls **`OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)` + `GetPackageFamilyName()` on EVERY process on Windows** whose basename is not in `protected_exes`.
     This directly undermines the anti-cheat safety invariant (`processes.py:174-175`, `AGENTS.md`) for:
     - **`gamelaunchhelper.exe`** — the initial bootstrapper process spawned by *every* Xbox / Microsoft Store / Game Pass protected game (Call of Duty, Halo Infinite, Halo MCC, Sea of Thieves, Dead by Daylight, Destiny 2, EA FC, Rainbow Six Siege) before the game executable starts.
     - **Unlisted Xbox/Store game binaries**, e.g. `DeadByDaylight-WinGDK-Shipping.exe` (missing from `protected_games.json:378`).
     - **Unlisted anti-cheat / launcher helper processes** (`EAAntiCheat.GameService.exe`, `EasyAntiCheat_EOS_Setup.exe`, `EpicGamesLauncher.exe`, `vgtray.exe`, etc.) and every OS/system process (`lsass.exe`, `csrss.exe`, etc.).
  2. **Catalog Gap for Xbox Game Pass Binary (`protected_games.json:378`):**
     `dead_by_daylight` lists `xbox_package_prefixes: ["BehaviourInteractive.DeadbyDaylight"]`, yet `game_exes` only contains `deadbydaylight-win64-shipping.exe` (Steam) and `deadbydaylight-egs-shipping.exe` (Epic)—omitting `deadbydaylight-wingdk-shipping.exe` (Microsoft Store / Xbox PC Game Pass). If Dead by Daylight is launched via Xbox/Game Pass, `ProtectionGuard` misses its game exe by name (relying solely on the `EasyAntiCheat_EOS` service probe), and `SessionWatcher` actively calls `OpenProcess` on it!
- **Live Evidence (`probe_races_and_vectors.py`, Test 6):**
  ```text
  === TEST 6: ProcessProbe OpenProcess leak when ANY Xbox game target exists ===
  protected_exes seen: frozenset({'valorant-win64-shipping.exe'})
  OpenProcess/inspect() called on PIDs: [(1002, False, True), (1003, False, True), (1004, False, True), (1005, False, True), (1006, False, True)]
  gamelaunchhelper.exe (1002) inspected? True
  DeadByDaylight-WinGDK-Shipping.exe (1003) inspected? True
  EAAntiCheat.GameService.exe (1005) inspected? True
  ```
- **Recommended Fix:**
  - Do not open handles to every arbitrary process on Windows just because an Xbox `package_id` target exists. At minimum:
    1. Exclude `gamelaunchhelper.exe`, all optional launcher exes (`optional_strict_launchers`), known anti-cheat helper exes, and Session 0 / system processes from `inspect()`—or better, match Xbox games by their discovered `exe_path` basenames (from `AppxManifest.xml` `<Application Executable=...>` already accessible to `XboxDetector`) instead of scanning every PID with `OpenProcess` + `GetPackageFamilyName`.
    2. Add `deadbydaylight-wingdk-shipping.exe` (and verify `-wingdk-` / `-winstore-` exe names for all other `xbox_package_prefixes` entries) to `protected_games.json`.

---

### [ORD-05] HIGH — Startup TOCTOU Window & `QueuedConnection` Delay Expose Hotkeys, `SessionWatcher`, and `ModsEngine` During Startup

- **Locations:**
  - `gamehub/app.py:397` (`protection_guard.self_check()`)
  - `gamehub/app.py:423-616` (startup work before `protection_guard.start()`)
  - `gamehub/app.py:596-603` (`Qt.ConnectionType.QueuedConnection`)
  - `gamehub/app.py:783, 802-862` (`mods_engine.recover_incomplete()`, `_start_hotkeys()`, `watcher.start()`, `capture_scheduler.start()`, `app.exec()`)
- **Description:**
  There are two compounding startup race windows:
  1. **Gap 1 (`app.py:397` → `app.py:613`):** After `protection_guard.self_check()` passes on line 397, the guard is **not running** while GameRewind performs potentially multi-second I/O: `migrate_legacy_data_root()` (file migration), `GameHubWindow(app)` creation, `SingleInstance.claim_or_activate()` (up to 1.0s loop), SQLite `Database` open + schema migration + backup, `Screenshot`/`Controls`/`Note` file recovery, `LibraryService.current()`, and `window.show()`.
  2. **Gap 2 (`app.py:613` → `app.py:862`):** Although `protection_guard.start()` starts the daemon thread on line 613, its callbacks emit `guard_bridge.triggered` / `guard_bridge.failed` via `Qt.ConnectionType.QueuedConnection` (`app.py:596-603`). Queued signals **cannot execute until `app.exec()` begins on line 862**. Therefore, even if `protection_guard` detects a protected game launched during Gap 1 or Gap 2, the main thread still blindly executes:
     - `mods_engine.recover_incomplete()` (`app.py:783`)
     - `_start_hotkeys()` -> Win32 `RegisterHotKey` (`app.py:802`)
     - `watcher.start()` -> spawns `SessionWatcher` (`OpenProcess`!) (`app.py:849`)
     - `capture_scheduler.start()` (`app.py:851`)
     before `app.exec()` ever dispatches `_emergency_shutdown()`.
- **Recommended Fix:**
  - Run a synchronous `if protection_guard.check_once() is not None or protection_guard.last_trigger is not None:` gate immediately **before** `window.show()`, **before** `mods_engine.recover_incomplete()`, and **before** `_start_hotkeys()` / `watcher.start()` / `capture_scheduler.start()` (and abort startup immediately if triggered, without entering `app.exec()`).
  - Start `protection_guard` immediately after `SingleInstance` claims the lock (or before heavy DB/recovery work), and check `protection_guard.last_trigger` / `protection_guard.failed_reason` synchronously at each startup milestone.

---

### [ORD-06] MEDIUM — User-Marked Custom `protection_mode='strict'` Games (Non-Catalog) Are Ignored by `ProtectionGuard` and Never Auto-Exit

- **Locations:**
  - `gamehub/app.py:328-344, 390-397, 605-610`
  - `gamehub/core/protection/guard.py:317-416`
  - `gamehub/core/sessions/watcher.py:112-125, 193-222`
- **Description:**
  GameRewind allows users to manually set any game in their library (e.g., a newly released online/anti-cheat game not yet in `protected_games.json`) to `protection_mode = 'strict'` via Game Page or Settings (`app.py:1143, 1450`). However:
  1. `_sync_guard_policy()` (`app.py:605-610`) only passes `enabled_optional_launchers` and `disabled_entry_ids` to `ProtectionGuard`—it **never passes custom Strict games' target executables**.
  2. `ProtectionGuard._check_once_locked()` (`guard.py:317-416`) only checks `self._catalog`, so it misses user-marked non-catalog Strict games in **Case 1 (startup)**, **Case 2 (runtime launch)**, and **Case 3 (launcher → game)**.
  3. `SessionWatcher._emit_protected_detections()` (`watcher.py:199`) only emits `ProtectedGameDetected` for `snapshot.protected_exes` (which also comes strictly from `self._catalog.all_exe_names()`, `watcher.py:91`). Thus, a user-marked non-catalog Strict game **never triggers auto-exit (`exit_app`)**—it only falls back to passive Strict mode 0–3s later via `GameStarted`, leaving hotkeys and capture active during that 0–3s window.
- **Live Evidence (`probe_remaining.py`, Test 8):**
  ```text
  === TEST 8: User-marked Strict game (non-catalog) gap in ProtectionGuard ===
  Game 'Custom Kernel Game' protection_mode='strict' targets=('customacgame.exe',)
  ProtectionGuard.check_once() with CustomACGame.exe running -> None
  ```
- **Recommended Fix:**
  - Read user-marked `protection_mode == 'strict'` game target basenames in `_read_startup_guard_prefs()` (for Case 1 startup) and in `_sync_guard_policy()` (for Cases 2 & 3 runtime), and pass them as `custom_strict_exes` into `ProtectionGuard` so user-marked Strict games receive the same `< 300ms` Zero-Presence protection as catalog games.

---

### [ORD-07] MEDIUM — Play-Through Order Inversion: Protected Game / Riot Client Launches BEFORE Hotkeys Suspend or GameRewind Exits

- **Locations:**
  - `gamehub/modules/memory/last_time_controller.py:262-294` (`_launch`, `_launch_finished`)
  - `gamehub/core/protection/lifecycle.py:80-95` (`on_play_launched`)
  - `gamehub/app.py:727-729`
- **Description:**
  When a user clicks **Play -> Launch** on a protected/Strict game inside GameRewind (`LastTimeCard`):
  1. `LastTimeController._launch()` (`last_time_controller.py:271-274`) immediately dispatches `WindowsLauncher.launch()` (`ShellExecuteW` or `Popen(RiotClientServices.exe)`) on its background worker thread.
  2. Hotkeys (`GlobalHotkeys`), `CaptureScheduler`, and `SessionWatcher` remain **fully active** while `ShellExecuteW` / `Popen` executes and starts the launcher/game.
  3. Only *after* `launch()` returns, posts a queued `_done` signal back to the Qt main thread, enters `_launch_finished()`, and invokes `lifecycle.on_play_launched()` (`lifecycle.py:87-94`) does GameRewind save the pending note and call `_emergency_shutdown()`.
  4. Combined with `ORD-02` (any in-flight background worker thread), `GameRewind.exe` with active Win32 hotkeys and `SessionWatcher` overlaps with the newly spawned protected launcher/game.
- **Recommended Fix:**
  - For any game where `is_strict_game(game_id)` is `True`, **before** calling `self._launcher.launch()`:
    1. Immediately suspend hotkeys (`hotkeys.suspend()`), pause `capture_scheduler`, and stop `watcher`.
    2. Pre-write the `pending_notes` record (or delete it only if `launch()` returns `accepted=False`).
    3. Dispatch the official URI / detached launcher, then immediately trigger `_emergency_shutdown()` without waiting for background pools.

---

### [ORD-08] MEDIUM — Turning Protection Off for Elden Ring Silently Disables `start_protected_game.exe` Early Detection for ALL Other EAC Games

- **Locations:**
  - `gamehub/core/protection/protected_games.json:205` (`elden_ring.launcher_stage_exes`)
  - `gamehub/core/protection/guard.py:353-364`
- **Description:**
  `start_protected_game.exe` is the standard Easy Anti-Cheat bootstrapper launched by Steam/Epic for **many** protected games (including `elden_ring_nightreign`, `armored_core_6`, `lords_of_the_fallen`, `space_marine_2`, `dead_by_daylight`, `halo_infinite`, `sea_of_thieves`, `the_finals`, `lost_ark`, `for_honor`, `fall_guys`). However, in `protected_games.json`, `start_protected_game.exe` is listed **only** inside `elden_ring.launcher_stage_exes` (line 205), not in `global_anti_cheat_exes`.
  If a user turns off protection for Elden Ring (`protection_mode = 'full'`, a very common single-player mod use case such as Seamless Co-op or offline translation mods), `"elden_ring"` is added to `disabled_entry_ids`. In `guard.py:354-355`, `if entry.id in disabled_entries: continue` skips `elden_ring`—which **completely disables `start_protected_game.exe` detection for every other EAC game on the system**! Those games then miss the earliest `launcher_stage` trigger and rely on later `EasyAntiCheat_EOS` service / game-exe detection.
- **Live Evidence (`probe_remaining.py`, Test 9):**
  ```text
  === TEST 9: Disabling Elden Ring breaks start_protected_game.exe for ALL EAC games ===
  Default: start_protected_game.exe -> ProtectionTrigger(kind='launcher_stage', identifier='start_protected_game.exe', display_name='ELDEN RING', stage='launcher_stage', entry_id='elden_ring')
  Elden Ring set to Off ('full'): start_protected_game.exe -> None
  ```
- **Recommended Fix:**
  - Move `start_protected_game.exe` (and generic EAC/BE bootstrappers like `easyanticheat_launcher.exe`, `eac_launcher.exe`) into `global_anti_cheat_exes` (or list `start_protected_game.exe` on every EAC game entry, noting that offline-modded Elden Ring launches `eldenring.exe` directly or via ModEngine2 rather than `start_protected_game.exe` with EAC).

---

### [ORD-09] MEDIUM — "Test Protection" Button Causes `SessionWatcher` to Falsely Trigger Emergency Exit and Kill GameRewind

- **Locations:**
  - `gamehub/core/protection/guard.py:508-599` (`run_dummy_process_protection_test`)
  - `gamehub/app.py:1463-1478` (`run_protection_test`)
  - `gamehub/core/sessions/watcher.py:160-180, 193-218`
  - `gamehub/core/protection/lifecycle.py:129-141`
- **Description:**
  When a user clicks **"Test Protection"** in Settings (`app.py:1463`), `run_dummy_process_protection_test()` copies `ping.exe` to a temp folder as `FortniteLauncher.exe`, spawns it, and exempts its PID in `live_guard` via `live_guard.ignore_pid(proc.pid)` (`guard.py:567`).
  However, **`SessionWatcher` is NOT notified of the ignored PID**. While the dummy `FortniteLauncher.exe` is alive (~150–300ms), if `SessionWatcher`'s 3-second poll tick fires, `ProcessProbe.snapshot()` sees `fortnitelauncher.exe` in `protected_exes`, `SessionWatcher` publishes `ProtectedGameDetected(entry_id='fortnite', ...)`, and `LifecycleCoordinator.on_protected_detected()` (default `external_behavior='exit_app'`) calls `_emergency_shutdown()`—**unexpectedly killing GameRewind during its own self-test** (roughly ~5–10% failure rate per click depending on poll phase).
- **Live Evidence (`probe_remaining.py`, Test 10):**
  ```text
  === TEST 10: SessionWatcher falsely fires ProtectedGameDetected during 'Test Protection' ===
  run_dummy_process_protection_test result: SelfTestResult(ok=True, elapsed_ms=172, trigger_name='Fortnite', error=None)
  live_guard triggers (expected []): []
  SessionWatcher false ProtectedGameDetected events: [ProtectedGameDetected(entry_id='fortnite', entry_name='Fortnite', anti_cheat='Easy Anti-Cheat / BattlEye', exe_name='fortnitelauncher.exe', game_id=None)]
  ```
- **Recommended Fix:**
  - Either pass an `ignored_pids` mechanism (or `watcher.pause()` / `watcher.resume()` around the self-test, or share an `ignored_pids` check between `ProtectionGuard` and `SessionWatcher`/`ProcessProbe`) so `SessionWatcher` ignores the self-test dummy PID just as `live_guard` does.

---

### [ORD-10] LOW — Case 4 `SingleInstance` Teardown Race: Silent Double-Exit or Blocking `QMessageBox.critical`

- **Locations:**
  - `gamehub/single_instance.py:24-45, 54-57`
  - `gamehub/app.py:451-452, 863-888, 1689-1693`
- **Description:**
  `instance.close()` is the **very last** statement in `app.py`'s `finally:` block (`app.py:888`), executing only after `protection_guard.close()`, `controls_controller.close()`, `notes_controller.close()`, `watcher.close()`, etc.
  If a second instance of GameRewind launches while the primary is shutting down (after `app.exec()` has returned, before `instance.close()` runs):
  1. **Named pipe still open (`server_open_no_loop`):** On Windows, the kernel Named Pipe for `QLocalServer` still accepts `connectToServer()` even though primary's Qt event loop has stopped. Instance #2 receives `waitForConnected() == True`, returns `False` (`app.py:451-452`), and exits silently thinking it woke primary—while primary also dies (`activated=0`).
  2. **Server closed / unresponsive while lock still held > 1s (`server_closed_lock_held`):** Instance #2 loops for 1.0s (`single_instance.py:37-45`) and raises `RuntimeError("The running GameRewind instance did not respond.")`. `app.py:1689-1693` catches `RuntimeError` and displays a **blocking `QMessageBox.critical`** (`ORD-01` variant)—if primary was exiting because a protected game just launched via Play-through (before the game exe appeared), Instance #2 remains stuck alive on the error box while the protected game runs!
- **Live Evidence (`probe_races_and_vectors.py`, Test 5):**
  ```text
  [server_open_no_loop] P1: PRIMARY_CLAIMED ok=True | PRIMARY_DONE activated=0
  [server_open_no_loop] P2: SECONDARY_RESULT ok=False dt=0.016s
  [server_closed_lock_held] P1: PRIMARY_CLAIMED ok=True | PRIMARY_DONE activated=0
  [server_closed_lock_held] P2: SECONDARY_RAISED RuntimeError: The running GameRewind instance did not respond. dt=1.000s
  ```
- **Recommended Fix:**
  - Close `instance._server` immediately when shutdown starts (inside `_emergency_shutdown()` / `window.closeEvent`) and call `instance.close()` as early as safe in `finally:` (or after DB/watcher stop, which should be bounded per `ORD-02`).
  - In `SingleInstance.claim_or_activate()`, re-attempt `self._lock.tryLock(0)` inside the 1-second retry loop (`single_instance.py:38-44`) so if the primary finishes exiting during that 1 second, Instance #2 cleanly re-runs `protection_guard.check_once()` and takes over instead of crashing into `QMessageBox.critical`.

---

### [ORD-11] LOW — Closing `NoteDialog` During `_emergency_shutdown()` Synchronously Re-Reveals `GameHubWindow`

- **Locations:**
  - `gamehub/modules/memory/notes_controller.py:168, 185-211` (`_prompt_closed`)
  - `gamehub/core/protection/lifecycle.py:122-127` (`on_note_prompt_finished`)
  - `gamehub/app.py:277-288, 592` (`window.reveal`, `window.closeEvent`, `_emergency_shutdown`)
- **Description:**
  When a post-game `NoteDialog` is open (from a recently closed single-player game) and a protected game starts:
  1. `_emergency_shutdown()` calls `window.close()` (`app.py:592`) -> `GameHubWindow.closeEvent` calls `app.closeAllWindows()`.
  2. Closing `NoteDialog` synchronously emits `NoteDialog.finished` -> `NotesController._prompt_closed()` (`notes_controller.py:185-211`).
  3. Line 210 calls `self._on_prompt_finished(game_id)` -> `LifecycleCoordinator.on_note_prompt_finished()` (`lifecycle.py:127`) -> `self._restore_window()` -> `window.reveal()` (`show(); raise_(); activateWindow()`), briefly flashing/stealing focus back to GameRewind right as the protected game launches, and line 211 queues `QTimer.singleShot(0, self, self._show_next)` if another prompt is in `_queue`.
- **Live Evidence (`probe_modal_shutdown.py`, scenario `note_dialog_reveal`):**
  ```text
  GUARD_TRIGGER_EMITTED
  EMERGENCY_SHUTDOWN_ENTER dt=0.000s
  NOTE_DIALOG_FINISHED_CALLING_REVEAL
  EMERGENCY_SHUTDOWN_EXIT dt=0.000s
  APP_EXEC_RETURNED rc=0 emergency_ran=True revealed_after_close=True win_visible=False
  ```
- **Recommended Fix:**
  - Set a shutdown guard flag (e.g., `if emergency_exit[0]: return` in `window.reveal()` and suppress `on_prompt_finished` / `_show_next` in `NotesController` once closing/emergency-exiting).

---

## Verified Controls & Observations (INFO)

### [INFO-01] PASS — Non-Elevated `ToolhelpProcessScanner` Sees Elevated, SYSTEM, PPL, and Cross-Session Processes on Windows 11
- **Location:** `gamehub/core/protection/guard.py:112-155`
- **Live Evidence (`probe_os_and_clock.py`):**
  Running as a non-elevated Medium-IL user (`IsUserAnAdmin=False`, WTS Session 1), `ToolhelpProcessScanner().list_processes()` enumerated **317 processes** across WTS Session 0 and Session 1—including `system`, `smss.exe`, `csrss.exe`, `wininit.exe`, `services.exe`, `lsass.exe`, `winlogon.exe`, `dwm.exe`, `svchost.exe`, and `securityhealthservice.exe`—with **zero `OpenProcess` calls**, even on SYSTEM/PPL processes where `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` fails with `ERROR_ACCESS_DENIED (winerror=5)`.
  This confirms that games launched as **Administrator (elevated)**, kernel anti-cheat services running as **SYSTEM / PPL**, and processes launched by **another user in Fast User Switching** are all visible to `ProtectionGuard`.

### [INFO-02] PASS — Non-Elevated Read-Only `WindowsServiceProbe` Succeeds on Windows 11
- **Location:** `gamehub/core/protection/guard.py:158-235`
- **Live Evidence (`probe_os_and_clock.py`):**
  Non-elevated `WindowsServiceProbe().verify_available()` returned `True`; `OpenServiceW(SERVICE_QUERY_STATUS)` + `QueryServiceStatusEx` succeeded on `EventLog`, `Schedule`, `WinDefend`, and PPL `SecurityHealthService`, and cleanly ignored missing services (`ERROR_SERVICE_DOES_NOT_EXIST = 1060`). Any `ERROR_ACCESS_DENIED` on a hardened anti-cheat service fails closed (`ProtectionCheckError`), though `ORD-01` must be fixed so fail-closed actually exits immediately.

### [INFO-03] PASS — Parented Modal Dialogs (`QFileDialog`, `QMessageBox`, `ScanFolderDialog`, `LastMomentsDialog`) and Modeless `LastTimeCard` Close Cleanly on Emergency Shutdown
- **Locations:** `gamehub/app.py:285-288, 592-593`; `gamehub/ui/{game_page,library_view,mods_view,settings_view,scan_folders_dialog,last_moments}.py`; `gamehub/modules/memory/last_time_card.py`
- **Live Evidence (`probe_modal_shutdown.py` & `probe_remaining.py`):**
  When `_emergency_shutdown()` (`window.close(); app.quit()`) fired via `QueuedConnection` from a background thread while each dialog was open, **all** of the following unwound and exited cleanly in `<= 50ms`:
  - Native Windows `QFileDialog.getOpenFileName` (both direct window parent and child-widget parent, including after 1.5s full render): `EMERGENCY_SHUTDOWN_EXIT dt=0.046s`, `rc=0`
  - Native Windows `QFileDialog.getExistingDirectory`: `dt=0.031s`, `rc=0`
  - `QMessageBox.warning(win, ...)`: `dt=0.015s`, `rc=0`
  - `ScanFolderDialog.exec()`: `dt=0.000s`, `rc=0`
  - `LastMomentsDialog.exec()`: `dt=0.015s`, `rc=0`
  - Modeless `LastTimeCard(..., parent=None)`: `LAST_TIME_CARD_CLOSED rc=0 card_visible=False`
  *(Caveat: This only holds when no parentless guard `QMessageBox` (`ORD-01`) and no slow `ThreadPoolExecutor` task (`ORD-02`) is active.)*

### [INFO-04] PASS — Real End-to-End Case 2 Exit Latency (Idle App, Harmless Dummy Process)
- **Live Evidence (`probe_races_and_vectors.py`, `Case2-RealDummyEndToEnd`):**
  Running real `_run()` with real `ToolhelpProcessScanner` and `WindowsServiceProbe` (default 300ms poll interval) and spawning a harmless renamed copy of `C:\Windows\System32\ping.exe` (`FortniteLauncher.exe`) resulted in `_run()` returning `rc=0` in **`375.0 ms`** after process spawn (when no `ThreadPoolExecutor` job was active).

### [INFO-05] PASS — `QLockFile.setStaleLockTime(0)` Recovers Dead-PID Lock Files After Crash
- **Location:** `gamehub/single_instance.py:17-18`
- **Live Evidence (`probe_races_and_vectors.py`, `crash_keep_lock`):**
  After forcefully crashing primary with `os._exit(99)` (leaving `gamehub.lock` on disk), a new `SingleInstance` successfully reclaimed the lock in `15 ms` (`SECONDARY_RESULT ok=True dt=0.015s`).

### [INFO-06] Observation — Fast User Switching & WTS Session Lock Interaction
- Because `ToolhelpProcessScanner` enumerates all WTS sessions (`INFO-01`), if User A leaves GameRewind running and switches to User B (Fast User Switching) who launches Valorant/Fortnite, User A's `ProtectionGuard` **does** see User B's protected process and triggers `_emergency_shutdown()`. This is **desirable** because kernel anti-cheat drivers (`vgk.sys`, `BEDaisy.sys`, `EasyAntiCheat_EOS.sys`) operate machine-wide across all sessions.
- `SingleInstance` hashes the per-user `data_root` (`%LOCALAPPDATA%\GameRewind`), so separate Windows users do not collide on `\\.\pipe\gamehub-<hash>`.
- However, if `ORD-01` or `ORD-03` triggers in a locked (`Win+L`) or disconnected (Fast User Switching) session, the blocking `QMessageBox.critical` sits invisible on the background desktop forever with `ProtectionGuard` stopped.

---

## Verdict

**FAIL — 11 open findings:**
- **CRITICAL (1):** `ORD-01`
- **HIGH (4):** `ORD-02`, `ORD-03`, `ORD-04`, `ORD-05`
- **MEDIUM (4):** `ORD-06`, `ORD-07`, `ORD-08`, `ORD-09`
- **LOW (2):** `ORD-10`, `ORD-11`


---

## Round 2 Re-Audit Verification

- **Date:** 2026-11-24
- **Role:** Independent Red-Team Security Auditor (read-only verification; zero application/test files modified)
- **Baseline Tests:** `pytest tests/test_zero_presence_guard.py tests/test_security_hardening.py tests/test_app.py tests/test_process_probe.py -q` -> `33 passed in 8.15s`

### Per-Finding Verification Table (`ORD-01` – `ORD-11`)

| ID | Round 1 Severity | Round 2 Status | Verification Evidence (Code & Live Probes) |
|---|---|---|---|
| **ORD-01** | CRITICAL | **CLOSED** | `_notify_guard_block()` (`gamehub/app.py:411-424`) replaces blocking `QMessageBox` with non-blocking `WindowsNotifier().notify_protected_game(...)`; `_emergency_shutdown()` (`gamehub/app.py:624-665`) stops `guard_watchdog`, `hotkeys`, `capture_scheduler`, `voice_player`, `watcher`, and `protection_guard`, then exits immediately via `os._exit(emergency_exit_code[0])`. Live subprocess probes (real notifier, `QT_QPA_PLATFORM=offscreen`): startup refusal exited `rc=0` in `0.656s`; runtime fail-closed exited `rc=2` in `0.734s`. |
| **ORD-02** | HIGH | **CLOSED** | `main()` passes `hard_exit_on_emergency=True` (`gamehub/app.py:1794`), causing `_emergency_shutdown()`'s `finally:` (`gamehub/app.py:654-664`) to close `hotkeys`/`instance` and call `os._exit(emergency_exit_code[0])`, completely bypassing CPython's `ThreadPoolExecutor` `atexit._python_exit` join hang. Additionally, `controls_controller.close(wait=...)` (`controls_controller.py:152-156`), `notes_controller.close(wait=...)` (`notes_controller.py:426-438`), `watcher.close(wait=..., timeout=0.5)` (`watcher.py:54, 77-81`), `protection_guard.close(wait=...)` (`guard.py:538-541`), and `controller.close(wait=...)` (`library_controller.py:161-162`) all respect `wait=not emergency_exit[0]` (`app.py:966-984`). Live subprocess probe with a 60s stuck `ThreadPoolExecutor` worker exited `rc=2` in `0.734s`. |
| **ORD-03** | HIGH | **CLOSED** | `unbiased_monotonic()` (`gamehub/core/protection/guard.py:44-60`) calls `kernel32.QueryUnbiasedInterruptTime` (which pauses during Windows S3 Sleep / Modern Standby / Hibernate) and is the default clock for `ProtectionGuard` (`guard.py:274`). `DEFAULT_GUARD_INTERVAL_SEC` is now `0.15` (`guard.py:30`). Live probe on Windows 11 confirmed `ProtectionGuard._clock == unbiased_monotonic` and `dt=0.0503s` over a 50ms sleep. |
| **ORD-04** | HIGH | **CLOSED** | `deadbydaylight-wingdk-shipping.exe` added to `gamehub/core/protection/protected_games.json:409` (live `match_exe_name` returns `dead_by_daylight`). `ProcessProbe.snapshot()` (`gamehub/core/sessions/processes.py:270-278, 283-316`) only uses `package_id` fallback when a game has no `exe_path` target, and skips `DEFAULT_NEVER_OPEN_EXES` (including `gamelaunchhelper.exe`, `lsass.exe`, `eaanticheat.gameservice.exe`, `vgtray.exe`, and launchers), `protected_exes`, and `never_open_exes` (`watcher.py:177-189`). Live probe: Xbox game with `exe_path + package_id` inspected `0` PIDs (`[]`); `package_id`-only fallback skipped all system/protected/launcher/anti-cheat processes and inspected only `SomeRandomApp.exe`. |
| **ORD-05** | HIGH | **CLOSED** | Synchronous startup TOCTOU re-check `protection_guard.check_once()` added at `gamehub/app.py:864-870` immediately before `mods_engine.recover_incomplete()` (`app.py:881`), `_start_hotkeys()` (`app.py:900`), and `watcher.start()` (`app.py:949`), while `CaptureScheduler` stays paused until a non-strict Full-mode game runs (`app.py:950`). Live subprocess probe where `FortniteLauncher.exe` appeared immediately after `self_check()` returned `code=0`, `started=[]` (zero hotkeys, watcher, or mod recovery executed). |
| **ORD-06** | MEDIUM | **CLOSED** | `_read_startup_guard_prefs()` (`gamehub/app.py:319-339`) queries custom `protection_mode = 'strict'` targets read-only for Case 1 startup (`app.py:439`); `_custom_strict_exes()` (`app.py:364-381`) feeds `extra_strict_exes` into `ProtectionGuard.update_policy()` (`app.py:678-682`), checked in Step 5b (`guard.py:442-450`). Live probes confirmed `_read_startup_guard_prefs` returned `(('customacgame.exe', 'CustomACGame'),)` and `ProtectionGuard.check_once()` returned `ProtectionTrigger(kind='game_exe', identifier='customacgame.exe', display_name='Custom Kernel Game', stage='game')`. |
| **ORD-07** | MEDIUM | **CLOSED** | `LastTimeController._launch()` (`gamehub/modules/memory/last_time_controller.py:271-272`) synchronously invokes `before_strict_launch` (`app.py:810-813`: `hotkeys.suspend()` + `capture_scheduler.pause()`) before submitting `launcher.launch()`. Live probe confirmed exact callback order: `['player.stop', 'before_strict_launch', 'launcher.launch', 'card.accept', 'on_launch_accepted', ...]`. |
| **ORD-08** | MEDIUM | **CLOSED** | `"start_protected_game.exe"` added to `DEFAULT_GLOBAL_ANTI_CHEAT_EXES` (`gamehub/core/protection/catalog.py:47`) and `gamehub/core/protection/protected_games.json:33`, evaluated unconditionally in `ProtectionGuard` Step 4 (`guard.py:404-413`). Live probe with `disabled_entry_ids=('elden_ring',)` confirmed `start_protected_game.exe` still triggers `ProtectionTrigger(kind='anti_cheat_exe', identifier='start_protected_game.exe', ...)`. |
| **ORD-09** | MEDIUM | **CLOSED** | `SessionWatcher` implements `ignore_pid` / `unignore_pid` (`gamehub/core/sessions/watcher.py:56-62, 175-189`) passed to `ProcessProbe.snapshot(ignored_pids=...)` (`processes.py:296-297`), and `app.py:1577` passes `live_watcher=watcher` into `run_dummy_process_protection_test()` (`guard.py:622-623, 652-653`). Live probe across 5 consecutive rapid trials (50ms watcher poll): `ok=True`, `watcher_false=0`, `guard_false=0`. *(INFO note: `guard.py:612-623` holds `live_guard._scan_lock` but not `live_watcher._poll_lock` around `Popen` + `live_watcher.ignore_pid`, leaving a narrow theoretical `CreateProcessW` race if a 3s watcher tick lands mid-`CreateProcessW`.)* |
| **ORD-10** | LOW | **OPEN** | `gamehub/single_instance.py` was **not modified** in Round 2 remediation. While `_emergency_shutdown()` now closes `instance` right before `os._exit()` (`app.py:661`)—shrinking the emergency-exit race window—`SingleInstance.claim_or_activate()` (`single_instance.py:38-45`) still does not re-attempt `self._lock.tryLock(0)` inside its 1-second wait loop, `app.py:988` still calls `instance.close()` last in `finally:` after all `wait=True` worker joins during normal exit, and `main()` (`app.py:1796-1799`) still catches `RuntimeError` into a blocking `QMessageBox.critical(None, ...)`. Live two-process probe (`server_closed_lock_held`) reproduced: `P2=(P2_RAISED RuntimeError The running GameRewind instance did not respond.)`. **Required Fix:** Retry `self._lock.tryLock(0)` inside the 1-second loop in `single_instance.py:38-44`, and close `instance._server` early on shutdown (`GameHubWindow.closeEvent` / top of `finally:`). |
| **ORD-11** | LOW | **CLOSED** | `gamehub/app.py:720` guards `restore_window=lambda: None if emergency_exit[0] else window.reveal()`. Live probe confirmed `revealed_during_emergency=False` when `on_note_prompt_finished` fires while `emergency_exit[0]` is `True`. |

### Round 2 Verdict (Domain d)

**FAIL — 1 open finding:**
- **LOW (1):** `ORD-10` (`SingleInstance` teardown race & `RuntimeError` -> blocking `QMessageBox.critical`)
