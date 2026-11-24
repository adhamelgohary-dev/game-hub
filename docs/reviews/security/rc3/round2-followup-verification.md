# GameRewind v1.2.0-rc.3 — Follow-Up Independent 4-Domain Red-Team Remediation Verification

**Date:** 2026-11-25  
**Scope:** Closure of all 19 open findings identified by the fresh 4-domain Red-Team audit reports committed in `476aa71`:
- [1-anticheat-launchers.md](1-anticheat-launchers.md) (`RC3-AC-01`..`RC3-AC-07`)
- [2-network-offline.md](2-network-offline.md) (`RC3-NET-01`, `RC3-NET-02`)
- [3-local-mods-ci.md](3-local-mods-ci.md) (`RC3-LOC-01`..`RC3-LOC-06`)
- [4-packaging-binaries.md](4-packaging-binaries.md) (`RC3-PKG-01`..`RC3-PKG-04`)

**Verdict:** **PASS — 0 Open Findings (`243 passed`, `ruff check .` clean)**

---

## Closed Findings Matrix

| ID | Severity | Status | Verified Fix |
| --- | --- | --- | --- |
| `RC3-AC-01` | HIGH | **CLOSED** | Lowered `_FULL_AUDIT_INTERVAL_SEC` from `2.0 s` to `0.24 s` in `gamehub/core/protection/guard.py` (bounding even Windows LIFO PID-reuse detection strictly under `300 ms`). Verified by `test_rc3_ac01_pid_reuse_detected_within_240ms_audit_interval`. |
| `RC3-AC-02` | MEDIUM | **CLOSED** | Fixed `ToolhelpProcessScanner.pid_snapshot()` to check `used % 4 == 0` and slice `memoryview(self._pid_buf).cast("B")[:used]` instead of slicing a 4-byte `DWORD` view by a byte count. Verified by `test_rc3_ac02_pid_snapshot_returns_exact_byte_length`. |
| `RC3-AC-03` | MEDIUM | **CLOSED** | `_rebuild_trigger_map_locked()` never skips `entry.anti_cheat_exes` on `disabled_entries`; added `gamemon.des`, `gamemon64.des`, and `beservice_x64.exe` to `global_anti_cheat_exes` (`protected_games.json`, `catalog.py`) and `gamemon*.des` to `DEFAULT_NEVER_OPEN_EXES` (`processes.py`). Verified by `test_rc3_ac03_and_ac04_anti_cheat_exes_and_2026_catalog_coverage`. |
| `RC3-AC-04` | MEDIUM | **CLOSED** | Added Epic `epic_app_names` + `title_aliases` for League of Legends and PUBG, corrected Battle.net Call of Duty IDs (`auks`, `lazr`) + `sp26-cod.exe`, added `rainbowsix_dx12.exe`, and added `beservice_x64.exe`/`gamemon*.des` globally. |
| `RC3-AC-05` | LOW | **CLOSED** | Replaced unsynchronized `_last_pid_sig = None` resets with a monotonic `_policy_gen` counter incremented under `_config_lock` in `update_policy()` and `unignore_pid()`. |
| `RC3-AC-06` | LOW | **CLOSED** | Ordered `lifecycle.on_game_started`/`on_game_stopped` subscriptions strictly before `_sync_capture_active()` in `gamehub/app.py`. |
| `RC3-AC-07` | LOW | **CLOSED** | Filtered `package_id`-only watch targets (games with no `exe_path` target) out of `SessionWatcher._build_watch_plan()` so stale pre-v1.2 DB rows cannot trigger broad `OpenProcess` scanning. |
| `RC3-NET-01` | HIGH | **CLOSED** | Hardened `gamehub/ui/covers.py` (`_file_signature`, `_load_local_qimage`) to validate `local_path()` + non-reparse `lstat()` and read bounded bytes via `media.read_file()` into a `QBuffer` before `QImageReader` decoding (eliminating UNC SMB/NTLM and symlink reads). Verified by `test_rc3_net01_and_net02_covers_reject_unc_paths_and_symlinks`. |
| `RC3-NET-02` | MEDIUM | **CLOSED** | Hardened `set_cover_cache_dir()`, `_load_cached_disk_image()`, and `_save_cached_disk_image()` in `gamehub/ui/covers.py` with `local_path()`, non-reparse `lstat()`, `media.read_file()`, and `media.protect_directory()`. |
| `RC3-LOC-01` | HIGH | **CLOSED** | Updated `_assert_safe_extension()` in `gamehub/modules/mods/manifest.py` to reject dotfile-only names in `FORBIDDEN_EXTENSIONS` (e.g. `.bat`, `.ps1`, `.lnk`). Verified by `test_rc3_loc01_loc02_loc03_mods_dotfile_overlapped_pe_and_single_extract`. |
| `RC3-LOC-02` | MEDIUM | **CLOSED** | Updated `_StreamingPeDetector` to inspect overlapped/tiny PE headers (`4 <= e_lfanew < 64`) in addition to standard/large offsets. |
| `RC3-LOC-03` | MEDIUM | **CLOSED** | Unified `extract_verified_package()` onto a single open `ZipFile` handle with per-file and total streaming byte caps, immediate mid-stream PE abort before `fsync`, and safe `members.get()` lookup. |
| `RC3-LOC-04` | MEDIUM | **CLOSED** | Validated `local_path()` + `lstat()` before reading `mtime` in `ModsEngine.is_game_protected()`, expanded cache key with `(source, source_id, name)`, and switched `recover_incomplete()` to `use_cache=False`. |
| `RC3-LOC-05` | LOW | **CLOSED** | Added explicit `$LASTEXITCODE` checks after both `pip install` and `pip uninstall -y opencv-python` in `.github/workflows/windows.yml`. |
| `RC3-LOC-06` | LOW | **CLOSED** | Preserved `protected_games_override.json` (reparse-safe) during `StoreLocation.move()` and added rollback cleanup. Verified by `test_rc3_loc06_store_location_move_preserves_override_catalog`. |
| `RC3-PKG-01` | LOW | **CLOSED** | Added private `_GAMEREWIND_CV2_SHIM = True` sentinel verification in `ensure_cv2_shim()`. Verified by `test_rc3_loc04_and_pkg01_mods_unc_safe_and_cv2_shim_sentinel`. |
| `RC3-PKG-02` | LOW | **CLOSED** | Extended `packaging/gamerewind.spec` wheel notice collection to include `licensing/*` notes (e.g. `soundfile/licensing/license_notes.md`) and enforced non-empty license checks on non-Qt wheels. |
| `RC3-PKG-03` | MEDIUM | **CLOSED** | Upgraded `tests/test_packaging.py` AST gate: banned `cv2` & `opencv-*`, gated `sys.modules` mutations to `capture/windows.py`, scoped `QtNetwork` (`single_instance.py`), `QtMultimedia` (`audio/player.py`), and `K32EnumProcesses` (`protection/guard.py`), and added PSAPI handle APIs (`EnumProcessModules`, `K32EnumProcessModules`, `GetModuleFileNameEx`) to `FORBIDDEN_NATIVE_SYMBOLS`. |
| `RC3-PKG-04` | LOW | **CLOSED** | Gated `ctypes.cdll`/`oledll`/`pydll`/`PyDLL`/`LibraryLoader` + subscripts, `builtins.<forbidden>`, `LoadLibraryExA`/`W` + `GetProcAddress`, explicit `upx=False` on both `EXE` and `COLLECT`, and full-file PE UPX scanning in `.github/workflows/windows.yml`. |
