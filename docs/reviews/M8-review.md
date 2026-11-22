# M8 Packaging and release review

## Advocate

Game Hub v1.0.0 (`__version__ = "1.0.0"`) delivers the complete offline Game Memory desktop application for Windows 10/11 x64: library discovery + manual add, low-overhead tray session tracking, exact-window Windows Graphics Capture screenshot ring, session-bound voice and text notes, Last time card with bounded Qt Multimedia Ogg playback and validated Play launch deduplication, Controls pinning/upload and paginated Session Timeline, full Settings with atomic batch hotkey rebinding, per-user startup, verified offline data-folder relocation, and bilingual English/Arabic RTL UI. Release packaging ships both a standalone PyInstaller `GameHub-Windows-x64.zip` bundle and a per-user Inno Setup `GameHub-Setup.exe` installer with complete third-party license notices and English/Arabic user guides.

## Critic

An independent Critic audit identified two blockers and five minors before tagging `m8`:

1. `CHANGELOG.md` needed a nonempty `## m8` section for the tagged release workflow. Added.
2. `packaging/installer.iss` needed `[InstallDelete]` on `{app}\_internal` to avoid stale DLLs during in-place upgrades, `[Registry]` `uninsdeletevalue` cleanup on `HKCU\...\Run\GameHub` so uninstall leaves no dangling startup entry, and default `AppVersion "1.0.0"`. Fixed all three.

Minors addressed: filtered macOS `libportaudio.dylib` out of `analysis.datas` in `packaging/gamehub.spec`, documented `opencv_videoio_ffmpeg510_64.dll` in `THIRD_PARTY_NOTICES.txt`, called `app.setApplicationVersion(__version__)`, updated `README.md` Tech stack to present tense, added upgrade/uninstall and close-prompt details to `docs/USER-GUIDE-AR.md`, added a user-data canary preservation check across CI upgrade and uninstall, and expanded `tests/test_packaging.py` with Qt network class and installer directive assertions.

## Neutral Analyst

All 169 automated tests and Ruff pass, including static zero-network and no-injection/no-memory-read AST audits across `gamehub/`, license and packaging manifest completeness, and AST-verified English/Arabic catalog parity. Local frozen `GameHub.exe --smoke-test` passed with `PATH` stripped to `System32;Windows` and `PYTHONHOME`/`PYTHONPATH` unset (`exit: 0`). Hosted Windows CI verifies portable zip extraction, Inno Setup installation, in-place upgrade, silent uninstall, user-data canary preservation, and Python-free `PATH` startup. Interactive GUI testing on a separate clean Windows machine without Python installed remains a manual owner acceptance check per `docs/TESTING.md`.

## Judge

Initial verdict **APPROVE WITH CHANGES** for the two Critic blockers above. Re-review confirms both blockers and the accompanying packaging, license, documentation, and CI verification improvements are complete and tested. Verify the tagged `m8` (v1.0.0) Windows release run before recording final milestone approval.
