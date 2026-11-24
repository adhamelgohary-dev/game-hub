# Translations & Mods Module — Simplified Design Specification (Owner Approved)

**Status:** Approved & Simplified for `M20` implementation (`v1.2.0-rc.2`).  
**Date:** 2026-11-24  
**Scope:** Part 6 of GameRewind v1.2 — simple, jargon-free, crash-safe manager for single-player game Arabic translations (تعريبات) and mods.

---

## 1. Safety & Legal Hard Rules (Non-Negotiable)

1. **Strictly IMPOSSIBLE on protected / online games:**
   - Any game matched by `protected_games.json` (by source/ID or executable basename) **OR** currently in `strict` mode is **permanently locked** for Translations & Mods — even if the user manually toggles protection mode in Settings!
   - Both the UI and the core `ModsEngine` enforce this hard gate (`ProtectedGameModError`).
   - Friendly lock message (no jargon, no actionable buttons):
     - EN: *"Mods and translations are turned off for online games to protect your account."*
     - AR: *"المودات والتعريبات مقفولة للألعاب الأونلاين علشان نحمي حسابك."*
2. **Never modify files while ANY game is running:**
   - Before every filesystem mutation (`import`, `set_enabled`, `resolve_conflict`, `remove`, `restore_original`), `ModsEngine` checks BOTH:
     - Active session state (`has_running_games()`), AND
     - A live passive `ToolhelpProcessScanner` scan against all known game executables in the library and protected catalog.
   - If ANY game is running, the operation is rejected (`GameRunningModError`) with a plain message (*"Close your running game before changing translations or mods."*).
3. **Never redistribute original game files:**
   - Packages contain **only changed or added files** (never original copyrighted game assets or executables).
   - Every original file that would be overwritten is backed up locally under `<data_root>/mods/backups/<game_id>/` with its SHA-256 hash recorded in SQLite (`mod_backups`) BEFORE the game folder is touched.
4. **Declarative-only manifest (zero scripts or executables):**
   - `manifest.json` supports ONLY declarative `files` entries (`src` → `dest`, `sha256`).
   - The validator strictly rejects:
     - Any script/command keys (`scripts`, `commands`, `hooks`, `pre_install`, `post_install`, `run`, `exec`, `shell`, `steps`).
     - Any executable or script file extensions in `src` or `dest` (`.exe`, `.dll`, `.sys`, `.bat`, `.cmd`, `.ps1`, `.vbs`, `.vbe`, `.js`, `.jse`, `.wsf`, `.wsh`, `.msi`, `.msp`, `.com`, `.scr`, `.pif`, `.hta`, `.py`, `.sh`, `.reg`, `.inf`).
     - Any path traversal (`..`), absolute paths, drive letters (`C:`), UNC paths (`\\`), null bytes, Windows reserved names (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`), or zip slip / symlinks / junctions.
   - All target paths are validated with `contained_file(install_dir, rel_path)` and `lstat()` reparse-point checks on every path component.
5. **Crash-safe write-ahead journal:**
   - Every apply/toggle/remove/restore writes a `mod_journal` record (`status = 'in_progress'`) capturing the exact target state before touching `install_dir`, stages files safely, verifies hashes, updates `mod_deployed_files`, and marks the journal entry `'committed'`.
   - On startup (or before the next mod operation for a game), `ModsEngine.recover_incomplete()` inspects any `'in_progress'` journal entries and replays/restores the game folder cleanly to a consistent state without leaving partial files behind.

---

## 2. Plain-Language User Experience (Zero Jargon)

### 2.1 Sidebar Entry & Per-Game Tab
- **Sidebar entry:** `"Translations & Mods"` / `"التعريبات والمودات"` (between Library and Settings).
  - Includes a **game search box** (*"Search your games…"*) to filter games quickly.
  - Main primary button: **"Import translation or mod (.zip)"** / **"استيراد تعريب أو مود (.zip)"**.
  - Clicking a game opens its simple list directly (or navigates into its Translations & Mods panel). Protected games show a lock badge and the friendly lock screen when selected.
- **Per-game tab:** Inside each `GamePage`, two tabs: **Overview** and **Translations & Mods**.

### 2.2 Per-Game Controls (NO Profile Chips, NO Priority Numbers)
- Removed all technical jargon: **no** `"Profile: Vanilla / Arabized / Modded / Modded+Arabized"` chips, **no** `#1 / #2` priority numbers, and **no** raw file paths shown by default.
- Instead, every eligible game shows:
  1. **Status line:** `"Original game files are backed up ✓"` (or `"No changes made yet — original game files are untouched"` when nothing has been modified yet).
  2. **Main actions:**
     - Primary button: **`Import translation or mod (.zip)`**
     - Big clear restore button: **`Restore the original game`** (turns off all items, deletes deployed mod files, restores every backed-up original file, verifies SHA-256 hashes, and confirms restoration).
  3. **Simple list of installed items:** Each row displays:
     - Title (Arabic `name_ar` in Arabic UI, English `name` in English UI) + simple pill badge (`Translation` / `Mod`).
     - **On / Off switch** (toggles the item immediately and updates the game folder safely).
     - **Remove** button (turns off, restores any files owned only by it, and deletes the imported package).
  4. **Plain-language conflict box (only shown when 2+ enabled items touch the same file):**
     - Text: *"This translation and this mod change the same file. Which one should win?"*
     - Two clear buttons: **`Use <Item A>`** and **`Use <Item B>`**.
     - Optional collapsible **`Details`** toggle that reveals the exact affected file names only if the owner clicks it.

---

## 3. Declarative Package Format (`.zip`)

```text
sample-arabic-translation.zip
├── manifest.json
└── files/
    └── localization/
        └── strings.txt
```

```json
{
  "schema_version": 1,
  "id": "sample-arabic-translation",
  "name": "Arabic Translation",
  "name_ar": "التعريب العربي",
  "kind": "translation",
  "version": "1.0.0",
  "author": "Community",
  "description": "Arabic menus and subtitles.",
  "description_ar": "تعريب القوائم والترجمة.",
  "files_root": "files",
  "files": [
    {
      "src": "localization/strings.txt",
      "dest": "localization/strings.txt",
      "sha256": "<64-hex-lowercase-sha256>"
    }
  ]
}
```
(`"kind"` accepts `"translation"`, `"arabization"` as an alias for `"translation"`, or `"mod"`.)

---

## 4. Architecture & Schema v7

### 4.1 Module Layout (`gamehub/modules/mods/`)
- `models.py` — dataclasses (`ModItem`, `ModManifest`, `ModManifestFile`, `FileConflict`, `GameModsState`, error types `ModError`, `ProtectedGameModError`, `GameRunningModError`, `ManifestValidationError`).
- `manifest.py` — strict declarative-only `.zip` & `manifest.json` validator with SHA-256 verification and zip-slip / extension / reserved-name blocking.
- `repository.py` — SQLite persistence for Schema v7 tables (`mod_items`, `mod_backups`, `mod_deployed_files`, `mod_conflict_choices`, `mod_journal`).
- `engine.py` — `ModsEngine` coordinating protected-game gate, running-game gate, original-file backup, conflict detection/winner choices, crash-safe journaled apply, remove, restore-original, and startup recovery.
- `sample_pack.py` — builder for clean sample translation & mod `.zip` fixtures used in automated tests and owner testing.
- UI widgets (`gamehub/ui/mods_view.py`):
  - `GameModsWidget` (embedded in `GamePage` tab AND selected-game pane of sidebar `ModsView`).
  - `ModsView` (sidebar `"Translations & Mods"` page with game search box, game list, and embedded `GameModsWidget`).

### 4.2 SQLite Schema v7 (Migration v6 → v7, backup `gamehub.db-v6.bak`)
- `mod_items(id TEXT PRIMARY KEY, game_id TEXT NOT NULL REFERENCES games(id) ON DELETE RESTRICT, package_id TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('translation', 'mod')), name TEXT NOT NULL, name_ar TEXT, version TEXT NOT NULL, author TEXT, storage_dir TEXT NOT NULL, manifest_json TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)), installed_at INTEGER NOT NULL, UNIQUE (game_id, package_id)) STRICT`
- `mod_backups(game_id TEXT NOT NULL REFERENCES games(id) ON DELETE RESTRICT, rel_path TEXT NOT NULL, existed INTEGER NOT NULL CHECK (existed IN (0, 1)), backup_path TEXT, orig_sha256 TEXT, backed_up_at INTEGER NOT NULL, PRIMARY KEY (game_id, rel_path)) STRICT`
- `mod_deployed_files(game_id TEXT NOT NULL REFERENCES games(id) ON DELETE RESTRICT, rel_path TEXT NOT NULL, item_id TEXT NOT NULL REFERENCES mod_items(id) ON DELETE CASCADE, deployed_sha256 TEXT NOT NULL, deployed_at INTEGER NOT NULL, PRIMARY KEY (game_id, rel_path)) STRICT`
- `mod_conflict_choices(game_id TEXT NOT NULL REFERENCES games(id) ON DELETE RESTRICT, rel_path TEXT NOT NULL, winner_item_id TEXT NOT NULL REFERENCES mod_items(id) ON DELETE CASCADE, updated_at INTEGER NOT NULL, PRIMARY KEY (game_id, rel_path)) STRICT`
- `mod_journal(id TEXT PRIMARY KEY, game_id TEXT NOT NULL REFERENCES games(id) ON DELETE RESTRICT, operation TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN ('in_progress', 'committed', 'rolled_back')), payload_json TEXT NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL) STRICT`

---

## 5. Updated Mockups

See [docs/design/mockups/mods-arabizations.html](mockups/mods-arabizations.html) and rendered PNG previews:
1. EN Dark: [docs/design/mockups/mods-en-dark.png](mockups/mods-en-dark.png)
2. AR RTL: [docs/design/mockups/mods-ar-rtl.png](mockups/mods-ar-rtl.png)
3. Protected-Game Lock: [docs/design/mockups/mods-protected-lock.png](mockups/mods-protected-lock.png)
