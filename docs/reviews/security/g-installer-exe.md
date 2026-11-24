# Security Audit Report — Focus (g): Installer & Executable Security

- **Auditor:** Independent Red-Team Security Auditor (Focus g)
- **Date:** 2026-11-24
- **Target Bundle:** `e:\projects\game hub\dist\GameRewind\` (`GameRewind.exe`, SHA-256 `66706d476462b1275b49db5cd1395a86a677daa1eb075432a12bd7b7a3bc30f0`, 5,785,409 bytes; total bundle: 318 files, 316,932,815 bytes, 115 PE binaries)
- **Target Definitions:**
  - `packaging/gamerewind.spec`
  - `packaging/GameRewind.manifest`
  - `packaging/version_info.txt`
  - `packaging/installer.iss`
  - `.github/workflows/windows.yml`
  - Cross-checked: `tests/test_packaging.py`, `packaging/THIRD_PARTY_NOTICES.txt`, `docs/SIGNPATH-APPLICATION.md`, `gamehub/__init__.py`

---

## Executive Summary

Binary-level hygiene on the built `dist\GameRewind\GameRewind.exe` executable and its 115 bundled PE binaries is strong: the embedded PE manifest strictly specifies `asInvoker` (`uiAccess="false"`), PE `VERSIONINFO` fields are cleanly embedded, UPX is completely absent across all 115 PE files, all binaries are x64 with ASLR and DEP enabled (plus High-Entropy VA and Control Flow Guard on `GameRewind.exe`), no dev/test modules leaked into `PYZ.pyz`, and the frozen executable passes a clean Python-free `PATH` `--smoke-test` with exit code `0` and zero autostart or lingering processes.

However, the audit uncovered **6 open findings** (**4 HIGH, 1 MEDIUM, 1 LOW**) concentrated in `packaging/installer.iss` and `.github/workflows/windows.yml`:
1. **`G-01` (HIGH):** Unsafe custom destination path validation + destructive `[InstallDelete]` on `{app}\_internal` permits installation directly onto drive roots (`D:\`), `Desktop`, `%USERPROFILE%`, `%LOCALAPPDATA%\GameRewind`, or non-empty folders containing other apps' `_internal` directories.
2. **`G-02` (HIGH):** `RunQuietUninstallerForKey` blindly executes unvalidated HKCU `UninstallString` targets with `SW_HIDE`, breaks when `UninstallString` has arguments, discards `Exec` / `ResultCode` failures, and prematurely deletes `LegacyGameHubUninstallKey`.
3. **`G-03` (HIGH):** `IsDirWritable` enters an infinite loop on non-existent UNC paths (`\\server\share\...`) while triggering repeated SMB/NTLM connection attempts, and ignores `DeleteFile` cleanup failures.
4. **`G-04` (HIGH):** Release CI uses mutable action tags (`actions/upload-artifact@v4`, `signpath/github-action-submit-signing-request@v3`) inside a `contents: write` job holding `SIGNPATH_API_TOKEN`, and leaves `GameRewind.exe` unsigned in both the installer and portable zip despite `docs/SIGNPATH-APPLICATION.md` declaring it signed.
5. **`G-05` (MEDIUM):** Windows Defender scan (`MpCmdRun.exe`) could not run on this workstation (`WinDefend` stopped due to Kaspersky; `hr = 0x80004005`, exit code `2`), and release CI (`windows-2025`, where Defender is active) lacks both a Defender scan gate and compiled PE manifest/version/UPX verification.
6. **`G-06` (LOW):** Hardcoded version drift in `packaging/version_info.txt` and `packaging/GameRewind.manifest` (`1.2.0` vs `gamehub/__init__.py` `1.2.0-rc.1`) plus stale `"Game Hub"` legal text in `packaging/THIRD_PARTY_NOTICES.txt:35`.

---

## Verification Matrix (Required Checks)

| # | Check | Status | Evidence Summary |
| --- | --- | --- | --- |
| 1 | Embedded PE manifest (`dist\GameRewind\GameRewind.exe`) | **PASS** | Single `RT_MANIFEST` (Type 24, ID 1, 1478 B): strictly `level="asInvoker" uiAccess="false"`; zero `requireAdministrator` / `highestAvailable`. |
| 2 | Embedded PE `VERSIONINFO` (`dist\GameRewind\GameRewind.exe`) | **PASS** | Verified via Win32 `version.dll` & PowerShell `.VersionInfo`: `ProductName=GameRewind`, `OriginalFilename=GameRewind.exe`, `FileDescription`, `CompanyName`, `LegalCopyright`, `FileVersion=1.2.0.0`, `ProductVersion=1.2.0`. |
| 3 | No UPX packing + PE hardening (`dist\GameRewind\`) | **PASS** | `gamerewind.spec:81,91` has `upx=False`; 0 UPX sections/markers across all 115 PE binaries; 100% x64, 100% ASLR+DEP, 0 RWX sections, `GameRewind.exe` has CFG + High-Entropy VA. |
| 4 | Real Windows Defender scan (`MpCmdRun.exe`) | **BLOCKED (Host AV) / CI GAP** | Ran `MpCmdRun.exe -Scan -ScanType 3`: exit code `2`, `hr = 0x80004005` (`WARN: Product/Feature disabled` — `WinDefend` stopped because Kaspersky 21.26 is active AV). See `G-05`. |
| 5 | Python-free `PATH` frozen `--smoke-test` | **PASS** | `PATH=C:\WINDOWS\System32;C:\WINDOWS`, `PYTHONHOME`/`PYTHONPATH` unset, `QT_QPA_PLATFORM=offscreen`: exit code `0` (`8082 ms`), 0 lingering processes, 0 `Run` keys. |
| 6 | `packaging/installer.iss` & `.github/workflows/windows.yml` | **FAIL** | Open findings `G-01`, `G-02`, `G-03`, `G-04`, `G-05`, `G-06`. `[Registry]` autostart deletion (`installer.iss:48-51`) verified clean. |

---

## Raw Binary & Command Verification Evidence

### 1. Embedded PE Manifest Extraction (`dist\GameRewind\GameRewind.exe`)
Parsed directly from the PE `.rsrc` resource directory (Type `24` / `RT_MANIFEST`):
```text
Total RT_MANIFEST resources found: 1
--- Resource ID=1, Lang=0, Size=1478 bytes ---
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <assemblyIdentity version="1.2.0.0" processorArchitecture="amd64" name="GameRewind.Desktop" type="win32"/>
  <description>GameRewind — Offline Game Memory for Windows</description>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="asInvoker" uiAccess="false"/>
      </requestedPrivileges>
    </security>
  </trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application>
      <!-- Windows 10 and Windows 11 -->
      <supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"/>
    </application>
  </compatibility>
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true/pm</dpiAware>
      <dpiAwareness xmlns="urn:schemas-microsoft-com:SMI/2016/WindowsSettings">PerMonitorV2, PerMonitor</dpiAwareness>
      <longPathAware xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">true</longPathAware>
    </windowsSettings>
  </application>
  <dependency>
    <dependentAssembly>
      <assemblyIdentity type="win32" name="Microsoft.Windows.Common-Controls" version="6.0.0.0" processorArchitecture="*" publicKeyToken="6595b64144ccf1df" language="*"/>
    </dependentAssembly>
  </dependency>
</assembly>
```
*(PyInstaller automatically appends the standard `Microsoft.Windows.Common-Controls` 6.0.0.0 `<dependency>` while preserving `packaging/GameRewind.manifest` verbatim.)*

### 2. Embedded PE `VERSIONINFO` & Authenticode Status
Queried via both Win32 `version.dll` (`GetFileVersionInfoW` / `VerQueryValueW`) and PowerShell `(Get-Item ...).VersionInfo` + `Get-AuthenticodeSignature`:
```text
GetFileVersionInfoSizeW: 1684
GetFileVersionInfoW ok: 1
Translation: 040904b0
  CompanyName: 'GameRewind'
  FileDescription: 'GameRewind — Offline Game Memory for Windows'
  FileVersion: '1.2.0.0'
  InternalName: 'GameRewind'
  LegalCopyright: 'Copyright (c) 2026 GameRewind Contributors (MIT License)'
  OriginalFilename: 'GameRewind.exe'
  ProductName: 'GameRewind'
  ProductVersion: '1.2.0'

Status        : NotSigned
StatusMessage : The file E:\projects\game hub\dist\GameRewind\GameRewind.exe is not digitally signed.
```

### 3. PE Sections, Security Mitigations, UPX Scan & Embedded Archive Audit
```text
GameRewind.exe: machine=0x8664 format=PE32+ subsystem=2 (2=GUI,3=CUI) dll_chars=0xc160
  Authenticode Security Directory: rva=0 size=0
  HIGH_ENTROPY_VA (0x0020): True
  DYNAMIC_BASE/ASLR (0x0040): True
  FORCE_INTEGRITY (0x0080): False
  NX_COMPAT/DEP (0x0100): True
  GUARD_CF/CFG (0x4000): True
  TERMINAL_SERVER_AWARE (0x8000): True
  Sections:
    .text      vsize=  204800 rawsize=  204800 perms=R-X chars=0x60000020
    .rdata     vsize=   84308 rawsize=   84480 perms=R-- chars=0x40000040
    .data      vsize=   19192 rawsize=    3584 perms=RW- chars=0xc0000040
    .pdata     vsize=   10092 rawsize=   10240 perms=R-- chars=0x40000040
    .fptable   vsize=     256 rawsize=     512 perms=RW- chars=0xc0000040
    .rsrc      vsize=   31928 rawsize=   32256 perms=R-- chars=0x40000040
    .reloc     vsize=    1888 rawsize=    2048 perms=R-- chars=0x42000040
  UPX sections: [], UPX hdr marker: False, UPX! anywhere: False

Scanned 115 PE binaries (.exe/.dll/.pyd) under dist\GameRewind:
  Other .exe files: []
  UPX hits: []
  Non-x64 binaries: []
  Missing ASLR (DYNAMIC_BASE): []
  Missing DEP (NX_COMPAT): []
  RWX sections: []
```
- `CArchive` / `PYZ.pyz` audit: 12 CArchive entries, 565 PYZ modules (81 `gamehub.*` modules); zero `pytest`, `ruff`, `test_*`, `requests`, `httpx`, `aiohttp`, `urllib3`, or `pip` modules leaked.
- Bootloader PE imports: standard stock PyInstaller 6.22.3 (`USER32.dll`, `COMCTL32.dll`, `KERNEL32.dll` including `SetDllDirectoryW`, `ADVAPI32.dll`, `GDI32.dll`); zero injection, hooking, or `WriteProcessMemory`/`CreateRemoteThread` imports.

### 4. Windows Defender Scan Output (`MpCmdRun.exe`)
Command executed:
```powershell
& "$env:ProgramFiles\Windows Defender\MpCmdRun.exe" -Scan -ScanType 3 -File "e:\projects\game hub\dist\GameRewind"
```
Exact output and exit code:
```text
CmdTool: Failed with hr = 0x80004005. Check C:\Users\adham\AppData\Local\Temp\MpCmdRun.log for more information
EXIT_CODE=2
```
Also tested with latest platform binary (`C:\ProgramData\Microsoft\Windows Defender\Platform\4.18.26080.4-0\MpCmdRun.exe`) and `-DisableRemediation`: identical `hr = 0x80004005` (`EXIT_CODE=2`).
Root cause confirmed from `MpCmdRun.log`, `Get-Service`, and `root/SecurityCenter2`:
```text
WARN: Product/Feature disabled
MpCmdRun.exe: hr = 0x80004005.

Name       Status StartType
----       ------ ---------
WdNisSvc  Stopped    Manual
WinDefend Stopped    Manual

AntiVirusProduct:
  Kaspersky (productState=262144) — C:\Program Files (x86)\Kaspersky Lab\Kaspersky 21.26\wmiav.exe
  Windows Defender (productState=393472)
  Kaspersky Total Security (productState=266240)
```

### 5. Python-Free `PATH` Frozen `--smoke-test`
```text
SMOKE_TEST_EXIT_CODE=0
SMOKE_TEST_ELAPSED_MS=8082
PATH_USED=C:\WINDOWS\System32;C:\WINDOWS
HKCU_RUN_GAMEHUB=
HKCU_RUN_GAMEREWIND=
(Get-Process -Name GameRewind -> empty)
```

### 6. Autostart / `Run` Registry Verification (`packaging/installer.iss:48-51`)
```ini
[Registry]
; Remove any legacy autostart values on install/upgrade and uninstall; never create one.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "GameHub"; ValueType: none; Flags: deletevalue uninsdeletevalue dontcreatekey
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "GameRewind"; ValueType: none; Flags: deletevalue uninsdeletevalue dontcreatekey
```
Verified: never creates any `Run` value or key; deletes legacy `GameHub` and `GameRewind` values on both install/upgrade and uninstall.

---

## Detailed Findings

### [G-01] HIGH — Unsafe custom destination path validation + destructive `[InstallDelete]` on drive roots, Desktop, user-data directory, and non-empty folders

- **Locations:**
  - `packaging/installer.iss:16-17` (`DisableDirPage=no`, `UsePreviousAppDir=no`)
  - `packaging/installer.iss:42-43` (`[InstallDelete] Type: filesandordirs; Name: "{app}\_internal"`)
  - `packaging/installer.iss:90-116` (`NextButtonClick`)
- **Vulnerability & Concrete Reproduction:**
  1. `NextButtonClick` only checks `(TargetDir = '') or (Pos('..', TargetDir) > 0)` and `IsDirWritable(TargetDir)`. It does **not** reject:
     - **Writable drive roots** such as `D:\` or `E:\` (on Windows, standard users have write permission to secondary drives; `RemoveBackslashUnlessRoot('D:\')` returns `'D:\'`, `DirExists('D:\')` is `True`, and `IsDirWritable('D:\')` succeeds).
     - **User profile / Desktop / Documents / AppData roots**, and specifically **`%LOCALAPPDATA%\GameRewind`** (GameRewind's own user-data directory containing the SQLite DB, screenshots, and voice notes) or **`%LOCALAPPDATA%\GameHub`**. Worse, `packaging/installer.iss:108` actively instructs the user:
       > *"please choose a writable folder (for example in your user folder, Desktop, or another drive)."*
     - **Existing non-empty folders** belonging to other applications or user files.
     - **UNC network paths** (`\\server\share\GameRewind`) or drive-relative paths (`D:GameRewind`), despite line 100 claiming *"Please choose a valid local folder"*.
  2. **Data/Application Destruction via `[InstallDelete]`:** Because PyInstaller 6.x uses `_internal` as the standard runtime directory name for *all* PyInstaller onedir apps on Windows, installing GameRewind into any existing non-empty folder (e.g., `D:\Tools`, `Desktop`, or another PyInstaller app's directory) triggers `installer.iss:43`:
     ```ini
     Type: filesandordirs; Name: "{app}\_internal"
     ```
     which **unconditionally recursively deletes `{app}\_internal`** before file copy, permanently destroying another application's runtime or any user directory named `_internal` without warning.
  3. **Silent-mode UX / false-positive defects:**
     - `Pos('..', TargetDir) > 0` (`installer.iss:98`) rejects legitimate directory names containing consecutive dots (e.g., `D:\Games..2026\GameRewind`).
     - `MsgBox(...)` at lines 100 and 106 is not guarded by `if not WizardSilent then`, which can block automated `/SILENT` or `/VERYSILENT` deployments invoked without `/SUPPRESSMSGBOXES` when `/DIR=` is invalid.
- **Recommended Fix:**
  1. Add a dedicated `ValidateInstallDir(const RawDir: string; var ErrMsg: string): Boolean` helper called in `NextButtonClick(wpSelectDir)` (with `if not WizardSilent then MsgBox(...)`) **and** as a defense-in-depth check in `PrepareToInstall`:
     - Require an absolute local drive path with at least one subdirectory component: `Length(CleanDir) >= 4`, `CleanDir[1]` in `['A'..'Z','a'..'z']`, `CleanDir[2] = ':'`, `CleanDir[3] = '\'`, and reject bare roots (`Length(RemoveBackslashUnlessRoot(CleanDir)) <= 3`), drive-relative paths, and UNC paths (`\\...`).
     - Reject path traversal segments (`\..\`, trailing `\..`, leading `..\`) instead of raw `Pos('..', ...)`.
     - Reject exact matches (case-insensitive) to `{userprofile}`, `{userdesktop}`, `{userdocs}`, `{userappdata}`, `{localappdata}`, `{localappdata}\GameRewind`, `{localappdata}\GameHub`, `{win}`, `{sys}`, `{autopf}`, `{autopf32}`, and `{temp}`.
     - If `DirExists(CleanDir)` and the directory is non-empty and does **not** already contain `GameRewind.exe`, block installation and instruct the user to pick an empty folder or append `\GameRewind` (preventing `[InstallDelete]` from ever touching an unrelated `_internal` folder).
  2. Update the message at `packaging/installer.iss:108` to give safe subfolder examples (e.g., `C:\Users\<you>\Desktop\GameRewind` or `D:\Games\GameRewind`) rather than `"your user folder, Desktop, or another drive"`.

---

### [G-02] HIGH — Unvalidated HKCU `UninstallString` execution (`SW_HIDE`), broken argument parsing, ignored exit codes, and premature legacy key deletion

- **Location:** `packaging/installer.iss:118-168` (`RunQuietUninstallerForKey`, `PrepareToInstall`)
- **Vulnerability & Concrete Reproduction:**
  ```pascal
  procedure RunQuietUninstallerForKey(const RegKey: string);
  var
    UninstallExe: string;
    ResultCode: Integer;
  begin
    if RegQueryStringValue(HKCU, RegKey, 'UninstallString', UninstallExe) then
    begin
      UninstallExe := RemoveQuotes(Trim(UninstallExe));
      if (UninstallExe <> '') and FileExists(UninstallExe) then
      begin
        Exec(
          UninstallExe,
          '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART',
          '',
          SW_HIDE,
          ewWaitUntilTerminated,
          ResultCode
        );
      end;
    end;
  end;
  ```
  1. **Unvalidated HKCU binary execution (Signed-Installer Proxy Execution):** On every install/upgrade — even on systems where legacy `Game Hub` was never installed — `PrepareToInstall` (`installer.iss:150`) reads `HKCU\...\Uninstall\{BCE7FA2A-7A55-487B-9BC4-2EA83958BF9A}_is1\UninstallString` and executes whatever file path is stored there silently (`SW_HIDE`). It does **not** verify:
     - that the executable filename matches Inno Setup's uninstaller pattern (`unins*.exe`),
     - that it is a local path (not a UNC path like `\\attacker\share\payload.exe`),
     - that its parent directory matches the key's `InstallLocation` (and is not e.g. `C:\Windows\System32\...` or an arbitrary attacker-dropped binary).
     Once `GameRewind-Setup-vX.Y.Z.exe` is Authenticode-signed via SignPath, any unprivileged script planting that HKCU value can abuse the signed installer as a hidden child-process launcher — and if a user manually launches Setup via *"Run as administrator"*, Setup executes that unprivileged HKCU-specified binary with elevated privileges.
  2. **Broken parsing when `UninstallString` contains arguments:** Inno Setup's `RemoveQuotes(S)` only strips quotes if *both* the first and last characters of `S` are `"`. If `UninstallString` contains any trailing switch (e.g., `"C:\Users\Alice\AppData\Local\Programs\Game Hub\unins000.exe" /SILENT`), `RemoveQuotes` leaves the quotes intact, `FileExists(UninstallExe)` returns `False`, and uninstall is silently skipped.
  3. **Ignored `Exec` failure / `ResultCode` & orphaned binaries:**
     - Both the `Exec(...)` Boolean result and `ResultCode` are discarded.
     - Lines 150-152 unconditionally run `RegDeleteKeyIncludingSubkeys(HKCU, LegacyGameHubUninstallKey)` even if `RunQuietUninstallerForKey` failed (e.g., because `GameHub.exe` was still running or `UninstallString` failed to parse), leaving orphaned `Game Hub` binaries on disk with no Uninstall entry in Windows Settings -> Apps.
     - During a folder-change upgrade (`installer.iss:161-167`), Inno Setup's `CloseApplications=yes` only inspects files in `{app}` (`NewInstallDir`), **not** `PrevInstallDir`. If `GameRewind.exe` is still running from `PrevInstallDir`, `unins000.exe` fails to remove the running binary and exits non-zero, yet `PrepareToInstall` proceeds anyway, leaving two side-by-side GameRewind installations.
- **Recommended Fix:**
  1. Parse the executable token properly from `UninstallString` (if starting with `"`, extract up to the matching closing `"`; otherwise extract up to `.exe` / end of string).
  2. Strictly validate the resolved uninstaller path before calling `Exec`:
     - Must be a local drive path (`[A-Za-z]:\...`, never UNC `\\...`).
     - Must match `unins*.exe` (e.g., `LowerCase(ExtractFileName(UninstallExe))` starts with `'unins'` and ends with `'.exe'`).
     - Must reside inside the key's `InstallLocation` (`CompareText(RemoveBackslashUnlessRoot(ExtractFileDir(UninstallExe)), RemoveBackslashUnlessRoot(InstallLoc)) = 0`).
  3. Return a `Boolean` success status from `RunQuietUninstallerForKey` checking `Exec(...) and (ResultCode = 0)`.
     - For `LegacyGameHubUninstallKey`: only delete the key manually when no valid uninstaller existed (stale stub) or after uninstall succeeds; if uninstall ran and failed (e.g., `GameHub.exe` still running), return a clear error string from `PrepareToInstall` telling the user to close Game Hub first.
     - For `CurrentGameRewindUninstallKey` folder-change upgrades: if `RunQuietUninstallerForKey` fails (e.g., old `GameRewind.exe` is running in `PrevInstallDir`), abort `PrepareToInstall` with a clear message instructing the user to close GameRewind before moving folders.

---

### [G-03] HIGH — Infinite loop & repeated SMB/NTLM connection leak in `IsDirWritable` on non-existent UNC paths, plus probe cleanup blind spot

- **Location:** `packaging/installer.iss:66-88` (`IsDirWritable`)
- **Vulnerability & Concrete Reproduction:**
  ```pascal
  function IsDirWritable(DirPath: string): Boolean;
  var
    ProbeDir: string;
    ProbeFile: string;
  begin
    Result := False;
    ProbeDir := RemoveBackslashUnlessRoot(Trim(DirPath));
    if ProbeDir = '' then
      Exit;

    while (not DirExists(ProbeDir)) and (Length(ProbeDir) > 3) do
      ProbeDir := RemoveBackslashUnlessRoot(ExtractFileDir(ProbeDir));
  ```
  1. **Infinite loop + SMB/NTLM coercion:** Because `NextButtonClick` does not block UNC paths, entering or passing `/DIR="\\nonexistent-or-attacker\share\GameRewind"` causes `ProbeDir` to walk up to `'\\nonexistent-or-attacker\share'` (length `> 3`). In Delphi/Inno Setup Pascal Script, `ExtractFileDir('\\server\share')` returns `'\\server\share'` unchanged. Because `DirExists` returns `False` and `Length(ProbeDir) > 3` remains `True`, the `while` loop **never terminates**, freezing the installer permanently while continuously issuing SMB `DirExists` probes to the remote host (which on Windows automatically sends NTLMv2 authentication material over SMB port 445 if pointed at an attacker-controlled host).
  2. **Probe file collision & stray file leak:** `ProbeFile` (`installer.iss:82-87`) uses a 1-second timestamp with `SaveStringToFile(..., False)` (overwrite mode) and ignores the return value of `DeleteFile(ProbeFile)`. On a directory with create-only / deny-delete ACLs, `IsDirWritable` returns `True` while leaving a stray `gamerewind-write-probe-*.tmp` file behind.
- **Recommended Fix:**
  1. Reject UNC paths before calling `IsDirWritable` (per `G-01`) **and** add a loop-progress termination guard inside `IsDirWritable`:
     ```pascal
     ParentDir := RemoveBackslashUnlessRoot(ExtractFileDir(ProbeDir));
     if (ParentDir = '') or (CompareText(ParentDir, ProbeDir) = 0) then
       Break;
     ProbeDir := ParentDir;
     ```
  2. Verify `DeleteFile(ProbeFile)` returns `True` before setting `Result := True`, and avoid overwriting any existing file (`if FileExists(ProbeFile) then ...`).

---

### [G-04] HIGH — CI release supply-chain gaps: unpinned mutable GitHub Actions tags (`@v3`/`@v4`) with `SIGNPATH_API_TOKEN` + `contents: write`, and `GameRewind.exe` left unsigned

- **Locations:**
  - `.github/workflows/windows.yml:43-44` (`permissions: contents: write`)
  - `.github/workflows/windows.yml:55-78` (builds portable zip & Inno installer with unsigned `GameRewind.exe`)
  - `.github/workflows/windows.yml:190-217` (`actions/upload-artifact@v4`, `signpath/github-action-submit-signing-request@v3`)
  - `docs/SIGNPATH-APPLICATION.md:27`
- **Vulnerability & Evidence:**
  1. **Unpinned mutable third-party / GitHub Action tags on the signing & release job:** While `actions/checkout` and `actions/setup-python` are properly pinned to full 40-character commit SHAs (`.github/workflows/windows.yml:19,22,46,49`), lines 193 and 201 use mutable major version tags:
     - `uses: actions/upload-artifact@v4` (line 193)
     - `uses: signpath/github-action-submit-signing-request@v3` (line 201)
     The `signpath` step runs inside the `release` job with `permissions: contents: write` and receives `${{ secrets.SIGNPATH_API_TOKEN }}` and `${{ secrets.SIGNPATH_ORG_ID }}`. If either upstream tag is mutated or hijacked, an attacker gains direct access to the SignPath API token and release publishing credentials.
  2. **Primary application binary `GameRewind.exe` is never signed:** `docs/SIGNPATH-APPLICATION.md:27` states:
     > *"Artifacts to sign: `GameRewind.exe` (inside portable zip) and `GameRewind-Setup-vX.Y.Z.exe` (Inno Setup installer)"*
     However, `.github/workflows/windows.yml:55-78` zips `dist/GameRewind` and compiles `GameRewind-Setup-$tag.exe` **before** any SignPath step runs, and lines 190-217 **only** upload and sign `dist/GameRewind-Setup-$tag.exe`. Even after `SIGNPATH_ENABLED=true` is enabled:
     - Installed `{app}\GameRewind.exe` (and `unins000.exe`) will remain **unsigned**, continuing to trigger SmartScreen / AV heuristic warnings on launch.
     - `GameRewind-Portable-$tag.zip` will ship an **unsigned** `GameRewind.exe`.
- **Recommended Fix:**
  1. Pin `actions/upload-artifact` and `signpath/github-action-submit-signing-request` to full 40-character immutable commit SHAs (with `# v4.x.y` / `# v3.x.y` version comments).
  2. Restructure the release workflow when `vars.SIGNPATH_ENABLED == 'true'` so `dist/GameRewind/GameRewind.exe` is signed **first** (right after PyInstaller builds it), **then** `GameRewind-Portable-$tag.zip` and `GameRewind-Setup-$tag.exe` are built using the signed `GameRewind.exe`, and **then** `GameRewind-Setup-$tag.exe` is signed via SignPath (optionally using Inno Setup `SignTool` or signing both `GameRewind.exe` and `GameRewind-Setup-$tag.exe`), before generating `SHA256SUMS.txt`.

---

### [G-05] MEDIUM — Missing Windows Defender scan and compiled PE binary verification in release CI

- **Locations:**
  - `.github/workflows/windows.yml:79-188`
  - `tests/test_packaging.py:73-79`
- **Issue & Evidence:**
  - On this local workstation, Windows Defender is disabled by Kaspersky (`WinDefend` stopped; `MpCmdRun.exe -Scan -ScanType 3` fails with `hr = 0x80004005`, exit code `2`). As a result, `dist\GameRewind` has **not** been scanned by Windows Defender locally.
  - The GitHub Actions `windows-2025` runner *does* have Windows Defender enabled, yet `.github/workflows/windows.yml` never invokes `MpCmdRun.exe -Scan -ScanType 3` against `dist/GameRewind` or `dist/GameRewind-Setup-$tag.exe` before publishing a release.
  - Additionally, `tests/test_packaging.py:73-79` only asserts text substrings in source files (`packaging/GameRewind.manifest`, `packaging/gamerewind.spec`), never verifying the **compiled PE binary** (`dist/GameRewind/GameRewind.exe` or `GameRewind-Setup-*.exe`) in CI for embedded `RT_MANIFEST` (`asInvoker`, no `requireAdministrator`/`highestAvailable`), embedded `VERSIONINFO`, zero UPX markers, or installer rejection of unsafe paths (`D:\`, UNC paths, non-empty directories).
- **Recommended Fix:**
  1. Add a release CI step in `.github/workflows/windows.yml` running:
     ```powershell
     & "$env:ProgramFiles\Windows Defender\MpCmdRun.exe" -Scan -ScanType 3 -File (Resolve-Path 'dist/GameRewind').Path
     if ($LASTEXITCODE -ne 0) { throw "Windows Defender flagged dist/GameRewind ($LASTEXITCODE)." }
     & "$env:ProgramFiles\Windows Defender\MpCmdRun.exe" -Scan -ScanType 3 -File (Resolve-Path "dist/GameRewind-Setup-$tag.exe").Path
     if ($LASTEXITCODE -ne 0) { throw "Windows Defender flagged installer ($LASTEXITCODE)." }
     ```
  2. Add a binary-inspection step in `.github/workflows/windows.yml` verifying the compiled `GameRewind.exe` and `GameRewind-Setup-$tag.exe` embedded `RT_MANIFEST` (`asInvoker`), `VERSIONINFO`, and zero UPX sections, plus negative installer tests verifying `/VERYSILENT /DIR="C:\"` and `/VERYSILENT /DIR="\\invalid\share\GameRewind"` fail cleanly and quickly.

---

### [G-06] LOW — Hardcoded PE version metadata drift & stale `"Game Hub"` branding in shipped third-party notice

- **Locations:**
  - `gamehub/__init__.py:3` (`__version__ = "1.2.0-rc.1"`)
  - `packaging/version_info.txt:3-4,20,25` (hardcoded `1.2.0.0` / `1.2.0`)
  - `packaging/GameRewind.manifest:4` (hardcoded `version="1.2.0.0"`)
  - `packaging/THIRD_PARTY_NOTICES.txt:35` (shipped in `dist\GameRewind\_internal\third-party\THIRD_PARTY_NOTICES.txt`)
- **Issue & Evidence:**
  1. `packaging/version_info.txt` and `packaging/GameRewind.manifest` hardcode `1.2.0` / `1.2.0.0`, while `gamehub/__init__.py` is `1.2.0-rc.1` and `.github/workflows/windows.yml:75-77` passes `/DAppVersion=$version` dynamically only to Inno Setup. On future patch/minor releases (e.g. `v1.2.1`, `v1.3.0`), `GameRewind.exe`'s PE `FileVersion`, `ProductVersion`, and assembly manifest version will silently lag behind unless manually updated, and `tests/test_packaging.py` does not assert they match `__version__`.
  2. `packaging/THIRD_PARTY_NOTICES.txt:35` (linked directly from the Start Menu shortcut `Third-party notices`) still reads:
     > *"The Game Hub terms allow reverse engineering for debugging such modifications."*
     instead of `"GameRewind"`.
- **Recommended Fix:**
  1. Add a unit test in `tests/test_packaging.py` asserting that the `X.Y.Z` base of `gamehub.__version__` matches `packaging/version_info.txt` (`filevers`, `prodvers`, `FileVersion`, `ProductVersion`), `packaging/GameRewind.manifest` (`version=`), and `packaging/installer.iss` (`#define AppVersion`), or generate `version_info.txt` / manifest version from `gamehub.__version__` at build time.
  2. Update `"Game Hub"` to `"GameRewind"` on `packaging/THIRD_PARTY_NOTICES.txt:35`.

---

## Informational Observations (INFO)

- **INFO-1 (Expected Unsigned Binary Pre-SignPath):** `dist\GameRewind\GameRewind.exe` currently has `Status: NotSigned` (PE Authenticode Security Directory `0/0`). This is expected prior to SignPath Foundation approval (`docs/SIGNPATH-APPLICATION.md`).
- **INFO-2 (Pip Hash Pinning):** `requirements.txt` and `requirements-dev.txt` pin exact package versions (good), but `.github/workflows/windows.yml:27,54` installs without `--require-hashes`. Adding pip hash locking (`pip-compile --generate-hashes`) would further harden release supply-chain integrity.
- **INFO-3 (CPython License Fetch in CI):** `.github/workflows/windows.yml:60-64` downloads `https://raw.githubusercontent.com/python/cpython/v$($python[1])/LICENSE` without integrity check when `LICENSE.txt` is absent from `sys.base_prefix`. Only non-executable text is fetched, so risk is minimal, though bundling `packaging/licenses/CPython.txt` in-repo would make release builds fully offline/deterministic.
- **INFO-4 (Bundle Footprint):** `dist\GameRewind` is 316.9 MB across 318 files due to transitive `PySide6-Addons` (`Qt6Multimedia`, `Qt6Quick`, `Qt6Qml`, `Qt6VirtualKeyboard`, FFmpeg) and `opencv-python` (`opencv_videoio_ffmpeg510_64.dll`). No unexpected dev binaries or 32-bit DLLs were found (`_keep_portaudio` cleanly excludes 32-bit PortAudio).

---

## Verdict

**FAIL** (6 open findings: `G-01` [HIGH], `G-02` [HIGH], `G-03` [HIGH], `G-04` [HIGH], `G-05` [MEDIUM], `G-06` [LOW])


---

## Round 2 Re-Audit Verification

- **Re-audit date:** 2026-11-24
- **Auditor:** Independent Red-Team Security Auditor (Focus `f` & `g`)
- **Rebuilt Target Bundle:** `e:\projects\game hub\dist\GameRewind\GameRewind.exe` (SHA-256 `5ffc08677b6c61992d4029d3a7bfabed27ccedc412c223369ee5e22ff33b34b1`, 5,729,622 bytes, rebuilt `2026-11-24 20:00:26`; 316 files, 114 PE binaries; identical SHA-256 verified inside `dist\GameRewind-Portable-v1.2.0-rc.2.zip`).
- **Target Definitions Reviewed:** `packaging/installer.iss`, `.github/workflows/windows.yml`, `packaging/THIRD_PARTY_NOTICES.txt`, `packaging/gamerewind.spec`, `packaging/GameRewind.manifest`, `packaging/version_info.txt`, `tests/test_packaging.py`.

### Rebuilt Binary & Artifact Verification Summary

```text
EXE SHA256: 5ffc08677b6c61992d4029d3a7bfabed27ccedc412c223369ee5e22ff33b34b1 (matches GameRewind-Portable-v1.2.0-rc.2.zip)
RT_MANIFEST (ID=1, Type=24, 1478 B): level="asInvoker" uiAccess="false" (True); requireAdministrator (False); highestAvailable (False)
VERSIONINFO: CompanyName='GameRewind', FileDescription='GameRewind — Offline Game Memory for Windows',
             FileVersion='1.2.0.0', InternalName='GameRewind', OriginalFilename='GameRewind.exe',
             ProductName='GameRewind', ProductVersion='1.2.0', LegalCopyright intact
PE scan (114 binaries): UPX hits=[], non_x64=[], no_aslr=[], no_dep=[], rwx_hits=[]
psutil audit: 0 files in dist\GameRewind, 0 in CArchive (12 entries), 0 in PYZ.pyz (561 modules), 0 in portable zip
THIRD_PARTY_NOTICES.txt (source, dist, portable zip): 'Game Hub' absent, 'psutil' absent
Python-free PATH frozen --smoke-test: exit code 0 (1063 ms)
pytest tests/test_packaging.py: 2 passed
```

### Per-Finding Verification Status

| ID | Round 1 Severity | Round 2 Status | Residual Severity | Verification Evidence & Remaining Gaps |
| --- | --- | --- | --- | --- |
| **G-01** | HIGH | **OPEN** | **MEDIUM** | Interactive wizard checks in `NextButtonClick(wpSelectDir)` (`packaging/installer.iss:161-209`) now properly reject UNC paths, bare drive roots (`C:\`, `D:\`), `%USERPROFILE%`, Desktop directly (`{userdesktop}`), `{localappdata}`, `{localappdata}\GameRewind` (and subdirs), `{localappdata}\GameHub` (and subdirs), and non-empty unrelated folders. **HOWEVER, two residual bypasses remain:** (1) **Silent-mode complete bypass:** In Inno Setup, `NextButtonClick` is **never called** during `/SILENT` or `/VERYSILENT` installs, and `PrepareToInstall` (`packaging/installer.iss:291-327`) performs **zero** validation on `ExpandConstant('{app}')`. Running `GameRewind-Setup.exe /VERYSILENT /DIR="D:\"` or `/DIR="D:\OtherPyInstallerApp"` or `/DIR="%LOCALAPPDATA%\GameRewind"` or `/DIR="\\attacker\share\GameRewind"` completely bypasses all destination validation and permits `[InstallDelete] {app}\_internal` to delete unrelated files. (2) **Forward-slash normalization bypass:** `IsLocalDrivePath` (`installer.iss:66-73`) does not reject `/` after index 3 (e.g., `C:\Users\<user>/AppData/Local/GameRewind`), which evades `CompareText` in `IsForbiddenDestination`. **Required Fix:** Extract a shared `ValidateInstallDir(const RawDir: string; var ErrMsg: string): Boolean` (also rejecting `Pos('/', DirPath) > 0` in `IsLocalDrivePath`), call it in `NextButtonClick(wpSelectDir)` (with `if not WizardSilent then MsgBox(...)`), **and** call it at the top of `PrepareToInstall` returning `ErrMsg` on failure. |
| **G-02** | HIGH | **OPEN** | **MEDIUM** | `RunValidatedQuietUninstaller` (`packaging/installer.iss:237-289`) now extracts quoted executable paths (`ExtractUninstallExePath`), checks `unins*.exe`, checks `Exec(...)` + `ResultCode = 0`, avoids deleting `LegacyGameHubUninstallKey` when uninstall fails, and aborts `PrepareToInstall` cleanly when old `GameRewind` fails to uninstall on folder move (`installer.iss:320-324`). **HOWEVER, two concrete security bugs remain:** (1) **Pre-validation UNC SMB/NTLM leak (`installer.iss:250` vs `254`):** Line 250 invokes `FileExists(UninstallExe)` **before** line 254 checks `IsLocalDrivePath(UninstallExe)`. A tampered HKCU `UninstallString = "\\attacker\share\unins000.exe"` triggers an outbound SMB/NTLM connection during `FileExists` before local-drive rejection runs. (2) **Bare-root / subdirectory `InstallLocation` bypass (`installer.iss:271-276`):** `InstallLoc` is never checked against bare drive roots (`C:\`) or forbidden destinations, and line 272 uses a loose prefix check (`Pos(Lowercase(InstallLoc), Lowercase(UninstallExe)) <> 1`) instead of exact parent directory equality. Setting HKCU `InstallLocation = "C:\"` and `UninstallString = "C:\Users\Public\evil\unins000.exe"` passes every check and silently executes an attacker-planted binary with `SW_HIDE`. **Required Fix:** Move `(not IsLocalDrivePath(UninstallExe)) or (Pos('..', UninstallExe) > 0)` **before** `FileExists(UninstallExe)`, validate `not IsForbiddenDestination(InstallLoc)`, and enforce direct parent directory equality (`CompareText(RemoveBackslashUnlessRoot(ExtractFileDir(UninstallExe)), RemoveBackslashUnlessRoot(InstallLoc)) = 0`). |
| **G-03** | HIGH | **CLOSED** | — | `IsDirWritable` (`packaging/installer.iss:131-159`) immediately exits on non-local-drive paths (`IsLocalDrivePath`), guards the parent-walk loop against non-progress (`(ParentDir = '') or (CompareText(ParentDir, ProbeDir) = 0)` -> `Break`), and requires `DeleteFile(ProbeFile)` to return `True` before returning `True`. |
| **G-04** | HIGH | **CLOSED** | — | All 6 `uses:` entries in `.github/workflows/windows.yml` (lines 19, 22, 46, 49, 230, 238) are now pinned to full 40-character immutable commit SHAs (`actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02`, `signpath/github-action-submit-signing-request@a2c5b60d9c75f073142b653c354b632eedce097b`). Line 226 explicitly notes extending SignPath signing to `GameRewind.exe` (before Inno Setup) and `GameRewind-Setup` once SignPath policy is live (`SIGNPATH_ENABLED` is currently disabled). *(INFO reminder: move `GameRewind.exe` signing ahead of zip/Inno packaging before setting `SIGNPATH_ENABLED=true`.)* |
| **G-05** | MEDIUM | **OPEN** | **MEDIUM** | `.github/workflows/windows.yml:189-223` added PE `asInvoker`/`VERSIONINFO`/zero-UPX checks and `MpCmdRun.exe -Scan -ScanType 3` Defender scanning for both `dist/GameRewind` and `dist/GameRewind-Setup-$tag.exe`. **HOWEVER, `.github/workflows/windows.yml:205` omits `if ($LASTEXITCODE -ne 0) { throw ... }` after `python -c "..."`!** On GitHub Actions `windows-2025` runners (default shell `pwsh`, where `$PSNativeCommandUseErrorActionPreference` defaults to `$false`), a non-zero exit code from `python -c` does **not** terminate the step; execution proceeds to the Defender block (lines 206-223), overwriting `$LASTEXITCODE` with `0` (or issuing `Write-Warning`) and silently swallowing any PE manifest, `VERSIONINFO`, or UPX assertion failure! Additionally, line 197 does not assert `b'highestAvailable' not in exe_bytes`. **Required Fix:** Immediately after line 205 add `if ($LASTEXITCODE -ne 0) { throw "PE security verification failed ($LASTEXITCODE)." }` and add `assert b'highestAvailable' not in exe_bytes` at line 197. |
| **G-06** | LOW | **CLOSED** | — | `packaging/THIRD_PARTY_NOTICES.txt:35` updated from `"Game Hub"` to `"GameRewind"` (verified in source, rebuilt `dist\GameRewind`, portable zip, and `tests/test_packaging.py:192`); zero `psutil` mentions; version metadata (`1.2.0` / `1.2.0.0`) aligned across `packaging/version_info.txt`, `packaging/GameRewind.manifest`, and `packaging/installer.iss`. *(INFO reminder: add a version-base parity check against `gamehub.__version__` in `tests/test_packaging.py` for future releases.)* |

### Round 2 Verdict (Focus g)

**FAIL** (3 open findings: `G-01` [MEDIUM], `G-02` [MEDIUM], `G-05` [MEDIUM]; 3 closed: `G-03`, `G-04`, `G-06`).
