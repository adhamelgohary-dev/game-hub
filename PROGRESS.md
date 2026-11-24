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
- ✅ M12c — `v1.1.0-rc.2` pre-release polish [simple]

## v1.2 ("GameRewind — Zero-Presence Anti-Cheat + All Launchers + Fitting Covers + Plain Settings + Simplified Translations & Mods")
- ✅ D-v1.2 — Anti-cheat research v2, v1.2 design, Part 6 Mods design & mockups, Rename conflict check, Council APPROVE [complex]
- ✅ M14 — Part 1: Zero-Presence Anti-Cheat Protocol (Layers 1–7 + Settings Protected Games UI) [complex]
- ✅ M15 — Part 2: Fix Epic & Steam, add Riot/GOG/EA/Ubisoft/Battle.net/itch/Xbox detectors, Scan Folders, plain scan warnings [complex]
- ✅ M16 — Part 3: Landscape-first Steam covers, thumbnail cache, optional SteamGridDB (off by default), Change cover [complex]
- ✅ M17 — Part 4: Plain-language grouped Settings, Reset to defaults, Egyptian Arabic settings guide [complex]
- ✅ M18 — Package `v1.2.0-rc.1`, copy installer to Desktop, Council review [complex]
- ✅ D-v1.2-rc2 — Owner-approved GameRewind rename, custom-folder installer, and simplified Translations & Mods design + 3 updated PNG mockups [complex]
- ✅ M19a — Rename app, exe, installer, portable zip, data folder (`%LOCALAPPDATA%\GameRewind` with automatic `%LOCALAPPDATA%\GameHub` migration), docs, and GitHub repo (`adhamelgohary-dev/game-rewind`); custom-folder per-user installer (`DisableDirPage=no`, `UsePreviousAppDir=no`, writable validation, desktop shortcut, legacy Game Hub cleanup) [complex]
- ✅ M20 — Simplified Translations & Mods (Schema v7, crash-safe journal, declarative-only manifest validator, sidebar page + per-game tab, On/Off switches, "Restore the original game", plain two-button conflict chooser, permanent lock on protected/online games, sample pack fixture) [complex]
- ✅ M21 — Independent 8-agent Red-Team Security Re-Audit (`docs/reviews/security/a–h` + Judge consolidation + 3 rounds → **0 open findings**; removed `psutil` completely, fixed idle Vanguard `vgc` lockout, 200 ms `os._exit` failsafe, `QueryUnbiasedInterruptTime` sleep immunity, hardened Mods/Installer/Xbox/SteamGridDB, `docs/SECURITY-AUDIT-v1.2.md` & `docs/SECURITY-AUDIT-v1.2-AR.md`) [complex]
- ✅ M22 — Publish `GameRewind v1.2.0-rc.2` pre-release via Windows CI, verify SHA-256 & installer/upgrade/folder-change/uninstall checks, copy `GameRewind-Setup-v1.2.0-rc.2.exe` + `Sample-Translation-Pack.zip` to Desktop [simple]
- ✅ M22b (`v1.2.0-rc.3`) — Speed + Size + Fresh Independent Security Re-Check: baseline recorded (`docs/perf/baseline-rc2.md`), local workspace cleaned (-2.23 GB), shipped bundle shrank 59% (`302 -> 123 MiB` unpacked, `121 -> 51 MiB` zip) by removing OpenCV via `cv2` shim and trimming unused PySide6/AVIF + CI size gate, lazy startup/audio/PIL imports + off-UI-thread viewport covers, UI-thread-independent direct guard-thread `os._exit` + handle-free `K32EnumProcesses` PID-diff (`362 ms -> 75–87 ms` avg / `max 180 ms` across 240 real frozen trials normal & under UI load; idle CPU `5.65% -> 1.43%` of 1 core), fresh 4-domain Red-Team audit closed all 7 findings (EA SPORTS FC Epic/EA/Xbox + 2026 catalog, DPAPI SteamGridDB API key encryption, HTTPS/magic hardening, Mods cache TTL) → **0 open findings**, Council APPROVE (`docs/reviews/M22b-rc3-review.md`) [complex]
- 🔄 Owner Gate (v1.2-rc.3) — Waiting for owner to run the 8-step Egyptian Arabic click checklist on `GameRewind-Setup-v1.2.0-rc.3.exe` and reply `"verified"` [simple]
- ⬜ M23 — Bump version to `1.2.0` and publish final `GameRewind v1.2.0` after owner replies `"verified"` [simple]

**Current task** — Paused cleanly on green `main` at **Owner Gate (v1.2-rc.3)** awaiting owner verification of `GameRewind-Setup-v1.2.0-rc.3.exe` on Desktop.

**Last completed**
- **M22b (`GameRewind v1.2.0-rc.3` Pre-Release):** Cut installed size 59% (`302.13 -> 123.24 MiB`), portable zip 58% (`121.32 -> 50.98 MiB`), idle CPU 4× (`5.65% -> 1.43%` of 1 core), cold startup 33% (`1,665 -> 1,116 ms`), cold 100-game library draw 4× (`2,477 -> 626 ms`), and frozen exit latency >4× (`~362 ms -> 75–87 ms` avg, `max 180.5 ms` across 240 real trials normal & under UI load); passed fresh 4-domain Red-Team security re-check with **0 open findings** (`docs/SECURITY-AUDIT-v1.2.md`), **236 tests passed**, `ruff` clean, and published `GameRewind v1.2.0-rc.3` with verified installer on Desktop.

**Tests** — 236 tests, `ruff check .`, local PyInstaller clean-PATH frozen smoke test, and Windows CI release workflow passing.
