# Review Council — M20 (Simplified Translations & Mods)

**Date:** 2026-11-24  
**Scope:** SQLite Schema v7 (`mod_items`, `mod_backups`, `mod_deployed_files`, `mod_conflict_choices`, `mod_journal`), declarative-only `.zip` / `manifest.json` validator, crash-safe write-ahead journaled backup/deploy/remove/restore engine (`gamehub/modules/mods/`), sample pack generator, sidebar `Translations & Mods` view + per-game `GamePage` tab, Arabic RTL translations, and `tests/test_mods.py`.

## Advocate
- Delivers the exact simplified, jargon-free UX the owner asked for: no profile chips, no priority numbers, no raw file paths unless the user clicks **Details**.
- Every single-player game gets automatic original-file backups (`"Original game files are backed up ✓"`), per-item On/Off switches + Remove buttons, a big clear **"Restore the original game"** button, and plain-language two-button conflict resolution.
- Hard-blocks protected/online games at both UI and core engine levels (even if the user manually changed `protection_mode` to `full` in Settings), hard-blocks any filesystem change while ANY game is running (via active session tracking AND live Toolhelp32 process scan), and rejects scripts/executables/path traversal/zip symlinks/junctions.
- Crash-safe `mod_journal` replays and recovers interrupted operations automatically on startup.

## Critic
- **Red-Team verification pending:** Agent H in M21 will independently try to break path containment, zip-slip, case-insensitive Windows collisions, junction/symlink attacks, protected-game overrides, and running-game races against `gamehub/modules/mods/`.
- **All 218 tests & `ruff check .` pass** cleanly, including AST i18n parity, RTL rendering, journal crash recovery, and protected-game lock verification.

## Neutral Analyst
- Schema v6 → v7 migration is additive with automatic `gamehub.db-v6.bak` backup, and `StoreLocation.move()` copies `mods/` backups/packages safely when users move their data folder.
- All user-visible labels follow plain EN and AR (RTL) phrasing with clean ampersand handling (`Translations & Mods` / `التعريبات والمودات`).

## Judge Verdict
**APPROVED** — Commit, tag `m20`, push to `origin`, and immediately launch **M21 (Independent 8-Agent Red-Team Security Re-Audit)**.
