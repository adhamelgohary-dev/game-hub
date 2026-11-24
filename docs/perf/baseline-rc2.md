# GameRewind v1.2.0-rc.2 — Performance & Size Baseline

**Recorded:** 2026-11-24  
**Baseline commit / tag:** `v1.2.0-rc.2` (`fb46a95` — untouched code before rc.3 size/speed changes)  
**Target binary:** `dist\GameRewind\GameRewind.exe` (PyInstaller 6.22.3 `--onedir`, Python 3.12.0 x64, Windows 11)  
**Benchmark script:** [benchmark_rc.py](../../scripts/bench/benchmark_rc.py)  
**Raw JSON data:** [baseline-rc2-raw.json](baseline-rc2-raw.json)

---

## 1. Size Metrics (Before Any Cleanup or Trimming)

### Repository & Local Workspace
- **GitHub repository (`adhamelgohary-dev/game-rewind`):** `3,951 KB` (`3.86 MiB`) — verified `PUBLIC`, **0** `.exe` / `.zip` / `.dll` / `.pyd` / `dist/` / `build/` / `.venv/` blobs in entire git history (`git count-objects -vH`: `4.62 MiB`, largest historical blob `150.9 KB`).
- **Local working folder total before cleanup:** **`2,964.2 MB` (`~2.89 GB`)**
  - `dist\`: `2,074.15 MB` (accumulated historical folders `GameHub`, `GameRewind`, `m4`, `m3`, `verified`, `Portable Smoke`, `debug`, `m2`, `m1`, `clean`, plus old zip archives)
  - `.venv\`: `659.49 MB`
  - `.pytest_cache\`: `121.83 MB`
  - `build\`: `98.45 MB`
  - `.git\`: `4.70 MB`
  - source / docs / tests / packaging: `~5.5 MB`

### Shipped Application Sizes (`v1.2.0-rc.2`)
| Artifact | Size (MiB) | Size (MB, decimal) | Exact Bytes |
| --- | --- | --- | --- |
| Installed folder (`dist\GameRewind`) | **302.13 MiB** | 316.81 MB | `316,808,549` |
| Portable `.zip` (GitHub Release `v1.2.0-rc.2`) | **121.32 MiB** | 127.21 MB | `127,212,822` |
| Setup `.exe` (GitHub Release `v1.2.0-rc.2`) | **81.24 MiB** | 85.19 MB | `85,188,316` |

### Top Contributors Inside `dist\GameRewind` (302.13 MiB)
| Component | Unpacked Size | Notes |
| --- | --- | --- |
| `cv2\cv2.pyd` + `opencv_videoio_ffmpeg510_64.dll` | **125.55 MiB** | Pulled in solely by top-level `import cv2` in `windows_capture/__init__.py` (unused by GameRewind) |
| `PySide6\opengl32sw.dll` | **19.68 MiB** | Software OpenGL fallback (unused 2D QWidgets app) |
| `numpy.libs\libscipy_openblas64_*.dll` + `numpy` | **~24 MiB** | Required by `windows_capture` (`numpy.frombuffer`) and `soundfile` |
| `PySide6\avcodec/avformat/swscale/avutil/swresample` + `ffmpegmediaplugin.dll` | **19.46 MiB** | Used by `QtMultimedia` for Ogg Vorbis voice note playback |
| `PySide6\Qt6Quick/Qml/OpenGL/VirtualKeyboard/QmlModels/MultimediaWidgets` | **15.28 MiB** | Unused QML/Quick/VirtualKeyboard chain |
| `PIL\_avif.cp312-win_amd64.pyd` | **7.53 MiB** | Unused AVIF codec (GameRewind uses PNG/JPEG/WebP) |
| `PySide6\translations\` (128 files) | **7.08 MiB** | Only English/Arabic needed |
| Unused PySide6 plugins (`qdirect2d`, `qtiff`, `qtvirtualkeyboardplugin`, etc.) | **~2.7 MiB** | Unused platform/image/input plugins |

---

## 2. Startup Time (Frozen `GameRewind.exe`, Median of 10 Runs)

Measured from `CreateProcess` (`Popen`) to visible `"GameRewind"` top-level window on the real 32-game library:

| Scenario (10 Runs) | Run 1 | Min | Median | Avg | P95 | Max |
| --- | --- | --- | --- | --- | --- | --- |
| Cold cover cache (`cache\covers` cleared) | 1,710.36 ms | 1,618.29 ms | **1,664.50 ms** | 1,661.92 ms | 1,710.36 ms | 1,710.36 ms |
| Warm (disk cover cache populated) | 1,071.55 ms | 1,071.55 ms | **1,112.99 ms** | 1,140.99 ms | 1,248.50 ms | 1,248.50 ms |

---

## 3. Library Draw & UI Navigation (Median of 10 Runs)

Measured with real 920×430 JPEG covers on disk (`bench_ui_operations`):

| Operation (10 Runs) | Min | Median | Avg | P95 | Max |
| --- | --- | --- | --- | --- | --- |
| Library draw — 20 games (cold cover cache) | 434.37 ms | **570.47 ms** | 546.03 ms | 587.61 ms | 587.61 ms |
| Library draw — 20 games (warm disk cache) | 121.72 ms | **127.95 ms** | 130.77 ms | 153.87 ms | 153.87 ms |
| Library draw — 100 games (cold cover cache) | 2,318.22 ms | **2,476.79 ms** | 2,551.73 ms | 2,885.34 ms | 2,885.34 ms |
| Library draw — 100 games (warm disk cache) | 399.69 ms | **551.61 ms** | 539.06 ms | 611.19 ms | 611.19 ms |
| Open Game Page | 17.93 ms | **23.13 ms** | 22.88 ms | 28.93 ms | 28.93 ms |
| Open Settings | 6.38 ms | **10.01 ms** | 10.85 ms | 25.55 ms | 25.55 ms |
| Open Translations & Mods | 53.12 ms | **64.00 ms** | 64.84 ms | 74.87 ms | 74.87 ms |

---

## 4. Idle RAM, Idle CPU (60 s), and Scroll RAM

Measured on frozen `dist\GameRewind\GameRewind.exe` (after 5 s settle, 60 s idle window) and on 100-game scroll test:

| Metric | Baseline (`v1.2.0-rc.2`) |
| --- | --- |
| Idle CPU over 60 s (% of 1 logical core) | **5.651%** (`3.3906 s` CPU time in `60.0 s`) |
| Idle CPU over 60 s (% of total system) | **0.471%** |
| Idle RAM at start (Working Set / Private) | **183.02 MiB** / **108.26 MiB** |
| Idle RAM after 60 s (Working Set / Private) | **183.09 MiB** / **108.21 MiB** |
| Frozen library RAM after scrolling (Working Set / Private) | **183.36 MiB** / **108.54 MiB** |
| 100-game library RAM after full scroll (Working Set / Private) | **219.24 MiB** / **135.45 MiB** |

**Idle CPU root cause identified:** `ProtectionGuard` invokes `CreateToolhelp32Snapshot` + `OpenSCManagerW` + 3× `OpenServiceW`/`QueryServiceStatusEx` every 150 ms (6.67×/sec) with full O(N) Python iteration over catalog entries, consuming ~5.65% of one logical core continuously while idle.

---

## 5. Anti-Cheat Exit Latency (Frozen `GameRewind.exe`, 40 Trials Each)

Measured wall-clock milliseconds from spawning a harmless renamed copy of `System32\ping.exe` until `GameRewind.exe` completely exited the process table:

| Game / Trigger Binary (40 Trials) | Min | Median | Avg | P95 | Max | Timeouts |
| --- | --- | --- | --- | --- | --- | --- |
| **Fortnite** (`FortniteLauncher.exe`) | 343.03 ms | 361.97 ms | **361.58 ms** | **376.09 ms** | **384.60 ms** | 0 |
| **Valorant** (`VALORANT.exe`) | 345.77 ms | 361.35 ms | **363.31 ms** | **383.54 ms** | **393.86 ms** | 0 |
| **EA SPORTS FC** (`FC26.exe`) | 348.26 ms | 358.67 ms | **361.54 ms** | **379.28 ms** | **389.92 ms** | 0 |

**Exit latency root cause identified:** `ProtectionGuard` fires `guard_bridge.triggered.emit(trigger)` via a `Qt.ConnectionType.QueuedConnection` to the Qt UI thread and arms a `200 ms` `Timer(0.20, os._exit)` failsafe. Whenever the UI thread is busy (e.g., startup `_wire_mods()` filesystem scanning, library cover decoding, or heavy scrolling), the queued Qt slot cannot execute promptly, forcing every shutdown to wait the full `200 ms` failsafe timer on top of the `150 ms` guard polling interval (~360 ms total, and up to 663 ms under heavier load as observed in M21).
