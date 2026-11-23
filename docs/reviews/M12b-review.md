# Review Council — M12b (Parts F & G: Release Cleanup & v1.1.0-rc.1)

Date: 2026-11-23  
Milestone: **M12b — Release cleanup (`v1.0.0`) and Pre-release Candidate (`v1.1.0-rc.1`)**  
Branch / Head: `main` (pre-tag review for `v1.1.0-rc.1`)

## Scope Reviewed
- GitHub Releases cleanup: Created `Game Hub v1.0.0` at `m8` (`6d1e0c2e39edae0bc48a9dfff1a331253b19f793`) with `GameHub-Setup-v1.0.0.exe`, `GameHub-Portable-v1.0.0.zip`, and `SHA256SUMS.txt`; deleted old `m0–m8` GitHub Release entries while retaining all git tags (`m0–m11`, `v1.0.0`).
- Version bump & release notes: `gamehub/__init__.py` (`1.1.0-rc.1`), `CHANGELOG.md` (`## v1.1.0-rc.1` with `Added`, `Changed`, `Fixed`, `Security`), `tests/test_packaging.py`.
- Workflow & packaging checks: `.github/workflows/windows.yml`, `packaging/installer.iss`, `packaging/gamehub.spec`, `packaging/version_info.txt`, `packaging/GameHub.manifest`.

## Role Deliberations

### Advocate
- GitHub Releases now strictly follow SemVer (`v1.0.0`, followed by pre-release `v1.1.0-rc.1`) with standardized asset naming (`GameHub-Setup-vX.Y.Z.exe`, `GameHub-Portable-vX.Y.Z.zip`, `SHA256SUMS.txt`) and structured `CHANGELOG.md` notes.
- Tagging `v1.1.0-rc.1` exercises the exact Windows 2025 CI release pipeline end-to-end: unit tests, Ruff, PyInstaller build, Inno Setup 6 installer build, Python-free PATH portable/install/upgrade/uninstall smoke test, legacy v1.0 `Run\GameHub` deletion test, SHA-256 checksum generation, and automatic `--prerelease` publication.

### Critic
- **Checked Inno Setup pre-release compatibility:** Verified `packaging/installer.iss` passes `AppVersion=1.1.0-rc.1` as a display string only (not `VersionInfoVersion`), preventing compiler errors on hyphenated SemVer pre-release tags.
- **Reminder for M13:** `v1.1.0-rc.1` is intentionally marked `--prerelease` and MUST NOT be promoted to final `v1.1.0` until the owner completes the 10-item Windows click checklist and replies `"verified"`.

### Neutral Analyst
- Full test suite (183 tests), Ruff, and `gitleaks` are verified clean before tagging `v1.1.0-rc.1`.
- Repository visibility confirmed `PUBLIC` with zero secrets or personal paths in commit history or working tree.

### Judge
- **Verdict: APPROVED**
- Proceed to commit, push `main`, tag and push `v1.1.0-rc.1`, monitor Windows CI to green release publication, verify `SHA256SUMS.txt`, copy `GameHub-Setup-v1.1.0-rc.1.exe` to `%USERPROFILE%\Desktop\`, and deliver the 10-item Egyptian Arabic checklist to the owner.
