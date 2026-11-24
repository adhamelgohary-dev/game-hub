# Red-Team Report C4 — Packaging & Frozen Binary Hygiene (`v1.2.0-rc.3`)

**Role:** Independent Packaging & Frozen Binary Red-Team Auditor (C4 — fresh eyes)  
**Date:** 2026-11-24  
**Scope:** Freshly built `dist\GameRewind\` bundle after rc.3 size cuts, `packaging/gamerewind.spec`, `packaging/GameRewind.manifest`, `packaging/version_info.txt`, `packaging/THIRD_PARTY_NOTICES.txt`, `requirements.txt`, `.github/workflows/windows.yml`.

## Binary & Packaging Verification Evidence

1. **Bundle Size & File Count:**
   - Total files: **148** (85 PE `.exe`/`.dll`/`.pyd` files, down from 114 PE files in rc.2).
   - Unpacked `dist\GameRewind`: **123.23 MiB** (`129,215,049` bytes) — **59.2% smaller** than rc.2 (`302.13 MiB`), well below the `200 MiB` CI limit.
   - Portable `.zip`: **~50.96 MiB** — **58.0% smaller** than rc.2 (`121.32 MiB`), well below the `70 MiB` CI limit.
2. **Forbidden Binary Absence:**
   - `psutil` / `_psutil_windows.pyd`: **0 files** (100% absent; excluded in `gamerewind.spec`, `requirements.txt`, and CI gate).
   - `cv2` / `opencv*`: **0 files** (100% absent; replaced by minimal in-memory `ensure_cv2_shim()`, excluded in `gamerewind.spec`, uninstalled in CI).
   - `opengl32sw.dll`, `Qt6Qml*`, `Qt6Quick*`, `PIL/_avif*`: **0 files** (100% absent).
3. **Zero Stray Third-Party DLLs:**
   - Inspected all 85 PE files in `dist\GameRewind\`: every single DLL/PYD traces cleanly to CPython 3.12, PySide6 (`QtCore`, `QtGui`, `QtWidgets`, `QtNetwork`, `QtMultimedia` + FFmpeg + allowed plugins), Shiboken6, NumPy, Pillow, `windows_capture`, `sounddevice` (64-bit PortAudio only), `soundfile` (`libsndfile_x64.dll`), `cffi`, SQLite3, OpenSSL (`libcrypto-3.dll`/`libssl-3.dll` for Python stdlib), and VC++ runtime. Zero stray DLLs from unrelated apps (enforced by isolated `PATH` in `packaging/gamerewind.spec`).
4. **PE Manifest, Metadata & UPX:**
   - Embedded manifest verified: `asInvoker` (`uiAccess="false"`), **no** `requireAdministrator`, **no** `highestAvailable`.
   - PE `VERSIONINFO` verified: `FileVersion` and `OriginalFilename = GameRewind.exe` present.
   - Zero UPX markers (`UPX0` / `UPX!`) across all 85 PE binaries (`upx=False` enforced by AST test and CI).
5. **License Notices:**
   - 32 third-party notice files present under `_internal/third-party/` covering CPython, Qt (LGPL-3.0 / GPL-3.0), FFmpeg (LGPL-2.1), PortAudio, PyInstaller, Pillow, NumPy, `windows-capture`, `sounddevice`, `soundfile`, `vdf`, `cffi`, `pycparser`, `typing-extensions`; stale OpenCV references removed from `THIRD_PARTY_NOTICES.txt`.
6. **Clean Python-Free Windows Verification:**
   - Executed `dist\GameRewind\GameRewind.exe --smoke-test` with `PATH=C:\Windows\System32;C:\Windows`, `PYTHONHOME` and `PYTHONPATH` unset, `QT_QPA_PLATFORM=offscreen` -> **exit code 0**, passing full `_check_capture_runtime()` (including end-to-end `windows_capture.Frame` -> `numpy` -> Pillow WebP encode without OpenCV) and `_check_audio_runtime()` (PortAudio + libsndfile + QtMultimedia).
7. **CI Windows Defender & Size Gate:**
   - `.github/workflows/windows.yml` enforces unpacked `< 200 MiB`, zip `< 70 MiB`, forbidden-binary scan, PE manifest/UPX check, clean-PATH smoke test, custom-folder fresh/legacy-upgrade/folder-change/uninstall lifecycle, and `MpCmdRun.exe -Scan -ScanType 3` Defender verification before publishing release assets.

## Round 2 Verdict: **PASS — 0 Open Findings**
