# Security Audit Report — Focus (f): Riot Vanguard (`vgc` / `vgk` / `vgtray`) Edge Case

- **Audit date:** 2026-11-24
- **Auditor:** Independent Red-Team Security Auditor (Focus `f`)
- **Scope:** Real Windows 11 host inspection (read-only) + `gamehub/core/protection/protected_games.json`, `catalog.py`, `guard.py`, `lifecycle.py`, `gamehub/app.py`, `gamehub/core/library/riot.py`, `docs/research/anti-cheat.md`, `tests/test_zero_presence_guard.py`.
- **Constraints honored:** Strictly read-only OS queries; zero real anti-cheat games launched; zero source/test files modified.

---

## 1. Real Windows PC Evidence (Read-Only Inspection)

Inspected directly on this Windows 11 host on 2026-11-24 (no Riot game or Riot Client running at inspection time):

### 1.1 Service States, Registry Config, and DACLs

| Service | Type | Start Type (`sc.exe qc` / Registry `Start`) | Current State (`sc.exe queryex`) | Binary Path | Non-Admin `WindowsServiceProbe` |
| --- | --- | --- | --- | --- | --- |
| `vgk` | `1 KERNEL_DRIVER` | `1 SYSTEM_START` (`Start = 1`) | **`4 RUNNING`** (`STOPPABLE, NOT_PAUSABLE, IGNORES_SHUTDOWN`) | `\??\C:\Program Files\Riot Vanguard\vgk.sys` | `running: {'vgk'}` (`avail: True`) |
| `vgc` | `10 WIN32_OWN_PROCESS` (`LocalSystem`) | `3 DEMAND_START` (`Start = 3`, Manual) | `1 STOPPED` (`WIN32_EXIT_CODE = 1077 / 0x435`, never started since 2026-11-21 boot) | `C:\Program Files\Riot Vanguard\vgc.exe` | Not running |

- **SDDL (`sc.exe sdshow vgc` & `sc.exe sdshow vgk`):**
  `D:(A;;CCLCSWRPWPDTLOCRRC;;;WD)(A;;CCLCSWRPWPDTLOCRRC;;;SY)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)(A;;CCLCSWLOCRRC;;;IU)(A;;CCLCSWLOCRRC;;;SU)`
  Currently grants `WD` (Everyone) and `IU` (Interactive Users) `LC` (`SERVICE_QUERY_STATUS`), so `WindowsServiceProbe` succeeds without admin today.

### 1.2 Installed Vanguard & Riot Client Binaries on Disk

- **`C:\Program Files\Riot Vanguard\`:** `vgk.sys` (113.7 MB), `vgc.exe` (155.9 MB), `vgm.exe` (56.7 MB), `vgtray.exe` (7.3 MB), `vgrl.dll` (11.6 MB), `log-uploader.exe`, `uninstall.exe`.
- **`E:\Valorant1\Riot Games\Riot Client\`:**
  - `RiotClientServices.exe`
  - `RiotClientCrashHandler.exe`
  - **`RiotClientElectron\Riot Client.exe`** (modern Electron UI binary — replaced legacy `RiotClientUx.exe`)
- **`E:\Valorant1\Riot Games\VALORANT\live\`:** `VALORANT.exe`, `ShooterGame\Binaries\Win64\VALORANT-Win64-Shipping.exe`.

### 1.3 Auto-Start Registry Entries Found on This PC

- `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run`:
  - `Riot Vanguard` = `"C:\Program Files\Riot Vanguard\vgtray.exe"` (registered by default on Vanguard install; manually disabled in Task Manager Startup on this PC: `StartupApproved\Run` byte 0 = `3`).
- `HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Run`:
  - `RiotClient` = `E:\Riot Games\Riot Client\RiotClientServices.exe --launch-background-mode` (registered by default on Riot Client install; manually disabled in Task Manager Startup on this PC: `StartupApproved\Run` byte 0 = `3`).

### 1.4 Historical Session Evidence on This PC (`Microsoft-Windows-FilterManager` + `Riot Vanguard\Logs`)

- Boot on `2026-11-21 17:24:33`: `vgk_2026-11-21_17-24-33.log` created and `vgk` stayed `RUNNING` continuously through `2026-11-24` with zero `vgc` log created (no Riot game launched since reboot).
- Prior session on `2026-11-20`:
  - `18:56:37`: FilterManager loaded `vgk` filter → `vgc_2026-11-20_18-57-10.log` → `19:05:09` filter unloaded / `19:05:12` `vgc` log closed.
  - `20:16:49`: FilterManager loaded `vgk` filter → `vgc_2026-11-20_20-16-52.log` → `21:01:29` filter unloaded / `21:01:33` `vgc` log closed.

---

## 2. Riot Vanguard Real-World Lifecycle on Windows 10/11

Riot Vanguard splits into four distinct components whose idle behavior differs sharply from on-demand anti-cheats like EAC (`EasyAntiCheat_EOS`) and BattlEye (`BEService`):

1. **`vgk.sys` (Ring-0 kernel driver):** `StartType = System` (`1`). **Always running from Windows boot to shutdown** on standard installs (except Windows 11 systems running Vanguard's optional On-Demand mode). Unloading it requires rebooting before playing Valorant or League of Legends again.
2. **`vgtray.exe` (system tray UI):** Registered in `HKLM\...\Run` by default. **Runs from Windows login on most PCs** even when no Riot game or Riot Client is open.
3. **`vgc` service (`vgc.exe`, LocalSystem user-mode service):**
   - Installed with `StartType = Manual` (`3`) by default, **HOWEVER**:
     - **(a) Post-session persistence:** On standard Vanguard setups, after a user plays Valorant or League of Legends and closes both the game and Riot Client, `vgc` commonly **stays `Running` until reboot** (or manual `net stop vgc` / tray "Exit Vanguard", which then forces a PC reboot to play Riot games again).
     - **(b) `StartType = Automatic` (very widespread):** Riot Support's official troubleshooting articles and virtually every community guide for **VAN 1067** and **VAN 9003** explicitly instruct players to open `services.msc`, change **`vgc` Startup Type to `Automatic`**, start it, and reboot. On every PC where a player has ever applied that fix, **`vgc` (`vgc.exe`) is ALWAYS `Running` from boot to shutdown**, even when Valorant, League of Legends, and Riot Client are completely closed.
4. **Riot Client (`RiotClientServices.exe` / `Riot Client.exe`):**
   - Installed with **Open Riot Client on startup** (`HKCU\...\Run` with `--launch-background-mode`) and **Close window → Minimize to system tray** enabled by default. Unless the user changes Riot Client settings or explicitly right-clicks the tray icon → Exit, `RiotClientServices.exe` stays silently running in the background.

---

## 3. Audit Findings

### [F-01] HIGH — Unconditional Block on `vgc` Service & `vgc.exe` Causes Permanent Startup Lockout on Real Vanguard PCs

- **Locations:**
  - `gamehub/core/protection/protected_games.json:24` (`"anti_cheat_services": [..., "vgc"]`)
  - `gamehub/core/protection/protected_games.json:30` (`"global_anti_cheat_exes": [..., "vgc.exe", ...]`)
  - `gamehub/core/protection/protected_games.json:48, 63` (`valorant` and `league_of_legends` `anti_cheat_exes: ["vgc.exe"]`)
  - `gamehub/core/protection/catalog.py:38, 44` (`DEFAULT_ANTI_CHEAT_SERVICES`, `DEFAULT_GLOBAL_ANTI_CHEAT_EXES`)
  - `gamehub/core/protection/guard.py:367-389, 406-414`
  - `gamehub/app.py:397, 408-421`
  - `docs/research/anti-cheat.md:78, 95, 97` (inaccurate assumption that `vgc` is always `Stopped` until launch)
  - `tests/test_zero_presence_guard.py:112` (locks in refusal on `{"vgc"}` alone)
- **Evidence & Reproduction:**
  1. `ProtectionGuard._check_once_locked()` triggers unconditionally on `"vgc.exe"` via `global_anti_cheat_exes` (`guard.py:367-376`), via per-game `anti_cheat_exes` (`guard.py:378-389`), and on `"vgc"` via `anti_cheat_services` (`guard.py:406-414`).
  2. `app.py:397` executes `protection_guard.self_check()` before creating the main window or opening Settings.
  3. On any PC where (a) the user changed `vgc` to `Automatic` per Riot's VAN 1067 / VAN 9003 fix, or (b) `vgc` stayed `Running` after a Valorant/LoL session, GameRewind **refuses to start at all** even when **zero Riot Client and zero Riot games are running**.
  4. Because `global_anti_cheat_exes` and `anti_cheat_services` cannot be disabled via Settings (and Settings cannot even be opened when startup is refused), the user is **100% locked out of GameRewind** until they either reboot their PC or stop `vgc` (which breaks Valorant/LoL until reboot).
  5. **Secondary fail-closed brick risk (`guard.py:211-214`):** `WindowsServiceProbe.running_services()` treats `OpenServiceW("vgc", SERVICE_QUERY_STATUS)` returning `ERROR_ACCESS_DENIED (5)` as a fatal `ProtectionCheckError` (exit code 2). If a future Vanguard update tightens `vgc`'s service DACL against non-admin `WD`/`IU` queries, every Vanguard PC would permanently crash-exit GameRewind with *"Protection could not start"*.
  6. **Precedent already established in this codebase:** `docs/research/anti-cheat.md:97` already documented and fixed this exact same class of bug for `EAAntiCheatService` (EA Javelin), removing the background service from `anti_cheat_services` and relying on launch-stage and game executables instead. `vgc` was mistakenly assumed to be always-stopped because this single dev PC had not launched Valorant since reboot.
- **Recommended Fix:**
  1. Remove `"vgc"` from `anti_cheat_services` in `protected_games.json:24` and `DEFAULT_ANTI_CHEAT_SERVICES` in `catalog.py:38`.
  2. Remove `"vgc.exe"` from `global_anti_cheat_exes` (`protected_games.json:30`, `catalog.py:44`) and from `valorant.anti_cheat_exes` / `league_of_legends.anti_cheat_exes` (`protected_games.json:48, 63`).
  3. Keep `always_strict_launchers["riot"]`, `launcher_stage_exes`, and `game_exes` as the active Vanguard Zero-Presence triggers (see Section 4 policy matrix and F-03).
  4. Update `docs/research/anti-cheat.md` (Section 3 & Section 4) to document the real `vgc` idle/Automatic lifecycle alongside the `EAAntiCheatService` finding.
  5. Replace `tests/test_zero_presence_guard.py:112` (`([], {"vgc"}, "vgc")`) with an explicit **regression test** asserting that idle `vgc` service + `vgc.exe` + `vgtray.exe` + `vgk` do **not** block startup when no Riot Client / Riot game is running, while any Riot Client or Riot game process still blocks startup and triggers <1 s exit.

---

### [F-02] MEDIUM — Generic Startup Refusal Dialog Hides Which Trigger Blocked Launch (Severe Friction With Default Riot Client Tray Mode)

- **Locations:**
  - `gamehub/app.py:408-421` (generic dialog text omits `startup_trigger.display_name`)
  - `gamehub/app.py:409-413` vs `gamehub/app.py:454` (`startup_refused_protected` logged before `_add_file_log(data_root)` attaches file logging, so the refusal reason is lost from log files)
- **Evidence & Reproduction:**
  1. On default Riot Client installations (confirmed on this PC via `HKCU\...\Run\RiotClient` = `RiotClientServices.exe --launch-background-mode`), Riot Client either auto-starts into the system tray or minimizes to the system tray when the user clicks `X`.
  2. `ProtectionGuard` correctly blocks startup on `RiotClientServices.exe` (`always_strict_launchers["riot"]`).
  3. However, `app.py:414-420` shows only:
     > `"A protected game or its launcher is running — GameRewind won't run alongside it. Close it first."`
  4. It does **not** name `"Riot Client"` (`startup_trigger.display_name`) and does **not** remind the user to check the Windows System Tray. Because no visible window is open on the taskbar and the log line at `app.py:409` is emitted before `_add_file_log` at `app.py:454`, neither the user nor support diagnostics can see why GameRewind refused to open.
- **Recommended Fix:**
  1. Include `startup_trigger.display_name` in the refusal dialog (English & Arabic translations), e.g.:
     - When `startup_trigger.kind == "strict_launcher"` (especially `"Riot Client"`):
       `"{name} is currently running (check the Windows System Tray near the clock and choose Exit) — GameRewind won't run alongside it."`
     - Otherwise:
       `"{name} is currently running — GameRewind won't run alongside it. Close it first."`
  2. Keep zero-write behavior before refusal (do not create `gamehub.db` or logs when refused; showing `display_name` in the dialog solves user visibility without writing to disk).

---

### [F-03] MEDIUM — Incomplete Riot / Vanguard Process & Product Coverage (`Riot Client.exe`, CEF Renderers, and Vanguard-Protected `2XKO`)

- **Locations:**
  - `gamehub/core/protection/protected_games.json:5-11` and `gamehub/core/protection/catalog.py:19-25` (`always_strict_launchers["riot"]`)
  - `gamehub/core/protection/protected_games.json:35-65` (`games` entries for Riot titles)
  - `gamehub/core/library/riot.py:22` (`"lion": "2XKO"` already detected by `RiotDetector`)
  - `gamehub/core/protection/lifecycle.py:80-98` (`on_play_launched` relies on `catalog.effective_mode` == `"strict"`)
- **Evidence & Reproduction:**
  1. **Missing modern Riot Client frontend binary:** Real-PC inspection of `E:\Valorant1\Riot Games\Riot Client\` confirmed Riot replaced legacy `RiotClientUx.exe` with **`RiotClientElectron\Riot Client.exe`** (`riot client.exe`). `always_strict_launchers["riot"]` lists `riotclientux.exe` but omits `"riot client.exe"`, `"riotclientuxrender.exe"`, and `"leagueclientuxrender.exe"`.
  2. **Missing Vanguard-protected game `2XKO` (`lion`):** `RiotDetector` (`riot.py:22`) discovers `"lion"` as `"2XKO"`, which requires **Riot Vanguard** (`lion.exe` / `lion-win64-shipping.exe`). Because `protected_games.json` has no `2XKO` entry, `catalog.match_game(GameSource.RIOT, "lion.live", ...)` returns `None`:
     - `2XKO` defaults to `"full"` (unprotected) mode instead of `"strict"`.
     - Clicking **Play** on 2XKO in GameRewind hits `lifecycle.py:96-98` (minimizes GameRewind instead of exiting immediately + saving a pending note), leaving a ~300 ms race window while Riot Client spawns before `ProtectionGuard` catches `RiotClientServices.exe`.
- **Recommended Fix:**
  1. Add `"riot client.exe"`, `"riotclientuxrender.exe"`, and `"leagueclientuxrender.exe"` to `always_strict_launchers["riot"]` in both `protected_games.json` and `catalog.py:DEFAULT_ALWAYS_STRICT_LAUNCHERS`.
  2. Add a `2xko` entry to `protected_games.json` with `anti_cheat: "Riot Vanguard"`, `privilege: "kernel"`, `starts_at: "boot"`, `default_mode: "strict"`, `riot_product_ids: ["lion"]`, `launcher_stage_exes: ["lion.exe"]`, `anti_cheat_exes: []`, `game_exes: ["lion-win64-shipping.exe"]`.
  3. Add unit test assertions in `tests/test_zero_presence_guard.py` verifying `Riot Client.exe` triggers `strict_launcher` and `2XKO` (`lion.live` / `Lion-Win64-Shipping.exe`) resolves to `strict`.

---

### [F-04] INFO (Observation) — `vgk.sys`, `vgtray.exe`, and `vgm.exe` Must Remain Excluded From Active-Session Blocklists

- **Locations:** `gamehub/core/protection/protected_games.json:20-34`, `gamehub/core/protection/catalog.py:34-48`.
- **Observation:** `vgk` (`vgk.sys`, `SYSTEM_START` kernel driver), `vgtray.exe` (`HKLM\...\Run` tray icon), and `vgm.exe` (Vanguard updater/helper) are currently **not** in `anti_cheat_services` or `global_anti_cheat_exes`. This is correct and must remain so — adding any of them would permanently lock out every user with Vanguard installed from boot to shutdown. Recommend documenting this explicitly in `protected_games.json` / `anti-cheat.md` and asserting it in tests so future contributors do not regress it.

---

## 4. Recommended Evidence-Based Policy Matrix for Riot Vanguard

| Component | Real-World Lifecycle | Block / Auto-Exit? | Rationale |
| --- | --- | --- | --- |
| `vgk.sys` (`vgk` driver) | `SYSTEM_START`, always running from boot | **NO (Allow when idle)** | Boot-time kernel driver; blocking makes GameRewind unusable on any PC with Vanguard installed. GameRewind loads 0 drivers, uses `asInvoker`, opens 0 handles to Riot processes. |
| `vgtray.exe` | `HKLM\...\Run`, runs from login on most PCs | **NO (Allow when idle)** | Pure system tray status UI; runs whenever Windows starts. |
| `vgm.exe` | Vanguard module/updater helper | **NO (Allow when idle)** | Runs for background updates/maintenance outside gameplay. |
| `vgc` service / `vgc.exe` | Often `Running` while idle (post-game persistence OR `StartType=Automatic` per Riot VAN 1067 / VAN 9003 fix) | **NO (Allow when idle)** | Matches proven `EAAntiCheatService` policy (`anti-cheat.md:97`). Blocking `vgc` bricks GameRewind for users who played Riot earlier or applied Riot Support's `Automatic` fix, while adding negligible safety beyond `vgk.sys` (already loaded at boot) + blocking Riot Client/games below. |
| `RiotClientServices.exe`, `Riot Client.exe`, `RiotClientUx.exe`, `RiotClientUxRender.exe`, `RiotClientCrashHandler.exe` | Active whenever Riot Client is open (including tray) | **YES — `always_strict_launchers["riot"]` (Stage 0)** | Non-disableable Zero-Presence barrier BEFORE any Riot game can launch. Must name `"Riot Client"` + mention System Tray in startup refusal dialog (F-02). |
| `LeagueClient.exe`, `LeagueClientUx.exe`, `LeagueClientUxRender.exe` | Active whenever League / TFT client opens | **YES — `always_strict_launchers["riot"]` + `launcher_stage_exes`** | Immediate exit before match/game client launches. |
| `VALORANT.exe`, `VALORANT-Win64-Shipping.exe`, `League of Legends.exe`, `lion.exe`, `Lion-Win64-Shipping.exe` | Active when Valorant / LoL / 2XKO launches or runs | **YES — `launcher_stage_exes` / `game_exes`** | Guaranteed Zero-Presence fallback + immediate exit on Play launch (`LifecycleCoordinator`). |

### Why This Policy Is Both Safe and Usable

1. **Zero-Presence before any protected game runs:** You cannot start Valorant, League of Legends, TFT, or 2XKO without Riot Client (`RiotClientServices.exe` / `Riot Client.exe`) and the game's own bootstrapper/executable. GameRewind exits in <500 ms the moment Riot Client opens (Stage 0), long before the user even clicks Play or the game window initializes.
2. **Defense in depth while `vgk.sys`/`vgc.exe` idle:** While the user plays single-player games with GameRewind, GameRewind runs as standard non-admin (`asInvoker`), loads zero kernel drivers, injects zero DLLs, installs zero global Windows hooks (`SetWindowsHookEx`), sends zero synthetic input, and opens zero handles to any Vanguard or Riot process.
3. **Honest uncertainty statement:** Riot Vanguard is closed-source, so no third party can mathematically guarantee internal telemetry rules never change. However, `vgk.sys` is *already* active from boot on every Vanguard machine regardless of `vgc`, and millions of PCs run `vgc` on `Automatic` (Riot Support's own documented fix) alongside Playnite, Steam, Discord, OBS, browsers, and developer tools with no ban risk when no Riot game is running. Removing `vgc` from the hard lockout list eliminates a guaranteed product-breaking bug without materially weakening real anti-cheat safety.

---

## 5. Honest Plain-Language Explanation for the Owner

> **What we found:** Right now, GameRewind refuses to open if Riot Vanguard's background service (`vgc`) is running. On your PC right now, `vgc` happened to be stopped because you hadn't played Valorant since your last restart — so everything looked fine during testing.
>
> **Why that breaks in real life:** On most players' PCs, `vgc` **stays running in the background** after you finish a match of Valorant or League of Legends until you restart Windows. Even more commonly, Riot Support's own official fix for `VAN 1067` and `VAN 9003` tells players to set `vgc` to **Automatic** so it runs 24/7 from the moment Windows boots. On any PC like that, GameRewind would **refuse to open at all** — even when Valorant and Riot Client are completely closed — and would only show a vague error without explaining why.
>
> **Why changing this is safe:** Vanguard's kernel driver (`vgk.sys`) is *already* running from boot whenever Windows is on, and GameRewind already never injects, never hooks, never reads memory, never loads drivers, and never touches Riot processes. By stopping GameRewind from blocking on idle `vgc` (just like we already do for EA's `EAAntiCheatService`), while **keeping the strict instant-exit rule** for **Riot Client** (`RiotClientServices.exe` / `Riot Client.exe`), **Valorant**, **League of Legends**, and **2XKO**, GameRewind will always be 100% closed before any Riot game can even start — and will actually work when you want to play single-player games after a Valorant session.
>
> **One extra tip for users:** Riot Client loves to hide in the Windows System Tray (the little arrow next to the clock) when you click `X`. Showing `"Riot Client is running — right-click it in the System Tray and click Exit"` in GameRewind's startup popup will save players a lot of confusion.

---

## 6. Verdict

**FAIL — 3 open findings (`F-01` [HIGH], `F-02` [MEDIUM], `F-03` [MEDIUM]); 1 informational observation (`F-04` [INFO]).**


---

## Round 2 Re-Audit Verification

- **Re-audit date:** 2026-11-24
- **Auditor:** Independent Red-Team Security Auditor (Focus `f` & `g`)
- **Verification Scope:** Current source (`gamehub/core/protection/protected_games.json`, `catalog.py`, `guard.py`, `gamehub/app.py`, `gamehub/core/i18n/catalog.py`, `gamehub/core/sessions/processes.py`, `gamehub/core/notifications/windows.py`, `tests/test_zero_presence_guard.py`), rebuilt `dist\GameRewind\_internal\gamehub\core\protection\protected_games.json`, pytest run (`15 passed in 1.98s`), and live Windows 11 Toolhelp32 dummy-process + read-only SCM verification (`vgk` running on host).

### Per-Finding Verification Status

| ID | Round 1 Severity | Round 2 Status | Verification Evidence |
| --- | --- | --- | --- |
| **F-01** | HIGH | **CLOSED** | `"vgc"` removed from `anti_cheat_services` (`protected_games.json:23-27`, `catalog.py:37-41`); `"vgc.exe"` removed from `global_anti_cheat_exes` (`protected_games.json:28-36`, `catalog.py:42-50`) and from `valorant`/`league_of_legends`/`2xko` `anti_cheat_exes` (`protected_games.json:50,65,80`). Identically verified in rebuilt `dist\GameRewind\_internal\gamehub\core\protection\protected_games.json`. `gamehub/core/sessions/processes.py:50-52` explicitly skips `vgtray.exe`, `vgc.exe`, and `vgm.exe` (zero `OpenProcess` handles). Live real-host `ProtectionGuard.self_check()` (with `vgk` running) returned `None`; real Windows Toolhelp32 dummy-process test running `vgc.exe` + `vgtray.exe` + `vgm.exe` with simulated running `{"vgc", "vgk"}` services returned `None`. Regression test locked in at `tests/test_zero_presence_guard.py:132-138`. |
| **F-02** | MEDIUM | **CLOSED** | `gamehub/app.py:459-469` now formats trigger-specific refusal text naming `startup_trigger.display_name`, with an explicit system tray hint when `startup_trigger.kind == "strict_launcher"` (`"{name} is running (check the system tray if you closed its window) — GameRewind won't run alongside it. Close it first."`). Exact matching Arabic translations added at `gamehub/core/i18n/catalog.py:573-578`. Refusal runs before creating `gamehub.db` (zero-write verified) and uses non-blocking `_notify_guard_block` (no blocking `QMessageBox` keeping the process alive). Verified by `tests/test_zero_presence_guard.py:106-130`. *(See INFO observation below on `WindowsNotifier` stub.)* |
| **F-03** | MEDIUM | **CLOSED** | `always_strict_launchers["riot"]` in both `protected_games.json:5-14` and `catalog.py:19-28` now includes `"riot client.exe"`, `"riotclientuxrender.exe"`, and `"leagueclientuxrender.exe"`. Added `2xko` entry at `protected_games.json:68-82` (`riot_product_ids: ["lion", "2xko"]`, `launcher_stage_exes: ["2xko.exe", "lion.exe"]`, `game_exes: ["lion-win64-shipping.exe", "2xko-win64-shipping.exe"]`, `default_mode: "strict"`). Verified `catalog.match_game(GameSource.RIOT, "lion.live")` resolves to `2xko` (`effective_mode == "strict"`). Live real Windows Toolhelp32 dummy-process verification confirmed instant detection of `Riot Client.exe` (`strict_launcher`), `RiotClientUxRender.exe` (`strict_launcher`), `LeagueClientUxRender.exe` (`strict_launcher`), `VALORANT.exe` (`launcher_stage`), `League of Legends.exe` (`game_exe`), `lion.exe` (`launcher_stage`), and `Lion-Win64-Shipping.exe` (`game_exe`). |
| **F-04** | INFO | **CLOSED (Confirmed)** | `vgk`, `vgtray.exe`, and `vgm.exe` remain absent from active blocklists, explicitly skipped in `processes.py:50-52`, and covered by `tests/test_zero_presence_guard.py:132-138`. |

### Live Round 2 Test Evidence

```text
Catalog matching OK: valorant, league_of_legends, 2xko (lion.live)
Exclusion check OK: vgc, vgk, vgc.exe, vgtray.exe, vgm.exe absent from all active lists
Real host ProtectionGuard.self_check(): None
Real dummy idle vgc.exe/vgtray.exe/vgm.exe + vgc/vgk svc -> None
Real dummy 'Riot Client.exe' -> ProtectionTrigger(kind='strict_launcher', identifier='riot client.exe', display_name='Riot Client', stage='launcher', entry_id=None)
Real dummy 'RiotClientUxRender.exe' -> ProtectionTrigger(kind='strict_launcher', identifier='riotclientuxrender.exe', display_name='Riot Client', stage='launcher', entry_id=None)
Real dummy 'LeagueClientUxRender.exe' -> ProtectionTrigger(kind='strict_launcher', identifier='leagueclientuxrender.exe', display_name='Riot Client', stage='launcher', entry_id=None)
Real dummy 'VALORANT.exe' -> ProtectionTrigger(kind='launcher_stage', identifier='valorant.exe', display_name='Valorant', stage='launcher_stage', entry_id='valorant')
Real dummy 'League of Legends.exe' -> ProtectionTrigger(kind='game_exe', identifier='league of legends.exe', display_name='League of Legends', stage='game', entry_id='league_of_legends')
Real dummy 'lion.exe' -> ProtectionTrigger(kind='launcher_stage', identifier='lion.exe', display_name='2XKO', stage='launcher_stage', entry_id='2xko')
Real dummy 'Lion-Win64-Shipping.exe' -> ProtectionTrigger(kind='game_exe', identifier='lion-win64-shipping.exe', display_name='2XKO', stage='game', entry_id='2xko')
pytest tests/test_zero_presence_guard.py tests/test_packaging.py -> 15 passed in 1.98s
```

### Round 2 Informational Observations (Non-Blocking)

- **INFO-F1 (`WindowsNotifier` Production Toast Delivery Stub):** While `gamehub/app.py:459-469` formats the exact trigger-specific refusal message (and Arabic translations in `catalog.py:573-578`), in production (`show_guard_dialog=None`) `_notify_guard_block` calls `WindowsNotifier().notify_protected_game(...)` where `_deliver_shell_toast_xml` (`gamehub/core/notifications/windows.py:47-54`) is currently a no-op placeholder returning `False` (intentionally avoiding PowerShell/tray icons). As a result, production startup refusal exits cleanly and safely with zero blocking window and zero disk writes, but displays no visible toast yet. Implementing native WinRT `ToastNotificationManager` COM delivery in a future update will surface the refusal message visually to end users.
- **INFO-F2 (Historical Research Doc Text):** `docs/research/anti-cheat.md:61,78,84,95,97` still describes `vgc` as included in `anti_cheat_services`; update those lines to match the remediated policy.

### Round 2 Verdict (Focus f)

**PASS** (0 open findings; `F-01`, `F-02`, `F-03` CLOSED; `F-04` confirmed).
