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
- ✅ M12b — Release cleanup (`v1.0.0` at `m8`, deleted `m0–m8` releases), publish `v1.1.0-rc.1` pre-release, copy installer to Desktop & deliver 10-item Egyptian Arabic checklist (Parts F & G) [complex]
- ✅ M12c — `v1.1.0-rc.2` pre-release polish: verify EAC Strict defaults (Elden Ring, Armored Core VI, Elden Ring Nightreign, Lords of the Fallen, Space Marine 2; Dark Souls III stays Full), remove visible button mnemonic underlines, update Arabic catalog & screenshots, publish `v1.1.0-rc.2` & copy installer to Desktop [simple]
- 🔄 Owner Gate 2 — Waiting for owner to run the 10-item RC2 Windows test checklist and reply `"verified"` [simple]
- ⬜ M13 — Publish final `v1.1.0` after owner replies `"verified"` (Part G) [simple]

## v1.2 ("Zero-Presence Anti-Cheat + All Launchers + Fitting Covers + Plain Settings") — Replaces unverified `v1.1.0-rc.2`
- ✅ D-v1.2 — Anti-cheat research v2, v1.2 design, Part 6 Mods design & mockups, Rename conflict check, Council APPROVE [complex]
- ✅ M14 — Part 1: Zero-Presence Anti-Cheat Protocol (Layers 1–7 + Settings Protected Games UI) [complex]
- ✅ M15 — Part 2: Fix Epic & Steam, add Riot/GOG/EA/Ubisoft/Battle.net/itch/Xbox detectors, Scan Folders, plain scan warnings [complex]
- ✅ M16 — Part 3: Landscape-first Steam covers, thumbnail cache, optional SteamGridDB (off by default), Change cover [complex]
- 🔄 M17 — Part 4: Plain-language grouped Settings, Reset to defaults, Egyptian Arabic settings guide [complex]
- ⬜ M18 — Part 5 conflict handoff + full verification, package `v1.2.0-rc.1`, copy installer to Desktop, Council review [complex]
- ⬜ M19 — Execute owner-chosen Rename variant & publish final `v1.2.0` after owner replies `"verified"` [simple]
- ⬜ M20 — Part 6: Mods & Arabizations implementation (blocked until owner approves `docs/design/12-mods-and-arabizations.md` + mockups) [complex]

**Current task** — Starting **M17 (Part 4 — Plain-Language Grouped Settings & Arabic Guide)** after `M16` Council APPROVE (`208 passed`).

**Last completed**
- **M16 (Part 3 — Cover Art That Fits):** Updated Steam `_find_cover()` to search wide landscape assets first across flat, nested, and hashed layouts (**26/26** live Steam games on PC now load wide landscape art), replaced stretched `QLabel` covers with resize-aware zero-stretch `CoverLabel`, added atomic `<data_root>/cache/covers/` WebP thumbnail cache + full-title typographic placeholders, added managed `CoverStore` + **"⋯ → Change cover…"** / **"Reset cover"** on every card and Game page, and added strictly opt-in `steamgriddb.py`. Passed `docs/reviews/M16-review.md`.

**Tests** — 208 tests and `ruff check .` passing.
