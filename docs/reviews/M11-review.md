# Review Council — M11 (Part D: Fluent UI Redesign, Covers & Branding)

Date: 2026-11-23  
Milestone: **M11 — Fluent UI redesign (Dark/Light + Arabic RTL + covers + icon + installer branding)**  
Branch / Head: `main` (pre-commit review of M11 working tree)

## Scope Reviewed
- Updated design & mockups: `docs/design/02-user-flows.md`, `docs/design/mockups/index.html`, and all 11 re-rendered mockup PNGs reflecting all 5 owner refinements.
- Theme & UI implementation: `gamehub/ui/theme.py`, `gamehub/ui/covers.py`, `gamehub/ui/library_view.py`, `gamehub/ui/game_page.py`, `gamehub/modules/memory/last_time_card.py`, `gamehub/modules/memory/note_dialog.py`, `gamehub/ui/settings_view.py`, `gamehub/ui/library_controller.py`, `gamehub/core/storage/memory.py`, `gamehub/app.py`, `gamehub/core/i18n/catalog.py`.
- Local cover art discovery: `gamehub/core/library/steam.py`, `gamehub/core/library/epic.py`.
- Branding & packaging: `packaging/assets/{GameHub.ico,GameHub.png,wizard-sidebar.bmp,wizard-header.bmp}`, `packaging/gamehub.spec`, `packaging/installer.iss`.
- Real app screenshots & README: `docs/screenshots/{library-dark-en,library-light-en,game-page-dark-en,library-dark-ar-rtl}.png`, `README.md`.
- Tests: `tests/test_library_view.py`, `tests/test_app.py`, `tests/test_i18n_and_settings_ui.py`, `tests/test_steam.py`, `tests/test_packaging.py`.

## Role Deliberations

### Advocate
- Every one of the owner's 5 mockup revisions is faithfully implemented in both the mockups and the live PySide6 UI:
  1. Real local game cover art (Steam flat, `<appid>/`, and hashed `librarycache` subdirs; Epic local cover files; bounded `QImageReader` decoding with LRU cache and stylized placeholder fallback; zero network calls).
  2. Zero-background pill and anti-cheat sidebar box removed from main UI and moved into **Settings → About and privacy** (with full Arabic translation).
  3. `"Open"` renamed to `"Details"` (`"التفاصيل"`) and the entire `GameCard` is clickable and keyboard-activatable.
  4. Game page uses **Play** as the sole primary CTA and places **"Change executable…"** and **"Last moments…"** inside a clean **`⋯`** overflow menu (hidden for Manual games where appropriate).
  5. Last-time card displays a clean **"Last moments"** carousel with flanking `‹`/`›` arrows, visual pagination dots (`●`/`○`), and zero technical labels anywhere in the UI.
- Pure PySide6 + custom Fluent QSS keeps Game Hub 100% MIT-licensed (avoiding GPLv3 `PySide6-Fluent-Widgets`) while delivering crisp Windows 11 Dark, Light, and System themes with live switching and smooth page fade transitions.
- Real PyInstaller bundle embeds `GameHub.ico`, `version_info.txt`, and `GameHub.manifest`, and passes `--smoke-test`.

### Critic
- **Caught & resolved during verification:** Initial real-app offscreen captures exposed (a) horizontal card clipping on the 3rd Library column due to `QLabel` pixmap `sizeHint` width and (b) a bright white `QScrollArea` tab surface inside `GamePage` in Dark mode. Both were fixed (`QSizePolicy.Policy.Ignored` + dynamic column width math + `ScrollBarAlwaysOff` on Library; `#tabSurface` QSS on GamePage tab containers; hidden `::menu-indicator` on `⋯`) and visually re-verified across all 4 real screenshots.
- **Residual low-risk notes:**
  - `fade_in_widget` is intentionally a no-op under `QT_QPA_PLATFORM=offscreen` to prevent headless animation flakiness; interactive Windows desktop rendering should be spot-checked during the owner's RC1 checklist.
  - Real Steam cover discovery was verified live on local Steam libraries (26/26 games resolved); Epic and Xbox local artwork fallback stays covered by synthetic fixtures + stylized placeholders.

### Neutral Analyst
- Automated verification: **183 passed** (`pytest -q`), **Ruff clean** (`All checks passed!`), **PyInstaller build + offscreen `GameHub.exe --smoke-test` exit 0**, **Arabic AST parity & BiDi filter check clean**, **zero-network / zero-injection / zero-tray static audit clean**, and **`gitleaks` 0 leaks** across git history and all source directories.
- No regressions to v1.0/M9/M10 contracts: zero background processes, passive Toolhelp-only protection tracking, Schema v5 compatibility, and offline-only operation remain strictly enforced.

### Judge
- **Verdict: APPROVED**
- M11 satisfies all Part D requirements and every owner refinement with verified tests, visual captures, clean packaging, and zero license or privacy regressions. Proceed to commit, tag `m11`, and execute M12b (approved `m0–m8` release cleanup + `v1.1.0-rc.1`).
