# Review Council — M18 (`v1.2.0-rc.1` Pre-Release, Verification & Owner Handoff)

**Date:** 2026-11-24  
**Test verification:** `211 passed in 14.09s`, `ruff check .` clean (0 errors), source `--smoke-test` exit `0`, local PyInstaller `6.22.3` `--onedir` (`upx=False`, embedded `VERSIONINFO` `1.2.0.0`, `asInvoker` manifest) + Python-free `PATH` frozen `dist\GameHub\GameHub.exe --smoke-test` exit `0`.

## Advocate
- Completed and verified all four v1.2 implementation pillars (`M14`–`M17`) plus Part 5 conflict check and Part 6 Mods & Arabizations design/mockups:
  - **Part 1 (Zero-Presence Anti-Cheat):** Layers 1–7 active, fail-closed startup guard before `SingleInstance`, 300 ms passive Toolhelp32 + read-only SCM service guard, 1 s watchdog, Riot locked ON, other launchers opt-in, emergency teardown < 500 ms, **"Test protection"** dummy lab, and `docs/DEFENDER-SUBMISSION.md`.
  - **Part 2 (Find All Games):** Fixed Epic (`HKCU\...\Uninstall\EpicGames-*` + `LauncherInstalled.dat`) and Steam offline/non-fixed drives (`GetDriveTypeW` `{1,2,4,5}`); added Riot, GOG, EA, Ubisoft, Battle.net, itch.io, improved Xbox, **Scan Folders**, and plain-language partial-scan banners with Retry/Learn more. Live PC verified: Steam (26, complete), Epic (3, complete), Riot (1, complete), EA (2, complete).
  - **Part 3 (Cover Art That Fits):** Landscape-first Steam cover discovery (**26/26** live Steam titles wide), zero-stretch `CoverLabel`, atomic `<data_root>/cache/covers/` WebP thumbnail cache, full-name typographic placeholders, **"⋯ → Change cover…"** / **"Reset cover"**, and strictly opt-in SteamGridDB.
  - **Part 4 (Plain-Language Grouped Settings):** 5 clear groups with one-line explanations under every setting in EN & AR, **Reset to defaults** (preserving user notes/screenshots), and updated Egyptian Arabic **"شرح الإعدادات"** in `docs/USER-GUIDE-AR.md`.
  - **Part 5 (Rename conflict check):** Plain `"Rewind"` flagged risky (Rewind.ai / Limitless, Rewind Software Inc., Microsoft Store Desktop Rewind); safe variants (`GameRewind`, `Rewind Games`, `PlayRewind`) prepared for owner choice without blocking RC1.
  - **Part 6 (Mods & Arabizations):** Design (`docs/design/12-mods-and-arabizations.md`) and interactive LTR/RTL mockup (`docs/design/mockups/mods-arabizations.html`) ready for owner approval prior to M20 implementation.

## Critic
- Checked static AST security invariants (`tests/test_packaging.py`): zero banned Win32 injection/hook/input/memory APIs, `OpenProcess` strictly confined to `processes.py`, `asInvoker` manifest, `upx=False`, and `urllib` strictly confined to opt-in `steamgriddb.py`.
- Checked EN/AR catalog parity: 0 missing keys, 0 placeholder mismatches, 0 mnemonic `&` ampersands, and valid `QFileDialog` globs.
- Checked SemVer release hygiene: `CHANGELOG.md` contains `## v1.2.0-rc.1` (`Added`, `Changed`, `Fixed`, `Security`), and Windows CI will build, smoke-test (portable, fresh install, legacy `Run` cleanup, upgrade, uninstall), checksum (`SHA256SUMS.txt`), and publish pre-release `Game Hub v1.2.0-rc.1`.

## Neutral Analyst
- All 211 tests, `ruff`, source smoke test, and Python-free frozen bundle smoke test passed cleanly. Ready to tag `v1.2.0-rc.1`, run Windows CI release build, verify SHA-256, and place `GameHub-Setup-v1.2.0-rc.1.exe` on the owner's Desktop.

## Judge
**Verdict: APPROVE.** Tag `m18` and `v1.2.0-rc.1`, publish pre-release via Windows CI, copy verified installer to Desktop, and pause at the Owner Gate for `"verified"` + Rename variant choice + Part 6 Mods approval.
