# Red-Team Security Audit — Focus (a): Static Codebase & Dependency Scan

- **Target:** GameRewind (`e:\projects\game hub`) — `gamehub/` (83 files), `packaging/` (13 files), `tests/` (41 files), plus installed runtime dependencies in `.venv` and built artifacts under `dist/GameRewind/`
- **Audit Scope:** Focus (a) — Static Scan Only (Win32/NT APIs, memory/injection/hooks/input simulation, drivers/services/elevation, packers, network surface, dependency PE imports & internals, and `tests/test_packaging.py` coverage)
- **Date:** 2026-11-24
- **Auditor:** Independent Red-Team Security Auditor (Focus a)
- **Verdict:** **FAIL (6 open findings: `STATIC-001`, `STATIC-002`, `STATIC-003`, `STATIC-004`, `STATIC-005`, `STATIC-006`; plus 1 informational observation: `STATIC-007`)**

---

## Executive Summary

A full AST, regex, and PE binary import/call-graph audit of `gamehub/`, `packaging/`, `tests/`, `.venv` runtime dependencies (`PySide6 6.12.0`, `windows-capture 2.0.1`, `psutil 7.2.2`, `sounddevice 0.5.6`, `soundfile 0.14.0`, `Pillow 12.3.0`, `opencv-python 5.1.0.95`), and `dist/GameRewind/GameRewind.exe` confirmed:

- **Clean areas:** Zero occurrences in `gamehub/` of `ReadProcessMemory`, `WriteProcessMemory`, `NtReadVirtualMemory`, `NtWriteVirtualMemory`, `CreateRemoteThread`, `VirtualAllocEx`, `QueueUserAPC`, `SetThreadContext`, `SetWindowsHookEx`, `SetWinEventHook`, `AppInit_DLLs`, `SendInput`, `keybd_event`, `mouse_event`, `CreateService`, `StartService`, `DeviceIoControl`, `QSystemTrayIcon`, `runas`, `requireAdministrator`, `highestAvailable`, or UPX packing (`upx=False` and zero UPX markers in `dist/GameRewind/`). Outbound networking is strictly isolated to opt-in `gamehub/core/library/steamgriddb.py` (disabled by default). `windows-capture` uses pure WinRT Windows Graphics Capture (`GraphicsCaptureItem` / `Direct3D11CaptureFramePool`) with zero injection, hooking, or `OpenProcess` imports.
- **Critical/High-risk gaps uncovered (FAIL):**
  1. **`STATIC-001` (HIGH):** Top-level `import psutil` in `gamehub/app.py` (via `capture/windows.py:12` and `sessions/processes.py:10`) invokes `PyInit__psutil_windows` → `AdjustTokenPrivileges("SeDebugPrivilege")` **at every startup BEFORE `ProtectionGuard.self_check()` executes**, and bundles `_psutil_windows.pyd` (which statically imports `ReadProcessMemory`, `VirtualQueryEx`, `OpenProcessToken`, `AdjustTokenPrivileges`, `StartServiceA`) solely for a single `create_time()` call.
  2. **`STATIC-002` (HIGH):** `ProcessProbe.snapshot()` (`gamehub/core/sessions/processes.py:184-188`) calls `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` on **every non-cataloged running process on Windows every 3 seconds** whenever the user has even one Xbox/MS Store `package_id` target — including `vgtray.exe`, `EpicGamesLauncher.exe`, `EADesktop.exe`, `FACEITClient.exe`, and OS processes.
  3. **`STATIC-003` (HIGH):** `WindowProbe.foreground()` (`gamehub/core/capture/windows.py:56-69`) unconditionally calls `psutil.Process(pid).create_time()` (which calls `OpenProcess`) on **whatever window is currently in the foreground** — even when zero games are tracked — because `CaptureScheduler` runs every 30s (down to 5s) from startup and `CaptureService.acquire()` probes the foreground window before checking `SessionTracker.active_for()`.
  4. **`STATIC-004` (MEDIUM):** `tests/test_packaging.py` uses literal substring checks with major bypass and coverage blind spots (misses dynamic `getattr`/concatenation, `importlib`/`__import__`, `psutil.Process` indirect `OpenProcess`, numeric access masks inside `processes.py`, and dozens of forbidden NT/Win32/Qt/network symbols).
  5. **`STATIC-005` (LOW):** `XboxDetector` spawns `powershell.exe -Command ...` on every library refresh (including automatically at startup), directly contradicting the project's own anti-AV/anti-cheat heuristic rule documented in `notifications/windows.py:50`.
  6. **`STATIC-006` (LOW):** Opt-in `steamgriddb.py` follows default `urllib.request` redirects (allowing HTTPS→HTTP downgrade or cross-host redirects) and accepts any `https://` image URL without CDN hostname allowlisting.

---

## Complete API & Surface Verification Matrix

| Category | Direct in `gamehub/` | Indirect via Dependencies / Packaging | Status |
|---|---|---|---|
| `OpenProcess` / `NtOpenProcess` | `gamehub/core/sessions/processes.py:57,93` (`0x1000` only) | `psutil.Process(pid).create_time()` (`capture/windows.py:64`, `processes.py:129`) → `_psutil_windows.pyd` `OpenProcess` | **FAIL** (`STATIC-001`, `STATIC-002`, `STATIC-003`) |
| `ReadProcessMemory` / `WriteProcessMemory` / `Nt*VirtualMemory` | None (0 hits) | Statically imported in bundled `_psutil_windows.pyd` (not invoked by `gamehub/`) | **FAIL** (`STATIC-001` — unneeded binary import) |
| `CreateRemoteThread` / `VirtualAllocEx` / `QueueUserAPC` / `SetThreadContext` | None (0 hits) | `opencv_videoio_ffmpeg510_64.dll` imports `SetThreadContext` (unused FFmpeg DLL via transitive `cv2`) | **INFO** (`STATIC-007`) |
| `SetWindowsHookEx` / `SetWinEventHook` / DLL injection / `AppInit_DLLs` | None (0 hits). Hotkeys use `RegisterHotKey`/`UnregisterHotKey` (`core/hotkeys/windows.py:90,93`) | `PySide6/opengl32sw.dll` imports `SetWindowsHookExA` (standard Mesa software GL, unused on HW GPU) | **PASS** (see `STATIC-007`) |
| `SendInput` / `keybd_event` / `mouse_event` | None (0 hits) | `qwindows.dll` / `qdirect2d.dll` (standard Qt platform plugins) | **PASS** (see `STATIC-007`) |
| Kernel drivers / `CreateService` / `StartService` / SCM | Read-only SCM only: `OpenSCManagerW(0x0001)` + `OpenServiceW(0x0004)` + `QueryServiceStatusEx` (`core/protection/guard.py:167-235`) | `_psutil_windows.pyd` imports `StartServiceA`, `OpenProcessToken`, `AdjustTokenPrivileges` and calls `AdjustTokenPrivileges("SeDebugPrivilege")` on `import psutil` | **FAIL** (`STATIC-001`) |
| Elevation (`requireAdministrator` / `highestAvailable` / `runas`) | None (0 hits). `ShellExecuteW` verb hardcoded `"open"` (`core/library/launcher.py:148`). `GameRewind.manifest`: `asInvoker`, `uiAccess="false"`. `installer.iss`: `PrivilegesRequired=lowest`, `PrivilegesRequiredOverridesAllowed=` | Embedded `RT_MANIFEST` in `dist/GameRewind/GameRewind.exe` verified `asInvoker` | **PASS** |
| Packers (`upx=True` / UPX markers) | `packaging/gamerewind.spec:81,91` both set `upx=False` | 0 occurrences of `UPX0`/`UPX1`/`UPX!` in `dist/GameRewind/GameRewind.exe` and all DLLs/PYDs in `_internal/` | **PASS** |
| Registry / Autostart / Background presence | All `winreg` calls strictly `KEY_READ`, except `core/startup.py:19-24` which ONLY calls `DeleteValue` on legacy `HKCU\...\Run\GameHub` & `GameRewind`. Zero `QSystemTrayIcon`. `installer.iss:50-51` deletes legacy `Run` values with `dontcreatekey` | None | **PASS** |
| Network imports / calls | `urllib` ONLY in opt-in `gamehub/core/library/steamgriddb.py:11-13` (default off). `PySide6.QtNetwork` ONLY in `gamehub/single_instance.py:9` (`QLocalServer`/`QLocalSocket` named pipe with `UserAccessOption`). `QDesktopServices.openUrl` ONLY in `app.py:1494` (`QUrl.fromLocalFile`) | No `QtWebEngine`, no `requests`/`socket`/`http.client` in `gamehub/`. Redirect/host hardening needed in `steamgriddb.py` | **LOW** (`STATIC-006`) |
| `tests/test_packaging.py` static gate | Passes (`2 passed in 0.24s`), but misses dynamic lookups, `psutil.Process`, `processes.py` masks, and key forbidden APIs | N/A | **FAIL** (`STATIC-004`) |

---

## Detailed Findings

### [STATIC-001] HIGH — Top-level `import psutil` invokes `AdjustTokenPrivileges("SeDebugPrivilege")` at startup before `ProtectionGuard.self_check()` and bundles dangerous Win32 imports

- **Severity:** **HIGH**
- **Location:**
  - `gamehub/app.py:30` (`from gamehub.core.capture.windows import WgcCapture, WindowProbe`)
  - `gamehub/app.py:70` (`from gamehub.core.sessions.processes import ProcessProbe`)
  - `gamehub/core/capture/windows.py:12,64`
  - `gamehub/core/sessions/processes.py:10,129`
  - `dist/GameRewind/_internal/psutil/_psutil_windows.pyd` (`psutil==7.2.2`)

#### Evidence & Reproduction
Inspecting `.venv\Lib\site-packages\psutil\_psutil_windows.pyd` via `pefile` and `.pdata` `RUNTIME_FUNCTION` + `.text` RIP-relative call-graph analysis:

```text
=== ADVAPI32 imports in _psutil_windows.pyd ===
  OpenProcessToken
  ImpersonateSelf
  LookupPrivilegeValueA
  RevertToSelf
  AdjustTokenPrivileges
  StartServiceA
  ControlService
  ...
=== KERNEL32 imports in _psutil_windows.pyd ===
  OpenProcess, ReadProcessMemory, VirtualQueryEx, TerminateProcess, GetProcessTimes, ...

SeDebugPrivilege file_off=0xcfb0 rva=0xe1b0
Export: PyInit__psutil_windows rva=0x10b0
Function containing SeDebugPrivilege ref: ['0x8510', '0x8748']
Code RVAs referencing SeDebugPrivilege: ['0x8627']
PyInit__psutil_windows: ['0x10b0', '0x162d']
Direct callers of SeDebugPrivilege func: [('0x10b0', '0x162d', '0x11d5')]
```

1. When Python executes `import psutil` (triggered at module load time in `gamehub/app.py:30` and `app.py:70`), `PyInit__psutil_windows` (`0x10b0..0x162d`) directly calls (`0x11d5`) `psutil_set_se_debug()` (`0x8510..0x8748`), which calls `ImpersonateSelf` → `OpenProcessToken` → `LookupPrivilegeValueA("SeDebugPrivilege")` → `AdjustTokenPrivileges`.
2. This executes **before `_run()` and `ProtectionGuard.self_check()` (`gamehub/app.py:397`) even start** — meaning even when GameRewind refuses to launch because Valorant/Vanguard or Fortnite/EAC is running, the process has ALREADY attempted to enable `SeDebugPrivilege`!
3. Although a non-elevated `asInvoker` user token fails `AdjustTokenPrivileges` with `ERROR_NOT_ALL_ASSIGNED`, the privilege-escalation attempt itself is observable to kernel/EDR/anti-cheat telemetry. Worse, if a user launches GameRewind from an elevated context (e.g., admin shell or UAC disabled), `psutil` **actually activates `SeDebugPrivilege`** on GameRewind's token.
4. Across the entire 83-file `gamehub/` codebase, `psutil` is used for **only one operation**: `psutil.Process(pid).create_time()` (`capture/windows.py:64` and `sessions/processes.py:129`). Shipping `_psutil_windows.pyd` (which also statically imports `ReadProcessMemory`, `VirtualQueryEx`, `TerminateProcess`, `StartServiceA`) solely for `GetProcessTimes` is both unnecessary and directly violates the spirit of `AGENTS.md` ("Never inject, hook, read memory of, or open handles with write or debug rights").

#### Recommended Fix
- Remove `psutil` completely from runtime code (`gamehub/core/sessions/processes.py`, `gamehub/core/capture/windows.py`), `requirements.txt`, and `packaging/gamerewind.spec` (keep `psutil` only in `requirements-dev.txt` if needed by tests).
- In `gamehub/core/sessions/processes.py`, read the creation timestamp via `kernel32.GetProcessTimes` on the **already-opened** `PROCESS_QUERY_LIMITED_INFORMATION` handle inside `_WindowsProcessMetadata.inspect()`, returning `(image, family, creation_time)` in a single handle open instead of four separate `OpenProcess` calls.

---

### [STATIC-002] HIGH — `ProcessProbe.snapshot()` sweeps EVERY non-cataloged Windows process with `OpenProcess` every 3 seconds whenever any Xbox `package_id` target exists

- **Severity:** **HIGH**
- **Location:**
  - `gamehub/core/sessions/processes.py:184-188`
  - `gamehub/core/sessions/watcher.py:24,91,159-164`
  - `gamehub/core/library/xbox.py:245-250`
  - `gamehub/core/protection/protected_games.json`

#### Evidence & Reproduction
In `gamehub/core/sessions/processes.py:184-188`:
```python
check_image = norm_name in basenames
if not check_image and not packages:
    continue
try:
    matches = self._matches(pid, check_image, executables, packages)
```
When a user has **even one** installed Xbox/MS Store game, `XboxDetector` adds a `GameTarget("package_id", ...)` (`xbox.py:249`). As a result, `packages` is non-empty (`bool(packages) == True`), so `if not check_image and not packages:` is **always `False`**. Every 3 seconds (`POLL_INTERVAL_SEC = 3.0`), `ProcessProbe.snapshot()` calls `self._metadata.inspect(pid, executable=False, package=True)` → `kernel32.OpenProcess(0x1000, False, pid)` (`processes.py:93`) on **every single running process on Windows** not present in `protected_exes`.

Live reproduction command using `.venv\Scripts\python.exe` against the real bundled `ProtectedGamesCatalog.load()`:
```text
With 1 Xbox package_id target, OpenProcess/inspect() called on PIDs:
  [(100, False, True), (101, False, True), (102, False, True), (103, False, True), (104, False, True)]
  # 100=vgtray.exe, 101=EpicGamesLauncher.exe, 102=EADesktop.exe, 103=FACEITClient.exe, 104=explorer.exe
vgtray.exe in catalog.all_exe_names(): False
epicgameslauncher.exe in catalog.all_exe_names(): False
eadesktop.exe in catalog.all_exe_names(): False
faceitclient.exe in catalog.all_exe_names(): False
```

Impact:
- `OpenProcess` (even with `PROCESS_QUERY_LIMITED_INFORMATION = 0x1000`) invokes kernel `ObRegisterCallbacks` registered by anti-cheat drivers and EDRs.
- Anti-cheat companion processes not listed in `protected_games.json` — notably **`vgtray.exe` (Riot Vanguard tray)**, **`FACEITClient.exe` / `faceitservice.exe`**, **`EABackgroundService.exe`**, **`EpicGamesLauncher.exe`** (when optional strict launcher is off, default), **`EADesktop.exe`**, plus **any anti-cheat game not in the 38-game catalog**, plus OS processes (`lsass.exe`, `csrss.exe`, etc.) — all receive an `OpenProcess` handle attempt every 3 seconds.

#### Recommended Fix
1. Eliminate unbounded system-wide `OpenProcess` iteration for `package_id` targets. `XboxDetector` already extracts concrete `exe_path` targets from `MicrosoftGame.config` (`xbox.py:224-240`); require `norm_name in basenames` (or match against a strict set of known game exe basenames for that Xbox game) BEFORE calling `inspect()` / `OpenProcess`. Never call `OpenProcess` on arbitrary system processes just because `packages` is non-empty.
2. Add missing anti-cheat / companion executables to `protected_games.json` (e.g., `vgtray.exe`, `faceitclient.exe`, `faceitservice.exe`, `eabackgroundservice.exe`, `ealaunchhelper.exe`, `beclient_x64.exe`).

---

### [STATIC-003] HIGH — `WindowProbe.foreground()` unconditionally calls `psutil.Process(pid).create_time()` (`OpenProcess`) on arbitrary foreground windows even when zero games are tracked

- **Severity:** **HIGH**
- **Location:**
  - `gamehub/core/capture/windows.py:56-69`
  - `gamehub/core/capture/service.py:40-47`
  - `gamehub/core/capture/scheduler.py:26-44`
  - `gamehub/app.py:684-686,850-851`

#### Evidence & Reproduction
In `gamehub/core/capture/windows.py:56-69`:
```python
def foreground(self) -> WindowIdentity | None:
    hwnd = self._foreground()
    if not hwnd:
        return None
    pid = self._eligible_owner(hwnd)
    if not pid:
        return None
    try:
        created_at = psutil.Process(pid).create_time()
    except (psutil.Error, OSError):
        return None
```
And in `gamehub/core/capture/service.py:40-46`:
```python
def acquire(self) -> CaptureLease | None:
    window = self._windows.foreground()
    if window is None:
        return None
    session = self._tracker.active_for(window.process)
```
And in `gamehub/app.py:850-851`:
- `capture_scheduler.start()` starts a periodic `QTimer` immediately on startup (every 30s default, configurable down to 5s in `settings.py:13`), **even when no game is running**.
- On every timer tick (and on every global hotkey press via `foreground_session()` at `app.py:684-686`), `WindowProbe.foreground()` calls `psutil.Process(pid).create_time()` BEFORE checking whether `SessionTracker` has any active tracked game or whether `pid` belongs to a tracked non-protected game.
- Inside `psutil` (`psutil/_pswindows.py:910-922` and `psutil/__init__.py`), `psutil.Process(pid).create_time()` calls `cext.proc_times(pid)` → `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid)` (twice on `AccessDenied`, then falls back to `NtQuerySystemInformation`).

Live reproduction command using `.venv\Scripts\python.exe` with `SessionTracker.active_for` returning `None` (zero tracked games):
```text
Lease returned: None
psutil.Process(pid) called with PIDs even with ZERO active games: [4242]
```

Impact:
- If a protected game or anti-cheat window is focused (during `ProtectionGuard`'s up-to-300ms poll + queued Qt shutdown window, or for any non-cataloged anti-cheat game, or if a user presses a hotkey), GameRewind opens a process handle to that foreground protected game window.
- Even during normal desktop use with no games running, GameRewind periodically opens process handles to whatever foreground app the user is using (browser, password manager, anti-cheat launcher, etc.).

#### Recommended Fix
1. Gate `CaptureService.acquire()` and `foreground_session()` on `SessionTracker` having an active eligible PID **first**: resolve `(hwnd, pid)` using only `GetForegroundWindow()` + `GetWindowThreadProcessId()` (zero process handles!), check if `pid` is in `tracker.active_pids()` (which only contains verified, non-strict tracked game PIDs), and ONLY THEN verify process creation time via `GetProcessTimes`.
2. Do not run the `CaptureScheduler` timer at all when zero non-strict games are active: start the timer only when a full-mode `GameStarted` fires and stop it when the last full-mode `GameStopped` fires.

---

### [STATIC-004] MEDIUM — `tests/test_packaging.py` static security test has critical bypass and coverage blind spots

- **Severity:** **MEDIUM**
- **Location:** `tests/test_packaging.py:6-80`

#### Evidence
Reviewing `tests/test_packaging.py` line-by-line reveals concrete blind spots that already allowed `STATIC-001` and `STATIC-003` to pass CI (`2 passed in 0.24s`):

1. **Indirect `OpenProcess` missed completely:** Line 66-67 checks `assert "OpenProcess" not in source` outside `processes.py`, which failed to catch `psutil.Process(pid).create_time()` in `gamehub/core/capture/windows.py:64` and `import psutil` calling `AdjustTokenPrivileges("SeDebugPrivilege")`.
2. **`processes.py` completely exempted from `OpenProcess` rights verification:** Line 66 (`if rel != "gamehub/core/sessions/processes.py":`) does not assert that `processes.py` only passes `_QUERY_LIMITED_INFORMATION` (`0x1000`), nor does it block numeric access masks (`0x1F0FFF`, `0x0010`, `0x0020`, `0x0008`, `0x0400`).
3. **Trivially bypassed literal substring matching:** Line 65 (`assert symbol not in source`) is defeated by:
   - String concatenation / dynamic attribute lookup: `getattr(kernel32, "Open" + "Process")`
   - Dynamic module loading: `importlib.import_module("socket")`, `__import__("urllib.request")`, `eval(...)`, `exec(...)` (none are checked in the AST walk!)
   - Arbitrary `ctypes.WinDLL("ntdll")` / `ctypes.CDLL(...)` / `ctypes.windll.*` loads (no allowlist of permitted DLLs/symbols).
   - Whitespace/truthy variants in `gamerewind.spec` (e.g., `upx = True` or `upx=1`).
4. **Missing critical forbidden Win32/NT/Qt/network symbols:**
   - Process/memory/thread/injection/hook APIs: `NtOpenProcess`, `ZwOpenProcess`, `NtAllocateVirtualMemory`, `NtProtectVirtualMemory`, `VirtualProtectEx`, `VirtualQueryEx`, `NtCreateThreadEx`, `RtlCreateUserThread`, `CreateRemoteThreadEx`, `QueueUserAPC`, `NtQueueApcThread`, `SetThreadContext`, `GetThreadContext`, `SuspendThread`, `SetWinEventHook`, `LoadLibraryA`, `LoadLibraryW`, `LoadLibraryExA`, `LoadLibraryExW`, `GetProcAddress`, `AppInit_DLLs`, `GetAsyncKeyState`, `GetKeyState`, `GetKeyboardState`, `RegisterRawInputDevices`, `BitBlt`, `PrintWindow`.
   - Driver/service/privilege/elevation APIs: `CreateService`, `StartService`, `DeviceIoControl`, `NtLoadDriver`, `ZwLoadDriver`, `AdjustTokenPrivileges`, `OpenProcessToken`, `LookupPrivilegeValue`, `SE_DEBUG_NAME`, `"runas"`.
   - Network/Qt/process modules & classes: `ssl`, `asyncio`, `xmlrpc`, `webbrowser`, `imaplib`, `poplib`, `QWebSocket`, `QWebEngineView`, `QWebEnginePage`, `QNetworkRequest`, `QNetworkReply`, `QSslSocket`, `QDnsLookup`, `QHostInfo`, `QProcess`.
   - `PySide6.QtNetwork` is not allowlist-restricted to only `QLocalServer` and `QLocalSocket` in `gamehub/single_instance.py`.

#### Recommended Fix
Upgrade `tests/test_packaging.py` to enforce an AST-based allowlist policy:
- Allowlist every `(file, dll, exported_symbol)` used via `ctypes` and fail on any unlisted DLL/symbol or dynamic `getattr`/`GetProcAddress` on DLL objects.
- Ban `importlib.import_module`, `__import__`, `eval`, `exec`, `compile`, and `psutil` inside `gamehub/`.
- Restrict `PySide6.QtNetwork` imports exclusively to `QLocalServer` and `QLocalSocket` in `gamehub/single_instance.py`.
- Verify `OpenProcess` in `processes.py` uses strictly `_QUERY_LIMITED_INFORMATION = 0x1000`.
- Expand `FORBIDDEN_NATIVE_SYMBOLS` and `FORBIDDEN_NETWORK_MODULES` with all missing symbols listed above, and parse `gamerewind.spec` with `ast.parse` to assert every `EXE`/`COLLECT` call explicitly passes `upx=False`.

---

### [STATIC-005] LOW — `XboxDetector` spawns `powershell.exe` on every library refresh (including startup)

- **Severity:** **LOW**
- **Location:**
  - `gamehub/core/library/xbox.py:21-27,146-165`
  - `gamehub/app.py:476,852`
  - Contrast with `gamehub/core/notifications/windows.py:50-51`

#### Evidence
`gamehub/core/library/xbox.py:156-165` resolves `System32\WindowsPowerShell\v1.0\powershell.exe` via `GetSystemDirectoryW` and executes:
```python
result = subprocess.run(
    [str(powershell), "-NoProfile", "-NonInteractive", "-Command", _PACKAGE_COMMAND],
    capture_output=True,
    shell=False,
    creationflags=subprocess.CREATE_NO_WINDOW,
    check=True,
    timeout=8,
    encoding="utf-8",
)
```
Because `QTimer.singleShot(0, controller.refresh)` runs automatically at startup (`app.py:852`), an unsigned PyInstaller-frozen `GameRewind.exe` spawns a hidden `powershell.exe -Command ...` child process on every launch. There is no command injection (the command string `_PACKAGE_COMMAND` is hardcoded and read-only), **however** GameRewind's own `gamehub/core/notifications/windows.py:50-51` explicitly documents avoiding `powershell.exe` because it *"triggers AV/anti-cheat heuristics"*.

#### Recommended Fix
Replace the `powershell.exe` subprocess in `gamehub/core/library/xbox.py:_installed_packages()` with a read-only `winreg` enumeration of `HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages` (or native WinRT `PackageManager` query), eliminating all `powershell.exe` process spawns.

---

### [STATIC-006] LOW — Opt-in `steamgriddb.py` allows default HTTP redirects and unvalidated HTTPS image hostnames

- **Severity:** **LOW**
- **Location:** `gamehub/core/library/steamgriddb.py:23-32,35-47,95-96`

#### Evidence
1. `_default_get_bytes()` checks `parsed.scheme != "https"` on the initial URL, then calls `urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_SEC)` using Python's default opener, which automatically follows 301/302/307/308 redirects — including redirects that downgrade `https://` to `http://` or target non-SteamGridDB/private hosts.
2. `_extract_grid_url()` (`lines 44-47`) accepts any `url` starting with `"https://"` returned by the JSON payload without validating the hostname against SteamGridDB CDN domains (`*.steamgriddb.com`).
3. Mitigating context: strictly opt-in (`covers.steamgriddb_enabled=False` by default, requires non-empty user API key, never runs automatically on startup — only on explicit "Fetch missing covers" click in Settings, and `image_headers` omits the `Authorization` header on line 95).

#### Recommended Fix
Build a dedicated `urllib.request.OpenerDirector` with a custom `HTTPRedirectHandler` that rejects non-HTTPS redirect targets and restricts hostnames to `steamgriddb.com` / `*.steamgriddb.com`, and enforce the same hostname allowlist in `_extract_grid_url()`.

---

### [STATIC-007] INFO (Observation) — Runtime Dependency Deep-Dive (`windows-capture`, `opencv-python`, `PySide6`, `sounddevice`, `soundfile`, `Pillow`)

All runtime dependencies in `.venv` and `dist/GameRewind/_internal/` were inspected at both the Python source and PE import-table level:

1. **`windows-capture 2.0.1` (`windows_capture.pyd`):** **CLEAN.** Uses pure WinRT Windows Graphics Capture (`api-ms-win-core-winrt-l1-1-0.dll`: `RoInitialize`, `RoGetActivationFactory`; `d3d11.dll`: `D3D11CreateDevice`, `CreateDirect3D11DeviceFromDXGIDevice`; `dwmapi.dll`: `DwmGetWindowAttribute`; `coremessaging.dll`: `CreateDispatcherQueueController`; strings `GraphicsCaptureItem`, `Direct3D11CaptureFramePool`). Zero `OpenProcess`, `ReadProcessMemory`, `SetWindowsHookEx`, `BitBlt`, `PrintWindow`, or injection imports.
2. **`opencv-python 5.1.0.95` (`cv2`):** **UNUSED DIRECTLY — TRANSITIVE BLOAT.** `gamehub/` never imports `cv2`. It is pulled in solely because `windows_capture/__init__.py:7` does `import cv2` for `Frame.save_as_image()` (which GameRewind never calls; GameRewind copies `frame.frame_buffer` and encodes WebP via Pillow). As a result, `dist/GameRewind/_internal/cv2/opencv_videoio_ffmpeg510_64.dll` is bundled (which statically imports `KERNEL32.dll!OpenProcess` and `SetThreadContext` from FFmpeg/pthreads-win32, though never called by GameRewind).
3. **`PySide6 6.12.0`:**
   - `gamehub/` imports only `QtCore`, `QtGui`, `QtWidgets`, `QtMultimedia` (local Ogg playback via `QBuffer`), and `QtNetwork` (strictly `QLocalServer` + `QLocalSocket` in `gamehub/single_instance.py:9` with `UserAccessOption` for single-instance named-pipe activation — zero TCP/UDP/HTTP usage).
   - Zero `QSystemTrayIcon`, zero `QtWebEngine` (confirmed `Qt6WebEngineCore.dll` is NOT in `dist/GameRewind/_internal/`).
   - Standard Qt platform DLLs (`qwindows.dll`, `qdirect2d.dll`, `Qt6Core.dll`, `opengl32sw.dll`) statically import standard Windows APIs (`SendInput`, `OpenProcess`, `SetWindowsHookExA` in Mesa `opengl32sw.dll`) internally for Qt GUI/IME/accessibility/software-GL support; none are called by GameRewind against game processes.
4. **`sounddevice 0.5.6` & `soundfile 0.14.0`:** **CLEAN.** `packaging/gamerewind.spec:66-72` strips 32-bit/ARM/ASIO PortAudio variants, bundling only `libportaudio64bit.dll` and `libsndfile_x64.dll`. Neither DLL imports any process-inspection, hooking, injection, or network APIs.
5. **`Pillow 12.3.0` (`PIL`):** **CLEAN.** Zero suspicious Win32/NT/network imports across all 8 compiled binaries. Used strictly for local WebP/PNG/JPG encoding & thumbnailing.
6. **Packaging & Manifest (`packaging/` & `dist/GameRewind/`):** **CLEAN.**
   - `packaging/GameRewind.manifest` and the embedded `RT_MANIFEST` resource in `dist/GameRewind/GameRewind.exe` both declare `<requestedExecutionLevel level="asInvoker" uiAccess="false"/>`.
   - `packaging/gamerewind.spec` sets `upx=False` on both `EXE` (line 81) and `COLLECT` (line 91); zero UPX sections or markers exist in `dist/GameRewind/GameRewind.exe` or `_internal/`.
   - `packaging/installer.iss` sets `PrivilegesRequired=lowest`, `PrivilegesRequiredOverridesAllowed=`, and only deletes legacy `HKCU\...\Run` values with `dontcreatekey`.

---

## Verdict

**FAIL — 6 open findings: `STATIC-001` (HIGH), `STATIC-002` (HIGH), `STATIC-003` (HIGH), `STATIC-004` (MEDIUM), `STATIC-005` (LOW), `STATIC-006` (LOW).**
(Plus 1 informational observation: `STATIC-007`.)


---

## Round 2 Re-Audit Verification

- **Date:** 2026-11-24
- **Auditor:** Independent Red-Team Security Auditor (Focus a — Round 2)
- **Scope Verified:** Current source tree (`gamehub/`, `packaging/`, `tests/`, `requirements.txt`), live `pytest` execution (`tests/test_packaging.py` + 70-test security/process/capture/xbox/covers slice), and rebuilt frozen bundle `dist/GameRewind/GameRewind.exe` (`5,729,622` bytes) + `dist/GameRewind/_internal/`.

### Per-Finding Verification Table

| ID | Round 1 Severity | Round 2 Status | Round 2 Severity | Verification Summary |
|---|---|---|---|---|
| `STATIC-001` | HIGH | **CLOSED** | — | `psutil` is 100% removed from `gamehub/`, `requirements.txt`, `packaging/gamerewind.spec` (`excludes=['psutil']`), `dist/GameRewind/GameRewind.exe` (CArchive + PYZ TOC = `[]`, `b'psutil'` absent), and `dist/GameRewind/_internal/` (0 files). `asInvoker` manifest and zero UPX markers re-confirmed. |
| `STATIC-002` | HIGH | **OPEN** | **MEDIUM** | Xbox games with `exe_path` targets now skip `package_id` (`0` handles opened), and `DEFAULT_NEVER_OPEN_EXES` + `all_launcher_exe_names()` were added. However, two defects remain: (1) `processes.py:313-316` checks `never_open` ONLY on `check_package`, NOT `check_image`; (2) any `package_id`-only Xbox target still sprays `OpenProcess(0x1000)` across **221/325 live Windows processes (99 unique exes)** every 3s, including AV (`avp.exe`), unlisted anti-cheat games, and missing companion exes. |
| `STATIC-003` | HIGH | **CLOSED** | — | `WindowProbe.foreground()`, `CaptureService.acquire()`, `CaptureService.is_current()`, and `app.py:foreground_session()` now gate strictly on `tracker.active_pids()` (Full-mode `created_at > 0.0` only); `CaptureScheduler` stays paused until a Full-mode game runs. Verified live with dummy `VALORANT-Win64-Shipping.exe` (`0` handle calls). |
| `STATIC-004` | MEDIUM | **OPEN** | **LOW** | `tests/test_packaging.py` passes (`2 passed in 0.25s`) and adds `psutil` ban, dynamic builtin checks, `*.import_module`, and `ctypes` DLL allowlist. However, 3 concrete AST bypasses remain: presence-only `self._open` mask check in `processes.py`, `ctypes` keyword/`windll`/imported-name bypasses, and `from importlib import import_module` bypass. |
| `STATIC-005` | LOW | **CLOSED** | — | `XboxDetector` (`gamehub/core/library/xbox.py`) contains zero `subprocess`/`powershell` references and enumerates `HKCU\...\AppModel\Repository\Packages` purely via read-only `winreg.KEY_READ`. Verified live (`state='complete', diagnostics=()`). |
| `STATIC-006` | LOW | **CLOSED** | — | `steamgriddb.py` disables all HTTP redirects via `_NoRedirectHandler` and enforces strict `https://` allowlisting (`www.steamgriddb.com`, `cdn.steamgriddb.com`, `cdn2.steamgriddb.com`) in `_validate_https_host()` and `_extract_grid_url()`. Verified live against 302 redirect and hostile hosts. |
| `STATIC-007` | INFO | **INFO** | INFO | `_psutil_windows.pyd` is gone from `dist/GameRewind/_internal/`. All other runtime dependencies (`windows-capture`, `PySide6`, `sounddevice`, `soundfile`, `Pillow`) remain clean. |

### Evidence for Closed Findings

- **`STATIC-001` (CLOSED):**
  - Source grep across `gamehub/` and `requirements.txt`: `0` hits for `psutil`. `packaging/gamerewind.spec:55` declares `excludes=['psutil']`.
  - Frozen bundle inspection (`dist/GameRewind/GameRewind.exe` & `_internal/`):
    ```text
    GameRewind.exe size=5,729,622
    UPX markers in GameRewind.exe: []
    psutil string in GameRewind.exe: False
    asInvoker in GameRewind.exe: True
    requireAdministrator in GameRewind.exe: False
    CArchive psutil entries: []
    PYZ psutil entries: []
    _internal psutil files: []
    _internal UPX binaries: []
    ```
  - `gamehub/core/sessions/processes.py:133-141,169-208` replaces `psutil.Process(pid).create_time()` with `kernel32.GetProcessTimes` on the single `PROCESS_QUERY_LIMITED_INFORMATION` (`0x1000`) handle.

- **`STATIC-003` (CLOSED):**
  - `gamehub/core/capture/windows.py:62-83`, `gamehub/core/capture/service.py:40-63`, `gamehub/app.py:762-769,950` enforce `tracker.active_pids()` before any `creation_time` / `OpenProcess` query and keep `CaptureScheduler` paused when zero Full-mode games are active.
  - Live dummy-process test (`VALORANT-Win64-Shipping.exe`, renamed `ping.exe`):
    ```text
    4a (0 active games, foreground=VALORANT pid=37552): acquire=None, foreground()=None, creation_time calls=[]
    4b (1 Full game pid=55555, foreground=VALORANT pid=37552): acquire=None, fg=None, is_current=False, creation_time calls=[]
    4c (Strict game pid=37552, created_at=0.0): active_pids=frozenset()
    ```

- **`STATIC-005` (CLOSED):**
  - AST/source scan of `gamehub/core/library/xbox.py`: `0` occurrences of `subprocess` or `powershell`.
  - `_installed_packages()` (`xbox.py:144-187`) uses read-only `winreg.OpenKey(..., winreg.KEY_READ)` on `HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages`.
  - Live execution: `XboxDetector().discover()` → `state=complete, games=0, diagnostics=()`.

- **`STATIC-006` (CLOSED):**
  - `gamehub/core/library/steamgriddb.py:17-64` implements `_NoRedirectHandler` (always raises `urllib.error.HTTPError` on redirect), `_validate_https_host()`, and `_ALLOWED_CDN_HOSTS = frozenset({"cdn.steamgriddb.com", "cdn2.steamgriddb.com"})`.
  - Live verification:
    ```text
    6b _NoRedirectHandler blocked 302 redirect: code=302, msg='Redirects are disabled for security.'
        _validate_https_host('http://cdn.steamgriddb.com/a.png') -> BLOCKED
        _validate_https_host('https://evil.example.com/a.png') -> BLOCKED
        _validate_https_host('https://cdn.steamgriddb.com.evil.com/a.png') -> BLOCKED
        _validate_https_host('https://cdn2.steamgriddb.com/a.png') -> ALLOWED
    ```

### Detailed Evidence & Required Fixes for Remaining Open Findings

#### `[STATIC-002]` OPEN (MEDIUM) — `ProcessProbe.snapshot()` bypasses `never_open` on `check_image` and still sprays `OpenProcess` on `package_id`-only Xbox targets

- **Locations:** `gamehub/core/sessions/processes.py:23-67,270-316`, `gamehub/core/library/xbox.py:244-270`
- **Empirical Reproduction:**
  1. **`check_image` bypasses `never_open` (`processes.py:313-316`):**
     ```python
     check_image = norm_name in basenames
     check_package = bool(packages) and (norm_name not in never_open)
     ```
     Passing `exe_path` targets whose basenames are explicitly in `DEFAULT_NEVER_OPEN_EXES` / `catalog.all_launcher_exe_names()` (including `vgc.exe`, which was removed from `protected_games.json`, and `GameLaunchHelper.exe`, an actual Xbox/GDK helper exe) STILL triggers `OpenProcess`:
     ```text
     3c (exe_path matching DEFAULT_NEVER_OPEN_EXES) inspected:
       [(1001, 'EpicGamesLauncher.exe', True, False),
        (1007, 'vgtray.exe', True, False),
        (1008, 'vgc.exe', True, False),
        (1021, 'GameLaunchHelper.exe', True, False)]
     ```
  2. **Residual `package_id`-only spray (`processes.py:314` + `xbox.py:253-270`):**
     When an Xbox game has both `exe_path` and `package_id`, `games_with_exe` cleanly skips `package_id` (`3a inspected: []`). However, if `xbox.py:254` (`contained_file(install_dir, raw_executable)`) returns `None` while `is_pc_game=True` (e.g., encrypted/inaccessible WindowsApps exe), `_with_package_family()` emits a `package_id`-only target, causing `ProcessProbe.snapshot()` to spray `OpenProcess(0x1000)` across **221/325 live Windows processes (99 unique exes)** every 3 seconds:
     ```text
     3b (Xbox package_id ONLY) inspected (8/21):
       EABackgroundService.exe, EpicWebHelper.exe, SteamService.exe, Agent.exe,
       BEService_x64.exe, GTA5.exe, RobloxPlayerBeta.exe, chrome.exe
     3b-live: Live OS procs=325, OpenProcess hits with 1 package_id-only target=221 (99 unique exes)
       Sample hit exes: ['agent_ovpnconnect.exe', ..., 'avp.exe', 'avpui.exe', ..., 'discord.exe', ...]
     ```
- **Recommended Fix:**
  1. Move `if norm_name in never_open: continue` directly after `if is_protected: continue` (`processes.py:311`) so `DEFAULT_NEVER_OPEN_EXES` and `never_open_exes` are **unconditionally** enforced for BOTH `check_image` and `check_package`.
  2. Add missing launcher/anti-cheat companions to `DEFAULT_NEVER_OPEN_EXES`: `eabackgroundservice.exe`, `ealaunchhelper.exe`, `epicwebhelper.exe`, `steamservice.exe`, `agent.exe`, `beservice_x64.exe`, `beclient_x64.exe`.
  3. Eliminate unbounded system-wide `package_id` spraying: record the declared `Executable/@Name` basename from `MicrosoftGame.config` (or require a basename shortlist) before calling `OpenProcess` + `GetPackageFamilyName`, rather than opening handles to arbitrary non-denylisted OS/AV/user processes.

#### `[STATIC-004]` OPEN (LOW) — `tests/test_packaging.py` AST security gate retains 3 concrete bypasses

- **Location:** `tests/test_packaging.py:77-150`
- **Evidence:**
  1. **Non-exhaustive `OpenProcess` mask check (`lines 127-130`):** `assert "self._open(_QUERY_LIMITED_INFORMATION, False, pid)" in proc_src` only checks that *one* safe call string exists in `processes.py`; adding a second `self._open(0x1F0FFF, False, pid)` call still passes.
  2. **`ctypes` DLL allowlist bypasses (`lines 104-115`):** Only checks `ast.Attribute` calls with positional `node.args`. Bypassed by `ctypes.WinDLL(name="ntdll")` (keyword arg), `from ctypes import WinDLL; WinDLL("ntdll")` (`ast.Name`), and `ctypes.windll.ntdll` / `ctypes.cdll.*` (attribute access).
  3. **Dynamic import bypass (`lines 101-120`):** `from importlib import import_module; import_module("socket")` uses `ast.Name("import_module")`, bypassing `isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"`. Also missing: `compile` in `FORBIDDEN_DYNAMIC_BUILTINS`, `DeviceIoControl` / `LookupPrivilegeValue` / `NtCreateThreadEx` / `CreateRemoteThreadEx` / `QWebSocket` / `QNetworkRequest` / `QSslSocket` / `QProcess` / `webbrowser` / `ssl`, `PySide6.QtNetwork` allowlist restriction (`QLocalServer`/`QLocalSocket` in `single_instance.py` only), and AST-based `upx=False` check on `gamerewind.spec`.
- **Recommended Fix:**
  - Parse `processes.py` with `ast` and assert **every** call to `self._open` or `OpenProcess` passes `ast.Name(id="_QUERY_LIMITED_INFORMATION")` as argument 0 (and verify `_QUERY_LIMITED_INFORMATION == 0x1000`).
  - Handle both `ast.Name` and `ast.Attribute` for `WinDLL`/`CDLL`/`OleDLL`/`LoadLibrary` (checking positional arg 0 OR `name=` keyword arg), ban `ctypes.windll`/`ctypes.cdll`/`ctypes.oledll` attribute access, and ban `import_module` on both `ast.Name` and `ast.Attribute` (plus `compile`).
  - Restrict `PySide6.QtNetwork` imports exclusively to `{QLocalServer, QLocalSocket}` in `gamehub/single_instance.py`, add missing forbidden symbols (`DeviceIoControl`, `LookupPrivilegeValue`, `NtCreateThreadEx`, `CreateRemoteThreadEx`, `QWebSocket`, `QNetworkRequest`, `QSslSocket`, `QProcess`, `webbrowser`, `ssl`), and AST-verify `upx=False` on every `EXE`/`COLLECT` call in `packaging/gamerewind.spec`.

---

### Round 2 Verdict (Focus a)

**FAIL — 2 open findings: `STATIC-002` (MEDIUM), `STATIC-004` (LOW).**
*(4 Round 1 findings CLOSED: `STATIC-001`, `STATIC-003`, `STATIC-005`, `STATIC-006`; 1 informational observation: `STATIC-007`.)*
