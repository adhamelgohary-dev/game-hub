# SignPath Foundation — Open-Source Code Signing Application Guide

This document prepares everything needed to apply for **free Windows Authenticode code signing** through the [SignPath Foundation](https://signpath.org/projects/submit) so Windows SmartScreen stops warning users when installing `GameRewind-Setup-vX.Y.Z.exe`.

## 1. Eligibility Checklist (SignPath Foundation Requirements)

| Requirement | GameRewind Status |
| --- | --- |
| Public GitHub repository | ✅ Ready (switched to PUBLIC after clean `gitleaks` + PII audit) |
| Single OSI-approved open-source license (no commercial dual-license) | ✅ MIT License (`LICENSE`); pure PySide6 QSS avoids GPLv3/commercial `PySide6-Fluent-Widgets` |
| No malware / PUP / closed-source components | ✅ 100% open source, zero network calls, zero background services |
| Active maintenance & existing public releases to sign | ✅ Active releases on GitHub Releases (`GameRewind-Setup-vX.Y.Z.exe`, `GameRewind-Portable-vX.Y.Z.zip`) |
| Published code signing policy & privacy statement | ✅ Published in `SECURITY.md` |
| Reproducible CI build workflow (GitHub Actions) | ✅ `.github/workflows/windows.yml` includes the SignPath submission step (disabled via `vars.SIGNPATH_ENABLED == 'true'` until approved) |
| SignPath attribution in README | ✅ Ready to activate once approved: *"Free code signing provided by SignPath.io, certificate by SignPath Foundation"* |

## 2. Exact Form Answers (Copy-Paste Ready)

- **Project name:** `GameRewind`
- **Project homepage / repository URL:** `https://github.com/adhamelgohary-dev/game-rewind`
- **Download page URL:** `https://github.com/adhamelgohary-dev/game-rewind/releases`
- **License:** `MIT License` (`https://github.com/adhamelgohary-dev/game-rewind/blob/main/LICENSE`)
- **Code Signing Policy URL:** `https://github.com/adhamelgohary-dev/game-rewind/blob/main/SECURITY.md#code-signing-policy-signpath-foundation`
- **Short project description:**
  > GameRewind is an offline, open-source Windows 10/11 desktop app (Python + PySide6) that helps players pick up single-player games after a break by showing their last voice/text note, recent window screenshots, playtime, and pinned controls. It runs with zero background footprint (no tray or autostart), makes zero network requests, and includes anti-cheat Strict mode safeguards for competitive games.
- **Build system / CI:** `GitHub Actions (windows-2025), PyInstaller one-folder bundle + Inno Setup 6 per-user installer`
- **Artifacts to sign:** `GameRewind.exe` (inside portable zip) and `GameRewind-Setup-vX.Y.Z.exe` (Inno Setup installer)
- **Team & approval policy:** Single maintainer (`adhamelgohary-dev`) approving release signing requests manually in SignPath dashboard after green CI + automated security/offline tests.

## 3. Only the Clicks You Must Do to Submit & Activate

1. Open **https://signpath.org/projects/submit** and click **Apply for free code signing** (fill in the fields from Section 2 above and submit).
2. Wait for the SignPath Foundation approval email (usually a few business days).
3. Once approved, sign in to **https://app.signpath.io**, create your project slug (`game-rewind`) with a **release** signing policy linked to GitHub Actions (`adhamelgohary-dev/game-rewind`), and generate a CI API token.
4. In GitHub (`adhamelgohary-dev/game-rewind` → **Settings → Secrets and variables → Actions**):
   - Add **Repository secrets**:
     - `SIGNPATH_API_TOKEN` = your SignPath CI user API token
     - `SIGNPATH_ORG_ID` = your SignPath Organization ID
   - Add **Repository variable**:
     - `SIGNPATH_ENABLED` = `true`
5. Uncomment the SignPath attribution line in `README.md`, and every future `vX.Y.Z` tag will automatically submit the Windows installer to SignPath for signing!
