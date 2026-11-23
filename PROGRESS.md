# Progress

## v1.0.0 (Completed)
- ✅ D — Design [complex]
- ✅ M0 — Setup [simple]
- ✅ M1 — Library detection [complex]
- ✅ M2 — Session tracking [complex]
- ✅ M3 — Screenshots [complex]
- ✅ M4 — Notes [complex]
- ✅ M5 — Last time card and Play [complex]
- ✅ M6 — Controls card and timeline [simple]
- ✅ M7 — Settings and Arabic/English [complex]
- ✅ M8 — Packaging and release [complex]

## v1.1 ("Zero background + anti-cheat safe + clean UI + public-ready")
- ✅ D-v1.1 — Anti-cheat research, v1.1 design docs & Fluent UI mockups [complex]
- ✅ M9 — Zero background & clean process exit (Part B) [complex]
- ✅ M10 — Game-aware lifecycle, protected-games catalog, Strict mode & borderless WGC (Part C) [complex]
- ✅ M12a — Public-readiness audit, MIT license, SECURITY/CONTRIBUTING, EXE metadata, SignPath & SemVer CI prep, repo PUBLIC (Parts E & F prep) [complex]
- ✅ Owner Gate 1 — Approved UI mockups (with 5 refinements) and `m0–m8` release cleanup plan [simple]
- ✅ M11 — Fluent UI redesign (Dark/Light + Arabic RTL + covers + icon + installer branding) (Part D) [complex]
- 🔄 M12b — Apply approved `m0–m8` release cleanup (`v1.0.0` at `m8`), bump version to `1.1.0-rc.1`, publish `v1.1.0-rc.1`, copy installer to Desktop & deliver 10-item Egyptian Arabic checklist (Parts F & G) [complex]
- ⬜ M13 — Publish final `v1.1.0` after owner replies `"verified"` (Part G) [simple]

**Current task** — Starting **M12b**: convert `m8` release to `v1.0.0`, remove `m0–m8` GitHub Release entries (keeping all git tags), then publish `v1.1.0-rc.1` via Windows CI.

**Last completed**
- Implemented M11 Fluent UI redesign (`gamehub/ui/theme.py`, `gamehub/ui/covers.py`, `library_view.py`, `game_page.py`, `last_time_card.py`, `note_dialog.py`, `settings_view.py`, `app.py`, `catalog.py`) incorporating all 5 owner refinements (real local Steam/Epic cover art, zero-background/anti-cheat info moved to Settings → About & Privacy, clickable cards + `"Details"`, Game page `⋯` overflow menu, Last-time `"Last moments"` carousel with arrows + pagination dots and zero technical labels).
- Generated app icon (`GameHub.ico` / `GameHub.png`) and Inno Setup branding BMPs, captured and visually verified 4 real app screenshots (`docs/screenshots/`), updated `README.md`, and passed M11 Review Council (`docs/reviews/M11-review.md`).

**Tests** — 183 tests, Ruff, frozen PyInstaller build + smoke test, and `gitleaks` all passing.
