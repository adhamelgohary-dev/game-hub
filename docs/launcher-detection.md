# Launcher detection

## Steam

GameRewind reads the primary Steam library and the local VDF index for other library folders. Installed entries come from readable game manifests and existing installation folders. An unambiguous local executable can be used for tracking. If more than one could be the game, use **Assign executable**. Invalid or unavailable library folders are skipped while the rest of the scan continues.

## Epic Games Store

GameRewind reads local `.item` files in the Epic Games Launcher's `ProgramData` manifests directory. It uses the manifest's artifact identity to construct a fixed launcher URI and records a process target only when the manifest points to a readable `.exe` inside the detected install. Malformed or incomplete entries can be left out while the rest of the library loads. [Epic protocol activation](https://dev.epicgames.com/docs/epic-games-store/protocol-activation)

## Xbox App and Game Pass

Detection is best effort. GameRewind checks the `XboxGames` directory at the root of fixed local drives. It reads a title's `MicrosoftGame.config` at the title root or one level down in `Content`. It also queries package registrations for the current Windows user. A package is shown as a game only when it has readable GDK game metadata. Matching folder and package identities are merged into one library entry. [GDK game configuration](https://learn.microsoft.com/en-us/gaming/gdk/docs/features/common/game-config/microsoftgameconfig-overview) · [Get-AppxPackage](https://learn.microsoft.com/en-us/powershell/module/appx/get-appxpackage)

Some WindowsApps directories are inaccessible to an ordinary user, and custom install layouts, cloud titles and older game packages can go undetected. GameRewind does not request elevation or change game folder permissions. If a local game has a readable executable, use **Add game** and select it. Titles that require Xbox sign-in or special launcher activation may still need to start from the Xbox app. Network locations and links are skipped during automatic discovery.
