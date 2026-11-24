# Red-Team Security Audit — Focus (h): Translations & Mods Safety

- **Target:** GameRewind Translations & Mods subsystem (`e:\projects\game hub`)
- **Date:** 2026-11-24
- **Auditor:** Independent Red-Team Security Auditor (Read-only code & local PoC verification)
- **Baseline:** `tests/test_mods.py` — 5/5 passed prior to adversarial testing.
- **Files Audited:**
  - `gamehub/modules/mods/models.py`
  - `gamehub/modules/mods/manifest.py`
  - `gamehub/modules/mods/repository.py`
  - `gamehub/modules/mods/engine.py`
  - `gamehub/modules/mods/sample_pack.py`
  - `gamehub/ui/mods_view.py`
  - `gamehub/app.py` (`_wire_mods`, `_wire_settings`, `_run`)
  - Cross-boundary dependencies inspected: `gamehub/core/protection/catalog.py`, `gamehub/core/protection/protected_games.json`, `gamehub/core/library/paths.py`, `gamehub/core/library/ubisoft.py`, `gamehub/core/library/battlenet.py`, `gamehub/core/library/ea.py`, `gamehub/core/library/riot.py`, `gamehub/core/storage/db.py`, `gamehub/core/storage/location.py`

---

## Executive Summary

While the Translations & Mods module establishes strong baseline concepts (declarative JSON manifests, SHA-256 checksums, atomic file replacement, reparse checks on `install_dir`, and SQLite journaling), adversarial testing broke **all four security boundaries** (Protected Games Lock, Running-Game Lock, Path/Archive/Filesystem Safety, and Crash-Safe Journal).

All findings below were verified against the live codebase with concrete file:line citations and non-destructive local reproductions in isolated temporary directories.

| ID | Severity | Boundary | Summary | Primary Locations |
|---|---|---|---|---|
| **MOD-01** | **CRITICAL** | Path / Backup Integrity | Case-insensitive path collisions on Windows bypass conflict detection, overwrite the original backup with mod bytes, and permanently break `restore_original()` | `engine.py:233,274,375,459-475`, `db.py:217-245` |
| **MOD-02** | **CRITICAL** | Protected Games Lock | Protected online games bypass the lock when `install_dir` contains protected/anti-cheat exes not listed in `game_targets` (Ubisoft R6 Siege, Battle.net OW2/WoW, Manual/Folder sibling exe, Riot `2XKO`) | `engine.py:130-140`, `catalog.py:391-422`, `ubisoft.py:141`, `battlenet.py:123` |
| **MOD-03** | **HIGH** | Running-Game Lock | Running-game check misses subdirectory exes (`Binaries\Win64\`, `bin\x64\`), Xbox `package_id` targets, anti-cheat services; suffers multi-second TOCTOU before disk writes and blocks `ProtectionGuard` emergency exit on the Qt main thread | `engine.py:155-190,318-343,439-540`, `app.py:596-626,1043-1091` |
| **MOD-04** | **HIGH** | Filesystem / Integrity | Unverified write-before-verify overwrites game files on checksum failure; untrusted DB `storage_dir`/`backup_path` allows arbitrary backup reads and cross-game `shutil.rmtree` wipe; `StoreLocation.move()` permanently breaks restores | `engine.py:394-398,496-502,527-532`, `location.py:152-175,375-393` |
| **MOD-05** | **HIGH** | Archive / Payload Safety | `FORBIDDEN_EXTENSIONS` misses game-mod native code loaders (`.asi`, `.pyd`, `.pyc`, `.flt`) and dangerous Windows executable/handler extensions (`.jar`, `.chm`, `.msc`, `.wsc`, `.sct`, `.scf`, `.msix`, `.appx`, `.iso`, `.vhd`, `.cab`, `.ps1xml`, `.library-ms`); zero PE (`MZ`) header check | `manifest.py:60-95,145-150` |
| **MOD-06** | **HIGH** | Archive / DoS | `src`-reuse amplification bypasses 512 MB limit (3.2 KB zip → 600 MB validated; scales to **128 GB** staging + **128 GB** deploy); deeply nested `manifest.json` triggers unhandled `RecursionError` app crash; `manifest.json` read lacks streaming cap | `manifest.py:153-164,205-221,284-308,345-368`, `app.py:1047` |
| **MOD-07** | **MEDIUM** | Path Traversal / Windows Paths | `normalize_rel_path` accepts `CONIN$`, `CONOUT$`, space-before-dot devices (`CON .txt`, `NUL .cfg`), superscript DOS devices (`COM¹`, `LPT²`), `< > " \| ? *`, control chars (`\t`, `\n`), BiDi overrides (`\u202e`), unbounded paths (>260 chars), and file/dir prefix collisions; zip member map is case-sensitive | `manifest.py:97-143,273-292,350-356` |
| **MOD-08** | **MEDIUM** | Crash-Safe Journal | DB state mutations & `shutil.rmtree` package replacement occur *before* `begin_journal()`; mid-deploy crash orphans files when another mod is active (`if not desired:`); deferred recovery prematurely closes secondary journals; `.grtmp`/staging leftovers never GC'd; stale backups downgrade patched games | `engine.py:329-343,354-437,487-492,530-538` |
| **MOD-09** | **MEDIUM** | Reparse Points / Containment | Junction at `data_root/mods/backups/<game_id>` bypasses `is_relative_to` check; `install_dir` can overlap `data_root` or system dirs (`C:\`, `C:\Windows`), allowing a mod to overwrite `protected_games_override.json`; override catalog can strip bundled Fortnite/Valorant protection | `engine.py:192-201,217-224`, `catalog.py:323-333` |
| **MOD-10** | **LOW** | UI / Concurrency | Settings protection changes (`on_guard_policy_changed`) do not refresh Mods UI; `GameModsWidget` hides rather than clears/disables controls on lock; `ModsEngine` lacks per-game concurrency locking | `app.py:843-847`, `mods_view.py:194-200`, `engine.py:110` |

---

## Detailed Findings

---

### [MOD-01] CRITICAL — Case-Insensitive Path Collisions on Windows Corrupt Original Backups & Permanently Break Restore

- **Boundary:** Path Safety & Backup Integrity
- **Locations:**
  - `gamehub/modules/mods/engine.py:230-233` (`_compute_conflicts` keys `by_path` by case-sensitive `f.dest`)
  - `gamehub/modules/mods/engine.py:271-274` (`_desired_file_map` keys `owners_by_path` by case-sensitive `f.dest`)
  - `gamehub/modules/mods/engine.py:375-377` (`choose_conflict_winner` intersects case-sensitive `f.dest` sets)
  - `gamehub/modules/mods/engine.py:459-475` (`_reconcile_game` checks `if rel_path in backups:` case-sensitively, then writes `_atomic_copy_file(target, backup_dst)`)
  - `gamehub/core/storage/db.py:217-245` (`mod_backups`, `mod_deployed_files`, `mod_conflict_choices` use case-sensitive `BINARY` primary keys on `(game_id, rel_path)`)

#### Attack Vector & Verified Reproduction
Although `parse_manifest_dict` (`manifest.py:217`) checks `dest.casefold()` *within a single manifest*, all cross-mod and engine/SQLite tracking is **case-sensitive**, whereas Windows NTFS is case-insensitive:
1. Original game has `localization/fonts.cfg` (`ORIGINAL_FONT_DATA`).
2. User imports **Mod A** targeting `localization/fonts.cfg` (`MOD_A_DATA`). Engine backs up `ORIGINAL_FONT_DATA` to `backups/<game_id>/localization/fonts.cfg` and deploys `MOD_A_DATA` into `install_dir`.
3. User imports **Mod B** targeting `localization/Fonts.cfg` (capital `F`, `MOD_B_DATA`) — **or** updates Mod A to v2 with changed casing (`localization/Fonts.cfg`).
4. `_compute_conflicts()` and `_desired_file_map()` treat `"localization/fonts.cfg"` and `"localization/Fonts.cfg"` as **two unrelated files** (`conflicts == ()`).
5. In `_reconcile_game` step 1 (`engine.py:460`), `"localization/Fonts.cfg" in backups` is `False`. On NTFS, `install_dir/localization/Fonts.cfg` exists and holds **`MOD_A_DATA`**. `_backup_file_path()` computes `backups/<game_id>/localization/Fonts.cfg`, which on NTFS is the **exact same file on disk** as `backups/<game_id>/localization/fonts.cfg`. `_atomic_copy_file()` **overwrites the original game backup on disk with `MOD_A_DATA`**.
6. When the user clicks **"Restore the original game"**, `_reconcile_game` step 2 reads `backups/<game_id>/localization/fonts.cfg` (now `MOD_A_DATA`), overwrites the game file, and fails with `ModFilesystemError("Backup checksum mismatch")`.

**Observed PoC Output:**
```text
=== [MOD-01] Case-insensitive collision on Windows ===
Conflicts detected: 0 (expected 1 if safe)
Original backup file contents now: b'MOD_A_DATA'
restore_original FAILED with: Backup checksum mismatch while restoring 'localization/fonts.cfg'.
Game file after failed restore: b'MOD_A_DATA'
```

#### Impact
Permanent, unrecoverable destruction of original game backups and total failure of "Restore the original game" triggered trivially by two mods (or one mod update) differing only in letter case.

#### Recommended Fix
1. Canonicalize all path comparison keys via `.casefold()` (`rel_key = rel_path.casefold()`) across `_compute_conflicts`, `_desired_file_map`, `choose_conflict_winner`, `_reconcile_game`, and `ModsRepository` lookups (or store `rel_path_key` / `COLLATE NOCASE` in `mod_backups`, `mod_deployed_files`, and `mod_conflict_choices`).
2. Store backup files on disk by content/key hash (e.g., `backups/<game_id>/<sha256(rel_path.casefold())>.bak`) instead of mirroring raw `rel_path` casing on NTFS, and refuse to overwrite an existing backup file (`open("xb")` or `if backup_dst.exists():` guard).

---

### [MOD-02] CRITICAL — Protected-Game Lock Bypass via Missing Launcher IDs & Unscanned `install_dir`

- **Boundary:** Protected Games Lock (Zero-Presence / Account Safety)
- **Locations:**
  - `gamehub/modules/mods/engine.py:130-140` (`is_game_protected` only checks `library.list_target_basenames().get(game.id, ())` + `catalog.match_game`)
  - `gamehub/core/protection/catalog.py:391-422` (`match_game` only checks `STEAM`, `EPIC`, `RIOT`, `XBOX` IDs — zero support for `UBISOFT`, `BATTLENET`, `EA`)
  - `gamehub/core/library/ubisoft.py:141-142` (`_pick_exe` returns `None` when >1 `.exe` exists in root, leaving `targets=()`)
  - `gamehub/core/library/battlenet.py:121-137` (`_pick_exe` only scans top-level `install_dir`, picking `Overwatch Launcher.exe` or `None` while `_retail_\Overwatch.exe` / `_retail_\Wow.exe` is in a subdirectory)
  - `gamehub/core/library/riot.py:22` & `gamehub/core/protection/protected_games.json:35-65` (Riot `2XKO` / `lion` is detected by `RiotDetector` but omitted from `protected_games.json`)

#### Attack Vectors & Verified Reproduction
`ModsEngine.is_game_protected()` NEVER inspects `game.install_dir` (nor parent/child directories, nor overlap with other protected library games) and relies strictly on `game_targets` + `catalog.match_game()`. Four real-world bypasses were reproduced:

1. **Ubisoft Connect (e.g., Rainbow Six Siege / BattlEye):** Root folder contains `RainbowSix.exe`, `RainbowSix_BE.exe`, and `RainbowSix_Vulkan.exe`. `UbisoftDetector._pick_exe()` sees `len(candidates) > 1` and returns `None` (`targets = ()`). `catalog.match_game(GameSource.UBISOFT, "635", ())` has no Ubisoft ID table and returns `None`. `ModsEngine` unlocks Rainbow Six Siege and deploys mods directly into its install directory!
2. **Battle.net (e.g., Overwatch 2 / World of Warcraft / Warden):** Root folder contains `Overwatch Launcher.exe` while the game binary is `_retail_\Overwatch.exe`. `BattleNetDetector` sets `targets = ('overwatch launcher.exe',)` (not in `protected_games.json`) and `catalog.match_game` has no Battle.net ID table. `ModsEngine` unlocks Overwatch 2 and deploys mods!
3. **Manual Add / Scan Folder Sibling or Subdir Exe (e.g., Fortnite / EAC / BattlEye / Valorant):** User manually adds any auxiliary `.exe` inside a protected game folder (e.g., `Fortnite\FortniteGame\Binaries\Win64\CrashReportClient.exe` or a custom `.exe` inside `C:\Program Files\Epic Games\Fortnite`). Even though `FortniteClient-Win64-Shipping.exe` sits in the **exact same folder** (and Fortnite may already be locked as an Epic game in the same library), `is_game_protected()` checks only the manual entry's own `game_targets` (`crashreportclient.exe`) and returns `(False, "")`, deploying mods straight into Fortnite's directory!
4. **Riot Client Game (`2XKO` / `lion.live`):** Detected with `GameSource.RIOT` (`source_id="lion.live"`), which uses Riot Vanguard, yet `GameSource.RIOT` is not blanket-locked and `"lion"` is absent from `protected_games.json`.

**Observed PoC Output:**
```text
=== [MOD-02] Protected-game lock bypasses ===
2A Ubisoft R6 protected=(False, '') targets=None
2A Ubisoft R6 mod deployed: True
2B Battle.net OW2 protected=(False, '') targets=('overwatch launcher.exe',)
2B Battle.net OW2 mod deployed: True
2C Manual helper in Fortnite Win64 protected=(False, '')
2C Mod deployed right next to FortniteClient-Win64-Shipping.exe: True
2D Riot 2XKO protected=(False, '')
```

#### Impact
GameRewind can modify files inside kernel anti-cheat protected game installations (BattlEye, Easy Anti-Cheat, Riot Vanguard, Blizzard Warden, EA Javelin), directly violating the zero-ban-risk account safety boundary.

#### Recommended Fix
1. **Bounded directory inspection in `ModsEngine.is_game_protected()`:** Depth-bounded (e.g. max depth 4, max 2048 entries, symlink-safe) scan of `game.install_dir` (and checking up to 3 ancestor folders for markers when `install_dir` is a deep subdir like `Binaries\Win64`) for:
   - Any `.exe` matching `catalog.all_exe_names()` (covering `game_exes`, `launcher_stage_exes`, `anti_cheat_exes`, `global_anti_cheat_exes`, `always_strict_launchers`).
   - Known anti-cheat directories/artifacts (`EasyAntiCheat`, `EasyAntiCheat_EOS`, `BattlEye`, `EAAntiCheat`, `AntiCheatExpert`, `GameGuard`, `HoYoKProtect`, `EasyAntiCheat_*.dll/.sys`, `BEService*.exe`, `BEClient*.dll`, `vgk.sys`).
2. **Cross-library path overlap check:** Lock `game` if its `install_dir` equals, is a parent of, or is a child of ANY protected game's `install_dir` in the library.
3. **Blanket-lock `GameSource.RIOT`** (all Riot desktop titles ship with Vanguard/online anti-cheat) and extend `protected_games.json` + `catalog.match_game()` with `ubisoft_install_ids`, `battlenet_uids`, and `ea_offer_ids` (plus `launch_target` exe basename fallback).

---

### [MOD-03] HIGH — Running-Game Lock Bypasses, Multi-Second TOCTOU, & Qt Main-Thread Blocking of Emergency Exit

- **Boundary:** Running-Game Lock & Zero-Presence Guard
- **Locations:**
  - `gamehub/modules/mods/engine.py:155-190` (`_collect_known_game_exes`, `_assert_no_game_running`)
  - `gamehub/modules/mods/engine.py:318-343` (`import_zip` checks running games once before extraction & reconcile)
  - `gamehub/modules/mods/engine.py:439-540` (`_reconcile_game` never re-checks `_assert_no_game_running`)
  - `gamehub/app.py:596-626` (`guard_bridge.triggered` uses `Qt.ConnectionType.QueuedConnection` + `guard_watchdog` `QTimer` on main thread)
  - `gamehub/app.py:780-783` (`recover_incomplete()` runs before `watcher.start()`)
  - `gamehub/app.py:1043-1091` (`_run_action` executes all mod I/O synchronously on the Qt main thread)

#### Attack Vectors & Verified Reproduction
1. **Subdirectory game executables completely missed:** `_collect_known_game_exes()` (`engine.py:166-168`) only iterates top-level `install_root.iterdir()` of `target_game`. Modern games launched via a root launcher (e.g., `REDprelauncher.exe` → `bin\x64\Cyberpunk2077.exe`, or Unreal `<install_dir>\Game\Binaries\Win64\Game-Win64-Shipping.exe`) and *other* games in the library whose real `.exe` is in a subdirectory are NOT in `known_exes`.
   **Observed PoC Output:**
   ```text
   === [MOD-03] Running-game lock bypasses ===
   3A Subdir exe CyberGame.exe running -> mod deployed anyway: True
   ```
2. **Xbox / UWP `package_id` targets missed:** `library.list_target_basenames()` (`library.py:255`) filters `WHERE kind = 'exe_path'`. Xbox games use `kind = 'package_id'`, so during `SessionWatcher`'s 3-second poll lag (`POLL_INTERVAL_SEC = 3.0`) or during startup `recover_incomplete()` (which runs at `app.py:783` *before* `watcher.start()` at `app.py:849`), running Xbox games are completely invisible to `_assert_no_game_running()`.
3. **Anti-cheat services not checked:** `_assert_no_game_running()` checks only `ToolhelpProcessScanner`, not `WindowsServiceProbe` for active `EasyAntiCheat`/`EasyAntiCheat_EOS`/`BEService`/`vgc` services.
4. **Multi-second TOCTOU & Qt Main-Thread Freeze Blocking `ProtectionGuard`:**
   - `import_zip()` checks `_assert_no_game_running()` ONCE at line 318, then extracts & hashes up to 512 MB twice (`validate_zip_manifest` + `extract_verified_package`), backs up original game files with `fsync`, and deploys files — **without ever re-checking `_assert_no_game_running()` before or during `_reconcile_game()`!**
   - Worse, `_wire_mods` (`app.py:1043-1091`) executes `import_zip`, `set_enabled`, `remove_item`, and `restore_original` **synchronously on the Qt GUI main thread**. While a large pack is extracting/copying for several seconds:
     - `EventBus` cannot deliver `GameStarted` to `window._tracked_games`.
     - `ProtectionGuard`'s background thread emits `guard_bridge.triggered` via `Qt.ConnectionType.QueuedConnection` (`app.py:598`), which sits stalled in the frozen Qt event queue until `import_zip()` finishes writing files — breaking the `<300ms` Zero-Presence emergency exit guarantee!

#### Recommended Fix
1. Walk `install_dir` recursively (bounded depth 4, symlink-safe) when collecting `.exe` basenames for `target_game` (and cache/collect for other installed library games), check active `ServiceProbe` anti-cheat services, and query `LaunchCoordinator` pending launches.
2. Re-check `_assert_no_game_running(game)` immediately before `_reconcile_game` mutates `install_dir` AND before each file replacement/unlink inside `_reconcile_game`.
3. Move `ModsEngine` archive extraction and disk reconciliation off the Qt main thread onto a dedicated single-threaded worker (`ThreadPoolExecutor(max_workers=1)`) with a cancellation flag checked between chunks/files so `ProtectionGuard`'s `_emergency_shutdown` can execute immediately on the main thread and abort any in-flight mod I/O.

---

### [MOD-04] HIGH — Unverified Write-Before-Verify, Untrusted DB Paths (`storage_dir` / `backup_path`), & Move Data Folder Breakage

- **Boundary:** Filesystem Integrity & Storage Containment
- **Locations:**
  - `gamehub/modules/mods/engine.py:496-502` (restore copies `backup.backup_path` to `target` *before* verifying `orig_sha256`, with zero containment/reparse check)
  - `gamehub/modules/mods/engine.py:527-532` (deploy copies `winner_item.storage_dir` to `target` *before* verifying `expected_sha`, with zero containment/reparse check)
  - `gamehub/modules/mods/engine.py:394-398` (`remove_item` runs `shutil.rmtree(pkg_dir)` if `is_relative_to(data_root/mods/packages)` — which is `True` for the root `packages/` folder itself!)
  - `gamehub/core/storage/location.py:152-175,375-393` (`migrate_legacy_data_root` and `StoreLocation.move` copy `mods/` + `gamehub.db` without updating stored absolute `storage_dir`/`backup_path` columns, and fail-cleanup at line 386 forgets `dest / "mods"`)

#### Attack Vectors & Verified Reproduction
1. **Write-Before-Verify on Both Restore and Deploy:** `_atomic_copy_file(src, dst)` (`engine.py:52-71`) executes `tmp.replace(dst)` **before** returning the SHA-256 digest. `_reconcile_game` only compares `restored_sha != backup.orig_sha256` (line 501) and `actual_sha != expected_sha` (line 531) **after** the unverified/corrupted file has already overwritten the game file on disk!
2. **Untrusted `backup_path` & `storage_dir` in SQLite:**
   - Neither `backup.backup_path` (line 497) nor `winner_item.storage_dir` (line 527) is validated for containment inside `self._data_root / "mods"` or checked for symlinks/junctions.
   - In `remove_item()` (line 395), `pkg_dir.resolve().is_relative_to((self._data_root / "mods" / "packages").resolve())` evaluates to **`True`** when `storage_dir` equals `data_root/mods/packages` or `data_root/mods/packages/<game_id>`, causing `shutil.rmtree(pkg_dir)` to wipe **all stored mod packages for all games**!
3. **`StoreLocation.move()` Permanently Breaks Original Restores:** Because `mod_items.storage_dir` and `mod_backups.backup_path` persist absolute filesystem paths, moving the data folder in Settings and cleaning up the old folder leaves every `backup_path` and `storage_dir` pointing at the deleted old folder, breaking `restore_original()`, `set_enabled()`, and `remove_item()`.

**Observed PoC Output:**
```text
=== [MOD-04] Write-before-verify, storage_dir/backup_path tampering, Move Data Folder ===
4A restore_original raised: Backup checksum mismatch while restoring 'data.cfg'.
4A Game file on disk AFTER checksum mismatch error: b'CORRUPTED_BACKUP'
4B set_enabled raised: Deployed file checksum mismatch for 'data.cfg'.
4B Game file on disk AFTER deploy checksum mismatch: b'TAMPERED_PACKAGE'
4C StoreLocation.move ok=True diag=None
4C restore_original AFTER Move Data Folder FAILED: Original backup file is missing for 'data.cfg'.
4D Game1 package exists before Game2 remove: True
4D Game1 package exists AFTER Game2 remove: False
```

#### Recommended Fix
1. Add `expected_sha256: str | None = None` to `_atomic_copy_file()`: verify `digest.hexdigest() == expected_sha256` **before** `tmp.replace(dst)`; on mismatch, unlink `tmp` and raise `ModFilesystemError` so `dst` is never touched.
2. Never trust absolute `storage_dir` or `backup_path` strings from SQLite: derive canonical paths dynamically from `self._data_root / "mods" / "packages" / game_id / item_id` and `self._data_root / "mods" / "backups" / game_id / ...` (or store relative POSIX paths strictly validated against `self._data_root / "mods"` with `_ensure_no_reparse_in_chain`).
3. In `remove_item()`, delete ONLY the exact derived `self._package_storage_dir(game_id, item_id)` after verifying it is not a reparse point and is strictly a child of `packages / game_id`.
4. Add `dest / "mods"` to the rollback cleanup tuple in `location.py:386`.

---

### [MOD-05] HIGH — Missing Dangerous Executable / Mod-Loader Extensions & Zero PE Header Inspection

- **Boundary:** Declarative-Only Pack Safety ("Zero scripts, commands, hooks, or executable payloads allowed")
- **Locations:**
  - `gamehub/modules/mods/manifest.py:60-95` (`FORBIDDEN_EXTENSIONS`)
  - `gamehub/modules/mods/manifest.py:145-150` (`_assert_safe_extension`)
  - `gamehub/modules/mods/manifest.py:313-335,358-368` (no magic-byte inspection)

#### Attack Vector & Verified Reproduction
`FORBIDDEN_EXTENSIONS` blocks 33 extensions (`.exe`, `.dll`, `.bat`, `.ps1`, `.py`, etc.), but omits **critical game-mod native code extensions** and **Windows executable/shell-handler extensions**, and performs zero binary header (PE `MZ`) inspection:
- **Game-mod native DLL/code loaders:** `.asi` (Win32 PE DLL auto-loaded by Ultimate ASI Loader / ScriptHook in GTA, Mafia, RE, etc.), `.pyd` (Python C-extension PE DLL), `.pyc`/`.pyo` (compiled Python bytecode), `.flt`/`.m3d`/`.mix` (Miles Sound System auto-loaded DLL plugins), `.so`/`.dylib`/`.node`.
- **Windows execution / shell / MotW-bypass extensions:** `.jar`, `.jnlp`, `.chm`, `.msc`, `.ws`, `.wsc`, `.sct`, `.scf` (auto-triggers SMB/NTLM auth when viewed in Explorer), `.appx`, `.msix`, `.appxbundle`, `.msixbundle`, `.appinstaller`, `.iso`, `.img`, `.vhd`, `.vhdx`, `.cab`, `.diagcab`, `.ps1xml`, `.ps2`, `.psc1`, `.psc2`, `.msh`, `.msh1`, `.msh2`, `.cdxml`, `.vb`, `.vba`, `.mjs`, `.cjs`, `.library-ms`, `.searchConnector-ms`, `.settingcontent-ms`, `.website`, `.xll`, `.xlam`, `.docm`, `.xlsm`, `.pptm`, `.hlp`, `.ins`, `.isp`, `.job`, `.shs`, `.shb`, `.gadget`.

**Observed PoC Output (every payload started with a valid Win32 PE `MZ\x90\x00` header):**
```text
=== [MOD-05] Missing dangerous extensions & PE header check ===
Accepted dangerous extensions (17/17): ['hook.asi', 'native.pyd', 'bytecode.pyc', 'loader.flt',
'app.jar', 'help.chm', 'snapin.msc', 'scriptlet.wsc', 'scriptlet.sct', 'ntlm.scf', 'pkg.msix',
'pkg.appx', 'disk.iso', 'disk.vhd', 'archive.cab', 'ps.ps1xml', 'shell.library-ms']
```

#### Impact
A malicious "translation" or "HUD mod" `.zip` can silently deploy native Win32 code (`.asi`, `.pyd`, `.flt`), compiled bytecode (`.pyc`), or Windows shell/NTLM/installer payloads (`.scf`, `.msix`, `.chm`, `.jar`, `.iso`) into a game folder, violating GameRewind's declarative-only safety guarantee.

#### Recommended Fix
1. Expand `FORBIDDEN_EXTENSIONS` to include all missing game-mod native/bytecode extensions and Windows dangerous/shell/archive-container extensions listed above (or consider an explicit allowlist mode for translation packs: `.txt`, `.cfg`, `.ini`, `.json`, `.xml`, `.csv`, `.loc`, `.pak`, `.font`, `.ttf`, `.otf`, `.png`, `.dds`, `.tga`, `.wav`, `.ogg`, etc.).
2. Inspect the first 4 bytes of every extracted member (and reject PE `b"MZ"` headers with a valid `PE\x00\x00` signature at `e_lfanew`, ELF `b"\x7fELF"`, Mach-O, and Windows shortcut `LNK` magic `b"\x4c\x00\x00\x00\x01\x14\x02\x00"` regardless of filename extension).

---

### [MOD-06] HIGH — Zip Amplification Bomb (3.2 KB → 128 GB+) & Unhandled `RecursionError` Crash

- **Boundary:** Archive Validation & Resource Exhaustion / Availability
- **Locations:**
  - `gamehub/modules/mods/manifest.py:153-164` (`_assert_no_forbidden_keys` unbounded recursion)
  - `gamehub/modules/mods/manifest.py:205-221` (`parse_manifest_dict` allows 500 `dest` entries pointing to the same `src`)
  - `gamehub/modules/mods/manifest.py:284-288` (`_inspect_zip_members` sums only unique ZIP member `info.file_size`, not total declared extraction bytes)
  - `gamehub/modules/mods/manifest.py:305-308` (`archive.read(manifest_info)` reads uncompressed stream without a streaming byte cap; in Python `zipfile`, `ZIP_LZMA`/`ZIP_BZIP2` decompress unbounded before slicing)
  - `gamehub/modules/mods/manifest.py:345-368` (`extract_verified_package` reopens `zip_path` with TOCTOU and enforces zero byte limits while writing to disk)
  - `gamehub/app.py:1047` (`_run_action` catches only `(ModError, OSError, StorageError)` — NOT `RecursionError`)

#### Attack Vectors & Verified Reproduction
1. **`src`-Reuse Extraction Amplification (256× bypass of `MAX_TOTAL_UNCOMPRESSED_BYTES`):**
   - A `.zip` contains a single compressible member `files/blob.bin` (256 MB of zeros → ~250 KB compressed) and `manifest.json` lists 500 distinct `dest` paths (`f0.bin`..`f499.bin`) all referencing `"src": "blob.bin"`.
   - `_inspect_zip_members` sums only ZIP members (`256 MB <= 512 MB`), passing validation.
   - `extract_verified_package` writes 500 copies = **128 GB** into `staging`, and `_reconcile_game` copies **another 128 GB** into `install_dir` (**256 GB** total disk exhaustion + minutes of UI freeze blocking `ProtectionGuard`).
   - Verified with a **3,278-byte** `.zip` declaring `300 × 2 MB = 600 MB > 512 MB`:
     ```text
     ACCEPTED! zip_size= 3278 declared_files= 300 total_extracted_bytes= 629145600 limit= 536870912
     ```
2. **Unhandled `RecursionError` Application Crash:**
   - A 10 KB `manifest.json` containing `{"a":` × 1500 + `1` + `}` × 1500 passes `MAX_MANIFEST_BYTES`, parses via `json.loads`, and crashes `_assert_no_forbidden_keys()` with `RecursionError`. Because `_run_action` (`app.py:1047`) only catches `(ModError, OSError, StorageError)`, importing this `.zip` crashes the entire GameRewind process!
   - **Observed PoC Output:**
     ```text
     6A Deep JSON raised RecursionError (is ModError? False)
     ```

#### Recommended Fix
1. Track cumulative **actual decompressed bytes** (`total_extracted_bytes`) across ALL `manifest.files` entries during both `validate_zip_manifest()` and `extract_verified_package()`, enforcing `total_extracted_bytes <= MAX_TOTAL_UNCOMPRESSED_BYTES` and `read_bytes <= MAX_SINGLE_FILE_BYTES` inside the streaming read loop. Reject duplicate `src` reuse (or count each output copy against `MAX_TOTAL_UNCOMPRESSED_BYTES`).
2. Only allow `ZIP_STORED` and `ZIP_DEFLATED` compression methods (reject `ZIP_BZIP2`/`ZIP_LZMA`), and read `manifest.json` via `archive.open(manifest_info).read(MAX_MANIFEST_BYTES + 1)` instead of `archive.read()`.
3. Replace recursive `_assert_no_forbidden_keys` with an iterative stack walk with an explicit max depth (e.g., 16) and catch `RecursionError` as `ManifestValidationError`.
4. Validate and extract from a **single opened `ZipFile` handle** inside `extract_verified_package()` to eliminate the validate-then-reopen TOCTOU.

---

### [MOD-07] MEDIUM — Windows Path Validation Gaps in `normalize_rel_path` & Case-Sensitive ZIP Member Map

- **Boundary:** Path Traversal & Windows Filesystem Safety
- **Locations:**
  - `gamehub/modules/mods/manifest.py:97-143` (`WINDOWS_RESERVED_NAMES`, `normalize_rel_path`)
  - `gamehub/modules/mods/manifest.py:273-292` (`_inspect_zip_members` case-sensitive `by_name`)
  - `gamehub/modules/mods/manifest.py:350-356` (no file/directory prefix collision check)

#### Attack Vector & Verified Reproduction
Unlike `gamehub/core/library/paths.py:13-25`, `manifest.py`'s `normalize_rel_path()` omits several Windows-specific path hazards:
1. **Reserved device bypasses:** Accepts `CONIN$.txt`, `CONOUT$.cfg`, space-before-dot devices (`CON .txt`, `NUL .cfg` — `part.split(".", 1)[0]` does not `.rstrip(" ")`), and Unicode superscript DOS devices (`COM¹.txt`, `LPT².cfg`). While `_safe_game_target` later rejects these via `local_path()`, `validate_zip_manifest()` and `extract_verified_package()` do NOT call `local_path()` and attempt to open/create these paths inside `staging_dir`.
2. **Windows illegal & control characters:** Accepts `< > " | ? *`, control characters (`\x01`–`\x1f`, `\t`, `\n`), and Unicode BiDi override characters (`\u202e` RLO, enabling visual filename/extension spoofing in UI conflict details).
3. **Silent outer whitespace stripping:** `raw.replace("\\", "/").strip()` silently normalizes `"  leading/trailing.txt  "` instead of rejecting invalid trailing spaces.
4. **Unbounded path length / depth:** Accepts >260-char paths (`"a"*300 + ".txt"`), causing `OSError` failures during extraction or `_atomic_copy_file` (+40 chars for `.{name}.{uuid}.grtmp`).
5. **Case-sensitive ZIP member collision & file/dir prefix collision:** `_inspect_zip_members` uses case-sensitive `norm in by_name` (allowing both `manifest.json` and `MANIFEST.JSON`, or `files/a.txt` and `files/A.TXT`), and `parse_manifest_dict` allows declaring both `"a"` and `"a/b.txt"` as `dest` targets (causing `FileExistsError` mid-extract).

**Observed PoC Output:**
```text
=== [MOD-07] normalize_rel_path gaps ===
  ACCEPTED 'CONIN$.txt' -> 'CONIN$.txt'
  ACCEPTED 'CONOUT$.cfg' -> 'CONOUT$.cfg'
  ACCEPTED 'CON .txt' -> 'CON .txt'
  ACCEPTED 'NUL .cfg' -> 'NUL .cfg'
  ACCEPTED 'COM¹.txt' -> 'COM¹.txt'
  ACCEPTED 'LPT².cfg' -> 'LPT².cfg'
  ACCEPTED 'sub/bad*name?.txt' -> 'sub/bad*name?.txt'
  ACCEPTED 'sub/bad"pipe|lt<.txt' -> 'sub/bad"pipe|lt<.txt'
  ACCEPTED 'sub/ctrl\tchar.txt' -> 'sub/ctrl\tchar.txt'
  ACCEPTED 'sub/line\nbreak.txt' -> 'sub/line\nbreak.txt'
  ACCEPTED 'sub/file\u202eexe.txt' -> 'sub/file\u202eexe.txt'
  ACCEPTED 'aaaa...aaaa.txt' (304 chars)
  ACCEPTED '  leading/trailing.txt  ' -> 'leading/trailing.txt'
```

#### Recommended Fix
1. Reuse `_is_safe_component()` from `gamehub.core.library.paths` (adding BiDi control rejection `U+202A–U+202E`, `U+2066–U+2069`, `U+200E–U+200F`, and `U+061C`), reject leading/trailing whitespace instead of stripping, and enforce max relative path length (e.g., `<= 180` chars) and max segment depth (e.g., `<= 16`).
2. Check casefolded duplicate ZIP member names in `_inspect_zip_members()` and reject parent/child prefix collisions across `manifest.files` (`"a"` vs `"a/b.txt"`).

---

### [MOD-08] MEDIUM — Crash-Safe Journal & Recovery Defects (Orphaned Files, Unjournaled Windows, Premature Rollback, Stale Backups)

- **Boundary:** Crash-Safe Journal & Transactional Recovery
- **Locations:**
  - `gamehub/modules/mods/engine.py:329-343` (`import_zip` runs `shutil.rmtree(final_dir)` + `shutil.move` + `upsert_item` *before* `begin_journal`)
  - `gamehub/modules/mods/engine.py:354-355,379-380,391-392,406-407` (all SQLite mutations occur *before* `begin_journal`)
  - `gamehub/modules/mods/engine.py:417-437` (`recover_incomplete` `seen_games` bug & protected-game skip & no `.grtmp`/staging GC)
  - `gamehub/modules/mods/engine.py:487-492` (`if not desired:` guard leaves crashed mid-deploy files orphaned when another mod is enabled)
  - `gamehub/modules/mods/engine.py:530-538` (`set_deployed_file` runs *after* `tmp.replace(target)`)
  - `gamehub/modules/mods/engine.py:460` (stale `mod_backups` never pruned after clean restore/removal)

#### Attack Vectors & Verified Reproduction
1. **Unjournaled DB/Filesystem Mutation Window:** Every operation (`import_zip`, `set_enabled`, `choose_conflict_winner`, `remove_item`, `restore_original`) commits DB state changes *before* `_reconcile_game()` inserts an `'in_progress'` journal row. Worse, re-importing an existing `package_id` executes `shutil.rmtree(final_dir)` + `shutil.move(staging_dir, final_dir)` *before* `upsert_item()` and outside any journal: a crash between `rmtree` and `upsert_item` destroys v1's stored package files (or replaces them with v2 files while DB still expects v1 SHA-256 hashes), leaving zero incomplete journals for `recover_incomplete()`.
2. **Orphaned Mid-Deploy Files When Another Mod Is Active:** `_reconcile_game()` writes `target` to disk (line 530) *before* inserting into `mod_deployed_files` (line 533). If a crash/exception happens between lines 530 and 533 for Mod A's `f2.txt`, while Mod B (`f3.txt`) is also enabled, then disabling/removing Mod A sees `desired` is non-empty (`{"f3.txt"}`), so `if not desired:` (line 488) is `False`. `f2.txt` is in `backups` (`existed=False`) but not in `deployed` — **`f2.txt` remains permanently orphaned in `install_dir`!**
3. **Premature Closing of Secondary Journals on Deferred Recovery:** In `recover_incomplete()` (`engine.py:417-421`), `seen_games.add(entry.game_id)` runs *before* the `try:` block. If a game has two incomplete journals (`j1`, `j2`) and recovery is deferred (e.g., game is currently running), `j2` is unconditionally marked `"rolled_back"` even though recovery failed!
4. **No Rollback on Failed `import_zip` & No Cleanup of `.grtmp` / `mods/staging/*`:** If `_reconcile_game` raises mid-import (e.g., locked file or junction on file #2 of 5), file #1 remains deployed, the broken mod stays `enabled=1`, the journal stays `in_progress`, and on next startup `recover_incomplete()` rolls *forward* into the broken state while labeling the journal `"rolled_back"`. Hard crashes also leak `.grtmp` files in `install_dir`/`backups` and up to 512 MB directories in `data_root/mods/staging/` indefinitely.
5. **Stale Backups Downgrade Patched Games:** `mod_backups` rows are never cleared when all mods are removed/restored; if a game updates via Steam/GOG and the user later enables and restores a mod, `if rel_path in backups: continue` skips backing up the patched game file and restores the outdated pre-patch backup.

**Observed PoC Output:**
```text
=== [MOD-08] Journal & recovery gaps ===
8A f2.txt orphaned in install_dir after disabling Mod A (Mod B active): True
8B Remaining incomplete journals after deferred recovery: ['j1'] (j2 was silently closed!)
```

#### Recommended Fix
1. Wrap the DB intent update AND `begin_journal()` in a **single atomic SQLite transaction** before touching the filesystem.
2. For package re-imports, stage to a new versioned directory (`packages/<game_id>/<item_id>_<rev>`) and only remove the previous directory *after* `upsert_item` + `_reconcile_game` commit.
3. Record a `"pending"` deployed entry (or write-ahead path list in `mod_deployed_files`) **before** calling `_atomic_copy_file(src_file, target)` so any interrupted deploy is always tracked in `deployed` even when other mods remain active.
4. In `recover_incomplete()`, only mark duplicate journals for `entry.game_id` as finished *after* recovery for that game actually succeeds; clean up orphaned `mods/staging/*` directories and `*.grtmp` files; and prune `mod_backups` once a game is cleanly restored with zero enabled items (verifying current on-disk SHA-256 matches `orig_sha256` before pruning).

---

### [MOD-09] MEDIUM — Reparse/Junction Bypass on `backups/`, `install_dir` Overlapping `data_root`, & Override Catalog Stripping Protection

- **Boundary:** Filesystem Containment & Protection Catalog Integrity
- **Locations:**
  - `gamehub/modules/mods/engine.py:217-224` (`_backup_file_path` lacks `_ensure_no_reparse_in_chain` / `local_path`)
  - `gamehub/modules/mods/engine.py:192-201` (`_validated_install_dir` permits `install_dir` to equal/overlap `data_root`, drive roots, or system folders)
  - `gamehub/core/protection/catalog.py:323-333` (`ProtectedGamesCatalog.load` replaces bundled entries wholesale with `by_id[entry.id] = entry`)

#### Attack Vectors & Verified Reproduction
1. **NTFS Junction in `backups/` Bypasses Containment:** `_backup_file_path()` checks `path.resolve().is_relative_to(backups_root.resolve())`. If `data_root/mods/backups/<game_id>` is a directory junction pointing to `C:\Outside`, **both** `path.resolve()` and `backups_root.resolve()` resolve through the junction to `C:\Outside`, so `is_relative_to()` returns **`True`** and backups are written outside `data_root`!
2. **`install_dir` Overlapping `data_root` / System Folders:** Adding any `.exe` located in `data_root` (or `C:\`, `C:\Windows`, `%LOCALAPPDATA%`) sets `install_dir` to that folder. A mod `.zip` can then legally deploy `protected_games_override.json` (or `store-location.json` / `gamehub.db`) directly into GameRewind's own `data_root`!
3. **Override Catalog Strips Bundled Protection:** `ProtectedGamesCatalog.load()` executes `by_id[entry.id] = entry` for `protected_games_override.json`. A 100-byte override file redefining `"id": "fortnite"` with empty `epic_app_names: []` and `game_exes: []` completely erases Fortnite from the catalog for both `ProtectionGuard` and `ModsEngine`!

**Observed PoC Output:**
```text
=== [MOD-09] Junction in backups/ & install_dir == data_root ===
9A Backup written OUTSIDE data_root via junction: True
9B Mod overwrote data_root/protected_games_override.json: True
10 Catalog match for Epic Fortnite after override: None
```

#### Recommended Fix
1. Enforce `local_path()` + `_ensure_no_reparse_in_chain(self._data_root, ...)` on `backups/`, `packages/`, and `staging/` paths (checking from `self._data_root` downward, not from `backups_root`).
2. In `_validated_install_dir()`, reject any `install_dir` that overlaps `self._data_root` (in either direction: `is_relative_to`), is a drive root (`len(path.parts) <= 1`), or is/contains `%SystemRoot%`, `%ProgramFiles%` root, `%ProgramFiles(x86)%` root, `%LOCALAPPDATA%`, or `%USERPROFILE%` root.
3. Make `protected_games_override.json` **strictly additive** in `ProtectedGamesCatalog.load()`: when `entry.id` already exists in bundled `by_id`, union its IDs/exes and never allow downgrading `default_mode` from `"strict"` or removing bundled identifiers.

---

### [MOD-10] LOW — Stale Mods UI on Settings Policy Change, Hidden Lock Controls, & Missing Engine Mutex

- **Boundary:** UI Security Hygiene & Concurrency Safety
- **Locations:**
  - `gamehub/app.py:843-847` (`on_guard_policy_changed` omits `refresh_mods_ui()`)
  - `gamehub/ui/mods_view.py:194-200` (`present_state` hides `_normal_box` without disabling/clearing hidden action widgets)
  - `gamehub/modules/mods/engine.py:110-128` (`ModsEngine` has no per-game `threading.Lock`)

#### Details & Evidence
1. Changing a game's protection mode in **Settings → Protected Games** (or clicking **Reset to defaults**) invokes `on_guard_policy_changed` (`app.py:843-847`), which refreshes `ProtectionGuard`, `SessionWatcher`, and `LibraryView`, but **does not call `refresh_mods_ui()`** (unlike `_wire_game_page` at `app.py:799`). `ModsView` and `GamePage.mods_panel` retain stale lock/unlock UI state until manually re-navigated (engine-level checks still block mutations).
2. When `state.protected` is `True`, `GameModsWidget.present_state()` hides `_normal_box` without clearing `_items_layout`/`_conflicts_layout` or disabling `_import_btn`/`_restore_btn`.
3. `ModsEngine` lacks an internal lock serializing mutating operations per `game_id` (important both for nested Qt event loops during `QMessageBox`/`QFileDialog` and once I/O is moved off the main thread per `MOD-03`).

#### Recommended Fix
1. Call `refresh_mods_ui()` inside `on_guard_policy_changed` (`app.py:843-847`).
2. In `GameModsWidget.present_state()`, disable `_import_btn`/`_restore_btn` and clear `_items_layout`/`_conflicts_layout` when `state.protected` is `True`.
3. Add a `threading.RLock` (or per-`game_id` lock) around mutating methods in `ModsEngine`.

---

## Positive Controls Verified

The following security properties were tested and confirmed working as designed:
- **Catalog-matched games with `protection_mode="full"` override:** When a game *is* matched by `catalog.match_game()` (e.g., Epic Fortnite or Steam CS2), switching `protection_mode="full"` does **not** unlock it in `ModsEngine` (`engine.py:134-135` returns `True` before consulting `protection_mode`).
- **Basic path traversal & ADS:** `../`, `..\`, `/abs`, `C:/foo`, `file.txt:stream`, null bytes, and `.` / `..` segments are properly rejected by `normalize_rel_path()`.
- **Encrypted ZIPs & Unix ZIP symlinks:** Encrypted entries (`flag_bits & 0x1`) and Unix symlink modes (`stat.S_ISLNK`) are rejected in `_inspect_zip_members()`.
- **NTFS junctions inside `install_dir`:** `_safe_game_target()` + `_ensure_no_reparse_in_chain()` + `local_path()` reject junctions/symlinks inside `install_dir`.
- **SQLite parameterization & PlainText UI labels:** All queries in `repository.py` are parameterized, and `mods_view.py` consistently sets `Qt.TextFormat.PlainText` on dynamic labels to prevent Qt RichText/HTML injection.
- **Forbidden manifest keys:** Top-level and nested command/hook/script keys (`post_install`, `cmd`, `powershell`, etc.) are rejected for normal-depth manifests.

---

## Verdict

**FAIL** — **10 open findings** (`MOD-01`, `MOD-02`, `MOD-03`, `MOD-04`, `MOD-05`, `MOD-06`, `MOD-07`, `MOD-08`, `MOD-09`, `MOD-10`: 2 CRITICAL, 4 HIGH, 3 MEDIUM, 1 LOW).

The Translations & Mods module should **not** ship to users until at least all CRITICAL and HIGH findings (`MOD-01`–`MOD-06`) — and the path/journal/containment MEDIUM findings (`MOD-07`–`MOD-09`) — are remediated and covered by regression tests.


---

## Round 2 Re-Audit Verification

- **Date:** 2026-11-24
- **Auditor:** Independent Red-Team Security Auditor (Read-only code review + live adversarial PoC verification on Windows Python 3.12)
- **Test Baseline:** `.venv\Scripts\python.exe -m pytest tests/test_mods.py tests/test_security_hardening.py -v` — **13/13 passed** (`3.09s`).
- **Scope Verified:** `gamehub/modules/mods/manifest.py`, `gamehub/modules/mods/engine.py`, `gamehub/modules/mods/repository.py`, `gamehub/ui/mods_view.py`, `gamehub/app.py`, `gamehub/core/protection/catalog.py`, `gamehub/core/protection/protected_games.json`, `gamehub/core/storage/location.py`, `tests/test_mods.py`, `tests/test_security_hardening.py`.

### Per-Finding Round 2 Status Matrix

| ID | Round 1 Severity | Round 2 Severity | Round 2 Status | Summary of Verification |
|---|---|---|---|---|
| **MOD-01** | CRITICAL | — | **CLOSED** | Case-insensitive `.casefold()` conflict/desired/backup/deployed tracking + case-duplicate ZIP entry rejection verified live (`fonts.cfg` vs `Fonts.cfg`). |
| **MOD-02** | CRITICAL | — | **CLOSED** | Ubisoft R6 Siege, Battle.net OW2/WoW, Riot 2XKO, EA FC/BF/Apex, depth-4 `install_dir` exe scan, and overlapping protected `install_dir` siblings all stay locked even when `protection_mode='full'`. |
| **MOD-03** | HIGH | **MEDIUM** | **OPEN** | Depth-4 running exe scan, fail-closed SCM anti-cheat check, startup TOCTOU re-check, and per-file `_reconcile_game` re-checks all verified. **Remaining gap:** `_run_action` (`app.py:1145-1153`) still runs synchronous mod I/O on the Qt main thread, blocking `ProtectionGuard` `QueuedConnection` emergency exit (`589.5 ms` measured for a 64 MB pack; ~2.3–4.7 s for 256–512 MB). |
| **MOD-04** | HIGH | **LOW** | **OPEN** | Verify-before-replace SHA-256 in `_atomic_copy_file`, relative DB `storage_dir`/`backup_path` surviving `StoreLocation.move()` + old folder deletion, and cross-game `rmtree` block all verified. **Remaining gaps:** `remove_item()` (`engine.py:523`) allows tampered `storage_dir="packages/<game_id>"` (`validated == base`) to wipe all packages for that game; `location.py:386` rollback cleanup still omits `dest / "mods"`. |
| **MOD-05** | HIGH | **MEDIUM** | **OPEN** | All 17 Round 1 PoC extensions and standard PE headers (`e_lfanew < 4096`) are now blocked. **Remaining gaps:** `_is_pe_binary()` (`manifest.py:130-137, 391-392`) only inspects the first 4096 bytes — a valid PE binary with `e_lfanew = 4096` (`0x1000`) bypasses detection; 15 dangerous extensions from Round 1 (`.pyo`, `.m3d`, `.mix`, `.msixbundle`, `.appxbundle`, `.appinstaller`, `.diagcab`, `.mjs`, `.cjs`, `.vb`, `.vba`, `.xll`, `.xlsm`, `.docm`, `.img`) remain accepted. |
| **MOD-06** | HIGH | — | **CLOSED** | `src`-reuse amplification bomb blocked (`total_declared_bytes <= 512 MB`), iterative `_assert_no_forbidden_keys` + `RecursionError` catch verified at depth 500 & 1500, and bounded streaming `manifest.json` read (`MAX_MANIFEST_BYTES + 1`) verified. |
| **MOD-07** | MEDIUM | — | **CLOSED** | `CONIN$`, `CONOUT$`, `CON .txt`, `NUL .cfg`, `COM¹`, `LPT²`, `< > " \| ? *`, `\x00-\x1f`, BiDi overrides (`\u202a-\u202e`, `\u2066-\u2069`), `>240`-char paths, file/dir prefix collisions, and case-duplicate ZIP members all rejected. |
| **MOD-08** | MEDIUM | **MEDIUM** | **OPEN** | Deferred multi-journal preservation (`['j1', 'j2']`), orphaned-file recovery via `desired_paths` when another mod is active, and staging/`.grtmp` cleanup verified. **Remaining gaps (2 real bugs reproduced live):** (1) failed v1→v2 re-import rolls back `final_dir` to v1 while leaving v2 manifest committed in SQLite, wedging `recover_incomplete()` and growing stuck `'in_progress'` journals unboundedly on every startup (`engine.py:447-469`); (2) `_cleanup_staging_and_temps()` uses `os.walk(install_dir)` which traverses NTFS junctions on Windows Python 3.12 and deletes `.grtmp` files **outside** `install_dir` (`engine.py:544-554`). |
| **MOD-09** | MEDIUM | — | **CLOSED** | NTFS junction at `data_root/mods/backups/<game_id>` rejected by `local_path()` + `_ensure_no_reparse_in_chain()`, `install_dir` overlapping `data_root` (equal/child/parent) rejected, and `protected_games_override.json` strictly additive merge verified. |
| **MOD-10** | LOW | — | **CLOSED** | `on_guard_policy_changed` calls `refresh_mods_ui()` (`app.py:945, 1201`), `GameModsWidget.present_state(protected=True)` disables buttons & clears layouts (`mods_view.py:197-204`), and `ModsEngine._op_lock` guards all mutating methods (`engine.py:188, 431-558`). |

---

### Detailed Round 2 Evidence

#### Closed Findings (6/10)

- **[MOD-01 — CLOSED]**
  - `engine.py:335-400`, `engine.py:502-506`, `engine.py:623-624, 638-675, 710-736`: All conflict, desired-map, backup, and deployed tracking now keys by `.casefold()`. Step 3 deletes old case-variant rows in `mod_deployed_files` when casing changes (`engine.py:729-730`).
  - `manifest.py:348-351`: `_inspect_zip_members` rejects case-duplicate ZIP paths.
  - **Live verification:**
    ```text
    conflicts: 1 winner: c0326be7797047a5aad1fed3906b706f
    restored: b'ORIGINAL_FONT_DATA'
    OK dup_manifest.zip rejected: Archive contains case-duplicate path: 'MANIFEST.JSON'
    OK dup_file.zip rejected: Archive contains case-duplicate path: 'files/A.TXT'
    ```

- **[MOD-02 — CLOSED]**
  - `protected_games.json` + `catalog.py:474-490`: Added `ubisoft_ids` (`635`, `1843`), `battlenet_ids` (`pro`, `overwatch`, `wow`, `wow_classic`, `wow_classic_era`), `ea_ids`, and `2xko` (`riot_product_ids: ["lion", "2xko"]`).
  - `engine.py:125-154, 190-224`: `is_game_protected()` performs bounded depth-4 symlink-safe `_scan_dir_exes(game.install_dir)` and `_paths_overlap(game.install_dir, other.install_dir)` against all protected/strict library games regardless of `protection_mode='full'`.
  - **Live verification:**
    ```text
    Ubisoft R6 (full): (True, 'BattlEye / QB')
    BNet Overwatch 2 (full): (True, 'Blizzard Warden')
    BNet Overwatch 2 Slug (full): (True, 'Blizzard Warden')
    BNet World of Warcraft (full): (True, 'Blizzard Warden')
    Riot 2XKO (full): (True, 'Riot Vanguard')
    Sibling inside Fortnite (Epic full): (True, 'Easy Anti-Cheat / BattlEye')
    Deep depth-4 cs2.exe: (True, 'VAC / Trusted Mode')
    ```
  - *INFO Observation:* `_scan_dir_exes` (`engine.py:132-154`) uses LIFO DFS (`stack.pop()`) with `_MAX_SCANNED_ENTRIES = 2000`; switching to BFS (`collections.deque.popleft()`) would reduce the chance of exhausting 2000 entries inside deep asset folders before reaching `Binaries\Win64` on manually added Unreal games.

- **[MOD-06 — CLOSED]**
  - `manifest.py:186-207, 365-401`: Cumulative `total_declared_bytes` checked in the streaming read loop (`<= MAX_TOTAL_UNCOMPRESSED_BYTES`), `manifest.json` read via bounded `m_stream.read(MAX_MANIFEST_BYTES + 1)`, `_assert_no_forbidden_keys` rewritten iteratively (`visited > 50_000`), and `RecursionError` caught at `manifest.py:371`.
  - **Live verification:** `test_security_hardening.py` confirms 300 × 2 MB `src`-reuse bomb rejected; depth 500 & depth 1500 JSON both raise `ManifestValidationError`; 300 KB compressed `manifest.json` rejected.
  - *INFO Observation:* `extract_verified_package()` (`manifest.py:415-448`) still reopens `zip_path` after `validate_zip_manifest()` without repeating the `MAX_TOTAL_UNCOMPRESSED_BYTES` counter inside the extraction loop; validating and extracting from a single opened `ZipFile` handle would eliminate the narrow local file-swap TOCTOU.

- **[MOD-07 — CLOSED]**
  - `manifest.py:35-43, 140-175, 209-219, 280, 348-351`: All reserved device variants (`CONIN$`, `CONOUT$`, `CON .txt`, `NUL .cfg`, `COM¹`, `LPT²`), illegal/control/BiDi override chars (`\x00-\x1f<>:"|?*\u202a-\u202e\u2066-\u2069`), `>240`-char paths, case-insensitive file/dir prefix collisions, and case-duplicate ZIP members are rejected.
  - *INFO Observation:* `manifest.py:146` still `.strip()`s outer whitespace (`"  leading/trailing.txt  "` → `"leading/trailing.txt"`), though it is normalized consistently before ZIP lookup and disk writes so no trailing space is ever written to NTFS.

- **[MOD-09 — CLOSED]**
  - `engine.py:288-289, 303-329, 411`: `_resolve_mods_subpath()` enforces `local_path()` + `_ensure_no_reparse_in_chain(self._mods_root, validated)` on `backups/` and `packages/`, and `_validated_install_dir()` rejects `install_dir` overlapping `self._data_root` in any direction.
  - `catalog.py:306-336, 379-393`: `_merge_override_entry()` is strictly additive and cannot strip bundled protection or downgrade `default_mode` from `"strict"`.
  - **Live verification:**
    ```text
    OK 9A: backup junction rejected: Stored mod path escaped managed mods directory. outside files: []
    OK 9B (equal) rejected: Game install folder cannot overlap GameRewind's data folder.
    OK 9B (child) rejected: Game install folder cannot overlap GameRewind's data folder.
    OK 9B (parent) rejected: Game install folder cannot overlap GameRewind's data folder.
    OK 9C Fortnite after override: ProtectedGameEntry(id='fortnite', ...)
    ```
  - *INFO Observation:* `_validated_install_dir()` does not explicitly reject unrelated drive roots (`D:\`) or `%SystemRoot%` (`C:\Windows`) when `data_root` is on another path/drive.

- **[MOD-10 — CLOSED]**
  - `app.py:941-946, 1201`: `on_guard_policy_changed` invokes `refresh_mods_ui()`.
  - `mods_view.py:197-204`: Verified live in offscreen Qt (`import_btn enabled: False`, `restore_btn enabled: False`, `items_layout count: 0`, `conflicts_layout count: 0`, `lock_card hidden: False`, `normal_box hidden: True`).
  - `engine.py:188, 431, 472, 491, 511, 531, 558`: `self._op_lock = Lock()` serializes all mutating `ModsEngine` methods.

---

#### Remaining Open Findings (4/10)

##### [MOD-03] OPEN (Downgraded: HIGH → MEDIUM) — Synchronous Qt Main-Thread Mod Extraction Stalls `ProtectionGuard` Emergency Exit
- **Verified Fixed:** Depth-4 symlink-safe `install_dir` scanning (`engine.py:125-154, 246-247`), fail-closed SCM anti-cheat service check (`engine.py:268-277`), per-file `_assert_no_game_running()` re-checks before writes inside `_reconcile_game` (`engine.py:641, 678, 723`), and startup TOCTOU re-check before `recover_incomplete()` (`app.py:864-870`).
- **Remaining Defect (`gamehub/app.py:667-674, 1145-1153`):** `_run_action()` still executes `mods_engine.import_zip()` synchronously on the Qt GUI main thread while `guard_bridge.triggered` relies on `Qt.ConnectionType.QueuedConnection`.
- **Live Measurement:**
  ```text
  64 MB import_zip synchronous blocking duration: 589.5 ms
  ```
  A realistic 256–512 MB mod/texture `.zip` (within `MAX_TOTAL_UNCOMPRESSED_BYTES`) freezes the Qt event loop for ~2.3–4.7 seconds, delaying `ProtectionGuard`'s `_emergency_shutdown()` well past the `<250 ms` Zero-Presence budget if a protected game launches mid-import.
- **Recommended Fix:** Run `_run_action` mod I/O on a single-threaded background worker (`ThreadPoolExecutor(max_workers=1)`) with UI busy state + cancellation check between chunks/files, and/or trigger a non-blocking fail-safe `os._exit()` timer directly from `ProtectionGuard`'s background thread if the Qt main thread does not complete shutdown within 150 ms.

##### [MOD-04] OPEN (Downgraded: HIGH → LOW) — Same-Game `storage_dir` Self-Match Wipe & Missing `dest / "mods"` Move Rollback Cleanup
- **Verified Fixed:** `_atomic_copy_file()` verifies `expected_sha256` before `tmp.replace(dst)` on both restore (`engine.py:692`) and deploy (`engine.py:728`); relative `storage_dir` and `backup_path` under `data_root/mods` survive `StoreLocation.move()` + deletion of the old data root; cross-game `storage_dir = "packages"` is blocked.
- **Remaining Defects:**
  1. `gamehub/modules/mods/engine.py:314, 523-525`: `_resolve_mods_subpath(item.storage_dir, f"packages/{game_id}")` checks `validated.resolve().is_relative_to(base.resolve())`, which is `True` when `validated == base`. If a SQLite row has `storage_dir = "packages/<game_id>"`, `remove_item()` runs `shutil.rmtree(data_root/mods/packages/<game_id>)`, deleting **all** other mod packages for that game.
     ```text
     4E ADVERSARIAL same-game wipe (storage_dir='packages/<gid>'): other mod still exists? False
     ```
  2. `gamehub/core/storage/location.py:386`: Rollback cleanup tuple `(dest / "gamehub.db", dest / "media", dest / "logs")` still omits `dest / "mods"` (promoted at line 378), leaking `dest / "mods"` if `staged_db.replace` or `_write_bootstrap` fails.
- **Recommended Fix:** In `remove_item()`, delete only the exact derived path `self._resolve_mods_subpath(self._package_storage_rel(game_id, item.id), f"packages/{game_id}/{item.id}")` (and reject `validated.resolve() == base.resolve()` in `_resolve_mods_subpath` when `expected_prefix` is a parent directory); add `dest / "mods"` to the rollback cleanup tuple in `location.py:386`.

##### [MOD-05] OPEN (Downgraded: HIGH → MEDIUM) — PE Binary Header Bypass (`e_lfanew >= 4096`) & Remaining Dangerous Extensions
- **Verified Fixed:** All 17 Round 1 PoC extensions (`.asi`, `.pyd`, `.pyc`, `.flt`, `.jar`, `.chm`, `.msc`, `.wsc`, `.sct`, `.scf`, `.msix`, `.appx`, `.iso`, `.vhd`, `.cab`, `.ps1xml`, `.library-ms`) and PE binaries with `e_lfanew < 4096` are now rejected.
- **Remaining Defects:**
  1. **PE Check Bypass (`gamehub/modules/mods/manifest.py:130-137, 391-392, 438-439`):** `_is_pe_binary()` inspects only the first 4096 bytes (`header_buf`). Any valid Win32 PE executable/DLL (renamed e.g. `payload.dat` or `plugin.mix`) with a DOS stub specifying `e_lfanew = 4096` (`0x1000`) makes `pe_offset + 4 > len(header_buf)` and silently returns `False`.
  2. **Missing Dangerous Extensions (`gamehub/modules/mods/manifest.py:68-127`):** 15 dangerous extensions from Round 1 remain accepted:
     ```text
     5B ADVERSARIAL: PE with e_lfanew=4096 ACCEPTED!
     5C Extra extensions accepted: ['mod.pyo', 'pkg.msixbundle', 'pkg.appxbundle', 'pkg.appinstaller',
     'troub.diagcab', 's.mjs', 's.cjs', 's.vb', 's.vba', 'add.xll', 'sheet.xlsm', 'doc.docm',
     'disk.img', 'snd.m3d', 'snd.mix']
     ```
- **Recommended Fix:**
  1. In both `validate_zip_manifest()` and `extract_verified_package()`, if the stream begins with `b"MZ"` and has `len >= 64`, parse `pe_offset = struct.unpack_from("<I", header, 60)[0]` and inspect the 4 bytes at `pe_offset` dynamically during streaming (or reject any `MZ` file whose `pe_offset` is a valid PE header offset `>= 64` that exceeds `header_buf`).
  2. Add `.pyo`, `.m3d`, `.mix`, `.so`, `.dylib`, `.node`, `.msixbundle`, `.appxbundle`, `.appinstaller`, `.diagcab`, `.mjs`, `.cjs`, `.vb`, `.vba`, `.xll`, `.xlam`, `.docm`, `.xlsm`, `.pptm`, `.img`, `.website` to `FORBIDDEN_EXTENSIONS`.

##### [MOD-08] OPEN (MEDIUM) — Failed Mod Update DB/Disk Desync + Infinite Journal Growth & NTFS Junction Traversal in `.grtmp` Cleanup
- **Verified Fixed:** Deferred recovery preserves all incomplete journals for a game (`['j1', 'j2']`); orphaned mid-deploy files recorded in `mod_backups(existed=False)` are cleaned via `desired_paths` in `recover_incomplete()` even while another mod stays active; `mods/staging` and `install_dir/*.grtmp` are cleaned on recovery.
- **Remaining Defects (both reproduced live with zero DB tampering):**
  1. **Unrecoverable DB/Disk Desync on Failed Re-Import (`gamehub/modules/mods/engine.py:447-469`):** When updating an existing mod `package_id` (v1 → v2), `upsert_item()` commits v2's manifest to SQLite at line 451 before `_reconcile_game()` runs at line 458. If `_reconcile_game()` raises (e.g., `GameRunningModError` because a game started during extraction, or a locked-file `OSError`), `except BaseException:` (lines 464-468) restores `final_dir` on disk back to **v1**, while SQLite `mod_items` **still holds v2's manifest**. Every subsequent `recover_incomplete()` fails checksum/missing-file verification, leaves recovery deferred forever, and appends **another** stuck `'in_progress'` journal row on every launch:
     ```text
     8D recover_incomplete after failed v2 re-import: remaining journals= (
       JournalRecord(operation='import:pkg-u', status='in_progress', ...),
       JournalRecord(operation='recover:4967c21f...', status='in_progress', ...)
     ) disk= b'V1_BYTES'
     ```
  2. **NTFS Junction Traversal & Out-of-Tree File Deletion (`gamehub/modules/mods/engine.py:544-554`):** `_cleanup_staging_and_temps(install_dir)` calls `os.walk(install_dir)`. On Windows Python 3.12, `os.walk()` with default `followlinks=False` **follows NTFS directory junctions** (`entry.is_symlink()` is `False` for junctions), deleting matching `*.grtmp` files **outside** `install_dir`:
     ```text
     === MOD-08 os.walk NTFS junction test ===
     outside keep.grtmp still exists after _cleanup_staging_and_temps: False
     ```
- **Recommended Fix:**
  1. In `import_zip()`'s `except BaseException:` block (`engine.py:462-469`), restore SQLite `mod_items` to match the disk rollback: if `existing is not None`, re-upsert `existing`'s original manifest/storage_dir/enabled state; if `existing is None`, delete the newly inserted item row and remove `final_dir`. Also ensure `recover_incomplete()` marks any transient recovery journal `'rolled_back'` if recovery fails, rather than accumulating duplicate `'in_progress'` rows.
  2. Replace `os.walk(install_dir)` in `_cleanup_staging_and_temps()` with a bounded `os.scandir` stack walk that checks `_is_reparse(entry.stat(follow_symlinks=False))` (matching `_scan_dir_exes`), and verify `not _is_reparse(staging_root.lstat())` before `shutil.rmtree(staging_root)`.

---

### Round 2 Verdict

**FAIL** — **4 open findings** (`MOD-03` [MEDIUM], `MOD-04` [LOW], `MOD-05` [MEDIUM], `MOD-08` [MEDIUM]; **6 closed**: `MOD-01`, `MOD-02`, `MOD-06`, `MOD-07`, `MOD-09`, `MOD-10`; **0 CRITICAL, 0 HIGH** remaining).
