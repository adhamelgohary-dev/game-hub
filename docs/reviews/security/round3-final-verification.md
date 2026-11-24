# Round 3 Final Security Verification Report (All 8 Domains)

- **Date:** 2026-11-24
- **Auditor:** Independent Red-Team Security Auditor (Read-Only Final Verification)
- **Target Source Tree:** `e:\projects\game hub` (`gamehub/`, `packaging/`, `.github/workflows/windows.yml`, `tests/`)
- **Rebuilt Binary Verified:** `dist\GameRewind\GameRewind.exe` (`5,732,376` bytes, SHA-256 `52e76f1057b570fdae2bc7c691e3c20b044acf76a6f6cfb5a46ecc82b6cf77ff`, built `2026-11-24 20:20:11`)
- **Automated Regression Suite:**
  ```text
  .\.venv\Scripts\python.exe -m pytest tests/test_packaging.py tests/test_security_hardening.py tests/test_mods.py tests/test_zero_presence_guard.py tests/test_process_probe.py -q
  34 passed in 4.96s
  ```

---

## Rebuilt Binary (`dist/GameRewind/GameRewind.exe`) Verification

- **PE Manifest & Metadata:** `asInvoker` (`True`), `requireAdministrator` (`False`), `highestAvailable` (`False`), `FileVersion` UTF-16LE (`True`), `GameRewind.exe` UTF-16LE (`True`).
- **Zero `psutil` & Zero UPX:** `b'psutil'` absent from executable, `0` entries in `CArchive` & `PYZ.pyz`, `0` `*psutil*` files in `dist/GameRewind/_internal/`; `0` UPX markers across all `.exe`/`.dll`/`.pyd` files in `dist/GameRewind/`.
- **Round 3 Bytecode Parity:** Extracted `PYZ.pyz` & `CArchive('app')` confirmed all Round 3 symbols compiled into the rebuilt binary (`avp.exe`/`beservice_x64.exe`/`eabackgroundservice.exe` in `processes`, `reloaded`/`anti_cheat_exes` in `watcher`, `live_watcher`/`pause`/`resume` in `guard`, `tryLock` in `single_instance`, `setdefault` in `catalog`, `_arm_hard_exit_failsafe` in `app`, `require_child`/`prev_item`/`scandir` in `engine`, `_StreamingPeDetector`/15 added extensions in `manifest`, `mods` cleanup in `location`).
- **Frozen Smoke Test:** `dist\GameRewind\GameRewind.exe --smoke-test` exited `rc=0` in `4.563s` with empty `stderr`.

---

## Per-Finding Verification Matrix (All 15 Round 2 Residual Findings)

| # | Finding ID | Round 2 Severity | Round 3 Status | Code / Artifact Citation | Live Verification Evidence |
|---|---|---|---|---|---|
| 1 | **STATIC-002** | MEDIUM | **CLOSED** | `gamehub/core/sessions/processes.py:23-76,319-320`; `gamehub/core/library/xbox.py:265-274` | `if is_protected or norm_name in never_open: continue` executes before both `check_image` and `check_package`; `DEFAULT_NEVER_OPEN_EXES` expanded (`avp.exe`, `avpui.exe`, `beservice_x64.exe`, `eabackgroundservice.exe`, `epicwebhelper.exe`, `steamservice.exe`, `agent.exe`, `gta5.exe`, `robloxplayerbeta.exe`, etc.). Live probe: 13 denylisted exes passed as `exe_path` targets yielded **0** `inspect()` calls (only `NormalGame.exe` inspected). |
| 2 | **PROC-02** | MEDIUM | **CLOSED** | `gamehub/core/sessions/processes.py:279-286,319-320`; `gamehub/core/library/xbox.py:265-274` | `_with_package_family()` returns `game` unchanged when no `exe_path` target exists (`targets=()`), eliminating `package_id`-only spraying. When `exe_path` is present, `ProcessProbe.snapshot()` skips `package_id` via `games_with_exe` (`inspected=[]`). |
| 3 | **STATIC-004** | LOW | **CLOSED** | `tests/test_packaging.py:21-26,94-189` | AST gate enforces `compile` ban, `from importlib import import_module` + call ban, `ctypes.windll.<dll>` allowlist, `WinDLL`/`CDLL`/`OleDLL`/`LoadLibrary` positional & `name=` keyword checks (both `ast.Name` and `ast.Attribute`), AST check that every `self._open(...)` in `processes.py` (2 calls) passes `_QUERY_LIMITED_INFORMATION` (`0x1000`), `PySide6.QtNetwork` restricted to `single_instance.py`, and AST `upx=False` on `packaging/gamerewind.spec`. All 7 synthetic bypass snippets caught. |
| 4 | **PROC-03** | LOW | **CLOSED** | `gamehub/core/sessions/watcher.py:135-142` | `always_protected` now unions `entry.anti_cheat_exes` for every catalog entry alongside `global_anti_cheat_exes` and `always_strict_launchers`. Live probe with Fortnite set to `"full"` (targeting `FortniteClient-Win64-Shipping_EAC_EOS.exe`): `missing entry.anti_cheat_exes: []`, `missing global_anti_cheat_exes: []`. |
| 5 | **PROC-05** | LOW | **CLOSED** | `gamehub/core/protection/guard.py:611-642`; `gamehub/core/sessions/watcher.py:68-75` | `run_dummy_process_protection_test()` calls `live_watcher.pause()` (draining `_poll_lock`) before `Popen` + `live_watcher.ignore_pid(proc.pid)` and `live_watcher.resume()` in `finally:`. Live probe across 3 trials with 10ms watcher polling: `ok=True` (`62–79ms`), exact order `['pause', 'ignore:<pid>', 'resume']`, `0` false triggers on both `watcher` and `guard`. |
| 6 | **PROC-07** | MEDIUM | **CLOSED** | `gamehub/core/sessions/watcher.py:166-205` | Explicit `reloaded = False` / `reloaded = True` boolean replaces `!=` container comparison. Live empty-library test across 3 consecutive polls confirmed `protected_exes` counts `[102, 102, 102]` (never drops to `0`). |
| 7 | **ORD-10** | LOW | **CLOSED** | `gamehub/single_instance.py:37-49`; `gamehub/app.py:979-980` | `claim_or_activate()` retries `self._lock.tryLock(0)` on every iteration of the 1.0s wait loop; `app.py` calls `instance.close()` as the very first statement in `finally:` (line 980). Live two-process teardown probe (P1 closes `QLocalServer` and holds lock 250ms before unlocking): `P2_OK=True dt=0.094s rc=0`. |
| 8 | **FC-03** | HIGH | **CLOSED** | `gamehub/core/protection/catalog.py:283-305,383-405` | All 10 lookup dicts in `ProtectedGamesCatalog.__init__()` use `.setdefault()` so bundled entries cannot be overwritten; `load()` forces new override entries to `default_mode="strict"`. Live different-ID hijack probe covering Fortnite, Valorant, CS2, Apex, R6, OW2, EA FC, DBD Xbox, and a new `"full"` override entry returned `"strict"` for all 9 and preserved bundled IDs (`fortnite`, `valorant`, `counter_strike_2`). |
| 9 | **G-01** | MEDIUM | **CLOSED** | `packaging/installer.iss:66-75,161-208,282-296` | `IsLocalDrivePath` rejects `/` (`Pos('/', DirPath) = 0`) and `..` (`Pos('..', DirPath) = 0`); shared `ValidateInstallDir()` enforces local-drive, forbidden-destination, non-empty-unrelated-dir, and writability checks in **both** `NextButtonClick(wpSelectDir)` (interactive) and `PrepareToInstall()` (`/SILENT` & `/VERYSILENT`). |
| 10 | **G-02** | MEDIUM | **CLOSED** | `packaging/installer.iss:236-280` | `RunValidatedQuietUninstaller()` validates `IsLocalDrivePath(UninstallExe)` at line 251 **before** `FileExists(UninstallExe)` at line 266 (preventing UNC SMB/NTLM leaks), rejects `IsForbiddenDestination(InstallLoc)` at line 260, and enforces exact parent-directory equality `CompareText(UninstallDir, InstallLoc) = 0` at lines 263–265. |
| 11 | **G-05** | MEDIUM | **CLOSED** | `.github/workflows/windows.yml:198,207` | Inline PE security script asserts `b'highestAvailable' not in exe_bytes` (line 198), and line 207 immediately enforces `if ($LASTEXITCODE -ne 0) { throw "PE manifest/UPX security verification failed ($LASTEXITCODE)." }` before running Defender checks. |
| 12 | **MOD-03** | MEDIUM | **CLOSED** | `gamehub/app.py:685-699` | `_on_guard_trigger` and `_on_guard_failure` arm a 200ms daemon `Timer(0.20, lambda: os._exit(code))` directly on the `ProtectionGuard` thread before emitting the queued Qt signal. Live subprocess probe freezing the Qt main thread for 5.0s exited in **`266.0 ms` (`rc=0`)** on protected trigger and **`265.0 ms` (`rc=2`)** on guard failure. |
| 13 | **MOD-04** | LOW | **CLOSED** | `gamehub/modules/mods/engine.py:303-321,548-550`; `gamehub/core/storage/location.py:386` | `_resolve_mods_subpath(..., require_child=True)` rejects `validated.resolve() == base.resolve()`; live tampered `storage_dir="packages/<gid>"` in `remove_item()` logged `mods_skip_unsafe_package_dir` and preserved sibling `item_b`. `StoreLocation.move()` rollback tuple includes `dest / "mods"`; simulated `_write_bootstrap` failure cleaned `dest/mods` and `dest` completely (`exists=False`). |
| 14 | **MOD-05** | MEDIUM | **CLOSED** | `gamehub/modules/mods/manifest.py:68-187,434-493` | `_StreamingPeDetector` catches `MZ` + `PE\0\0` at any `e_lfanew` across chunk boundaries (verified live at `e_lfanew=64`, `4096`, `131070`, `200000`, and 3-byte streaming, with 0 false positives on non-PE `MZ` files). All 15 added extensions (`.pyo`, `.msixbundle`, `.appxbundle`, `.appinstaller`, `.diagcab`, `.mjs`, `.cjs`, `.vb`, `.vba`, `.xll`, `.xlsm`, `.docm`, `.img`, `.m3d`, `.mix`) verified present and rejected. |
| 15 | **MOD-08** | MEDIUM | **CLOSED** | `gamehub/modules/mods/engine.py:444-494,567-595` | Failed v1→v2 re-import rolls back both `final_dir` and SQLite `mod_items` to `prev_item`; live probe confirmed `db_ver=1.0`, `recover_incomplete()` returned `1` with `remaining_journals=()` and disk at `b'V1_BYTES'`. `_cleanup_staging_and_temps()` uses reparse-safe `os.scandir`; live NTFS junction probe preserved outside `keep.grtmp` (`exists=True`) while removing in-tree `stale.grtmp` (`exists=False`). |

---

## Informational Observations (Non-Blocking)

1. **INFO-01 (Local Portable ZIP Timestamp):** `dist\GameRewind-Portable-v1.2.0-rc.2.zip` (`2026-11-24 20:04:01`) predates the Round 3 rebuild of `dist\GameRewind\GameRewind.exe` (`2026-11-24 20:20:11`). Re-compress the portable archive before any local artifact upload (the GitHub Actions release workflow builds it fresh from source).
2. **INFO-02 (Future AST Hygiene):** `tests/test_packaging.py` closes all Round 2 `STATIC-004` gaps; in a future maintenance pass, extending the AST gate to also reject `from PySide6 import QtNetwork` and `ctypes.cdll`/`ctypes.oledll` attribute access would harden it further (all dangerous networking/Win32 symbols already remain blocked via `FORBIDDEN_NATIVE_SYMBOLS`).

---

## Final Verdict

**PASS (0 open findings — all 15 Round 2 residual findings verified CLOSED across source, tests, live adversarial probes, and rebuilt `dist/GameRewind/GameRewind.exe`).**
