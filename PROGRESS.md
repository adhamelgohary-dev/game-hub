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
- 🔄 Owner Gate 2 — Waiting for owner to run the 10-item RC1 Windows test checklist and reply `"verified"` [simple]
- ⬜ M13 — Publish final `v1.1.0` after owner replies `"verified"` (Part G) [simple]

**Current task** — Paused at **Owner Gate 2**: `Game Hub v1.1.0-rc.1` pre-release built and published; `GameHub-Setup-v1.1.0-rc.1.exe` copied to Desktop for owner's 10-item verification checklist before publishing final `v1.1.0`.

**Last completed**
- Created SemVer GitHub Release `v1.0.0` at `m8` with `GameHub-Setup-v1.0.0.exe`, `GameHub-Portable-v1.0.0.zip`, and `SHA256SUMS.txt`, and removed legacy `m0–m8` GitHub Release entries while keeping all git tags (`m0–m11`, `v1.0.0`).
- Bumped `__version__` to `1.1.0-rc.1`, wrote structured `CHANGELOG.md` notes, passed M12b Review Council (`docs/reviews/M12b-review.md`), and published `v1.1.0-rc.1` via Windows CI.

**Tests** — 183 tests, Ruff, `gitleaks`, and Windows CI release workflow all passing.
