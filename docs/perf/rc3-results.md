# GameRewind v1.2.0-rc.3 — Speed & Size Results (vs. `v1.2.0-rc.2` Baseline)

**Recorded:** 2026-11-24 / 2026-11-25  
**Baseline:** [docs/perf/baseline-rc2.md](baseline-rc2.md) ([baseline-rc2-raw.json](baseline-rc2-raw.json))  
**rc.3 Raw Trial Data:** [rc3-results-raw.json](rc3-results-raw.json)  
**Benchmark Script:** [scripts/bench/benchmark_rc.py](../../scripts/bench/benchmark_rc.py)  
**Regression Tests:** [tests/test_performance_regressions.py](../../tests/test_performance_regressions.py), [tests/test_packaging.py](../../tests/test_packaging.py)

---

## 1. Size Comparison (Local Workspace & Shipped Artifacts)

| Metric | `v1.2.0-rc.2` Baseline | `v1.2.0-rc.3` | Change | Target |
| --- | --- | --- | --- | --- |
| Local working folder (total) | `2,964.2 MB` (`~2.89 GB`) | **`736.56 MB`** (after clean + rc.3 build; `543.49 MB` clean) | **-75.2% (-2.23 GB freed)** | Clean local junk |
| Git repository (`git count-objects -vH` / GitHub) | `4.62 MiB` / `3.86 MiB` (0 binaries in history) | `~4.7 MiB` (0 binaries in history) | Verified clean | Public & small |
| Installed folder (`dist\GameRewind`) | `302.13 MiB` (`316.81 MB`) | **`123.24 MiB`** local / **`123.45 MiB`** CI (`129.44 MB`) | **-59.1% (-178.7 MiB)** | `< 200 MiB` ✅ |
| Portable `.zip` | `121.32 MiB` (`127.21 MB`) | **`50.98 MiB`** local / **`52.41 MiB`** CI (`54.96 MB`) | **-56.8% (-68.9 MiB)** | `< 70 MiB` ✅ |
| Setup `.exe` (Inno Setup LZMA2) | `81.24 MiB` (`85.19 MB`) | **`38.07 MiB`** CI (`39.92 MB`) | **-53.1% (-43.2 MiB)** | Clean & Defender `0 threats` ✅ |
| PE binary count in `dist\GameRewind` | `114` PE files | **`85` PE files** | **-29 binaries** | 0 `cv2`/`psutil`/`opengl32sw` ✅ |

*Verified on Windows CI (`windows-2025`, run `45510996638`): `GameRewind-Setup-v1.2.0-rc.3.exe` (`38.07 MiB`, SHA-256 `980d4499836bcae0cc3c41b0b3e75a44f1348b269e896e294e05b0fa1753b085`) and `GameRewind-Portable-v1.2.0-rc.3.zip` (`52.41 MiB`, SHA-256 `b79b2e8f3ab43837869e95088ffc3814a87bdb24a7d5df2a9529907c132d5e2b`) passed all bundle-size gates, PE manifest/zero-UPX checks, smoke tests, and Windows Defender (`MpCmdRun.exe`) scans with `0 threats`.*

---

## 2. Startup & UI Navigation (Median of 10 Runs)

| Scenario | `v1.2.0-rc.2` Baseline | `v1.2.0-rc.3` | Change |
| --- | --- | --- | --- |
| Frozen startup — cold cover cache (`GameRewind.exe`) | `1,664.50 ms` | **`1,115.59 ms`** | **-33.0% (-548.9 ms)** |
| Frozen startup — warm (`GameRewind.exe`) | `1,112.99 ms` | **`1,014.46 ms`** (min `896.52 ms`) | **-8.9% (-98.5 ms)** |
| Library draw — 20 games (cold cover cache) | `570.47 ms` | **`123.19 ms`** | **4.6× faster (-78.4%)** |
| Library draw — 100 games (cold cover cache) | `2,476.79 ms` | **`626.12 ms`** | **4.0× faster (-74.7%)** |
| Open Game Page | `23.13 ms` | **`25.54 ms`** | Comparable (~25 ms) |
| Open Settings | `10.01 ms` | **`11.98 ms`** | Comparable (~12 ms) |
| Open Translations & Mods | `64.00 ms` | **`12.87 ms`** | **5.0× faster (-79.9%)** |

*Note on async cover loading: In `v1.2.0-rc.3`, `CoverLabel` paints non-blocking placeholders immediately and decodes/crops/caches WebP covers off the UI thread with viewport-aware lazy loading on scroll; `library_draw_*` above measures full completion until all visible covers finish decoding.*

---

## 3. Idle CPU & Memory (Frozen `GameRewind.exe`, 60 s Idle + Scroll)

| Metric | `v1.2.0-rc.2` Baseline | `v1.2.0-rc.3` | Change |
| --- | --- | --- | --- |
| Idle CPU over 60 s (% of 1 logical core) | `5.651%` (`3.391 s`) | **`1.432%`** (`0.859 s`) | **4.0× lower (-74.7%)** |
| Idle CPU over 60 s (% of total system) | `0.471%` | **`0.119%`** (~0.1%) | **4.0× lower** |
| Idle RAM after 60 s (Working Set / Private) | `183.09 / 108.21 MiB` | **`184.66 / 106.10 MiB`** | `-2.1 MiB` Private |
| Frozen library RAM after scroll (WS / Private) | `183.36 / 108.54 MiB` | **`184.91 / 106.29 MiB`** | `-2.3 MiB` Private |

---

## 4. Safety-Critical Anti-Cheat Exit Latency (Frozen `GameRewind.exe`, 40 Trials Each)

Measured wall-clock milliseconds from spawning a harmless renamed copy of `System32\ping.exe` until `GameRewind.exe` completely exited the Windows process table. Targets: **P95 < 200 ms**, **Max < 300 ms** both normally and under UI load.

### Normal Operation (40 Trials Each = 120 Trials)
| Game (`Trigger Binary`) | `rc.2` Avg / P95 / Max | `rc.3` Min | `rc.3` Avg | `rc.3` P95 | `rc.3` Max | Target Status |
| --- | --- | --- | --- | --- | --- | --- |
| **Fortnite** (`FortniteLauncher.exe`) | `361.6 / 376.1 / 384.6 ms` | `40.89 ms` | **`80.66 ms`** | **`149.97 ms`** | **`166.29 ms`** | **PASS** (4.5× faster) ✅ |
| **Valorant** (`VALORANT.exe`) | `363.3 / 383.5 / 393.9 ms` *(M21 max 663 ms)* | `37.43 ms` | **`82.22 ms`** | **`171.31 ms`** | **`180.46 ms`** | **PASS** (4.4× faster) ✅ |
| **EA SPORTS FC** (`FC26.exe`) | `361.5 / 379.3 / 389.9 ms` | `33.92 ms` | **`85.23 ms`** | **`141.14 ms`** | **`153.84 ms`** | **PASS** (4.2× faster) ✅ |

### Under Active UI Load (40 Trials Each = 120 Trials, Continuous Scrolling)
| Game (`Trigger Binary`) | `rc.3` Min | `rc.3` Avg | `rc.3` P95 | `rc.3` Max | Timeouts | Target Status |
| --- | --- | --- | --- | --- | --- | --- |
| **Fortnite** (`FortniteLauncher.exe`, UI load) | `42.89 ms` | **`75.30 ms`** | **`133.45 ms`** | **`137.37 ms`** | `0` | **PASS** (`P95 < 200`, `Max < 300`) ✅ |
| **Valorant** (`VALORANT.exe`, UI load) | `41.74 ms` | **`81.97 ms`** | **`154.56 ms`** | **`163.47 ms`** | `0` | **PASS** (`P95 < 200`, `Max < 300`) ✅ |
| **EA SPORTS FC** (`FC26.exe`, UI load) | `39.70 ms` | **`86.91 ms`** | **`135.70 ms`** | **`153.34 ms`** | `0` | **PASS** (`P95 < 200`, `Max < 300`) ✅ |

**Raw trial data (all 240 trials):** Published verbatim in [docs/perf/rc3-results-raw.json](rc3-results-raw.json).
