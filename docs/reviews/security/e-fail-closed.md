# Security Audit Report — Focus (e): Fail-Closed Behavior

- **Target:** GameRewind (`e:\projects\game hub`)
- **Scope:** `gamehub/core/protection/catalog.py`, `gamehub/core/protection/guard.py`, `gamehub/core/protection/lifecycle.py`, `gamehub/app.py` (and direct shutdown dependencies in `gamehub/core/sessions/watcher.py`, `gamehub/core/capture/scheduler.py`, `gamehub/ui/library_controller.py`)
- **Role:** Independent Red-Team Security Auditor (read-only audit; zero source/test edits)
- **Date:** 2026-11-24
- **Python / Runtime:** `.\.venv\Scripts\python.exe` (Python 3.12, PySide6, Windows)

---

## Executive Summary

While GameRewind's startup catalog parsing, read-only Windows SCM queries, and basic `ProtectionGuard` exception handling correctly implement several fail-closed paths, adversarial testing uncovered **9 open findings** (2 CRITICAL, 2 HIGH, 4 MEDIUM, 1 LOW) that break fail-closed guarantees under real-world failure, low-memory, stall/deadlock, or override-tampering conditions:

| ID | Severity | Area | Summary |
|---|---|---|---|
| **FC-01** | **CRITICAL** | `_emergency_shutdown` / Startup Modal | Blocking `QMessageBox.critical` / `QMessageBox.information` keeps `GameRewind` alive indefinitely while `ProtectionGuard` is stopped and `SessionWatcher` keeps polling |
| **FC-02** | **CRITICAL** | `_emergency_shutdown` OOM / Slot Exception | Any exception (e.g., `MemoryError` allocating `QMessageBox`) inside `_emergency_shutdown(fail_closed=True)` aborts before `window.close()`/`app.quit()`, leaving the app alive forever with **both** `ProtectionGuard` and `guard_watchdog` permanently stopped |
| **FC-03** | **HIGH** | `protected_games_override.json` | User override `by_id[entry.id] = entry` **replaces** bundled entries and can completely neuter detection & Strict mode for all 38 bundled protected games |
| **FC-04** | **HIGH** | Watchdog Stall / Exit Deadlock | No `os._exit()` fallback: hung guard holding `_scan_lock` + `ThreadPoolExecutor` worker (`atexit._python_exit`) causes a **permanent deadlock** at exit; un-timed `SessionWatcher.close()` and double 2s `protection_guard.close()` add 4s–∞ hang |
| **FC-05** | **MEDIUM** | `ProtectionGuard._loop()` | Catches `Exception` only (misses `BaseException` like `SystemExit`); secondary `MemoryError` in `except` block skips immediate `on_failure` |
| **FC-06** | **MEDIUM** | `LifecycleCoordinator.is_strict_game()` | Catches `StorageError` and returns `False` (**fail-open**), keeping GameRewind running on Play launch instead of exiting |
| **FC-07** | **MEDIUM** | Bundled Catalog Validation | `strict_load=True` accepts JSON boolean `schema_version: true`, allows bundled JSON to wipe hardcoded `always_strict_launchers`/`anti_cheat_services`/`global_anti_cheat_exes` to empty, and leaks `RecursionError` on deeply nested JSON |
| **FC-08** | **MEDIUM** | Windows SCM & Toolhelp32 Edge Cases | `WindowsServiceProbe` misses non-`SERVICE_STOPPED` transitional states (`STOP_PENDING`, `PAUSED`, `PAUSE_PENDING`, `CONTINUE_PENDING`); `ToolhelpProcessScanner` silently returns empty `()` on `Process32FirstW` `ERROR_NO_MORE_FILES` |
| **FC-09** | **LOW** | Runtime Fail-Closed Exit Code | `_emergency_shutdown(fail_closed=True)` calls `app.quit()`, returning exit code `0` instead of `2` |

---

## Detailed Findings

### [FC-01] CRITICAL — Blocking `QMessageBox` in `_emergency_shutdown(fail_closed=True)` (and Startup Refusal/Fail-Closed) Keeps Process Alive Indefinitely With Guard Dead and `SessionWatcher` Polling

- **Locations:**
  - `gamehub/app.py:373-381` (`_notify_guard_block`)
  - `gamehub/app.py:398-406` (startup fail-closed)
  - `gamehub/app.py:408-421` (startup protected-game refusal)
  - `gamehub/app.py:574-594` (`_emergency_shutdown`)
- **Root Cause:**
  In `_emergency_shutdown(fail_closed=True)`:
  1. Line 577 stops `guard_watchdog`.
  2. Line 584 calls `protection_guard.close()` (stopping the guard thread).
  3. Lines 585–591 call `_notify_guard_block("fail_closed", ...)`, which calls **`QMessageBox.critical(None, "GameRewind", text)`** — a **blocking modal dialog with no timeout**.
  4. Lines 592–593 (`window.close()`, `app.quit()`) and the `finally:` teardown (`watcher.close()`, `hotkeys.close()`, `instance.close()`) **do not execute until the user clicks OK**.
  5. `SessionWatcher` (`game-session-watcher`) is **not** stopped or paused in `_emergency_shutdown`, so it continues polling processes every 3 seconds while the modal dialog blocks!
  6. Similarly, on startup when a protected game (e.g., `FortniteLauncher.exe`) is **already running** (`app.py:414-420`), `QMessageBox.information(None, ...)` keeps the `GameRewind` process alive in memory indefinitely alongside the protected game until the user dismisses the dialog.
  7. `_emergency_shutdown` also lacks a re-entrancy check (`if emergency_exit[0]: return`), allowing stacked calls if multiple shutdown triggers queue while a modal loop runs.
- **Concrete Evidence (Live Subprocess Probes 7a-detail & 7b):**
  Spawned isolated subprocesses executing `gamehub.app._run(..., show_guard_dialog=None)` (real `QMessageBox` path, `QT_QPA_PLATFORM=offscreen`, `ProcessProbe` mocked with a counting probe):
  - **Runtime fail-closed (`OpenServiceW("vgc")` -> `ProtectionCheckError(winerror=5)`):**
    ```text
    MONITOR dt=0.80s: protection_guard_alive=False session_watcher_alive=True watcher_polls=1 threads=['MainThread', 'Thread-1 (_readerthread)', 'Thread-2 (_readerthread)', 'audit-monitor', 'game-session-watcher', 'library_0']
    MONITOR dt=2.00s: protection_guard_alive=False session_watcher_alive=True watcher_polls=1 threads=['MainThread', 'audit-monitor', 'game-session-watcher', 'library_0']
    MONITOR dt=4.00s: protection_guard_alive=False session_watcher_alive=True watcher_polls=2 threads=['MainThread', 'audit-monitor', 'game-session-watcher', 'library_0']
    STILL ALIVE after 4.95s (killed)!
    ```
  - **Startup refusal (`FortniteLauncher.exe` running):**
    ```text
    [7b STARTUP REFUSED MODAL CONFIRMED!] Process STILL ALIVE after 2.66s while FortniteLauncher.exe is running (waiting on QMessageBox.information)!
    ```
- **Security Impact:**
  If a protection failure occurs while GameRewind is minimized, behind a fullscreen launcher/game, or while the user launches a protected title from desktop/Epic/Riot, the modal dialog stays open unattended. GameRewind remains resident indefinitely with `ProtectionGuard` and `guard_watchdog` dead, `GameHubWindow` open, and `SessionWatcher` actively polling. This directly violates the Zero-Presence and Fail-Closed invariants.
- **Recommended Fix:**
  1. Never block process exit on a modal dialog during fail-closed shutdown or protected-game refusal.
  2. In `_emergency_shutdown`, guard re-entrancy (`if emergency_exit[0]: return`), immediately stop `guard_watchdog`, `hotkeys`, `capture_scheduler`, `watcher`, `voice_player`, hide/close `window`, and exit immediately (`app.exit(2 if fail_closed else 0)` + `os._exit()` failsafe).
  3. To inform the user without keeping the process alive, fire a best-effort non-blocking Windows toast notification (`WindowsNotifier`) with a short timeout (or write a last-exit marker shown on the next clean launch) and exit immediately. If a startup modal is retained for UX when no protected game is detected, auto-close it via a short `QTimer` (e.g., 3–5s) — and never show a blocking modal when a protected game is already detected or during runtime fail-closed.

---

### [FC-02] CRITICAL — Exception Inside `_emergency_shutdown(fail_closed=True)` (e.g., `MemoryError`) Leaves App Alive Indefinitely With Guard and Watchdog Permanently Disabled

- **Locations:**
  - `gamehub/app.py:574-603` (`_emergency_shutdown`, `guard_bridge` connections)
  - `gamehub/app.py:620-626` (`_check_guard_heartbeat`)
- **Root Cause:**
  `_emergency_shutdown` executes teardown steps sequentially without `try/finally`:
  ```python
  if guard_watchdog is not None:
      guard_watchdog.stop()          # line 577 — watchdog now STOPPED
  ...
  protection_guard.close()           # line 584 — guard now STOPPED
  if fail_closed:
      _notify_guard_block(...)       # line 586 — allocates QMessageBox / UI!
  window.close()                     # line 592 — NEVER REACHED on exception
  app.quit()                         # line 593 — NEVER REACHED on exception
  ```
  In PySide6/Qt, an unhandled Python exception raised inside a signal slot (`guard_bridge.failed` or `guard_watchdog.timeout`) is caught by the Qt/Shiboken bridge, printed to `stderr`, and **`app.exec()` continues running normally**. Under low-memory conditions (`MemoryError` during scan -> `on_failure` -> `_emergency_shutdown(fail_closed=True)` -> `MemoryError` constructing `QMessageBox.critical` or calling `hotkeys.suspend()`/`capture_scheduler.pause()`/`voice_player.stop()`), lines 592–593 never execute, while lines 577 and 584 have already disabled both the guard and the watchdog.
- **Concrete Evidence (Live Probe 6 — Isolated):**
  Simulated `MemoryError("oom during scan")` from scanner followed by `MemoryError("cannot allocate QMessageBox under OOM")` in `_notify_guard_block`:
  ```text
  Traceback (most recent call last):
    File "e:\projects\game hub\gamehub\app.py", line 601, in <lambda>
      lambda _reason: _emergency_shutdown(fail_closed=True),
    File "e:\projects\game hub\gamehub\app.py", line 586, in _emergency_shutdown
      _notify_guard_block(
    ...
  MemoryError: cannot allocate QMessageBox under OOM
    [CRITICAL FAIL-OPEN CONFIRMED!] App is STILL ALIVE 3.20s after MemoryError! visible_windows=['GameHubWindow']
    6 result: oom_called=[(1.42, 'fail_closed')] stayed_alive_unprotected=True code=0
  ```
- **Security Impact:**
  A genuine low-memory condition (Focus Area 6) or any runtime error in teardown converts a fail-closed event into a **permanent fail-open state**: GameRewind stays open and usable with zero protection monitoring and no watchdog recovery.
- **Recommended Fix:**
  1. At the very top of `_emergency_shutdown`, arm a daemon failsafe timer (`threading.Timer(1.0, os._exit, args=(exit_code,))`) before doing anything else.
  2. Wrap every teardown call (`hotkeys.suspend`, `capture_scheduler.pause`, `voice_player.stop`, `protection_guard.close`, notification) in individual `try: ... except BaseException: pass` blocks.
  3. Put `window.close()` and `app.exit(exit_code)` inside a `finally:` block, and if `window.close()` / `app.exit()` raises, invoke `os._exit(exit_code)` immediately.

---

### [FC-03] HIGH — User Override (`protected_games_override.json`) Replaces Bundled Entries and Can Completely Disable Protection for All 38 Bundled Games

- **Locations:**
  - `gamehub/core/protection/catalog.py:323-334` (specifically lines 326–327)
- **Root Cause:**
  In `ProtectedGamesCatalog.load()`:
  ```python
  if override_path is not None and override_path.is_file():
      try:
          override = _parse_file(override_path)
          for entry in override.entries:
              by_id[entry.id] = entry
  ```
  Although `always_strict_launchers` and `optional_strict_launchers` are ignored in the override file, and `anti_cheat_services` / `global_anti_cheat_exes` are unioned (cannot be emptied — verified in Probe 2b), **`by_id[entry.id] = entry` completely overwrites bundled `ProtectedGameEntry` objects with matching `id`s**.
  A malicious, tampered, or mistakenly authored `protected_games_override.json` specifying bundled game IDs (`"valorant"`, `"fortnite"`, `"apex_legends"`, `"cs2"`, `"elden_ring"`, `"call_of_duty"`, etc.) with empty executable/store-ID arrays and `"default_mode": "full"` strips all game executables, launcher-stage executables, per-game anti-cheat executables, and store identifiers from the catalog.
- **Concrete Evidence (Live Probe 2c):**
  Loaded `ProtectedGamesCatalog.load(override_path=neuter_path, strict_load=True)` where `neuter_path` redefined all 38 bundled IDs with empty arrays and `"default_mode": "full"`, then ran `ProtectionGuard.check_once()` against 10 simultaneously running major protected executables (`FortniteBootstrapper.exe`, `FortniteLauncher.exe`, `FortniteClient-Win64-Shipping.exe`, `FortniteClient-Win64-Shipping_EAC_EOS.exe`, `VALORANT.exe`, `VALORANT-Win64-Shipping.exe`, `r5apex.exe`, `cs2.exe`, `eldenring.exe`, `cod.exe`):
  ```text
  [2c NEUTER ALL GAMES] guard.check_once() with 10 major protected game exes -> None
  [2c NEUTER] match_game(EPIC, 'Fortnite') -> None
  [2c NEUTER] effective_mode('auto', EPIC, 'Fortnite', ('FortniteLauncher.exe',)) -> 'full'
  [2c NEUTER] match_exe_name('VALORANT-Win64-Shipping.exe') -> None
  [2c NEUTER] match_game(STEAM, '1172470') (Apex) -> None
  [2c NEUTER] RiotClientServices.exe still triggers -> ProtectionTrigger(kind='strict_launcher', identifier='riotclientservices.exe', display_name='Riot Client', stage='launcher', entry_id=None)
  ```
- **Security Impact:**
  - `ProtectionGuard` stops detecting all per-game launcher-stage exes, per-game anti-cheat exes (e.g., `FortniteClient-Win64-Shipping_EAC_EOS.exe`), and game exes for every overwritten title (only `always_strict_launchers`, `global_anti_cheat_exes`, and the 4 SCM services survive).
  - `LifecycleCoordinator`, `SessionWatcher`/`ProcessProbe`, and `ModsEngine` all rely on `catalog.match_game()` / `effective_mode()`: overwritten titles silently flip from Strict to Full, allowing `ProcessProbe` to open handles and `ModsEngine` to treat protected online games as unprotected!
  - Even an accidental partial override (e.g., a user trying to add a new beta exe for `"fortnite"`) silently wipes all bundled Fortnite exes and IDs.
- **Recommended Fix:**
  Make `protected_games_override.json` **strictly additive**: when `entry.id` already exists in `by_id`, merge the override into the bundled entry by unioning all ID tuples (`steam_app_ids`, `epic_app_names`, `riot_product_ids`, `xbox_package_prefixes`) and exe tuples (`launcher_stage_exes`, `anti_cheat_exes`, `game_exes`, `exe_names`), preserving `default_mode="strict"` whenever the bundled entry is `"strict"` (never allowing an override to downgrade or delete bundled protection entries).

---

### [FC-04] HIGH — No `os._exit()` Fallback Causes Permanent `atexit` Deadlock on Hung Guard + Worker Contention, Unbounded `SessionWatcher.close()`, and Double 2s `close()` Delay

- **Locations:**
  - `gamehub/app.py:584`, `863-889` (`_emergency_shutdown` & `_run` `finally:` block)
  - `gamehub/core/protection/guard.py:485-489` (`ProtectionGuard.close`), `557-568` (`run_dummy_process_protection_test`)
  - `gamehub/core/sessions/watcher.py:52`, `67-71` (`SessionWatcher._thread` & `close`)
  - `gamehub/core/capture/scheduler.py:22`, `94-97` (`CaptureScheduler._worker`)
  - `gamehub/ui/library_controller.py:39`, `161-162` (`LibraryController._worker`)
- **Root Cause:**
  1. **Permanent `atexit` deadlock (no `os._exit()`):** In Python 3.12, `ThreadPoolExecutor` spawns **non-daemon** threads and registers `concurrent.futures.thread._python_exit` via `atexit`, which calls **`t.join()` with NO timeout** on every live pool thread at interpreter exit — **even after `shutdown(wait=False, cancel_futures=True)`** (`app.py:870`, `884`, `scheduler.py:97`). If the `protection-guard` daemon thread hangs inside `check_once()` (holding `_scan_lock`) and `move_worker` calls `run_dummy_process_protection_test()` (`guard.py:558: with live_guard._scan_lock:`), `move_worker` blocks forever waiting on `_scan_lock`. Even after `guard_watchdog` fires `_emergency_shutdown(fail_closed=True)` and `_run()` returns, `sys.exit()` / `SystemExit` enters `atexit._python_exit` and **deadlocks permanently** waiting for `move_worker`! The same exit stall occurs if `move_worker` is running `store_location.move()` or `fetch_steamgriddb_cover()`, or if `library`/`capture` workers are blocked.
  2. **Double 2.0s `protection_guard.close()` block:** `protection_guard.close()` calls `self._thread.join(timeout=2.0)`. It is invoked once in `_emergency_shutdown()` (`app.py:584`) and **a second time** in `finally:` (`app.py:866`), adding **4.0 seconds** of dead wait on top of the 2.5–3.5s watchdog stale window (~7–8.4s total!).
  3. **Unbounded `SessionWatcher.close()`:** `watcher.py:52` creates a **non-daemon** thread and `watcher.py:71` calls `self._thread.join()` with **no timeout** (`app.py:882`), allowing any blocked watcher poll to hang emergency shutdown indefinitely.
- **Concrete Evidence (Live Probes 4a & 4b):**
  - **Probe 4a (hung scanner, isolated):**
    ```text
    exit_code=0 (expected 2? got 0) dt_since_hang=8.38s dialog_called_at_dt=[(6.36, 'fail_closed')]
    ```
    (`~4.3s` to stale detection + `2.0s` first `close()` = `6.36s`, then `+2.0s` second `close()` in `finally:` = `8.38s`.)
  - **Probe 4b (hung scanner holding `_scan_lock` + `ThreadPoolExecutor` worker acquiring `_scan_lock`, subprocess):**
    ```text
    WORKER: waiting on live_guard._scan_lock...
    DIALOG: fail_closed at dt=5.12s
    _run() RETURNED code=0 at dt=7.14s; now calling sys.exit(code)...
    [DEADLOCK CONFIRMED!] Child STILL ALIVE after 12.16s (killed)!
    ```
- **Security Impact:**
  A hung Win32 SCM/Toolhelp call or contended worker can delay fail-closed termination by 8+ seconds or **prevent the process from ever exiting**, defeating the watchdog completely.
- **Recommended Fix:**
  1. Arm a daemon hard-exit failsafe timer (`threading.Timer(1.0, os._exit, args=(exit_code,))`) in `_emergency_shutdown`, and at the end of `_run`'s `finally:` block, if `emergency_exit[0]` is `True` and any worker/guard thread is still alive (or unconditionally on emergency exit after flushing logs/unlocking `SingleInstance`), call **`os._exit(exit_code)`** so Python's `atexit._python_exit` can never block or deadlock exit.
  2. In `ProtectionGuard.close(timeout: float = 2.0)`, use a short timeout (e.g., `0.25s`) during emergency shutdown and skip re-joining in `finally:` if already closed/timed out.
  3. Make `SessionWatcher._thread` `daemon=True` and add a bounded `timeout` to `SessionWatcher.close()`.
  4. In `run_dummy_process_protection_test()` (`guard.py:558`), acquire `live_guard._scan_lock.acquire(timeout=1.0)` and abort the self-test cleanly on timeout instead of blocking forever.

---

### [FC-05] MEDIUM — `ProtectionGuard._loop()` Misses `BaseException` and Can Drop Immediate `on_failure` on Secondary `MemoryError`

- **Locations:**
  - `gamehub/core/protection/guard.py:431-457`
- **Root Cause:**
  Line 451 catches `except Exception as exc:` only. Any `BaseException` (`SystemExit`, `KeyboardInterrupt`, async thread kill) bypasses the handler completely: `self._failed_reason` remains `None` and `on_failure` is never called (leaving exit to the 1.0s `guard_watchdog` poll). Furthermore, under low memory (`MemoryError`), lines 452–455 (`reason = f"{type(exc).__name__}: {exc}"`, `LOGGER.error(...)`) allocate memory before calling `on_failure(reason)`; a secondary `MemoryError` aborts the `except` block before `on_failure` runs.
- **Concrete Evidence (Live Probe 3):**
  ```text
  [RuntimeError  ] on_failure_called=True  thread_alive=False is_healthy=False failed_reason='RuntimeError: boom'
  [OSError       ] on_failure_called=True  thread_alive=False is_healthy=False failed_reason='OSError: io fail'
  [MemoryError   ] on_failure_called=True  thread_alive=False is_healthy=False failed_reason='MemoryError: oom'
  [SystemExit    ] on_failure_called=False thread_alive=False is_healthy=False failed_reason=None
  [BaseException ] on_failure_called=False thread_alive=False is_healthy=False failed_reason=None
  ```
- **Recommended Fix:**
  Catch `except BaseException as exc:`, set `self._failed_reason = "protection_guard_failed"` first using a pre-allocated literal string, best-effort format/log inside a nested `try/except BaseException`, and unconditionally invoke `on_failure(reason)` (also wrapped in `try/except BaseException`).

---

### [FC-06] MEDIUM — `LifecycleCoordinator.is_strict_game()` Fails Open (`return False`) on `StorageError`

- **Locations:**
  - `gamehub/core/protection/lifecycle.py:67-78`
- **Root Cause:**
  ```python
  def is_strict_game(self, game_id: str) -> bool:
      try:
          game = self._library.get_game(game_id)
          if game is None:
              return False
          exes = self._library.list_target_basenames().get(game_id, ())
      except StorageError:
          return False
  ```
  If SQLite raises `StorageError` (e.g., transient lock contention during library refresh or disk I/O glitch) when the user launches a game via Play (`on_play_launched`), `is_strict_game()` fails **open** (`False`). `on_play_launched()` then minimizes GameRewind instead of exiting immediately, leaving hotkeys and WGC capture active. For user-marked Strict games not present in the bundled catalog, `ProtectionGuard` will not catch the launch either.
- **Concrete Evidence (Live Probe 8):**
  ```text
  [8 StorageError] is_strict_game()=False on_play_launched_exited=False actions=['minimize']
  ```
- **Recommended Fix:**
  Fail closed (`return True`) on `StorageError` in `is_strict_game()` for launch/enforcement decisions (e.g., `is_strict_game(game_id, *, fail_closed: bool = True)` used by `on_play_launched` / `on_game_started`).

---

### [FC-07] MEDIUM — Bundled Catalog `strict_load=True` Accepts `schema_version: true`, Allows Emptying Hardcoded Defaults, and Leaks Unhandled `RecursionError`

- **Locations:**
  - `gamehub/core/protection/catalog.py:163`, `307-321`
  - `gamehub/app.py:398`
- **Root Cause:**
  1. **Boolean schema bypass (`catalog.py:163`):** `raw.get("schema_version") not in {1, 2}` accepts JSON `true` because `True == 1` in Python.
  2. **Empty default wipe (`catalog.py:307-314`):** In `strict_load=True`, if a bundled JSON has 1 valid game entry plus `"always_strict_launchers": {}`, `"anti_cheat_services": []`, and `"global_anti_cheat_exes": []`, lines 307–314 overwrite `DEFAULT_ALWAYS_STRICT_LAUNCHERS` (Riot Client), `DEFAULT_ANTI_CHEAT_SERVICES` (4 kernel services), and `DEFAULT_GLOBAL_ANTI_CHEAT_EXES` (7 exes) with empty collections instead of failing closed.
  3. **Unhandled `RecursionError` (`catalog.py:315`):** `except (OSError, TypeError, ValueError)` does not catch `RecursionError` on deeply nested JSON, bypassing `CatalogLoadError` and `app.py:398` (crashes with raw traceback instead of clean fail-closed exit code 2).
- **Concrete Evidence (Live Probe 1):**
  ```text
  [LOADED!] schema_bool_true: entries=1 always_strict={'riot': (...)} services=('EasyAntiCheat_EOS', 'EasyAntiCheat', 'BEService', 'vgc') global_ac=7
  [LOADED!] empty_strict_launchers_and_services: entries=1 always_strict={} services=() global_ac=0
  [RAISED]  deep_recursion_json: RecursionError: maximum recursion depth exceeded while decoding a JSON array from a unicode string
  ```
- **Recommended Fix:**
  1. Enforce exact integer type: `ver = raw.get("schema_version"); if type(ver) is not int or ver not in {1, 2}: raise ValueError(...)`.
  2. In `strict_load=True`, fail closed with `CatalogLoadError` if `always_strict_launchers`, `anti_cheat_services`, or `global_anti_cheat_exes` are empty (and union with hardcoded `DEFAULT_*` baselines so Riot Client and core anti-cheat services cannot be stripped).
  3. Catch `RecursionError` alongside `(OSError, TypeError, ValueError)` in `catalog.py:315` (and `332` for override).

---

### [FC-08] MEDIUM — `WindowsServiceProbe` Misses Transitional Non-Stopped Service States & `ToolhelpProcessScanner` Silently Returns Empty Process List on `ERROR_NO_MORE_FILES`

- **Locations:**
  - `gamehub/core/protection/guard.py:136-155` (`ToolhelpProcessScanner.list_processes`)
  - `gamehub/core/protection/guard.py:229-230` (`WindowsServiceProbe.running_services`)
- **Root Cause:**
  1. **SCM service states (`guard.py:229`):** Only `{_SERVICE_RUNNING (4), _SERVICE_START_PENDING (2)}` are treated as active. An anti-cheat service in `SERVICE_STOP_PENDING (3)` (still loaded/tearing down), `SERVICE_CONTINUE_PENDING (5)`, `SERVICE_PAUSE_PENDING (6)`, or `SERVICE_PAUSED (7)` is NOT stopped (`SERVICE_STOPPED = 1`), yet is ignored.
  2. **Empty Toolhelp32 snapshot (`guard.py:137-155`):** `list_processes()` checks `snap == _INVALID_HANDLE_VALUE` (not `snap in (None, 0, _INVALID_HANDLE_VALUE)`) and if `Process32FirstW` returns `0` with `ERROR_NO_MORE_FILES (18)`, it silently returns `()` instead of raising `ProtectionCheckError` — even though a valid Windows snapshot must always contain at least the current process!
- **Concrete Evidence (Live Probe 5e & 5f):**
  ```text
  [5e state=STOP_PENDING(3)] detected=False (frozenset())
  [5e state=CONTINUE_PENDING(5)] detected=False (frozenset())
  [5e state=PAUSE_PENDING(6)] detected=False (frozenset())
  [5e state=PAUSED(7)] detected=False (frozenset())
  [5f Process32FirstW=0 err=NO_MORE_FILES(18)] returned () (no error raised!)
  ```
- **Recommended Fix:**
  1. In `WindowsServiceProbe.running_services()`, define `_SERVICE_STOPPED = 0x00000001` and treat any `status.dwCurrentState != _SERVICE_STOPPED` as active (fail-closed on all non-stopped states).
  2. In `ToolhelpProcessScanner.list_processes()`, reset `ctypes.set_last_error(0)` before Win32 calls, guard `if snap in (None, 0, _INVALID_HANDLE_VALUE):`, and fail closed if `not results` (`raise ProtectionCheckError("process_snapshot_empty")`).

---

### [FC-09] LOW — Runtime Fail-Closed Returns Exit Code `0` Instead of `2`

- **Locations:**
  - `gamehub/app.py:406` (startup fail-closed returns `2`)
  - `gamehub/app.py:593`, `862` (runtime fail-closed calls `app.quit()` -> `app.exec()` returns `0`)
- **Concrete Evidence (Live Probe 4a & Probe 6):**
  `_run()` returned `exit_code=0` after runtime watchdog fail-closed, inconsistent with startup fail-closed (`exit_code=2`).
- **Recommended Fix:**
  Use `app.exit(2 if fail_closed else 0)` and pass `2 if fail_closed else 0` to any `os._exit()` failsafe.

---

## Verified Passing Controls & Observations (INFO)

1. **Bundled catalog startup fail-closed (Probe 1):** Missing file, empty file, invalid JSON, non-UTF-8 bytes, `schema_version` of `0`, `3`, or `"2"`, missing `games` key, `games: []`, and malformed-only `games` all raise `CatalogLoadError` in `strict_load=True`, causing `app._run()` to return exit code `2` before creating `SingleInstance`, `Database`, or `GameHubWindow`.
2. **Corrupt override & top-level override immutability (Probes 2a & 2b):** Corrupt JSON in `protected_games_override.json` logs `protected_catalog_override_invalid` and falls back to the bundled catalog. Top-level `"always_strict_launchers": {}`, `"optional_strict_launchers": {}`, `"anti_cheat_services": []`, and `"global_anti_cheat_exes": []` in the override file do **not** clear bundled defaults (`always_strict_riot=5`, `services=('EasyAntiCheat_EOS', 'EasyAntiCheat', 'BEService', 'vgc')`, `global_ac=7`).
3. **Windows SCM read-only fail-closed checks (Probes 5a–5d):** Real read-only `WindowsServiceProbe` works cleanly on this host (`SC_MANAGER_CONNECT` + `SERVICE_QUERY_STATUS`). `OpenSCManagerW` returning `0` fails both `verify_available()` (`False`) and `running_services()` (`ProtectionCheckError`). `OpenServiceW` returning `0` with `ERROR_ACCESS_DENIED (5)` raises `ProtectionCheckError` (only `ERROR_SERVICE_DOES_NOT_EXIST = 1060` is ignored). `QueryServiceStatusEx` returning `0` raises `ProtectionCheckError`.
4. **Startup `MemoryError`:** `MemoryError` during `ProtectedGamesCatalog.load()` or `ProtectionGuard.self_check()` is uncaught and terminates Python with exit code `1` before creating any window or background thread.
5. **In-process Qt modal dialog during non-fail-closed trigger (Probe 4c):** When an in-process `QDialog.exec()` is open and `guard_bridge.triggered` fires `_emergency_shutdown(fail_closed=False)`, `window.close()` invokes `GameHubWindow.closeEvent` -> `app.closeAllWindows()`, which closed the Qt modal dialog cleanly in `1.45s`. (Native Win32 COM modal dialogs like `QFileDialog.getOpenFileName` are still best protected by the `os._exit()` failsafe recommended in `FC-04`.)
6. **`_disabled_catalog_entries` on `StorageError` (`app.py:328-344`):** Returns `frozenset()` on `StorageError` (correctly fails closed, keeping all catalog entries active).

---

## Verdict

**FAIL** — **9 open findings**: `FC-01` (CRITICAL), `FC-02` (CRITICAL), `FC-03` (HIGH), `FC-04` (HIGH), `FC-05` (MEDIUM), `FC-06` (MEDIUM), `FC-07` (MEDIUM), `FC-08` (MEDIUM), `FC-09` (LOW).


---

## Round 2 Re-Audit Verification

- **Date:** 2026-11-24
- **Role:** Independent Red-Team Security Auditor (read-only verification; zero application/test files modified)
- **Baseline Tests:** `pytest tests/test_zero_presence_guard.py tests/test_security_hardening.py tests/test_app.py tests/test_process_probe.py -q` -> `33 passed in 8.15s`

### Per-Finding Verification Table (`FC-01` – `FC-09`)

| ID | Round 1 Severity | Round 2 Status | Verification Evidence (Code & Live Probes) |
|---|---|---|---|
| **FC-01** | CRITICAL | **CLOSED** | `_notify_guard_block()` (`gamehub/app.py:411-424`) uses non-blocking `WindowsNotifier().notify_protected_game(...)` instead of `QMessageBox`. `_emergency_shutdown()` (`gamehub/app.py:624-665`) guards re-entrancy (`if emergency_exit[0]: return`), immediately stops `guard_watchdog`, `hotkeys`, `capture_scheduler`, `voice_player`, `watcher.close(wait=False)`, and `protection_guard.close(wait=False)`, and terminates via `os._exit(emergency_exit_code[0])`. Live subprocess probes (real notifier, `QT_QPA_PLATFORM=offscreen`): startup refusal exited `rc=0` in `0.656s`; runtime fail-closed exited `rc=2` in `0.734s`. |
| **FC-02** | CRITICAL | **CLOSED** | `_emergency_shutdown()` (`gamehub/app.py:629-664`) wraps `_notify_guard_block(...)` in `try/except BaseException: pass` and executes `hotkeys.close()`, `instance.close()` (each inside `try/except BaseException: pass`), and `os._exit(emergency_exit_code[0])` inside `finally:` whenever `hard_exit_on_emergency=True` (`main()`, `app.py:1794`). Live subprocess probe raising `MemoryError` inside both `list_processes()` and `_notify_guard_block()` terminated cleanly with `rc=2` in `0.672s`. |
| **FC-03** | HIGH | **OPEN** | **Incomplete Fix — New-ID Override Hijack Bypass Confirmed:** While same-ID replacement is fixed by `_merge_override_entry()` (`gamehub/core/protection/catalog.py:307-336, 383-384`)—verified live that same-ID neutering keeps Fortnite/Valorant/Apex `strict`—an override file can still define a **new** entry with a different `"id"` (e.g., `"id": "hijack_bypass"`) and `"default_mode": "full"` containing bundled `steam_app_ids`, `epic_app_names`, `riot_product_ids`, and `game_exes`. Because `by_id` preserves insertion order, new override entries follow bundled entries in `self._entries`, and `ProtectedGamesCatalog.__init__()` (`catalog.py:283-305`) uses unconditional assignment (`self._by_steam[app_id] = entry`, `self._by_epic[epic_name] = entry`, `self._by_riot[riot_id] = entry`, `self._by_ubisoft[ubi_id] = entry`, `self._by_battlenet[bnet_id] = entry`, `self._by_ea[ea_id] = entry`, `self._by_game_exe[exe] = entry`, `self._by_exe[exe] = entry`). **Live Reproduction Output:** `New-ID hijack -> Fortnite effective_mode: full`, `Valorant effective_mode: full`, `Apex effective_mode: full`, `CS2 effective_mode: full`, `LifecycleCoordinator.is_strict_game(VALORANT): False`, `SessionWatcher strict_games: frozenset()` (Valorant moved into `active_targets`). **Required Fix:** (1) In `ProtectedGamesCatalog.__init__()` (`catalog.py:283-305`), never let a non-strict or later entry overwrite an existing bundled strict entry in `_by_steam`, `_by_epic`, `_by_riot`, `_by_ubisoft`, `_by_battlenet`, `_by_ea`, `_by_game_exe`, or `_by_exe` (use `.setdefault(...)` or prefer `default_mode == "strict"`); (2) in `ProtectedGamesCatalog.load()` (`catalog.py:385-386`), force new override entries to `default_mode="strict"` so `protected_games_override.json` can never introduce `"full"` downgrades. |
| **FC-04** | HIGH | **CLOSED** | `hard_exit_on_emergency=True` (`gamehub/app.py:1794`) + `os._exit(emergency_exit_code[0])` (`app.py:664`) eliminates `atexit._python_exit` deadlocks on blocked `ThreadPoolExecutor` threads; `protection_guard.close(wait=False)` (`app.py:640, 966`) eliminates the double 2.0s join; `SessionWatcher._thread` is `daemon=True` (`watcher.py:54`) with bounded `close(wait=..., timeout=0.5)` (`watcher.py:77-81`). Live subprocess probe with a hung scanner (60s sleep) + 60s stuck `ThreadPoolExecutor` worker exited via `guard_watchdog` -> `os._exit(2)` in `3.078s` with zero deadlock. |
| **FC-05** | MEDIUM | **CLOSED** | `ProtectionGuard._loop()` (`gamehub/core/protection/guard.py:498-509`) catches `except BaseException as exc:`, formats `reason` inside `try/except BaseException` falling back to pre-allocated literal `"protection_guard_fatal"`, records `self._failed_reason`, wraps `LOGGER.error` in `try/except BaseException`, and calls `on_failure(reason)`. Live probe confirmed `on_failure=True` and `is_healthy=False` for `RuntimeError`, `OSError`, `MemoryError`, `SystemExit`, `BaseException`, and `EvilOOM` (raises `MemoryError` inside `__str__`, yielding `reason=['protection_guard_fatal']`). |
| **FC-06** | MEDIUM | **CLOSED** | `LifecycleCoordinator.is_strict_game()` (`gamehub/core/protection/lifecycle.py:73-74`) catches `StorageError` and returns `True` (fail-closed). Live probe confirmed `is_strict_game()=True`, `on_play_launched_exited=True`, `actions=['exit_app']`. |
| **FC-07** | MEDIUM | **CLOSED** | `_parse_file()` (`gamehub/core/protection/catalog.py:168-170`) checks `type(schema_ver) is not int or schema_ver not in {1, 2}` (rejecting `True`); `ProtectedGamesCatalog.load()` (`catalog.py:348-370`) unions parsed fields onto `DEFAULT_*` baselines so empty bundled arrays cannot wipe hardcoded defaults; `catalog.py:371, 391` catch `RecursionError`. Live probe confirmed: `schema_version: true` -> `CatalogLoadError`; empty bundled defaults preserved `always_strict_riot=8`, `services=('EasyAntiCheat_EOS', 'EasyAntiCheat', 'BEService')`, `global_ac=7`; 5000-level nested JSON -> `CatalogLoadError (RecursionError)` on bundled and clean fallback (`entries=39`) on override. |
| **FC-08** | MEDIUM | **CLOSED** | `WindowsServiceProbe.running_services()` (`gamehub/core/protection/guard.py:37, 252-253`) treats any `status.dwCurrentState != _SERVICE_STOPPED` as active; `ToolhelpProcessScanner.list_processes()` (`guard.py:174-175`) raises `ProtectionCheckError("Toolhelp32 returned an empty process snapshot")` when `results` is empty. Live probes confirmed `START_PENDING(2)`, `STOP_PENDING(3)`, `RUNNING(4)`, `CONTINUE_PENDING(5)`, `PAUSE_PENDING(6)`, and `PAUSED(7)` all return `detected=True` (`STOPPED(1)` -> `False`), and empty Toolhelp32 snapshot with `ERROR_NO_MORE_FILES` raises `ProtectionCheckError`. |
| **FC-09** | LOW | **CLOSED** | `emergency_exit_code[0] = 2 if fail_closed else 0` (`gamehub/app.py:628`) is returned via `os._exit(emergency_exit_code[0])` (`app.py:664`) and `app.py:962`, matching startup fail-closed (`app.py:451, 870`). Live subprocess probes confirmed `rc=2` on runtime fail-closed and `rc=0` on startup refusal / protected trigger. |

### Round 2 Verdict (Domain e)

**FAIL — 1 open finding:**
- **HIGH (1):** `FC-03` (new-ID entry in `protected_games_override.json` with `"default_mode": "full"` overwrites bundled strict entries in `ProtectedGamesCatalog.__init__` lookup maps, flipping `effective_mode` to `"full"` and `LifecycleCoordinator.is_strict_game()` to `False` for Valorant, Fortnite, Apex Legends, CS2, etc.)
