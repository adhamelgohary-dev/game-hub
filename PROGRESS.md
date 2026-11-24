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
- ✅ M22c (rc.3 Follow-Up Security Hardening) — Closed all 19 open findings from the fresh 4-domain Red-Team reports (`docs/reviews/security/rc3/1..4` -> `round2-followup-verification.md`): 240 ms PID-reuse audit bound (`RC3-AC-01`), exact `K32EnumProcesses` byte slice (`RC3-AC-02`), unconditional `anti_cheat_exes` + `gamemon*.des` / `beservice_x64.exe` + 2026 catalog fixes (`RC3-AC-03..04`), `_policy_gen` lock safety (`RC3-AC-05`), `GameStarted` ordering (`RC3-AC-06`), `package_id`-only filter (`RC3-AC-07`), `covers.py` UNC/reparse hardening (`RC3-NET-01..02`), Mods dotfile/overlapped-PE/single-handle-extract/cache/override-move hardening (`RC3-LOC-01..06`), and `cv2` sentinel/licenses/AST gate hardening (`RC3-PKG-01..04`) [complex]
- 🔄 Owner Gate (v1.2-rc.3) — `GameRewind v1.2.0-rc.3` published via Windows CI; 19 follow-up security fixes ready on `main` (can cut `v1.2.0-rc.4` or test `rc.3` and fold into final `v1.2.0` once owner replies `"verified"`) [simple]
- ⬜ M23 — Bump version to `1.2.0` and publish final `GameRewind v1.2.0` after owner replies `"verified"` [simple]

**Current task** — Paused cleanly on green `main` at **Owner Gate (v1.2-rc.3)** with 19 follow-up Red-Team security fixes committed and verified (`243 passed`, `ruff` clean).

**Last completed**
- **M22b (`GameRewind v1.2.0-rc.3` Pre-Release):** Published via Windows CI (`run 45510996638`, `success`) with 59% smaller bundle (`302 -> 123 MiB` unpacked, `121 -> 51 MiB` zip), 4× faster library draw & exit latency (`~362 ms -> 75–87 ms`), and 4× lower idle CPU.
- **M22c (Follow-Up Red-Team Hardening on `main`):** Closed all 19 findings across `docs/reviews/security/rc3/1..4` (`round2-followup-verification.md`) with regression tests (`tests/test_security_rc3_fixes.py`, `243 passed`, `ruff` clean).

**Tests** — 243 tests passing (`pytest -q`), `ruff check .` clean, `v1.2.0-rc.3` Windows CI release workflow passing.
