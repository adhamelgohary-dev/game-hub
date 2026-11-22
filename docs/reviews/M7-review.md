# M7 Settings and Arabic/English review

## Advocate

Settings expose all nine persisted preferences (language, capture interval, screenshot ring size, voice autoplay, close prompt, all three global hotkeys, Windows startup) plus current data-folder display, Explorer open, and verified offline relocation. Atomic batch hotkey rebinding preserves working shortcuts on Windows conflict and supports swapping shortcuts between actions. English and Arabic switch live with mirrored RTL layout, updated `QLocale`, full AST-verified catalog parity across all `.tr()` strings, and clean copyable LTR paths.

## Critic

An independent Critic audit raised six blockers on the initial implementation:

1. Arabic `QFileDialog` filters embedded invisible BiDi isolates (`\u2066`/`\u2069`) inside glob parentheses, hiding `.exe`, `.png`, and `.bmp` files in Arabic mode. Fixed by keeping glob parentheses plain ASCII and adding a `QDir.match` regression test.
2. Data-folder relocation ran synchronously on the Qt UI thread without pausing background workers or preventing post-move split-brain writes. Fixed by pausing `CaptureScheduler` and `SessionWatcher`, executing `StoreLocation.move()` off the UI thread, closing writers and disabling Settings writes into a restart-required state on success, and resuming cleanly on failure.
3. `StoreLocation` and `resolve_data_root` had symlink/TOCTOU gaps, used `Path.exists()` (silently skipping permission-denied files), and omitted `PRAGMA user_version` verification. Fixed with `lstat()` + reparse checks, bounded bootstrap reads, directory pinning via `media.protect_directory`, exclusive temp bootstrap writes, and `PRAGMA user_version == SCHEMA_VERSION` verification.
4. Sequential hotkey rebinding failed when swapping two shortcuts, and `Shift`-only letter/digit chords could hijack typing. Fixed with two-phase `GlobalHotkeys.rebind_batch()` and disallowing `Shift`-only alphanumeric chords.
5. `SingleInstance` used the moved `data_root` instead of `effective_default`, allowing a second concurrent instance after relocation. Fixed by anchoring `SingleInstance` on `effective_default`.
6. Hardcoded errors in `LibraryController` and `app.py` bypassed `.tr()`, `CatalogTranslator` returned `sourceText` instead of `""` on miss, `QLocale` stayed at OS default, and `GamePage.retranslate_ui()` omitted `_summary`. Fixed all four plus added `"Close"` to `AR_CATALOG`.

Minors addressed: removed invisible BiDi chars from copyable paths (using `LeftToRight` widget direction instead), added RTL arrow-key reversal on `LastTimeCard` and `LastMomentsDialog`, added `Escape` back-navigation on `SettingsView`, guarded `open_settings()` against `StorageError`, and expanded tests for swaps, SQLite rollback, mid-move rollback, and junction rejection.

## Neutral Analyst

All 167 automated tests and Ruff pass, including full AST key and placeholder parity across every `.tr()` call in `gamehub/`, `QDir.match` validation of Arabic file filters, real `RegisterHotKey` conflict preservation (`code=1409`), verified `StoreLocation` relocation and rollback, and live Arabic RTL rendering across Library, GamePage, Settings, and tray. Visual inspection across 100%/150%/200% Windows DPI and screen-reader traversal remain manual acceptance checks on the owner's machine.

## Judge

Initial verdict **APPROVE WITH CHANGES** for the six Critic blockers above. Re-review confirms all six blockers and the accompanying reliability, security, and accessibility fixes are implemented and covered by tests. All 167 tests, Ruff, native conflict/RTL/relocation checks, and source startup pass. Verify the tagged Windows release packages before closing the milestone.
