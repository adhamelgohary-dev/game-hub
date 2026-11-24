# Security Audit Report — Focus (b): Process Detection, Inspection & Handle Hygiene

- **Target:** GameRewind (`e:\projects\game hub\gamehub\`)
- **Scope:** Every code path that enumerates, inspects, or opens OS handles to Windows processes (`ProtectionGuard`, `ProcessProbe`, `SessionWatcher`, `WindowProbe`, `ModsEngine`, `psutil` internals, and all callers/wiring in `app.py` and `capture/`).
- **Auditor:** Independent Red-Team Security Auditor (Focus b)
- **Date:** 2026-11-24
- **Environment:** Windows 11, Python `.venv`, `psutil 7.2.2` (`_psutil_windows.pyd`)

---

## Executive Summary

While `ProtectionGuard` (`gamehub/core/protection/guard.py`) and `ModsEngine` (`gamehub/modules/mods/engine.py`) are clean — strictly passive Toolhelp32 basenames + read-only SCM queries with **zero** `OpenProcess` handles and **zero** `psutil` usage — the surrounding runtime subsystems (**`WindowProbe`**, **`ProcessProbe`**, **`SessionWatcher`**, and **`app.py` shutdown/self-test wiring**) contain **multiple CRITICAL and HIGH anti-cheat safety violations** that actively call `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid)` on protected games, kernel anti-cheat services, and game launchers:

| ID | Severity | Component | Summary |
|---|---|---|---|
| **PROC-01** | **CRITICAL** | `WindowProbe` / `CaptureService` / `app.py` | `WindowProbe.foreground()` unconditionally calls `psutil.Process(pid).create_time()` → **`OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`** (twice on `ACCESS_DENIED`) on **every** foreground window — including Fortnite, Valorant, anti-cheat splash screens, and launchers — every 30s (min 5s) even with **zero** tracked games, on every global hotkey, and every 25ms during Alt-Tab out of capture. |
| **PROC-02** | **CRITICAL** | `ProcessProbe` / `SessionWatcher` / `catalog.py` | Whenever **even one** non-strict Xbox/Microsoft Store game (`kind="package_id"`) is in the library, `ProcessProbe.snapshot()` sprays **`OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`** + `GetPackageFamilyName` against **every non-catalog process on Windows** (329/329 processes on test host) every 3 seconds — hitting `EpicGamesLauncher.exe`, `EADesktop.exe`, `Battle.net.exe`, `upc.exe`, `UbisoftConnect.exe`, `steam.exe`, `vgtray.exe`, `EAAntiCheat.GameService.exe`, and any unlisted anti-cheat game (`GTA5.exe`, `RobloxPlayerBeta.exe`, etc.). |
| **PROC-03** | **HIGH** | `SessionWatcher._build_watch_plan()` | Setting any catalog game to `protection_mode="full"` subtracts **all** of `matched.exe_names` (including `anti_cheat_exes` and `launcher_stage_exes`) from `effective_protected`, globally stripping `vgc.exe`, `beservice.exe`, `easyanticheat.exe`, `easyanticheat_eos.exe`, `sguard64.exe`, `sguardsvc64.exe`, `leagueclient.exe`, and `leagueclientux.exe` — permitting `ProcessProbe` to call **`OpenProcess`** directly on kernel anti-cheat services and Riot launchers. |
| **PROC-04** | **MEDIUM** | `app.py` (`_emergency_shutdown` / `finally:`) | Emergency shutdown triggered by `ProtectionGuard` does not stop `SessionWatcher` or synchronously cancel in-flight WGC capture leases; `finally:` blocks on `controls_controller.close(wait=True)` and `notes_controller.close(wait=True)` before closing `SessionWatcher`, leaving `OpenProcess` polling active during teardown. |
| **PROC-05** | **MEDIUM** | `app.py` / `guard.py` / `watcher.py` | "Test Protection" (`run_dummy_process_protection_test`) exempts its dummy `FortniteLauncher.exe` PID only from `ProtectionGuard`, not `SessionWatcher` — causing `SessionWatcher` to emit `ProtectedGameDetected` and call `exit_app()` (closing GameRewind) whenever its 3s poll overlaps the self-test. |
| **PROC-06** | **LOW** | `ProcessProbe.snapshot()` | Opens up to **4 separate `OpenProcess` handles** per matched non-protected game PID per poll cycle (2 direct + 2 via `psutil.Process(pid).create_time()`) instead of querying image path and creation time atomically on one handle. |
| **PROC-07** | **LOW** | `ModsEngine` / `SessionWatcher` | `ModsEngine._collect_known_game_exes()` only inspects top-level `.exe` files via `iterdir()`, missing nested shipping binaries; `SessionWatcher._run()` relies on CPython's non-interning of `frozenset(set())` for target-reload detection. |

---

## Inventory of All Process-Inspection Sites in `gamehub/`

A full-repository scan across all `.py` files under `e:\projects\game hub\gamehub\` (and native `.pyd` symbol inspection of `windows_capture.pyd` and `_psutil_windows.pyd`) identified every process/window enumeration or handle API call:

| File & Lines | APIs Used | Calls `OpenProcess`? | Calls `psutil`? | Status |
|---|---|---|---|---|
| `gamehub/core/protection/guard.py:112-155` (`ToolhelpProcessScanner`) | `CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)`, `Process32FirstW`, `Process32NextW`, `CloseHandle` | **No** | **No** | **PASS** |
| `gamehub/core/protection/guard.py:158-235` (`WindowsServiceProbe`) | `OpenSCManagerW(SC_MANAGER_CONNECT)`, `OpenServiceW(SERVICE_QUERY_STATUS)`, `QueryServiceStatusEx`, `CloseServiceHandle` | **No** | **No** | **PASS** |
| `gamehub/modules/mods/engine.py:18, 128, 173-190` (`ModsEngine`) | Delegates strictly to `ToolhelpProcessScanner` | **No** | **No** | **PASS** (see PROC-07) |
| `gamehub/core/capture/windows.py:12, 28-97` (`WindowProbe`) | `GetForegroundWindow`, `GetDesktopWindow`, `GetShellWindow`, `IsWindowVisible`, `IsIconic`, `GetAncestor`, `DwmGetWindowAttribute`, `GetWindowThreadProcessId`, **`psutil.Process(pid).create_time()`** | **YES (via `psutil`)** | **YES** | **FAIL (PROC-01)** |
| `gamehub/core/capture/windows.py:113-264` (`WgcCapture`) | `windows_capture.WindowsCapture` (verified: `windows_capture.pyd` imports **zero** `OpenProcess` / `ReadProcessMemory` / `CreateToolhelp32Snapshot` symbols), calls `is_current()` every 25ms → `WindowProbe.foreground()` | **Indirectly via `is_current()`** | **Indirectly** | **FAIL (PROC-01, PROC-04)** |
| `gamehub/core/sessions/processes.py:10, 46-229` (`_WindowsProcessMetadata`, `ProcessProbe`) | `CreateToolhelp32Snapshot`, `Process32FirstW/NextW`, **`OpenProcess(0x1000, False, pid)`**, `QueryFullProcessImageNameW`, `GetPackageFamilyName`, **`psutil.Process(pid).create_time()`** | **YES (direct + via `psutil`)** | **YES** | **FAIL (PROC-02, PROC-03, PROC-06)** |
| `gamehub/core/sessions/watcher.py:79-223` (`SessionWatcher`) | Orchestrates `ProcessProbe.snapshot()` every 3.0s | **Indirectly via `ProcessProbe`** | **Indirectly** | **FAIL (PROC-02, PROC-03, PROC-04, PROC-05, PROC-07)** |

*(No other files in `gamehub/` call `OpenProcess`, `OpenThread`, `ReadProcessMemory`, `WriteProcessMemory`, `VirtualAlloc`, `SetWindowsHookEx`, `CreateRemoteThread`, `EnumProcesses`, `NtQuerySystemInformation`, or `psutil`.)*

---

## Verification of Audit Questions 1–4

### Q1. Is `ProtectionGuard` strictly Toolhelp32 basenames only with ZERO `OpenProcess` handles?
**YES — Verified Clean.**
- AST verification of `gamehub/core/protection/guard.py` and `gamehub/modules/mods/engine.py` confirmed **zero** references to `OpenProcess`, `psutil`, `QueryFullProcessImageNameW`, `ReadProcessMemory`, or `VirtualQueryEx`.
- `ToolhelpProcessScanner` (`guard.py:112-155`) invokes only `CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)`, `Process32FirstW`, `Process32NextW`, and `CloseHandle` (in `finally:`), failing closed with `ProtectionCheckError` on `INVALID_HANDLE_VALUE` or any termination error other than `ERROR_NO_MORE_FILES (18)`.
- `WindowsServiceProbe` (`guard.py:158-235`) invokes only read-only SCM APIs (`SC_MANAGER_CONNECT = 0x0001`, `SERVICE_QUERY_STATUS = 0x0004`, `QueryServiceStatusEx`), failing closed on any error other than `ERROR_SERVICE_DOES_NOT_EXIST (1060)` (including `ERROR_ACCESS_DENIED (5)`). Verified live: `WindowsServiceProbe().verify_available()` returned `True`.

### Q2 & Q3. `psutil` Internals on Windows (`psutil 7.2.2`) & Every `OpenProcess` Path
**Empirical proof of what `psutil.Process(pid).create_time()` executes on Windows:**

In `E:\projects\game hub\.venv\Lib\site-packages\psutil\__init__.py` (`Process._init` → `Process._get_ident`) and `psutil\_pswindows.py` (`Process.create_time`):
```python
# psutil/__init__.py (Process._get_ident)
if WINDOWS:
    self._create_time = self._proc.create_time(fast_only=True)
    return (self.pid, self._create_time)

# psutil/_pswindows.py (Process.create_time)
def create_time(self, fast_only=False):
    try:
        _user, _system, created = cext.proc_times(self.pid)
        return created
    except OSError as err:
        if is_permission_err(err):
            if fast_only:
                raise
            return self._proc_info()[pinfo_map['create_time']]
        raise
```
Static PE string check on `_psutil_windows.pyd` confirmed imports of `OpenProcess`, `GetProcessTimes`, and `NtQuerySystemInformation`.

Live empirical proof on PID 4 (`System`, where `OpenProcess` is denied with `WinError 5`, mirroring kernel anti-cheat `ObRegisterCallbacks` handle denial):
```text
proc_times(4): PermissionError winerror=5 (OpenProcess denied)
psutil.Process(4).create_time() -> 0.0
calls = [
  ('cext.proc_times [OpenProcess]', 4),        # Call 1 inside Process.__init__ -> _get_ident(fast_only=True)
  ('cext.proc_times [OpenProcess]', 4),        # Call 2 inside .create_time(fast_only=False)
  ('cext.proc_info [NtQuerySystemInformation]', 4)
]
```
**Key finding:** Every call to `psutil.Process(pid).create_time()` calls `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid)` **first** — and if kernel anti-cheat `ObRegisterCallbacks` or privilege boundaries return `ERROR_ACCESS_DENIED (5)`, `psutil` calls **`OpenProcess` TWICE** on that protected PID before falling back to `NtQuerySystemInformation`!

### Q4. Does `WindowProbe.foreground()` call `OpenProcess` on a foreground protected game?
**YES — CRITICAL FINDING (PROC-01).** Detailed below.

---

## Detailed Findings

### PROC-01 [CRITICAL] — `WindowProbe.foreground()` Unconditionally Calls `OpenProcess` (via `psutil`) on Any Foreground Window, Including Protected Games and Launchers

**Locations:**
- `gamehub/core/capture/windows.py:56-69` (`WindowProbe.foreground`)
- `gamehub/core/capture/service.py:40-54` (`CaptureService.acquire`, `CaptureService.is_current`)
- `gamehub/core/capture/scheduler.py:26-44, 52` (`CaptureScheduler.sample_foreground`, `pin_foreground`)
- `gamehub/core/capture/windows.py:231-234` (`WgcCapture._run_capture_attempt`)
- `gamehub/app.py:684-686, 850-851` (`foreground_session`, `capture_scheduler.start()`)

**Analysis:**
`WindowProbe.foreground()` inspects the foreground HWND, resolves its PID via `GetWindowThreadProcessId`, and **unconditionally** executes `psutil.Process(pid).create_time()` (`windows.py:64`) without checking whether `pid` belongs to a tracked non-protected game or whether `pid` is a protected/anti-cheat process:
```python
# gamehub/core/capture/windows.py:56-69
def foreground(self) -> WindowIdentity | None:
    hwnd = self._foreground()
    if not hwnd:
        return None
    pid = self._eligible_owner(hwnd)
    if not pid:
        return None
    try:
        created_at = psutil.Process(pid).create_time()  # <-- calls OpenProcess(pid)!
    except (psutil.Error, OSError):
        return None
```
Every caller invokes `WindowProbe.foreground()` **before** checking `SessionTracker`:
1. **Unconditional Periodic Polling (even with ZERO games running):** `app.py:850-851` starts `CaptureScheduler` at startup. Every `capture_interval_sec` (default 30s, configurable down to **5s** in `settings.py:13`), `sample_foreground()` calls `CaptureService.acquire()` (`scheduler.py:42`), which calls `self._windows.foreground()` **first** (`service.py:41`) before calling `self._tracker.active_for(window.process)` (`service.py:44`).
2. **Race Window on Protected Game Launch (0–300ms+):** `ProtectionGuard` polls every `0.30s` (`guard.py:30`) and delivers shutdown via `Qt.ConnectionType.QueuedConnection` (`app.py:596-599`). Whenever a protected game (e.g., `FortniteClient-Win64-Shipping.exe`, `VALORANT-Win64-Shipping.exe`, `FortniteLauncher.exe`, `EasyAntiCheat_EOS.exe`) takes focus before `ProtectionGuard` completes shutdown, any timer tick or hotkey directly invokes `OpenProcess` on the protected game process.
3. **Optional Launchers Always Open by Default:** `strict_launcher_*` settings (`settings.py:36-40`) default to `False`, so Epic Games Launcher, EA app, Battle.net, Ubisoft Connect, and Steam remain focused while GameRewind is running — `WindowProbe.foreground()` hits their foreground processes with `OpenProcess` on every capture tick.
4. **Unlisted Anti-Cheat Games & `strict_mode`/`ask_me` Users:** Any anti-cheat game not in the 37-entry catalog (e.g., GTA V BattlEye, Roblox Hyperion, Marvel Rivals, Arena Breakout) is never exited by `ProtectionGuard`, so `WindowProbe.foreground()` repeatedly calls `OpenProcess` on it every 5–30 seconds.
5. **Alt-Tab During WGC Capture (40 Hz `OpenProcess`!):** While `WgcCapture._run_capture_attempt()` runs (`capture/windows.py:231-234`), it calls `is_current(lease)` (`capture/service.py:52`) every **25ms** (`settled.wait(min(0.025, ...))`). If the user Alt-Tabs from a single-player game to a protected game or launcher during the 2-second capture lease, `is_current()` calls `WindowProbe.foreground()` → `OpenProcess` on the newly foregrounded process.
6. **Global Hotkeys (`Ctrl+Alt+N`, `Ctrl+Alt+L`, `Ctrl+Alt+C`):** All three hotkeys call `foreground_session()` (`app.py:684-686`) or `pin_foreground()` (`scheduler.py:52`), both of which call `WindowProbe.foreground()` before checking `SessionTracker`.

**Empirical Proof / Reproduction:**
Spawned a harmless copy of `System32\ping.exe` renamed to `VALORANT-Win64-Shipping.exe` (PID `34288`), pointed `WindowProbe` foreground to it, and called `CaptureService.acquire()` with an **empty** `SessionTracker` (0 tracked games):
```text
Tracked games = 0, foreground dummy = VALORANT-Win64-Shipping.exe (pid=34288)
CaptureService.acquire() -> None
psutil.Process() called on PIDs -> [34288] (triggers OpenProcess!)
```
And as proven above, `psutil.Process(pid).create_time()` calls `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` directly on PID `34288` (and twice if `ObRegisterCallbacks` denies access).

**Recommended Fix:**
1. Add `eligible_pids() -> frozenset[int]` (or `has_eligible() -> bool`) to `SessionTracker` (`gamehub/core/sessions/tracker.py`) returning only PIDs of active, non-strict, verified sessions (where `created_at > 0.0`).
2. In `CaptureService.acquire()`, `CaptureService.is_current()`, and `app.py:foreground_session()`, return `None`/`False` immediately if `not eligible_pids` — **never** call `WindowProbe.foreground()` when no single-player game is actively tracked.
3. Update `WindowProbe.foreground(allowed_pids: frozenset[int] | None = None)` to check `if allowed_pids is not None and pid not in allowed_pids: return None` **before** calling `create_time()`. For `is_current(lease)`, pass `allowed_pids=frozenset({lease.window.process.pid})` (and compare `hwnd == lease.window.hwnd` before querying PID/creation time at all!).
4. Replace `psutil.Process(pid).create_time()` in `WindowProbe` with handle-less `NtQuerySystemInformation(SystemProcessInformation)` (or match against `(hwnd, pid)` with a handle-less creation-time lookup) so `WindowProbe` **never** calls `OpenProcess` on any process.

---

### PROC-02 [CRITICAL] — `ProcessProbe.snapshot()` Sprays `OpenProcess` Across Every Non-Catalog Process on Windows Every 3 Seconds Whenever Any Xbox/MS Store Game Exists

**Locations:**
- `gamehub/core/sessions/processes.py:90-104, 153-154, 184-188, 223`
- `gamehub/core/sessions/watcher.py:91, 159-166`
- `gamehub/core/protection/catalog.py:363-368`
- `gamehub/core/library/xbox.py:245-250`

**Analysis:**
`XboxDetector` attaches a `GameTarget("package_id", package_family_name)` to every installed Xbox/Microsoft Store game (`xbox.py:249-250`). When a user has **even one** non-strict Xbox/Store game (e.g., Minecraft, Forza Horizon, Lies of P, Hollow Knight, Stardew Valley), `packages` in `ProcessProbe.snapshot()` is non-empty (`processes.py:153-154`).

Then, in the main process enumeration loop (`processes.py:184-188`):
```python
check_image = norm_name in basenames
if not check_image and not packages:
    continue
try:
    matches = self._matches(pid, check_image, executables, packages)
```
Because `bool(packages)` is `True`, `if not check_image and not packages:` evaluates to **`False` for every running process on Windows** not in `protected_exes`. `self._matches()` calls `self._metadata.inspect(pid, executable=False, package=True)` → **`OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)`** + `GetPackageFamilyName(handle)` every **3.0 seconds**!

Compounding this, `ProtectedGamesCatalog.all_exe_names()` (`catalog.py:363-368`) omits:
- **All `optional_strict_launchers`:** `epicgameslauncher.exe`, `eadesktop.exe`, `ealocalhostsvc.exe`, `battle.net.exe`, `upc.exe`, `ubisoftconnect.exe`, `steam.exe` (even when the user enables optional strict launchers in Settings, `SessionWatcher._build_watch_plan()` never adds them to `protected_exes`!).
- **Key anti-cheat and launcher companion executables:** `vgtray.exe` (Riot Vanguard tray), `eaanticheat.gameservice.exe` (EA Javelin service), `beservice_x64.exe`, `eabackgroundservice.exe`, `epicwebhelper.exe`, `steamservice.exe`, `agent.exe` (Blizzard Update Agent).
- **Unlisted anti-cheat games:** e.g., `GTA5.exe` / `GTA5_Enhanced.exe` (BattlEye), `RobloxPlayerBeta.exe` (Hyperion/Byfron), `FaceitClient.exe`, `BlackDesert64.exe`, etc.
- **Every OS/security process on Windows** (`csrss.exe`, `lsass.exe`, `svchost.exe`, AV/EDR, browsers).

**Empirical Proof / Reproduction:**
1. Read-only count against live Toolhelp32 snapshot on this Windows 11 host:
   ```text
   Live OS processes = 329, would be hit by OpenProcess every 3s = 329
   ```
2. Instrumented `ProcessProbe.snapshot([WatchTarget("g-mc", "package_id", "Microsoft.MinecraftUWP_8wekyb3d8bbwe")], protected_exes=catalog.all_exe_names())` against 13 synthetic processes:
   ```text
   With 1 Xbox game target, OpenProcess (inspect) called on (10/13):
     - pid=1001 EpicGamesLauncher.exe (executable=False, package=True)
     - pid=1002 EADesktop.exe (executable=False, package=True)
     - pid=1003 Battle.net.exe (executable=False, package=True)
     - pid=1004 upc.exe (executable=False, package=True)
     - pid=1005 UbisoftConnect.exe (executable=False, package=True)
     - pid=1006 steam.exe (executable=False, package=True)
     - pid=1007 vgtray.exe (executable=False, package=True)
     - pid=1008 EAAntiCheat.GameService.exe (executable=False, package=True)
     - pid=1009 GTA5.exe (executable=False, package=True)
     - pid=1010 RobloxPlayerBeta.exe (executable=False, package=True)
   ```
   *(Only `FortniteClient-Win64-Shipping.exe`, `VALORANT-Win64-Shipping.exe`, and `RiotClientServices.exe` were skipped.)*

**Recommended Fix:**
1. **Eliminate system-wide `OpenProcess` scanning for Xbox `package_id` targets:** `XboxDetector._read_config()` (`xbox.py:226-240`) already extracts exact `exe_path` targets from `MicrosoftGame.config`. Shortlist processes by known game executable basename **before** calling `OpenProcess` — only inspect `GetPackageFamilyName` when `norm_name in basenames` (or a game explicitly registers a known executable basename). Never allow `bool(packages)` to open handles to arbitrary OS processes.
2. **Expand `ProcessProbe`'s never-open-handle denylist:** Add a dedicated `never_inspect_exes()` method on `ProtectedGamesCatalog` that unconditionally includes `all_exe_names()`, **all** `optional_strict_launchers`, and common anti-cheat/launcher companion binaries (`vgtray.exe`, `eaanticheat.gameservice.exe`, `beservice_x64.exe`, `eabackgroundservice.exe`, `epicwebhelper.exe`, `steamservice.exe`, `agent.exe`, `faceitclient.exe`, `faceitservice.exe`, etc.), and pass it to `ProcessProbe.snapshot()` independently of exit-trigger policy.

---

### PROC-03 [HIGH] — Per-Game `"full"` Override in `SessionWatcher._build_watch_plan()` Strips Global Anti-Cheat & Always-Strict Launchers from `effective_protected`

**Locations:**
- `gamehub/core/sessions/watcher.py:107-124`
- `gamehub/core/protection/catalog.py:110-123, 363-368`

**Analysis:**
In `SessionWatcher._build_watch_plan()`:
```python
# gamehub/core/sessions/watcher.py:107-124
combined_exes = set(target_exes)
if matched is not None:
    combined_exes.update(matched.exe_names)  # includes launcher_stage_exes + anti_cheat_exes + game_exes!
...
elif matched is not None and game.protection_mode == "full":
    # User explicitly opted this game into Full mode.
    full_override_exes.update(combined_exes)
...
effective_protected = frozenset(protected_exes.difference(full_override_exes))
```
`ProtectedGameEntry.exe_names` (`catalog.py:114-119`) is the union of `launcher_stage_exes`, `anti_cheat_exes`, and `game_exes`. Consequently, overriding a single game to `"full"` mode globally removes shared kernel anti-cheat executables and always-strict Riot launchers from `effective_protected`:
- Overriding **Apex Legends** or **Rust** removes `easyanticheat.exe`, `easyanticheat_eos.exe`.
- Overriding **Rainbow Six Siege** or **PUBG** removes `beservice.exe`.
- Overriding **Valorant** or **League of Legends** removes `vgc.exe`, `leagueclient.exe`, `leagueclientux.exe`.
- Overriding **Delta Force** removes `sguard64.exe`, `sguardsvc64.exe`.
- Overriding **EA SPORTS FC** removes `eaanticheat.gameservicelauncher.exe`.

This directly contradicts `ProtectionGuard` (`guard.py:331-339, 367-376`), which explicitly forbids disabling `always_strict_launchers` and `global_anti_cheat_exes`. Combined with PROC-02 (or a matching target), `ProcessProbe` opens handles directly to `vgc.exe`, `BEService.exe`, `EasyAntiCheat_EOS.exe`, and `LeagueClient.exe`.

**Empirical Proof / Reproduction:**
Configured a temporary SQLite library with Apex Legends, Rainbow Six Siege, and League of Legends set to `protection_mode="full"` plus Minecraft (Xbox `package_id`), then ran `SessionWatcher._build_watch_plan()` and `ProcessProbe.snapshot()`:
```text
Global AC / always-strict exes stripped: ['vgc.exe', 'beservice.exe', 'easyanticheat.exe', 'easyanticheat_eos.exe', 'leagueclient.exe', 'leagueclientux.exe']
ProcessProbe called OpenProcess (inspect) on: ['vgc.exe', 'BEService.exe', 'EasyAntiCheat_EOS.exe', 'LeagueClient.exe']
```

**Recommended Fix:**
In `SessionWatcher._build_watch_plan()` (`watcher.py:116-124`), restrict `full_override_exes` strictly to `matched.game_exes` (and `target_exes`), and **always** preserve `never_override = catalog.global_anti_cheat_exes | {all always_strict_launchers} | {all entry.anti_cheat_exes}`:
```python
effective_protected = frozenset(
    (protected_exes - full_override_exes) | never_override
)
```

---

### PROC-04 [MEDIUM] — `SessionWatcher` and In-Flight WGC Capture Are Not Halted Immediately During `_emergency_shutdown()`

**Locations:**
- `gamehub/app.py:574-594, 863-888`
- `gamehub/core/capture/scheduler.py:94-97`
- `gamehub/modules/memory/controls_controller.py:156`
- `gamehub/modules/memory/notes_controller.py:431`

**Analysis:**
When `ProtectionGuard` detects a protected game on its background thread (`protection-guard`), it emits `guard_bridge.triggered` via `Qt.ConnectionType.QueuedConnection` (`app.py:596-599`), scheduling `_emergency_shutdown()` on the Qt main thread:
1. `_emergency_shutdown()` (`app.py:574-594`) stops `guard_watchdog`, suspends `hotkeys`, pauses `capture_scheduler`, stops `voice_player`, closes `protection_guard`, and calls `window.close(); app.quit()` — **it never signals `watcher` to stop**.
2. After `app.exec()` returns, `finally:` (`app.py:863-888`) executes `controls_controller.close()` (`self._worker.shutdown(wait=True)`, `controls_controller.py:156`) and `notes_controller.close()` (`self._worker.shutdown()`, `notes_controller.py:431`, defaulting to `wait=True`) **before** reaching `capture_scheduler.close()` (`app.py:880`) and `watcher.close()` (`app.py:882`).
3. Meanwhile, `SessionWatcher`'s background thread can execute another `ProcessProbe.snapshot()` cycle (`OpenProcess`), and `CaptureScheduler.close()` uses `wait=False` (`scheduler.py:97`), allowing an already-in-flight `WgcCapture._run_capture_attempt()` thread to continue calling `is_current()` → `WindowProbe.foreground()` → `OpenProcess` for up to `LEASE_SECONDS` (`2.0s`) until the lease expires.

**Recommended Fix:**
1. Share a lock-free `threading.Event` (`abort_handle_ops`) set synchronously **inside `ProtectionGuard`'s trigger callback** (before Qt queued delivery) and inside `_emergency_shutdown()`.
2. Check `abort_handle_ops.is_set()` immediately before any `OpenProcess` / `psutil` / WGC call in `ProcessProbe`, `WindowProbe`, and `CaptureService.is_current()`, and signal `watcher._stop.set()` inside `_emergency_shutdown()`.
3. During `emergency_exit[0]`, shut down `controls_controller` and `notes_controller` with `wait=False` after stopping `watcher` and `capture_scheduler` first.

---

### PROC-05 [MEDIUM] — "Test Protection" Self-Test Dummy `FortniteLauncher.exe` Is Not Exempted from `SessionWatcher`, Causing Spurious App Termination

**Locations:**
- `gamehub/app.py:663, 673-680, 1463-1478`
- `gamehub/core/protection/guard.py:557-594`
- `gamehub/core/sessions/watcher.py:193-218`
- `gamehub/core/protection/lifecycle.py:129-141`

**Analysis:**
When the user clicks "Test Protection" in Settings (`app.py:1463-1478`), `run_dummy_process_protection_test()` spawns a harmless copy of `ping.exe` renamed to `FortniteLauncher.exe` and calls `live_guard.ignore_pid(proc.pid)` (`guard.py:567`). However, `SessionWatcher` is neither paused nor informed of `proc.pid`.

If `SessionWatcher`'s 3-second poll overlaps the ~200–300ms lifetime of the dummy `FortniteLauncher.exe`:
- `ProcessProbe.snapshot()` records `"fortnitelauncher.exe"` in `snapshot.protected_exes`.
- `SessionWatcher._emit_protected_detections()` (`watcher.py:199-218`) publishes `ProtectedGameDetected(entry_id="fortnite", ...)`.
- `LifecycleCoordinator.on_protected_detected()` (`lifecycle.py:129-141`) sees the default `external_behavior == "exit_app"` and **immediately shuts down GameRewind**.

**Empirical Proof / Reproduction:**
Ran `SessionWatcher._emit_protected_detections()` wired to `LifecycleCoordinator(external_behavior="exit_app")` against dummy `(9999, "FortniteLauncher.exe")`:
```text
ProtectedGameDetected emitted: [ProtectedGameDetected(entry_id='fortnite', entry_name='Fortnite', anti_cheat='Easy Anti-Cheat / BattlEye', exe_name='fortnitelauncher.exe', game_id=None)]
LifecycleCoordinator called exit_app(): [True]
```

**Recommended Fix:**
Pause `SessionWatcher` (`watcher.pause()` / `watcher.resume()`) around `run_dummy_process_protection_test()` in `app.py:1469-1476`, or pass `ignored_pids` through `SessionWatcher` to `ProcessProbe.snapshot()` so the dummy self-test PID is excluded from `seen_protected`.

---

### PROC-06 [LOW] — `ProcessProbe.snapshot()` Opens 4 Separate `OpenProcess` Handles per Matched Game PID per Poll Cycle

**Locations:**
- `gamehub/core/sessions/processes.py:90-104, 128-129, 187-201`

**Analysis:**
For every matched non-protected game PID, `ProcessProbe.snapshot()` executes:
1. `self._matches()` (`processes.py:188`) → `OpenProcess(0x1000)` + `QueryFullProcessImageNameW` + `CloseHandle`
2. `self._creation_time(pid)` (`processes.py:196`) → `psutil.Process(pid).create_time()` → `OpenProcess(0x1000)` + `GetProcessTimes` + `CloseHandle`
3. `self._matches()` (`processes.py:197`) → `OpenProcess(0x1000)` + `QueryFullProcessImageNameW` + `CloseHandle`
4. `self._creation_time(pid)` (`processes.py:198`) → `psutil.Process(pid).create_time()` → `OpenProcess(0x1000)` + `GetProcessTimes` + `CloseHandle`

This 4-handle re-check pattern is unnecessary on Windows: a single `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` handle pins the exact kernel `EPROCESS` object for the duration of the handle, making PID reuse impossible between `QueryFullProcessImageNameW(handle)` and `GetProcessTimes(handle)`. Removing `psutil` here also eliminates any hidden `psutil` fallback behavior and cuts handle operations by 75%.

**Recommended Fix:**
Call `GetProcessTimes(handle, ...)` alongside `QueryFullProcessImageNameW(handle, ...)` on the **single** open handle inside `_WindowsProcessMetadata.inspect()`, and remove the `psutil` dependency from `gamehub/core/sessions/processes.py`.

---

### PROC-07 [LOW] — Minor Process-Detection Gaps in `ModsEngine` and `SessionWatcher`

**Locations:**
- `gamehub/modules/mods/engine.py:162-170`
- `gamehub/core/sessions/watcher.py:167`

**Analysis:**
1. `ModsEngine._collect_known_game_exes()` (`engine.py:166-168`) checks `for child in install_root.iterdir(): if child.suffix.lower() == ".exe"` — only top-level `.exe` files in `install_dir`. If a single-player Unreal/CDPR game has only its launcher registered in `game_targets` while its actual game binary lives in `Binaries/Win64/*.exe` or `bin/x64/*.exe`, `_assert_no_game_running()` could miss the running game binary. (Safe with respect to handles: strictly uses `ToolhelpProcessScanner`.)
2. `SessionWatcher._run()` (`watcher.py:167`) uses `if raw_targets is not next_raw or strict_games is not next_strict:` to detect whether `_build_watch_plan()` ran. In CPython, `()` is interned (`() is ()` is `True`), so this check only succeeds when `raw_targets` is empty because `frozenset(set())` happens not to return the empty `frozenset()` singleton in CPython 3.12 (`frozenset() is frozenset(set())` is `False`). Relying on object identity of empty containers is fragile across Python versions/implementations.

**Recommended Fix:**
1. Walk `install_root` up to bounded depth (e.g., depth ≤ 3, skipping reparse points) when collecting `.exe` basenames in `ModsEngine._collect_known_game_exes()`.
2. Track an explicit `reloaded = False` / `reloaded = True` boolean in `SessionWatcher._run()` instead of identity comparison (`is not`).

---

## Verdict

**Verdict: FAIL (7 open findings: PROC-01 [CRITICAL], PROC-02 [CRITICAL], PROC-03 [HIGH], PROC-04 [MEDIUM], PROC-05 [MEDIUM], PROC-06 [LOW], PROC-07 [LOW])**


---

## Round 2 Re-Audit Verification

- **Date:** 2026-11-24
- **Auditor:** Independent Red-Team Security Auditor (Focus b — Round 2)
- **Scope Verified:** `gamehub/core/sessions/processes.py`, `gamehub/core/sessions/watcher.py`, `gamehub/core/sessions/tracker.py`, `gamehub/core/capture/windows.py`, `gamehub/core/capture/service.py`, `gamehub/core/capture/scheduler.py`, `gamehub/core/protection/guard.py`, `gamehub/core/protection/catalog.py`, `gamehub/core/protection/protected_games.json`, `gamehub/modules/mods/engine.py`, `gamehub/app.py`, and controller teardown (`controls_controller.py`, `notes_controller.py`, `library_controller.py`).

### Per-Finding Verification Table

| ID | Round 1 Severity | Round 2 Status | Round 2 Severity | Verification Summary |
|---|---|---|---|---|
| `PROC-01` | CRITICAL | **CLOSED** | — | `psutil` removed completely; `WindowProbe.foreground()`, `CaptureService.acquire()`, `CaptureService.is_current()`, and `app.py:foreground_session()` never open any handle when 0 Full-mode games are active or foreground PID is not in `tracker.active_pids()`; `CaptureScheduler` stays paused until a Full-mode game runs. Verified live with dummy `VALORANT-Win64-Shipping.exe` (`0` handle calls). |
| `PROC-02` | CRITICAL | **OPEN** | **MEDIUM** | Primary GDK-with-`exe_path` path no longer triggers `package_id` scanning (`0` hits). Two defects remain: (1) `processes.py:313-316` checks `never_open` ONLY on `check_package`, NOT `check_image` (opening handles on `EpicGamesLauncher.exe`, `vgtray.exe`, `vgc.exe`, `GameLaunchHelper.exe` when matched via `exe_path`); (2) `package_id`-only Xbox targets still spray `OpenProcess(0x1000)` across **221/325 live Windows processes (99 unique exes)** every 3s, including AV (`avp.exe`), unlisted anti-cheat games, and missing companion exes. |
| `PROC-03` | HIGH | **OPEN** | **LOW** | `global_anti_cheat_exes` (`missing = []`) and `always_strict_launchers` (`missing = []`) are now preserved on per-game `"full"` overrides (`watcher.py:135-140`). However, per-game `entry.anti_cheat_exes` (e.g. `fortniteclient-win64-shipping_eac_eos.exe`, `gamemon64.des`) are not in `always_protected`, so `full_override_exes.update(target_exes)` (`watcher.py:130`) still strips `fortniteclient-win64-shipping_eac_eos.exe` from `effective_protected`. |
| `PROC-04` | MEDIUM | **CLOSED** | — | `_emergency_shutdown()` (`app.py:624-665`) stops `guard_watchdog`, suspends `hotkeys`, pauses `capture_scheduler`, stops `voice_player`, calls `watcher.close(wait=False)` and `protection_guard.close(wait=False)`, and terminates immediately via `os._exit(code)` when `hard_exit_on_emergency=True` (`app.py:1794`); `finally:` passes `wait=not emergency_exit[0]` to all controllers (verified `close(wait=...)` supported on `ControlsController`, `NotesController`, `LibraryController`). |
| `PROC-05` | MEDIUM | **OPEN** | **LOW** | `app.py:1577` passes `live_watcher=watcher` and `SessionWatcher` implements `ignore_pid()`/`unignore_pid()` (`watcher.py:56-62`). However, `guard.py:611-624` acquires `live_guard._scan_lock` across `Popen` + `ignore_pid` without acquiring `live_watcher._poll_lock` (or pausing `live_watcher`), leaving a race window where `watcher.py:176` snapshots an empty `_ignored_pids` just before `Popen` + `live_watcher.ignore_pid(proc.pid)`. |
| `PROC-06` | LOW | **CLOSED** | — | Verified live: `_WindowsProcessMetadata.inspect_with_time()` (`processes.py:169-184,318-333`) opens **1** `OpenProcess(0x1000, False, pid)` handle per matched candidate PID and queries `QueryFullProcessImageNameW` + `GetProcessTimes` atomically on that single pinned handle (`psutil` removed). |
| `PROC-07` | LOW | **OPEN** | **MEDIUM** | Part 1 (`ModsEngine._collect_known_game_exes()`) is **FIXED** (bounded depth-4 `_scan_dir_exes` skipping reparse points). Part 2 (**REGRESSION** in `watcher.py:192`): replacing `is not` with `!=` (`if raw_targets != next_raw or strict_games != next_strict:`) instead of a `reloaded` boolean causes `SessionWatcher` to drop all **102 `protected_exes`** down to **`0`** on Poll #2+ whenever `raw_targets` and `strict_games` are unchanged (e.g., empty library on startup). |

### Evidence for Closed Findings

- **`PROC-01` (CLOSED):**
  - `WindowProbe` (`gamehub/core/capture/windows.py:27-84`) has zero `psutil` references, takes `allowed_pids=tracker.active_pids` (`app.py:762`), and checks `pid not in effective_allowed` before invoking `self._creation_time(pid)`.
  - `CaptureService.acquire()` (`service.py:45-55`) and `app.py:foreground_session()` (`app.py:764-769`) immediately return `None` when `tracker.active_pids()` is empty; `CaptureService.is_current()` (`service.py:57-62`) passes `allowed_pids=frozenset({lease.window.process.pid})`.
  - `SessionTracker.active_pids()` (`tracker.py:110-112`) returns only PIDs with `created_at > 0.0` (excluding Strict-mode games which carry `created_at == 0.0`).
  - Live reproduction with harmless renamed `System32\ping.exe` → `VALORANT-Win64-Shipping.exe` (PID `37552`):
    ```text
    4a (0 active games, foreground=VALORANT pid=37552): acquire=None, foreground()=None, creation_time calls=[]
    4b (1 Full game pid=55555, foreground=VALORANT pid=37552): acquire=None, fg=None, is_current=False, creation_time calls=[]
    4c (Strict game pid=37552, created_at=0.0): active_pids=frozenset()
    ```

- **`PROC-04` (CLOSED):**
  - `_emergency_shutdown()` (`app.py:624-665`) stops `guard_watchdog`, suspends `hotkeys`, pauses `capture_scheduler`, stops `voice_player`, calls `watcher.close(wait=False)` (`app.py:639`), calls `protection_guard.close(wait=False)`, and in production (`main()` passes `hard_exit_on_emergency=True` at `app.py:1794`) closes `hotkeys` + `SingleInstance` and exits immediately via `os._exit(emergency_exit_code[0])`.
  - Non-hard-exit teardown (`app.py:963-988`) passes `wait=not emergency_exit[0]` to `protection_guard`, `move_worker`, `controls_controller`, `notes_controller`, `watcher`, and `controller` (all verified to implement `close(wait=...)`).

- **`PROC-06` (CLOSED):**
  - Live instrumented `ProcessProbe(_WindowsProcessMetadata()).snapshot([WatchTarget("self", "exe_path", my_img)])` confirmed exactly **1** `OpenProcess(0x1000, False, pid)` call per candidate `python.exe` PID (down from 4 in Round 1):
    ```text
    3d (PROC-06 single-handle check) matched=True,
       OpenProcess calls=[('0x1000', False, 33952), ('0x1000', False, 33236), ...]
       # 1 handle open per running python.exe PID, strictly access=0x1000
    ```

### Detailed Evidence & Required Fixes for Remaining Open Findings

#### `[PROC-02]` OPEN (MEDIUM) — `check_image` bypasses `never_open`, and `package_id`-only Xbox targets still spray `OpenProcess`

- **Locations:** `gamehub/core/sessions/processes.py:23-67,270-316`, `gamehub/core/library/xbox.py:244-270`
- **Empirical Evidence:**
  ```text
  3a (Xbox WITH exe_path + package_id) inspected: []
  3b (Xbox package_id ONLY) inspected (8/21):
      (1010, 'EABackgroundService.exe', False, True)
      (1011, 'EpicWebHelper.exe', False, True)
      (1012, 'SteamService.exe', False, True)
      (1013, 'Agent.exe', False, True)
      (1014, 'BEService_x64.exe', False, True)
      (1015, 'GTA5.exe', False, True)
      (1016, 'RobloxPlayerBeta.exe', False, True)
      (1020, 'chrome.exe', False, True)
  3b-live: Live OS procs=325, OpenProcess hits with 1 package_id-only target=221 (99 unique exes)
      Sample hit exes: ['agent_ovpnconnect.exe', ..., 'avp.exe', 'avpui.exe', ..., 'discord.exe', ...]
  3c (exe_path matching DEFAULT_NEVER_OPEN_EXES) inspected:
      [(1001, 'EpicGamesLauncher.exe', True, False),
       (1007, 'vgtray.exe', True, False),
       (1008, 'vgc.exe', True, False),
       (1021, 'GameLaunchHelper.exe', True, False)]
  ```
- **Recommended Fix:**
  1. Add `if norm_name in never_open: continue` immediately after `if is_protected: continue` (`processes.py:311`) so `never_open` unconditionally blocks `OpenProcess` on both `check_image` and `check_package`.
  2. Add `eabackgroundservice.exe`, `ealaunchhelper.exe`, `epicwebhelper.exe`, `steamservice.exe`, `agent.exe`, `beservice_x64.exe`, `beclient_x64.exe` to `DEFAULT_NEVER_OPEN_EXES`.
  3. Require a known executable basename shortlist before calling `OpenProcess` + `GetPackageFamilyName` for `package_id` targets (eliminating system-wide `OpenProcess` spraying on 200+ OS/AV/user processes).

#### `[PROC-07]` OPEN (MEDIUM — Regression) — `SessionWatcher._run()` drops all 102 `protected_exes` to `0` on Poll #2 when `raw_targets` & `strict_games` are unchanged

- **Location:** `gamehub/core/sessions/watcher.py:164-201` (specifically line 192)
- **Empirical Reproduction:**
  Ran `SessionWatcher._run()` for 2 polls with a real `ProtectedGamesCatalog.load(strict_load=True)` and an empty library (`store.watch_targets()` → `()`):
  ```text
  5b (PROC-07 empty-library poll protected_exes counts across 2 polls): [102, 0]
  ```
- **Root Cause:** On Poll #1, `self._reload_targets` is set, `_build_watch_plan(())` returns `next_protected` with 102 catalog exes and `next_strict = frozenset()`. Line 192 checks `if raw_targets != next_raw or strict_games != next_strict:`, which evaluates to `False` (`() != ()` and `frozenset() != frozenset()`). Consequently, `protected_exes = next_protected` (line 197) is skipped, and on Poll #2+ (`_reload_targets` is clear) `SessionWatcher` passes `protected_exes = frozenset()` (`0` exes) to `ProcessProbe.snapshot()`. (The same bug occurs on any `reload_protection()` that changes `protected_exes` or `exe_to_game` without altering `raw_targets`/`strict_games`.)
- **Recommended Fix:** Track an explicit `reloaded = False` flag before line 164, set `reloaded = True` inside `if self._reload_targets.is_set():`, and commit all updated plan variables (`raw_targets`, `active_targets`, `passive_basenames`, `protected_exes`, `exe_to_game`, `strict_games`) whenever `reloaded` is `True` (still calling `_finish_removed_games` when `raw_targets != next_raw or strict_games != next_strict`).
- *(Note: Part 1 of `PROC-07` — `ModsEngine._collect_known_game_exes()` — is **FIXED** via bounded depth-4 `_scan_dir_exes()` in `gamehub/modules/mods/engine.py:125-154,239-248`.)*

#### `[PROC-03]` OPEN (LOW) — Per-game `entry.anti_cheat_exes` can still be stripped via `target_exes` on `"full"` override

- **Location:** `gamehub/core/sessions/watcher.py:126-140`
- **Empirical Evidence:**
  Setting Apex Legends, Rainbow Six Siege, League of Legends, Delta Force, and Fortnite (with `target_exes` containing `FortniteClient-Win64-Shipping_EAC_EOS.exe`) to `protection_mode="full"`:
  ```text
  5a (PROC-03) missing global_anti_cheat_exes: []
  5a (PROC-03) missing always_strict_launchers: []
  5a (PROC-03) missing per-game entry.anti_cheat_exes: ['fortniteclient-win64-shipping_eac_eos.exe']
  ```
- **Recommended Fix:** In `watcher.py:135-137`, also union every catalog entry's `anti_cheat_exes` into `always_protected`:
  ```python
  for entry in self._catalog.entries:
      always_protected.update(entry.anti_cheat_exes)
  ```

#### `[PROC-05]` OPEN (LOW) — Lock race between `run_dummy_process_protection_test()` and `SessionWatcher._run()`

- **Locations:** `gamehub/core/protection/guard.py:611-637`, `gamehub/core/sessions/watcher.py:175-189`
- **Analysis:** `guard.py:612` holds `live_guard._scan_lock` across `subprocess.Popen(...)` + `live_guard.ignore_pid(proc.pid)` so `live_guard` cannot race with spawn, but does NOT acquire `live_watcher._poll_lock` (or call `live_watcher.pause()` / `resume()`). If `SessionWatcher._run()` executes `ignored_pids = frozenset(self._ignored_pids)` (`watcher.py:176`) right before `Popen` + `live_watcher.ignore_pid(proc.pid)` (`guard.py:623`), `ProcessProbe.snapshot()` runs with an empty `ignored_pids` and can observe the dummy `FortniteLauncher.exe`, triggering `ProtectedGameDetected` → `exit_app()`.
- **Recommended Fix:** Acquire `live_watcher._poll_lock` (or call `live_watcher.pause()` before `Popen` and `live_watcher.resume()` in `finally:` after `live_watcher.ignore_pid(proc.pid)`) in `guard.py:611-637`.

---

### Round 2 Verdict (Focus b)

**FAIL — 4 open findings: `PROC-02` (MEDIUM), `PROC-07` (MEDIUM — regression), `PROC-03` (LOW), `PROC-05` (LOW).**
*(3 Round 1 findings CLOSED: `PROC-01`, `PROC-04`, `PROC-06`.)*
