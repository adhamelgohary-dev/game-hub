# Anti-Cheat Landscape & Zero-Presence Protocol Research (Game Hub v1.2 — v2)

**Research date:** 2026-11-24 (expanded from v1.1 report dated 2026-11-23)  
**Purpose:** Establish an evidence-based **Zero-Presence Anti-Cheat Protocol** for Game Hub v1.2 so the practical ban risk—especially for *Fortnite* and *Valorant*—is effectively **zero**: equal to not having Game Hub installed at all while any protected game, its anti-cheat, or its launch sequence is active.

> **Honesty & uncertainty note:** Commercial anti-cheat vendors (Riot Vanguard, Epic/EAC, BattlEye, Activision RICOCHET, EA Javelin, Valve VAC) do not publish their full heuristic tables or internal allowlists, and detection rules evolve without public notice. Where vendor guidance is silent or ambiguous, this document states the uncertainty clearly and mandates the strictest safe behavior (**fail-closed + zero presence**).

---

## 1. Core Principle: Why Zero Presence = Zero Risk

Anti-cheat bans and kicks originate from software that **interacts with a protected game or system integrity boundary**:
- Process memory reads/writes (`OpenProcess` with VM rights, `ReadProcessMemory`, `WriteProcessMemory`)
- DLL injection or graphics/input hooks (`CreateRemoteThread`, `SetWindowsHookEx`, DirectX/Vulkan present hooks)
- Synthetic input / macros (`SendInput`, `keybd_event`, `mouse_event`)
- Vulnerable, unsigned, or blocklisted kernel drivers
- Topmost overlays rendered on top of the game window
- Modified or unsigned game/system files

Even mainstream, vendor-partnered apps (Discord overlay, OBS Game Capture, Overwolf, GeForce Experience) have occasionally caused false-positive kicks or bans when running alongside or hooking a protected game. Therefore, Game Hub v1.2 enforces **two independent guarantees simultaneously**:
1. **Never interact (Layer 1):** Zero memory reads, zero hooks, zero DLL injection, zero synthetic input, zero drivers, zero overlays on other windows, zero admin elevation, zero packers (no UPX), and zero `OpenProcess` handles on protected games.
2. **Never even be running (Layers 2–5):** Game Hub refuses to start if a protected game, its launch-stage process, its anti-cheat process/service, or the Riot Client is already active, and exits completely within ~0.5–1.0 seconds if one starts while Game Hub is open—before the anti-cheat bootstrap initializes.

---

## 2. How Reference Applications Stay Safe (and What We Copy)

### 2.1 Playnite (Open Source, MIT — `https://github.com/JosefNemec/Playnite`, retrieved 2026-11-24)
- **Game launching:** Playnite launches storefront titles through official launcher URIs (`steam://rungameid/<id>`, `com.epicgames.launcher://apps/<artifact>?action=launch&silent=true`, Riot Client command-line arguments, EA/Ubisoft/GOG/Battle.net protocols), handing off execution to the official storefront so Playnite is **not** the parent process of DRM/anti-cheat games.
- **Process tracking & window lifecycle:** Playnite watches running game processes passively and offers configurable actions on game start (minimize or close Playnite).
- **Elevation warning:** Playnite's official documentation and GitHub issue tracker explicitly warn **never to run Playnite as Administrator**, because elevated child processes inherit admin tokens that anti-cheats flag or block.
- **Anti-cheat reports:** Playnite itself has **no confirmed ban cases** caused by its core launcher; reported EAC/Vanguard errors trace back to third-party overlays/RGB utilities injecting into Playnite or custom user automation scripts.
- **Library discovery plugins (`PlayniteExtensions`):** Read-only local manifest, SQLite, and registry readers:
  - **Steam:** `libraryfolders.vdf` + `appmanifest_*.acf` + `appcache/librarycache/`
  - **Epic:** Legacy `%PROGRAMDATA%\Epic\EpicGamesLauncher\Data\Manifests\*.item` **and** modern per-user Epic Games Launcher registry entries under `HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\EpicGames-*` (`EpicAppId`, `InstallLocation`, `DisplayName`)
  - **Riot Client:** `%PROGRAMDATA%\Riot Games\RiotClientInstalls.json`, `%PROGRAMDATA%\Riot Games\Metadata\<product>\*.product_settings.yaml`, and `HKCU\...\Uninstall\Riot Game *`
  - **GOG Galaxy:** `%PROGRAMDATA%\GOG.com\Galaxy\storage\galaxy-2.0.db` (read-only SQLite `InstalledBaseProducts` / `LimitedDetails` / `PlayTasks`) + `HKLM\SOFTWARE\WOW6432Node\GOG.com\Games\*`
  - **EA app:** `%PROGRAMDATA%\EA Desktop\InstallData\*`, `HKLM\SOFTWARE\EA Games\*`, `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*` (Electronic Arts publisher)
  - **Ubisoft Connect:** `HKLM\SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs\*` (`InstallDir`) + `Uninstall\Uplay Install <id>`
  - **Battle.net:** `%PROGRAMDATA%\Battle.net\Agent\product.db` + `HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*` (Blizzard Entertainment) + `.build.info`
  - **itch.io:** `%APPDATA%\itch\db\butler.db` (read-only SQLite `caves` + `games`)
  - **Xbox / Game Pass:** Windows `AppX` packages (`Get-AppxPackage` / package registry) + `MicrosoftGame.config` under `XboxGames` roots.
- **What Game Hub copies (and makes stricter):** Official URI-only launching, never running as admin (`asInvoker`), read-only plugin detectors, and going **stricter than Playnite** by unconditionally refusing to run or auto-exiting (fail-closed) whenever a protected game, its anti-cheat, or the Riot Client is active.

### 2.2 Overwolf (`https://www.overwolf.com/`, incident coverage `charlieintel.com` / Activision Support, retrieved 2026-11-24)
- **Why Overwolf apps generally avoid bans:** Formal agreements with game publishers, exclusive use of approved game-event APIs (no direct memory reading, no gameplay-advantage features), and code-signed binaries.
- **Known false-positive incident (October 2021 — Call of Duty on Windows 11):** Early Windows 11 users running Overwolf overlays (notably Outplayed) alongside *Call of Duty: Warzone / Black Ops Cold War / Vanguard* experienced repeated overlay crash loops. Activision's RICOCHET anti-cheat flagged the hooks/crashes as unauthorized memory manipulation and issued **permanent, largely unreversed bans**.
- **Lesson for Game Hub:** Even publisher-partnered overlay frameworks are not immune to false positives if they run next to or hook a game. Game Hub refuses to inject overlays AND exits completely before protected games start.

### 2.3 Discord, Steam Overlay, NVIDIA App, and OBS Studio
- **Mechanism:** These tools inject EV/OV-signed graphics-hook DLLs (`GameOverlayRenderer64.dll`, `graphics-hook64.dll`, etc.) explicitly allowlisted by EAC, BattlEye, Riot, and EA.
- **Why this path is irrelevant to Game Hub:** Game Hub will **never** inject DLLs or hook DirectX/Vulkan/OpenGL. For single-player / non-protected games, Game Hub uses only OS compositor Windows Graphics Capture (`Windows.Graphics.Capture`); for protected games, Game Hub is not even running.

### 2.4 Riot Games Official Policy & 2026 Vanguard Memory-Access Change
- **Sources:**
  - Riot Games — *Third-Party Applications Policy & Vanguard FAQ* (`https://support-valorant.riotgames.com/hc/en-us/articles/360046160933-What-is-Vanguard`, retrieved 2026-11-24)
  - Riot Games — *2026 Vanguard Game-Memory Access Restrictions* (`https://www.riotgames.com/`, retrieved 2026-11-24)
- **Key facts:**
  - Riot prohibits third-party tools that read/write game memory or provide unfair gameplay information.
  - In **2026**, Riot rolled out a major Vanguard policy change **proactively blocking game-memory access by default for all unknown third-party apps** (with an extended migration grace period until April 2027 only for established, approved tools moving to official Riot APIs, and **no manual allow-list**).
  - **Game Hub compliance:** Game Hub never opens a handle to, reads memory from, or injects into any Riot process (enforced by automated AST/static code-scan tests), AND enforces **Zero-Presence** whenever the Riot Client (`RiotClientServices.exe` / `RiotClientUx.exe`), `vgc` service, *Valorant*, or *League of Legends* is active.

### 2.5 Epic Games / Easy Anti-Cheat (EAC) Official Guidance
- **Sources:**
  - Epic Games Support — *Troubleshooting Easy Anti-Cheat ("Game Security Violation" & "Untrusted System File")* (`https://www.epicgames.com/help/en-US/c-Category_Fortnite`, retrieved 2026-11-24)
  - Easy Anti-Cheat — *Official Site* (`https://www.easy.ac/`, retrieved 2026-11-24)
- **Key facts:**
  - `"Untrusted system file"` triggers when EAC encounters an unsigned, tampered, or unrecognized DLL loaded into the game process or a corrupted Windows system component.
  - `"Game Security Violation"` triggers when EAC detects unauthorized hooks, unsupported background overlays/RGB/macro utilities, or driver/process tampering while a protected game runs.
  - **Key launcher fact (verified locally on Windows 11):** The **Epic Games Launcher itself (`EpicGamesLauncher.exe`) runs NO anti-cheat**. EAC (`EasyAntiCheat_EOS`) and BattlEye (`BEService`) remain **Stopped** while browsing the Epic store or playing single-player Epic games (e.g., *Death Stranding*, *Hue*). They start **only** when a protected game's own launch sequence begins (`FortniteBootstrapper.exe` / `FortniteLauncher.exe`).

---

## 3. Question: Is Running Game Hub *Before* Valorant Opens a Risk Given `vgk.sys` Runs From Boot?

- **How Vanguard splits boot vs. game runtime (verified on this PC):**
  - `vgk` (`vgk.sys`, Ring-0 kernel driver): `StartMode = System`, `State = Running` from Windows boot.
  - `vgc` (`C:\Program Files\Riot Vanguard\vgc.exe`, user-mode service): `StartMode = Manual`, **`State = Stopped`** when Riot Client / Valorant is not running.
- **Evidence-based risk assessment:**
  - According to Riot's official Vanguard documentation, `vgk.sys` at boot enforces driver-signing / vulnerable-driver blocks (`VAN` errors) and protects kernel integrity so cheats cannot load before the OS finishes booting.
  - Vanguard is **not known to ban users** for running ordinary, non-driver, non-injecting desktop applications while no Riot client or game is running (millions of PCs run Python, browsers, IDEs, Playnite, Discord, etc. with `vgk.sys` active from boot).
  - **Uncertainty:** Because Vanguard's internal heuristics are closed-source, we still apply the strictest practical protection:
    1. Game Hub loads **zero drivers**, requests **no admin elevation** (`asInvoker`), and never calls `OpenProcess`, `ReadProcessMemory`, `WriteProcessMemory`, `CreateRemoteThread`, `SetWindowsHookEx`, or `SendInput` on any protected process.
    2. Game Hub **refuses to start** whenever `RiotClientServices.exe`, `RiotClientUx.exe`, `vgc` service, `VALORANT.exe`, `VALORANT-Win64-Shipping.exe`, or `League of Legends.exe` is running—and **exits immediately** (< 1 s) if any of them starts while Game Hub is open.
    3. Closing Game Hub exits the process completely (**zero background footprint**).

---

## 4. Exact Process & Service Launch Timelines

Every protected game in `gamehub/core/protection/protected_games.json` (schema v2) categorizes executables into three distinct stages plus on-demand anti-cheat services:
- `launcher_stage_exes`: Earliest process spawned when the user clicks Play — Game Hub exits here **before** the anti-cheat initializes.
- `anti_cheat_exes`: Anti-cheat bootstrapper / user-mode service processes.
- `game_exes`: Main game client executables.
- `anti_cheat_services` (catalog-level on-demand SCM services): `EasyAntiCheat_EOS`, `EasyAntiCheat`, `BEService`, `vgc`.

> **Critical real-PC finding (`EAAntiCheatService`):** Local inspection on Windows 11 with *EA SPORTS FC 27* installed confirmed that `EAAntiCheatService` (`eaanticheat.gameservice.exe`) can remain `Running` in the background even when no EA game is open (unlike `EasyAntiCheat_EOS`, `BEService`, and `vgc`, which are `Stopped` until launch). Treating `EAAntiCheatService` as an "active game" would permanently block Game Hub on PCs with EA Javelin installed. Therefore, EA Javelin titles are detected by their launch-stage bootstrapper **`EAAntiCheat.GameServiceLauncher.exe`** (which runs only when an EA protected game actually launches) plus all `fc24.exe`–`fc27.exe` / `bf*.exe` game executables.

### 4.1 Fortnite (Epic Games Store — verified against local `E:\epic games\Fortnite\FortniteGame\Binaries\Win64`)
1. User clicks **Fortnite** in Epic Games Launcher (or Game Hub opens `com.epicgames.launcher://apps/fn%3A4fe75bbc5a674f4f9b356b5c90567da5%3AFortnite?action=launch&silent=true` and exits immediately).
2. **Stage 1 (`launcher_stage_exes`, ~T+0.1 s):** `FortniteBootstrapper.exe` → `FortniteLauncher.exe` **(Game Hub exits here within ~0.3–0.6 s)**.
3. **Stage 2 (`anti_cheat_exes` / `anti_cheat_services`, ~T+2–6 s):** `FortniteClient-Win64-Shipping_EAC_EOS.exe` or `FortniteClient-Win64-Shipping_BE.exe`; `EasyAntiCheat_EOS` (`EasyAntiCheat_EOS.exe`) or `BEService` (`BEService.exe`) starts.
4. **Stage 3 (`game_exes`, ~T+8–20 s):** `FortniteClient-Win64-Shipping.exe` window opens.

### 4.2 Valorant (Riot Client — verified against local `E:\Valorant1\Riot Games\`)
1. **Stage 0 (Strict Launcher — Always Blocked):** `RiotClientServices.exe` / `RiotClientUx.exe` (`Riot Client`) starts **(Game Hub refuses to start or exits immediately here — before the user even clicks Play on Valorant)**.
2. **Stage 1 (`anti_cheat_services` / `anti_cheat_exes`):** `vgc` service (`vgc.exe`) starts (`vgk.sys` already loaded at boot).
3. **Stage 2 (`launcher_stage_exes`):** `VALORANT.exe` bootstrapper starts.
4. **Stage 3 (`game_exes`):** `VALORANT-Win64-Shipping.exe` window opens.

### 4.3 League of Legends (Riot Client)
1. **Stage 0 (Strict Launcher):** `RiotClientServices.exe` / `RiotClientUx.exe` → `LeagueClient.exe` / `LeagueClientUx.exe` **(Game Hub exits immediately)**.
2. **Stage 1 (`anti_cheat_services`):** `vgc` service (`vgc.exe`) runs.
3. **Stage 2 (`game_exes`):** `League of Legends.exe`.

### 4.4 EA SPORTS FC 24/25/26/27 & Battlefield (EA app / Steam / Epic)
1. User clicks Play in EA app / Steam (EA app itself is allowed by default for non-protected EA single-player titles like *Dead Space* or *It Takes Two*).
2. **Stage 1 (`launcher_stage_exes`):** `EAAntiCheat.GameServiceLauncher.exe` **(Game Hub exits here before game window opens)**.
3. **Stage 2 (`game_exes`):** `fc24.exe`, `fc25.exe`, `fc26.exe`, `fc27.exe`, `fc27_showcase.exe`, `fc27_trial.exe`, `bf2042.exe`, `bfv.exe`, `bf1.exe`.

### 4.5 Counter-Strike 2 & Deadlock (Steam — VAC / Trusted Mode)
1. User clicks Play in Steam (Steam itself is allowed by default for single-player games).
2. **Stage 1/2 (`game_exes`):** `cs2.exe` (CS2), `project8.exe` / `deadlock.exe` (Deadlock). VAC runs in user-mode inside the game/Steam context; Game Hub still exits immediately by default.

### 4.6 Other Catalog Games (EAC / BattlEye / RICOCHET / GameGuard / HoYoKProtect / ACE / Warden)
- **EAC games** (*Apex Legends*, *Rust*, *Elden Ring*, *Elden Ring Nightreign*, *Armored Core VI*, *Lords of the Fallen*, *Space Marine 2*, *Halo MCC/Infinite*, *Sea of Thieves*, *Dead by Daylight*, *THE FINALS*, *Lost Ark*, *For Honor*, *Fall Guys*, *War Thunder*): `launcher_stage_exes` includes `start_protected_game.exe`, `eac_launcher.exe`, `easyanticheat_launcher.exe`; `anti_cheat_exes` includes `easyanticheat.exe`, `easyanticheat_eos.exe`; SCM watches `EasyAntiCheat` and `EasyAntiCheat_EOS`.
- **BattlEye games** (*Rainbow Six Siege*, *PUBG*, *Destiny 2*, *DayZ*, *Escape from Tarkov*, *Arma 3*): `launcher_stage_exes` includes `*_be.exe`, `arma3battleye.exe`; `anti_cheat_exes` includes `beservice.exe`, `beclient_x64.dll` host `bedaisy` service `BEService`.
- **RICOCHET** (*Call of Duty*): `cod.exe`, `modernwarfare.exe`, `blackopscoldwar.exe`, `sp22-cod.exe`, `sp23-cod.exe`.
- **nProtect GameGuard** (*HELLDIVERS 2*): `gamemon.des`, `gamemon64.des`, `npggnt.des`, `helldivers2.exe`.
- **HoYoKProtect** (*Genshin Impact*, *Honkai: Star Rail*, *Zenless Zone Zero*): `genshinimpact.exe`, `yuanshen.exe`, `starrail.exe`, `zenlesszonezero.exe`.
- **Anti-Cheat Expert (ACE)** (*Delta Force*, *NARAKA: BLADEPOINT*): `sguard64.exe`, `sguardsvc64.exe`, `deltaforceclient-win64-shipping.exe`, `narakabladepoint.exe`.
- **Blizzard Warden** (*Overwatch 2*, *World of Warcraft*): `overwatch.exe`, `wow.exe`, `wowclassic.exe`.

---

## 5. Fast Detection Benchmark: WMI vs. Toolhelp32 + Read-Only SCM (Measured 2026-11-24)

Tested without Administrator privileges on Windows 11 (Build 26300, 322 running processes):
1. **`Win32_ProcessStartTrace` (ETW via WMI):** Returns **`AccessDenied`** for non-admin (`asInvoker`) processes. Cannot be used without elevation (and we strictly forbid admin elevation).
2. **`__InstanceCreationEvent WITHIN 0.5 WHERE TargetInstance ISA 'Win32_Process'` (WMI):** Subscribes without admin, **but** WMI implements `WITHIN 0.5` by polling inside `WmiPrvSE.exe` every 500 ms (adding COM/WMI service CPU overhead and external service dependency).
3. **Dedicated `ProtectionGuard` thread using `CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)` + read-only SCM (`OpenSCManagerW(SC_MANAGER_CONNECT)` / `OpenServiceW(SERVICE_QUERY_STATUS)` / `QueryServiceStatusEx`):**
   - Average basename scan time on 322 processes: **11.1 ms**.
   - At a **300 ms** guard interval: average detection latency **~160 ms**, worst-case **~315 ms**, full teardown + process exit well under **500–800 ms**—comfortably **1.5–5+ seconds before** EAC/BattlEye/Vanguard finishes bootstrapping and long before the game window opens!
   - **Zero `OpenProcess` handles**, zero COM/WMI fragility, zero admin privileges, and trivially testable with a 1-second **fail-closed watchdog** verifying the guard heartbeat.

---

## 6. Packaging Security Evaluation: Nuitka vs. PyInstaller (Layer 6)

| Criterion | PyInstaller (`--onedir`, `upx=False`) | Nuitka (`--standalone`) |
| --- | --- | --- |
| Windows Defender / SmartScreen on unsigned binary | Moderate–Low (one-dir avoids temp-folder dropper extraction; no UPX; still flagged as "Unknown Publisher" until signed) | Moderate–Low (native C binary, but unsigned new binaries still trigger SmartScreen & some heuristic AVs) |
| Build & CI stability with PySide6 + `windows-capture` (Rust) + `sounddevice`/`soundfile` | Proven green locally and in GitHub Actions (~65 s build) | Requires MSVC/MinGW C compilation (15–35 min CI builds), frequent hook edge-cases with PySide6-Addons + native CFFI/Rust wheels |
| Root fix for Defender/SmartScreen | **EV/OV Code Signing (SignPath Foundation)** + Microsoft Security Intelligence portal submission | Same: **Code Signing** is still required to eliminate SmartScreen warnings |

**Decision (recorded in `DECISIONS.md`):** Keep **PyInstaller one-dir with `upx=False`**, embedded `VERSIONINFO` + `asInvoker` manifest, zero obfuscation, MIT open-source repository, SignPath Foundation free open-source code signing, and click-only Microsoft Defender false-positive submission instructions (`docs/DEFENDER-SUBMISSION.md`). This achieves the highest reliability and auditability while avoiding PyInstaller's `--onefile` / UPX AV triggers.
