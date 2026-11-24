# Independent Red-Team Security Audit — Domain 1: Anti-Cheat, Guard & 2026 Launcher/Catalog Coverage (`v1.2.0-rc.3`)

- **Target:** GameRewind (`E:\projects\game hub`, commit `c9e0f67` / `1417576` / `0c61627`)
- **Audit Scope:**
  1. `gamehub/core/protection/guard.py` (`K32EnumProcesses` 80 ms PID-diff fast path, 2.0 s full audit, PID reuse window, `os._exit`, `QueryUnbiasedInterruptTime`, `ToolhelpProcessScanner`, `WindowsServiceProbe`, `_trigger_map`, `run_dummy_process_protection_test`)
  2. `gamehub/app.py` (startup order, deferred wiring, startup TOCTOU `check_once()`, direct guard-thread exit vs Qt shutdown, `CaptureScheduler` pausing)
  3. `gamehub/core/sessions/processes.py`, `watcher.py`, `gamehub/core/capture/windows.py`, `service.py` (zero `psutil`, zero handle spraying, `allowed_pids` gating, `ensure_cv2_shim()`)
  4. `gamehub/core/protection/catalog.py`, `protected_games.json`, `lifecycle.py` (2026 anti-cheat & multi-launcher coverage, additive-only overrides, idle `vgc`/`EAAntiCheatService` handling)
- **Method:** Independent static code audit + targeted non-spawning Python reproductions + targeted pytest verification (`14/14` passed in `test_security_rc3.py`, `test_packaging.py`, `test_process_probe.py`). No source, test, packaging, or git state was modified.

---

## Verdict: **FAIL**

The rc.3 architecture preserves its core zero-presence security foundations (zero `psutil`, zero `OpenProcess` outside `processes.py`, read-only pre-startup `self_check()`, direct guard-thread `os._exit`, additive-only catalog overrides, `allowed_pids`-gated `WindowProbe`, clean `ensure_cv2_shim()`, and strong EA SPORTS FC multi-launcher coverage).

However, this audit identified **1 HIGH**, **3 MEDIUM**, and **3 LOW** open findings — most critically:
1. A **2.0 s PID-reuse blind window** in the new `K32EnumProcesses` fast path (`RC3-AC-01`) that directly explains the observed **`1,710.03 ms` Fortnite trial 9 spike** in `docs/perf/rc3-raw.json` and breaches the `< 300 ms` max safety-critical exit SLA.
2. A **4× DWORD-vs-byte `memoryview` slice bug** in `ToolhelpProcessScanner.pid_snapshot()` (`RC3-AC-02`) that over-reads stale buffer tail memory on all systems and silently drops process-exit visibility at `≥ 1,024` running processes.
3. A **per-game override bypass of `entry.anti_cheat_exes`** in `ProtectionGuard` (`RC3-AC-03`) that disables active nProtect GameGuard (`gamemon64.des`) detection when `helldivers_2` is set to `full`.
4. **2026 catalog & multi-launcher gaps** (`RC3-AC-04`) affecting Epic-installed League of Legends / PUBG, Battle.net Call of Duty UIDs (`auks`/`lazr`), Rainbow Six Siege DX12 (`rainbowsix_dx12.exe`), and `beservice_x64.exe` / `gamemon*.des`.

---

## Findings Table

| ID | Severity | Status | File:Line | Summary |
| --- | --- | --- | --- | --- |
| `RC3-AC-01` | **HIGH** | **OPEN** | `gamehub/core/protection/guard.py:32, 533-548` | `K32EnumProcesses` PID-diff fast path introduces up to a **2,000 ms PID-reuse blind window** (`_FULL_AUDIT_INTERVAL_SEC = 2.0`), directly explaining the `1,710.03 ms` Fortnite trial 9 spike and breaching the `< 300 ms` max exit SLA. |
| `RC3-AC-02` | **MEDIUM** | **OPEN** | `gamehub/core/protection/guard.py:166-184` | `ToolhelpProcessScanner.pid_snapshot()` slices `memoryview(DWORD[4096])[:used]` using a **byte** count (`lpcbNeeded`) as a **DWORD** element count — 4× stale tail over-read on all systems and silent clamping / exit-blind-spot at `≥ 1,024` processes. |
| `RC3-AC-03` | **MEDIUM** | **OPEN** | `gamehub/core/protection/guard.py:421-435` | `_rebuild_trigger_map_locked()` skips `entry.anti_cheat_exes` when `entry.id in disabled_entries` (inconsistent with `SessionWatcher`), allowing `gamemon.des`/`gamemon64.des` (GameGuard) to go undetected if `helldivers_2` is set to `full`. |
| `RC3-AC-04` | **MEDIUM** | **OPEN** | `gamehub/core/protection/protected_games.json:28-36, 55-68, 126, 156, 159-171`; `catalog.py:49-57` | 2026 catalog/launcher gaps: Epic LoL & Epic PUBG lack `epic_app_names`/`title_aliases`; Battle.net CoD has typos `"augs"`/`"lazarus"` instead of `"auks"`/`"lazr"`; R6 Siege missing `rainbowsix_dx12.exe`; `beservice_x64.exe` & `gamemon*.des` missing from `global_anti_cheat_exes`. |
| `RC3-AC-05` | **LOW** | **OPEN** | `gamehub/core/protection/guard.py:491-493, 502-503, 527-548` | Unsynchronized invalidation race between `update_policy()`/`unignore_pid()` (`_last_pid_sig = None` under `_config_lock`) and `_check_once_locked()` overwriting `_last_pid_sig` outside `_config_lock`, deferring policy tightening up to `_FULL_AUDIT_INTERVAL_SEC`. |
| `RC3-AC-06` | **LOW** | **OPEN** | `gamehub/app.py:765-770` | `GameStarted` calls `_sync_capture_active()` before `lifecycle.on_game_started`, briefly invoking `capture_scheduler.start()` before Strict mode pauses it. |
| `RC3-AC-07` | **LOW** | **OPEN** | `gamehub/core/sessions/processes.py:288-291, 327-339` | Legacy `package_id`-only target fallback sets `check_package = True` for every non-denylisted running process if a stale pre-v1.2 DB row lacks `exe_path`. |
| `RC3-AC-08` | **INFO** | **INFO** | `app.py`, `guard.py`, `processes.py`, `windows.py`, `service.py`, `catalog.py`, `lifecycle.py` | Verified sound: zero `psutil`, zero `OpenProcess` outside `processes.py`, `allowed_pids` gating, `ensure_cv2_shim()`, pre-window `self_check()` + startup TOCTOU `check_once()`, direct guard-thread `os._exit`, `QueryUnbiasedInterruptTime`, additive-only overrides, idle `vgc`/`EAAntiCheatService` handling, and EA SPORTS FC Steam/Epic/EA/Xbox coverage. |

---

## Detailed Findings & Concrete Fixes

### `RC3-AC-01` [HIGH / OPEN] — 2.0 s PID-Reuse Blind Window in `K32EnumProcesses` Fast Path (Explains 1,710 ms Fortnite Trial 9 Spike)

- **Location:** `gamehub/core/protection/guard.py:32` (`_FULL_AUDIT_INTERVAL_SEC = 2.0`), `guard.py:533-548` (`_check_once_locked`)
- **Root Cause & Analysis:**
  `ProtectionGuard._check_once_locked()` uses `K32EnumProcesses` on 80 ms ticks to obtain a raw PID array (`sig`) and skips `CreateToolhelp32Snapshot` whenever `sig == self._last_pid_sig and (now - self._last_full_scan) < _FULL_AUDIT_INTERVAL_SEC` (`2.0 s`).
  Because `K32EnumProcesses` returns *only* PIDs (no creation times, no image names) and Windows' `PspCidTable` LIFO free-list aggressively recycles recently exited PIDs, a newly spawned protected launcher/game/anti-cheat that reuses the PID of a recently exited process at the same slot produces `sig == self._last_pid_sig` and is **completely invisible** until `_FULL_AUDIT_INTERVAL_SEC` (`2.0 s`) elapses.
- **Evidence / Reproduction:**
  1. **Observed in frozen rc.3 benchmark (`docs/perf/rc3-raw.json:144`):** Fortnite trial 9 (`raw_ms[8]`) spiked to **`1,710.03 ms`** while 39/40 trials completed in `46.46–176.38 ms`. In `benchmark_rc.py:338`, the dummy is spawned `0.85 s` after window visibility (~`0.29 s` after `_finish_startup()`'s `protection_guard.check_once()` resets `_last_full_scan`): `2,000 ms − 290 ms ≈ 1,710 ms`. This breaches the design SLA in `docs/design/13-v1.2-rc3-speed-size.md:52` (`max < 300 ms`) and exceeds kernel anti-cheat driver load latency (~200–800 ms).
  2. **Deterministic Python reproduction** (reusing PID `200` for `fortnitelauncher.exe` at `+290 ms` after `force_full=True`):
     ```text
     [2] PID reuse detection: at +290ms=None, at +1900ms=None, at +2010ms=Fortnite
     ```
  3. **Measured primitive cost on host:** `pid_snapshot` = `0.053 ms`, `CreateToolhelp32Snapshot` = `7.069 ms`, `SCM probe` = `0.207 ms`.
- **Concrete Fix:**
  Lower `_FULL_AUDIT_INTERVAL_SEC` in `gamehub/core/protection/guard.py:32` from `2.0` to **`0.24`** (240 ms, matching `_SCM_CHECK_EVERY_N_TICKS = 3`, guaranteeing worst-case PID-reuse detection `≤ 240–280 ms` to satisfy the `< 300 ms` max SLA while still avoiding 2 out of 3 Toolhelp32 calls — ~4.2 calls/s ≈ `~0.25%` total system CPU on a 12-thread CPU). Add a deterministic unit test in `tests/test_performance_regressions.py` simulating PID reuse with identical `pid_snapshot()` bytes and asserting detection within `≤ 300 ms`.

---

### `RC3-AC-02` [MEDIUM / OPEN] — DWORD-vs-Byte Unit Mismatch in `ToolhelpProcessScanner.pid_snapshot()`

- **Location:** `gamehub/core/protection/guard.py:166-184`
- **Root Cause & Analysis:**
  `self._pid_buf` is `(wintypes.DWORD * 4096)()` (`itemsize = 4`, `self._pid_buf_cb = 16384` bytes). `K32EnumProcesses` writes the number of **bytes** returned into `self._pid_needed` (`used`). Line 184 executes:
  ```python
  return bytes(memoryview(self._pid_buf)[:used])
  ```
  Because `memoryview(self._pid_buf)` has `format = '<L'` (`itemsize = 4`, length `4096` DWORDs), slicing `[:used]` slices `used` **DWORDs** (`4 * used` bytes), not `used` bytes:
  - On normal systems (~300 PIDs, `used ≈ 1252` B), it returns `5,008` B (4× over-read into stale/zero tail entries of the reused buffer).
  - On busy systems with `≥ 1,024` processes (`used ≥ 4096` B, still `< 16384` B `_pid_buf_cb`), `memoryview[:used]` **silently clamps to `4096` DWORDs (`16,384` B)**. Because `self._pid_buf` is reused without clearing, when a process exits (`1025 → 1024`), `self._pid_buf[1024]` retains the exited PID and `pid_snapshot()` returns the **exact same 16,384-byte signature**, hiding the exit and enabling signature collisions if another process spawns into that slot.
- **Evidence / Reproduction:**
  Executed directly against `ToolhelpProcessScanner` on this Windows host:
  ```text
  [1] K32EnumProcesses lpcbNeeded=1252 B (313 PIDs), pid_snapshot() returned len=5008 B (4x over-read!)
  [1b] >=1024 procs exit blind spot: len(sig_a)=16384, len(sig_b)=16384, sig_a == sig_b: True
  ```
- **Concrete Fix:**
  Replace `guard.py:181-184` with byte-accurate slicing and alignment validation:
  ```python
  used = int(self._pid_needed.value)
  if used <= 0 or used >= self._pid_buf_cb or (used % ctypes.sizeof(wintypes.DWORD)) != 0:
      return None
  return bytes(memoryview(self._pid_buf).cast("B")[:used])
  ```
  Add a unit test verifying `len(pid_snapshot()) == lpcbNeeded` and that a `1025 → 1024` process count drop produces distinct snapshots.

---

### `RC3-AC-03` [MEDIUM / OPEN] — Per-Game `disabled_entry_ids` Skips `entry.anti_cheat_exes` in `ProtectionGuard`

- **Location:** `gamehub/core/protection/guard.py:421-435`
- **Root Cause & Analysis:**
  In `ProtectionGuard._rebuild_trigger_map_locked()`:
  ```python
  for entry in self._catalog.entries:
      if entry.id in disabled_entries:
          continue
      for exe in entry.anti_cheat_exes:
          _put(exe, 5, ...)
  ```
  This contradicts `SessionWatcher._build_watch_plan()` (`gamehub/core/sessions/watcher.py:144-145`), which unconditionally puts every `entry.anti_cheat_exes` into `always_protected`, and contradicts the invariant documented in `tests/test_zero_presence_guard.py:285` (*"Per-game override OFF ('full') allows that specific game's exe, while anti-cheat exe still protects"*).
  Because `gamemon.des` and `gamemon64.des` (HELLDIVERS 2 / nProtect GameGuard) and `fortniteclient-win64-shipping_eac_eos.exe` / `_be.exe` are **only** in `entry.anti_cheat_exes` (not in `global_anti_cheat_exes`), setting `helldivers_2` to `full` disables `ProtectionGuard` even while kernel nProtect GameGuard is actively running — and unlike EAC/BattlEye, GameGuard has no SCM service fallback in `anti_cheat_services`.
- **Evidence / Reproduction:**
  ```text
  [3] helldivers_2 disabled + gamemon64.des running -> trigger=None
  ```
- **Concrete Fix:**
  1. Remove `if entry.id in disabled_entries: continue` from the `entry.anti_cheat_exes` loop at `gamehub/core/protection/guard.py:421-435`.
  2. Add `"gamemon.des"` and `"gamemon64.des"` to `global_anti_cheat_exes` (`protected_games.json` and `catalog.py:DEFAULT_GLOBAL_ANTI_CHEAT_EXES`) and to `DEFAULT_NEVER_OPEN_EXES` in `gamehub/core/sessions/processes.py`.

---

### `RC3-AC-04` [MEDIUM / OPEN] — 2026 Anti-Cheat & Multi-Launcher Catalog Coverage Gaps

- **Location:** `gamehub/core/protection/protected_games.json:28-36, 55-68, 126, 156, 159-171`; `gamehub/core/protection/catalog.py:49-57`
- **Root Cause & Analysis:**
  Cross-checking `protected_games.json` against `BattleNetDetector`, `EpicDetector`, `processes.py`, and 2026 PC anti-cheat titles revealed concrete matching gaps:
  1. **Epic Games Store — League of Legends & PUBG:** Both titles are distributed on Epic Games Store, yet `league_of_legends` (line 62) and `pubg` (line 166) have empty `epic_app_names: []` and **no `title_aliases`**. When Epic reports an opaque hex `AppName` or stub installer without the nested game binary, `catalog.match_game(GameSource.EPIC, ...)` returns `None`, leaving the library entry unmarked as Strict (bypassing Play-through Layer 5 auto-exit and `ModsEngine` catalog match).
  2. **Call of Duty Battle.net UID typos:** `protected_games.json:126` lists `"augs"` and `"lazarus"`, whereas `gamehub/core/library/battlenet.py:33-34` uses the actual Battle.net product UIDs `"auks"` (Call of Duty HQ / BO6) and `"lazr"`. Also missing `"sp26-cod.exe"` for 2026 CoD builds.
  3. **Rainbow Six Siege DX12 executable:** `protected_games.json:156` lists `rainbowsix.exe`, `rainbowsix_vulkan.exe`, `rainbowsix_dx11.exe`, omitting **`rainbowsix_dx12.exe`** (Vulkan was deprecated in favor of DX12 / Siege X in 2025–2026).
  4. **64-bit BattlEye executable:** `beservice_x64.exe` is listed in `processes.py:58` (`DEFAULT_NEVER_OPEN_EXES`) but missing from `global_anti_cheat_exes` in `protected_games.json` and `catalog.py` (SCM `BEService` mitigates runtime detection, but process-level detection is missing).
- **Evidence / Reproduction:**
  ```text
  [4a] Epic LoL opaque ID + title: None
  [4b] Epic PUBG opaque ID + title: None
  [4c] Battle.net CoD uid='auks': None
  [4d] Battle.net CoD uid='lazr': None
  [4e] R6 Siege DX12 exe: None
  [4f] BattlEye 64-bit BEService_x64.exe: None, in global_ac=False
  ```
- **Concrete Fix:**
  Update `protected_games.json` (and `catalog.py:DEFAULT_GLOBAL_ANTI_CHEAT_EXES`):
  - Add `"beservice_x64.exe"`, `"gamemon.des"`, `"gamemon64.des"` to `global_anti_cheat_exes`.
  - Add `"title_aliases": ["league of legends", "teamfight tactics"]` and Epic slugs (`["league_of_legends", "league-of-legends"]`) to `league_of_legends`, `"title_aliases": ["2xko"]` to `2xko`, and `"title_aliases": ["pubg"]` + Epic slugs (`["pubg", "pubg-battlegrounds"]`) to `pubg`.
  - Add `"auks"` and `"lazr"` to `call_of_duty.battlenet_ids` and `"sp26-cod.exe"` to `call_of_duty.game_exes`.
  - Add `"rainbowsix_dx12.exe"` to `rainbow_six_siege.game_exes`.

---

### `RC3-AC-05` [LOW / OPEN] — Concurrency Race Between `update_policy()`/`unignore_pid()` and `_check_once_locked()`

- **Location:** `gamehub/core/protection/guard.py:491-493, 502-503, 527-548`
- **Root Cause & Analysis:**
  `update_policy()` and `unignore_pid()` set `self._last_pid_sig = None` under `self._config_lock` to force a full scan on the next tick. However, `_check_once_locked()` snapshots `self._trigger_map` under `_config_lock` (lines 527–529), releases `_config_lock`, and then writes `self._last_pid_sig = sig` (line 542 or 546). If `update_policy()` runs while the guard thread is mid-scan using the **old** `trigger_map`, the guard thread overwrites `self._last_pid_sig = None` with `sig`, causing subsequent ticks to skip re-evaluating the **new** policy until `_FULL_AUDIT_INTERVAL_SEC` expires.
- **Concrete Fix:**
  Maintain a `_policy_gen: int = 0` counter incremented under `_config_lock` in `update_policy()` and `unignore_pid()`. In `_check_once_locked()`, read `(trigger_map, ignored_pids, policy_gen)` atomically under `_config_lock`, force `did_full_scan = True` when `policy_gen != self._last_scanned_gen`, and only assign `self._last_scanned_gen = policy_gen` when `did_full_scan` completes.

---

### `RC3-AC-06` [LOW / OPEN] — `GameStarted` Starts `CaptureScheduler` Before `LifecycleCoordinator.on_game_started`

- **Location:** `gamehub/app.py:765-770`
- **Root Cause & Analysis:**
  `_sync_capture_active()` is subscribed to `GameStarted` **before** `lifecycle.on_game_started`:
  ```python
  events.subscribe(GameStarted, window.game_started)
  events.subscribe(GameStopped, window.game_stopped)
  events.subscribe(GameStarted, lambda _e: _sync_capture_active())
  events.subscribe(GameStopped, lambda _e: _sync_capture_active())
  events.subscribe(GameStarted, lifecycle.on_game_started)
  events.subscribe(GameStopped, lifecycle.on_game_stopped)
  ```
  When a Strict game emits `GameStarted`, `window._tracked_games` is non-empty while `lifecycle.is_strict_active()` is still `False`, so `_sync_capture_active()` calls `capture_scheduler.start()` right before `lifecycle.on_game_started` pauses it. (Mitigated by `ProtectionGuard` exiting on strict games, 30 s capture timer interval, and `SessionTracker.active_pids()` filtering `created_at > 0.0`.)
- **Concrete Fix:**
  Move `events.subscribe(GameStarted, lifecycle.on_game_started)` and `events.subscribe(GameStopped, lifecycle.on_game_stopped)` **above** the `_sync_capture_active()` subscriptions.

---

### `RC3-AC-07` [LOW / OPEN] — Legacy `package_id`-Only Target Fallback Allows Broad `OpenProcess` Inspection

- **Location:** `gamehub/core/sessions/processes.py:288-291, 327-339`
- **Root Cause & Analysis:**
  If a `WatchTarget` of kind `"package_id"` exists for a game with no `"exe_path"` target (possible in a stale pre-v1.2 upgraded SQLite DB prior to its first library refresh), `packages` is non-empty, setting `check_package = True` for **every** running process not in `protected` or `never_open`, invoking `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` + `GetPackageFamilyName` across unrelated user processes every 3 s. (`xbox.py:268` prevents newly discovered Xbox games from creating `package_id`-only targets, and `DEFAULT_NEVER_OPEN_EXES` + `protected` still protect known anti-cheats/launchers.)
- **Concrete Fix:**
  Either drop the `package_id`-only scanning fallback in `ProcessProbe.snapshot()` (require `check_image` to match before opening any handle, so `GetPackageFamilyName` is only a secondary disambiguator on matched basenames) or prune orphaned `package_id`-only rows during DB migration/startup.

---

### `RC3-AC-08` [INFO] — Verified Controls (No Issues Found)

- **Zero `psutil` & zero forbidden Win32 APIs:** Confirmed via repo-wide search and `tests/test_packaging.py` (`14/14` passing across `test_security_rc3.py`, `test_packaging.py`, `test_process_probe.py`). `OpenProcess` exists solely in `gamehub/core/sessions/processes.py` using strictly `PROCESS_QUERY_LIMITED_INFORMATION (0x1000)` in a single atomic `inspect_with_time()` handle open.
- **Startup order & TOCTOU (`gamehub/app.py:404-609, 898-905`):** `ProtectionGuard.self_check()` executes before `migrate_legacy_data_root()`, `SingleInstance.claim_or_activate()`, window creation, log creation, and DB writes (using `?mode=ro` read-only prefs lookup). `protection_guard.start()` runs before `window.show()`, and `_finish_startup()` performs a synchronous `protection_guard.check_once()` strictly before `mods_engine.recover_incomplete()`, `_start_hotkeys()`, and `watcher.start()`.
- **Direct guard-thread `os._exit` (`gamehub/app.py:579-590, 1855`):** In production (`hard_exit_on_emergency=True`), both `_on_guard_trigger` (`os._exit(0)`) and `_on_guard_failure` (`os._exit(2)`) terminate immediately on the guard thread, independent of Qt UI thread stalls; `SingleInstance` recovers cleanly from the lockfile on next launch (`test_single_instance_recovers_cleanly_after_hard_os_exit`).
- **Sleep-safe watchdog clock (`guard.py:47-63`):** `QueryUnbiasedInterruptTime` cleanly pauses elapsed-time tracking during Windows S3/Modern Standby sleep.
- **`WindowProbe` & `ensure_cv2_shim()` (`windows.py:63-84, 115-135`; `service.py:38-61`):** `WindowProbe.foreground()` checks `allowed_pids` (strictly `SessionTracker.active_pids()` where `created_at > 0.0`) before calling `query_process_creation_time(pid)`. `ensure_cv2_shim()` removes OpenCV cleanly without breaking `windows_capture` or Python introspection.
- **Additive-only catalog overrides (`catalog.py:325-359, 401-435`):** `protected_games_override.json` cannot delete entries, weaken `default_mode` from `"strict"`, or strip any IDs, executables, or services.
- **Idle `vgc` & `EAAntiCheatService` handling:** Neither `vgc` nor `EAAntiCheatService` is polled in `anti_cheat_services`, and `vgc.exe`, `vgtray.exe`, `vgm.exe`, `eaanticheat.gameservice.exe` are permanently listed in `processes.py:DEFAULT_NEVER_OPEN_EXES`, avoiding false lockouts and zero handle opens while idle.
- **EA SPORTS FC multi-launcher coverage:** Verified across Steam (`2195250`, `2669320`, `3103970`, `3405690`), Epic (slugs + hex IDs + `title_aliases`), EA app (slugs + `title_aliases` for opaque `Origin.OFR.*`), Xbox (`ElectronicArtsMobile.EASPORTSFC`, `ElectronicArts.EASPORTSFC`), plus `eaanticheat.gameservicelauncher.exe` and `fc24..27*.exe`.
