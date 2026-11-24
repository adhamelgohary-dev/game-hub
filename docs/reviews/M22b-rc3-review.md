# Review Council Gate — `v1.2.0-rc.3` (Speed + Size + Fresh Security Re-Check)

**Date:** 2026-11-24 / 2026-11-25  
**Scope:** Parts A (Workspace Cleanup & Bundle Size Reduction), B (Startup, Async Library/Covers, Direct Guard Exit Latency, Near-Zero Idle CPU), C (Fresh 4-Domain Independent Red-Team Re-Check + Remediation to 0 Open Findings), and D (`v1.2.0-rc.3` Pre-Release).

---

## Advocate
- Every measurable target in the rc.3 brief was exceeded against the recorded `docs/perf/baseline-rc2.md` baseline:
  - Installed bundle cut **59.2%** (`302.13 MiB -> 123.24 MiB`, limit `< 200 MiB`); Portable `.zip` cut **58.0%** (`121.32 MiB -> 50.98 MiB`, limit `< 70 MiB`); local working folder cut **~2.26 GB** (`2.89 GB -> ~0.70 GB`).
  - Anti-cheat exit latency cut **>4×** (`~362 ms -> 75–87 ms` avg; worst P95 `171.3 ms < 200 ms`; worst single trial across 240 real frozen trials `180.5 ms < 300 ms`), completely independent of the Qt UI thread even under active load.
  - Idle CPU over 60 s cut **4.0×** (`5.65% -> 1.43%` of 1 logical core; `0.119%` total system CPU).
  - Cold-cache frozen startup cut **33.0%** (`1,664.5 ms -> 1,115.6 ms`); 20-game and 100-game cold library draws are **4.0×–4.6× faster** with non-blocking off-UI-thread cover decoding; Mods page open is **5.0× faster** (`64.0 ms -> 12.9 ms`).
- Fresh independent 4-domain Red-Team audit caught real gaps (EA SPORTS FC Epic/EA/Xbox detection, 2026 anti-cheat catalog including GTA V Enhanced & Marvel Rivals, plaintext SteamGridDB API key, URL/image hardening) and closed all 7 findings with regression tests (**236 passed**, `ruff` clean, clean-PATH frozen `--smoke-test` exit `0`).

## Critic
- Check 1: Does removing `opencv-python` via `ensure_cv2_shim()` risk breaking live WGC capture?
  - Verified: `windows_capture/__init__.py` imports `cv2` strictly for unused `save_as_image()`; GameRewind reads `frame.frame_buffer` (NumPy view) and encodes WebP via Pillow. `_check_capture_runtime()` now proves end-to-end `windows_capture.Frame -> _copy_frame -> Pillow WebP encode -> Qt WebP decode` inside the frozen `GameRewind.exe` with zero OpenCV installed.
- Check 2: Does `K32EnumProcesses` PID-diff risk missing a protected game on PID reuse?
  - Verified: `pid_snapshot()` captures active PIDs BEFORE `list_processes()` (race-free), falls back fail-closed to full `Toolhelp32` on any API error or buffer overflow, runs an unconditional full `Toolhelp32` audit every 2.0 s, checks SCM services every 240 ms, resets on `update_policy()` and `unignore_pid()`, and `self_check()` / direct `check_once()` always run full scans.
- Check 3: Does direct guard-thread `os._exit(0)` leave a stale `gamehub.lock` blocking the next launch?
  - Verified live and automated in `tests/test_security_rc3.py::test_single_instance_recovers_cleanly_after_hard_os_exit`: Qt's `QLockFile` immediately detects the dead PID and reclaims the lock cleanly.
- Check 4: Does `title_aliases` risk false-positive strict-mode matches on single-player games?
  - Verified: matches require exact normalized title equality or whole-word prefix (`alias + " "`), tested against single-player titles (`Hollow Knight`, `Portal`, `Terraria`, `Balatro`).

## Neutral Analyst
- All design docs (`docs/design/13-v1.2-rc3-speed-size.md`), decisions (`DECISIONS.md`), baseline vs. results (`docs/perf/baseline-rc2.md`, `docs/perf/rc3-results.md`, raw JSON trial logs), and fresh security audit reports (`docs/reviews/security/rc3/`, `docs/SECURITY-AUDIT-v1.2.md`, `docs/SECURITY-AUDIT-v1.2-AR.md`) are complete and internally consistent.
- CI enforces the new `< 200 MiB` unpacked / `< 70 MiB` zip size gate, forbidden-binary check, clean-PATH smoke test, custom-folder installer/upgrade/uninstall lifecycle, PE manifest/UPX verification, and Windows Defender scan before publishing `v1.2.0-rc.3`.

## Judge Verdict
**APPROVE** — Ship `GameRewind v1.2.0-rc.3` pre-release via Windows CI, copy verified installer to Desktop, and pause at Owner Gate for `"verified"` before cutting final `v1.2.0`.
