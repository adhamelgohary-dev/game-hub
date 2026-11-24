# GameRewind v1.2 — Independent Red-Team Security Audit Report

**Date:** 2026-11-24 (Re-verified for `v1.2.0-rc.3`)  
**Product:** GameRewind (`v1.2.0-rc.3`)  
**Methodology:**
- **M21 Initial Audit (`v1.2.0-rc.2`):** 8-agent Red-Team audit (`docs/reviews/security/a-static-scan.md` through `h-mods-safety.md`) -> 3 verification rounds -> 0 open findings.
- **rc.3 Fresh-Eyes Re-Check (`v1.2.0-rc.3`):** 4 independent fresh-eyes Red-Team audits after the speed & size optimizations ([C1 Anti-Cheat & Launchers](reviews/security/rc3/c1-anticheat.md), [C2 Network & Websites](reviews/security/rc3/c2-network.md), [C3 Local Safety, Mods & CI](reviews/security/rc3/c3-local-safety.md), [C4 Packaging & Frozen Binary](reviews/security/rc3/c4-packaging.md)) consolidated by the Judge ([judge-consolidation.md](reviews/security/rc3/judge-consolidation.md)) -> all 7 findings closed and regression-tested -> **0 open findings**.

**Final Verdict:** **PASS — 0 Open Findings (0 Critical, 0 High, 0 Medium, 0 Low)**

---

## 1. Fresh `v1.2.0-rc.3` Audit Scope & Domain Results

| Domain | Independent Report | Final Verdict | Key Guarantees Verified |
| --- | --- | --- | --- |
| **(C1) Anti-Cheat & Launcher Coverage** | [c1-anticheat.md](reviews/security/rc3/c1-anticheat.md) | **PASS (0 open)** | Verified all 43 catalog entries across Epic, Steam, EA app, Xbox/Game Pass, Riot Client, Ubisoft, and Battle.net. Closed EA SPORTS FC Epic/EA/Xbox/Steam/title gaps + added 2026 titles (GTA V / GTA V Enhanced BattlEye, Marvel Rivals, Wuthering Waves, Roblox, Dota 2, Battlefield 6, CoD Battle.net). Verified `K32EnumProcesses` fast PID-diff (0 process handles, fail-closed fallback, 2 s unconditional full audit) + direct guard-thread `os._exit` + unchanged `self_check()` -> `SingleInstance` -> TOCTOU `check_once()` order. Zero `psutil`, zero injection/hooks/memory reads. |
| **(C2) Network & Websites** | [c2-network.md](reviews/security/rc3/c2-network.md) | **PASS (0 open)** | Confirmed **only one** outbound network path exists: strictly opt-in SteamGridDB (`steamgriddb_enabled=False` by default). Enforced HTTPS-only port 443, allow-listed hosts only (`www.steamgriddb.com`, `cdn.steamgriddb.com`, `cdn2.steamgriddb.com`), no userinfo, no redirects, explicit `ssl.create_default_context()`, 6 s timeout, 256 KB JSON / 8 MB image caps, CRLF key validation, PNG/JPEG/WebP magic validation, and **Windows DPAPI encryption at rest** (`gamehub/core/secrets.py`) for the SteamGridDB API key. Steam covers & cover cache are 100% local/offline. Zero telemetry. |
| **(C3) Local Safety, Mods & CI** | [c3-local-safety.md](reviews/security/rc3/c3-local-safety.md) | **PASS (0 open)** | `SingleInstance` uses same-user ACL (`UserAccessOption`) and recovers cleanly after direct `os._exit(0)` (regression-tested). Custom-folder per-user installer validates destination in both interactive and `/VERYSILENT` modes and validates quiet uninstallers. Translations & Mods permanently locked on all protected/online games (including uncached `_assert_not_protected()` + 15 s UI cache TTL), rejects executables/scripts/PE headers/zip bombs/path traversal/symlinks. All CI actions pinned to 40-char commit SHAs with `SHA256SUMS.txt`. |
| **(C4) Packaging & Frozen Binary** | [c4-packaging.md](reviews/security/rc3/c4-packaging.md) | **PASS (0 open)** | After size cuts: `123.24 MiB` unpacked / `50.98 MiB` portable zip (CI limits `< 200 MiB` / `< 70 MiB`). All 85 PE files audited: **0** `psutil`, **0** `cv2`/`opencv`, **0** `opengl32sw.dll`, **0** QML/Quick, **0** stray DLLs, **0** UPX. Embedded `asInvoker` (`uiAccess="false"`) manifest + `VERSIONINFO` + 32 third-party license files intact. Clean Python-free `PATH` `--smoke-test` exits `0` (including WGC+WebP pipeline without OpenCV). Windows Defender `MpCmdRun.exe` scan enforced in CI. |

---

## 2. Real Frozen Exit Latency Benchmarks (240 Trials on `dist\GameRewind\GameRewind.exe`)

Measured wall-clock milliseconds from spawning a harmless renamed copy of `System32\ping.exe` until `GameRewind.exe` completely disappeared from the Windows process table (raw trial data: [docs/perf/rc3-results-raw.json](perf/rc3-results-raw.json)):

| Scenario (40 Real Trials Each) | Min | Average | P95 | Max | Target (`P95 < 200`, `Max < 300`) |
| --- | --- | --- | --- | --- | --- |
| **Fortnite** (`FortniteLauncher.exe`) — Normal | 40.89 ms | **80.66 ms** | **149.97 ms** | **166.29 ms** | **PASS** ✅ |
| **Valorant** (`VALORANT.exe`) — Normal | 37.43 ms | **82.22 ms** | **171.31 ms** | **180.46 ms** | **PASS** ✅ |
| **EA SPORTS FC** (`FC26.exe`) — Normal | 33.92 ms | **85.23 ms** | **141.14 ms** | **153.84 ms** | **PASS** ✅ |
| **Fortnite** (`FortniteLauncher.exe`) — Under UI Load | 42.89 ms | **75.30 ms** | **133.45 ms** | **137.37 ms** | **PASS** ✅ |
| **Valorant** (`VALORANT.exe`) — Under UI Load | 41.74 ms | **81.97 ms** | **154.56 ms** | **163.47 ms** | **PASS** ✅ |
| **EA SPORTS FC** (`FC26.exe`) — Under UI Load | 39.70 ms | **86.91 ms** | **135.70 ms** | **153.34 ms** | **PASS** ✅ |

*Also verified in `tests/test_performance_regressions.py`: direct guard-thread `os._exit(0)` exits in `< 200 ms` even if the Qt main UI thread is completely frozen for 5 seconds.*

---

## 3. Evidence-Based Riot Vanguard Decision (`vgk` / `vgc` / `vgtray`)

Unchanged from M21 and re-verified by C1:
- Keep always-on `vgk` (boot driver), `vgtray.exe`, `vgm.exe`, and idle `vgc` / `vgc.exe` **out** of the active-session blocklist (matching `EAAntiCheatService`), while strictly blocking on **every** Riot Client executable (`RiotClientServices.exe`, `RiotClientUx.exe`, `RiotClientUxRender.exe`, `RiotClientCrashHandler.exe`, `Riot Client.exe`, `LeagueClient.exe`, `LeagueClientUx.exe`, `LeagueClientUxRender.exe`) and every Vanguard-protected game executable (`VALORANT.exe`, `VALORANT-Win64-Shipping.exe`, `League of Legends.exe`, `2XKO.exe`, `lion.exe`, `lion-win64-shipping.exe`).
- GameRewind exits completely in **~82 ms avg (max 180 ms)** the moment Riot Client or any Riot game starts, while remaining 100% usable for single-player games when Riot Client is closed.

---

## 4. `v1.2.0-rc.3` Security Remediation Highlights

- **Multi-launcher EA SPORTS FC & 2026 catalog coverage:** Added Epic/EA/Xbox/Steam IDs and normalized title matching (`EA SPORTS FC`, `FC 24/25/26/27`, `GTA V / GTA V Enhanced`, `Marvel Rivals`, `Wuthering Waves`, `Roblox`, `Dota 2`, `Battlefield 6`, `Call of Duty` Battle.net) plus bounded depth-3 Epic executable discovery.
- **Windows DPAPI encryption for SteamGridDB API key:** Replaced plaintext SQLite storage with user-scoped `crypt32.CryptProtectData` / `CryptUnprotectData` (`gamehub/core/secrets.py`), restricted via AST tests.
- **Hardened SteamGridDB HTTP client:** Blocked userinfo/non-443 URLs, added explicit `ssl.create_default_context()`, CRLF `api_key` rejection, and PNG/JPEG/WebP magic-byte verification.
- **UI-thread-independent emergency exit & fast PID-diff guard:** Eliminated the 200 ms `QueuedConnection` bottleneck (`361 ms -> 82 ms` avg exit) while cutting idle CPU by 4× (`5.65% -> 1.43%` of 1 core) using handle-free `K32EnumProcesses`.

*See also: Egyptian Arabic owner summary in [docs/SECURITY-AUDIT-v1.2-AR.md](SECURITY-AUDIT-v1.2-AR.md).*
