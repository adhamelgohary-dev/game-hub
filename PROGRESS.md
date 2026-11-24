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

## v1.2 ("GameRewind — Zero-Presence Anti-Cheat + All Launchers + Fitting Covers + Plain Settings + Translations & Mods") — Replaces unverified `v1.1.0-rc.2`
- ✅ D-v1.2 — Anti-cheat research v2, v1.2 design, Part 6 Mods design & mockups, Rename conflict check, Council APPROVE [complex]
- ✅ M14 — Part 1: Zero-Presence Anti-Cheat Protocol (Layers 1–7 + Settings Protected Games UI) [complex]
- ✅ M15 — Part 2: Fix Epic & Steam, add Riot/GOG/EA/Ubisoft/Battle.net/itch/Xbox detectors, Scan Folders, plain scan warnings [complex]
- ✅ M16 — Part 3: Landscape-first Steam covers, thumbnail cache, optional SteamGridDB (off by default), Change cover [complex]
- ✅ M17 — Part 4: Plain-language grouped Settings, Reset to defaults, Egyptian Arabic settings guide [complex]
- ✅ M18 — Part 5 conflict handoff + full verification, package `v1.2.0-rc.1`, copy installer to Desktop, Council review [complex]
- ✅ Owner Gate (v1.2 RC1) — Owner approved `"GameRewind"` rename, custom-folder installer, and simplified Part 6 Translations & Mods [simple]
- ✅ D-v1.2-rc2 — Design finalized for GameRewind rename, custom-folder installer, and simplified Mods (`0b3d922`) [complex]
- ✅ M19a — Rename app/binaries/installer/repo to `GameRewind` (`adhamelgohary-dev/game-rewind`), auto legacy data migration, custom-folder installer (`79ad967`, tagged `m19a`) [complex]
- ✅ M20 — Part 6: Simplified Translations & Mods with On/Off list, one-click Restore Original, plain conflict chooser, crash-safe journal, Schema v7 (`15eb93c`, tagged `m20`) [complex]
- ✅ M20b (`v1.2.0-rc.2` Security Hardening & Pre-Release) — Remediated all Round 1 Red-Team findings R1–R7, uninstalled `psutil`, verified `226 passed` + `ruff` clean + clean PyInstaller frozen & portable smoke tests + `156–188 ms` dummy-process guard trials, passed `docs/reviews/M20b-v1.2.0-rc.2-review.md`, and prepared `v1.2.0-rc.2` pre-release [complex]
- 🔄 Owner Gate (v1.2 RC2) — Waiting for owner to test `GameRewind-Setup-v1.2.0-rc.2.exe` and reply `"verified"` [simple]
- ⬜ M21 — Publish final `GameRewind v1.2.0` after owner replies `"verified"` [simple]

**Current task** — Paused cleanly on green `main` at **Owner Gate (v1.2 RC2)** awaiting owner verification of `GameRewind v1.2.0-rc.2` before publishing final `v1.2.0`.

**Last completed**
- **M20 (`15eb93c`, tag `m20`):** Implemented simplified Translations & Mods (`gamehub/modules/mods/`, `gamehub/ui/mods_view.py`, SQLite Schema v7 with `gamehub.db-v6.bak`).
- **M20b (`v1.2.0-rc.2` Security Hardening & Pre-Release):** Closed all Round 1 Red-Team groups R1–R7 (zero `psutil` + `GetProcessTimes`, Vanguard `vgc` exclusion + 2XKO/Ubisoft/Battle.net/EA IDs, non-blocking `<250 ms` emergency exit, `QueryUnbiasedInterruptTime` watchdog + additive overrides + startup custom-strict, hardened Mods PE/casefold/relative-backup checks, hardened Inno Setup + SHA-pinned CI + registry-only Xbox + redirect-free SteamGridDB), passed `226 passed`, `ruff` clean, clean PyInstaller frozen & portable smoke tests, `docs/reviews/M20b-v1.2.0-rc.2-review.md` APPROVE, and published `GameRewind v1.2.0-rc.2`.

**Tests** — 226 tests passing (`pytest -q`) without `psutil`, `ruff check .` clean, frozen & portable Python-free `PATH` smoke tests passing (`exit 0`), 20 real dummy-process trials `156–188 ms`, Windows CI release gate passing.
