# Red-Team Report C3 — Local Safety, Mods & CI Supply Chain (`v1.2.0-rc.3`)

**Role:** Independent Local Safety, Mods & CI Red-Team Auditor (C3 — fresh eyes)  
**Date:** 2026-11-24  
**Scope:** `single_instance.py`, `packaging/installer.iss`, `core/storage/*`, `modules/mods/*`, `.github/workflows/windows.yml`.

## Audit Matrix

| Area | Verification Result |
| --- | --- |
| **Single-Instance Socket & Lock (`single_instance.py`)** | `QLocalServer` enforces `UserAccessOption` (same-user ACL). Live subprocess test verified `QLockFile` cleanly detects stale PID and reclaims lock immediately after direct guard-thread `os._exit(0)`. |
| **Installer & Uninstaller (`packaging/installer.iss`)** | `PrivilegesRequired=lowest`, `DisableDirPage=no`, `UsePreviousAppDir=no`, `ValidateInstallDir` enforced in BOTH interactive `NextButtonClick` and `/VERYSILENT` `PrepareToInstall` (rejects UNC, `/`, `..`, drive roots, Desktop directly, `%USERPROFILE%`, `%LOCALAPPDATA%`, data folders, non-empty unrelated folders, unwritable paths). `RunValidatedQuietUninstaller` validates local drive + exact `InstallLocation` parent match + `unins*.exe` before `FileExists`. Removes legacy `HKCU\...\Run` keys and never creates any startup entry. Preserves `%LOCALAPPDATA%\GameRewind` on upgrade/uninstall. |
| **Data Folder & Migration (`location.py`, `media.py`)** | Reparse/symlink-safe traversal (`_is_reparse`), atomic `sqlite3.backup()` + `quick_check`/`foreign_key_check`, bounded file copies, non-destructive `GameHub -> GameRewind` migration, relative paths surviving `StoreLocation.move()`. |
| **Translations & Mods (`manifest.py`, `engine.py`)** | Declarative-only JSON validator (iterative traversal immune to `RecursionError`), 70+ forbidden executable/script extensions, streaming arbitrary-offset PE detector (`_StreamingPeDetector`), path traversal / reserved Windows device names / BiDi & control chars / zip symlinks / encrypted entries / `src`-reuse zip bombs / case-insensitive collision rejection, atomic verify-before-replace writes, crash-safe `mod_journal` recovery, permanent lock on protected/online games even if `protection_mode='full'`, blocked whenever any game or anti-cheat is running. |
| **CI Supply Chain (`.github/workflows/windows.yml`)** | All third-party actions pinned to 40-char commit SHAs (`checkout`, `setup-python`, `upload-artifact`, `signpath`), `persist-credentials: false`, least-privilege `permissions:`, `SHA256SUMS.txt` generated, bundle size & forbidden-binary gate enforced, `MpCmdRun.exe` Defender scan enabled. |

## Round 1 Findings

### `[MEDIUM] C3-01` — `ModsEngine._protected_cache` lacked TTL expiration for UI reads
- **Evidence:** While `_assert_not_protected()` always bypassed the cache (`use_cache=False`) before mutations, UI reads (`is_game_protected()`) cached `False` keyed only by top-level `install_dir.st_mtime_ns` (which NTFS does not update when a deeper subdirectory changes).
- **Fix Applied:** Added a 15-second monotonic TTL on `_protected_cache` entries and ensured `invalidate_protection_cache()` is called on `LibraryChanged` and protection policy updates while keeping `_assert_not_protected()` 100% uncached.
- **Verification:** `tests/test_mods.py` + `tests/test_security_hardening.py` PASS.

### `[LOW] C3-02` — Missing automated regression test for `SingleInstance` recovery after hard `os._exit(0)`
- **Evidence:** Direct guard-thread `os._exit(0)` leaves `gamehub.lock` on disk; live verification passed, but needed a permanent automated regression test.
- **Fix Applied:** Added `tests/test_security_rc3.py::test_single_instance_recovers_cleanly_after_hard_os_exit`.
- **Verification:** PASS (subprocess `os._exit(0)` -> second process claims lock cleanly).

## Round 2 Verdict: **PASS — 0 Open Findings**
