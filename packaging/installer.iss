#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{BCE7FA2A-7A55-487B-9BC4-2EA83958BF9A}
AppName=Game Hub
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Game Hub
DefaultGroupName=Game Hub
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
MinVersion=10.0.17763
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=GameHub-Setup
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\GameHub.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\GameHub\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
; Remove any legacy v1.0 autostart value on install/upgrade and uninstall; never create one.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "GameHub"; ValueType: none; Flags: deletevalue uninsdeletevalue dontcreatekey

[Icons]
Name: "{group}\Game Hub"; Filename: "{app}\GameHub.exe"; WorkingDir: "{app}"
Name: "{group}\Third-party notices"; Filename: "{app}\_internal\third-party\THIRD_PARTY_NOTICES.txt"

[Run]
Filename: "{app}\GameHub.exe"; Description: "Launch Game Hub"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent
