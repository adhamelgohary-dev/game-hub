# Anti-Cheat Landscape & Third-Party Feature Risk Research (Game Hub v1.1)

**Research date:** 2026-11-23  
**Purpose:** Establish evidence-based defaults and a bundled, updatable protected-games catalog for Game Hub v1.1 so players who also play competitive multiplayer games are protected from blocks, kicks, crashes, or false-positive anti-cheat flags.

> **Honesty & uncertainty note:** No commercial anti-cheat vendor publishes its complete detection heuristics or internal allowlists. Policies and enforcement behavior also change silently with game or driver updates. Where official documentation is silent or ambiguous (especially around unsigned third-party binaries combining multiple Win32 APIs), this report states the uncertainty explicitly and defaults to conservative protection (**Strict mode** or **automatic exit**).

---

## 1. Anti-Cheat Systems & Games Surveyed

### 1.1 Riot Vanguard (*Valorant*, *League of Legends*)
- **Scope & privilege:** Kernel-mode driver (`vgk.sys`, Ring 0) plus user-mode client (`vgc.exe`) and tray monitor (`VGTray`).
- **Start timing:** **At Windows boot** (driver loads at OS startup; disabling or exiting Vanguard requires a system reboot before launching protected Riot titles). Enforces Secure Boot, TPM 2.0, and HVCI/VBS on Windows 11.
- **Official stance & behavior:**
  - Riot Support explains that Vanguard monitors system integrity from boot and blocks vulnerable or incompatible third-party drivers and unsigned/tampered components (`VAN` error codes such as `VAN: INCOMPATIBLE SOFTWARE`, `VAN 7007`, `VAN 7018`, `VAN 7020`).
  - Riot allows mainstream streaming/communication tools (OBS Studio, Discord, NVIDIA App), though OBS Game Capture hooks have periodically been blocked after updates until OBS updated its signed graphics-hook binaries, pushing users to OBS Window Capture (WGC) or Display Capture.
  - Because `vgk.sys` runs at boot, even when a Riot game is not open, Vanguard can inspect handles and drivers; when *Valorant* or *League of Legends* runs, `ObRegisterCallbacks` strips invasive process handles and Vanguard aggressively scrutinizes unsigned external topmost windows, pixel-capture loops, and global hotkeys.
- **Sources:**
  - Riot Games Support — *What is Vanguard?* (`https://support-valorant.riotgames.com/hc/en-us/articles/360046160933-What-is-Vanguard`, retrieved 2026-11-23)
  - Riot Games Support — *Vanguard Restrictions / Troubleshooting VAN Errors* (`https://support-valorant.riotgames.com/hc/en-us/sections/360008365133-Vanguard`, retrieved 2026-11-23)
  - Riot Games Support — *League of Legends Vanguard FAQ* (`https://support-leagueoflegends.riotgames.com/`, retrieved 2026-11-23)

### 1.2 Easy Anti-Cheat / EAC (*Fortnite*, *Apex Legends*, *Rust*, *Elden Ring*, *Halo MCC/Infinite*, *Sea of Thieves*, *Dead by Daylight*, *The Finals*, *Fall Guys*, *Lost Ark*, *For Honor*, *War Thunder*, *Smite 2*)
- **Scope & privilege:** Kernel-mode driver (`EasyAntiCheat_EOS.sys` / `EasyAntiCheat.sys`, Ring 0) managed by Epic Online Services.
- **Start timing:** **At game launch** (unloads when the protected game closes).
- **Official stance & behavior:**
  - EAC states it collects limited technical runtime data only while a protected game is running, and protects game processes via kernel handle filtering (`ObRegisterCallbacks`) and driver/code-integrity verification.
  - Mainstream capture/overlay tools (OBS Studio with "anti-cheat compatibility hook", Discord, Steam Overlay, NVIDIA App, Xbox Game Bar) are accommodated through signed-hook compatibility or OS-level capture.
  - Unrecognized or unsigned programs that hook graphics pipelines, use suspicious topmost overlay flags, or trigger integrity rules can cause `"Game Security Violation Detected"` kicks/crashes; Epic's official support instructs players to close background overlay/capture utilities when violations occur.
- **Sources:**
  - Easy Anti-Cheat — *Official Site & Privacy / Operations* (`https://www.easy.ac/`, retrieved 2026-11-23)
  - Epic Games Support — *Troubleshooting Easy Anti-Cheat / Game Security Violation* (`https://www.epicgames.com/help/en-US/c-Category_Fortnite`, retrieved 2026-11-23)
  - OBS Project Wiki — *Game Capture Troubleshooting (Anti-Cheat Compatibility Hook)* (`https://obsproject.com/kb/game-capture-troubleshooting`, retrieved 2026-11-23)

### 1.3 BattlEye (*Fortnite* [dual with EAC], *Rainbow Six Siege* [with QB], *PUBG: BATTLEGROUNDS* [with Zakynthos], *Destiny 2*, *DayZ*, *Escape from Tarkov*, *Arma 3*)
- **Scope & privilege:** Kernel-mode driver (`BEDaisy.sys`, Ring 0) plus `BEService.exe`.
- **Start timing:** **At game launch** (driver loads when the game starts and unloads on exit).
- **Official stance & behavior:**
  - BattlEye's official FAQ explicitly states: *"No one is banned for using non-hack programs"* (citing Fraps and standard overlays), and distinguishes between **blocks/kicks** (e.g., for certain macro tools or developer-restricted tools like ReShade in *PUBG*/*Fortnite*) versus **global bans** (reserved for cheats and bypasses).
  - However, BattlEye uses kernel `ObRegisterCallbacks` to strip unauthorized process handles, blocks unsigned DLL injections and certain third-party overlay/hook mechanisms, and game publishers (*Ubisoft* with *Rainbow Six Siege* + QB anti-cheat; *KRAFTON* with *PUBG* + *Zakynthos* kernel layer) add proprietary enforcement layers on top of BattlEye.
- **Sources:**
  - BattlEye — *Official FAQ* (`https://www.battleye.com/support/faq/`, retrieved 2026-11-23)
  - Ubisoft — *Rainbow Six Siege Anti-Cheat / BattlEye* (`https://www.ubisoft.com/en-us/game/rainbow-six/siege/news-updates`, retrieved 2026-11-23)
  - KRAFTON / PUBG — *PUBG Anti-Cheat Dev Letters (BattlEye + Zakynthos)* (`https://pubg.com/en/news`, retrieved 2026-11-23)

### 1.4 Valve Anti-Cheat / VAC & Trusted Mode (*Counter-Strike 2*, *Deadlock*)
- **Scope & privilege:** **User-mode (Ring 3)** plus server-side behavioral analysis (*VAC Live* in CS2; server-authoritative / live anti-cheat in *Deadlock*). Valve has not deployed a Windows kernel driver for VAC.
- **Start timing:** **At game launch / connection to VAC-secured servers**.
- **Official stance & behavior:**
  - *Counter-Strike 2* enables **Trusted Mode** by default, blocking third-party software from injecting into the game process. Valve's support documentation warns that disabling Trusted Mode via `-allow_third_party_software` can negatively affect Trust Factor.
  - Because Trusted Mode blocks DLL injection (which breaks OBS Game Capture hooks), OBS and Valve communities specifically recommend **Window Capture using Windows Graphics Capture (WGC)** in Borderless Windowed mode, which operates at the OS compositor level without injecting into the game process.
  - *Deadlock* (Steam AppID `1422450`) uses Valve's evolving user-mode + server-side anti-cheat (not kernel-mode) and also blocks unauthorized process injection.
  - While VAC is user-mode and does not ban for non-injecting WGC or passive process enumeration, competitive players still prefer zero uninvited overlays over CS2/Deadlock matches.
- **Sources:**
  - Steam Support — *Valve Anti-Cheat (VAC) System* (`https://help.steampowered.com/en/faqs/view/571A-97DA-70E9-FF74`, legacy ref `7849-Radz-6869`, retrieved 2026-11-23)
  - Steam Support — *Counter-Strike 2 Trusted Mode* (`https://help.steampowered.com/en/faqs/view/09A0-4879-4353-EF95`, retrieved 2026-11-23)
  - OBS Project — *Capturing CS2 with Window Capture (Windows Graphics Capture)* (`https://obsproject.com/kb/game-capture-troubleshooting`, retrieved 2026-11-23)

### 1.5 Activision RICOCHET (*Call of Duty: Warzone*, *MW2*, *MW3*, *Black Ops 6* / CoD HQ)
- **Scope & privilege:** **Kernel-mode driver** (`randgrid.sys`, Ring 0) paired with server-side ML analytics and active in-game mitigations.
- **Start timing:** **At game launch** (driver runs while *Call of Duty* is active).
- **Official stance & behavior:**
  - Activision's RICOCHET FAQ confirms the PC kernel-level driver monitors background processes and applications that attempt to interact with *Call of Duty*.
  - Activision's Security and Enforcement Policy warns that unauthorized third-party software manipulating game data, overlays, or input can lead to temporary suspensions or permanent account bans across linked accounts, and support troubleshooting recommends closing background overlay/monitoring/capture tools on conflicts.
- **Sources:**
  - Activision Support — *RICOCHET Anti-Cheat FAQ* (`https://support.activision.com/articles/ricochet-anti-cheat-faq`, retrieved 2026-11-23)
  - Activision Support — *Call of Duty Security and Enforcement Policy* (`https://support.activision.com/articles/call-of-duty-security-and-enforcement-policy`, retrieved 2026-11-23)

### 1.6 EA Javelin Anticheat (formerly EA Anticheat) (*EA SPORTS FC 24/25/26*, *Battlefield 2042/V/1/6*, *Madden NFL*, *F1*)
- **Scope & privilege:** **Kernel-mode driver** (`EAAntiCheat.GameService`, Ring 0). Requires Secure Boot and TPM 2.0 on modern Windows titles.
- **Start timing:** **At game launch** (runs while the protected EA title is active).
- **Official stance & behavior:**
  - EA Help states EA Javelin Anticheat protects against kernel exploits, tampering, and unauthorized overlays/mod managers. Mainstream signed overlays (Steam, Discord, NVIDIA, AMD) are explicitly maintained for compatibility, while unknown overlays, macro utilities, or conflicting background apps routinely trigger launch blocks or error dialogs requiring background tools to be closed.
- **Sources:**
  - EA Help — *EA Javelin Anticheat on PC* (`https://help.ea.com/en/help/pc/ea-anticheat/`, retrieved 2026-11-23)

### 1.7 Other Notable Kernel & User-Mode Anti-Cheats Across Launchers
- **nProtect GameGuard** (*Helldivers 2* on Steam): **Kernel-mode**, starts at **game launch**. Historically aggressive toward unknown background processes, hotkeys, and unsigned overlays.
- **HoYoKProtect / mhyprot** (*Genshin Impact*, *Honkai: Star Rail*, *Zenless Zone Zero* on Epic / standalone): **Kernel-mode**, starts at **game launch**.
- **Anti-Cheat Expert (ACE)** (*Delta Force*, *Arena Breakout: Infinite*, *Naraka: Bladepoint*, *PUBG* secondary regions on Steam/Epic/standalone): **Kernel-mode**, starts at **game launch** (or service install).
- **Blizzard Warden / Defense Matrix** (*World of Warcraft*, *Overwatch 2*, *Diablo IV* on Battle.net / Steam): **User-mode (Ring 3)** inside the game process + server-side analytics; starts at **game launch**. Much more permissive of non-injecting utilities and mainstream overlays than Ring-0 drivers, though automation/memory reads are banned.
- **Cross-launcher coverage:** Kernel anti-cheat titles appear across **Steam** (*Apex Legends*, *Rust*, *PUBG*, *Rainbow Six Siege*, *Elden Ring*, *Call of Duty*, *EA FC*, *Helldivers 2*, *Destiny 2*, *DayZ*, *Dead by Daylight*, *Halo MCC*, *Sea of Thieves*, *The Finals*, *Battlefield 2042*, *Lost Ark*, *For Honor*, *War Thunder*, *Delta Force*, *Naraka: Bladepoint*), **Epic Games Store** (*Fortnite*, *Fall Guys*, *Genshin Impact*, *Dead by Daylight*, *Rainbow Six Siege*, *EA FC*), **Xbox / Game Pass** (*Call of Duty*, *Halo MCC/Infinite*, *Sea of Thieves*, *Rainbow Six Siege*, *Dead by Daylight*, *EA Play/EA FC/Battlefield*), **Battle.net** (*Call of Duty*), **Riot Client** (*Valorant*, *League of Legends*), **EA app** (*EA FC*, *Battlefield*, *Apex Legends*), and **Ubisoft Connect** (*Rainbow Six Siege*, *For Honor*).
- **Sources:**
  - AreWeAntiCheatYet Community Database (`https://areweanticheatyet.com/`, retrieved 2026-11-23)
  - SteamDB App Catalog (`https://steamdb.info/`, retrieved 2026-11-23)
  - Blizzard Entertainment — *Defense Matrix Updates* (`https://overwatch.blizzard.com/en-us/news/`, retrieved 2026-11-23)

---

## 2. Feature-by-Feature Risk Analysis for Game Hub

Game Hub **never** injects DLLs, hooks DirectX/Vulkan, reads or writes game process memory, requests `PROCESS_VM_READ`/`PROCESS_VM_WRITE`/`PROCESS_CREATE_THREAD`, or loads a kernel driver. Still, anti-cheat engines inspect **behavioral combinations** of user-mode APIs — especially from **unsigned or low-reputation executables** (such as a newly released PyInstaller binary).

### (a) Periodic Screenshots via Windows Graphics Capture (`Windows.Graphics.Capture`)
- **Mechanism:** Game Hub binds `IGraphicsCaptureItemInterop::CreateForWindow` to the verified foreground HWND via the official OS compositor API (the same API OBS Window Capture uses on Windows 10 1903+/11).
- **Risk profile:**
  - **Single-player / no anti-cheat:** **None / Minimal.**
  - **User-mode anti-cheat (VAC, Warden):** **Low.** WGC is explicitly the recommended non-injecting capture path for CS2 Trusted Mode.
  - **Kernel anti-cheat (Vanguard, EAC, BattlEye, Ricochet, EA Javelin, GameGuard, ACE):** **Medium–High for an unsigned app.** While WGC itself is a legitimate Windows API used by OBS and Xbox Game Bar, external **pixel-bot / color-aimbot / AI-vision cheats** also use WGC/DXGI to capture frames periodically without touching game memory. Some protected games block WGC (`SetWindowDisplayAffinity` / black frames), and an unsigned binary repeatedly opening WGC sessions against a competitive game window creates unnecessary heuristic risk.
- **Conclusion:** Disable periodic WGC screenshots completely in **Strict mode** (default for all kernel anti-cheat games).

### (b) Process Enumeration (`psutil` / `CreateToolhelp32Snapshot` / `OpenProcess`)
- **Mechanism:** Game Hub currently snapshots process basenames with `CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)` every 3 seconds, then calls `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, ...)` and `psutil.Process(pid).create_time()` **only** for shortlisted matching executables.
- **Risk profile:**
  - **Enumerating basenames via `CreateToolhelp32Snapshot` (zero handles opened to the game):** **Minimal / Safe.** Task Manager, Explorer, Discord, Steam, and hundreds of Windows utilities enumerate running process names passively without ever opening a handle to the game process.
  - **Opening a handle via `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` on a protected game:** **Low–Medium (sensitive under Ring-0 `ObRegisterCallbacks`).** Kernel anti-cheats intercept every `OpenProcess` call via `ObRegisterCallbacks`. While `PROCESS_QUERY_LIMITED_INFORMATION` grants no memory read/write rights and is often allowed or silently stripped (resulting in `ERROR_ACCESS_DENIED`), repeatedly opening handles to a protected game from an unsigned process is avoidable telemetry.
- **Conclusion:**
  - Never request write, memory-read, or debug rights on any process (hard rule).
  - For **passive protected-game detection ("forgetful case")**, match strictly by **process basename from `CreateToolhelp32Snapshot`** (or passive WMI/ETW-free basename polling at a slow interval, e.g., every 3–5 seconds) **without opening any handle to the protected game process at all**.
  - When a protected game is detected while Game Hub is open, default to **exiting Game Hub automatically** (zero residual process polling while playing).

### (c) Global Hotkeys (`RegisterHotKey`)
- **Mechanism:** Win32 `RegisterHotKey` (not `SetWindowsHookEx(WH_KEYBOARD_LL)`).
- **Risk profile:**
  - **Single-player / user-mode anti-cheat:** **Low.** `RegisterHotKey` does not install a low-level keyboard hook or inject into other processes.
  - **Kernel anti-cheat:** **Low–Medium in combination.** Alone, `RegisterHotKey` is benign (used by screenshot tools, Discord, volume controllers). Combined with an unsigned binary, topmost windows, and screen capture, global hotkeys resemble external cheat menu toggles.
- **Conclusion:** Unregister all in-game global hotkeys while in **Strict mode** (or exit Game Hub entirely).

### (d) Microphone Recording (WASAPI / PortAudio via `sounddevice`)
- **Mechanism:** Opens the default Windows audio input device only when explicitly triggered by the user.
- **Risk profile:** **Minimal / None** across all anti-cheats (identical to Discord, OBS, Windows Voice Recorder).
- **Conclusion:** Still disable in-game hotkey microphone recording in **Strict mode** (because in-game hotkeys are disabled, and notes are taken **after** the game exits), keeping the runtime footprint during protected gameplay strictly zero.

### (e) Showing Windows Over the Game (`WS_EX_TOPMOST` / Always-on-Top Cards & Popups)
- **Mechanism:** Qt `WindowStaysOnTopHint` (`WS_EX_TOPMOST`) for the Last-time card (separate top-level OS window, not an injected DX/Vulkan overlay).
- **Risk profile:**
  - **Single-player / no anti-cheat:** **None** (only fullscreen-exclusive Z-order hiding).
  - **User-mode anti-cheat (VAC, Warden):** **Low** (can steal focus or disrupt fullscreen play).
  - **Kernel anti-cheat (Vanguard, EAC, BattlEye, Ricochet, EA Javelin, GameGuard):** **Medium–High.** External ESP/radar cheats rely heavily on `WS_EX_TOPMOST` windows floating over borderless-windowed games. Anti-cheats actively scan topmost windows overlapping the game rect and may block, minimize, kick, or flag unknown unsigned topmost windows.
- **Conclusion:** Never show `WS_EX_TOPMOST` cards or dialogs over a running protected game. Show the Last-time card **before** launching the game, show the note prompt **after** the game exits, and for the "Ask me" forgetful-case prompt use a standard passive **Windows toast/system notification** (never a topmost Qt window over the game).

---

## 3. Comparison with Known Allowed Applications

| Application | Capture / Overlay Method | Why Anti-Cheats Allow It | Key Difference vs. Game Hub v1.0 |
| --- | --- | --- | --- |
| **OBS Studio** | Signed DirectX/Vulkan hook (with EAC/BattlEye compatibility) or WGC Window Capture | EV/OV code-signed, widely whitelisted by EAC, BattlEye, Riot, EA; updates hooks promptly when anti-cheats change | Game Hub v1.0 was unsigned and used periodic automated WGC + `WS_EX_TOPMOST` |
| **Discord** | Signed overlay + process name scanning for Rich Presence | Digitally signed, vendor-whitelisted by publishers | Whitelisted publisher identity; Game Hub avoids injecting any overlay |
| **Xbox Game Bar** | Built-in signed Microsoft OS component (WGC + Game DVR) | First-party Microsoft Windows component | First-party OS trust |
| **NVIDIA App / GeForce Experience** | Signed GPU driver-level capture (NVFBC/NVENC) & overlay | Signed NVIDIA driver & vendor-whitelisted | First-party GPU vendor trust |
| **Steam Overlay** | Signed Valve `GameOverlayRenderer64.dll` | First-party launcher explicitly whitelisted by game publishers | First-party launcher trust |

**Takeaway:** Even though Game Hub is *less invasive* than OBS Game Capture or Discord Overlay (zero injection, zero hooks, zero memory reads), an **unsigned open-source app** does not enjoy vendor allowlisting. Combining **(1) zero background process when closed**, **(2) Strict mode / auto-exit for protected games**, and **(3) free open-source code signing via SignPath Foundation (Part E)** eliminates both the technical risk and the trust gap.

---

## 4. Documented Bans, Kicks, and Warnings for Similar Tools

- **Confirmed non-ban policy statements:** BattlEye's official FAQ explicitly states non-cheat overlays and capture tools do not result in bans, though individual tools may be blocked or kicked. Valve VAC bans target known cheat signatures and memory/code tampering, not WGC Window Capture.
- **Documented blocks / kicks / crashes:**
  - *Valorant* / Riot Vanguard (`VAN` errors) routinely blocks unsigned/incompatible background drivers and utilities, and periodically breaks OBS Game Capture until updated.
  - *Easy Anti-Cheat* (`Game Security Violation Detected`) and *EA Javelin Anticheat* frequently refuse to launch or kick players when unrecognized overlay, RGB, macro, or screen-hook tools run concurrently.
  - *CS2* Trusted Mode silently blocks unsigned DLL hooks (preventing OBS Game Capture) and lowers Trust Factor if `-allow_third_party_software` is used.
- **Community reports of false-positive flags / uncertainty:** Across Reddit and publisher forums, players occasionally report temporary kicks, shadow-bans (*Call of Duty* Ricochet), or automated bans when running unsigned Python/AutoHotkey/screen-capture/overlay scripts alongside *Valorant*, *Call of Duty*, *Rust*, or *PUBG*—even when those scripts were intended for accessibility or personal stats. Because publishers do not disclose exact ban reasons, **causation cannot be proven with 100% certainty**, so Game Hub treats **zero activity during protected games** (Strict mode or full exit) as the only truly safe default.

---

## 5. Summary Risk Matrix & Recommended Defaults

| Game | Launcher(s) | Anti-Cheat | Level & Start | (a) WGC Shots | (b) Process Enum | (c) Global Hotkeys | (d) Mic Record | (e) Topmost Window | Default Mode |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Valorant** | Riot Client | Riot Vanguard | Kernel · **Boot** | High | Medium (handle) / Low (basename) | Medium | Minimal | High | **Strict** (Auto-exit on external launch) |
| **League of Legends** | Riot Client | Riot Vanguard | Kernel · **Boot** | High | Medium / Low | Medium | Minimal | High | **Strict** (Auto-exit on external launch) |
| **Fortnite** | Epic | EAC + BattlEye | Kernel · Launch | Medium–High | Low–Medium | Low–Medium | Minimal | Medium–High | **Strict** (Auto-exit on external launch) |
| **Apex Legends** | Steam, EA app | Easy Anti-Cheat | Kernel · Launch | Medium–High | Low–Medium | Low–Medium | Minimal | Medium–High | **Strict** (Auto-exit on external launch) |
| **Call of Duty (Warzone / MW / BO6)** | Steam, Battle.net, Xbox | RICOCHET | Kernel · Launch | High | Medium / Low | Medium | Minimal | High | **Strict** (Auto-exit on external launch) |
| **Rainbow Six Siege** | Steam, Ubisoft, Epic, Xbox | BattlEye + QB | Kernel · Launch | Medium–High | Low–Medium | Low–Medium | Minimal | Medium–High | **Strict** (Auto-exit on external launch) |
| **PUBG: BATTLEGROUNDS** | Steam, Epic | BattlEye + Zakynthos | Kernel · Launch | High | Medium / Low | Medium | Minimal | High | **Strict** (Auto-exit on external launch) |
| **Rust** | Steam | Easy Anti-Cheat | Kernel · Launch | Medium–High | Low–Medium | Low–Medium | Minimal | Medium–High | **Strict** (Auto-exit on external launch) |
| **EA SPORTS FC (24/25/26)** | Steam, EA app, Epic, Xbox | EA Javelin Anticheat | Kernel · Launch | Medium–High | Low–Medium | Low–Medium | Minimal | Medium–High | **Strict** (Auto-exit on external launch) |
| **Battlefield (2042/V/1/6)** | Steam, EA app, Epic, Xbox | EA Javelin Anticheat | Kernel · Launch | Medium–High | Low–Medium | Low–Medium | Minimal | Medium–High | **Strict** (Auto-exit on external launch) |
| **Helldivers 2** | Steam | nProtect GameGuard | Kernel · Launch | High | Medium / Low | Medium | Minimal | High | **Strict** (Auto-exit on external launch) |
| **Elden Ring** | Steam | Easy Anti-Cheat | Kernel · Launch | Medium | Low–Medium | Low–Medium | Minimal | Medium | **Strict** (user may switch to Full if playing offline without EAC) |
| **Halo MCC / Infinite** | Steam, Xbox | Easy Anti-Cheat | Kernel · Launch | Medium | Low–Medium | Low–Medium | Minimal | Medium | **Strict** (Auto-exit on external launch) |
| **Sea of Thieves** | Steam, Xbox | Easy Anti-Cheat | Kernel · Launch | Medium | Low–Medium | Low–Medium | Minimal | Medium | **Strict** (Auto-exit on external launch) |
| **Destiny 2 / DayZ / Tarkov / Arma 3** | Steam, Epic, Standalone | BattlEye | Kernel · Launch | Medium–High | Low–Medium | Low–Medium | Minimal | Medium–High | **Strict** (Auto-exit on external launch) |
| **Dead by Daylight / The Finals / Lost Ark / For Honor / Fall Guys / War Thunder** | Steam, Epic, Xbox, Ubisoft | Easy Anti-Cheat | Kernel · Launch | Medium–High | Low–Medium | Low–Medium | Minimal | Medium–High | **Strict** (Auto-exit on external launch) |
| **Genshin Impact / Honkai: Star Rail / ZZZ** | Epic, Standalone | HoYoKProtect | Kernel · Launch | Medium–High | Low–Medium | Low–Medium | Minimal | Medium–High | **Strict** (Auto-exit on external launch) |
| **Delta Force / Naraka / Arena Breakout** | Steam, Epic, Standalone | ACE (Anti-Cheat Expert) | Kernel · Launch | High | Medium / Low | Medium | Minimal | High | **Strict** (Auto-exit on external launch) |
| **Counter-Strike 2** | Steam | VAC + VAC Live + Trusted Mode | **User-mode** · Launch | Low (WGC safe) | Low | Low | Minimal | Low–Medium (focus/UX) | **Strict** (recommended default for competitive multiplayer; user can switch to Full) |
| **Deadlock** | Steam | Valve Anti-Cheat | **User-mode** · Launch | Low | Low | Low | Minimal | Low–Medium | **Strict** (recommended default; user can switch to Full) |
| **Overwatch 2 / World of Warcraft** | Battle.net, Steam | Blizzard Warden | **User-mode** · Launch | Low | Low | Low | Minimal | Low–Medium | **Strict** (recommended default; user can switch to Full) |
| **Single-player / Offline games (no anti-cheat)** | Steam, Epic, Xbox, Manual | None | None | None | Minimal | None | None | None | **Full** (v1 features) |

---

## 6. Bundled, Updatable Protected-Games Data File

Game Hub stores its protected-games list in a versioned JSON data file (never hardcoded in Python logic):
- **Bundled location:** `gamehub/core/protection/protected_games.json` (included in PyInstaller bundle under `_internal/gamehub/core/protection/protected_games.json`).
- **User override / update location:** `%LOCALAPPDATA%\GameHub\protected_games_override.json` (optional local JSON file in the user's data root so the list can be updated without waiting for an app release, while keeping v1.1 strictly offline).
- **Schema:**
  - `schema_version`: `1`
  - `updated_at`: ISO date string
  - `games`: array of entries with `id`, `name`, `anti_cheat`, `privilege` (`kernel` | `user`), `starts_at` (`boot` | `launch`), `default_mode` (`strict`), `steam_app_ids` (list of strings), `epic_app_names` (list of strings), `xbox_package_prefixes` (list of strings), and `exe_names` (lowercase executable basenames, e.g. `valorant-win64-shipping.exe`, `fortniteclient-win64-shipping.exe`, `r5apex.exe`, `cs2.exe`, `cod.exe`, `rainbowsix.exe`, `tslgame.exe`, `rustclient.exe`, `fc25.exe`, `fc26.exe`, `league of legends.exe`, `helldivers2.exe`, `eldenring.exe`, etc.).
- **Matching rule:**
  1. For library entries: match by Steam AppID, Epic AppName, Xbox package prefix, or target executable basename.
  2. For the passive "forgetful case" detector: match **only** by process basename from `CreateToolhelp32Snapshot` — **never** call `OpenProcess` on a protected game just to detect it!
