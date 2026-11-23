# Mods & Arabizations Module — Design Specification (DESIGN ONLY — Awaiting Owner Approval)

**Status:** Design & Mockups Ready — **NO CODE IMPLEMENTED** until owner replies `"OK"`.  
**Date:** 2026-11-24  
**Scope:** Part 6 of Game Hub v1.2 roadmap — first-class safe manager for single-player game mods and Arabic translations (Arabizations / تعريبات).

---

## 1. Safety & Legal Hard Rules (Non-Negotiable)

1. **Strictly DISABLED for protected / online games:**
   - Any game matched by `protected_games.json` (or in Strict protection mode) has the Mods & Translations tab locked with a clear banner: *"Mods and translations are disabled for online/anti-cheat games to prevent bans."*
   - Attempting to install or enable a mod on a protected game is rejected at both UI and core service layers.
2. **Never redistribute original game files:**
   - Mod / translation packages contain **only changed or added files** (never base game executables, DLLs, or unmodified copyrighted assets).
   - Original game files are backed up **locally** on the player's own PC before any file is overwritten.
3. **Atomic backup + one-click Restore to Vanilla:**
   - Before touching any file inside a game's `install_dir`, Game Hub copies the original file to `<data_root>/mods/backups/<game_id>/<relative_path>` and records its SHA-256 hash in SQLite (`mod_backups`).
   - Clicking **"Restore to Vanilla"** removes all deployed mod files, restores every backed-up original file, verifies hashes, and returns the game directory to its exact pre-mod state.
4. **Offline & symlink-safe:**
   - All paths validated through `contained_file()` / `local_path()` (zero path traversal `..`, zero symlinks/junctions escaping `install_dir`).

---

## 2. User Features (Global + Per-Game)

### 2.1 Global "Mods & Translations" View (Sidebar Entry)
- Summary across all eligible single-player games:
  - Total installed mods & Arabizations, active profile per game, any unresolved file conflicts highlighted at the top.
  - **"Import Package (.zip / folder)"** button to install a mod or Arabization package directly from disk.
  - Quick filter: *All* | *Arabizations (تعريبات)* | *Mods* | *Has conflicts*.

### 2.2 Per-Game "Mods & Translations" Tab (Inside Game Page)
- **Profile Switcher** (one click switches deployed files atomically):
  - `Vanilla` (zero mods active; original files restored)
  - `Arabized` (only Arabic translation package(s) active)
  - `Modded` (gameplay/visual mods active)
  - `Modded + Arabized` (or custom user profiles)
- **Ordered Mod / Translation List (Load Order):**
  - Drag-or-arrow reorder (`Move Up` / `Move Down`): lower-priority items deploy first; higher-priority items win on controlled overrides when the user resolves a conflict.
  - Per-item controls: Enable/Disable toggle, Type badge (`Arabization` / `Mod`), Version, File count, Conflict warning icon, Uninstall button.
- **One-Click "Restore to Vanilla" button** with verification badge (*"Verified: all 14 original files intact"*).

---

## 3. Conflict Detection (Real-World Case: Mafia II Arabization vs. Mod)

### Real Scenario
Suppose a player installs:
1. **Mafia II — Arabic Translation (تعريب Mafia II)** modifying `pc/sds_en/text/text_default.sds` and `pc/sds_en/gui/fonts.sds`.
2. **Mafia II — Classic HUD / Remaster Mod** also modifying `pc/sds_en/gui/fonts.sds` and `pc/sds_en/cars/cars.sds`.

### How Game Hub Handles It
1. **Pre-deploy file-map intersection:** Before deploying a profile, `ConflictAnalyzer` computes the set of normalized relative target paths for every enabled package in load order.
2. **Exact conflict report:** Any relative path touched by ≥ 2 enabled packages (e.g., `pc/sds_en/gui/fonts.sds`) is flagged immediately:
   - Shows the exact conflicting file path and both packages (*"Arabic Translation v1.2"* vs. *"Classic HUD Mod v2.0"*).
   - Explains clearly which package currently wins based on **Load Order** (higher priority wins).
   - Offers 3 safe user actions:
     1. **Change Load Order** (e.g., put Arabization on top so Arabic fonts aren't overwritten by the HUD mod).
     2. **Disable one package** in this profile (or keep separate `Arabized` vs. `Modded` profiles).
     3. **Per-file override rule** (advanced: choose which package provides `fonts.sds` while keeping all other files from both).
3. **Target game version / hash mismatch warning:** If `manifest.json` specifies `target_exe_sha256` or `target_version` and the installed game's exe hash differs (e.g., after a Steam update), Game Hub warns clearly (*"This translation was built for game version 1.0.4; your installed game differs — continue at your own risk?"*) before deploying.

---

## 4. Simple Package Format (For Owner's Own Arabizations & Community Packages)

A package is either a standard `.zip` archive or a folder containing a `manifest.json` plus a `files/` tree with **changed/added files only**:

```text
mafia2-ar-v1.2.zip
├── manifest.json
└── files/
    └── pc/
        └── sds_en/
            ├── text/
            │   └── text_default.sds
            └── gui/
                └── fonts.sds
```

### `manifest.json` Schema (v1)
```json
{
  "schema_version": 1,
  "id": "mafia2-arabic-translation",
  "name": "Mafia II — Arabic Translation",
  "name_ar": "تعريب مافيا 2",
  "kind": "arabization",
  "version": "1.2.0",
  "author": "Author Name",
  "description": "Full Arabic menus, subtitles, and HUD fonts.",
  "description_ar": "تعريب كامل للقوائم والترجمة وخطوط الواجهة.",
  "target_game": {
    "name": "Mafia II: Definitive Edition",
    "steam_app_ids": ["1030830"],
    "exe_name": "Mafia II Definitive Edition.exe",
    "target_version": "1.0.4",
    "target_exe_sha256": "optional-lowercase-hex-sha256"
  },
  "files_root": "files",
  "files": [
    {
      "src": "pc/sds_en/text/text_default.sds",
      "dest": "pc/sds_en/text/text_default.sds",
      "sha256": "..."
    },
    {
      "src": "pc/sds_en/gui/fonts.sds",
      "dest": "pc/sds_en/gui/fonts.sds",
      "sha256": "..."
    }
  ],
  "notes": "Requires English language selected in Steam properties."
}
```

### Why This Format Works Great for the Owner's Own Translations
- **Zero copyrighted base files redistributed:** Only the translated strings/fonts/assets go in `files/`.
- **Built-in "Package Creator" wizard (Phase 2 of module):** Point Game Hub at your modified translation files + target game, and Game Hub auto-computes hashes and writes `manifest.json` + `.zip` ready to share.

---

## 5. Proposed Architecture & SQLite Tables (Future Implementation — Schema v7)

- `gamehub/modules/mods/` (isolated pluggable module subscribing to `EventBus`, zero impact on core tracking):
  - `manifest.py` — strict `manifest.json` validation & SHA-256 checks
  - `backup.py` — atomic original-file backup & verified Restore-to-Vanilla
  - `conflicts.py` — file-level conflict detector & load-order resolver
  - `deployer.py` — transactional profile switch (guards protected games first!)
- SQLite tables (only added after owner approves):
  - `mod_packages(id, game_id, kind, name, name_ar, version, author, storage_dir, manifest_json, installed_at)`
  - `mod_profiles(id, game_id, name, is_active, created_at)`
  - `mod_profile_items(profile_id, package_id, enabled, load_order)`
  - `mod_backups(game_id, rel_path, backup_path, orig_sha256, backed_up_at)`
  - `mod_deployed_files(game_id, rel_path, package_id, deployed_sha256, deployed_at)`

---

## 6. Mockups

See interactive HTML mockup: [docs/design/mockups/mods-arabizations.html](mockups/mods-arabizations.html) and rendered PNG previews in `docs/design/mockups/mods-en-dark.png` and `docs/design/mockups/mods-ar-rtl.png`.
