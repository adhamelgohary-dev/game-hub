# Review Council — M23 (`GameRewind v1.2.0` Final Release Gate)

**Date:** 2026-11-25  
**Scope:** Promotion of verified `v1.2.0-rc.3` plus M22c follow-up Red-Team hardening (`14907bb`) to final SemVer release **`GameRewind v1.2.0`**.  
**Owner Gate:** Owner replied `"verified"` after testing `GameRewind-Setup-v1.2.0-rc.3.exe`.

---

## 1. Advocate
- Every v1.2 pillar is complete, tested, and verified on real Windows hardware and isolated `windows-2025` CI:
  - **GameRewind brand & custom-folder installer (M19a):** Lossless `%LOCALAPPDATA%\GameHub` → `%LOCALAPPDATA%\GameRewind` migration, writable custom-folder install (`DisableDirPage=no`, `UsePreviousAppDir=no`), legacy Game Hub cleanup, and `asInvoker` zero-elevation execution.
  - **Zero-Presence Anti-Cheat Protocol (M14, M21, M22b, M22c):** Fail-closed `ProtectionGuard.self_check()` first, zero `psutil`, zero `OpenProcess` on protected/anti-cheat targets, direct guard-thread `os._exit` achieving `75–87 ms` avg / `180 ms` max exit latency across 240 real frozen trials (Fortnite, Valorant, EA SPORTS FC — normal and under active UI load), 240 ms LIFO PID-reuse full audit bound, and 2026 multi-launcher catalog coverage.
  - **Speed & Size (M22b):** 59% smaller shipped bundle (`302 -> 123.45 MiB` unpacked, `121 -> 52.41 MiB` portable `.zip`, `81 -> 38.07 MiB` Setup `.exe`), 4× lower idle CPU (`5.65% -> 1.43%` of 1 core), 4×–4.6× faster library rendering, and automated CI size/forbidden-binary gates.
  - **Simplified Translations & Mods (M20, M21, M22c):** Crash-safe `mod_journal`, declarative-only SHA-256 single-handle zip extraction with dotfile and overlapped-PE header rejection, and permanent protected-game lock.
  - **Security Audits:** Zero open findings across both the M21 8-agent audit and the rc.3 4-domain Red-Team audit + 19-finding M22c remediation (`243 passed`, `ruff check .` clean, Windows Defender `0 threats`).

## 2. Critic
- **Delta between `v1.2.0-rc.3` and `v1.2.0`:** Commit `14907bb` (M22c) landed 19 security hardening fixes on `main` after `v1.2.0-rc.3` was tagged. Could any of those changes break the frozen PyInstaller build or Windows CI installer smoke tests?
  - *Check required:* We MUST run the full `pytest -q` (`243 passed`), `ruff check .`, and a clean local PyInstaller build (`packaging/gamerewind.spec`) + Python-free `--smoke-test` BEFORE tagging `v1.2.0`, and verify every CI gate on `v1.2.0` (including fresh custom-folder install, legacy upgrade, folder change, uninstall, PE manifest/full-file UPX scan, bundle size gate, and Windows Defender scan) succeeds before delivering the Desktop installer.
- **Release metadata consistency:** Ensure `gamehub/__init__.py` (`__version__ = "1.2.0"`), `packaging/version_info.txt` (`ProductVersion = '1.2.0'`), and `CHANGELOG.md` (`## v1.2.0`) all match cleanly so Windows CI extracts non-empty release notes and publishes a non-prerelease GitHub Release (`isPrerelease: false`).
- **Repository visibility & git hygiene:** Confirm `adhamelgohary-dev/game-rewind` stays `PUBLIC`, no force-push occurs, and `dist/`/`build/` stay untracked.

## 3. Neutral Analyst
- The M22c hardening commit (`14907bb`) is strictly defensive (exact `K32EnumProcesses` byte slicing, 240 ms PID-reuse audit, UNC/reparse-safe cover loading, dotfile/overlapped-PE/single-handle mod validation, `protected_games_override.json` preservation on store moves, and stricter AST/CI gates), has dedicated regression coverage (`tests/test_security_rc3_fixes.py`), and already passed `main` CI (`45511981692`, `45512019614`).
- The M23 release commit touches only version strings and documentation (`gamehub/__init__.py`, `packaging/version_info.txt`, `CHANGELOG.md`, `PROGRESS.md`, `HANDOFF.md`, `LEARNING.md`, `docs/reviews/M23-review.md`). Risk is minimal once local tests, `ruff`, and frozen `--smoke-test` pass.

## 4. Judge Verdict
- **Verdict:** **APPROVE** for final **`GameRewind v1.2.0`** release, contingent on:
  1. `243 passed` in `pytest -q` and `ruff check .` clean after the version bump.
  2. Clean local PyInstaller build of `packaging/gamerewind.spec` + Python-free `--smoke-test` exit `0`.
  3. Full green Windows CI pipeline on tag `v1.2.0` publishing non-prerelease `GameRewind v1.2.0` with `GameRewind-Setup-v1.2.0.exe`, `GameRewind-Portable-v1.2.0.zip`, `SHA256SUMS.txt`, and `0 threats` from Windows Defender.
  4. Verified SHA-256 match on the Desktop copy `C:\Users\adham\Desktop\GameRewind-Setup-v1.2.0.exe`.
