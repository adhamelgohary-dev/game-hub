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
- 🔄 Owner Gate 1 — Waiting for owner approval on Part D UI mockups (`docs/design/mockups/`) and Part F `m0–m8` release cleanup list [simple]
- ⬜ M11 — Fluent UI redesign (Dark/Light + Arabic RTL + covers + icon + installer branding) (Part D) [complex]
- ⬜ M12b — Apply approved `m0–m8` release cleanup, bump version to `1.1.0-rc.1`, publish `v1.1.0-rc.1` + copy installer to Desktop + 10-item Egyptian Arabic checklist (Parts F & G) [complex]
- ⬜ M13 — Publish final `v1.1.0` after owner replies `"verified"` (Part G) [simple]

**Current task** — Paused at **Owner Gate 1**: awaiting owner approval on (1) Part D Fluent UI mockups (`docs/design/mockups/`) before implementing M11, and (2) proposed `m0–m8` GitHub Release cleanup list before deleting any old releases.

**Last completed**
- Ran full git-history audit (`gitleaks 8.30.1`: 0 leaks across all commits; 561-blob PII scan: 0 findings; third-party licenses: 100% MIT-compatible).
- Added MIT `LICENSE`, `SECURITY.md` (including SignPath code signing policy), `CONTRIBUTING.md`, `docs/SIGNPATH-APPLICATION.md`, updated bilingual `README.md`, `packaging/version_info.txt`, and `packaging/GameHub.manifest`.
- Updated `.github/workflows/windows.yml` to SemVer releases (`tags: ['v*']`, `GameHub-Setup-vX.Y.Z.exe`, `GameHub-Portable-vX.Y.Z.zip`, `SHA256SUMS.txt`, legacy v1.0 `Run` deletion check, and disabled SignPath signing step).
- Verified PyInstaller frozen EXE metadata + bundled `protected_games.json` + smoke test, passed Review Council (`docs/reviews/M12a-review.md`), and switched the repository to **PUBLIC**.

**Tests** — 182 tests, Ruff, frozen PyInstaller smoke test, and `gitleaks` all passing.
